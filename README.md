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
assets/exportadoras/        ← logos de las exportadoras (ver su README)
geo_data.json               ← geometría (generado)
nutricion_data.json         ← análisis de suelo y foliares (generado)
cosecha_data.json           ← cosecha por cuartel y semana (generado)
pye_data.json               ← monitoreo de plagas y enfermedades (generado)
ceres_data.json             ← vuelos de Ceres Imaging (generado)
umbrales_nutricion.json     ← umbrales agronómicos — SE EDITA A MANO
ceres_predio.json           ← identificadores de Ketcal en Ceres (descubierto)
data-version.json           ← cache-busting por dataset

tools/kmz_to_geojson.py     ← Ketcal KMZ.kmz  → geo_data.json
tools/build_nutricion.py    ← Excel + umbrales → nutricion_data.json
tools/build_cosecha.py      ← planillas + KMZ  → cosecha_data.json
tools/build_pye.py          ← monitoreos + KMZ  → pye_data.json
tools/fetch_ceres.py        ← API de Ceres    → ceres_data.json
.github/workflows/ceres.yml ← refresco semanal de Ceres

(Riego no genera archivo: se consulta en vivo. Ver más abajo.)

Ketcal KMZ.kmz                                       ← insumo
Base_Datos_Suelos_Foliares_Ketcal_SEMBRADOR_v2.xlsx  ← insumo
AGQ Labs …/  Laboquim …/  Analisis Suelos AgroLab/   ← informes de origen (PDF)
datos_fuente/Base de datos Cosecha Ketcal_20xx.xlsx  ← insumo, NO versionado
datos_fuente/Registro Monitoreo Fruto Ketcal 2026.xlsx  ← insumo, NO versionado
datos_fuente/Ketcal - Registro Monitoreo Planta.xlsx    ← insumo, NO versionado
```

`datos_fuente/` está en `.gitignore` a propósito. Las planillas de cosecha
traen, además de los eventos de campo, guías y facturas, kilos recepcionados por
exportadora y rendimientos de proceso: detalle comercial que el mapa nunca
muestra y que este repositorio es **público**. Lo que sí se versiona es
`cosecha_data.json`, que es exactamente lo que el sitio sirve. Las planillas
viven en la carpeta compartida del portal; para regenerar hay que copiarlas a
`datos_fuente/`.

### Regenerar los datos

```bash
python tools/kmz_to_geojson.py
python tools/build_nutricion.py
python tools/build_cosecha.py "datos_fuente/Base de datos Cosecha*.xlsx"
python tools/build_pye.py
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

## Control de PyE: dos monitoreos que no se mezclan

Son dos registros distintos, con distinta unidad de medida, distinta cadencia y
distinta cobertura. Meterlos en un solo número habría sido cómodo y falso, así
que la pestaña los separa como Nutrición separa foliar de suelo.

| | Planta | Fruto |
|---|---|---|
| Archivo | `Ketcal - Registro Monitoreo Planta.xlsx` | `Registro Monitoreo Fruto Ketcal 2026.xlsx` |
| Qué mide | **incidencia**: % de árboles revisados con la plaga | **% de frutos** con cada defecto |
| Cadencia | mensual | semanal, en cosecha |
| Periodos | 6 (ene → jul 2026, sin junio) | 8 (semanas 24–33) |
| Cobertura | 30 cuarteles, 455 lecturas | 24 cuarteles, 178 muestras, 8.900 frutos |
| Agentes | 14 grupos de plaga | 38 defectos, sólo 11 de plaga o enfermedad |

### El cruce con la geometría

Planta nombra los cuarteles por centro de costo — `L2-C1`, `L1-C8`,
`Naranjos N1-C3`, `Tango M1-C2` — y Fruto por especie más número, como las
planillas de cosecha. Los dos cruzan 1 a 1 con `LIM-C#` / `NAR-C#` / `MAN-C#`, y
la partición por centro de costo calza con el cuadro de plantación: Limones 1
son los cuarteles 7–11 y Limones 2 los 1–6 y 12–14, sin solapamiento.

### La escala del mapa es la del informe, no una inventada

El monitoreo entrega un `nivel_alerta` por lectura. Resultó ser una **función
determinista de la incidencia**, comprobada sobre las 455 filas sin un solo
solapamiento:

| Nivel | Incidencia | n | mín – máx observado |
|---|---|---|---|
| Normal | < 6 % | 111 | 0,0 – 5,9 |
| Bajo | 6 – 10 % | 63 | 6,0 – 9,8 |
| Medio | 10 – 20 % | 78 | 10,0 – 19,4 |
| Alto | ≥ 20 % | 203 | 20,0 – 100,0 |

Esos cortes van en el JSON y son los que pinta el mapa. La leyenda lo dice:
*"cortes del informe de campo, no del mapa"*. Si alguna vez el nivel declarado
dejara de coincidir con el derivado, el build lo lista en `issues` en vez de
elegir uno en silencio.

### Cuatro decisiones sobre los datos

1. **Fruto es un registro de calidad, no de plagas.** De sus 38 defectos, 27 son
   fisiológicos o de manejo (golpe de sol, russet, bajo calibre, daño de tijera).
   Se clasifican en plaga / enfermedad / otro y el selector **agrega sólo PyE por
   defecto**. Contar un golpe de sol como presión de plaga sería un error de
   lectura. El russet queda como `otro` a propósito: en cítricos puede ser
   fisiológico o de ácaro y el registro no lo distingue.

2. **La muestra son 50 frutos**, verificado: los 175 grupos donde el tamaño se
   puede derivar de `frutos / %` dan 50 exacto. El denominador de cualquier
   agregado es 50 × número de muestras, no el número de filas.

3. **Los frutos no son enteros.** 768 de las 3.427 filas traen medios frutos
   (0,5 · 3,5 · 6,5) porque la fila promedia dos submuestras. Truncar a entero
   perdía 64 frutos repartidos por todos los defectos.

4. **Se usa `BASE DE DATOS`, no `BD Ketcal `.** Esta última es una copia parcial
   y vieja: 2.113 filas contra 3.427, semanas 24–27 contra 24–33, y 130 filas con
   el mes 9 sobre fechas de junio y julio.

Las incidencias que el build reporta: 25 filas de Fruto sin cuartel legible (48
frutos afectados que quedan fuera del mapa) y 4 muestras sin ningún defecto con
porcentaje, a las que se les asigna el tamaño estándar.

### La pestaña

Nivel **cuartel**, como Cosecha: ninguno de los dos monitoreos baja a sector.
Un cuartel sin registro en la ventana **no tiene presión cero: no se monitoreó**,
y se pinta con el beige de ausencia.

La **franja de periodos** es el control central, como en Cosecha: una barra por
mes o por semana, apilada por nivel de alerta (Planta) o por clase de defecto
(Fruto), clicable para llevar el mapa ahí.

**Métricas de Planta:**

| Métrica | Qué pinta |
|---|---|
| Nivel de alerta | la peor lectura del periodo, cortada por los umbrales del informe |
| Plagas en alerta | cuántas plagas distintas llegaron a Medio o Alto |
| Persistencia de la alerta | en qué proporción de los meses monitoreados el cuartel estuvo en alerta |
| Nivel de abundancia | el índice de densidad, que es una medida aparte de la incidencia |

La **persistencia** existe por una razón concreta: sobre seis meses y con las 14
plagas juntas, "la peor lectura" satura —29 de 30 cuarteles tocan Alto alguna
vez— y deja de discriminar. Eso es cierto y la pestaña lo muestra, pero para
decidir hace falta separar el cuartel que estuvo en alerta una vez del que
estuvo siempre. Con una plaga concreta seleccionada, la persistencia se abre
bien: Conchuela va de 25 % a 100 % entre sus 18 cuarteles.

**Métricas de Fruto:** % de frutos afectados, frutos afectados y defectos
distintos.

### Los gráficos

El botón **Panorama** abre los tres que el mapa no puede dar:

1. **Evolución de la presión por plaga** — una línea por agente sobre el eje de
   periodos, con las cuatro **franjas de alerta de fondo** en Planta: es lo que
   convierte una curva en una decisión. Los huecos cortan la línea en vez de
   unirla, porque un mes sin monitoreo no es un cero y unirlo dibujaría una
   caída que no ocurrió. Clic en un periodo lleva el mapa ahí.
2. **Ranking de plagas** — barra apilada por nivel de alerta, ordenada por
   cuántas lecturas en Alto. Clic en una fila pinta el mapa con ese agente.
3. **Mapa de calor cuartel × plaga** — 30 × 14 celdas con el nivel de alerta de
   cada cruce. El gris es *no se monitoreó ese cruce*, que no es lo mismo que
   *sin presencia*. Clic en una celda va al cuartel.

Cada cuartel tiene además su modal: KPI, la lista de sus plagas con incidencia y
pastilla de alerta, la evolución de cada una **en ese cuartel**, y el registro
crudo — mes, plaga, especie observada, árboles con presencia sobre revisados,
incidencia, abundancia y alerta.

El **tooltip** lleva la cifra grande arriba con lo que significa debajo
("28,00 % · de los frutos evaluados"), la pastilla de alerta al lado, y las tres
plagas de más presión con su barra y su nivel **escrito**, no sólo en el color de
una barra de 6 px. Se corta en tres y dice cuántas quedan: con nueve plagas pasaba
de 600 px de alto y se salía del canvas.

Una nota de mantenimiento: el botón "Ver detalle" del tooltip estaba estilado
enumerando ids (`#ttRiegoBlock .rt-cta, #ttCeresBlock .rt-cta, …`), así que cada
pestaña nueva que añadía un tooltip con botón se olvidaba de sumar el suyo y
salía el `<button>` pelado del navegador. Pasó dos veces. Ahora la regla se ancla
al contenedor —`.hover-tooltip .rt-cta`—, que es lo único que todos comparten.

En la tabla de Fruto la columna "Afectados" muestra **los frutos de la selección
activa en negrita sobre el total de la muestra**: los KPI cuentan sólo PyE y la
tabla es el registro completo, y sin marcarlo se leían como una contradicción.

---

## Cosecha: el cuartel y la semana

Dos planillas de campo —temporadas **2025** y **2026**— consolidadas por
`tools/build_cosecha.py`. Lo que hubo que resolver antes de dibujar nada:

### El cruce con la geometría

Las planillas numeran los cuarteles **por especie** (Limón 1-14, Naranja 1-12,
Mandarina 1-4) y el mapa los llama `LIM-C1`, `NAR-C1`, `MAN-C1`. Los 30 cruzan
1 a 1, y las superficies declaradas calzan con la geometría del KMZ dentro del
2 % —la diferencia es cabecera y caminos, que el polígono incluye y la
plantación no—, así que la clave `(especie, número)` es segura.

| | 2025 | 2026 |
|---|---|---|
| Registros | 687 | 1.514 |
| Cosechado | 3.370 t | 4.523 t (+34,8 %) |
| Bins | 9.007 | 12.268 |
| Cuarteles | 14 (sólo limones) | 25 (limones + naranjas) |
| Semanas | 36 | 30 |
| Exportación | 63,2 % | 62,0 % |
| Mercado interno | 33,8 % | 35,1 % |
| Desecho | 3,0 % | 3,0 % |

Mandarinas (4 cuarteles) y `NAR-C9` no tienen ninguna cosecha registrada: se
pintan con el beige de ausencia, que **no** es el extremo bajo de la rampa.

### Cuatro decisiones que conviene no revertir

1. **Las hectáreas del rendimiento son las PLANTADAS**, del cuadro de
   plantación, no las geométricas del KMZ. Es el denominador que usa la propia
   planilla en su columna `Kg / Ha` y el agronómicamente correcto. Se usa el
   mismo valor en las dos temporadas para que kg/ha sea comparable entre años:
   2025 y 2026 traen la misma superficie redondeada distinto (5,91 vs 5,92).

2. **La semana sale de la columna `Semana`, no del calendario ISO** de la fecha.
   Difieren en 2 filas de 687 en 2025, ambas domingos que el packing cuenta en
   la semana siguiente. Manda la convención operativa del campo; las
   discrepancias quedan en `issues`.

3. **El destino se reduce a tres clases comparables**: exportación / mercado
   interno / desecho. 2026 separa además el *camote* y 2025 no. El camote se
   guarda como desglose del mercado interno —que es lo que agronómicamente es,
   fruta de menor calibre que se vende igual—: contarlo aparte dejaría el
   mercado interno de 2026 cinco puntos por debajo del de 2025 por un cambio de
   planilla, no de campo.

4. **`Cuartel Real` (sólo en 2026) NO se usa como clave.** En las 23 filas donde
   difiere de `Cuartel`, la superficie y el `Kg / Ha` de la propia fila siguen
   **siempre** a `Cuartel` (23 de 23, verificado), y `Cuartel Real` trae valores
   que no existen en limones (15, 20, 29). Las 23 caen en un único bloque de
   tres días: tiene la firma de un arrastre de fórmula. Quedan listadas en
   `issues` para que agronomía las revise; el script no las corrige.

Las otras incidencias que el build reporta: una fila de 2025 sin cuartel
asignado (13.809 kg de mercado interno, guía 663) que entra en el total del
predio pero no pinta ningún polígono, y una fila fechada `2023-07-31` cuya
semana declarada (31) coincide con `2025-07-31` — se conservan sus kilos y su
semana, y se descarta sólo la fecha, que si no arrancaba la temporada 2025 en
julio de 2023.

### La pestaña

El nivel es **cuartel y sólo cuartel**. Un cuartel lo riegan hasta tres
sectores; repartir sus kilos entre ellos por superficie sería inventar el dato.
La leyenda lo dice en vez de ofrecer un selector que miente.

**La franja de semanas** es el control central, no un adorno. Cada barra es una
semana de la temporada, apilada por destino y a escala del pico, y se puede
clickear para llevar el mapa ahí. Un stepper solo obligaba a adivinar dónde
estaba el peak (2026: semana 32, 495,8 t).

Mide 312 px para hasta 36 semanas: sirve para ver la forma de la curva y para
elegir, no para leerla. El botón de la esquina la abre **en grande** —el mismo
gráfico a 1.180 px, con los KPI de la temporada, el reparto por destino y la
tabla de las semanas del predio entero—, y ahí también se puede clickear una
columna o una fila para llevar el mapa a esa semana.

Tres **ventanas**, calculadas siempre sumando semanas —el build garantiza que
las semanas particionan el total, así que hay una sola ruta de código:

| Ventana | Qué pinta |
|---|---|
| Temporada | todo el año |
| Acumulado | desde el inicio hasta la semana elegida |
| Semana | sólo esa semana |

**Siete métricas**: rendimiento (kg/ha), kilos, bins, kilos por bin, y el % a
cada uno de los tres destinos. Más un **filtro por destino** que cambia el
numerador: con "Exportación" puesto, el rendimiento pasa a ser *kg/ha
exportables* (2026: 16.453 kg/ha de los 26.557 totales).

**Comparar con otra temporada** pinta la **variación relativa** de la métrica
activa contra la misma ventana de semanas del otro año, con rampa divergente.

### Las escalas de color

| Régimen | Cortes | Rampa | Por qué |
|---|---|---|---|
| Magnitud (kg/ha, kg, bins, kg/bin) | septiles de lo que hay en la ventana | productividad (beige → morado) | los kilos de una semana y los de una temporada difieren en dos órdenes de magnitud; con cortes fijos, mirar una semana metería todo en la primera banda |
| Porcentaje de destino | fijos cada 20 % | la del propio destino | comparables entre semanas y entre temporadas; unos cortes móviles harían que el mismo 60 % cambiara de color al mover el calendario |
| Variación | fijos en ±10 % y ±30 % | divergente | simétrica alrededor de "sin cambio" |

Los **tres colores de destino** —teal, oro, tierra— se eligieron por separación
de tono *y* de luminosidad, no por el reflejo verde-amarillo-rojo: bajo
deuteranopia ese trío colapsa a tres olivas y el reparto de la fruta deja de
leerse, que es justo lo único que la pestaña tiene que comunicar de un vistazo.
El mismo color identifica al destino en todas partes —barra del tooltip, franja
de semanas, columnas del modal, leyenda—, y la rampa del "% a exportación"
termina en el mismo teal que el segmento de exportación, para no tener que
explicar dos códigos de color distintos.

### Los tooltips de los gráficos

`title` nativo no servía en ninguno de los gráficos evolutivos: tarda un segundo
largo en aparecer, no admite los cuadraditos de color del reparto por destino, y
desaparece solo mientras se lo está leyendo. Hay un tooltip propio, `#chartTip`,
separado del tooltip del mapa —aquel se posiciona contra el canvas de Mapbox, y
estos viven en el panel lateral y dentro de modales, donde esas coordenadas no
significan nada—, acotado a la ventana en los dos ejes.

El contenido viaja armado y escapado en el `data-tip` del propio elemento, y una
sola pareja de escuchas delegadas lo muestra: registrar handlers por cada una de
las 36 barras cada vez que se redibuja la franja no tenía sentido.

Cada punto o columna lleva una **zona de captura de alto completo**: acertarle
con el mouse a un círculo de 2,5 px o a una barra de 3 px no es razonable, y el
tooltip trae la semana o el muestreo entero en vez del segmento suelto que
hubiera tocado el cursor.

Cubre las tres familias:

| Gráfico | Qué muestra el tooltip |
|---|---|
| Franja de semanas y columnas de Cosecha | semana, fechas, toneladas, reparto por destino con sus tres colores y porcentajes, bins, cuarteles, peso sobre la temporada, avance acumulado y —en el modal de un cuartel— kg/ha |
| Series de Nutrición | fecha, valor con su unidad, banda de umbral en la que cae, variación respecto del muestreo anterior y número de muestras |
| Series de Ceres | fecha del vuelo, valor, clase del indicador y variación respecto del vuelo anterior |

### El destino de la fruta, en anillos

El detalle general de la temporada abre con **dos anillos**, porque son dos
preguntas distintas y una sola barra apilada sólo contestaba la primera:

1. **Reparto por destino** — exportación / mercado interno / desecho, con el
   total cosechado en el centro.
2. **Exportación por exportadora** — a quién le fue la fruta que se exportó, con
   el logo de cada una.

Anillos y no tortas macizas: el hueco central lleva el total, que es el número
que uno busca antes de comparar proporciones. Una sola porción se dibuja como
círculo, porque un arco de 360° tiene los dos extremos en el mismo punto y
degenera.

El segundo anillo usa los kilos de **exportación** de cada receptor, no sus
kilos totales: Rosales también recibe mercado interno, y contarlo ahí infla su
porción con fruta que no se exportó. La diferencia no es menor — en 2026 Rosales
recibió 3.261 t en total y 1.676 t de exportación.

| Exportadora | 2026 | 2025 |
|---|---|---|
| Rosales | 59,8 % | 40,6 % |
| Gesex | 30,0 % | 13,6 % |
| Propal | 7,0 % | 17,7 % |
| El Parque | 3,2 % | 15,8 % |
| Westfalia | — | 10,1 % |
| Río Blanco | — | 2,2 % |

El **botadero no entra** en el anillo de exportadoras: no es un cliente, es el
destino de la merma. Aparece en la tarjeta "Todos los receptores" del detalle de
cada cuartel, con su reparto por destino.

Los colores de las porciones **no** son los de marca de cada exportadora: cuatro
de las cinco son verdes y en un anillo de seis porciones no se distinguirían. El
logo lleva la identidad; el color sólo tiene que separar las porciones.

Los logos viven en `assets/exportadoras/<id>.png`, donde `<id>` es el que emite
`tools/build_cosecha.py`. Si el archivo no está, el `onerror` del `<img>` lo
quita del DOM y el monograma que va detrás queda visible — el selector
`img + b` sólo lo oculta *mientras* el `img` exista, así que el respaldo es CSS
puro sin JavaScript de por medio. Un detalle que costó descubrir: con
`loading="lazy"` el respaldo **no** funcionaba, porque la carga diferida no
dispara `onerror` mientras el elemento está bajo el pliegue y quedaba una caja
vacía. Son cinco PNG de pocos KB; diferirlos no ahorraba nada.

### El detalle semanal

Es lo que el polígono no puede mostrar. Un cuartel con 35 t/ha y 62 % de
exportación puede haber entrado todo en dos semanas o repartido en quince, y
puede haber empezado exportando y terminado mandando todo a mercado interno.

El modal trae, para el cuartel elegido: cinco KPI, el reparto por destino de la
temporada, un gráfico de **columnas apiladas por destino semana a semana** con
la **curva de avance acumulado** superpuesta (y la de la temporada de
comparación punteada al lado), la tabla de semanas con fechas, bins, toneladas,
kg/ha, avance y reparto, y los **kilos por receptor** (Rosales, Gesex, Propal,
El Parque, Westfalia, Botadero).

Las columnas fuera de la ventana que el mapa está pintando se atenúan, y
clickear una lleva el mapa a esa semana: el gráfico y el mapa son la misma
selección, no dos vistas sueltas.

---

## Nutrición se organiza por PROGRAMA, no por matriz

Éste es el cambio que hace que la pestaña se entienda. **Una matriz no es un
programa de monitoreo.** "Foliar" en Ketcal son dos programas que conviven, con
laboratorios, cadencias, coberturas y sets de parámetros distintos:

| | Laboquim Terra | AGQ Labs |
|---|---|---|
| Muestreos | 4 (abr-24, may-24, jun-25, abr-26) | 6 (nov-25 → mar-26) |
| Fechas | **todas aproximadas** (fecha del informe) | reales |
| Cadencia | ~320 días (anual) | ~28 días (mensual) |
| Ubicaciones | 28, variables entre fechas | 5 fijas |
| Con serie (≥2 muestreos) | 12 | 5 |
| Parámetros | 12 | 14 (agrega S y Mo) |

Lo mismo en suelo: `Suelo_Fertilidad` son **dos campañas de una fecha cada una**
(AGQ, 5 ubicaciones, oct-2025, 24 parámetros; AgroLab, 6 ubicaciones, nov-2025,
21 parámetros), y sólo `Solucion_Suelo` (AGQ, mensual) tiene serie.

Con el diseño anterior, el selector de "Muestreo" listaba las 10 fechas foliares
seguidas. Al avanzar una fecha cambiaban **a la vez** el laboratorio, las
unidades muestreadas y los parámetros disponibles: el mapa se repintaba entero y
no había forma de saber por qué. Ése era el "no se comprende bien".

Ahora se elige primero el **programa** y todo lo demás cuelga de él:

- El selector agrupa los programas por matriz con `<optgroup>`, y cada opción
  dice el laboratorio, la cadencia, cuántos muestreos y cuántas unidades:
  `Laboquim Terra · anual · 4 muestreos · 28 unid.`
- La **leyenda va encabezada por la procedencia**: chip con el laboratorio,
  nombre del análisis, cuántos muestreos y entre qué fechas, la cadencia en días,
  cuántas ubicaciones muestreadas y cuántas con evolución, y el aviso de fechas
  aproximadas con su proporción. Es la primera respuesta a "¿qué estoy mirando?"
  y va antes que cualquier color, porque dos programas del mismo análisis no son
  comparables entre sí.
- El **sello superior** lleva el laboratorio junto a la fecha del muestreo.
- Las **series de tiempo nunca cruzan programas**: encadenar un valor de Laboquim
  con uno de AGQ dibuja un salto que es de método, no de la planta.
- Los **parámetros se agrupan por cómo se leen sus colores** (umbral de
  laboratorio / de referencia / escala relativa), no por orden agronómico: un
  cuartil del predio y un diagnóstico se pintan igual y no significan lo mismo.
- El **catálogo de programas se arma en el build** (`programas` en
  `nutricion_data.json`), no en el navegador.

### "Sólo con evolución"

El filtro que pedía el encargo: restringe mapa, leyenda, métricas, ranking y
selector del modal a las unidades con **dos o más muestreos dentro del programa
elegido**. Se calcula por nivel, porque una unidad sin serie a nivel de ubicación
puede tenerla al agregar por sector:

| Programa | Ubicaciones | Sectores | Cuarteles | Equipos |
|---|---|---|---|---|
| Foliar · Laboquim Terra | 12 | 13 | 12 | 5 |
| Foliar · AGQ Labs | 5 | 5 | 3 | 3 |
| Solución de suelo · AGQ | 5 | 5 | 3 | 3 |
| Los tres de una sola fecha | 0 | 0 | 0 | 0 |

En un programa sin ninguna serie el checkbox queda apagado y deshabilitado, y el
botón "Evolución" también, en vez de vaciar el mapa sin explicación.

El **segmentado de nivel lleva su conteo** de unidades con dato (o con serie, si
el filtro está puesto) y se deshabilita donde el programa no muestreó nada.
El **ranking marca `n×`** los muestreos que tiene cada unidad en el programa —no
en el muestreo seleccionado, que siempre daría 1.

El modal de Evolución sólo ofrece unidades con serie; si el nivel activo no tiene
ninguna, cae al nivel más fino que sí las tenga y lo dice en el subtítulo.

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
- **Cosecha** — dos temporadas (2025 y 2026) por cuartel y **por semana**, con
  ventana de temporada / acumulado / semana suelta, siete métricas, filtro por
  destino de la fruta, comparación entre temporadas y detalle semanal por
  cuartel. Ver la sección de abajo.
- **Control de PyE** — dos monitoreos por cuartel: **planta** (mensual, 30
  cuarteles, 14 plagas, con el nivel de alerta del informe de campo) y **fruto**
  (semanal en cosecha, 178 muestras de 50 frutos, 38 defectos). Con evolución de
  la presión por plaga, ranking y mapa de calor cuartel × plaga. Ver abajo.
- **Nutrición** — subpestañas foliares / suelo, **6 programas de muestreo**
  (matriz × laboratorio), selector de profundidad para los que la tienen,
  filtro "sólo con evolución", pintado por banda de umbral, leyenda encabezada
  por la procedencia, ranking de peor a mejor, series de tiempo por parámetro
  con las bandas de fondo, y las 13 calicatas del estudio 2018 como capa de
  puntos con su perfil físico y químico. Ver la sección de abajo.
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
  lado A, y por eso al entrar al comparador se apagan y sus botones quedan
  deshabilitados: comparar árboles contra polígonos no compara nada.

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

### Tooltip y modal de detalle

Replican los de San Gerardo, que es lo que se pidió:

- **Tooltip** — el valor grande en **m³/ha** (que es lo comparable entre sectores
  de superficie distinta), una retícula de cuatro métricas (superficie, volumen
  total, frecuencia, duración promedio), el botón *Ver detalle* y la línea de
  procedencia al pie.
- **Modal** — siete tarjetas KPI en dos filas, gráfico de barras de **volumen por
  evento** con el último en navy, y la tabla completa de eventos: `#`, fecha,
  inicio, fin, duración, m³, mm y días hasta el siguiente. El evento más reciente
  encabeza la tabla y va destacado: contesta "¿cuándo se regó por última vez?".

Dos cosas que **no** se copiaron tal cual:

1. El tooltip tenía que quedar **vivo al pasarle el mouse por encima**, o el botón
   *Ver detalle* no se podía clickear nunca: se ocultaba en el `mouseleave` del
   polígono. Ahora se oculta con un retardo corto que pasar por encima cancela.
2. **A nivel equipo no hay eventos propios**: los eventos son por sector.
   Fusionar los de cinco sectores haría que "días hasta el siguiente" deje de
   significar algo, así que el modal del equipo muestra sus KPI y el **desglose
   por sector**, con cada sector clickeable para saltar a su detalle.

> El contenido del tooltip va envuelto en un `<div id="ttRiegoBlock">` porque las
> reglas `.rt-*` del CSS copiado están *scoped* por ese ancestro. Reusar el id es
> lo que hace que se vea idéntico al de San Gerardo sin duplicar una línea de
> CSS.

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

Con cualquier capa de detalle encendida se apaga el **relleno** del nivel: son
círculos de 2 px o celdas semitransparentes, y un relleno al 62 % encima los
apaga. Ver "El velo, una sola autoridad" más abajo.

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

### Los cuatro segundos de la capa por árbol

Medido en frío, predio completo a z15, los cinco overlays del vuelo:

```
clic            →     0 ms
tiles en mano   → ~2.000 ms   cinco fuentes vectoriales
primer pintado  → ~4.300 ms   parseo y subida a GPU de 230.000 círculos
```

Ese costo es real y no se puede negociar: son 230.000 puntos. Lo que sí era
arreglable —y era lo que se veía como "no renderiza"— es todo lo demás:

**Uno. El mapa quedaba en blanco los cuatro segundos.** El velo bajaba el
relleno del polígono en el instante del clic, y los árboles llegaban cuatro
segundos después: en el medio, satelital pelado y ninguna explicación. Ahora el
velo espera a que la capa haya dibujado. Medido: **0 ms de mapa vacío**, contra
los ~4.300 ms de antes. Los polígonos ceden recién cuando los árboles están.

**Dos. Cualquier cambio de estilo pagaba la recarga entera.** La firma que
decidía si reconstruir incluía `S.ceres.nivel` y `arbolesSoloMalos`, que son
estilo puro. Cambiar de nivel o apretar "sólo los que no están en la mejor
clase" —las dos cosas que uno hace *mientras* mira los árboles— tiraba las cinco
fuentes y volvía a la red. Ahora la firma cubre sólo lo que determina qué tiles
pedir (modo, vuelo, catálogo de overlays) y el resto se aplica encima con
`setPaintProperty` / `setFilter`. Las dos operaciones pasaron de ~4 s a
instantáneas, con **cero peticiones**. Lo mismo en la capa de celdas, donde
`S.ceres.nivel` tampoco pintaba nada: el color de la celda viene dentro del tile.

**Tres. Se pedían tiles de equipos que no estaban en pantalla.** Ceres publica
un overlay por equipo, así que son cinco fuentes, y sin `bounds` Mapbox le pide
tiles a las cinco en toda la ventana. Los cinco equipos de Ketcal no se solapan,
así que cada fuente declara su extensión (calculada del propio `geo_data.json`,
con 65 m de margen para el árbol del borde) y mirando de cerca un equipo las
otras cuatro no salen a la red.

**Cuatro. Encender desde lejos pedía dos pirámides de tiles.** `toggleArboles`
animaba el zoom hasta 14.2 *mientras* montaba la capa, y la animación cruzaba
z14: se pedían los tiles de z13 y se descartaban a los 600 ms. Ahora la cámara
salta primero y la capa se monta después.

**Cinco. Cuatro segundos sin una palabra se leen como "no funciona".** El botón
dice "Cargando árboles…" y late mientras tanto.

Una trampa que conviene no reintroducir: **`map.isSourceLoaded()` no sirve como
señal de "ya está"**. Verificado en este mapa: devuelve `false` para fuentes que
están pintando miles de features —las cinco de celdas con 153 a 450 celdas en
pantalla, la de árboles de E1 con 2.954 puntos—, porque con `bounds` y `maxzoom`
quedan tiles especulativos pendientes indefinidamente. La comprobación buena es
`queryRenderedFeatures`, que es cara: se hace una sola vez por activación y el
resultado se pega. El disparador es `sourcedata` estrangulado a 400 ms, no
`idle`: con los tiles entrando en tandas, `idle` llegó a emitir **una sola vez
en diez segundos** y el botón se quedaba colgado en "Cargando…".

### El velo, una sola autoridad

Era el bug de "a veces la vista por árbol queda bugeada o queda por debajo de
los polígonos". Tenía dos causas y las dos están arregladas.

**Una.** Tres lugares escribían la misma propiedad de visibilidad —`repintar()`,
el velo de los árboles y el de las celdas— y ganaba el último en correr. Como
`repintar()` llama primero a `refrescarArboles()` y después a
`refrescarCeldas()`, el velo de las celdas (que con las celdas apagadas dice
"mostrar") deshacía el de las variedades. Reproducido: tras `toggleVariedades()`
el relleno quedaba en `none`, y tras un `repintar()` volvía a `visible`; bastaba
mover cualquier control para enterrar los 230.000 árboles bajo un relleno al
62 %. Ahora hay **una sola función**, `aplicarVelos()`, que mira todo el estado y
decide una vez.

**Dos.** El velo no miraba el zoom. La capa por árbol no dibuja bajo z13 y la
grilla bajo el `min_zoom` que declara Ceres: encenderlas desde lejos apagaba el
relleno y no ponía nada en su lugar, y el predio quedaba en puros contornos. Ese
era el "queda bugeada".

La regla, ahora una sola para las tres capas de detalle:

```
si hay capa de detalle montada Y el zoom alcanza para que dibuje
    → relleno del nivel: oculto
contorno  → siempre visible (es la referencia de qué unidad se mira)
etiquetas → siguen al interruptor "Etiquetas", y nada más
```

Se reevalúa en cada `zoomend`. San Gerardo aplicaba el velo sólo a variedades
porque su capa por árbol convive con un único nivel de polígono; acá son cuatro
y el efecto se nota mucho más, así que también cubre la capa por indicador.


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
