#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Recorta el margen vacio de los logos de `assets/exportadoras/`.

La caja del mapa mide 58x22 px y ajusta el logo con `object-fit: contain`, asi
que cualquier margen que traiga el archivo se descuenta del tamano util. Los
logos que llegan de la web vienen con lienzos generosos: El Parque ocupaba el
50 % de su PNG y Gesex el 62 %, y en la leyenda se veian la mitad de grandes de
lo que podian.

Que hace:

* Calcula la caja del contenido ignorando los pixeles transparentes Y los
  casi-blancos. Lo segundo importa porque no todos los archivos traen canal
  alfa —el de Gesex es opaco con fondo blanco— y sin eso el recorte no
  encontraria nada que sacar.
* Recorta a esa caja. No reescala ni recomprime el contenido: la marca queda
  igual, sólo desaparece el aire alrededor.
* Es idempotente: un archivo ya recortado ocupa el 100 % de su lienzo y se
  deja como esta. Se puede volver a correr sin acumular recortes.

El aire alrededor lo pone el CSS (`padding` de la caja), que es donde
corresponde: asi es el mismo para todos los logos, venga como venga el archivo.

Uso:  python tools/trim_logos.py [--dir assets/exportadoras] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: falta Pillow.  pip install pillow")

# Un pixel cuenta como fondo si es casi transparente o casi blanco. Los dos
# umbrales son deliberadamente laxos: los PNG de la web traen bordes con
# antialias y un corte estricto dejaba una orla de un pixel.
ALFA_MIN = 24
BLANCO_MIN = 244


def caja_contenido(im):
    """(x0, y0, x1, y1) del contenido visible, o None si esta todo vacio."""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < ALFA_MIN:
                continue
            if r > BLANCO_MIN and g > BLANCO_MIN and b > BLANCO_MIN:
                continue
            if x < x0:
                x0 = x
            if y < y0:
                y0 = y
            if x > x1:
                x1 = x
            if y > y1:
                y1 = y
    return None if x1 < 0 else (x0, y0, x1 + 1, y1 + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="assets/exportadoras")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    carpeta = Path(args.dir)
    if not carpeta.is_dir():
        sys.exit("ERROR: no existe %s" % carpeta)

    archivos = sorted(p for p in carpeta.iterdir()
                      if p.suffix.lower() in (".png", ".webp"))
    if not archivos:
        print("Sin logos en %s." % carpeta)
        return 0

    tocados = 0
    for f in archivos:
        im = Image.open(f)
        w, h = im.size
        caja = caja_contenido(im)
        if caja is None:
            print("  %-24s %3dx%-3d  sin contenido, se deja" % (f.stem, w, h))
            continue
        x0, y0, x1, y1 = caja
        cw, ch = x1 - x0, y1 - y0
        ocupa = cw * ch / (w * h) * 100
        if (cw, ch) == (w, h):
            print("  %-24s %3dx%-3d  ya recortado" % (f.stem, w, h))
            continue
        print("  %-24s %3dx%-3d -> %3dx%-3d  (ocupaba %.0f %%)%s"
              % (f.stem, w, h, cw, ch, ocupa, "  [dry-run]" if args.dry_run else ""))
        if not args.dry_run:
            # `optimize` sin cambiar el modo: no se recomprime con perdida ni se
            # tira el canal alfa de los que lo traen.
            im.crop(caja).save(f, optimize=True)
            tocados += 1

    print("%d de %d archivo(s) recortados." % (tocados, len(archivos)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
