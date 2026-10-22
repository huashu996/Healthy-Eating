#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/apps/api"
export PYTHONDONTWRITEBYTECODE=1
export PDP_AGENT_ENABLED=false
export PDP_PUBLIC_SOURCES_ENABLED=false
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PDP_PORT:-8765}"
