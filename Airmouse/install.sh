#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("AirMouse requires Python 3.10 or newer (Python 3.12 recommended).")
print(f"Using Python {sys.version.split()[0]}")
PY
"$PYTHON" -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
printf '\nDependencies installed in %s/.venv\n' "$ROOT"
printf 'On Ubuntu, venv creation may require: sudo apt install python3-venv python3-dev\n'
