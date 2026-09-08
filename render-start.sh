#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR${PYTHONPATH:+:$PYTHONPATH}"

cleanup() {
  [[ -n "${APP_PID:-}" ]] && kill "$APP_PID" 2>/dev/null || true
  [[ -n "${SEARCH_PID:-}" ]] && kill "$SEARCH_PID" 2>/dev/null || true
  [[ -n "${RAILWAY_PID:-}" ]] && kill "$RAILWAY_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python -m alembic upgrade head

python -m uvicorn backend.mcp_servers.search_server.server:app \
  --host 127.0.0.1 --port 8100 &
SEARCH_PID=$!

DEBUG=false SERVER_HOST=127.0.0.1 SERVER_PORT=8200 mcp-12306 &
RAILWAY_PID=$!

python -m uvicorn backend.app.main:app \
  --host 0.0.0.0 --port "${PORT:-10000}" &
APP_PID=$!

wait "$APP_PID"
