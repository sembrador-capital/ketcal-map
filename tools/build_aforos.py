#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convierte la base de aforos de goteros en `aforos_data.json`, la fuente de la
subpestana "Aforos" de Riego.

Un aforo de goteros mide el caudal de 16 emisores de una VALVULA, repartidos en
una grilla de 4 x 4: cuatro posiciones a lo largo del lateral (inicial, 1/3,
2/3, ultimo) por cuatro posiciones dentro de cada lateral (primer emisor, 1/3,
2/3, ultimo). Esa grilla no es decorativa: es la que separa un problema de
presion —que se ve al final del lateral— de uno de obturacion, que aparece
disperso.

De las 16 lecturas salen las tres cifras de la ficha:

    QA   caudal medio de los 16 emisores, en L/h
    Q25  caudal medio del 25 % de MENOR emision, o sea los 4 mas bajos
    CU   coeficiente de uniformidad = Q25 / QA x 100

CU es la unidad principal y la que pinta el mapa. Mide cuanto le falta al cuarto
peor regado respecto del promedio: un CU de 75 % significa que la parte mas
castigada del sector recibe tres cuartos del agua que recibe el promedio, y
regar hasta que esa parte quede satisfecha implica pasarse un tercio en el
resto. Es la definicion de Merriam & Keller, la misma que usa la planilla
fuente en su columna "CUC calculado" (verificado: coincide en las 57 zonas).

CRUCE CON EL MAPA
-----------------
Las 57 zonas aforadas cruzan 1 a 1 con las valvulas del KMZ, que ya se llaman
igual: la hoja `Z14-S2-E1` es la valvula `E1-S2-Z14` de `geo_data.json`. Por eso
los aforos se pueden pintar donde de verdad se midieron —el punto de la
valvula— y no solo como un promedio del sector. Cubren 57 de las 150 valvulas y
14 de los 28 sectores; los que faltan se dibujan en gris y la leyenda lo dice.

DECISIONES
----------
* El CU de un sector es el PROMEDIO de los CU de sus zonas, no el CU del monton
  de emisores juntos. Cada valvula se opera por separado y su uniformidad es un
  problema propio; juntar 64 emisores de cuatro valvulas distintas en una sola
  poblacion mezclaria la variacion entre valvulas con la de adentro de cada una,
  que es lo que el aforo quiere medir. El CU agrupado se guarda igual, como
  `cu_pool`, y la ficha muestra ademas la PEOR zona, que es por donde se parte.

* El caudal nominal del emisor es 3,0 L/h en todo el predio (base de nutricion,
  50 de 53 ubicaciones, sin un solo valor distinto). Con eso el QA medido se
  puede leer como porcentaje del nominal, que es lo que dice si el equipo esta
  entregando lo que se diseno.

* Las fechas de `Sector 4 - E1.xlsx` estan arruinadas por un arrastre de Excel:
  la ficha original tiene una sola fecha y el archivo trae 96 filas donde el
  anio avanza de uno en uno, 19/01/2026, 19/01/2027 ... 19/01/2105. Se toma la
  fecha MINIMA de cada ficha, que es la unica que sobrevive al arrastre, y queda
  anotado en `issues`. El control de calidad de la planilla no lo detecto.

Uso:
    python tools/build_aforos.py [--xlsx RUTA] [--geo geo_data.json]
                                 [--out aforos_data.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

XLSX = "datos_fuente/Ketcal_Base_Aforos_Goteros_vFinal.xlsx"

# Clasificacion de funcionamiento por uniformidad. Son los cortes de Ketcal,
# no los del estandar: cuatro clases y no cinco, con todo lo que baja de 70 %
# en una sola bolsa de "inaceptable" en vez de separar pobre e inaceptable.
#
# Las bandas se evaluan en orden y cada una es [min, min de la anterior). En 70
# exacto manda "regular", que es como esta escrito el corte. Hoy no cambia nada:
# la peor valvula del predio da 75,0 %.
#
# Si los cortes cambian, se cambian aca: el mapa, la leyenda, las fichas y el
# modal los leen del JSON.
ESCALA_CU = [
    {"clave": "excelente",   "min": 90,   "es": "Excelente",   "en": "Excellent",    "token": "--dat-cu-1"},
    {"clave": "buena",       "min": 80,   "es": "Buena",       "en": "Good",         "token": "--dat-cu-2"},
    {"clave": "regular",     "min": 70,   "es": "Regular",     "en": "Fair",         "token": "--dat-cu-3"},
    {"clave": "inaceptable", "min": None, "es": "Inaceptable", "en": "Unacceptable", "token": "--dat-cu-5"},
]

CAUDAL_NOMINAL_LH = 3.0

# Las cuatro posiciones de la grilla, en orden fisico. La ficha las escribe con
# tildes y mayusculas inconsistentes ("Ultimo lateral" / "Último emisor").
ORDEN_LATERAL = ["Lateral inicial", "1/3 lateral", "2/3 lateral", "Ultimo lateral"]
ORDEN_GOTERO = ["Primer emisor", "emisor 1/3", "emisor 2/3", "Último emisor"]
LATERAL_CORTO = {"Lateral inicial": "Inicial", "1/3 lateral": "1/3",
                 "2/3 lateral": "2/3", "Ultimo lateral": "Último"}
GOTERO_CORTO = {"Primer emisor": "Primero", "emisor 1/3": "1/3",
                "emisor 2/3": "2/3", "Último emisor": "Último"}
LATERAL_EN = {"Lateral inicial": "First", "1/3 lateral": "1/3",
              "2/3 lateral": "2/3", "Ultimo lateral": "Last"}
GOTERO_EN = {"Primer emisor": "First", "emisor 1/3": "1/3",
             "emisor 2/3": "2/3", "Último emisor": "Last"}

RX_HOJA = re.compile(r"^Z(\d+)\s*-\s*S(\d+)\s*-\s*E(\d+)$", re.I)


def norm(s):
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ".").strip())
    except ValueError:
        return None


def r2(v, d=2):
    return None if v is None else round(float(v), d)


def ilat(v):
    return ORDEN_LATERAL.index(v) if v in ORDEN_LATERAL else 9


def ipos(v):
    return ORDEN_GOTERO.index(v) if v in ORDEN_GOTERO else 9


def clave_cu(cu):
    for b in ESCALA_CU:
        if b["min"] is None or cu >= b["min"]:
            return b["clave"]
    return ESCALA_CU[-1]["clave"]


def uniformidad(caudales):
    """(QA, Q25, CU, CV) de una lista de caudales en L/h.

    Q25 es la media del cuarto de MENOR emision. Con 16 lecturas son 4 exactos;
    `round` deja el reparto correcto para cualquier n (nunca menos de 1)."""
    qs = sorted(c for c in caudales if c is not None)
    n = len(qs)
    if not n:
        return None, None, None, None
    k = max(1, int(round(n * 0.25)))
    qa = sum(qs) / n
    q25 = sum(qs[:k]) / k
    cu = 100.0 * q25 / qa if qa else None
    if n > 1:
        var = sum((q - qa) ** 2 for q in qs) / (n - 1)
        cv = 100.0 * (var ** 0.5) / qa if qa else None
    else:
        cv = None
    return qa, q25, cu, cv


def resumen(caudales):
    qa, q25, cu, cv = uniformidad(caudales)
    qs = [c for c in caudales if c is not None]
    return OrderedDict([
        ("n", len(qs)),
        ("qa", r2(qa, 3)),
        ("q25", r2(q25, 3)),
        ("cu", r2(cu, 1)),
        ("cv", r2(cv, 1)),
        ("qmin", r2(min(qs), 2) if qs else None),
        ("qmax", r2(max(qs), 2) if qs else None),
        ("pct_nominal", r2(100.0 * qa / CAUDAL_NOMINAL_LH, 1) if qa else None),
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default=XLSX)
    ap.add_argument("--geo", default="geo_data.json")
    ap.add_argument("--out", default="aforos_data.json")
    args = ap.parse_args()

    if not Path(args.xlsx).exists():
        sys.exit("ERROR: no existe %s" % args.xlsx)
    if not Path(args.geo).exists():
        sys.exit("ERROR: no existe %s" % args.geo)

    issues = []
    geo = json.loads(Path(args.geo).read_text(encoding="utf-8"))
    valvulas = {f["properties"]["id"]: f["properties"]
                for f in geo["valvulas"]["features"]}
    sect_geo = {f["properties"]["id"]: f["properties"]
                for f in geo["sectores"]["features"]}
    eq_geo = {f["properties"]["id"]: f["properties"]
              for f in geo["equipos"]["features"]}

    wb = openpyxl.load_workbook(args.xlsx, data_only=True, read_only=True)
    filas = list(wb["Base_Aforos"].iter_rows(values_only=True))
    wb.close()
    hdr = {h: i for i, h in enumerate(filas[0]) if h}

    def c(fila, nombre):
        i = hdr.get(nombre)
        return fila[i] if i is not None else None

    # ── Lecturas, agrupadas por zona ───────────────────────────────────────
    # La clave sale de `Hoja origen` y no de las columnas numericas: 32 filas
    # traen `Valvula N` vacio y su numero solo esta en el nombre de la hoja.
    por_zona = OrderedDict()
    fechas_ficha = defaultdict(set)
    sin_clave = 0
    for f in filas[1:]:
        hoja = norm(c(f, "Hoja origen"))
        m = RX_HOJA.match(hoja or "")
        if not m:
            sin_clave += 1
            continue
        z, s, e = (int(x) for x in m.groups())
        zid = "E%d-S%d-Z%d" % (e, s, z)
        lh = num(c(f, "Caudal L/h"))
        if lh is None:
            mlmin = num(c(f, "Caudal ml/min"))
            lh = mlmin * 0.06 if mlmin is not None else None
        por_zona.setdefault(zid, []).append({
            "e": c(f, "Emisor N°"),
            "lat": norm(c(f, "Posición lateral")),
            "pos": norm(c(f, "Posición gotero")),
            "lh": lh,
            "fecha": c(f, "Fecha"),
            "cultivo": norm(c(f, "Cultivo declarado")),
            "resp": norm(c(f, "Responsable")),
            "archivo": norm(c(f, "Archivo origen")),
            "hoja": hoja,
        })
        arch = norm(c(f, "Archivo origen"))
        fe = c(f, "Fecha")
        if arch and isinstance(fe, datetime):
            fechas_ficha[arch].add(fe.date())

    if sin_clave:
        issues.append({"nivel": "warn",
                       "msg": "%d fila(s) sin `Hoja origen` interpretable; se "
                              "descartan" % sin_clave})

    # ── La fecha de cada ficha ─────────────────────────────────────────────
    # Un aforo es de un dia. Cuando una ficha trae varias fechas es un arrastre
    # de Excel, no dos campanas: se toma la minima y se anota.
    fecha_de_ficha = {}
    for arch, fs in fechas_ficha.items():
        fecha_de_ficha[arch] = min(fs)
        if len(fs) > 1:
            issues.append({
                "nivel": "warn", "archivo": arch,
                "msg": "la ficha trae %d fechas distintas (de %s a %s): "
                       "arrastre de Excel en la celda de fecha. Se usa la "
                       "minima." % (len(fs), min(fs), max(fs))})

    hoy = datetime.now(timezone.utc).date()
    for arch, fe in sorted(fecha_de_ficha.items()):
        if fe > hoy:
            issues.append({
                "nivel": "warn", "archivo": arch,
                "msg": "fecha de aforo en el futuro (%s). El resto de la "
                       "campana es de enero de 2026; revisar la ficha." % fe})

    # ── Zonas ──────────────────────────────────────────────────────────────
    zonas = OrderedDict()
    for zid in sorted(por_zona, key=lambda k: (int(k.split("-")[0][1:]),
                                               int(k.split("-")[1][1:]),
                                               int(k.split("-Z")[1]))):
        ls = por_zona[zid]
        v = valvulas.get(zid)
        if not v:
            issues.append({"nivel": "warn", "zona": zid,
                           "msg": "zona aforada sin valvula en el KMZ; no se "
                                  "puede ubicar en el mapa"})
        arch = ls[0]["archivo"]
        cultivos = sorted({x["cultivo"] for x in ls if x["cultivo"]})
        r = resumen([x["lh"] for x in ls])
        faltan = [x for x in ls if x["lh"] is None]
        if faltan:
            issues.append({"nivel": "warn", "zona": zid,
                           "msg": "%d emisor(es) sin caudal" % len(faltan)})
        if r["n"] != 16:
            issues.append({"nivel": "info", "zona": zid,
                           "msg": "%d lecturas (lo normal son 16)" % r["n"]})
        fe = fecha_de_ficha.get(arch)
        zonas[zid] = OrderedDict([
            ("id", zid),
            ("name", v["name"] if v else zid),
            ("zona", int(zid.split("-Z")[1])),
            ("sector_id", "-".join(zid.split("-")[:2])),
            ("equipo_id", zid.split("-")[0]),
            ("fecha", fe.isoformat() if fe else None),
            ("cultivo", " / ".join(cultivos) or None),
            ("responsable", ls[0]["resp"]),
            ("clase", clave_cu(r["cu"]) if r["cu"] is not None else None),
            ("archivo", arch),
            ("hoja", ls[0]["hoja"]),
            # Las 16 lecturas van completas: son la grilla que dibuja la
            # ficha. Como tripletas [lateral, gotero, L/h] con los dos primeros
            # como indice en `grilla`, no como texto: escritos completos, los
            # nombres de posicion pesaban mas que todos los caudales juntos
            # (118 KB de archivo contra 46 KB). Ordenadas por la grilla fisica,
            # no por el numero de emisor, que es el orden en que se anotaron.
            ("lecturas", [[ilat(x["lat"]), ipos(x["pos"]), r2(x["lh"], 2)]
                for x in sorted(ls, key=lambda x: (ilat(x["lat"]), ipos(x["pos"])))]),
        ] + list(r.items()))

    # ── Agregados por sector y por equipo ──────────────────────────────────
    def agrupar(clave_fn, catalogo):
        out = OrderedDict()
        grupos = defaultdict(list)
        for zid, z in zonas.items():
            grupos[clave_fn(z)].append(z)
        for uid in sorted(grupos):
            zs = grupos[uid]
            cus = [z["cu"] for z in zs if z["cu"] is not None]
            todas = [l[2] for z in zs for l in z["lecturas"]]
            pool = resumen(todas)
            peor = min(zs, key=lambda z: z["cu"] if z["cu"] is not None else 999)
            cu = sum(cus) / len(cus) if cus else None
            meta = catalogo.get(uid) or {}
            out[uid] = OrderedDict([
                ("id", uid),
                ("name", meta.get("name") or uid),
                ("n_zonas", len(zs)),
                ("zonas", [z["id"] for z in zs]),
                ("fecha", min((z["fecha"] for z in zs if z["fecha"]), default=None)),
                ("cu", r2(cu, 1)),
                ("clase", clave_cu(cu) if cu is not None else None),
                ("cu_pool", pool["cu"]),
                ("cu_min", peor["cu"]),
                ("peor_zona", peor["id"]),
                ("qa", pool["qa"]),
                ("q25", pool["q25"]),
                ("cv", pool["cv"]),
                ("qmin", pool["qmin"]),
                ("qmax", pool["qmax"]),
                ("pct_nominal", pool["pct_nominal"]),
                ("n", pool["n"]),
            ])
        return out

    sectores = agrupar(lambda z: z["sector_id"], sect_geo)
    equipos = agrupar(lambda z: z["equipo_id"], eq_geo)

    sin_aforo = [s for s in sect_geo if s not in sectores]
    if sin_aforo:
        issues.append({"nivel": "info",
                       "msg": "%d de %d sectores sin aforo: %s"
                              % (len(sin_aforo), len(sect_geo),
                                 ", ".join(sorted(sin_aforo)))})

    todas = [l[2] for z in zonas.values() for l in z["lecturas"]]
    cus = [z["cu"] for z in zonas.values() if z["cu"] is not None]
    predio = OrderedDict(list(resumen(todas).items()))
    predio["cu_zonas"] = r2(sum(cus) / len(cus), 1) if cus else None
    predio["n_zonas"] = len(zonas)
    predio["n_valvulas"] = len(valvulas)
    predio["n_sectores"] = len(sectores)
    predio["n_sectores_geo"] = len(sect_geo)
    predio["reparto"] = OrderedDict(
        (b["clave"], sum(1 for z in zonas.values() if z["clase"] == b["clave"]))
        for b in ESCALA_CU)

    fechas = sorted(f for f in (z["fecha"] for z in zonas.values()) if f)
    payload = OrderedDict([
        ("generated_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
        ("source", {"archivo": Path(args.xlsx).name,
                    "fichas": len(fecha_de_ficha),
                    "zonas": len(zonas),
                    "mediciones": sum(z["n"] for z in zonas.values())}),
        ("nota", "CU = Q25 / QA x 100 (Merriam & Keller). Q25 es el caudal "
                 "medio del 25 % de emisores de menor emision. El CU de un "
                 "sector es el promedio de los CU de sus zonas."),
        ("caudal_nominal_lh", CAUDAL_NOMINAL_LH),
        ("escala_cu", ESCALA_CU),
        ("campana", {"desde": fechas[0] if fechas else None,
                     "hasta": fechas[-1] if fechas else None}),
        ("grilla", {"lateral": [LATERAL_CORTO[x] for x in ORDEN_LATERAL],
                    "gotero": [GOTERO_CORTO[x] for x in ORDEN_GOTERO],
                    "lateral_en": [LATERAL_EN[x] for x in ORDEN_LATERAL],
                    "gotero_en": [GOTERO_EN[x] for x in ORDEN_GOTERO],
                    "lateral_largo": ORDEN_LATERAL, "gotero_largo": ORDEN_GOTERO}),
        ("predio", predio),
        ("equipos", equipos),
        ("sectores", sectores),
        ("zonas", zonas),
        ("issues", issues),
    ])

    Path(args.out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── Resumen en consola ─────────────────────────────────────────────────
    kb = Path(args.out).stat().st_size / 1024
    print("OK  %s  (%.0f KB)" % (args.out, kb))
    print("    %d zonas aforadas de %d valvulas, %d mediciones, %d fichas"
          % (len(zonas), len(valvulas), sum(z["n"] for z in zonas.values()),
             len(fecha_de_ficha)))
    print("    %d de %d sectores con aforo, %d equipos"
          % (len(sectores), len(sect_geo), len(equipos)))
    print("    campana %s a %s" % (fechas[0] if fechas else "?",
                                   fechas[-1] if fechas else "?"))
    print("    predio  CU %.1f %%   QA %.2f L/h (%.0f %% del nominal)   Q25 %.2f L/h"
          % (predio["cu_zonas"], predio["qa"], predio["pct_nominal"], predio["q25"]))
    print("    reparto: " + "  ".join(
        "%s %d" % (b["es"], predio["reparto"][b["clave"]]) for b in ESCALA_CU))
    peores = sorted((z for z in zonas.values() if z["cu"] is not None),
                    key=lambda z: z["cu"])[:5]
    print("    peores zonas: " + ", ".join("%s %.1f %%" % (z["id"], z["cu"])
                                           for z in peores))
    if issues:
        print("    ISSUES (%d):" % len(issues))
        for i in issues:
            print("      [%s] %s" % (i["nivel"], i["msg"][:110]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
