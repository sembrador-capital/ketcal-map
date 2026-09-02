# Ketcal — mapa interactivo

Mapa Mapbox GL del predio **Ketcal** (cítricos, Región de Coquimbo), operado por
Sembrador Capital. Sitio estático: un solo `index.html`, los JSON que genera el
pipeline, y una consulta en vivo a DropControl.

> **La temporada de Ketcal es el AÑO CALENDARIO**, del 1 de enero al 31 de
> diciembre. No es julio-junio como en San Gerardo, y como este mapa se
> construyó replicando el de allá, es el error más fácil de reintroducir.
> Rige en las dos pestañas con eje temporal: el `?temporada=YYYY` del Worker de
> riego y el `season_of()` del pipeline de Ceres.

Réplica del mapa de [San Gerardo](../san-gerardo): mismo token de Mapbox, mismo
sistema de diseño (tokens `:root`, chrome, paneles, leyendas, i18n es/en), misma
arquitectura de un archivo + datos externos.

---

## Arrancarlo

El mapa hace `fetch('./geo_data.json')`. Abierto con `file://` CORS lo bloquea y
se ve un mapa vacío: **hay que servirlo por HTTP.**

```bash
python -m http.server 8010
```

→ <http://localhost:8010>

---

## La estructura del predio

Esto es lo primero que hay que entender, porque manda sobre todo el resto.

Ketcal tiene **dos particiones distintas del mismo terreno**, no una jerarquía:

| Partición | Unidades | De dónde sale |
|---|---|---|
| Riego | 5 equipos → 28 sectores | `Ketcal KMZ.kmz`, carpeta *Equipos y Sectores de Riego* |
| Agronómica | 30 cuarteles (14 Lim, 12 Nar, 4 Man) | `Ketcal KMZ.kmz`, carpeta *Cuarteles* |

Un sector riega trozos de varios cuarteles y un cuartel recibe agua de varios
sectores. La intersección de las dos es la **ubicación `E#-S#-C#`** — 53 en
total — y ésa es la clave con la que la base de laboratorio referencia el
terreno (`Clave_Mapa` en el Excel).

Por eso el mapa tiene **cuatro niveles** y no dos, y por eso la pestaña
Nutrición pinta por ubicación: es la única unidad donde el dato de laboratorio
está realmente medido. Sector, cuartel y equipo son promedios de las muestras
que caen dentro, y la leyenda lo dice.

El cruce **no viene en el KMZ**: lo calcula `tools/kmz_to_geojson.py` por
intersección geométrica, con un umbral de solape (`MIN_OVERLAP = 3 %`) para no
contar bordes de digitalización como si fueran riego real.

> **Verificación que ya pasó:** las 50 ubicaciones que declara
> `Maestro_Ubicaciones` existen todas entre las 53 que produce la intersección.
> Las 3 restantes (`E1-S4-C1`, `E4-S2-C9`, `E4-S7-C8`) son solapes que el maestro
> no registra. Las hectáreas calculadas por geometría coinciden con las
> declaradas en el KMZ dentro del 1 % en los 30 cuarteles.

---

## Los archivos

```
index.html                  ← TODO el mapa: HTML + CSS + JS en un archivo
geo_data.json               ← geometría (generado)
nutricion_data.json         ← análisis de suelo y foliares (generado)
ceres_data.json             ← vuelos de Ceres Imaging (generado)
umbrales_nutricion.json     ← umbrales agronómicos — SE EDITA A MANO
ceres_predio.json           ← identificadores de Ketcal en Ceres (descubierto)
data-version.json           ← cache-busting por dataset

tools/kmz_to_geojson.py     ← Ketcal KMZ.kmz  → geo_data.json
tools/build_nutricion.py    ← Excel + umbrales → nutricion_data.json
tools/fetch_ceres.py        ← API de Ceres    → ceres_data.json
.github/workflows/ceres.yml ← refresco semanal de Ceres

(Riego no genera archivo: se consulta en vivo. Ver más abajo.)

Ketcal KMZ.kmz                                       ← insumo
Base_Datos_Suelos_Foliares_Ketcal_SEMBRADOR_v2.xlsx  ← insumo
AGQ Labs …/  Laboquim …/  Analisis Suelos AgroLab/   ← informes de origen (PDF)
```

### Regenerar los datos

```bash
python tools/kmz_to_geojson.py
python tools/build_nutricion.py
python tools/fetch_ceres.py            # incremental; --full para rehacer todo
```

Los dos son idempotentes, imprimen un resumen y **listan sus incidencias** en
vez de corregirlas en silencio. `nutricion_data.json` incluye esas incidencias
en `issues[]`. Después de regenerar, subir la clave correspondiente de
`data-version.json`.

Dependencias externas: `shapely` (geometría), `openpyxl` (Excel) y `requests`
(Ceres).

---

## Los umbrales

`umbrales_nutricion.json` es la **única** fuente de los cortes que pintan
Nutrición. El mapa no calcula ninguno por su cuenta y el script tampoco inventa.

Cada entrada declara su procedencia, y eso llega hasta la leyenda:

| `fuente` | Chip | Qué significa |
|---|---|---|
| `laboquim` | `lab.` | Rango impreso en el propio informe del laboratorio. |
| `referencia` | `ref.` | Valor de referencia general para cítricos. **Pendiente de validación por agronomía.** |
| *(sin entrada)* | `rel.` | Sin umbral: se pinta por cuartiles del propio predio y la leyenda avisa que indica alto/bajo relativo, no cumplimiento. |

Hoy: **84 parámetros mapeables**, 58 con umbral (10 de laboratorio, el resto de
referencia) y el resto en escala relativa.

**Lo que hay que revisar con agronomía** son las entradas `referencia`: todos
los umbrales de suelo, salinidad y solución de suelo, más S, Mo, Na y Cl
foliares. Cambiarlos es editar el JSON y volver a correr
`tools/build_nutricion.py`; no hay que tocar ni el script ni el mapa.

La escala relativa es deliberadamente morada, no verde/rojo: un umbral inventado
se lee igual que uno validado y hace tomar decisiones equivocadas.

---

## El layout, igual que San Gerardo

El reparto de controles se copia del mapa de San Gerardo, verificado contra el
sitio publicado:

| Pestañas | Controles |
|---|---|
| Vista general, Nutrición | barra superior centrada (`.foliar-controls`) |
| Riego, Ceres | **panel lateral derecho** (`.riego-controls`, `.ceres-controls`) |

El panel derecho tiene header con título en mayúsculas y un subtítulo que dice
de dónde sale el dato ("Datos en vivo desde DropControl", "Vuelos de Ceres
Imaging sobre el predio"), y un cuerpo con los controles apilados más
**secciones colapsables** debajo: en Ceres, *Cambios de clase* y *Ranking del
vuelo*; en Riego, *Ranking del periodo*.

Que el ranking viva en el panel y no en la ficha de una unidad es deliberado: es
lo que se mira **antes** de elegir una unidad, no después.

Al hacer clic en una unidad se abre además `#pvSide`, la columna de detalle a
todo el alto, y el panel de pestaña se corre a su izquierda.

El selector de vuelo de Ceres es un **stepper** (`‹ fecha ›`) y no un
desplegable: con 28 vuelos, avanzar a la fecha siguiente —el gesto frecuente al
comparar— costaba tres acciones con un `<select>`. Para saltar a un vuelo lejano
hay un modal con los 28 agrupados por temporada.

---

## Convenciones (heredadas de San Gerardo, no negociables)

1. **Ningún literal de color fuera de `:root`.** En CSS `var(--token)`, en JS
   `SEM('--token')`. Colores nuevos se declaran como tokens con un comentario.
2. **Ningún `z-index` fuera de la escala `--z-*`.**
3. **Todo texto visible en español e inglés**, vía `t()` o `data-i18n`.
4. **Un solo archivo.** No separar CSS ni JS.
5. **Los datos van en JSON externo** cargado con `loadDataset()`.
6. Paleta de marca (`--sem-*`) para el chrome, escalas propias (`--dat-*`) para
   los datos.

Chequeo rápido de 1 y 2 — las dos líneas tienen que dar cero:

```bash
python -c "import re,pathlib; s=pathlib.Path('index.html').read_text(encoding='utf-8'); r=[m.span() for m in re.finditer(r':root\s*\{[^}]*\}',s)]; print(len([m for m in re.finditer(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)',s) if not any(a<=m.start()<b for a,b in r)]))"
```

`index.html` pesa ~230 KB / ~4.300 líneas, de las cuales ~2.100 son el sistema de
diseño copiado de San Gerardo. **No lo leas completo**: ubicá la sección con
`grep -n` y leé sólo ese rango.

---

## Estado

**Listo**

- **Vista general** — cuatro niveles (equipo / sector / cuartel / ubicación),
  ocho criterios de color (equipo, especie, variedad, superficie, caudal/ha, año
  de plantación, portainjerto, análisis disponibles), capas de válvulas (150),
  pozos (3) y etiquetas, buscador, tooltip, ficha lateral con el cruce
  sector↔cuartel navegable.
- **Nutrición** — subpestañas foliares / suelo, 4 matrices mapeables, 84
  parámetros, 10 campañas de muestreo, selector de profundidad para las matrices
  que la tienen, pintado por banda de umbral, leyenda con rangos y conteos,
  ranking de peor a mejor, series de tiempo por parámetro con las bandas de
  fondo, y las 13 calicatas del estudio 2018 como capa de puntos con su perfil
  físico y químico.
- **Riego** — consumo por sector con calendario de días / meses / temporadas,
  en vivo desde DropControl. Ver la sección de abajo.
- **Ceres Imaging** — 28 vuelos aéreos entre dic-2022 y abr-2026, 5 indicadores,
  en los tres niveles nativos, más la capa por árbol. Ver la sección de abajo.

- **Comparador A/B** de dos vuelos lado a lado (`mapbox-gl-compare`). El
  indicador y el nivel valen para los dos lados; lo que se compara es la fecha.
- **Capa por árbol** en Ceres (por indicador) y en Vista general (por variedad).
- **Calendario de riego** por días, meses y temporadas.

- **Capa de celdas** (1.766 celdas de 1.142 m²) con su histograma de reparto.
- **Comparación entre temporadas** en el panel de Ceres.

**Pendiente**

- **Datos de riego.** El calendario funciona, pero DropControl devuelve cero
  eventos en todo periodo probado, incluidas dos temporadas completas. Ver abajo.
- **Comparador A/B para la capa de celdas y la de árboles.** Hoy el comparador
  pinta los polígonos de los dos lados; las capas vectoriales viven sólo en el
  lado A.

---

## Riego: DropControl vía Cloudflare Worker

A diferencia de las otras pestañas, Riego **no lee un JSON del repo**. Consulta
en vivo un Worker de Cloudflare:

```
https://ketcal-riego.rpina.workers.dev
```

Sin barra final y sin `/exec`: responde en la raíz.

El Worker habla con la API de DropControl del lado del servidor. **Ese es el
punto**: la credencial vive en el Worker y nunca llega al navegador, así que el
sitio puede ser público y estar al día sin un workflow de CI.

> **Migración desde Apps Script.** Antes esto era un Google Apps Script; se
> reescribió como Worker al perderse el acceso a esa cuenta de Google. El JSON
> de respuesta es idéntico —mismos campos, fechas en `dd/MM/yyyy`— así que el
> renderizado no cambió, sólo la URL.
>
> Lo que sí cambió es que **el Worker devuelve datos.** El Apps Script
> respondía cero eventos en todo periodo, incluidas temporadas completas, y eso
> había quedado documentado acá como un problema a investigar del lado de
> DropControl. Era del Apps Script: el Worker devuelve 27 eventos y 10.762 m³
> en la última semana, y 1.607 eventos en la temporada 2026.

### Parámetros

Verificados contra el Worker real. Cada modo del calendario usa el que le
corresponde, porque `?mes=` y `?temporada=` resuelven el periodo de **una sola
llamada** en vez de armarlo con un rango:

| Modo | Parámetro | Nota |
|---|---|---|
| — | *(ninguno)* | última semana |
| Días | `?desde=YYYY-MM-DD&hasta=…` | rango arbitrario |
| Meses | `?mes=YYYY-MM` | **`MM/YYYY` devuelve NaN** |
| Temporadas | `?temporada=YYYY` | año calendario, 1-ene a 31-dic |

El Worker echoa en `consulta` el periodo que resolvió, así que el mapa compara
lo pedido contra lo devuelto y avisa si no coinciden, en vez de mostrar una
ventana bajo el rótulo de otra.

> Con el Apps Script esta comprobación necesitaba un sondeo aparte: su consulta
> por defecto eran los últimos 7 días, **exactamente** la ventana que devolvía
> cuando no filtraba, así que comparar pedido contra devuelto daba un falso
> positivo. Con `?mes=` y `?temporada=` eso no puede pasar y el sondeo se
> eliminó.

### La temporada

`?temporada=2026` es **el año calendario completo**. Las disponibles son 2022 a
2026, y la navegación no baja de 2022 porque DropControl no tiene dato antes y
una temporada vacía se lee como "no se riega".

### Los eventos

Ahora que el backend devuelve eventos, la ficha del sector los lista de verdad
en vez de volcar sus campos genéricamente. La forma es:

```
fecha "25/08/2026"  hora_inicio "06:30"  hora_fin "09:30"
duracion_hrs 3  m3 474.9  mm 6.4  m3_ha 61.4
status "Executed OK" | "Stopped by User" | "Executed with failure"
dias_hasta_siguiente 2 | null
```

El `status` es lo más accionable del evento —un riego cortado o fallado es lo
que hay que ir a mirar— y era justo lo que el volcado genérico enterraba entre
las otras ocho claves. Va con color de estado y sólo se nombra cuando **no** es
`Executed OK`, para que el ojo caiga en la excepción.

---

## Antes de publicar

El repositorio todavía **no está inicializado como git** en local. Al hacerlo,
tener en cuenta que si va a GitHub Pages como el de San Gerardo, queda público
**junto con los insumos**: el Excel de la base y los PDF de AGQ, Laboquim y
AgroLab, que hoy están en la raíz. Si eso no corresponde, moverlos fuera del
repo y apuntar los scripts con `--xlsx` / `--kmz`.


---

## Ceres Imaging

`tools/fetch_ceres.py` es una adaptación de
`../san-gerardo/tools/fetch_ceres.py`. Toda la lógica de API, políticas de
umbrales, etiquetado de bandas, deltas y cumplimiento viene de ahí sin cambios:
es código verificado contra la cuenta real. Lo propio de Ketcal es el bloque de
identificadores y el paso de dos niveles a tres.

### La credencial

Token DRF permanente, leído en este orden:

1. Variable de entorno `CERES_TOKEN` — lo que usa CI (`secrets.CERES_TOKEN`).
2. Archivo `.ceres_token` en la raíz — conveniencia para correr en local.

`.ceres_token` está en `.gitignore`. **Este repo es público: el token no va en
ningún archivo rastreado, ni en un log, ni en un mensaje de error.** Para
comprobar que la credencial sirve sin descargar nada:

```bash
python tools/fetch_ceres.py --check-token
```

Describe la *forma* del token (largo, espacios, prefijo) sin imprimir su valor,
que es lo que sirve para depurar un secret mal pegado.

### Los identificadores

`ceres_predio.json` los guarda y `--discover` los encuentra. Cómo se llegó a
ellos, todo verificado contra la cuenta:

| Qué | Valor |
|---|---|
| user_id | `7868` (es de la cuenta, no del predio) |
| Cliente | `4558` — **no** el 4527 de San Gerardo |
| Predio | `Ketcal`, farm id `6311` |
| admin_group | `CFF\|4558.6311` |

El camino no es obvio: `/fields/` lista los 5 campos de Ketcal con
`customer=4558` y un `farm` que es un **UUID**, pero el `admin_group` usa el id
**numérico** del predio. `/farms/?customer=4558` cruza los dos
(`legacy_id` → `id`). Si mañana hay que rehacerlo:

```bash
python tools/fetch_ceres.py --discover
```

Es de solo lectura e imprime lo que encuentra para revisarlo antes de confiar.

### Los tres niveles

Ketcal tiene **tres grillas cargadas** y las tres son agregados nativos de Ceres
sobre los píxeles. Ninguna se deriva de otra:

| Nivel | `grid_type_id` | Unidades | `block_name` en Ceres |
|---|---|---|---|
| Equipo | 18 | 5 | `equipo 3 naranjos` |
| Sector | 7 | 28 | `E1 - S2` |
| Cuartel | 11 | 30 | `Naranjos- C12` |

**Que el cuartel sea dato medido y no un promedio de sectores es lo que permite
cruzar Ceres con Nutrición**, cuyos análisis foliares se toman por cuartel.

Los tres formatos de `block_name` son distintos entre sí y **ninguno coincide
con las claves del repo**, así que `unit_key()` normaliza los tres. Verificado
contra el vuelo `2026.16.A`: las 63 claves (28+5+30) mapean sin faltantes ni
sobrantes contra `geo_data.json`.

### El predio creció por etapas

Este es el hecho que manda sobre el diseño de la pestaña, como en San Gerardo lo
manda que sólo haya vuelos de noviembre a marzo.

```
2022-02 a 2022-10   0 unidades    Ceres voló, pero no había grilla cargada
2022-12 a 2023-03   2-3 equipos   limoneros (E1, E2) y mandarinos (E5)
2023-08             4 equipos     aparece E3 (naranjos, creado ago-2023)
2025-01             5 equipos     aparece E4 (creado nov-2023)
2025-03 en adelante 5 / 28 / 30   completo
```

De los 32 vuelos de la API, **4 no traen ninguna unidad** y se omiten del JSON
(quedan registrados en `flights_omitidos`). De los 28 restantes, **sólo 9 cubren
el predio completo.**

Por eso cada vuelo lleva su `coverage` por nivel, con tres estados que el mapa
pinta distinto:

- `no_existia` — nunca apareció hasta esa fecha: **no estaba plantado.** Va en
  beige, no en gris, y la leyenda lo explica.
- `sin_dato` — ya había aparecido antes y en este vuelo no viene. Eso sí es una
  anomalía, y el script la advierte.
- el resto — tiene valor.

Sin esa distinción, la mitad del histórico se vería como "sin dato" cuando el
cuartel simplemente no existía.

### Los umbrales

Cada indicador declara cómo se clasifica, y eso llega a la leyenda:

| Indicador | Clases | Origen |
|---|---|---|
| Estrés hídrico | 4 | cortes publicados por Ceres |
| Estrés acumulado | 4 | los mismos: es el promedio de temporada del anterior |
| NDVI absoluto | 9 | definidos por agronomía |
| NDVI promedio temporada | 9 | los mismos |
| Clorofila | 4 | **relativas a cada vuelo** |

> **Los cortes de NDVI venían de nogal.** Se verificó si discriminan en cítricos,
> que son de hoja perenne y mantienen NDVI alto todo el año: en el vuelo de
> abr-2026 los sectores van de 0,519 a 0,852 con mediana 0,706, y **8 de las 9
> clases están pobladas**. La escalera sirve, y sirve porque la plantación es
> joven y el dosel está en formación. Conviene volver a mirarlo en un par de
> temporadas: si se apelotona arriba, hay dos salidas y las dos se hacen editando
> `ceres_thresholds.json`, sin tocar código — cortes propios para cítricos, o
> `"bands_policy": "relative"`.

En la clorofila **no se habla de cumplimiento**: por construcción la mitad de las
unidades cae en la mitad mejor, así que un porcentaje se leería como veredicto
agronómico cuando sólo dice "sobre la mediana del vuelo". Ahí la métrica informa
la peor clase, que sí es accionable.

El color no declara tokens nuevos: los indicadores tienen entre 4 y 9 clases, así
que se interpola sobre las anclas `--dat-st-*` por **severidad** de la banda
(0 = mejor). Con 4 clases cae exacto sobre las anclas.

### La capa por árbol

Ketcal tiene **460 overlays `tree_data`** y 22 de `tree_count` — más que San
Gerardo. El JSON trae el catálogo de los 334 que calzan con un vuelo, indexados
por vuelo e indicador.

El tiler de Ceres (`tiler.ceresimaging.net`) es **público y manda CORS abierto**,
así que el mapa consume los MVT directo y no hace falta pre-extraer nada. Eso
importa por seguridad: inyectar el token con `transformRequest` se lo entregaría
a cualquier visitante de un sitio público.

Son ~230.000 árboles, así que la capa se agrega **bajo demanda** al pulsar *Ver
por árbol*, nunca en el load inicial, y sólo se ve desde **z≥15**: más abajo es
un manchón ilegible. Cada árbol trae `tree_id`, `value` y `varietal`.

Dos indicadores —*Estrés acumulado* y *NDVI promedio temporada*— **no tienen
raster por árbol**: son promedios de temporada derivados. El botón se deshabilita
solo al elegirlos y explica por qué, y si la capa estaba encendida se apaga en
vez de quedar pintada con los valores del indicador anterior.

Los cortes de color del árbol son los **del nivel**, y la leyenda lo declara: las
clases por árbol propias requieren la estadística que sólo calcula `--extras`.

### Lo que no se baja por defecto

`--extras` habilita dos cosas que decodifican miles de tiles: la **estadística**
por árbol (clases relativas sobre la distribución real de árboles y conteo de
variedades) y la **grilla de celdas**. Está apagado porque con 28 vuelos esa
etapa pasó los 30 minutos sin terminar, y hasta que no termina **no escribe
nada**: se perdían los vuelos ya descargados. El workflow tampoco lo usa, porque
su timeout es de 20 min.

Ojo con la distinción: el **catálogo** de árboles sí se genera siempre —es sólo
indexar ids— y es lo único que el mapa necesita para pintarlos.

### Advertencias que quedan

Una corrida limpia deja ~40, y todas dicen algo:

- **Paginación del catálogo de overlays** (3): lee ~1.377 de 1.440. Con cientos
  de fechas empatadas la paginación de Ceres no es estable. Afecta al catálogo de
  imágenes, no a los umbrales (con un overlay por indicador alcanza).
- **`2023.36.A` (2023-09-07) pierde E3** (3): ese vuelo no trae los naranjos, que
  sí están el 11-ago y el 31-oct. **Es una anomalía real, no crecimiento del
  predio.** Vale preguntárselo a Ceres.
- **Cobertura parcial de imágenes** (~34): el mismo crecimiento por etapas, en el
  catálogo de imágenes. Son informativas.


---

## El comparador A/B

Sólo en Ceres: es la única pestaña con un histórico denso donde comparar dos
fechas lado a lado responde algo que una sola no responde.

El indicador y el nivel son ajustes de **vista** y valen para los dos lados; lo
que se compara es el **vuelo**, que es el eje con dato estacional. Cada lado
tiene su propio stepper, y el chip de vigencia pasa a decir
`Comparando 9 mar 2026 → 15 abr 2026`.

El lado B arranca en el penúltimo vuelo, que es la comparación que se quiere el
90 % de las veces. Salir de la pestaña apaga el comparador en vez de dejar medio
mapa pintado con un vuelo que ya no se está mirando.

Lo único que hubo que cambiar del resto del mapa fue `addLayers()`, que pasó a
recibir la instancia: era lo único que impedía tener dos mapas.

---

## La capa por árbol

Ketcal tiene **460 overlays `tree_data`** y 22 de `tree_count` — más que San
Gerardo. El JSON trae el catálogo de los 334 que calzan con un vuelo, indexados
por vuelo e indicador, y el **catálogo de variedades** con sus conteos:

| Variedad | Árboles |
|---|---|
| Cara Cara | 153.837 |
| Eureka | 26.713 |
| Fino | 21.121 |
| Tango | 18.378 |
| Messina-Fino | 15.326 |
| Eureka-Messina-Fino | 14.320 |
| Fino-Eureka | 8.325 |

Los compuestos (`Messina-Fino`) son cuarteles con más de una variedad donde
Ceres no separa el árbol individual.

La capa la usan **dos pestañas** y el modo se deduce de la activa, no de un
estado global, así ninguna puede dejar a la otra pintando lo que no corresponde:

- **Ceres** la pinta por indicador, con las mismas bandas del nivel. La leyenda
  lo declara: las clases propias del árbol requieren la estadística que sólo
  calcula `--extras`.
- **Vista general** la pinta por variedad, con los tokens categóricos de equipo.
  Con las variedades encendidas se ocultan los polígonos: son 230.000 círculos
  de 2 px y cualquier capa encima compite con ellos.

Parámetros calibrados, tomados de San Gerardo tal cual:

```
minzoom capa      13        más abajo son 230.000 puntos encimados
zoom al encender  14.2
maxzoom source    18
radio             z13 0,5 → z18 6,5   (más gruesa con el filtro puesto)
opacidad          0,92
borde             0 en z16 → 0,4 en z18
color             ['step', ['to-number', ['get','value']], …]
```

**"Sólo los que no están en la mejor clase"** es el botón que hace útil la capa:
con estrés hídrico, 24.284 árboles pasan a 14.009 al filtrar. Con NDVI el efecto
es mucho más marcado, porque casi todo el predio cae en la clase alta.

Hay árboles para **water_stress, absolute_ndvi y chlorophyll_class**, los tres en
los 28 vuelos. *Estrés acumulado* y *NDVI promedio temporada* no tienen: son
promedios de temporada derivados. El botón se deshabilita solo y dice por qué.

Dos detalles que hubo que resolver y conviene no volver a romper:

- Los ids de las capas vivas se guardan en una lista propia y **no** se deducen
  de `getStyle()`: esa devuelve una serialización que no refleja los
  `addLayer`/`removeLayer` del mismo tick, y leer el filtro justo después daba
  `null`.
- La capa se reconstruye sólo cuando cambia algo que la afecta (una firma de
  pestaña + vuelo + indicador + nivel + filtro). Sin ese guardia, cada repintado
  volvía a crear cinco sources vectoriales y a pedir todos los tiles.


---

## La capa de celdas

`grid_type_id` 26 parte el predio en **1.766 celdas de 1.142 m²** y responde lo
que el polígono no puede: **dónde, dentro del cuartel, está el problema.** Un
cuartel promediado en "Estrés bajo" puede tener media hectárea en crítico y el
promedio lo esconde.

Sólo existe para **`cumulative_thermal_stress`**: es el único indicador con
overlays `grid_data`. Con cualquier otro el botón se deshabilita y dice para
cuál sirve.

**El color sale del propio tile**, y es el de la plataforma de Ceres — no se
remapea a los tokens del sistema. Es la única capa del mapa donde el usuario
compara contra lo que ve en Ceres, y cambiarle la paleta rompe esa
correspondencia. Es la excepción consciente a la regla de las escalas propias.

El histograma del panel es lo que la convierte en un número accionable en vez de
una mancha de colores: cuánta superficie cae en cada décima, la banda peor
arriba, como en la plataforma. Para el vuelo del 15-abr-2026:

```
0,6–0,7      13 celdas    1,2 ha
0,5–0,6     126 celdas   14,0 ha
0,4–0,5     506 celdas   58,3 ha
0,3–0,4     770 celdas   88,7 ha
0,2–0,3     307 celdas   35,5 ha
0,1–0,2      44 celdas    4,7 ha
            1.766 celdas · 1.142 m²        202,5 ha
```

> **El tamaño de celda se deriva del dato, no se hereda.** San Gerardo declara
> 0,125 ha; en Ketcal las celdas miden **0,1142 ha**. Rotular 1.766 celdas como
> "0,125 ha" declararía 20 ha de más, así que el script lo calcula del histograma
> (ponderado por celdas, ignorando las bandas vacías) y avisa cuando difiere del
> nominal.

Con las celdas encendidas se ocultan el relleno y las etiquetas del nivel —dos
rellenos superpuestos dan un color que no es ninguno de los dos— pero **se
conserva el contorno**, que es la única referencia de qué unidad se está mirando.

Celdas y árboles no se leen juntos, así que encender una apaga la otra. Vale
saber que **hoy esa guarda no se dispara nunca**: los dos conjuntos de
indicadores son disjuntos (grilla sólo en `cumulative_thermal_stress`, árboles
sólo en los otros tres). Se deja por si Ceres publica un día `tree_data` del
indicador de la grilla.

---

## La comparación entre temporadas

Eje X = mes, una línea por temporada: responde **"¿venimos peor que el año
pasado a la misma altura?"**. Es el promedio del predio en el nivel activo,
ubicado en el mes de cada vuelo, y sigue al indicador y al nivel que estén
elegidos.

**Acá no se copió el eje de San Gerardo, y es la diferencia que importa.** Allá
son cinco meses (nov–mar) porque el nogal sólo se vuela en esa ventana. Ketcal se
vuela de **enero a abril y de agosto a diciembre** —nueve meses, ~8 vuelos por
temporada— así que un eje de cinco meses esconderia más de la mitad del
histórico. Los meses se **derivan del dato**, y van de **enero a diciembre**
porque la temporada es el año calendario: con el orden julio-junio de San
Gerardo, dos vuelos del mismo año quedaban en extremos opuestos del gráfico.

```
meses con vuelo: ene feb mar abr · ago sep oct nov dic
sin vuelos:      may jun jul          (lo dice la nota del gráfico)
temporadas:      2022 (1 vuelo) · 2023 (8) · 2024 (8) · 2025 (7) · 2026 (4)
```

La temporada 2022 queda con un solo vuelo (13-dic-2022) al pasar a año
calendario: los de febrero y marzo de 2022 son anteriores a que hubiera grilla
cargada y el pipeline los omite.

El gráfico es SVG propio, como el resto de los del mapa, con eje de **categoría**
y no temporal: los vuelos no son equidistantes y un eje lineal dejaría medio
gráfico vacío. Las líneas se cortan donde no se voló en vez de interpolar por
encima del hueco.

---

## Una trampa del pipeline que conviene no reintroducir

`build_trees()` y `build_grid()` devuelven un bloque **nuevo** con `varieties`,
`stats` y `ramp` vacíos: son catálogos de ids, no estadística. Si la reinyección
de lo ya calculado queda dentro de `if args.extras`, **el refresco semanal del
workflow —que no pasa `--extras`— pisa el catálogo de variedades y el histograma
de la grilla con vacíos.** Pasó, y el síntoma es silencioso: el JSON sigue
pesando lo mismo y el mapa simplemente deja de ofrecer las dos capas.

El orden correcto son dos pasos separados:

1. **Preservar** lo que ya estaba: siempre, salvo `--full`.
2. **Recalcular** lo que falte: sólo con `--extras`.


---

## Nota sobre los indicadores "de temporada" de Ceres

`cumulative_thermal_stress` y `season_average_ndvi` son promedios **de
temporada** que calcula Ceres, no el mapa. Ceres usa su propia definición de
temporada para acumularlos, que no necesariamente es el año calendario de
Ketcal.

O sea: la **etiqueta** de temporada de cada vuelo es nuestra y es el año
calendario; el **valor** de esos dos indicadores lo acumula Ceres con su
criterio. En la práctica no cambia la lectura —el valor de un vuelo es el que
Ceres publica para ese vuelo— pero conviene saberlo antes de interpretar un
salto de esos dos indicadores justo en un cambio de año.
