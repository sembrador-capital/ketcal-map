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
umbrales_nutricion.json     ← umbrales agronómicos — SE EDITA A MANO
data-version.json           ← cache-busting por dataset

tools/kmz_to_geojson.py     ← Ketcal KMZ.kmz  → geo_data.json
tools/build_nutricion.py    ← Excel + umbrales → nutricion_data.json

(Riego no genera archivo: se consulta en vivo. Ver más abajo.)

Ketcal KMZ.kmz                                       ← insumo
Base_Datos_Suelos_Foliares_Ketcal_SEMBRADOR_v2.xlsx  ← insumo
AGQ Labs …/  Laboquim …/  Analisis Suelos AgroLab/   ← informes de origen (PDF)
```

### Regenerar los datos

```bash
python tools/kmz_to_geojson.py
python tools/build_nutricion.py
```

Los dos son idempotentes, imprimen un resumen y **listan sus incidencias** en
vez de corregirlas en silencio. `nutricion_data.json` incluye esas incidencias
en `issues[]`. Después de regenerar, subir la clave correspondiente de
`data-version.json`.

Única dependencia externa: `shapely` (geometría) y `openpyxl` (Excel).

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

**Pendiente**

- **Ceres Imaging** — la pestaña está en la barra, deshabilitada. En San Gerardo
  está resuelto y documentado
  en `../san-gerardo/docs/ceres-integracion.md`: **leer ese documento antes de
  empezar**, la investigación de la API ya está hecha. Lo que cambia en Ketcal
  son los identificadores (`admin_group`, `field_id` por equipo, `grid_type_id`)
  y que acá hay tres niveles de grilla posibles, no dos.

El token de Ceres se lee de variable de entorno (`CERES_TOKEN`) y de secrets en
CI. **Nunca de un archivo versionado**, y nunca inyectado en el navegador: este
sitio es público.

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
