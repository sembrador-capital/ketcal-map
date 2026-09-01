#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convierte `Base_Datos_Suelos_Foliares_Ketcal_SEMBRADOR_v2.xlsx` en
`nutricion_data.json`, la fuente de la pestaña Nutricion del mapa.

Decisiones que importan:

* La unidad espacial es la ubicacion `E#-S#-C#` (interseccion sector x cuartel),
  que es la clave `Clave_Mapa` de la base y la que produce kmz_to_geojson.py.
  Si una clave de la base no existe en geo_data.json, se registra en `issues`
  y la lectura NO se descarta: queda sin geometria y el mapa la lista aparte.

* Los umbrales salen de `umbrales_nutricion.json`, que se edita a mano. Aca no
  se inventa ninguno. Un parametro sin umbral queda con `escala: "relativa"` y
  el mapa lo declara como tal.

* El estado (deficiente/bajo/optimo/alto/excesivo) se calcula en el build, no
  en el navegador, porque depende de los umbrales.

* Las calicatas del estudio 2018 vienen en UTM 19S y se reproyectan a WGS84
  para poder mostrarlas como capa de puntos.

Uso:  python tools/build_nutricion.py [--xlsx RUTA] [--geo RUTA] [--out RUTA]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import openpyxl

# Orden en que se ofrecen las matrices en el selector, y a que subpestaña van.
#
# `mapeable` marca si la matriz se puede pintar sobre el mapa. Las dos de linea
# base 2018 NO lo son: sus muestras son calicatas georreferenciadas por UTM,
# no ubicaciones E#-S#-C#. Pintarlas por poligono obligaria a inventar una
# asignacion. Van a la capa de puntos "Calicatas 2018", donde cada punto lleva
# su perfil completo.
MATRICES = [
    ("Foliar", "foliar", "Analisis foliar", "Leaf analysis", True),
    ("Suelo_Fertilidad", "suelo", "Suelo - fertilidad", "Soil - fertility", True),
    ("Suelo_Salinidad", "suelo", "Suelo - salinidad", "Soil - salinity", True),
    ("Solucion_Suelo", "suelo", "Solucion de suelo", "Soil solution", True),
    ("Suelo_Quimico_LineaBase", "suelo", "Linea base 2018 - quimico",
     "2018 baseline - chemical", False),
    ("Suelo_Fisico_LineaBase", "suelo", "Linea base 2018 - fisico",
     "2018 baseline - physical", False),
]

# Orden agronomico de los parametros dentro de cada matriz. Ordenarlos por
# numero de lecturas, como salia antes, dejaba "Ca" y "B" de default: el
# usuario abre la pestaña y lo primero que ve es un micronutriente.
# Lo que no este listado va al final, por frecuencia.
ORDEN_PARAM = {
    "Foliar": ["N Total", "P", "K", "Ca", "Mg", "S",
               "B", "Cu", "Fe", "Mn", "Zn", "Mo", "Na", "Cl"],
    "Suelo_Fertilidad": ["pH", "MO", "CE", "CE 1/5",
                         "N Disponible", "N Total", "N-NO3", "N-NH4",
                         "P Olsen", "P Disponible", "K Disponible",
                         "K Cambio", "Ca Cambio", "Mg Cambio", "Na Cambio",
                         "CIC", "Suma Bases", "Saturacion Bases",
                         "Ca %CIC", "Mg %CIC", "K %CIC", "Na %CIC",
                         "C/N", "Caliza Activa",
                         "B", "Cu", "Fe", "Mn", "Zn",
                         "DA", "Arena", "Limo", "Arcilla"],
    "Suelo_Salinidad": ["CE", "pH", "RAS", "Saturacion Pasta",
                        "Cl soluble", "Na soluble", "SO4 soluble", "HCO3 soluble",
                        "Ca soluble", "Mg soluble", "K soluble"],
    "Solucion_Suelo": ["CE", "pH", "NO3", "NH4", "H2PO4", "K", "Ca", "Mg",
                       "SO4", "Cl", "Na", "HCO3", "B", "Fe", "Mn", "Cu", "Zn"],
}

# Nombre legible de cada parametro. Lo que no este aca se muestra tal cual.
PARAM_EN = {
    "N Total": "Total N", "N Disponible": "Available N", "P Disponible": "Available P",
    "K Disponible": "Available K", "MO": "Organic matter", "CIC": "CEC",
    "Ca Cambio": "Exchangeable Ca", "Mg Cambio": "Exchangeable Mg",
    "K Cambio": "Exchangeable K", "Na Cambio": "Exchangeable Na",
    "Suma Bases": "Sum of bases", "Saturacion Bases": "Base saturation",
    "Saturacion Pasta": "Saturation percentage", "Caliza Activa": "Active lime",
    "Carbonato Total": "Total carbonate", "Arena": "Sand", "Limo": "Silt",
    "Arcilla": "Clay", "DA": "Bulk density", "Profundidad Efectiva": "Effective depth",
    "Capacidad Estanque": "Reservoir capacity", "CRACC": "Water holding (FC)",
    "CRAPMP": "Water holding (PWP)", "Ca soluble": "Soluble Ca",
    "Mg soluble": "Soluble Mg", "K soluble": "Soluble K", "Na soluble": "Soluble Na",
    "Cl soluble": "Soluble Cl", "SO4 soluble": "Soluble SO4",
    "HCO3 soluble": "Soluble HCO3", "B soluble": "Soluble B",
    "Ca soluble meq": "Soluble Ca", "Mg soluble meq": "Soluble Mg",
    "K soluble meq": "Soluble K", "Na soluble meq": "Soluble Na",
    "Cl soluble meq": "Soluble Cl", "SO4 soluble meq": "Soluble SO4",
    "HCO3 soluble meq": "Soluble HCO3",
}

ESTADOS = ["deficiente", "bajo", "optimo", "alto", "excesivo"]


# ----------------------------------------------------------------- utilidades

def norm(s):
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def num(v):
    """Convierte a float tolerando coma decimal, '<0,01' y celdas de texto."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = norm(v).replace(",", ".")
    if not t:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def fecha_iso(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", norm(v))
    return m.group(0) if m else None


def hojas(xlsx):
    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    out = {}
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        try:
            hdr = [norm(h) for h in next(it)]
        except StopIteration:
            out[ws.title] = []
            continue
        out[ws.title] = [dict(zip(hdr, r)) for r in it if not all(c is None for c in r)]
    wb.close()
    return out


# -------------------------------------------------------------- UTM -> WGS84

def utm_a_wgs84(este, norte, zona=19, sur=True):
    """Inversa de la transversa de Mercator (WGS84). Sin dependencias externas.

    Se usa solo para las 13 calicatas del estudio 2018, que vienen en UTM. El
    archivo no declara la zona; 19S es la unica que cae sobre el predio, y el
    resultado se valida contra el bbox del KMZ antes de escribirlo.
    """
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    e_p2 = e2 / (1 - e2)
    k0 = 0.9996
    x = este - 500000.0
    y = norte - (10000000.0 if sur else 0.0)

    m = y / k0
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    phi1 = (mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))

    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = a / math.sqrt(1 - e2 * s * s)
    t1 = t * t
    c1 = e_p2 * c * c
    r1 = a * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = x / (n1 * k0)

    lat = phi1 - (n1 * t / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * e_p2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * e_p2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d
           - (1 + 2 * t1 + c1) * d ** 3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * e_p2 + 24 * t1 ** 2) * d ** 5 / 120) / c

    lon0 = math.radians((zona - 1) * 6 - 180 + 3)
    return round(math.degrees(lon0 + lon), 6), round(math.degrees(lat), 6)


# --------------------------------------------------------- punto en poligono

def _en_anillo(lon, lat, anillo):
    """Ray casting. Suficiente para 13 puntos contra 53 poligonos."""
    dentro = False
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i][0], anillo[i][1]
        x2, y2 = anillo[(i + 1) % n][0], anillo[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            xin = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < xin:
                dentro = not dentro
    return dentro


def _en_geom(lon, lat, geom):
    partes = (geom["coordinates"] if geom["type"] == "MultiPolygon"
              else [geom["coordinates"]])
    for poly in partes:
        if not poly or not _en_anillo(lon, lat, poly[0]):
            continue
        if any(_en_anillo(lon, lat, hueco) for hueco in poly[1:]):
            continue
        return True
    return False


def ubicacion_en(geo, lon, lat):
    """Ubicacion E#-S#-C# que contiene el punto, o None si cae fuera."""
    for f in geo["ubicaciones"]["features"]:
        if _en_geom(lon, lat, f["geometry"]):
            return f["properties"]["id"]
    return None


# ------------------------------------------------------------------- umbrales

def clave_param(parametro, unidad):
    return "%s [%s]" % (parametro, unidad if unidad else "-")


def construir_umbral(cfg, margen_default):
    """Traduce una entrada de umbrales_nutricion.json a bandas ordenadas."""
    direccion = cfg.get("direccion", "rango")
    fuente = cfg.get("fuente", "referencia")
    nota = cfg.get("nota")
    margen = cfg.get("margen", margen_default)

    if direccion == "menor_mejor":
        a, b = float(cfg["opt_max"]), float(cfg["alto_max"])
        bandas = [
            {"estado": "optimo", "min": None, "max": a},
            {"estado": "alto", "min": a, "max": b},
            {"estado": "excesivo", "min": b, "max": None},
        ]
    elif direccion == "mayor_mejor":
        a, b = float(cfg["bajo_max"]), float(cfg["opt_min"])
        bandas = [
            {"estado": "deficiente", "min": None, "max": a},
            {"estado": "bajo", "min": a, "max": b},
            {"estado": "optimo", "min": b, "max": None},
        ]
    else:
        lo, hi = float(cfg["min"]), float(cfg["max"])
        d0 = max(lo * margen, (hi - lo) * margen)
        d1 = max(hi * margen, (hi - lo) * margen)
        bandas = [
            {"estado": "deficiente", "min": None, "max": round(lo - d0, 4)},
            {"estado": "bajo", "min": round(lo - d0, 4), "max": lo},
            {"estado": "optimo", "min": lo, "max": hi},
            {"estado": "alto", "min": hi, "max": round(hi + d1, 4)},
            {"estado": "excesivo", "min": round(hi + d1, 4), "max": None},
        ]

    return {"direccion": direccion, "fuente": fuente, "nota": nota,
            "optimo": ([cfg.get("min"), cfg.get("max")] if direccion == "rango"
                       else [None, cfg.get("opt_max")] if direccion == "menor_mejor"
                       else [cfg.get("opt_min"), None]),
            "bandas": bandas}


def estado_de(valor, umbral):
    if valor is None or not umbral:
        return None
    for b in umbral["bandas"]:
        lo = b["min"] if b["min"] is not None else -math.inf
        hi = b["max"] if b["max"] is not None else math.inf
        if lo <= valor < hi or (b["max"] is None and valor >= lo):
            return b["estado"]
    return umbral["bandas"][-1]["estado"]


# -------------------------------------------------------------------- proceso

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="Base_Datos_Suelos_Foliares_Ketcal_SEMBRADOR_v2.xlsx")
    ap.add_argument("--geo", default="geo_data.json")
    ap.add_argument("--umbrales", default="umbrales_nutricion.json")
    ap.add_argument("--out", default="nutricion_data.json")
    args = ap.parse_args()

    for p in (args.xlsx, args.geo, args.umbrales):
        if not Path(p).exists():
            sys.exit("ERROR: no existe %s" % p)

    issues = []
    sh = hojas(args.xlsx)
    geo = json.loads(Path(args.geo).read_text(encoding="utf-8"))
    cfg_umb = json.loads(Path(args.umbrales).read_text(encoding="utf-8"))
    margen_default = cfg_umb.get("margen_default", 0.25)

    ubi_geo = {f["properties"]["id"]: f["properties"] for f in geo["ubicaciones"]["features"]}
    bbox = geo["bbox"]

    # ── Maestro: metadatos agronomicos por ubicacion ────────────────────────
    maestro = {}
    for r in sh.get("Maestro_Ubicaciones", []):
        uid = norm(r.get("ID_Ubicacion"))
        if not uid:
            continue
        maestro[uid] = {
            "portainjerto": norm(r.get("Portainjertos")) or None,
            "anio_plantacion": norm(r.get("Anio_Plantacion")) or None,
            "centro_costo": norm(r.get("Centro_Costo")) or None,
            "rol": norm(r.get("Rol")) or None,
            "caseta": norm(r.get("Caseta")) or None,
            "sup_diseno_ha": num(r.get("Sup_Diseno_Ha")),
            "sistema_conduccion": norm(r.get("Sistema_Conduccion")) or None,
            "dist_goteros": num(r.get("Dist_Goteros")),
            "caudal_emisor": num(r.get("Caudal_Emisor")),
            "goteros_ha": num(r.get("Goteros_Ha")),
        }
        if uid not in ubi_geo:
            issues.append({"nivel": "alerta", "tipo": "maestro_sin_geometria",
                           "detalle": "Maestro_Ubicaciones trae %s, que no existe en "
                                      "geo_data.json" % uid})

    # Plantas/ha y variedades desde Detalle_Plantaciones, agregado por ubicacion.
    plantas = defaultdict(list)
    for r in sh.get("Detalle_Plantaciones", []):
        uid = "E%s-S%s-C%s" % (norm(r.get("Equipo")), norm(r.get("Sector")),
                               norm(r.get("Cuartel")))
        v = num(r.get("Plantas_Ha"))
        if v:
            plantas[uid].append(v)
    for uid, vs in plantas.items():
        if uid in maestro:
            maestro[uid]["plantas_ha"] = round(sum(vs) / len(vs))

    # ── Muestras: laboratorio, fechas y trazabilidad al PDF de origen ───────
    muestras = {}
    for r in sh.get("Muestras", []):
        mid = norm(r.get("ID_Muestra"))
        if not mid:
            continue
        muestras[mid] = {
            "lab": norm(r.get("Laboratorio")) or None,
            "matriz": norm(r.get("Matriz")) or None,
            "f_muestreo": fecha_iso(r.get("Fecha_Muestreo")),
            "f_informe": fecha_iso(r.get("Fecha_Informe")),
            "f_ingreso": fecha_iso(r.get("Fecha_Ingreso")),
            "identificacion": norm(r.get("Identificacion_Fuente")) or None,
            "edad": norm(r.get("Edad_Fuente")) or None,
            "estado_asignacion": norm(r.get("Estado_Asignacion")) or None,
        }

    fuente_pdf = {}
    for r in sh.get("Asignaciones_Mapeo", []):
        mid = norm(r.get("ID_Muestra"))
        if mid and mid not in fuente_pdf:
            fuente_pdf[mid] = {"archivo": norm(r.get("Archivo_Fuente")) or None,
                               "pagina": norm(r.get("Pagina_Fuente")) or None,
                               "regla": norm(r.get("Regla_Asignacion")) or None,
                               "multi": norm(r.get("Es_Multiubicacion")) == "Si"}

    # ── Umbrales ────────────────────────────────────────────────────────────
    umbrales = {}
    for matriz, tabla in cfg_umb.get("umbrales", {}).items():
        for clave, c in tabla.items():
            try:
                umbrales[(matriz, clave)] = construir_umbral(c, margen_default)
            except (KeyError, TypeError, ValueError) as e:
                issues.append({"nivel": "error", "tipo": "umbral_invalido",
                               "detalle": "%s / %s: %s" % (matriz, clave, e)})

    # ── Lecturas ────────────────────────────────────────────────────────────
    lecturas = []
    sin_valor = sin_geom = 0
    claves_huerfanas = set()
    for r in sh.get("Resultados_Mapeables", []):
        matriz = norm(r.get("Matriz"))
        parametro = norm(r.get("Parametro"))
        unidad = norm(r.get("Unidad")) or None
        valor = num(r.get("Valor"))
        if not matriz or not parametro:
            continue
        if valor is None:
            sin_valor += 1
            continue

        mid = norm(r.get("ID_Muestra"))
        m = muestras.get(mid, {})
        fecha = (fecha_iso(r.get("Fecha_Muestreo")) or m.get("f_muestreo")
                 or m.get("f_informe") or m.get("f_ingreso"))
        fecha_aprox = fecha_iso(r.get("Fecha_Muestreo")) is None and fecha is not None

        uid = norm(r.get("Clave_Mapa")) or None
        if uid and uid not in ubi_geo:
            claves_huerfanas.add(uid)
            sin_geom += 1

        prof = norm(r.get("Profundidad_Fuente")) or None
        clave = clave_param(parametro, unidad)
        umb = umbrales.get((matriz, clave))

        lecturas.append({
            "m": matriz,
            "u": uid,
            "f": fecha,
            "fa": 1 if fecha_aprox else 0,
            "p": parametro,
            "un": unidad,
            "d": prof,
            "v": round(valor, 6),
            "e": estado_de(valor, umb),
            "cl": norm(r.get("Clasificacion_Fuente")) or None,
            "es": norm(r.get("Especie")) or None,
            "lab": norm(r.get("Laboratorio")) or None,
            "id": mid or None,
        })

    if sin_valor:
        issues.append({"nivel": "info", "tipo": "valor_no_numerico",
                       "detalle": "%d filas sin valor numerico, omitidas" % sin_valor})
    for k in sorted(claves_huerfanas):
        issues.append({"nivel": "alerta", "tipo": "clave_sin_geometria",
                       "detalle": "Clave_Mapa %s no existe en geo_data.json" % k})

    # ── Catalogo de parametros por matriz ───────────────────────────────────
    params = defaultdict(dict)
    for l in lecturas:
        clave = clave_param(l["p"], l["un"])
        d = params[l["m"]].setdefault(clave, {
            "id": clave, "parametro": l["p"], "unidad": l["un"],
            "es": l["p"], "en": PARAM_EN.get(l["p"], l["p"]),
            "n": 0, "vals": [],
        })
        d["n"] += 1
        d["vals"].append(l["v"])

    catalogo = {}
    sin_umbral = []
    for matriz, tabla in params.items():
        salida = []
        for clave, d in tabla.items():
            vals = sorted(d.pop("vals"))
            d["min"] = round(vals[0], 4)
            d["max"] = round(vals[-1], 4)
            d["p50"] = round(vals[len(vals) // 2], 4)
            umb = umbrales.get((matriz, clave))
            if umb:
                d["escala"] = "umbral"
                d["umbral"] = umb
            else:
                # Sin umbral agronomico: cuartiles del propio predio, declarados
                # como escala relativa. No es un umbral y el mapa lo dice.
                def q(p):
                    return round(vals[min(len(vals) - 1, int(p * (len(vals) - 1)))], 4)
                d["escala"] = "relativa"
                d["cuartiles"] = [q(0.25), q(0.50), q(0.75)]
                sin_umbral.append("%s / %s" % (matriz, clave))
            salida.append(d)
        orden = ORDEN_PARAM.get(matriz, [])
        salida.sort(key=lambda x: (orden.index(x["parametro"]) if x["parametro"] in orden
                                   else len(orden), -x["n"], x["unidad"] or ""))
        catalogo[matriz] = salida

    if sin_umbral:
        issues.append({"nivel": "info", "tipo": "sin_umbral",
                       "detalle": "%d parametros sin umbral en umbrales_nutricion.json; "
                                  "se pintan en escala relativa" % len(sin_umbral),
                       "items": sorted(sin_umbral)})

    # ── Campanas (fechas con dato) por matriz ───────────────────────────────
    campanas = {}
    for matriz in {l["m"] for l in lecturas}:
        por_fecha = Counter(l["f"] for l in lecturas if l["m"] == matriz)
        campanas[matriz] = [
            {"fecha": f, "n": n,
             "ubicaciones": len({l["u"] for l in lecturas
                                 if l["m"] == matriz and l["f"] == f and l["u"]}),
             "aprox": all(l["fa"] for l in lecturas if l["m"] == matriz and l["f"] == f)}
            for f, n in sorted(por_fecha.items(), key=lambda kv: (kv[0] is None, kv[0]),
                               reverse=True)
        ]

    # ── Calicatas 2018, reproyectadas ───────────────────────────────────────
    # Las lecturas de linea base no tienen ubicacion E#-S#-C#, pero si tienen
    # calicata: el ID_Muestra es BASE2018-CAL-<n>. Se cuelgan del punto, que es
    # donde efectivamente se midieron.
    perfil_2018 = defaultdict(list)
    for l in lecturas:
        if not l["m"].endswith("LineaBase") or not l["id"]:
            continue
        # BASE2018-CAL-<n> es el analisis fisico; BASE2018-Q-<n>, el quimico.
        # En los dos, <n> es el numero de calicata.
        m = re.match(r"BASE2018-(?:CAL|Q)-(\w+)$", l["id"])
        if m:
            perfil_2018["CAL-%s" % m.group(1)].append(
                {"p": l["p"], "un": l["un"], "v": l["v"], "d": l["d"], "m": l["m"]})
    huerfanas = set(perfil_2018) - {"CAL-%s" % norm(r.get("Calicata"))
                                    for r in sh.get("Calicatas_2018", [])}
    for c in sorted(huerfanas):
        issues.append({"nivel": "alerta", "tipo": "perfil_sin_calicata",
                       "detalle": "hay lecturas de linea base para %s, que no esta en "
                                  "Calicatas_2018 (sin coordenadas, no se puede mapear)" % c})

    calicatas = []
    fuera = 0
    for r in sh.get("Calicatas_2018", []):
        este, norte = num(r.get("UTM_Este")), num(r.get("UTM_Norte"))
        if este is None or norte is None:
            continue
        lon, lat = utm_a_wgs84(este, norte)
        dentro = (bbox[0] - 0.01 <= lon <= bbox[2] + 0.01
                  and bbox[1] - 0.01 <= lat <= bbox[3] + 0.01)
        if not dentro:
            fuera += 1
        cid = "CAL-%s" % norm(r.get("Calicata"))
        calicatas.append({
            "type": "Feature",
            "properties": {
                "id": cid,
                "calicata": norm(r.get("Calicata")),
                "perfil": sorted(perfil_2018.get(cid, []),
                                 key=lambda x: (x["m"], x["p"])),
                "textura": norm(r.get("Textura")) or None,
                "arena": num(r.get("Arena_%")), "limo": num(r.get("Limo_%")),
                "arcilla": num(r.get("Arcilla_%")),
                "crapmp": num(r.get("CRAPMP")), "cracc": num(r.get("CRACC")),
                "capacidad_estanque": num(r.get("Capacidad_Estanque")),
                "prof_efectiva_cm": num(r.get("Profundidad_Efectiva_cm")),
                "datum": norm(r.get("Datum")) or None,
                "dentro_predio": dentro,
                "ubicacion": ubicacion_en(geo, lon, lat),
            },
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        })
    if fuera:
        issues.append({"nivel": "alerta", "tipo": "calicata_fuera_de_bbox",
                       "detalle": "%d calicatas caen fuera del predio al reproyectar desde "
                                  "UTM 19S; el Excel no declara la zona" % fuera})

    # ── Contexto cualitativo del estudio 2018 ───────────────────────────────
    unidades_suelo = [{norm(k): norm(v) or None for k, v in r.items() if k}
                      for r in sh.get("Unidades_Suelo_2018", [])]
    limitantes = [{norm(k): (num(v) if k == "Valor_Base" else norm(v) or None)
                   for k, v in r.items() if k}
                  for r in sh.get("Limitantes_2018", [])]
    pendientes = [{norm(k): norm(v) or None for k, v in r.items() if k}
                  for r in sh.get("Pendientes_Mapeo", []) if norm(r.get("ID_Muestra"))]
    fuentes = [{norm(k): norm(v) or None for k, v in r.items() if k}
               for r in sh.get("Fuentes", []) if norm(r.get("Archivo"))]

    # ── Cobertura por ubicacion ─────────────────────────────────────────────
    cobertura = {}
    for uid in sorted({l["u"] for l in lecturas if l["u"]}):
        sub = [l for l in lecturas if l["u"] == uid]
        cobertura[uid] = {
            "n": len(sub),
            "matrices": sorted({l["m"] for l in sub}),
            "fechas": sorted({l["f"] for l in sub if l["f"]}, reverse=True),
            "labs": sorted({l["lab"] for l in sub if l["lab"]}),
            **(maestro.get(uid) or {}),
        }
    for uid in ubi_geo:
        if uid not in cobertura:
            cobertura.setdefault(uid, {"n": 0, "matrices": [], "fechas": [], "labs": [],
                                       **(maestro.get(uid) or {})})

    salida = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": Path(args.xlsx).name,
        "umbrales_source": Path(args.umbrales).name,
        "margen_default": margen_default,
        "estados": ESTADOS,
        "matrices": [
            {"id": mid, "grupo": grupo, "es": es, "en": en, "mapeable": mapeable,
             "n": sum(1 for l in lecturas if l["m"] == mid),
             "ubicaciones": len({l["u"] for l in lecturas if l["m"] == mid and l["u"]}),
             "profundidades": sorted({l["d"] for l in lecturas if l["m"] == mid and l["d"]}),
             "labs": sorted({l["lab"] for l in lecturas if l["m"] == mid and l["lab"]})}
            for mid, grupo, es, en, mapeable in MATRICES
            if any(l["m"] == mid for l in lecturas)
        ],
        "params": catalogo,
        "campanas": campanas,
        "lecturas": lecturas,
        "cobertura": cobertura,
        "muestras": {k: dict(v, **(fuente_pdf.get(k) or {})) for k, v in muestras.items()},
        "calicatas": {"type": "FeatureCollection", "features": calicatas},
        "unidades_suelo_2018": unidades_suelo,
        "limitantes_2018": limitantes,
        "pendientes_revision": pendientes,
        "fuentes": fuentes,
        "totales": {
            "lecturas": len(lecturas),
            "muestras": len({l["id"] for l in lecturas if l["id"]}),
            "ubicaciones_con_dato": len({l["u"] for l in lecturas if l["u"]}),
            "ubicaciones_totales": len(ubi_geo),
            "parametros": sum(len(v) for v in catalogo.values()),
            "con_umbral": sum(1 for v in catalogo.values() for d in v
                              if d["escala"] == "umbral"),
            "calicatas": len(calicatas),
        },
        "issues": issues,
    }

    out = Path(args.out)
    out.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    t = salida["totales"]
    print("OK  %s  (%.0f KB)" % (out, out.stat().st_size / 1024))
    print("    lecturas %d - muestras %d - parametros %d (%d con umbral)"
          % (t["lecturas"], t["muestras"], t["parametros"], t["con_umbral"]))
    print("    ubicaciones con dato %d de %d - calicatas %d"
          % (t["ubicaciones_con_dato"], t["ubicaciones_totales"], t["calicatas"]))
    for m in salida["matrices"]:
        print("      %-26s n=%-5d ubic=%-3d fechas=%d"
              % (m["id"], m["n"], m["ubicaciones"], len(campanas.get(m["id"], []))))
    if issues:
        print("    ISSUES (%d):" % len(issues))
        for i in issues:
            print("      [%s] %s" % (i["nivel"], i["detalle"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
