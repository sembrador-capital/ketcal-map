# Ketcal — mapa interactivo

Mapa Mapbox GL del predio **Ketcal** (cítricos, Región de Coquimbo), operado por
Sembrador Capital. Sitio estático: un solo `index.html`, los JSON que genera el
pipeline, y una consulta en vivo a DropControl.

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

**Pendiente**

- **Capa de celdas** de Ceres (`grid_type_id` 26, 1.766 celdas) para mapas de
  calor dentro del cuartel. El script ya la sabe bajar con `--extras`; el mapa
  no la consume.
- **Comparación entre temporadas** en el panel de Ceres, que San Gerardo tiene
  como tercera sección colapsable.
- **Datos de riego.** El calendario funciona, pero DropControl devuelve cero
  eventos en todo periodo probado, incluidas dos temporadas completas. Ver abajo.

---

## Riego: DropControl vía Apps Script

A diferencia de las otras dos pestañas, Riego **no lee un JSON del repo**.
Consulta en vivo un Web App de Google Apps Script:

```
https://script.google.com/macros/s/AKfycbx9…/exec
```

El Apps Script habla con la API de DropControl del lado del servidor y devuelve
el consumo agregado por sector. **Ese es el punto**: el token de DropControl vive
en el Apps Script y nunca llega al navegador, así que el sitio puede ser público
y estar al día sin un workflow de CI ni un archivo que regenerar.

Lo verificado contra el endpoint real:

- Devuelve las **mismas claves `E#-S#`** que produce `kmz_to_geojson.py`, las 28.
  Cero mapeo necesario. Si alguna vez llega una clave sin geometría, el mapa la
  avisa por consola en vez de tragársela.
- Manda `Access-Control-Allow-Origin`, así que el `fetch` desde el navegador
  funciona. Tarda ~2–3 s.
- **Acepta `?desde=&hasta=`** y echoa el rango que usó en `consulta`, lo que
  permite verificar que lo aplicó. Probado de 7 días a dos temporadas completas;
  una temporada tarda ~4 s. Sin parámetros devuelve la última semana.

  > Corrección: en una primera pasada concluí que ignoraba el rango. Era un
  > error de método — probé con un rango de un año, el Apps Script se cayó y
  > devolvió HTML en vez de JSON, y lo leí como "ignora el parámetro". Con
  > rangos razonables funciona perfecto.

- El mapa **sondea** una vez por sesión si el rango se respeta, con un rango del
  mes pasado. No se puede comprobar con la consulta normal: su rango por defecto
  son los últimos 7 días, que es justo lo que el endpoint devuelve cuando NO
  filtra, así que coincidirían siempre. Si el Apps Script cambia, el mapa lo
  detecta y deshabilita el calendario en vez de mostrar la semana actual bajo el
  rótulo de otro periodo.

- **Ningún periodo trae eventos.** Cero en la última semana, cero en el último
  mes, cero en las temporadas 2024-25 y 2025-26 completas. Que dos temporadas
  enteras vuelvan vacías apunta a la consulta del Apps Script hacia DropControl
  —ids de equipo, permisos, nombre del campo— y no al mapa ni al rango. El panel
  lo dice con esas palabras en vez de mostrar un mapa en beige sin explicación.
- Por sector entrega `total_m3`, `total_mm`, `total_m3_ha`, `total_horas`,
  `n_eventos`, `frecuencia_dias`, `duracion_promedio_hrs`, `ultimo_evento`,
  `dias_sin_riego`, `data_ok` y un array `eventos[]`.

La consulta se dispara **al entrar a la pestaña**, no en el load inicial, y queda
cacheada en memoria hasta que se pulse *Actualizar*.

Dos cosas a tener presentes:

1. **Agregación por equipo.** Volumen, horas y eventos se **suman** (el caudal se
   mide por sector, así que la suma es exacta). Lámina, m³/ha, frecuencia y
   duración se promedian ponderando por superficie. No se ofrece por cuartel:
   repartir el volumen de un sector entre los cuarteles que toca exigiría suponer
   cómo se distribuye por dentro, y eso sería un número inventado.
2. **`eventos[]` nunca se pudo observar con contenido.** En todas las consultas
   el endpoint devolvió cero eventos (ventana del 25-ago al 1-sep-2026, receso
   invernal). El panel los renderiza de forma genérica —muestra los campos que
   vengan— justamente para no asumir un esquema que no vi. Cuando haya riego
   real, conviene mirar una ficha y darle a esa tabla el formato que corresponda.

`0 m³` se pinta con un color propio (`--dat-sin-riego`), no como el extremo bajo
de la rampa: un sector que no regó es la señal que hay que ver primero, y la
rampa lo escondería entre los que regaron poco.

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

Dos detalles que hubo que resolver y conviene no volver a romper:

- Los ids de las capas vivas se guardan en una lista propia y **no** se deducen
  de `getStyle()`: esa devuelve una serialización que no refleja los
  `addLayer`/`removeLayer` del mismo tick, y leer el filtro justo después daba
  `null`.
- La capa se reconstruye sólo cuando cambia algo que la afecta (una firma de
  pestaña + vuelo + indicador + nivel + filtro). Sin ese guardia, cada repintado
  volvía a crear cinco sources vectoriales y a pedir todos los tiles.
