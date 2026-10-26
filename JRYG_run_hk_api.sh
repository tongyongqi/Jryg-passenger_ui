#!/bin/bash
set -e

BASE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$BASE_DIR"

if [ -x "$BASE_DIR/JRYG_Passenger_API_HK/.venv/bin/python3" ]; then
    PYTHON="$BASE_DIR/JRYG_Passenger_API_HK/.venv/bin/python3"
else
    PYTHON="python3"
fi

exec "$PYTHON" "$BASE_DIR/JRYG_Passenger_API_HK/JRYG_run_main.py" "$@"
