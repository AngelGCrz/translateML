#!/bin/sh
# Prepara translateML en macOS o Linux: crea .venv e instala el programa y openpyxl.
set -e
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else "Se necesita Python 3.9 o superior.")'
[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e .
.venv/bin/python -m translateml --version
echo "Listo. Usa ./translateml.sh (por ejemplo: ./translateml.sh generate RUTA/eng/info/info.json --xlsx Multidioma.xlsx)"
