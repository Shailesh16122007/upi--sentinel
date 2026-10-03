#!/usr/bin/env bash
# Starts the API (port 8000) and the web app (port 5173). Ctrl+C stops both.
set -e
cd "$(dirname "$0")"
( cd backend && [ -d .venv ] && source .venv/bin/activate; uvicorn app.main:app --port 8000 ) &
API=$!
( cd frontend && npm run dev -- --host 127.0.0.1 ) &
WEB=$!
trap 'kill $API $WEB 2>/dev/null' EXIT INT TERM
echo "UPI Sentinel: http://127.0.0.1:5173  (API docs: http://127.0.0.1:8000/docs)"
wait
