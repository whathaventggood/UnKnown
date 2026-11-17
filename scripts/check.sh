#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR/backend"
backend/.venv/bin/python -m pytest backend/tests -q
(cd frontend && npm run test:requests && npm run typecheck && npm run build)
backend/.venv/bin/python scripts/evaluate_semantics.py
backend/.venv/bin/python scripts/evaluate.py
backend/.venv/bin/python scripts/verify_offline.py
