#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guarda la credencial de Ceres en `.ceres_token` sin que pase por ningun lado
donde quede escrita.

Por que existe: rotar la clave es una operacion que se repite, y las formas
obvias de hacerla la dejan grabada en algun registro que despues nadie limpia.

    echo LA_CLAVE > .ceres_token        <- queda en el historial del shell
    python algo.py LA_CLAVE             <- queda en la lista de procesos
    pegarla en un chat o en un ticket   <- queda en el historial de la conversacion

Aca la clave se pide con `getpass`: no se imprime mientras se escribe, no viaja
por argv y no entra al historial, porque el comando que se tipea no la contiene.
Si la terminal no permite apagar el eco —pasa en algunas consolas de Windows—
el script ABORTA en vez de mostrarla; una clave visible en pantalla es
exactamente lo que se estaba evitando.

Lo unico que imprime es la FORMA de la clave y una huella sha256 truncada, que
sirve para confirmar que el archivo cambio sin revelar el contenido.

Normaliza tres errores de pegado tipicos, avisando de cada uno:

    "abc123"        -> comillas de sobra
    Token abc123    -> el prefijo del header, no va en el archivo
    ' abc123\\n '    -> espacios y saltos de linea alrededor

`.ceres_token` esta en .gitignore. Este repo es publico: la clave no va en
ningun archivo versionado, nunca.

Uso:
    python tools/set_ceres_token.py             # pide, guarda y valida
    python tools/set_ceres_token.py --no-check  # guarda sin llamar a la API
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import subprocess
import sys
import warnings

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(REPO_ROOT, ".ceres_token")
FETCH = os.path.join(REPO_ROOT, "tools", "fetch_ceres.py")


def huella(valor):
    """sha256 truncada: sirve para cotejar dos claves sin poder reconstruirlas."""
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()[:8]


def normalizar(crudo):
    """(clave_limpia, [avisos]). No inventa: solo saca lo que sobra al pegar."""
    avisos = []
    v = crudo.strip()
    if v != crudo:
        avisos.append("venia con espacios o saltos de linea alrededor")
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
        avisos.append("venia entre comillas")
    if v.lower().startswith("token "):
        v = v[6:].strip()
        avisos.append("venia con el prefijo 'Token ' del header HTTP")
    return v, avisos


def pedir():
    """Pide la clave sin eco. Aborta si la terminal no puede apagarlo."""
    with warnings.catch_warnings():
        # getpass avisa con GetPassWarning y cae a una lectura CON eco. Eso es
        # peor que fallar: la clave quedaria a la vista en la pantalla.
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass("Pega la clave de Ceres (no se vera al escribir): ")
        except getpass.GetPassWarning:
            sys.exit(
                "\nERROR: esta terminal no deja ocultar lo que se escribe, asi que\n"
                "la clave quedaria visible. Corre el script desde PowerShell o\n"
                "desde cmd, donde si se puede.\n")
        except (EOFError, KeyboardInterrupt):
            sys.exit("\nCancelado. El archivo no se toco.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-check", action="store_true",
                    help="guarda sin validar contra la API de Ceres")
    args = ap.parse_args()

    anterior = None
    if os.path.isfile(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8-sig") as fh:
            anterior = fh.read().strip()
        print("Archivo actual: %s, %d caracteres, huella %s"
              % (os.path.basename(TOKEN_FILE), len(anterior), huella(anterior)))
    else:
        print("No hay %s todavia; se va a crear." % os.path.basename(TOKEN_FILE))

    clave, avisos = normalizar(pedir())
    if not clave:
        sys.exit("ERROR: no se escribio nada. El archivo no se toco.\n")
    for a in avisos:
        print("  corregido: %s" % a)
    if any(c.isspace() for c in clave):
        sys.exit("ERROR: la clave tiene espacios en el medio; el pegado quedo "
                 "mal. El archivo no se toco.\n")
    if not all(ord(c) < 128 for c in clave):
        sys.exit("ERROR: la clave tiene caracteres no ASCII; el pegado quedo "
                 "mal. El archivo no se toco.\n")
    if anterior is not None and clave == anterior:
        print("\nLa clave es la MISMA que ya estaba (huella %s). Nada que hacer."
              % huella(clave))
        return 0

    # Sin salto de linea final: el lector hace strip igual, pero asi el archivo
    # contiene exactamente la clave y nada mas.
    with open(TOKEN_FILE, "w", encoding="utf-8", newline="") as fh:
        fh.write(clave)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass                      # en Windows no siempre aplica; no es fatal

    print("\nGuardada en %s" % os.path.basename(TOKEN_FILE))
    print("  largo:   %d caracteres" % len(clave))
    print("  huella:  %s%s" % (huella(clave),
                               "" if anterior is None
                               else "   (antes era %s)" % huella(anterior)))

    if args.no_check:
        print("\nSin validar (--no-check). Para probarla:")
        print("  python tools/fetch_ceres.py --check-token")
        return 0

    print("\nValidando contra Ceres...\n")
    return subprocess.call([sys.executable, FETCH, "--check-token"])


if __name__ == "__main__":
    raise SystemExit(main())
