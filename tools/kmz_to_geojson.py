#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Convierte `Ketcal KMZ.kmz` en `geo_data.json`: la fuente de verdad geometrica
del mapa de Ketcal.

Salida (un solo fetch para el mapa):

    {
      "generated_at": ..., "source": ..., "bbox": [...], "center": [lon, lat],
      "totales": {...},
      "equipos":     FeatureCollection  (5  poligonos, union de sus sectores)
      "sectores":    FeatureCollection  (28 poligonos)
      "cuarteles":   FeatureCollection  (30 poligonos)
      "ubicaciones": FeatureCollection  (53 poligonos, sector ∩ cuartel)
      "valvulas":    FeatureCollection  (150 puntos)
      "pozos":       FeatureCollection  (3 puntos)
    }

La relacion sector <-> cuartel NO viene en el KMZ: se calcula por interseccion
geometrica y queda en `properties.cuarteles` / `properties.sectores`, ordenada
por superficie compartida y filtrada por `MIN_OVERLAP`.

`ubicaciones` materializa esa interseccion como poligono propio, con la clave
`E#-S#-C#`. Es la unidad con la que la base de suelos y foliares referencia el
terreno (`Clave_Mapa`), asi que es la unidad que pinta la pestaña Nutricion.

Uso:  python tools/kmz_to_geojson.py [--kmz RUTA] [--out RUTA]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import Polygon, mapping
from shapely.ops import transform, unary_union

KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

# Un cuartel cuenta como "regado por" un sector si comparten al menos este
# porcentaje del cuartel. Por debajo es solape de borde por digitalizacion.
MIN_OVERLAP = 0.03

# Prefijo de id por especie de cuartel. La numeracion C1..Cn se repite entre
# especies en el KMZ, asi que el numero solo NO es una clave.
ESPECIE_PREFIJO = {"Limoneros": "LIM", "Naranjos": "NAR", "Mandarinos": "MAN"}
ESPECIE_CORTA = {"Limoneros": "Lim", "Naranjos": "Nar", "Mandarinos": "Man"}
ORDEN_ESPECIE = {"Limoneros": 0, "Naranjos": 1, "Mandarinos": 2}

RE_SECTOR_DESC = re.compile(r"([\d.]+)\s*H[aá]s?\s*-\s*([\d.]+)\s*m3/h", re.I)
RE_CUARTEL_DESC = re.compile(r"^(.*?)\s*-\s*([\d.]+)\s*[Hh][aá]?s?\.?$")
RE_SECTOR_NAME = re.compile(r"^E(\d+)\s*-\s*S(\d+)$")
RE_VALVULA = re.compile(r"^Z(\d+)\s*-\s*S(\d+)\s*-\s*E(\d+)$")


# --------------------------------------------------------------- utilidades

def norm(s):
    """Colapsa espacios y normaliza guiones unicode a ASCII."""
    s = unicodedata.normalize("NFC", s or "")
    for guion in ("–", "—", "−"):
        s = s.replace(guion, "-")
    return re.sub(r"\s+", " ", s).strip()


def parse_coords(text):
    pts = []
    for tok in (text or "").split():
        parts = tok.split(",")
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    return pts


def area_ha(geom, lat0):
    """Area en hectareas via proyeccion equirectangular local.

    A la escala del predio (~3 km) el error contra una geodesica real es
    < 0,1 %, muy por debajo de la precision con la que se digitalizo el KMZ.
    """
    k = math.cos(math.radians(lat0))
    m_por_grado = 111320.0
    plano = transform(lambda x, y, z=None: (x * k * m_por_grado, y * m_por_grado), geom)
    return plano.area / 10000.0


def round_geom(geom, nd=6):
    """Recorta coordenadas a ~0,1 m. Baja el peso del JSON a la mitad."""
    return transform(lambda x, y, z=None: (round(x, nd), round(y, nd)), geom)


# ------------------------------------------------------------- lectura KMZ

def leer_kml(kmz_path):
    with zipfile.ZipFile(kmz_path) as z:
        nombre = next((n for n in z.namelist() if n.lower().endswith(".kml")), None)
        if nombre is None:
            sys.exit("ERROR: %s no contiene ningun .kml" % kmz_path)
        raiz = ET.fromstring(z.read(nombre).decode("utf-8"))
    doc = raiz.find("k:Document", KML_NS)
    return doc if doc is not None else raiz


def recorrer(el, ruta=()):
    """Genera (ruta_de_carpetas, placemark) para todo el arbol."""
    for hijo in el:
        tag = hijo.tag.split("}")[-1]
        if tag == "Folder":
            nombre = hijo.find("k:name", KML_NS)
            yield from recorrer(hijo, ruta + (norm(nombre.text if nombre is not None else ""),))
        elif tag == "Placemark":
            yield ruta, hijo


def geom_de(pm):
    poly = pm.find(".//k:Polygon", KML_NS)
    if poly is not None:
        outer = poly.find(".//k:outerBoundaryIs//k:coordinates", KML_NS)
        anillo = parse_coords(outer.text if outer is not None else "")
        huecos = [parse_coords(c.text)
                  for c in poly.findall(".//k:innerBoundaryIs//k:coordinates", KML_NS)]
        if len(anillo) < 4:
            return None
        g = Polygon(anillo, [h for h in huecos if len(h) >= 4])
        return g if g.is_valid else g.buffer(0)
    pt = pm.find(".//k:Point//k:coordinates", KML_NS)
    if pt is not None:
        c = parse_coords(pt.text)
        return c[0] if c else None
    return None


def campo(pm, etiqueta):
    el = pm.find("k:%s" % etiqueta, KML_NS)
    return norm(el.text) if el is not None and el.text else ""


# --------------------------------------------------------------- extraccion

def extraer(doc):
    sectores, cuarteles, valvulas, pozos, avisos = [], [], [], [], []

    for ruta, pm in recorrer(doc):
        nombre = campo(pm, "name")
        desc = campo(pm, "description")
        el_desc = pm.find("k:description", KML_NS)
        desc_raw = (el_desc.text or "").strip() if el_desc is not None else ""
        g = geom_de(pm)
        if g is None:
            avisos.append("placemark sin geometria utilizable: %s :: %s"
                          % ("/".join(ruta), nombre))
            continue
        raiz = ruta[0] if ruta else ""

        if raiz.startswith("Equipos"):
            m = RE_SECTOR_NAME.match(nombre)
            if not m:
                avisos.append("nombre de sector no reconocido: %r" % nombre)
                continue
            eq, se = int(m.group(1)), int(m.group(2))
            md = RE_SECTOR_DESC.search(desc)
            if not md:
                avisos.append("descripcion de sector no parseada: %s: %r" % (nombre, desc))
            sectores.append({
                "id": "E%d-S%d" % (eq, se),
                "name": "E%d - S%d" % (eq, se),
                "equipo": eq,
                "equipo_id": "E%d" % eq,
                "sector": se,
                "ha_kmz": float(md.group(1)) if md else None,
                "caudal_m3h": float(md.group(2)) if md else None,
                "geom": g,
            })

        elif raiz.startswith("Cuarteles"):
            especie = ruta[1] if len(ruta) > 1 else "?"
            num = int(re.sub(r"\D", "", nombre) or 0)
            md = RE_CUARTEL_DESC.match(desc)
            variedades = []
            if md:
                variedades = [v.strip() for v in md.group(1).split("/") if v.strip()]
            else:
                avisos.append("descripcion de cuartel no parseada: %s %s: %r"
                              % (especie, nombre, desc))
            cuarteles.append({
                "id": "%s-C%d" % (ESPECIE_PREFIJO.get(especie, "XXX"), num),
                "name": "%s C%d" % (ESPECIE_CORTA.get(especie, especie), num),
                "especie": especie,
                "especie_corta": ESPECIE_CORTA.get(especie, especie),
                "numero": num,
                "variedades": variedades,
                "variedad": " / ".join(variedades),
                "ha_kmz": float(md.group(2)) if md else None,
                "geom": g,
            })

        elif raiz.startswith("V"):  # "Valvulas" / "Valvulas" con tilde
            m = RE_VALVULA.match(nombre)
            if not m:
                avisos.append("nombre de valvula no reconocido: %r" % nombre)
                continue
            z, se, eq = int(m.group(1)), int(m.group(2)), int(m.group(3))
            valvulas.append({
                "id": "E%d-S%d-Z%d" % (eq, se, z),
                "name": nombre,
                "zona": z,
                "sector": se,
                "equipo": eq,
                "sector_id": "E%d-S%d" % (eq, se),
                "equipo_id": "E%d" % eq,
                "lonlat": g,
            })

        elif raiz.startswith("Pozos"):
            bajo = desc.lower()
            estado = ("Operativo" if bajo.startswith("pozo operativo")
                      else "Parcialmente operativo" if "parcialmente" in bajo
                      else "No habilitado")
            pozos.append({
                "id": re.sub(r"\s+", "-", nombre.lower()),
                "name": nombre,
                "detalle": desc_raw.replace("\r\n", "\n"),
                "estado": estado,
                "operativo": estado == "Operativo",
                "lts_seg": max((float(x) for x in re.findall(r"([\d.]+)\s*lts/seg", desc)),
                               default=None),
                "lonlat": g,
            })
        else:
            avisos.append("carpeta raiz desconocida, ignorada: %r :: %s" % (raiz, nombre))

    return sectores, cuarteles, valvulas, pozos, avisos


# ------------------------------------------------------- relaciones espaciales

def cruzar(sectores, cuarteles, lat0, avisos):
    """Sector <-> cuartel por interseccion de superficie.

    Devuelve ademas la lista de ubicaciones `E#-S#-C#`: la interseccion misma,
    materializada como poligono.
    """
    for item in list(sectores) + list(cuarteles):
        item["_rel"] = []
    ubicaciones = []

    for s in sectores:
        ha_s = area_ha(s["geom"], lat0)
        for c in cuarteles:
            if not s["geom"].intersects(c["geom"]):
                continue
            inter = s["geom"].intersection(c["geom"])
            if inter.is_empty or inter.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            ha = area_ha(inter, lat0)
            frac_c = ha / max(area_ha(c["geom"], lat0), 1e-9)
            frac_s = ha / max(ha_s, 1e-9)
            if frac_c < MIN_OVERLAP and frac_s < MIN_OVERLAP:
                continue
            s["_rel"].append({"id": c["id"], "name": c["name"], "ha": round(ha, 2),
                              "frac": round(frac_s, 3), "_orden": ha})
            c["_rel"].append({"id": s["id"], "name": s["name"], "ha": round(ha, 2),
                              "frac": round(frac_c, 3), "_orden": ha})
            ubicaciones.append({
                "id": "%s-C%d" % (s["id"], c["numero"]),
                "sector_id": s["id"], "equipo_id": s["equipo_id"], "cuartel_id": c["id"],
                "equipo": s["equipo"], "sector": s["sector"], "cuartel": c["numero"],
                "especie": c["especie"], "especie_corta": c["especie_corta"],
                "variedad": c["variedad"], "variedades": c["variedades"],
                "ha": round(ha, 2),
                "frac_sector": round(frac_s, 3), "frac_cuartel": round(frac_c, 3),
                "geom": inter,
            })

    for coleccion, etiqueta in ((sectores, "sector"), (cuarteles, "cuartel")):
        for item in coleccion:
            item["_rel"].sort(key=lambda r: -r["_orden"])
            for r in item["_rel"]:
                r.pop("_orden")
            if not item["_rel"]:
                avisos.append("%s sin contraparte espacial: %s" % (etiqueta, item["id"]))

    vistos = set()
    for u in ubicaciones:
        if u["id"] in vistos:
            avisos.append("id de ubicacion duplicado: %s" % u["id"])
        vistos.add(u["id"])

    ubicaciones.sort(key=lambda u: (u["equipo"], u["sector"], u["cuartel"]))
    return ubicaciones


def tramos_de(nums):
    """1,2,3,7 -> 'C1-C3, C7'"""
    nums = sorted(set(nums))
    if not nums:
        return ""
    tramos, ini, prev = [], nums[0], nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        tramos.append((ini, prev))
        ini = prev = n
    tramos.append((ini, prev))
    return ", ".join("C%d" % a if a == b else "C%d-C%d" % (a, b) for a, b in tramos)


def resumen_cuarteles(rel, cuarteles_por_id):
    """Etiqueta tipo 'Lim - Messina/Fino - C1-C3', como la que usa el cliente."""
    if not rel:
        return {"especies": [], "variedades": [], "etiqueta": ""}
    cs = [cuarteles_por_id[r["id"]] for r in rel]
    especies, variedades = [], []
    for c in sorted(cs, key=lambda x: ORDEN_ESPECIE.get(x["especie"], 9)):
        if c["especie_corta"] not in especies:
            especies.append(c["especie_corta"])
        for v in c["variedades"]:
            if v not in variedades:
                variedades.append(v)
    partes = ["/".join(especies), "/".join(variedades), tramos_de(c["numero"] for c in cs)]
    return {"especies": especies, "variedades": variedades,
            "etiqueta": " - ".join(p for p in partes if p)}


# ---------------------------------------------------------------- ensamblado

def fc(features):
    return {"type": "FeatureCollection", "features": features}


def feature(geom, props):
    return {"type": "Feature", "properties": props, "geometry": mapping(round_geom(geom))}


def punto(d):
    lon, lat = d["lonlat"]
    return {"type": "Feature",
            "properties": {k: v for k, v in d.items() if k != "lonlat"},
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kmz", default="Ketcal KMZ.kmz")
    ap.add_argument("--out", default="geo_data.json")
    args = ap.parse_args()

    kmz = Path(args.kmz)
    if not kmz.exists():
        sys.exit("ERROR: no existe %s" % kmz)

    doc = leer_kml(kmz)
    sectores, cuarteles, valvulas, pozos, avisos = extraer(doc)

    todo = unary_union([s["geom"] for s in sectores] + [c["geom"] for c in cuarteles])
    minx, miny, maxx, maxy = todo.bounds
    lat0 = (miny + maxy) / 2.0

    ubicaciones = cruzar(sectores, cuarteles, lat0, avisos)
    por_id = {c["id"]: c for c in cuarteles}

    valv_por_sector = {}
    for v in valvulas:
        valv_por_sector[v["sector_id"]] = valv_por_sector.get(v["sector_id"], 0) + 1
    for sid in valv_por_sector:
        if sid not in {s["id"] for s in sectores}:
            avisos.append("valvulas apuntan a un sector inexistente: %s" % sid)

    # -- sectores --
    f_sectores = []
    for s in sorted(sectores, key=lambda x: (x["equipo"], x["sector"])):
        res = resumen_cuarteles(s["_rel"], por_id)
        ha = round(area_ha(s["geom"], lat0), 2)
        f_sectores.append(feature(s["geom"], {
            "id": s["id"], "name": s["name"],
            "equipo": s["equipo"], "equipo_id": s["equipo_id"], "sector": s["sector"],
            "ha": ha, "ha_kmz": s["ha_kmz"], "caudal_m3h": s["caudal_m3h"],
            "caudal_m3h_ha": round(s["caudal_m3h"] / ha, 1) if s["caudal_m3h"] and ha else None,
            "n_valvulas": valv_por_sector.get(s["id"], 0),
            "cuarteles": s["_rel"],
            "especies": res["especies"], "variedades": res["variedades"],
            "etiqueta": ("%s - %s" % (s["name"], res["etiqueta"])) if res["etiqueta"] else s["name"],
            "centro": [round(v, 6) for v in s["geom"].representative_point().coords[0]],
        }))

    # -- equipos: union real de sus sectores, no un bounding box --
    f_equipos = []
    for eq in sorted({s["equipo"] for s in sectores}):
        miembros = [s for s in sectores if s["equipo"] == eq]
        # el buffer +/- cierra las costuras submilimetricas entre sectores vecinos
        g = unary_union([m["geom"] for m in miembros]).buffer(1e-7).buffer(-1e-7)
        vistos, rel = set(), []
        for m in sorted(miembros, key=lambda x: x["sector"]):
            for r in m["_rel"]:
                if r["id"] not in vistos:
                    vistos.add(r["id"])
                    rel.append(dict(r))
        res = resumen_cuarteles(rel, por_id)
        ha = round(area_ha(g, lat0), 2)
        caudales = [m["caudal_m3h"] for m in miembros if m["caudal_m3h"]]
        f_equipos.append(feature(g, {
            "id": "E%d" % eq, "name": "Equipo %d" % eq, "equipo": eq,
            "ha": ha,
            "n_sectores": len(miembros),
            "sectores": [m["id"] for m in sorted(miembros, key=lambda x: x["sector"])],
            "caudal_m3h": round(sum(caudales), 1) if caudales else None,
            "n_valvulas": sum(valv_por_sector.get(m["id"], 0) for m in miembros),
            "cuarteles": rel,
            "especies": res["especies"], "variedades": res["variedades"],
            "etiqueta": ("Equipo %d - %s" % (eq, res["etiqueta"])) if res["etiqueta"]
                        else "Equipo %d" % eq,
            "centro": [round(v, 6) for v in g.representative_point().coords[0]],
        }))

    # -- cuarteles --
    f_cuarteles = []
    for c in sorted(cuarteles, key=lambda x: (ORDEN_ESPECIE.get(x["especie"], 9), x["numero"])):
        ha = round(area_ha(c["geom"], lat0), 2)
        f_cuarteles.append(feature(c["geom"], {
            "id": c["id"], "name": c["name"],
            "especie": c["especie"], "especie_corta": c["especie_corta"], "numero": c["numero"],
            "variedad": c["variedad"], "variedades": c["variedades"],
            "ha": ha, "ha_kmz": c["ha_kmz"],
            "sectores": c["_rel"],
            "equipos": sorted({r["id"].split("-")[0] for r in c["_rel"]}),
            "etiqueta": "%s - %s" % (c["name"], c["variedad"]),
            "centro": [round(v, 6) for v in c["geom"].representative_point().coords[0]],
        }))

    # -- ubicaciones E#-S#-C# --
    f_ubicaciones = []
    for u in ubicaciones:
        g = u.pop("geom")
        u = dict(u, ha=round(area_ha(g, lat0), 2))
        u["name"] = u["id"]
        u["etiqueta"] = "%s - %s C%d - %s" % (u["sector_id"], u["especie_corta"],
                                              u["cuartel"], u["variedad"])
        u["centro"] = [round(v, 6) for v in g.representative_point().coords[0]]
        f_ubicaciones.append(feature(g, u))

    f_valvulas = [punto(v) for v in sorted(valvulas,
                                           key=lambda x: (x["equipo"], x["sector"], x["zona"]))]
    f_pozos = [punto(p) for p in pozos]

    ha_sec = sum(f["properties"]["ha"] for f in f_sectores)
    ha_cua = sum(f["properties"]["ha"] for f in f_cuarteles)

    salida = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": kmz.name,
        "farm": {"name": "Ketcal", "operador": "Sembrador Capital"},
        "bbox": [round(minx, 6), round(miny, 6), round(maxx, 6), round(maxy, 6)],
        "center": [round((minx + maxx) / 2, 6), round((miny + maxy) / 2, 6)],
        "totales": {
            "equipos": len(f_equipos), "sectores": len(f_sectores),
            "cuarteles": len(f_cuarteles), "ubicaciones": len(f_ubicaciones),
            "valvulas": len(f_valvulas), "pozos": len(f_pozos),
            "ha_sectores": round(ha_sec, 2), "ha_cuarteles": round(ha_cua, 2),
            "caudal_m3h": round(sum(f["properties"]["caudal_m3h"] or 0 for f in f_sectores), 1),
            "por_especie": [
                {"especie": e,
                 "cuarteles": sum(1 for f in f_cuarteles if f["properties"]["especie"] == e),
                 "ha": round(sum(f["properties"]["ha"] for f in f_cuarteles
                                 if f["properties"]["especie"] == e), 2)}
                for e in ("Limoneros", "Naranjos", "Mandarinos")
            ],
        },
        "equipos": fc(f_equipos),
        "sectores": fc(f_sectores),
        "cuarteles": fc(f_cuarteles),
        "ubicaciones": fc(f_ubicaciones),
        "valvulas": fc(f_valvulas),
        "pozos": fc(f_pozos),
        "avisos": avisos,
    }

    out = Path(args.out)
    out.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")

    print("OK  %s  (%.0f KB)" % (out, out.stat().st_size / 1024))
    print("    equipos %d - sectores %d - cuarteles %d - ubicaciones %d - "
          "valvulas %d - pozos %d"
          % (len(f_equipos), len(f_sectores), len(f_cuarteles), len(f_ubicaciones),
             len(f_valvulas), len(f_pozos)))
    print("    ha sectores %.1f - ha cuarteles %.1f - caudal %.0f m3/h"
          % (ha_sec, ha_cua, salida["totales"]["caudal_m3h"]))
    if avisos:
        print("    AVISOS (%d):" % len(avisos))
        for a in avisos:
            print("      - %s" % a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
