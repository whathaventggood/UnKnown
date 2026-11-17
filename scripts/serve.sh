#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
[ -f frontend/dist/index.html ] || { echo '请先执行 cd frontend && npm ci && npm run build'; exit 1; }
[ -x backend/.venv/bin/python ] || { echo '请先执行 uv sync --project backend --frozen --python python3.11'; exit 1; }
export PYTHONPATH="$PROJECT_DIR/backend"
# Single worker: in-flight AI deduplication and quotas live in the process.
exec backend/.venv/bin/python -m uvicorn app.main:app --host "${UNKNOWN_HOST:-127.0.0.1}" --port "${UNKNOWN_PORT:-8000}" --workers 1
