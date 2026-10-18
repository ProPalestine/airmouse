#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  printf 'Virtual environment not found. Run ./install.sh first.\n' >&2
  exit 1
fi
printf 'AirMouse starting at http://127.0.0.1:5000\n'
printf 'Desktop session: %s. On GNOME/Wayland, start the ydotoold user service before launching.\n' "${XDG_SESSION_TYPE:-unknown}"
exec "$ROOT/.venv/bin/python" "$ROOT/app.py"
