#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
if [ -f "$DIR/.env" ]; then
    set -a
    source "$DIR/.env"
    set +a
fi
PYTHON="${XRAY_WEB_PYTHON:-$DIR/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
exec "$PYTHON" "$DIR/scripts/service_control.py" stop
