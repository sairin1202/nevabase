#!/usr/bin/env bash
# Run one nevabase service locally:  ./run.sh hub   |   ./run.sh coal   |   ./run.sh coffee
# Ports come from sites.json. Creates the virtualenv on first run.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
key="${1:-hub}"
port="$(.venv/bin/python -c "import json,sys; print(next(s['port'] for s in json.load(open('sites.json')) if s['key']==sys.argv[1]))" "$key")"
export PYTHONPATH=core:.
if [ "$key" = hub ]; then
  exec .venv/bin/uvicorn hub.app:app --host "${HOST:-127.0.0.1}" --port "${NEVA_PORT:-$port}"
fi
exec env NEVA_MARKET="$key" .venv/bin/uvicorn markets.serve:app --host "${HOST:-127.0.0.1}" --port "${NEVA_PORT:-$port}"
