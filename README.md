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
- **Riego** — consumo por sector de la última semana, en vivo desde DropControl.
  Ver la sección de abajo.
- **Ceres Imaging** — 28 vuelos aéreos entre dic-2022 y abr-2026, 5 indicadores,
  en los tres niveles nativos. Ver la sección de abajo.

**Pendiente**

- **Comparador A/B** de dos vuelos lado a lado, que en San Gerardo existe
  (`mapbox-gl-compare`) y acá todavía no. Con 28 vuelos es donde más se
  aprovecharía.
- **Capa de celdas** de Ceres (`grid_type_id` 26, 1.766 celdas) para mapas de
  calor dentro del cuartel. El script ya la sabe bajar con `--extras`; el mapa
  no la consume.

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
- La ventana es **fija: la última semana**. Probé `?dias=`, `?periodo=`,
  `?rango=`, `?desde=/?hasta=` y `?modo=`: los ignora todos. Si más adelante hace
  falta histórico o temporada, hay que tocar el Apps Script, no el mapa.
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

### Lo que no se baja por defecto

`--extras` habilita la capa por árbol y la grilla de celdas, que decodifican
miles de tiles. Está apagado porque con 28 vuelos esa etapa pasó los 30 minutos
sin terminar, y hasta que no termina **no escribe nada**: se perdían los vuelos
ya descargados. El workflow tampoco lo usa, porque su timeout es de 20 min.

Para Ketcal la capa por árbol además no existe: la cuenta no tiene overlays
`tree_data`. Queda la grilla de celdas, que el mapa todavía no consume.

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
