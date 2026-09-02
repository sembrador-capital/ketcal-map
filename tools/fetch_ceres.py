#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_ceres.py — Descarga los vuelos de Ceres Imaging del predio Ketcal y
escribe ceres_data.json en la raiz del repo, listo para que el mapa lo lea con
loadDataset('ceres', ...).

Adaptado de san-gerardo/tools/fetch_ceres.py. Toda la logica de API, umbrales,
bandas, deltas y cumplimiento viene de ahi sin cambios: es codigo verificado
contra la cuenta real de Ceres. Lo propio de Ketcal es el bloque de
identificadores, que NO se hardcodea: se descubre con --discover y queda en
ceres_predio.json.

────────────────────────────────────────────────────────────────────────────────
PRIMER USO

  1. python tools/fetch_ceres.py --check-token     valida la credencial
  2. python tools/fetch_ceres.py --discover        encuentra los identificadores
                                                   del predio y escribe
                                                   ceres_predio.json
  3. python tools/fetch_ceres.py --full            baja todo el historico

El paso 2 es de SOLO LECTURA e imprime lo que encuentra para revisarlo antes de
confiar en el. Si Ketcal no esta bajo el mismo cliente que San Gerardo, ahi se
ve.

────────────────────────────────────────────────────────────────────────────────
CREDENCIAL

El token DRF permanente de Ceres se lee, en este orden:

  1. Variable de entorno CERES_TOKEN   <- lo que usa CI (secrets.CERES_TOKEN)
  2. Archivo .ceres_token en la raiz   <- conveniencia para correr en local

.ceres_token esta en .gitignore. Este repo es publico: el token no va en ningun
archivo rastreado, ni en un log, ni en un mensaje de error. Si falta, el script
aborta con exit(1) sin imprimir nada del valor.

────────────────────────────────────────────────────────────────────────────────
UMBRALES

Cada indicador declara en PARAMS como se clasifica (bands_policy). Nada se
adivina en runtime: la decision es humana y esta escrita con su motivo.

  water_stress               "ceres"      4 clases, cortes publicados por Ceres
                                          (0/0,25/0,50/0,75/1), rotuladas 1..4
                                          como en la plataforma
  cumulative_thermal_stress  "share:"     hereda los cortes de water_stress: es
                                          su promedio de temporada (verificado,
                                          error 0,0000 en 322 observaciones)
  absolute_ndvi              "fixed"      9 clases con cortes de agronomia. El
  season_average_ndvi                     colorMap de Ceres es una rampa
                                          uniforme de 0,05: escala fija, pero
                                          despliegue y no clasificacion
  chlorophyll_class          "relative"   4 clases relativas AL VUELO. Es un
                                          indice relativo: la auditoria de los
                                          845 overlays encuentra 67 colorMap
                                          distintos en 69, recalculados por
                                          campo y por vuelo. La plataforma
                                          tampoco muestra numeros ahi, muestra
                                          1-Mas bajo .. 4-Mas alto

Los cortes publicados salen del parametro colorMap de download_urls en
/api/overlays/ (NO de flight_summary, cuyos overlays vienen sin download_urls).

Un indicador relativo guarda sus cortes DENTRO de cada vuelo y por nivel, en
flights[].relative_bands, porque no son los mismos entre fechas. El mapa lo
advierte: dos vuelos no son comparables entre si.

Queda una cuarta modalidad, "unclassified", para el indicador que no tenga con
que clasificarse. Hoy ninguno cae ahi, pero es la red si Ceres cambia algo.

Para ajustar cualquier corte sin tocar codigo ni mapa, crea
ceres_thresholds.json en la raiz del repo. Un override SIEMPRE gana sobre la
politica, incluso convierte un relativo en cortes fijos:

    {
      "water_stress": {
        "bands": [
          {"min": 0.00, "max": 0.30},
          {"min": 0.30, "max": 0.55},
          {"min": 0.55, "max": 0.80},
          {"min": 0.80, "max": 1.00}
        ]
      }
    }

Sus bandas pisan las del indicador y bands_source pasa a "custom". Las etiquetas
y los codigos de estado se derivan de la cantidad de bandas y de la direccion del
indicador; no hace falta escribirlas.

────────────────────────────────────────────────────────────────────────────────
USO

    pip install requests mapbox-vector-tile
    python tools/fetch_ceres.py --full      # historia completa (28 llamadas)
    python tools/fetch_ceres.py             # incremental: solo vuelos ausentes
    python tools/fetch_ceres.py --check-token       # valida el token, sin bajar nada
    python tools/fetch_ceres.py --inspect-overlays  # forma y umbrales de /overlays/

`requests` es obligatorio. `mapbox-vector-tile` solo hace falta para la capa por
arbol: decodifica los tiles para calcular las clases de un indicador relativo
sobre la distribucion de arboles y contar las variedades. Si falta, el script
avisa y sigue sin esas dos cosas.

Correr dos veces seguidas no genera cambios la segunda vez: si el JSON
resultante es identico al que ya esta en disco, no se reescribe (ni siquiera
generated_at).
"""

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
from collections import OrderedDict
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.stderr.write(
        "ERROR: falta la dependencia `requests`.\n"
        "       Instalala con:  pip install requests\n"
    )
    sys.exit(1)

# ── Identificadores de San Gerardo (verificados contra la cuenta real) ───────
BASE_URL = "https://works.ceresimaging.net/api"

# ── Identificadores del predio ───────────────────────────────────────────────
#
# NO se hardcodean. Viven en ceres_predio.json, que lo escribe `--discover`
# despues de preguntarle a la API. Es la diferencia con San Gerardo, donde los
# identificadores se averiguaron a mano una vez y quedaron en el codigo: aca el
# descubrimiento es reproducible y queda registrado con su fecha.
#
# Forma del archivo:
#
#   {
#     "user_id": "7868",
#     "admin_group": "CFF|4527.<id del predio>",
#     "farm_name": "Ketcal",
#     "customer": "...",
#     "grid_types": {"sectors": 7, "equipos": 18},
#     "field_to_equipo": {"<field_id>": "E1", ...},
#     "descubierto": "2026-09-01T…Z"
#   }
PREDIO_PATH_NAME = "ceres_predio.json"

# El user_id no depende del predio sino de la cuenta, y es la misma que la de
# San Gerardo (Sembrador). Sirve de punto de partida para el descubrimiento.
USER_ID_DEFAULT = "7868"

# Cliente bajo el que esta San Gerardo. Si Ketcal cuelga del mismo, el
# admin_group del predio es "CFF|4527.<id>"; --discover lo confirma o lo
# desmiente en vez de asumirlo.
CUSTOMER_HINT = "CFF|4527"

USER_ID = None
ADMIN_GROUP = None
FARM_NAME = "Ketcal"
CUSTOMER = None

# ── Niveles ──────────────────────────────────────────────────────────────────
#
# Ketcal tiene TRES grillas cargadas en Ceres, y las tres son agregados nativos
# sobre los pixeles: el cuartel no sale de promediar sectores. Eso es lo que
# permite cruzar Ceres con Nutricion a nivel cuartel, que es la unidad de los
# analisis foliares.
#
# El orden es el del selector del mapa: de lo grueso a lo fino.
LEVELS = ("equipos", "sectors", "cuarteles")

# Nombre del nivel -> coleccion de geo_data.json con la que se cotejan sus claves.
LEVEL_GEO = {"equipos": "equipos", "sectors": "sectores", "cuarteles": "cuarteles"}

LEVEL_ES = {"equipos": "Equipo", "sectors": "Sector", "cuarteles": "Cuartel"}
LEVEL_EN = {"equipos": "Unit", "sectors": "Sector", "cuarteles": "Block"}

# grid_type_id por nivel, desde ceres_predio.json. Un nivel sin grilla se omite.
LEVEL_GRID = {}
# Cuantas unidades esperar por nivel, desde geo_data.json.
LEVEL_N = {}


def niveles_activos():
    """Niveles que tienen grilla en Ceres, en el orden de LEVELS."""
    return tuple(l for l in LEVELS if LEVEL_GRID.get(l) is not None)

# field_id -> equipo. Sirve para etiquetar el nivel equipo, donde block_name no
# necesariamente viene con el formato "E<n>".
FIELD_TO_EQUIPO = {}

# bands_policy, por indicador (ver el detalle en el encabezado del archivo):
#
#   "ceres"          los cortes publicados son clases agronomicas de verdad
#   "share:<otro>"   toma prestados los cortes de otro indicador que mide lo mismo
#   "fixed"          cortes definidos por agronomia, en `cuts`
#   "relative"       clases recalculadas en cada vuelo, `n_classes`
#   "unclassified"   sin nada con que clasificar; el mapa lo muestra en gris
#
# Es una decision humana verificada contra el dato real de San Gerardo (14 vuelos,
# 322 observaciones por indicador): vive aca escrita y con su motivo, y no se
# infiere en runtime.

# Cortes de NDVI definidos por agronomia. No los publica Ceres como umbral: su
# colorMap es una rampa uniforme de 0,05. Nueve clases, con la primera y la
# ultima abiertas (<0,50 y >0,85).
#
# ⚠ PENDIENTE DE VALIDACION PARA CITRICOS. Esta escalera se definio para NOGAL
# en San Gerardo. El citrico es de hoja perenne: no tira la hoja en invierno y
# su NDVI se mantiene alto todo el año, asi que es probable que en Ketcal casi
# todas las unidades caigan en las dos clases de arriba y la escala no
# discrimine nada. El script lo MIDE y lo avisa al terminar (ver
# revisar_discriminacion_ndvi): si la distribucion se apelotona, hay dos
# salidas, y las dos se hacen sin tocar codigo:
#
#   1. cortes propios para citricos en ceres_thresholds.json, definidos por
#      agronomia; o
#   2. "bands_policy": "relative" para el NDVI en ese mismo archivo, que lo
#      clasifica por cuartiles de cada vuelo como se hace con la clorofila.
#
# Mientras no se decida, se usan estos y el mapa muestra su procedencia.
NDVI_CUTS = [0.0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 1.0]

# Los nombres en espanol son los de la plataforma de Ceres, tal como los ve
# agronomia: si el mapa los llamara de otra forma, habria que traducir de cabeza
# entre las dos herramientas. Los de ingles son equivalentes razonables (solo se
# verifico la interfaz en espanol).
#
# `group` reproduce la agrupacion de la plataforma, para que el selector del mapa
# se lea igual.
PARAMS = OrderedDict([
    ("water_stress", {
        "es": "Estrés Hídrico - perennes", "en": "Water stress - perennials",
        "desc_es": "Déficit de transpiración",
        "desc_en": "Transpiration deficit",
        "group_es": "Irrigación", "group_en": "Irrigation",
        "higher_is_better": False,
        "bands_policy": "ceres",
        # Los cuatro tramos publicados son las cuatro clases que la plataforma
        # rotula 1..4; se usan sus nombres y no unos genericos.
        "labels": "stress_4",
    }),
    ("cumulative_thermal_stress", {
        "es": "Estrés Acumulado", "en": "Cumulative stress",
        "desc_es": "Déficit promedio de transpiración esta temporada",
        "desc_en": "Average transpiration deficit this season",
        "group_es": "Irrigación", "group_en": "Irrigation",
        "higher_is_better": False,
        # Verificado sobre las 322 observaciones con error 0.0000: este indicador
        # es el promedio corrido de water_stress dentro de la temporada. Misma
        # magnitud fisica (deficit de transpiracion), misma escala 0-1, mismo
        # significado, asi que le corresponden los MISMOS cortes publicados que a
        # water_stress. No es un umbral inventado: es el umbral de Ceres aplicado
        # a la media de Ceres de la misma cantidad. La rampa de 10 tramos que
        # publica para este overlay es una eleccion de despliegue del mapa de
        # calor, no una clasificacion.
        "bands_policy": "share:water_stress",
        "labels": "stress_4",
    }),
    ("absolute_ndvi", {
        "es": "Índice de Vegetación Absoluto", "en": "Absolute vegetation index",
        "desc_es": "Crecimiento del dosel",
        "desc_en": "Canopy growth",
        "group_es": "Desarrollo de cultivos", "group_en": "Crop development",
        "higher_is_better": True,
        # El colorMap de Ceres es una rampa uniforme de 0,05 (escala fija, pero
        # despliegue y no clasificacion). Los cortes de abajo los define
        # agronomia: nueve clases, con el primero y el ultimo abiertos.
        "bands_policy": "fixed",
        "cuts": NDVI_CUTS,
        "labels": "ranges",
    }),
    ("season_average_ndvi", {
        "es": "Índice de Vegetación promedio temporada",
        "en": "Season average vegetation index",
        "desc_es": "Crecimiento promedio del dosel esta temporada",
        "desc_en": "Average canopy growth this season",
        "group_es": "Desarrollo de cultivos", "group_en": "Crop development",
        "higher_is_better": True,
        # Es el promedio corrido del NDVI dentro de la temporada (verificado,
        # error 0.0000 en 299 obs), asi que vive en la misma escala y le
        # corresponden los mismos cortes.
        "bands_policy": "fixed",
        "cuts": NDVI_CUTS,
        "labels": "ranges",
    }),
    ("chlorophyll_class", {
        "es": "Clorofila", "en": "Chlorophyll",
        "desc_es": "Crecimiento relativo del dosel",
        "desc_en": "Relative canopy growth",
        "group_es": "Desarrollo de cultivos", "group_en": "Crop development",
        "higher_is_better": True,
        # La plataforma lo describe como "crecimiento RELATIVO del dosel", y la
        # auditoria de los 845 overlays lo confirma: 67 colorMap DISTINTOS en 69
        # overlays, recalculados por campo Y por vuelo. Por eso NO se le pueden
        # poner cortes fijos: el mismo valor caeria en clases distintas segun el
        # vuelo. Y por eso la plataforma no muestra numeros, muestra cuatro
        # clases relativas (1 - Mas bajo .. 4 - Mas alto).
        #
        # Se clasifica igual que ahi: cuartiles de la distribucion DE CADA VUELO,
        # calculados en el script y por nivel. Los cortes viven en el vuelo y no
        # en el indicador, porque cambian vuelo a vuelo.
        "bands_policy": "relative",
        "n_classes": 4,
        "labels": "relative",
        "relative_es": "Clases relativas al vuelo: los cortes se recalculan en cada vuelo, así que no son comparables entre fechas.",
        "relative_en": "Classes relative to the flight: cuts are recomputed per flight, so they are not comparable across dates.",
    }),
])

# colorized_ndvi queda fuera: la plataforma lo describe como "crecimiento
# RELATIVO del dosel" frente al "crecimiento del dosel" del absoluto, o sea es el
# mismo NDVI renderizado contra la distribucion del vuelo. Como valor por sector
# no es comparable entre vuelos, que es justo lo que el mapa necesita.
# cir (Infrarroja Color) y core_thermal (Térmica) no entran como INDICADOR:
# son imagenes para mirar, no indices con un valor por unidad. Si entran como
# capa raster, por otra via: ver IMAGERY_TYPES.
IGNORED_OVERLAYS = {"colorized_ndvi", "cir", "core_thermal"}

# ── Escalera de estados ──────────────────────────────────────────────────────
# Los codigos salen de STATUS_COLORS / STATUS_PALETTES de index.html: no se crea
# un sistema de estados paralelo. severity (0 = mejor) es lo que el mapa usa
# para elegir el color, porque el orden de los tokens en la escala foliar es
# posicional (def -> bajo -> optimo -> alto -> exc, de dos lados) y no una rampa
# de severidad: pintar por status daria naranjo antes que amarillo.
STATUS_LADDER = {
    2: ["opt", "exc"],
    3: ["opt", "alto", "exc"],
    4: ["opt", "bajo", "alto", "exc"],
    5: ["opt", "bajo", "alto", "exc", "def"],
}

BAND_LABELS = {
    2: [("Óptimo", "Optimal"), ("Crítico", "Critical")],
    3: [("Óptimo", "Optimal"), ("Alerta", "Warning"), ("Crítico", "Critical")],
    4: [("Óptimo", "Optimal"), ("Adecuado", "Adequate"),
        ("Alerta", "Warning"), ("Crítico", "Critical")],
    5: [("Óptimo", "Optimal"), ("Adecuado", "Adequate"), ("Moderado", "Moderate"),
        ("Alerta", "Warning"), ("Crítico", "Critical")],
}

# Etiquetas de la plataforma de Ceres, indexadas por SEVERIDAD (0 = mejor). Se
# usan en vez de las genericas de arriba cuando el indicador las declara, para
# que el mapa nombre las clases igual que la herramienta que usa agronomia.
PLATFORM_LABELS = {
    "stress_4": [
        ("1 - No estresadas", "1 - Not stressed"),
        ("2 - Estrés bajo", "2 - Low stress"),
        ("3 - Estrés moderado", "3 - Moderate stress"),
        ("4 - Estrés alto", "4 - High stress"),
    ],
}


def relative_labels(n):
    """
    Clases relativas 1..n por posicion de VALOR ascendente: 1 es el mas bajo del
    vuelo. Se generan para el n que resulte y no se leen de una tabla fija,
    porque los cuartiles pueden colapsar: con 5 equipos y dos valores empatados
    quedan 3 clases, y ahi una tabla de 4 entradas dejaria ese vuelo con nombres
    distintos a los demas.
    """
    out = []
    for i in range(n):
        cls = i + 1
        if n == 1:
            out.append(("Única clase", "Single class"))
        elif cls == 1:
            out.append(("1 - Más bajo", "1 - Lowest"))
        elif cls == n:
            out.append(("%d - Más alto" % cls, "%d - Highest" % cls))
        else:
            out.append((str(cls), str(cls)))
    return out


def range_labels(cuts, decimals=2):
    """
    Etiquetas de rango a partir de los cortes, en orden de valor ascendente:
    "<0,50", "0,50–0,55", ..., ">0,85". El primero y el ultimo se abren, porque
    sus extremos son el limite del indice y no un corte real.
    """
    def es(v):
        return ("%." + str(decimals) + "f") % v
    def num_es(v):
        return es(v).replace(".", ",")
    out = []
    n = len(cuts) - 1
    for i in range(n):
        lo, hi = cuts[i], cuts[i + 1]
        if i == 0:
            out.append(("<" + num_es(hi), "<" + es(hi)))
        elif i == n - 1:
            out.append((">" + num_es(lo), ">" + es(lo)))
        else:
            out.append((num_es(lo) + "–" + num_es(hi), es(lo) + "–" + es(hi)))
    return out



REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREDIO_PATH = os.path.join(REPO_ROOT, PREDIO_PATH_NAME)
GEO_PATH = os.path.join(REPO_ROOT, "geo_data.json")
OUT_DEFAULT = os.path.join(REPO_ROOT, "ceres_data.json")
DATA_VERSION_PATH = os.path.join(REPO_ROOT, "data-version.json")
OVERRIDES_PATH = os.path.join(REPO_ROOT, "ceres_thresholds.json")
TOKEN_FILE = os.path.join(REPO_ROOT, ".ceres_token")

TIMEOUT = 60
RETRIES = 3


# ═══════════════════════════════════════════════════════════════════════════
# Credencial
# ═══════════════════════════════════════════════════════════════════════════

def unquote_token(tok):
    """
    Saca las comillas que envuelven el valor, si estan.

    Los secrets de GitHub se guardan literalmente: no hay shell que interprete
    nada, asi que pegar "abc123" deja las comillas DENTRO del valor y el header
    sale como `Token "abc123"`. Ceres devuelve 401 y el mensaje no dice por que.
    Un token DRF nunca lleva comillas, asi que quitarlas no puede romper uno
    valido. Se avisa por stderr para que el problema quede visible en el log en
    vez de arreglarse en silencio.
    """
    for q in ('"', "'"):
        if len(tok) >= 2 and tok.startswith(q) and tok.endswith(q):
            sys.stderr.write(
                "ADVERTENCIA: el token venia entre comillas (%s). Se quitaron, "
                "pero conviene corregir el valor: en un secret de GitHub va el "
                "token solo, sin comillas ni el prefijo `Token `.\n" % q)
            return tok[1:-1].strip()
    return tok


def cargar_geometria():
    """N de sectores y equipos, y el bbox, desde geo_data.json."""
    global FARM_BBOX
    try:
        with io.open(GEO_PATH, "r", encoding="utf-8") as fh:
            geo = json.load(fh)
    except (IOError, OSError, ValueError) as exc:
        sys.stderr.write("ERROR: no se pudo leer geo_data.json (%s).\n"
                         "       Corre primero: python tools/kmz_to_geojson.py\n" % exc)
        sys.exit(1)
    for nivel, coleccion in LEVEL_GEO.items():
        LEVEL_N[nivel] = len(geo[coleccion]["features"])
    b = geo.get("bbox")
    if b and len(b) == 4:
        FARM_BBOX = (b[0], b[2], b[1], b[3])
    return geo


def cargar_predio(obligatorio=True):
    """Identificadores del predio, escritos por --discover."""
    global USER_ID, ADMIN_GROUP, FARM_NAME, CUSTOMER, FIELD_TO_EQUIPO
    if not os.path.exists(PREDIO_PATH):
        if not obligatorio:
            USER_ID = USER_ID_DEFAULT
            return None
        sys.stderr.write(
            "ERROR: falta %s.\n"
            "       Corre primero el descubrimiento, que es de solo lectura:\n"
            "           python tools/fetch_ceres.py --discover\n"
            % PREDIO_PATH_NAME)
        sys.exit(1)
    with io.open(PREDIO_PATH, "r", encoding="utf-8") as fh:
        p = json.load(fh)
    USER_ID = str(p.get("user_id") or USER_ID_DEFAULT)
    ADMIN_GROUP = p["admin_group"]
    FARM_NAME = p.get("farm_name") or FARM_NAME
    CUSTOMER = p.get("customer")
    LEVEL_GRID.clear()
    for nivel, gid in (p.get("grid_types") or {}).items():
        if gid is not None:
            LEVEL_GRID[nivel] = gid
    FIELD_TO_EQUIPO = {}
    for k, v in (p.get("field_to_equipo") or {}).items():
        try:
            FIELD_TO_EQUIPO[int(k)] = v
        except (TypeError, ValueError):
            FIELD_TO_EQUIPO[k] = v
    if not ADMIN_GROUP or not LEVEL_GRID:
        sys.stderr.write("ERROR: %s esta incompleto (falta admin_group o "
                         "grid_types).\n" % PREDIO_PATH_NAME)
        sys.exit(1)
    return p


def read_token():
    tok = unquote_token((os.environ.get("CERES_TOKEN") or "").strip())
    if tok:
        return tok
    if os.path.isfile(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r", encoding="utf-8") as fh:
                tok = unquote_token(fh.read().strip())
        except OSError as exc:
            sys.stderr.write("ERROR: no se pudo leer .ceres_token: %s\n" % exc)
            sys.exit(1)
        if tok:
            return tok
    sys.stderr.write(
        "ERROR: falta el token de Ceres.\n"
        "\n"
        "  Local:  pone el token en el archivo .ceres_token de la raiz del repo\n"
        "          (ya esta en .gitignore), o exporta CERES_TOKEN.\n"
        "  CI:     define el secret CERES_TOKEN en el repositorio.\n"
    )
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# HTTP
# ═══════════════════════════════════════════════════════════════════════════

class CeresError(Exception):
    """Falla de red o de la API tras agotar los reintentos."""


def api_get(session, path, params=None, retries=RETRIES):
    """GET con backoff exponencial. Nunca incluye el token en el mensaje."""
    url = BASE_URL + path
    last = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise CeresError(
                    "HTTP %d - el token fue rechazado por Ceres." % resp.status_code
                )
            last = "HTTP %d" % resp.status_code
        except CeresError:
            raise
        except requests.RequestException as exc:
            last = type(exc).__name__
        except ValueError:
            last = "respuesta no era JSON"
        if attempt < retries:
            wait = 2 ** (attempt - 1)
            sys.stderr.write("    reintento %d/%d en %ds (%s)\n"
                             % (attempt, retries - 1, wait, last))
            time.sleep(wait)
    raise CeresError(last or "sin respuesta")


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint 1 - vuelos
# ═══════════════════════════════════════════════════════════════════════════

def list_flights(session):
    """Semanas ISO con vuelo. Solo level 0: level 1 son subsemanas y duplican."""
    path = "/admin_groups/weeks/%s/%s/" % (
        USER_ID, urllib.parse.quote(ADMIN_GROUP, safe="")
    )
    raw = api_get(session, path)
    if isinstance(raw, list):
        weeks = raw
    else:
        weeks = raw.get("results") or raw.get("weeks") or []

    flights = []
    for wk in weeks:
        if not isinstance(wk, dict):
            continue
        if wk.get("level") != 0:
            continue
        key = wk.get("key")
        dates = [d for d in (wk.get("capture_dates") or []) if d]
        if not key or not dates:
            continue
        flights.append({
            "week_key": key,
            "date": max(dates),
            "capture_dates": sorted(dates),
        })

    flights.sort(key=lambda f: (f["date"], f["week_key"]))
    return flights


def season_of(date_str):
    """Temporada jul-jun en el formato de la casa: "2025-26"."""
    year, month = int(date_str[0:4]), int(date_str[5:7])
    start = year if month >= 7 else year - 1
    return "%d-%02d" % (start, (start + 1) % 100)


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint 2 - valores de un vuelo
# ═══════════════════════════════════════════════════════════════════════════

def flight_summary(session, week_key, grid_type_id):
    rows = api_get(session, "/tables/flight_summary/", params={
        "admin_group": ADMIN_GROUP,
        "week": week_key,
        "grid_type_id": grid_type_id,
    })
    if isinstance(rows, list):
        return rows
    return rows.get("results") or []


# ═══════════════════════════════════════════════════════════════════════════
# Endpoint 3 - umbrales publicados
# ═══════════════════════════════════════════════════════════════════════════

# flight_summary devuelve overlays "flacos": overlay_type, value, color, area,
# plants, capture_date. El colorMap con los cortes oficiales NO viene ahi: vive
# en download_urls de /api/overlays/. Por eso los umbrales se piden aparte.
# Ketcal tiene 32 vuelos x 5 indicadores x 5 campos: la primera corrida
# informo 1.440 overlays y el tope de 12 paginas solo alcanzo a leer 1.137. El
# catalogo alimenta los colorMap (con uno por indicador ya alcanza) pero tambien
# los ids de las capas de imagen, y ahi faltar paginas si se nota.
OVERLAYS_PAGE_CAP = 40


# ── Capa por arbol ──────────────────────────────────────────────────────────
#
# Verificado empiricamente contra el tiler antes de escribir nada, como exige el
# diseno: el endpoint NO pide Authorization (un token invalido tampoco lo rompe),
# responde con Access-Control-Allow-Origin: * y cachea 90 dias. Por eso el mapa
# puede consumir el MVT directo como source vectorial y NO hace falta
# pre-extraer nada ni inyectar el token con transformRequest, que en un sitio
# publico lo filtraria a cualquier visitante.
#
# El tile trae una capa "trees" de puntos, con `value` (el valor del indicador
# por arbol), `tree_id` y `varietal`. Como viene `value`, el mapa clasifica con
# las MISMAS bandas que el nivel sector y la leyenda no se parte en dos.
TREE_TILE_TEMPLATE = "https://tiler.ceresimaging.net/tree/data/{id}/{z}/{x}/{y}.mvt"
TREE_SOURCE_LAYER = "trees"


# ── Grilla de celdas ────────────────────────────────────────────────────────
#
# El mismo tiler publico sirve el indicador agregado en celdas, con la ruta
# /grid/{overlay}/{grid_type}/{z}/{x}/{y}.mvt. El grid_type es un entero de la
# misma familia que el 7 (sectores) y el 18 (equipos) que ya usa flight_summary;
# barriendo del 1 al 40 contra el tiler aparecen nueve escalones y el 26 es el de
# 1/8 de hectarea: celdas de 1.234 m2 medidos contra 1.250 nominales.
#
# Verificado contra la plataforma antes de escribir nada: los cinco equipos del
# vuelo del 23-03-2026 dan 1.277 celdas y 132,5 ha, que es exactamente la
# superficie que muestra Ceres para ese vuelo.
#
# Sin autorizacion, Access-Control-Allow-Origin: * y cache de 90 dias, igual que
# la capa por arbol. Sirve desde z10 y pesa 9-15 KB por equipo, asi que el mapa
# lo consume directo.
#
# El overlay que sirve NO es el mismo que el de la capa por arbol: hay que pedir
# el de source=grid_data. Con uno de source=tree_data el tiler responde HTTP 500.
GRID_TYPE_CELDAS = 26
GRID_CELL_HA = 0.125
GRID_SOURCE_LAYER = "grid"
GRID_MIN_ZOOM = 10
GRID_STATS_ZOOM = 13
# Solo estres acumulado: es el indicador que se lee por zona de riego y no por
# planta, y el unico que la plataforma muestra asi.
GRID_PARAM = "cumulative_thermal_stress"
GRID_TILE_TEMPLATE = ("https://tiler.ceresimaging.net/grid/{id}/%d/{z}/{x}/{y}.mvt"
                      % GRID_TYPE_CELDAS)


# ── Capas de imagen ─────────────────────────────────────────────────────────
#
# Las imagenes (source=geotiff) no tienen un valor por unidad, asi que no entran
# como indicador; pero como capa para mirar son otra cosa: la CIR muestra vigor y
# fallas de plantacion de un vistazo, la termica muestra el agua.
#
# El id del overlay NO sirve para pedirlas: /overlay/{overlay_id}/... responde
# "Resource Not Found". El que sirve esta dentro de download_urls y es otro UUID.
# Con ese, el tiler entrega tiles XYZ normales de 256x256, sin autorizacion,
# CORS abierto y cache de 90 dias.
IMAGERY_TILE_TEMPLATE = "https://tiler.ceresimaging.net/imagery/{id}/{z}/{x}/{y}.png"
# El grupo y la descripcion salen de la plataforma, para que el selector del mapa
# diga lo mismo que Ceres: la infrarroja va en Desarrollo de cultivos y la
# termica en Irrigacion, cada una al lado de los indicadores de su familia. No
# son un selector aparte: en la plataforma son una entrada mas de la misma lista.
#
# La RGB no aparece en ninguno de esos dos grupos, asi que donde va y como se
# describe es decision nuestra: se la pone con la infrarroja, que es la otra
# imagen del dosel.
IMAGERY_TYPES = OrderedDict([
    ("cir", {
        "es": "Infrarroja Color", "en": "Color infrared",
        "desc_es": "Suelo y vegetación", "desc_en": "Soil and vegetation",
        "group_es": "Desarrollo de cultivos", "group_en": "Crop development",
    }),
    ("core_thermal", {
        "es": "Térmica", "en": "Thermal",
        "desc_es": "Temperatura relativa", "desc_en": "Relative temperature",
        "group_es": "Irrigación", "group_en": "Irrigation",
    }),
    ("rgb", {
        "es": "Foto aérea", "en": "Aerial photo",
        "desc_es": "Imagen sin procesar", "desc_en": "Unprocessed image",
        "group_es": "Desarrollo de cultivos", "group_en": "Crop development",
    }),
])
IMAGERY_SOURCE = "geotiff"


def imagery_id_from(overlay):
    """
    Saca el id de imagen de download_urls. Es un UUID distinto del id del
    overlay, y es el unico que el tiler acepta. Se prueban las claves en orden de
    preferencia y se extrae el UUID de la URL en vez de guardar la URL entera,
    que trae parametros de query que no queremos fijar en el JSON.
    """
    du = overlay.get("download_urls") or {}
    if not isinstance(du, dict):
        return None
    for clave in ("ts_png", "png", "geotiff"):
        url = du.get(clave)
        if not url or not isinstance(url, str):
            continue
        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                      r"[0-9a-f]{4}-[0-9a-f]{12})", url)
        if m:
            return m.group(1)
    return None


def fetch_overlay_catalog(session, warn):
    """
    Un solo recorrido de /api/overlays/ que junta dos cosas:

      - el colorMap por overlay_type, para los umbrales publicados
      - el catalogo de overlays por arbol (source=tree_data), indexado por
        fecha de captura, indicador y equipo

    Se recorre completo y no se corta antes: season_average_ndvi no publica
    colorMap nunca, asi que un corte temprano igual no ahorraria paginas, y el
    catalogo de arboles necesita verlas todas.

    Devuelve (colormaps, trees, completo). `completo` es False si la API informa
    mas overlays de los que se pudieron leer: quien llama NO debe pisar datos
    buenos con un resultado parcial.
    """
    colormaps = {}
    cm_date = {}        # overlay_type -> capture_date del colorMap elegido
    trees = {}          # capture_date -> overlay_type -> {equipo: overlay_id}
    grids = {}          # capture_date -> {equipo: overlay_id}  (source=grid_data)
    imagery = {}        # capture_date -> tipo -> {equipo: imagery_id}
    # Cientos de overlays comparten capture_date, y con empates el orden entre
    # ellos es arbitrario: cada consulta corta las paginas en otro lugar, asi que
    # algunos registros se saltan y otros se repiten. Dos corridas daban
    # catalogos distintos (193 y 196 overlays).
    #
    # Ordenar por `id` seria el arreglo natural, pero la API lo rechaza con HTTP
    # 400: los campos de ordenamiento van por lista blanca. La via que si
    # funciona es sacar la paginacion del medio pidiendo todo en una respuesta.
    # Si el endpoint no acepta page_size, se cae a la paginacion de siempre y se
    # avisa de que el catalogo puede variar entre corridas.
    base = {"admin_group": ADMIN_GROUP, "ordering": "-capture_date"}
    esperado = None
    una_sola = False
    try:
        probe = api_get(session, "/overlays/", params=dict(base, page_size=1000),
                        retries=1)
        if isinstance(probe, dict):
            esperado = probe.get("count")
            if not probe.get("next"):
                una_sola = True
    except CeresError:
        probe = None
    params = dict(base, page_size=1000) if una_sola else dict(base)
    page, total = 1, 0
    vistos = set()
    while page <= OVERLAYS_PAGE_CAP:
        # La primera pagina va sin `page`: si el endpoint no estuviera paginado,
        # mandar el parametro podria hacerlo fallar sin necesidad.
        query = dict(params) if page == 1 else dict(params, page=page)
        try:
            payload = api_get(session, "/overlays/", params=query)
        except CeresError as exc:
            warn("no se pudo leer /overlays/ pagina %d (%s); los umbrales y el "
                 "catalogo de arboles pueden quedar incompletos." % (page, exc))
            break

        if isinstance(payload, list):
            rows, has_next = payload, False
        else:
            rows = payload.get("results") or []
            has_next = bool(payload.get("next"))
            if esperado is None:
                esperado = payload.get("count")
        total += len(rows)

        for overlay in rows:
            oid = overlay.get("id")
            if oid is not None:
                if oid in vistos:
                    continue          # ya visto: no se cuenta dos veces
                vistos.add(oid)
            otype = overlay.get("overlay_type")
            equipo = FIELD_TO_EQUIPO.get(overlay.get("field_id"))
            date = overlay.get("capture_date") or ""
            # Las imagenes van primero: no son indicadores, asi que el
            # filtro por PARAMS de mas abajo las descartaria.
            if (otype in IMAGERY_TYPES and equipo and date
                    and overlay.get("source") == IMAGERY_SOURCE):
                iid = imagery_id_from(overlay)
                if iid:
                    imagery.setdefault(date, {}).setdefault(otype, {})[equipo] = iid
            if not otype or otype not in PARAMS:
                continue
            # Se conserva el colorMap del overlay MAS RECIENTE, no el primero que
            # aparezca: ordenando por id el orden ya no es cronologico.
            if date >= cm_date.get(otype, ""):
                bands = extract_colormap(overlay)
                if bands:
                    colormaps[otype] = bands
                    cm_date[otype] = date
            # Catalogo de grilla: mismo indicador, otro source.
            if (otype == GRID_PARAM and overlay.get("source") == "grid_data"
                    and oid and date and equipo):
                grids.setdefault(date, {})[equipo] = str(oid)
            # Catalogo por arbol
            if overlay.get("source") != "tree_data":
                continue
            if not oid or not date or not equipo:
                continue
            trees.setdefault(date, {}).setdefault(otype, {})[equipo] = str(oid)

        if not rows or not has_next:
            break
        page += 1

    # `total` cuenta filas devueltas y `vistos` overlays distintos. La API informa
    # cuantos hay: si no coinciden, el recorrido quedo incompleto y hay que
    # decirlo, no seguir como si nada.
    print("  overlays revisados: %d de %s (%d distintos%s)"
          % (total, esperado if esperado is not None else "?", len(vistos),
             ", en una sola respuesta" if una_sola else ", paginado"))
    completo = (esperado is None) or (len(vistos) >= esperado)
    if total != len(vistos):
        warn("la paginacion devolvio %d filas para %d overlays distintos: hay "
             "duplicados." % (total, len(vistos)))
    if esperado is not None and len(vistos) < esperado:
        warn("solo se leyeron %d de los %d overlays que informa la API. Con "
             "ordering=-capture_date y cientos de fechas empatadas la paginacion "
             "no es estable, asi que el catalogo puede variar entre corridas."
             % (len(vistos), esperado))
    if page > OVERLAYS_PAGE_CAP:
        warn("se alcanzo el tope de %d paginas de /overlays/: el catalogo puede "
             "estar incompleto." % OVERLAYS_PAGE_CAP)
    print("  umbrales: %d/%d indicadores con colorMap%s"
          % (len(colormaps), len(PARAMS),
             "" if len(colormaps) == len(PARAMS)
             else " (faltan: %s)" % ", ".join(p for p in PARAMS if p not in colormaps)))
    n_ids = sum(len(e) for d in trees.values() for e in d.values())
    print("  capa por arbol: %d overlays en %d fechas" % (n_ids, len(trees)))
    n_grid = sum(len(e) for e in grids.values())
    print("  grilla de %g ha: %d overlays en %d fechas"
          % (GRID_CELL_HA, n_grid, len(grids)))
    n_img = sum(len(e) for d in imagery.values() for e in d.values())
    print("  imagenes: %d en %d fechas (%s)"
          % (n_img, len(imagery),
             ", ".join("%s=%d" % (t, sum(len(d.get(t) or {})
                                         for d in imagery.values()))
                       for t in IMAGERY_TYPES)))
    return colormaps, trees, grids, imagery, completo


# Bbox del predio, para saber que tiles pedir. Sale del GEOJSON de index.html;
# se deja fijo porque los 23 sectores no se mueven.
# lon0, lon1, lat0, lat1. Sale del bbox de geo_data.json en vez de estar
# escrito a mano: si el KMZ cambia, el bbox lo sigue solo.
FARM_BBOX = (-71.228078, -71.213176, -30.025189, -30.003220)
TREE_STATS_ZOOM = 16


def farm_tiles(z):
    import math
    lon0, lon1, lat0, lat1 = FARM_BBOX

    def xy(lon, lat):
        n = 2 ** z
        r = math.radians(lat)
        return (int((lon + 180.0) / 360.0 * n),
                int((1.0 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2.0 * n))

    x0, y0 = xy(lon0, lat1)
    x1, y1 = xy(lon1, lat0)
    return [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]


def decode_tree_tiles(session, overlay_ids, warn):
    """
    Decodifica los tiles de un conjunto de overlays por arbol y devuelve
    (valores, variedades). Requiere mapbox-vector-tile; si falta, avisa y
    devuelve vacio en vez de abortar: la capa por arbol sigue funcionando, lo que
    se pierde son las clases sobre arboles y el inventario de variedades.
    """
    try:
        import mapbox_vector_tile
    except ImportError:
        warn("falta la dependencia `mapbox-vector-tile`: no se pueden calcular "
             "clases sobre arboles ni contar variedades. Instalala con "
             "`pip install mapbox-vector-tile`.")
        return None, None

    vals, varieties = [], {}
    tiles = farm_tiles(TREE_STATS_ZOOM)
    for oid in overlay_ids:
        base = TREE_TILE_TEMPLATE.replace("{id}", oid)
        for x, y in tiles:
            url = (base.replace("{z}", str(TREE_STATS_ZOOM))
                       .replace("{x}", str(x)).replace("{y}", str(y)))
            try:
                # El tiler es publico: va sin el header de autorizacion.
                resp = requests.get(url, timeout=TIMEOUT)
            except requests.RequestException:
                continue
            if resp.status_code != 200 or not resp.content:
                continue
            try:
                dec = mapbox_vector_tile.decode(resp.content)
            except Exception:
                continue
            layer = dec.get(TREE_SOURCE_LAYER)
            if not layer:
                continue
            for feat in layer.get("features") or []:
                pr = feat.get("properties") or {}
                v = pr.get("value")
                if v is not None:
                    try:
                        vals.append(float(v))
                    except (TypeError, ValueError):
                        pass
                var = pr.get("varietal")
                if var:
                    varieties[var] = varieties.get(var, 0) + 1
    return vals, varieties


def compute_tree_stats(session, trees, flights, params, warn):
    """
    Dos cosas, en una sola pasada de decodificacion:

      - clases de los indicadores RELATIVOS calculadas sobre la distribucion de
        ARBOLES. Los cortes de sectores no sirven ahi: son promedios agrupados en
        una franja angosta, y medido sobre el vuelo del 23-mar-2026 dejaban 77%
        de los 34.073 arboles en una sola clase.
      - el inventario de variedades del predio, que alimenta la vista por
        variedad del mapa.

    Solo se decodifican los vuelos que hagan falta: el inventario se toma del
    vuelo mas reciente, porque la variedad de un arbol no cambia.
    """
    if not trees:
        return
    relativos = [p for p in params if p.get("bands_source") == "relative"]
    bf = trees["by_flight"]

    # Inventario de variedades: el vuelo mas reciente que tenga overlays.
    for wk in reversed(list(bf.keys())):
        per = bf[wk]
        pid = next((k for k in per if per[k]), None)
        if not pid:
            continue
        print("  variedades: decodificando %s / %s..." % (wk, pid))
        _, varieties = decode_tree_tiles(session, list(per[pid].values()), warn)
        if varieties:
            orden = sorted(varieties, key=lambda k: -varieties[k])
            trees["varieties"] = OrderedDict([
                ("source_flight", wk),
                ("order", orden),
                ("counts", OrderedDict((k, varieties[k]) for k in orden)),
            ])
            print("    %s" % ", ".join("%s=%d" % (k, varieties[k]) for k in orden))
        break

    if not relativos:
        return
    by_wk = {f["week_key"]: f for f in flights}
    for wk, per in bf.items():
        flight = by_wk.get(wk)
        if not flight:
            continue
        out = OrderedDict()
        for param in relativos:
            eqs = per.get(param["id"])
            if not eqs:
                continue
            print("  clases sobre arboles: %s / %s..." % (wk, param["id"]))
            vals, _ = decode_tree_tiles(session, list(eqs.values()), warn)
            if not vals:
                continue
            cuts = quantile_cuts(vals, PARAMS[param["id"]].get("n_classes", 4))
            if not cuts:
                warn("vuelo %s / %s: no se pudieron calcular clases sobre arboles."
                     % (wk, param["id"]))
                continue
            out[param["id"]] = label_bands(
                bands_from_cuts(cuts), PARAMS[param["id"]]["higher_is_better"],
                PARAMS[param["id"]].get("labels"))
            print("    %d arboles -> cortes %s"
                  % (len(vals), " / ".join("%.4f" % c for c in cuts)))
        if out:
            flight["relative_bands_trees"] = out


def week_matcher(flights):
    """
    Devuelve una funcion fecha_de_captura -> week_key.

    Las fechas de captura de un vuelo pueden ser mas de una (2022-11-14/15) y el
    vuelo guarda la mas reciente, asi que se acepta cualquier fecha a <=3 dias.
    Lo usan los tres catalogos que se indexan por vuelo: arboles, grilla e
    imagenes.
    """
    by_date = {f["date"]: f["week_key"] for f in flights}

    def week_for(date):
        if date in by_date:
            return by_date[date]
        for d, wk in by_date.items():
            try:
                if abs((datetime.strptime(d, "%Y-%m-%d")
                        - datetime.strptime(date, "%Y-%m-%d")).days) <= 3:
                    return wk
            except ValueError:
                continue
        return None

    return week_for


def build_trees(trees_raw, flights, warn):
    """
    Arma el bloque `trees` del JSON: la plantilla del tiler y, por vuelo e
    indicador, el overlay de cada equipo. Se indexa por week_key para que el mapa
    lo cruce con el vuelo activo sin recorrer nada.
    """
    if not trees_raw:
        return None
    week_for = week_matcher(flights)
    out = OrderedDict()
    huerfanos = 0
    for date in sorted(trees_raw):
        wk = week_for(date)
        if not wk:
            huerfanos += 1
            continue
        bucket = out.setdefault(wk, OrderedDict())
        for otype in PARAMS:
            eqs = (trees_raw[date] or {}).get(otype)
            if not eqs:
                continue
            dest = bucket.setdefault(otype, OrderedDict())
            for eq in sorted(eqs, key=equipo_num):
                dest[eq] = eqs[eq]
    if huerfanos:
        warn("%d fecha(s) de overlays por arbol no calzaron con ningun vuelo; "
             "se omiten." % huerfanos)
    # Aviso si un vuelo trae arboles de algunos equipos y no de los cinco.
    for wk, per in out.items():
        for otype, eqs in per.items():
            if len(eqs) != LEVEL_N.get("equipos"):
                warn("vuelo %s / %s: capa por arbol con %d de %d equipos."
                     % (wk, otype, len(eqs), LEVEL_N.get("equipos")))
    if not out:
        return None
    return OrderedDict([
        ("tile_template", TREE_TILE_TEMPLATE),
        ("source_layer", TREE_SOURCE_LAYER),
        ("value_property", "value"),
        # El tiler es publico y CORS abierto: verificado, no lleva credencial.
        ("requires_auth", False),
        ("min_zoom", 15),
        ("by_flight", out),
    ])


GRID_BANDS = 10          # bandas de 0,1 entre 0 y 1, como la leyenda de Ceres


def grid_band_of(value):
    """Indice de banda 0..9. El 1,0 exacto cae en la ultima, no afuera."""
    return min(max(int(float(value) * GRID_BANDS), 0), GRID_BANDS - 1)


def decode_grid_tiles(overlay_ids, warn):
    """
    Decodifica los tiles de grilla de un vuelo y devuelve la lista de celdas con
    sus propiedades (value, color, area, plants).

    Una celda del borde aparece en dos tiles vecinos, asi que se deduplica por
    (overlay, id de celda): sin eso la superficie sale inflada.
    """
    try:
        import mapbox_vector_tile
    except ImportError:
        warn("falta la dependencia `mapbox-vector-tile`: no se puede calcular la "
             "leyenda de la grilla. Instalala con `pip install mapbox-vector-tile`.")
        return None

    celdas = []
    tiles = farm_tiles(GRID_STATS_ZOOM)
    for oid in overlay_ids:
        vistos = set()
        base = GRID_TILE_TEMPLATE.replace("{id}", oid)
        for x, y in tiles:
            url = (base.replace("{z}", str(GRID_STATS_ZOOM))
                       .replace("{x}", str(x)).replace("{y}", str(y)))
            try:
                # El tiler es publico: va sin el header de autorizacion.
                resp = requests.get(url, timeout=TIMEOUT)
            except requests.RequestException:
                continue
            if resp.status_code != 200 or not resp.content:
                continue
            try:
                dec = mapbox_vector_tile.decode(resp.content)
            except Exception:
                continue
            layer = dec.get(GRID_SOURCE_LAYER)
            if not layer:
                continue
            for feat in layer.get("features") or []:
                pr = feat.get("properties") or {}
                cid = pr.get("id")
                if cid is not None:
                    if cid in vistos:
                        continue
                    vistos.add(cid)
                celdas.append(pr)
    return celdas


def compute_grid_stats(grid, warn, solo=None):
    """
    Por cada vuelo con grilla: cuenta celdas, superficie y plantas, y arma el
    histograma por banda de 0,1 que alimenta la leyenda.

    De paso deriva la rampa. El tile trae el `color` de cada celda, y se verifico
    contra el tiler -sobre las 1.277 celdas del vuelo del 23-03-2026 mas las de
    enero- que ese color es funcion limpia del valor en bandas de 0,1: ni una
    celda cruza banda. Asi la leyenda no inventa ningun color, usa el que manda
    Ceres. Si dos colores distintos cayeran en la misma banda se avisa, porque
    querria decir que la rampa cambio y la leyenda dejo de ser fiel.

    `solo` limita el recalculo a esos week_key; el resto se conserva.
    """
    por_banda = {}          # banda -> {color: celdas}
    for wk in sorted(grid["by_flight"]):
        if solo is not None and wk not in solo:
            # Se conserva lo ya calculado, pero la rampa igual necesita los
            # colores: se releen del histograma guardado.
            for ent in (grid["stats"].get(wk) or {}).get("hist") or []:
                if ent.get("color") and ent.get("cells"):
                    por_banda.setdefault(ent["band"], {})[ent["color"]] = (
                        por_banda.setdefault(ent["band"], {}).get(ent["color"], 0)
                        + ent["cells"])
            continue
        eqs = grid["by_flight"][wk]
        celdas = decode_grid_tiles([eqs[e] for e in sorted(eqs, key=equipo_num)], warn)
        if celdas is None:
            return False
        hist = [{"band": i, "cells": 0, "area_m2": 0, "color": None}
                for i in range(GRID_BANDS)]
        area = plants = 0
        n = 0
        for c in celdas:
            v = c.get("value")
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            b = grid_band_of(v)
            a = c.get("area") or 0
            hist[b]["cells"] += 1
            hist[b]["area_m2"] += a
            area += a
            plants += c.get("plants") or 0
            n += 1
            col = c.get("color")
            if col:
                por_banda.setdefault(b, {})[col] = por_banda.setdefault(b, {}).get(col, 0) + 1
        if not n:
            warn("vuelo %s: la grilla no devolvio ninguna celda con valor." % wk)
            continue
        grid["stats"][wk] = OrderedDict([
            ("cells", n),
            ("area_ha", round(area / 10000.0, 2)),
            ("plants", plants),
            ("hist", hist),
        ])
        print("    %s: %d celdas, %.1f ha, %d plantas"
              % (wk, n, area / 10000.0, plants))

    # Rampa: un color por banda, el mas frecuente si hubiera mas de uno.
    ramp = []
    for b in range(GRID_BANDS):
        cols = por_banda.get(b) or {}
        if len(cols) > 1:
            warn("la banda %.1f-%.1f de la grilla aparece con %d colores "
                 "distintos (%s): la rampa de Ceres cambio y la leyenda puede "
                 "no coincidir con el mapa."
                 % (b / 10.0, b / 10.0 + 0.1, len(cols),
                    ", ".join(sorted(cols))))
        if not cols:
            continue
        color = max(cols, key=lambda c: cols[c])
        ramp.append(OrderedDict([("band", b), ("min", round(b / 10.0, 2)),
                                 ("max", round(b / 10.0 + 0.1, 2)),
                                 ("color", color)]))
    grid["ramp"] = ramp
    # El color de cada banda se anota en el histograma para que la leyenda de un
    # vuelo se pinte sin cruzar estructuras.
    por_b = {r["band"]: r["color"] for r in ramp}
    for wk in grid["stats"]:
        for ent in grid["stats"][wk]["hist"]:
            ent["color"] = por_b.get(ent["band"])
    faltan = [b for b in range(GRID_BANDS) if b not in por_b]
    print("  rampa de la grilla: %d de %d bandas observadas%s"
          % (len(ramp), GRID_BANDS,
             "" if not faltan
             else " (sin datos en %s)" % ", ".join("%.1f-%.1f" % (b / 10.0, b / 10.0 + 0.1)
                                                   for b in faltan)))
    return True


def build_grid(grids_raw, flights, warn):
    """
    Arma el bloque `grid`: la plantilla del tiler y, por vuelo, el overlay de
    cada equipo. Un solo indicador y un solo tamano de celda, asi que la
    estructura es un nivel mas plana que la de `trees`.
    """
    if not grids_raw:
        return None
    week_for = week_matcher(flights)
    out = OrderedDict()
    huerfanos = 0
    for date in sorted(grids_raw):
        wk = week_for(date)
        if not wk:
            huerfanos += 1
            continue
        eqs = grids_raw[date] or {}
        dest = out.setdefault(wk, OrderedDict())
        for eq in sorted(eqs, key=equipo_num):
            dest[eq] = eqs[eq]
    if huerfanos:
        warn("%d fecha(s) de overlays de grilla no calzaron con ningun vuelo; "
             "se omiten." % huerfanos)
    for wk, eqs in out.items():
        if len(eqs) != LEVEL_N.get("equipos"):
            warn("vuelo %s: grilla con %d de %d equipos." % (wk, len(eqs), LEVEL_N.get("equipos")))
    if not out:
        return None
    return OrderedDict([
        ("tile_template", GRID_TILE_TEMPLATE),
        ("source_layer", GRID_SOURCE_LAYER),
        ("value_property", "value"),
        ("color_property", "color"),
        ("param", GRID_PARAM),
        ("grid_type", GRID_TYPE_CELDAS),
        ("cell_ha", GRID_CELL_HA),
        # El tiler es publico y CORS abierto: verificado, no lleva credencial.
        ("requires_auth", False),
        ("min_zoom", GRID_MIN_ZOOM),
        ("bands", GRID_BANDS),
        ("ramp", []),
        ("stats", OrderedDict()),
        ("by_flight", out),
    ])


def build_imagery(imagery_raw, flights, warn):
    """
    Arma el bloque `imagery`: por vuelo y tipo, el id de imagen de cada equipo.
    Son tiles PNG XYZ comunes, asi que el mapa los usa como source raster.
    """
    if not imagery_raw:
        return None
    week_for = week_matcher(flights)
    out = OrderedDict()
    huerfanos = 0
    for date in sorted(imagery_raw):
        wk = week_for(date)
        if not wk:
            huerfanos += 1
            continue
        bucket = out.setdefault(wk, OrderedDict())
        for otype in IMAGERY_TYPES:
            eqs = (imagery_raw[date] or {}).get(otype)
            if not eqs:
                continue
            dest = bucket.setdefault(otype, OrderedDict())
            for eq in sorted(eqs, key=equipo_num):
                dest[eq] = eqs[eq]
    if huerfanos:
        warn("%d fecha(s) de imagenes no calzaron con ningun vuelo; se omiten."
             % huerfanos)
    # Un vuelo con imagenes de algunos equipos y no de los cinco se pinta a
    # medias, que es peor que no pintarse: conviene saberlo.
    for wk, per in out.items():
        for otype, eqs in per.items():
            if len(eqs) != LEVEL_N.get("equipos"):
                warn("vuelo %s / %s: imagen con %d de %d equipos."
                     % (wk, otype, len(eqs), LEVEL_N.get("equipos")))
    if not out:
        return None
    return OrderedDict([
        ("tile_template", IMAGERY_TILE_TEMPLATE),
        # Igual que los otros dos: verificado, no lleva credencial.
        ("requires_auth", False),
        ("types", [OrderedDict([("id", t)] + [(k, IMAGERY_TYPES[t][k])
                                for k in ("es", "en", "desc_es", "desc_en",
                                          "group_es", "group_en")])
                   for t in IMAGERY_TYPES]),
        ("by_flight", out),
    ])


def inspect_overlays(session):
    """
    Diagnostico: imprime la forma de los overlays de /api/overlays/ para poder
    ajustar el parseo si Ceres cambia el esquema. Nunca imprime una URL
    completa (pueden venir firmadas): solo host, path y NOMBRES de parametros.
    El unico valor que muestra es colorMap, que son umbrales, no una credencial.
    """
    payload = api_get(session, "/overlays/", params={
        # Igual que el catalogo: se ordena por `id` para que la paginacion sea
        # reproducible. Con -capture_date hay empates y las paginas se cortan
        # distinto en cada consulta.
        "admin_group": ADMIN_GROUP, "ordering": "id",
    })
    rows = payload if isinstance(payload, list) else (payload.get("results") or [])
    if not isinstance(payload, list):
        print("paginado: count=%r next=%s" % (payload.get("count"),
                                             bool(payload.get("next"))))
    print("overlays en la primera pagina: %d" % len(rows))

    tipos = {}
    for overlay in rows:
        tipos.setdefault(overlay.get("overlay_type"), 0)
        tipos[overlay.get("overlay_type")] += 1
    print("overlay_type presentes: %s" % json.dumps(tipos, ensure_ascii=False, indent=2))

    shown = set()
    for overlay in rows:
        otype = overlay.get("overlay_type")
        if otype not in PARAMS or otype in shown:
            continue
        shown.add(otype)
        print("")
        print("── %s ─────────────────────────────────" % otype)
        print("  claves del overlay: %s" % sorted(overlay.keys()))
        urls = overlay.get("download_urls")
        print("  download_urls es %s" % type(urls).__name__)
        cands = []
        if isinstance(urls, dict):
            print("  sus claves: %s" % sorted(urls.keys()))
            cands = [(k, v) for k, v in urls.items() if isinstance(v, str)]
        elif isinstance(urls, list):
            cands = [(i, v) for i, v in enumerate(urls) if isinstance(v, str)]
        elif isinstance(urls, str):
            cands = [("(str)", urls)]
        for name, url in cands:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            print("    [%s] %s%s  params=%s" % (name, parsed.netloc, parsed.path,
                                                sorted(qs.keys())))
            if "colorMap" in qs:
                print("       colorMap = %s" % qs["colorMap"][0])
        bands = extract_colormap(overlay)
        print("  -> extract_colormap: %s" % (bands if bands else "NADA"))
        if len(shown) >= len(PARAMS):
            break

    audit_colormaps(session)


def audit_colormaps(session):
    """
    Recorre TODOS los overlays y junta los colorMap distintos por overlay_type.
    Contesta la pregunta que decide la politica de bandas: los cortes de un
    indicador son fijos, o cambian de vuelo en vuelo?

      1 colorMap distinto  -> escala fija; los cortes son candidatos a umbral.
      N colorMaps distintos -> se recalculan por vuelo; NO son umbrales, porque
                               el mismo valor caeria en categorias distintas
                               segun que vuelo definio la escala.
    """
    print("")
    print("=" * 70)
    print("AUDITORIA: cuantos colorMap distintos publica cada indicador")
    print("=" * 70)

    vistos = {}          # overlay_type -> {firma: [fechas]}
    page, total = 1, 0
    while page <= OVERLAYS_PAGE_CAP:
        query = {"admin_group": ADMIN_GROUP, "ordering": "id"}
        if page > 1:
            query["page"] = page
        try:
            payload = api_get(session, "/overlays/", params=query)
        except CeresError as exc:
            print("  (corte en la pagina %d: %s)" % (page, exc))
            break
        if isinstance(payload, list):
            rows, has_next = payload, False
        else:
            rows = payload.get("results") or []
            has_next = bool(payload.get("next"))
        total += len(rows)
        for overlay in rows:
            otype = overlay.get("overlay_type")
            if otype not in PARAMS:
                continue
            bands = extract_colormap(overlay)
            if not bands:
                continue
            firma = json.dumps([[b["min"], b["max"]] for b in bands])
            vistos.setdefault(otype, {}).setdefault(firma, []).append(
                overlay.get("capture_date") or "?")
        if not rows or not has_next:
            break
        page += 1

    print("overlays revisados: %d" % total)
    for otype in PARAMS:
        firmas = vistos.get(otype) or {}
        if not firmas:
            print("")
            print("  %-27s ningun colorMap publicado" % otype)
            continue
        print("")
        print("  %-27s %d colorMap distinto(s) en %d overlays"
              % (otype, len(firmas), sum(len(v) for v in firmas.values())))
        for firma, fechas in sorted(firmas.items(), key=lambda kv: -len(kv[1])):
            cortes = [round(x[0], 4) for x in json.loads(firma)]
            cortes.append(round(json.loads(firma)[-1][1], 4))
            print("      %d overlays  cortes=%s" % (len(fechas), cortes))
            print("                  fechas=%s%s"
                  % (", ".join(sorted(set(fechas))[:4]),
                     " ..." if len(set(fechas)) > 4 else ""))
        print("      => %s" % verdict(firmas))


def verdict(firmas):
    """
    Veredicto sobre un conjunto de colorMap observados.

    Un test de "uno contra muchos" es demasiado grosero: absolute_ndvi publica
    dos firmas que difieren SOLO en el piso del primer tramo (-1.0 vs 0.0) y
    tienen los cortes interiores identicos, o sea es una escala fija con una
    variante cosmetica, no una escala recalculada. Por eso se comparan tambien
    los cortes interiores, y se marca por separado la uniformidad: una rampa de
    tramos iguales es una eleccion de despliegue, no una clasificacion.
    """
    n_over = sum(len(v) for v in firmas.values())
    cortes = [json.loads(f) for f in firmas]

    # Cortes interiores: los extremos del rango son los que suelen variar.
    interiores = {tuple(round(x[0], 4) for x in c[1:]) for c in cortes}

    if len(firmas) == 1:
        base = "ESCALA FIJA"
    elif len(interiores) == 1:
        base = ("ESCALA FIJA con %d variantes solo en los extremos" % len(firmas))
    elif len(firmas) >= n_over * 0.5:
        return ("SE RECALCULA POR OVERLAY (%d firmas en %d overlays) -> "
                "no son umbrales: el mismo valor cambiaria de categoria segun "
                "el campo y el vuelo" % (len(firmas), n_over))
    else:
        return ("VARIA ENTRE VUELOS (%d firmas) -> no son umbrales"
                % len(firmas))

    # Escala fija: falta decidir si es clasificacion o rampa de despliegue.
    anchos = [round(x[1] - x[0], 4) for x in cortes[0]]
    interior = anchos[1:-1] if len(anchos) > 2 else anchos
    uniforme = len(set(interior)) == 1
    if uniforme and len(anchos) > 5:
        return ("%s, pero es una RAMPA de %d tramos iguales de %s -> eleccion de "
                "despliegue, no umbrales agronomicos"
                % (base, len(anchos), interior[0]))
    return "%s -> los cortes son candidatos a umbral" % base


# Prefijo de cuartel por especie, igual que en kmz_to_geojson.py: la numeracion
# C1..Cn se repite entre especies, asi que el numero solo NO es una clave.
ESPECIE_PREFIJO = {"limoneros": "LIM", "naranjos": "NAR", "mandarinos": "MAN"}

RE_CERES_SECTOR = re.compile(r"^E\s*(\d+)\s*-\s*S\s*(\d+)$", re.I)
RE_CERES_CUARTEL = re.compile(r"^(limoneros|naranjos|mandarinos)\s*-\s*C\s*(\d+)$", re.I)
RE_CERES_EQUIPO = re.compile(r"equipo\s*(\d+)", re.I)


def unit_key(row, level):
    """
    Clave de la unidad, normalizada a las claves del repo.

    Ceres nombra cada grilla a su manera y NINGUNA coincide con las claves de
    geo_data.json, asi que hay que normalizar los tres formatos. Verificado
    contra el vuelo 2026.16.A: las 63 claves (28+5+30) mapean sin faltantes ni
    sobrantes.

        sectores   "E1 - S2"            -> "E1-S2"    (sobran los espacios)
        cuarteles  "Naranjos- C12"      -> "NAR-C12"  (especie a prefijo)
        equipos    "equipo 3 naranjos"  -> "E3"       (no es un codigo, es el
                                                       nombre del campo)

    Se devuelve None si no se reconoce, y quien llama lo registra como
    advertencia en vez de inventar una clave.
    """
    block = (row.get("block_name") or "").strip()

    if level == "sectors":
        m = RE_CERES_SECTOR.match(block)
        return "E%d-S%d" % (int(m.group(1)), int(m.group(2))) if m else None

    if level == "cuarteles":
        m = RE_CERES_CUARTEL.match(block)
        if not m:
            return None
        return "%s-C%d" % (ESPECIE_PREFIJO[m.group(1).lower()], int(m.group(2)))

    # equipos: el block_name es el nombre del campo ("equipo 3 naranjos"). Se
    # intenta leer el numero de ahi y, si no, se cae a la tabla field_id ->
    # equipo que dejo el descubrimiento.
    for texto in (block, row.get("field_name")):
        if not texto:
            continue
        m = RE_CERES_EQUIPO.search(str(texto)) or re.search(r"\bE(\d+)\b", str(texto))
        if m:
            return "E%d" % int(m.group(1))
    return FIELD_TO_EQUIPO.get(row.get("field_id"))


def extract_colormap(overlay):
    """
    Las bandas oficiales del indicador viajan URL-encoded en el parametro
    colorMap de alguna de las URLs de download_urls. Formato [color, min, max].
    Devuelve [{"min":.., "max":..}] ordenado ascendente, o None.
    """
    urls = overlay.get("download_urls")
    candidates = []
    if isinstance(urls, dict):
        candidates = [v for v in urls.values() if isinstance(v, str)]
    elif isinstance(urls, list):
        for item in urls:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                candidates.extend(v for v in item.values() if isinstance(v, str))
    elif isinstance(urls, str):
        candidates = [urls]

    for url in candidates:
        query = urllib.parse.urlparse(url).query
        raw = urllib.parse.parse_qs(query).get("colorMap")
        if not raw:
            continue
        try:
            parsed = json.loads(raw[0])
        except (ValueError, IndexError):
            continue
        bands = []
        for entry in parsed:
            if not isinstance(entry, (list, tuple)) or len(entry) < 3:
                continue
            try:
                lo, hi = float(entry[1]), float(entry[2])
            except (TypeError, ValueError):
                continue
            if hi < lo:
                lo, hi = hi, lo
            bands.append({"min": lo, "max": hi})
        if bands:
            bands.sort(key=lambda b: b["min"])
            return bands
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Bandas -> params
# ═══════════════════════════════════════════════════════════════════════════

def label_bands(raw_bands, higher_is_better, labels_spec=None):
    """
    Ordena las bandas por valor ascendente y les cuelga severidad, codigo de
    estado y etiqueta es/en. severity 0 = mejor: si el indicador es "alto =
    peor", la severidad crece con el valor; si es "alto = mejor", decrece. El
    mapa pinta por severidad, no por el orden del arreglo.

    labels_spec:
      None            -> etiquetas genericas por cantidad de bandas
      "ranges"        -> el rango numerico como etiqueta ("<0,50", "0,50–0,55")
      <clave>         -> etiquetas de la plataforma, indexadas por severidad
    """
    bands = sorted(raw_bands, key=lambda b: b["min"])
    n = len(bands)
    ladder = STATUS_LADDER.get(n)

    # Etiquetas por severidad. Las de rango se resuelven por posicion de valor,
    # no por severidad, asi que se calculan aparte.
    by_severity = None
    by_value = None
    if labels_spec == "ranges":
        cuts = [b["min"] for b in bands] + [bands[-1]["max"]]
        by_value = range_labels(cuts)
    elif labels_spec == "relative":
        # Por posicion de valor, no por severidad: "1 - Mas bajo" es el valor mas
        # bajo del vuelo, cualquiera sea la direccion del indicador.
        by_value = relative_labels(n)
    elif labels_spec and labels_spec in PLATFORM_LABELS:
        cand = PLATFORM_LABELS[labels_spec]
        if len(cand) == n:
            by_severity = cand
    if by_severity is None and by_value is None:
        by_severity = BAND_LABELS.get(n)

    out = []
    for idx, band in enumerate(bands):
        severity = (n - 1 - idx) if higher_is_better else idx
        # El status solo existe para clasificar en compliance; con mas bandas que
        # la escalera de estados se cae a un codigo numerico, que igual es unico.
        status = ladder[severity] if ladder else ("b%d" % severity)
        if by_value is not None:
            es, en = by_value[idx]
        elif by_severity is not None:
            es, en = by_severity[severity]
        else:
            es = en = "%s - %s" % (band["min"], band["max"])
        out.append(OrderedDict([
            ("min", round(band["min"], 6)),
            ("max", round(band["max"], 6)),
            ("es", es),
            ("en", en),
            ("status", status),
            ("severity", severity),
        ]))
    return out


def bands_from_cuts(cuts):
    return [{"min": cuts[i], "max": cuts[i + 1]} for i in range(len(cuts) - 1)]


def quantile_cuts(values, n_classes):
    """
    Cortes por cuantiles sobre los valores de UN vuelo. Devuelve n_classes+1
    limites. Si hay empates y un corte se repite, se colapsa: es mejor entregar
    menos clases que dos bandas de ancho cero.
    """
    vals = sorted(v for v in values if v is not None)
    if len(vals) < 2:
        return None
    lo, hi = vals[0], vals[-1]
    if hi <= lo:
        return None
    cuts = [lo]
    for i in range(1, n_classes):
        pos = (len(vals) - 1) * i / float(n_classes)
        lower = int(pos)
        frac = pos - lower
        upper = min(lower + 1, len(vals) - 1)
        cuts.append(vals[lower] + (vals[upper] - vals[lower]) * frac)
    cuts.append(hi)
    out = [cuts[0]]
    for c in cuts[1:]:
        if c > out[-1] + 1e-9:
            out.append(c)
    return out if len(out) >= 3 else None


def compute_relative_bands(flights, params, warn):
    """
    Para los indicadores relativos, los cortes se recalculan en CADA vuelo y por
    nivel, igual que hace la plataforma. Van dentro del vuelo y no del indicador,
    porque no son los mismos entre fechas.
    """
    rel = [p for p in params if p.get("bands_source") == "relative"]
    if not rel:
        return
    meta = {pid: PARAMS[pid] for pid in PARAMS}
    for flight in flights:
        out = OrderedDict()
        for param in rel:
            pid = param["id"]
            per_level = OrderedDict()
            for level in niveles_activos():
                vals = [v.get(pid) for v in (flight.get(level) or {}).values()]
                vals = [v for v in vals if v is not None]
                cuts = quantile_cuts(vals, meta[pid].get("n_classes", 4))
                if not cuts:
                    continue
                per_level[level] = label_bands(
                    bands_from_cuts(cuts), meta[pid]["higher_is_better"],
                    meta[pid].get("labels"))
            if per_level:
                out[pid] = per_level
            else:
                warn("vuelo %s / %s: no se pudieron calcular clases relativas "
                     "(valores insuficientes o todos iguales)."
                     % (flight["week_key"], pid))
        flight["relative_bands"] = out


def load_overrides():
    if not os.path.isfile(OVERRIDES_PATH):
        return {}
    try:
        with open(OVERRIDES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        sys.stderr.write("ADVERTENCIA: ceres_thresholds.json ilegible (%s); se "
                         "usan las bandas de Ceres.\n" % exc)
        return {}
    out = {}
    for pid, cfg in (data or {}).items():
        bands = (cfg or {}).get("bands")
        if not isinstance(bands, list) or not bands:
            continue
        clean = []
        for band in bands:
            try:
                clean.append({"min": float(band["min"]), "max": float(band["max"])})
            except (KeyError, TypeError, ValueError):
                clean = []
                break
        if clean:
            out[pid] = clean
    return out


def build_params(colormaps, overrides, warn, value_ranges=None):
    """
    Arma params[]. Un override de ceres_thresholds.json siempre gana: es la via
    para que agronomia habilite un indicador que Ceres deja sin umbrales.
    """
    value_ranges = value_ranges or {}
    params = []
    for pid, meta in PARAMS.items():
        policy = meta.get("bands_policy", "unclassified")
        reason_es = reason_en = None

        if pid in overrides:
            raw, source = overrides[pid], "custom"
        elif policy == "fixed":
            # Cortes definidos por agronomia, fijos y comparables entre vuelos.
            raw, source = bands_from_cuts(meta["cuts"]), "agronomia"
        elif policy == "relative":
            # Los cortes no viven aca: se recalculan por vuelo en
            # compute_relative_bands(). El indicador queda marcado y sin bandas
            # propias, y el mapa las toma del vuelo activo.
            raw, source = [], "relative"
        elif policy == "ceres" and pid in colormaps:
            raw, source = colormaps[pid], "ceres"
        elif policy == "ceres":
            raw, source = [], "unclassified"
            reason_es = "No se pudo leer el colorMap de Ceres."
            reason_en = "Could not read the Ceres colorMap."
            warn("`%s` tiene politica `ceres` pero no se pudo extraer su "
                 "colorMap: queda sin clasificar." % pid)
        elif policy.startswith("share:"):
            # Toma prestados los cortes publicados de otro indicador que mide la
            # MISMA magnitud. La procedencia queda escrita en bands_source, para
            # que se pueda auditar de donde salio cada banda.
            donor = policy.split(":", 1)[1]
            if donor in overrides:
                raw, source = overrides[donor], "custom:" + donor
            elif donor in colormaps:
                raw, source = colormaps[donor], "ceres:" + donor
            else:
                raw, source = [], "unclassified"
                reason_es = "No se pudo leer el colorMap de %s, del que toma sus cortes." % donor
                reason_en = "Could not read the colorMap of %s, whose cuts it borrows." % donor
                warn("`%s` toma sus cortes de `%s`, pero no se pudo extraer ese "
                     "colorMap: queda sin clasificar." % (pid, donor))
        else:
            raw, source = [], "unclassified"
            reason_es = meta.get("why_es")
            reason_en = meta.get("why_en")

        bands = label_bands(raw, meta["higher_is_better"], meta.get("labels")) if raw else []

        # Rango del eje: con bandas manda la banda; sin bandas, el rango real de
        # los datos, para que los graficos tengan un eje utilizable igual.
        if bands:
            lo = min(b["min"] for b in bands)
            hi = max(b["max"] for b in bands)
        elif pid in value_ranges:
            lo, hi = value_ranges[pid]
        else:
            lo, hi = 0.0, 1.0

        entry = OrderedDict([
            ("id", pid),
            ("es", meta["es"]),
            ("en", meta["en"]),
            ("desc_es", meta.get("desc_es", "")),
            ("desc_en", meta.get("desc_en", "")),
            ("group_es", meta.get("group_es", "")),
            ("group_en", meta.get("group_en", "")),
            ("min", round(lo, 6)),
            ("max", round(hi, 6)),
            ("higher_is_better", meta["higher_is_better"]),
            ("bands", bands),
            ("bands_source", source),
        ])
        if source == "unclassified":
            entry["unclassified_es"] = reason_es or "Sin umbrales definidos."
            entry["unclassified_en"] = reason_en or "No thresholds defined."
            # Cuantas bandas publico Ceres y se descartaron. Queda anotado para
            # que se note si algun dia Ceres empieza a publicar umbrales reales.
            entry["ceres_bands_found"] = len(colormaps.get(pid) or [])
        if source == "relative":
            # El mapa tiene que decirlo: dos vuelos no son comparables entre si.
            entry["relative_es"] = meta.get("relative_es", "")
            entry["relative_en"] = meta.get("relative_en", "")
            entry["n_classes"] = meta.get("n_classes", 4)
        params.append(entry)
    return params


# ═══════════════════════════════════════════════════════════════════════════
# Derivados: deltas y cumplimiento
# ═══════════════════════════════════════════════════════════════════════════

def band_of(param, value):
    """Banda que contiene el valor. El ultimo tramo incluye su tope."""
    bands = param.get("bands") or []
    if value is None or not bands:
        return None
    for i, band in enumerate(bands):
        last = (i == len(bands) - 1)
        if band["min"] <= value < band["max"] or (last and value <= band["max"]):
            return band
    return bands[-1] if value > bands[-1]["max"] else bands[0]


def compute_coverage(flights, geo, warn):
    """
    Cobertura por vuelo y nivel, y deteccion de unidades que desaparecen.

    Devuelve (vuelos_con_dato, omitidos). Los omitidos son los que no traen ni
    una unidad en ningun nivel: Ceres volo el predio pero todavia no habia
    grilla cargada. Dejarlos haria que el mapa arranque en un vuelo con los 63
    poligonos en gris.
    """
    # Universo de unidades de HOY, por nivel. Hace falta para separar "todavia
    # no estaba plantado" de "no reporto": sin el, lo unico que se puede saber
    # es que faltan 7 de 28, no cuales ni por que.
    universo = dict((l, {f["properties"]["id"]
                         for f in geo[LEVEL_GEO[l]]["features"]})
                    for l in niveles_activos())
    vistas = dict((l, set()) for l in niveles_activos())
    omitidos, con_dato = [], []

    for flight in flights:
        total = sum(len(flight.get(l) or {}) for l in niveles_activos())
        if total == 0:
            omitidos.append(OrderedDict([
                ("week_key", flight["week_key"]),
                ("date", flight["date"]),
                ("motivo", "el vuelo no trae ninguna unidad en ningun nivel"),
            ]))
            continue

        cobertura = OrderedDict()
        for level in niveles_activos():
            unidades = set(flight.get(level) or {})
            perdidas = sorted(vistas[level] - unidades)
            nuevas = sorted(unidades - vistas[level])
            if perdidas:
                warn("vuelo %s (%s) / %s: desaparecieron %d unidad(es) que un "
                     "vuelo anterior si traia: %s. Esto NO es crecimiento del "
                     "predio; revisalo."
                     % (flight["week_key"], flight["date"], level,
                        len(perdidas), ", ".join(perdidas)))
            vistas[level] |= unidades
            # Tres estados distintos, y el mapa los pinta distinto:
            #   no_existia -> nunca aparecio hasta esta fecha: no estaba plantado
            #   sin_dato   -> ya habia aparecido antes y en este vuelo no viene
            #   el resto   -> tiene valor
            cobertura[level] = OrderedDict([
                ("n", len(unidades)),
                ("de", LEVEL_N.get(level)),
                ("nuevas", nuevas),
                ("no_existia", sorted(universo[level] - vistas[level])),
                ("sin_dato", perdidas),
            ])
        flight["coverage"] = cobertura
        con_dato.append(flight)

    return con_dato, omitidos


def compute_deltas(flights):
    """Diferencia contra el vuelo anterior, por unidad e indicador."""
    for i, flight in enumerate(flights):
        deltas = OrderedDict((l, OrderedDict()) for l in niveles_activos())
        if i > 0:
            prev = flights[i - 1]
            for level in niveles_activos():
                for unit in flight[level]:
                    now = flight[level][unit]
                    before = prev[level].get(unit) or {}
                    diff = OrderedDict()
                    for pid in PARAMS:
                        if pid in now and pid in before:
                            diff[pid] = round(now[pid] - before[pid], 4)
                    if diff:
                        deltas[level][unit] = diff
        flight["deltas"] = deltas


def compute_compliance(flights, params, metas, warn):
    """
    Cuantas unidades, cuanta superficie y cuantas plantas caen en cada banda.
    Precalculado aca: el navegador no debe contar nada.

    Se calcula para los TRES niveles. El mapa pinta 5 equipos, 28 sectores o 30
    cuarteles segun el toggle, y si solo existiera el cumplimiento por sector,
    al mirar equipos la leyenda diria "22 de 28" sobre un mapa de 5 poligonos.

    A diferencia de San Gerardo, el cumplimiento va indexado por nivel en
    flight["compliance"][nivel] en vez de tener una clave por nivel: con tres
    niveles, "compliance" y "compliance_equipos" y "compliance_cuarteles" seria
    una invitacion a olvidarse de uno.
    """
    for flight in flights:
        flight["compliance"] = OrderedDict(
            # Lo esperado es la cobertura DE ESTE VUELO, no la del predio
            # maduro: en 2023 habia 21 sectores plantados y clasificar 21 de 21
            # es correcto. Comparar contra los 28 de hoy generaba 310
            # advertencias que no eran nada.
            (level, _compliance_for(flight, level, params,
                                    metas.get(level) or {},
                                    ((flight.get("coverage") or {}).get(level)
                                     or {}).get("n"), warn))
            for level in niveles_activos())


def flight_bands(flight, param, level):
    """
    Bandas vigentes para un indicador en un vuelo y nivel. Los indicadores
    relativos las tienen dentro del vuelo, porque cambian vuelo a vuelo; el
    resto las tiene en el propio indicador.
    """
    if param.get("bands_source") == "relative":
        rel = (flight.get("relative_bands") or {}).get(param["id"]) or {}
        return rel.get(level) or []
    return param.get("bands") or []


def _compliance_for(flight, level, params, meta_by_unit, expected, warn):
    out = OrderedDict()
    for param in params:
        bands = flight_bands(flight, param, level)
        if not bands:
            continue
        statuses = [b["status"] for b in bands]
        by_unit = OrderedDict((s, 0) for s in statuses)
        by_area = OrderedDict((s, 0) for s in statuses)
        by_plants = OrderedDict((s, 0) for s in statuses)
        classified = 0
        for unit, values in (flight.get(level) or {}).items():
            band = band_of({"bands": bands}, values.get(param["id"]))
            if band is None:
                continue
            meta = meta_by_unit.get(unit) or {}
            by_unit[band["status"]] += 1
            by_area[band["status"]] += int(meta.get("area_m2") or 0)
            by_plants[band["status"]] += int(meta.get("plants") or 0)
            classified += 1
        if expected and classified and classified != expected:
            warn("vuelo %s / %s / %s: %d unidades clasificadas, se esperaban %d."
                 % (flight["week_key"], level, param["id"], classified, expected))
        # Con tres niveles, un nombre de clave distinto por nivel (by_sector,
        # by_equipo, by_cuartel) obliga al mapa a saber en cual esta parado para
        # leer el mismo numero. Se llama by_unit en los tres.
        out[param["id"]] = OrderedDict([
            ("by_unit", by_unit),
            ("by_area_m2", by_area),
            ("by_plants", by_plants),
        ])
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Descarga de un vuelo
# ═══════════════════════════════════════════════════════════════════════════

def fetch_flight(session, flight, colormaps, meta_sink, warn):
    """
    Devuelve un dict por nivel con los valores nativos de cada uno. Ninguno se
    deriva de otro: Ceres agrega sobre los pixeles y un promedio de promedios no
    es lo mismo. Por eso el cuartel es dato medido y no una estimacion.
    """
    result = OrderedDict((l, OrderedDict()) for l in niveles_activos())
    for level in niveles_activos():
        grid = LEVEL_GRID[level]
        rows = flight_summary(session, flight["week_key"], grid)
        for row in rows:
            key = unit_key(row, level)
            if not key:
                warn("vuelo %s / %s: fila sin unidad reconocible (field_id=%r, "
                     "block_name=%r); se ignora."
                     % (flight["week_key"], level, row.get("field_id"),
                        row.get("block_name")))
                continue
            values = OrderedDict()
            area = plants = None
            for overlay in (row.get("overlays") or []):
                otype = overlay.get("overlay_type")
                if not otype or otype in IGNORED_OVERLAYS or otype not in PARAMS:
                    continue
                if otype not in colormaps:
                    bands = extract_colormap(overlay)
                    if bands:
                        colormaps[otype] = bands
                val = overlay.get("value")
                if val is None:
                    continue      # sin dato: se omite la clave, no va null
                try:
                    values[otype] = round(float(val), 4)
                except (TypeError, ValueError):
                    continue
                if overlay.get("area") is not None:
                    try:
                        area = max(area or 0.0, float(overlay["area"]))
                    except (TypeError, ValueError):
                        pass
                if overlay.get("plants") is not None:
                    try:
                        plants = max(plants or 0, int(overlay["plants"]))
                    except (TypeError, ValueError):
                        pass
            if values:
                result[level][key] = values
            # La metadata (superficie, plantas) se guarda con la fecha del vuelo:
            # despues gana el vuelo mas reciente que la traiga.
            if area or plants:
                sink = meta_sink[level].setdefault(key, {})
                if flight["date"] >= sink.get("_date", ""):
                    sink["_date"] = flight["date"]
                    if area:
                        sink["area_m2"] = int(round(area))
                    if plants:
                        sink["plants"] = int(plants)
                    if row.get("field_id") is not None:
                        sink["field_id"] = row.get("field_id")

        # No se advierte por traer menos unidades de las que hay hoy: en Ketcal
        # eso es lo NORMAL, porque el predio se planto por etapas y Ceres solo
        # reporta lo que existia en cada fecha. La anomalia se detecta despues,
        # comparando vuelos entre si (ver compute_coverage), y solo si un vuelo
        # PIERDE una unidad que otro anterior ya traia.
        got = len(result[level])
        want = LEVEL_N.get(level)
        if want and got > want:
            warn("vuelo %s (%s): trae %d %s y hoy hay %d. Sobran unidades: "
                 "cambio la grilla en Ceres."
                 % (flight["week_key"], flight["date"], got, level, want))
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Metadata de unidades
# ═══════════════════════════════════════════════════════════════════════════

def per_ha(plants, area_m2):
    if not plants or not area_m2:
        return None
    return round(plants / (area_m2 / 10000.0), 1)


def parse_sector_key(key):
    eq, sec = key.split("-", 1)
    return int(eq.lstrip("Ee")), int(sec.lstrip("Ss"))


def sector_sort(key):
    try:
        return parse_sector_key(key)
    except (ValueError, IndexError):
        return (99, 99)


def equipo_num(key):
    try:
        return int(key.lstrip("Ee"))
    except ValueError:
        return 99


ORDEN_ESPECIE = {"LIM": 0, "NAR": 1, "MAN": 2}


def cuartel_sort(key):
    """LIM-C3 -> (0, 3). Mismo orden que geo_data.json."""
    try:
        pref, num = key.split("-C", 1)
        return (ORDEN_ESPECIE.get(pref.upper(), 9), int(num))
    except (ValueError, IndexError):
        return (9, 99)


LEVEL_SORT = {"sectors": lambda k: sector_sort(k),
              "equipos": lambda k: equipo_num(k),
              "cuarteles": lambda k: cuartel_sort(k)}


def build_unit_meta(meta_sink):
    """Metadata por unidad, para los tres niveles."""
    metas = OrderedDict()

    for level in niveles_activos():
        out = OrderedDict()
        for key in sorted(meta_sink.get(level) or {}, key=LEVEL_SORT[level]):
            raw = meta_sink[level][key]
            fila = OrderedDict()
            if level == "sectors":
                try:
                    eq, sec = parse_sector_key(key)
                except (ValueError, IndexError):
                    eq = sec = None
                fila["equipo"], fila["sector"] = eq, sec
            elif level == "equipos":
                fila["equipo"] = equipo_num(key)
            else:
                pref, num = (key.split("-C", 1) + [None])[:2]
                fila["especie"] = pref
                fila["cuartel"] = int(num) if num and num.isdigit() else None
            fila["field_id"] = raw.get("field_id")
            fila["area_m2"] = raw.get("area_m2")
            fila["plants"] = raw.get("plants")
            fila["plants_per_ha"] = per_ha(raw.get("plants"), raw.get("area_m2"))
            out[key] = fila
        metas[level] = out

    # n_sectores del equipo, ahora que estan los dos niveles armados.
    for key, fila in (metas.get("equipos") or {}).items():
        fila["n_sectores"] = sum(
            1 for f in (metas.get("sectors") or {}).values()
            if f.get("equipo") == fila.get("equipo"))
    return metas


def seed_meta_from_existing(existing, meta_sink):
    """
    Reinyecta la metadata de unidades de un archivo previo, para que una corrida
    incremental no pierda area_m2 / plants de los vuelos que no volvio a pedir.
    Lo que trajo esta corrida (marcado con _date) siempre gana.
    """
    for level in niveles_activos():
        source = ((existing or {}).get("units") or {}).get(level) or {}
        for key, meta in source.items():
            sink = meta_sink[level].setdefault(key, {})
            if "_date" in sink:
                continue
            for field in ("area_m2", "plants", "field_id"):
                if meta.get(field) is not None and sink.get(field) is None:
                    sink[field] = meta[field]


# ═══════════════════════════════════════════════════════════════════════════
# Escritura
# ═══════════════════════════════════════════════════════════════════════════

def read_existing(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh, object_pairs_hook=OrderedDict)
    except (OSError, ValueError) as exc:
        sys.stderr.write("ADVERTENCIA: %s ilegible (%s); se rehace completo.\n"
                         % (os.path.basename(path), exc))
        return None


def dump(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def bump_data_version(latest_date, body):
    """
    Actualiza data-version.json dejando el resto de las claves intactas:

      "ceres"          fecha del vuelo mas reciente. Es lo que el mapa MUESTRA
                       como vigencia del dato.
      "_hash"."ceres"  hash del contenido. Es lo que el mapa usa para romper
                       cache.

    Hacen falta las dos. Con solo la fecha, un JSON que cambia sin que llegue un
    vuelo nuevo -- por ejemplo al agregar el inventario de variedades -- deja la
    fecha igual, y el navegador sigue sirviendo el archivo viejo de cache
    indefinidamente. Paso de verdad: el mapa cargo 193 overlays cuando el archivo
    en disco ya tenia 205.
    """
    try:
        with open(DATA_VERSION_PATH, "r", encoding="utf-8") as fh:
            versions = json.load(fh, object_pairs_hook=OrderedDict)
    except (OSError, ValueError) as exc:
        sys.stderr.write("ADVERTENCIA: no se pudo leer data-version.json (%s); "
                         "no se bumpeo la version.\n" % exc)
        return False
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:10]
    hashes = versions.get("_hash")
    if not isinstance(hashes, dict):
        hashes = OrderedDict()
    cambio = (versions.get("ceres") != latest_date
              or hashes.get("ceres") != digest)
    if not cambio:
        return False
    versions["ceres"] = latest_date
    hashes["ceres"] = digest
    versions["_hash"] = hashes
    with open(DATA_VERSION_PATH, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(versions, ensure_ascii=False, indent=2) + "\n")
    return True


def order_units(units, keyfn):
    return OrderedDict((k, units[k]) for k in sorted(units, key=keyfn))


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def summarize_trees(trees):
    print("")
    if not trees:
        print("Capa por arbol: sin overlays tree_data.")
        return
    bf = trees["by_flight"]
    n = sum(len(e) for per in bf.values() for e in per.values())
    print("Capa por arbol: %d overlays en %d vuelos (tiler publico, sin token)" % (n, len(bf)))
    ultimo = list(bf.keys())[-1]
    for otype, eqs in bf[ultimo].items():
        print("  %-11s %-27s %d equipos" % (ultimo, otype, len(eqs)))


def summarize(flights, params, metas, failed, warnings):
    print("")
    print("-- Resumen ------------------------------------------------")
    print("Vuelos:      %d  (%s -> %s)"
          % (len(flights), flights[0]["date"], flights[-1]["date"]))
    print("Unidades:    %s"
          % " / ".join("%d %s" % (len(metas.get(l) or {}), l)
                       for l in niveles_activos()))
    banded = [p for p in params
              if p.get("bands") or p.get("bands_source") == "relative"]
    print("Indicadores: %d de %d clasificados" % (len(banded), len(params)))
    for p in params:
        n = len(p.get("bands") or [])
        if p.get("bands_source") == "relative":
            _ref = niveles_activos()[-1] if niveles_activos() else "sectors"
            rb = ((flights[-1].get("relative_bands") or {}).get(p["id"]) or {}).get(_ref) or []
            print("               %-27s %d clases relativas por vuelo  [relative]"
                  % (p["id"], len(rb)))
            continue
        line = "               %-27s %d bandas  [%s]" % (p["id"], n, p.get("bands_source"))
        if p.get("bands_source") == "unclassified":
            line += "  <- %s" % p.get("unclassified_es", "")
            if p.get("ceres_bands_found"):
                line += " (Ceres publica %d tramos)" % p["ceres_bands_found"]
        print(line)
    if len(banded) < len(params):
        print("")
        print("  Los indicadores sin clasificar se muestran en gris en el mapa, con")
        print("  su valor y su evolucion, pero sin banda de color. Para habilitarlos,")
        print("  agrega sus cortes a ceres_thresholds.json (ver el encabezado).")
    print("Vuelos por fecha:")
    for flight in flights:
        cob = flight.get("coverage") or {}
        completo = all((cob.get(l) or {}).get("n") == (cob.get(l) or {}).get("de")
                       for l in niveles_activos())
        print("  %-11s %s  %-8s  %s  %s"
              % (flight["week_key"], flight["date"], flight["season"],
                 " / ".join("%2d de %-2s %s" % ((cob.get(l) or {}).get("n", 0),
                                                (cob.get(l) or {}).get("de", "?"), l)
                            for l in niveles_activos()),
                 "" if completo else "<- parcial"))
    if failed:
        print("Vuelos fallidos: %s" % ", ".join(failed))
    if warnings:
        print("")
        print("%d advertencia(s) - revisalas antes de commitear." % len(warnings))
    else:
        print("")
        print("Sin advertencias.")


# ═══════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# Descubrimiento de los identificadores del predio
# ═══════════════════════════════════════════════════════════════════════════
#
# San Gerardo trae sus identificadores hardcodeados porque se averiguaron a mano.
# Para Ketcal no los conozco, y no hay un endpoint documentado que los liste, asi
# que esto SONDEA una escalera de candidatos y REPORTA lo que encuentra. No
# escribe nada hasta el final, y solo si pudo identificar el predio.
#
# Todo lo que hace es GET. Si un candidato no existe, se anota y se sigue.

CANDIDATOS_GRUPOS = [
    "/admin_groups/",
    "/admin_groups/tree/%(user)s/",
    "/admin_groups/%(user)s/",
    "/users/%(user)s/",
    "/users/me/",
    "/fields/",
]


def _get_crudo(session, path, params=None):
    """GET tolerante: devuelve (ok, payload_o_error). No aborta la corrida."""
    try:
        resp = session.get(BASE_URL + path, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        return False, type(exc).__name__
    if resp.status_code != 200:
        return False, "HTTP %d" % resp.status_code
    try:
        return True, resp.json()
    except ValueError:
        return False, "no era JSON"


def _iterar(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("results", "admin_groups", "children", "fields", "data"):
            if isinstance(payload.get(k), list):
                return payload[k]
        return [payload]
    return []


def _muestra(payload, n=400):
    txt = json.dumps(payload, ensure_ascii=False)
    return txt[:n] + ("…" if len(txt) > n else "")


def discover(session, user_id):
    """Explora la API y devuelve el dict de ceres_predio.json, o None."""
    print("Descubrimiento (solo lectura). Cuenta: user_id=%s" % user_id)
    print("")

    # ── 1. Que endpoints responden ──────────────────────────────────────────
    print("1) Sondeo de endpoints de catalogo")
    encontrados = {}
    for tpl in CANDIDATOS_GRUPOS:
        path = tpl % {"user": user_id}
        ok, payload = _get_crudo(session, path)
        print("   %-34s %s" % (path, "OK" if ok else payload))
        if ok:
            encontrados[path] = payload
    print("")

    # ── 2. Buscar Ketcal por nombre en todo lo que respondio ────────────────
    print("2) Buscando el predio por nombre")
    candidatos = []
    for path, payload in encontrados.items():
        for item in _iterar(payload):
            if not isinstance(item, dict):
                continue
            txt = json.dumps(item, ensure_ascii=False).lower()
            if "ketcal" in txt:
                candidatos.append((path, item))
    if candidatos:
        for path, item in candidatos:
            print("   %s -> %s" % (path, _muestra(item)))
    else:
        print("   Ningun endpoint de catalogo menciona 'Ketcal'.")
        for path, payload in encontrados.items():
            print("   forma de %s: %s" % (path, _muestra(payload, 300)))
    print("")

    # ── 3. Probar admin_groups hermanos del de San Gerardo ──────────────────
    # Si Ketcal cuelga del mismo cliente, su admin_group es "CFF|4527.<id>" y
    # el endpoint de semanas responde. Se prueba el grupo del cliente, que suele
    # devolver el arbol de predios.
    print("3) Probando el cliente de San Gerardo (%s)" % CUSTOMER_HINT)
    for grupo in (CUSTOMER_HINT,):
        path = "/admin_groups/weeks/%s/%s/" % (user_id,
                                               urllib.parse.quote(grupo, safe=""))
        ok, payload = _get_crudo(session, path)
        print("   %-46s %s" % (grupo, "OK" if ok else payload))
        if ok:
            print("      %s" % _muestra(payload, 300))
    print("")

    # ── 4. Grillas y campos del predio elegido ──────────────────────────────
    grupo = None
    for _, item in candidatos:
        for clave in ("admin_group", "admin_group_id", "id", "key"):
            v = item.get(clave)
            if isinstance(v, str) and v.startswith("CFF|"):
                grupo = v
                break
        if grupo:
            break
    if not grupo:
        print("No pude identificar el admin_group de Ketcal automaticamente.")
        print("Con la salida de arriba se completa a mano %s." % PREDIO_PATH_NAME)
        return None

    print("4) Predio identificado: %s" % grupo)
    ok, semanas = _get_crudo(session, "/admin_groups/weeks/%s/%s/"
                             % (user_id, urllib.parse.quote(grupo, safe="")))
    n_vuelos = len([w for w in _iterar(semanas) if isinstance(w, dict)
                    and w.get("level") == 0]) if ok else 0
    print("   semanas con vuelo (level 0): %d" % n_vuelos)

    # Grid types: se prueba cada id contra flight_summary del vuelo mas reciente
    # y se mira cuantas unidades devuelve. Es la unica forma fiable de saber que
    # grilla es cual sin documentacion.
    grids, fields = {}, {}
    if ok and n_vuelos:
        vuelos = sorted([w for w in _iterar(semanas)
                         if isinstance(w, dict) and w.get("level") == 0],
                        key=lambda w: max(w.get("capture_dates") or [""]))
        week = vuelos[-1].get("key")
        print("   probando grillas contra el vuelo %s" % week)
        for gid in range(1, 40):
            ok2, rows = _get_crudo(session, "/tables/flight_summary/", params={
                "admin_group": grupo, "week": week, "grid_type_id": gid})
            if not ok2:
                continue
            filas = _iterar(rows)
            if not filas:
                continue
            unidades = [{"block_name": r.get("block_name"),
                         "field_id": r.get("field_id"),
                         "field_name": r.get("field_name")}
                        for r in filas if isinstance(r, dict)]
            print("      grid_type_id=%-3d %3d unidades  ej: %s"
                  % (gid, len(filas), [u["block_name"] for u in unidades][:4]))
            grids[gid] = {"n": len(filas), "unidades": unidades}
            for u in unidades:
                if u["field_id"]:
                    fields[u["field_id"]] = u["field_name"]
    print("")
    return {"grupo": grupo, "grids": grids, "fields": fields,
            "n_vuelos": n_vuelos, "user_id": user_id}


def escribir_predio(hallado, geo):
    """Traduce el descubrimiento a ceres_predio.json, si es inequivoco.

    Empareja cada nivel con la grilla cuyo numero de unidades calza con la
    geometria del repo, y despues COTEJA las claves una por una: que los
    conteos coincidan no garantiza que las claves lo hagan, y un mapa con
    claves que no calzan se pinta gris sin decir por que.
    """
    grids = hallado.get("grids") or {}
    esperado = {nivel: len(geo[coleccion]["features"])
                for nivel, coleccion in LEVEL_GEO.items()}

    print("Emparejando grillas de Ceres con la geometria del repo:")
    elegidas, sobrantes = OrderedDict(), dict(grids)
    for nivel in LEVELS:
        n = esperado[nivel]
        # Entre las que tienen el conteo correcto, gana la que mas claves
        # normaliza: en Ketcal hay dos grillas de 30 unidades y solo una trae
        # los nombres de cuartel.
        candidatas = []
        for gid, d in grids.items():
            if d["n"] != n:
                continue
            ok = sum(1 for u in d["unidades"] if unit_key(u, nivel))
            candidatas.append((ok, gid))
        candidatas.sort(reverse=True)
        if not candidatas:
            print("   %-10s %2d unidades -> ninguna grilla calza" % (nivel, n))
            continue
        ok, gid = candidatas[0]
        if ok == 0:
            print("   %-10s %2d unidades -> grid %s calza en cantidad pero "
                  "ninguna clave se pudo normalizar" % (nivel, n, gid))
            continue
        elegidas[nivel] = gid
        sobrantes.pop(gid, None)
        extra = ""
        if len(candidatas) > 1:
            extra = "  (tambien calzaban en cantidad: %s)" % [g for _, g in candidatas[1:]]
        print("   %-10s %2d unidades -> grid_type_id %-3d (%d/%d claves)%s"
              % (nivel, n, gid, ok, n, extra))

    if sobrantes:
        print("   otras grillas cargadas: %s"
              % {g: d["n"] for g, d in sorted(sobrantes.items())})

    if not elegidas:
        print("")
        print("Ninguna grilla de Ceres calza con la geometria. Reviso a mano.")
        return None

    # ── field_id -> equipo, desde la grilla de equipos ──────────────────────
    f2e, sin_resolver = OrderedDict(), []
    if "equipos" in elegidas:
        for u in grids[elegidas["equipos"]]["unidades"]:
            fid = u.get("field_id")
            if not fid:
                continue
            etiqueta = unit_key(u, "equipos")
            if etiqueta:
                f2e[str(fid)] = etiqueta
            else:
                sin_resolver.append((fid, u.get("block_name"), u.get("field_name")))
    if sin_resolver:
        print("")
        print("   OJO: no pude deducir el equipo de %d campo(s):" % len(sin_resolver))
        for fid, bn, fn in sin_resolver:
            print("      field_id=%s block_name=%r field_name=%r" % (fid, bn, fn))
        print("   Completalos a mano en field_to_equipo de %s." % PREDIO_PATH_NAME)
    elif f2e:
        print("   field_id -> equipo: %s" % dict(f2e))

    # ── Cotejo de claves, nivel por nivel ───────────────────────────────────
    print("")
    print("Cotejo de claves contra geo_data.json:")
    desajuste = False
    claves_por_nivel = OrderedDict()
    for nivel, gid in elegidas.items():
        traidas = set()
        for u in grids[gid]["unidades"]:
            k = unit_key(u, nivel)
            if k:
                traidas.add(k)
        claves_por_nivel[nivel] = sorted(traidas)
        objetivo = {f["properties"]["id"]
                    for f in geo[LEVEL_GEO[nivel]]["features"]}
        faltan, sobran = sorted(objetivo - traidas), sorted(traidas - objetivo)
        if faltan or sobran:
            desajuste = True
            print("   %-10s DESAJUSTE" % nivel)
            if faltan:
                print("      en el KMZ y no en Ceres: %s" % faltan)
            if sobran:
                print("      en Ceres y no en el KMZ: %s" % sobran)
        else:
            print("   %-10s las %d claves calzan exactamente" % (nivel, len(traidas)))

    if desajuste:
        print("")
        print("Hay claves que no calzan. El mapa pintaria esas unidades en gris.")
        print("Resolvelo antes de seguir: o se corrige la grilla en Ceres, o hay")
        print("que ajustar unit_key() con una equivalencia explicita.")
        print("No se escribe %s." % PREDIO_PATH_NAME)
        return None

    predio = OrderedDict([
        ("user_id", hallado["user_id"]),
        ("admin_group", hallado["grupo"]),
        ("farm_name", FARM_NAME),
        ("customer", hallado.get("customer")),
        ("grid_types", OrderedDict((n, elegidas[n]) for n in LEVELS
                                   if n in elegidas)),
        ("field_to_equipo", f2e),
        ("otras_grillas", {str(g): d["n"] for g, d in sorted(sobrantes.items())}),
        ("claves_sectores", claves_por_nivel.get("sectors") or []),
        ("descubierto", now_iso()),
    ])
    with io.open(PREDIO_PATH, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(predio, ensure_ascii=False, indent=2))
        fh.write("\n")
    print("")
    print("Escrito %s. Revisalo y despues corre --full." % PREDIO_PATH_NAME)
    return predio


def main():
    ap = argparse.ArgumentParser(
        description="Descarga los vuelos de Ceres Imaging de Ketcal.")
    ap.add_argument("--discover", action="store_true",
                    help="solo lectura: explora la API para encontrar el "
                         "admin_group, las grillas y los campos de Ketcal, y "
                         "escribe ceres_predio.json")
    ap.add_argument("--full", action="store_true",
                    help="refetch completo: ignora los vuelos ya guardados")
    ap.add_argument("--extras", action="store_true",
                    help="incluye la capa por arbol y la grilla de celdas. "
                         "Decodifica miles de tiles: con los 32 vuelos de Ketcal "
                         "son >30 min, asi que esta apagado por defecto y no lo "
                         "usa el workflow. El mapa no las consume todavia.")
    ap.add_argument("--extras-ultimos", type=int, default=4, metavar="N",
                    help="con --extras, cuantos vuelos recientes procesar "
                         "(default 4). La capa por arbol solo se muestra del "
                         "vuelo elegido, no hace falta el historico completo.")
    ap.add_argument("--out", default=OUT_DEFAULT,
                    help="ruta de salida (default: ceres_data.json en la raiz)")
    ap.add_argument("--inspect-overlays", action="store_true",
                    help="diagnostico: imprime la forma de /api/overlays/ para "
                         "ajustar el parseo del colorMap. No escribe nada.")
    ap.add_argument("--check-token", action="store_true",
                    help="diagnostico: valida el token con una sola llamada y "
                         "describe su FORMA (largo, espacios, prefijo) sin "
                         "imprimir el valor. Sirve para depurar el secret de CI.")
    args = ap.parse_args()

    warnings = []

    def warn(msg):
        warnings.append(msg)
        sys.stderr.write("  !  %s\n" % msg)

    token = read_token()

    # El descubrimiento y --check-token no necesitan ceres_predio.json; todo lo
    # demas si.
    geo = cargar_geometria()
    cargar_predio(obligatorio=not (args.discover or args.check_token))

    if args.discover:
        session = requests.Session()
        session.headers.update({
            "Authorization": "Token %s" % token,
            "Accept": "application/json",
            "User-Agent": "ketcal-map/fetch_ceres",
        })
        hallado = discover(session, USER_ID or USER_ID_DEFAULT)
        if not hallado:
            return 1
        return 0 if escribir_predio(hallado, geo) else 1

    if args.check_token:
        # Describe la FORMA del token, nunca su valor: alcanza para distinguir un
        # pegado truncado, uno con el prefijo "Token " adentro o uno con un salto
        # de linea en medio, que son las tres formas tipicas de romper un secret.
        raw = os.environ.get("CERES_TOKEN")
        crudo = (raw or "").strip()
        print("origen:            %s" % ("variable de entorno CERES_TOKEN" if raw
                                         else "archivo .ceres_token"))
        entre_comillas = (len(crudo) >= 2 and crudo[0] == crudo[-1]
                          and crudo[0] in ('"', "'"))
        print("entre comillas:    %s" % ("SI - sobran, va el token solo"
                                         if entre_comillas else "no"))
        print("largo:             %d caracteres%s"
              % (len(token), " (ya sin las comillas)" if entre_comillas else ""))
        print("espacios internos: %s" % ("SI - probablemente se pego mal"
                                         if any(c.isspace() for c in token) else "no"))
        print("empieza con Token: %s" % ("SI - sobra el prefijo, va solo el valor"
                                         if token.lower().startswith("token") else "no"))
        print("solo ASCII:        %s" % ("si" if all(ord(c) < 128 for c in token)
                                         else "NO - hay caracteres raros"))
        if raw is not None and raw != raw.strip():
            print("ADVERTENCIA:       venia con espacios al principio o al final "
                  "(se recortaron)")
        sys.stdout.flush()
        s = requests.Session()
        s.headers.update({"Authorization": "Token %s" % token,
                          "Accept": "application/json"})
        # Si todavia no se descubrio el predio, se valida contra el grupo del
        # cliente: alcanza para saber si la credencial sirve.
        grupo = ADMIN_GROUP or CUSTOMER_HINT
        url = BASE_URL + "/admin_groups/weeks/%s/%s/" % (
            USER_ID or USER_ID_DEFAULT, urllib.parse.quote(grupo, safe=""))
        try:
            resp = s.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            print("resultado:         fallo de red (%s)" % type(exc).__name__)
            return 1
        print("resultado:         HTTP %d" % resp.status_code)
        if resp.status_code == 200:
            print("")
            print("El token es valido.")
            return 0
        if resp.status_code in (401, 403):
            print("")
            print("Ceres rechazo el token. Con el largo de arriba se distingue si")
            print("el pegado quedo incompleto o si el valor ya no sirve.")
        return 1

    session = requests.Session()
    session.headers.update({
        "Authorization": "Token %s" % token,
        "Accept": "application/json",
        "User-Agent": "ketcal-map/fetch_ceres",
    })

    if args.inspect_overlays:
        try:
            inspect_overlays(session)
        except CeresError as exc:
            sys.stderr.write("ERROR: no se pudo leer /overlays/ (%s).\n" % exc)
            return 1
        return 0

    existing = None if args.full else read_existing(args.out)
    known = {}
    if existing:
        for flight in existing.get("flights") or []:
            if flight.get("week_key"):
                known[flight["week_key"]] = flight
        print("Incremental: %d vuelos ya en %s."
              % (len(known), os.path.basename(args.out)))
    else:
        print("Refetch completo." if args.full else "Sin archivo previo: descarga completa.")

    print("Listando vuelos...")
    try:
        catalog = list_flights(session)
    except CeresError as exc:
        sys.stderr.write("ERROR: no se pudo listar los vuelos (%s).\n" % exc)
        return 1
    print("  %d vuelos en el historico (level 0)." % len(catalog))

    pending = [f for f in catalog if f["week_key"] not in known]
    print("  %d por descargar." % len(pending))

    # Los umbrales se piden antes que los vuelos, y de /overlays/: los overlays
    # de flight_summary vienen sin download_urls, asi que ahi no hay colorMap.
    print("Leyendo umbrales y catalogo de overlays...")
    (colormaps, trees_raw, grids_raw, imagery_raw,
     cat_completo) = fetch_overlay_catalog(session, warn)

    # Una lectura fallida o parcial de /overlays/ NO puede degradar lo que ya
    # estaba bien. Paso: un HTTP 400 dejo el catalogo en cero y la corrida
    # reescribio el JSON quitandole las bandas a water_stress y borrando los 193
    # overlays por arbol. Si lo leido esta incompleto y hay un archivo previo con
    # esa informacion, se conserva la vieja y se avisa.
    prev = existing or {}
    if not colormaps and (prev.get("params") or []):
        recuperados = bands_from_params([p for p in prev["params"]
                                        if p.get("bands_source") in ("ceres",)])
        if recuperados:
            colormaps = recuperados
            warn("no se pudo leer ningun colorMap; se conservan las bandas del "
                 "archivo previo en vez de dejar los indicadores sin clasificar.")
    if not trees_raw and (prev.get("trees") or {}).get("by_flight"):
        warn("no se pudo leer el catalogo por arbol; se conserva el del archivo "
             "previo en vez de borrarlo.")
        trees_raw = None          # build_trees devolvera None...
        conservar_trees = prev["trees"]
    else:
        conservar_trees = None
    # Lo mismo para los dos catalogos nuevos, por la misma razon: un HTTP 400 ya
    # dejo una vez el catalogo en cero y la corrida reescribio el JSON borrando
    # lo que si estaba bien.
    if not grids_raw and (prev.get("grid") or {}).get("by_flight"):
        warn("no se pudo leer el catalogo de grilla; se conserva el del archivo "
             "previo en vez de borrarlo.")
        conservar_grid = prev["grid"]
    else:
        conservar_grid = None
    if not imagery_raw and (prev.get("imagery") or {}).get("by_flight"):
        warn("no se pudo leer el catalogo de imagenes; se conserva el del "
             "archivo previo en vez de borrarlo.")
        conservar_imagery = prev["imagery"]
    else:
        conservar_imagery = None
    if not cat_completo:
        warn("el catalogo quedo incompleto: revisa las advertencias antes de "
             "commitear este JSON.")
    meta_sink = dict((l, {}) for l in niveles_activos())
    fetched, failed = {}, []

    for i, flight in enumerate(pending, 1):
        print("[%d/%d] %s / %s" % (i, len(pending), flight["week_key"], flight["date"]))
        try:
            fetched[flight["week_key"]] = fetch_flight(
                session, flight, colormaps, meta_sink, warn)
        except CeresError as exc:
            warn("vuelo %s (%s) fallo tras los reintentos (%s); se omite y la "
                 "corrida continua." % (flight["week_key"], flight["date"], exc))
            failed.append(flight["week_key"])

    # Los vuelos que ya estaban en disco reusan su metadata de unidades.
    seed_meta_from_existing(existing, meta_sink)

    overrides = load_overrides()
    if overrides:
        print("  ceres_thresholds.json: bandas propias para %s."
              % ", ".join(sorted(overrides)))

    flights = []
    for entry in catalog:
        wk = entry["week_key"]
        if wk in fetched:
            values = fetched[wk]
        elif wk in known:
            values = OrderedDict(
                (l, known[wk].get(l) or OrderedDict()) for l in niveles_activos())
        else:
            continue
        fila = OrderedDict([
            ("week_key", wk),
            ("date", entry["date"]),
            ("season", season_of(entry["date"])),
        ])
        for level in niveles_activos():
            fila[level] = order_units(values.get(level) or OrderedDict(),
                                      LEVEL_SORT[level])
        flights.append(fila)

    if not flights:
        sys.stderr.write("ERROR: no quedo ningun vuelo con datos. No se escribe nada.\n")
        return 1

    metas = build_unit_meta(meta_sink)

    # Los params se arman recien aca: un indicador sin bandas toma como rango de
    # eje el minimo y maximo reales de sus datos, y eso exige tener los vuelos.
    params = build_params(colormaps, overrides, warn, value_ranges(flights))

    # Cobertura antes que todo lo demas: descarta los vuelos vacios, y deltas y
    # cumplimiento no deben calcularse sobre ellos.
    flights, vuelos_omitidos = compute_coverage(flights, geo, warn)
    if not flights:
        sys.stderr.write("ERROR: todos los vuelos quedaron vacios. No se escribe nada.\n")
        return 1
    if vuelos_omitidos:
        print("Vuelos omitidos por no traer ninguna unidad: %s"
              % ", ".join(v["week_key"] for v in vuelos_omitidos))

    compute_deltas(flights)
    # Las clases relativas se calculan antes del cumplimiento: este las necesita.
    compute_relative_bands(flights, params, warn)
    compute_compliance(flights, params, metas, warn)

    payload = OrderedDict([
        ("generated_at", (existing or {}).get("generated_at") or now_iso()),
        ("source", "Ceres Imaging"),
        ("farm", OrderedDict([("name", FARM_NAME), ("customer", CUSTOMER),
                              ("admin_group", ADMIN_GROUP)])),
        ("levels", OrderedDict(
            (l, OrderedDict([("es", LEVEL_ES[l]), ("en", LEVEL_EN[l]),
                             ("grid_type_id", LEVEL_GRID[l]),
                             ("n", LEVEL_N.get(l)),
                             ("geo", LEVEL_GEO[l])]))
            for l in niveles_activos())),
        ("params", params),
        ("units", metas),
        ("flights", flights),
        ("flights_omitidos", vuelos_omitidos),
    ])
    # Capa por arbol: la plantilla del tiler mas el overlay de cada equipo por
    # vuelo e indicador. Va al final porque necesita los vuelos ya armados.
    #
    # Detras de --extras: decodificar los tiles de los 32 vuelos es lo que hacia
    # que la corrida no terminara nunca. Sin el flag se conserva lo que ya
    # hubiera en el archivo previo, que es mejor que borrarlo.
    if not args.extras:
        trees = conservar_trees
        if trees:
            payload["trees"] = trees
            print("Capa por arbol: reusada del archivo previo (sin --extras).")
        else:
            print("Capa por arbol: omitida (pasa --extras para incluirla).")
    else:
        trees = build_trees(trees_raw, flights, warn) or conservar_trees
    if args.extras and trees:
        # Reusar lo ya calculado: decodificar tiles es lo mas caro de la corrida
        # (27 tiles por vuelo e indicador), y ni las variedades ni las clases de
        # un vuelo pasado cambian. Con --full se recalcula todo.
        prev_trees = (existing or {}).get("trees") or {}
        if not args.full and prev_trees.get("varieties"):
            trees["varieties"] = prev_trees["varieties"]
        prev_rel = {}
        for f in (existing or {}).get("flights") or []:
            if f.get("relative_bands_trees"):
                prev_rel[f.get("week_key")] = f["relative_bands_trees"]
        # Solo los N vuelos mas recientes: la capa por arbol se muestra del
        # vuelo elegido, y bajarla para 2022 no le sirve a nadie.
        recientes = {f["week_key"] for f in flights[-max(1, args.extras_ultimos):]}
        pendientes = []
        for f in flights:
            if not args.full and f["week_key"] in prev_rel:
                f["relative_bands_trees"] = prev_rel[f["week_key"]]
            elif f["week_key"] in recientes:
                pendientes.append(f["week_key"])
        if pendientes or not trees.get("varieties"):
            print("Calculando estadistica por arbol (%d vuelo(s) pendiente(s))..."
                  % len(pendientes))
            solo = OrderedDict((k, v) for k, v in trees["by_flight"].items()
                               if k in pendientes)
            parcial = dict(trees)
            parcial["by_flight"] = solo if pendientes else trees["by_flight"]
            compute_tree_stats(session, parcial, flights, params, warn)
            if parcial.get("varieties"):
                trees["varieties"] = parcial["varieties"]
        else:
            print("Estadistica por arbol: sin cambios, reusada del archivo previo.")
        payload["trees"] = trees

    # Grilla de 1/8 ha del estres acumulado. La leyenda y la rampa salen de
    # decodificar los tiles, que es caro (2 tiles por equipo y por vuelo), asi
    # que se reusa lo del archivo previo salvo --full.
    if not args.extras:
        grid = conservar_grid
        if grid:
            payload["grid"] = grid
            print("Grilla de celdas: reusada del archivo previo (sin --extras).")
        else:
            print("Grilla de celdas: omitida (pasa --extras para incluirla).")
    else:
        grid = build_grid(grids_raw, flights, warn) or conservar_grid
    if args.extras and grid:
        prev_grid = (existing or {}).get("grid") or {}
        prev_stats = prev_grid.get("stats") or {}
        if not args.full:
            grid["stats"] = OrderedDict(
                (wk, prev_stats[wk]) for wk in grid["by_flight"] if wk in prev_stats)
            grid["ramp"] = prev_grid.get("ramp") or []
        pendientes = [wk for wk in grid["by_flight"] if wk not in grid["stats"]]
        if pendientes:
            print("Calculando la grilla de %g ha (%d vuelo(s) pendiente(s))..."
                  % (GRID_CELL_HA, len(pendientes)))
            if not compute_grid_stats(grid, warn, solo=set(pendientes)):
                # Sin la dependencia no hay leyenda; el catalogo de tiles igual
                # sirve, y conservar la rampa previa es mejor que dejarla vacia.
                if prev_grid.get("ramp"):
                    grid["ramp"] = prev_grid["ramp"]
                    grid["stats"] = prev_stats
                    warn("se conserva la leyenda de la grilla del archivo previo.")
        else:
            print("Grilla: sin cambios, reusada del archivo previo.")
        payload["grid"] = grid

    # Capas de imagen: solo el catalogo de ids, no hay nada que decodificar.
    imagery = build_imagery(imagery_raw, flights, warn) or conservar_imagery
    if imagery:
        payload["imagery"] = imagery
        # El cumplimiento de un relativo depende de sus clases, y las de arbol
        # recien existen ahora: no afecta al compliance por sector, que usa las
        # clases de sector, asi que no hace falta recalcularlo.

    body = dump(payload)
    previous = None
    if os.path.isfile(args.out):
        try:
            with open(args.out, "r", encoding="utf-8") as fh:
                previous = fh.read()
        except OSError:
            previous = None

    if previous == body:
        print("")
        print("Sin cambios: %s ya esta al dia." % os.path.basename(args.out))
        summarize(flights, params, metas, failed, warnings)
        summarize_trees(trees)
        return 0

    payload["generated_at"] = now_iso()
    body_final = dump(payload)
    try:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body_final)
    except OSError as exc:
        sys.stderr.write("ERROR: no se pudo escribir %s (%s).\n" % (args.out, exc))
        return 1
    print("")
    print("Escrito %s (%d vuelos)." % (os.path.basename(args.out), len(flights)))

    latest = flights[-1]["date"]
    if bump_data_version(latest, body_final):
        print('data-version.json: "ceres" -> %s.' % latest)

    summarize(flights, params, metas, failed, warnings)
    summarize_trees(trees)
    return 0


def value_ranges(flights):
    """
    {overlay_type: (min, max)} sobre todos los vuelos y los dos niveles. Es el
    rango del eje para los indicadores que quedan sin clasificar: sin bandas que
    lo definan, el grafico igual necesita un eje que encuadre el dato.
    """
    acc = {}
    for flight in flights:
        for level in ("sectors", "equipos"):
            for values in flight[level].values():
                for pid, val in values.items():
                    lo, hi = acc.get(pid, (val, val))
                    acc[pid] = (min(lo, val), max(hi, val))
    return acc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.stderr.write("\nInterrumpido.\n")
        sys.exit(130)
