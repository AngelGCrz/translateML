#!/bin/sh
# Ejecuta translateML con el entorno de .venv (créalo antes con ./setup.sh).
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "Falta el entorno .venv. Ejecuta primero: $ROOT/setup.sh" >&2
    exit 2
fi
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 exec "$ROOT/.venv/bin/python" -B -m translateml "$@"
