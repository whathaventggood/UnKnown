#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
command -v uv >/dev/null || { echo '缺少 uv。安装说明：https://docs.astral.sh/uv/getting-started/installation/'; exit 1; }
command -v node >/dev/null || { echo '缺少 Node.js 22.12+，请先安装。'; exit 1; }
command -v npm >/dev/null || { echo '缺少 npm。'; exit 1; }
node -e 'const [major,minor]=process.versions.node.split(".").map(Number);if(major<22||(major===22&&minor<12)){console.error("需要 Node.js 22.12+");process.exit(1)}'
# Explicit bounded dependency setup; does not download models or collect external content.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_DIR/.cache/uv}"
uv sync --project backend --frozen --python "${UNKNOWN_PYTHON:-python3.11}"
(cd frontend && npm ci --no-audit --no-fund)
if [ ! -f .env ]; then echo '没有 .env：使用安全本地默认值，AI 关闭。可从 .env.example 复制后按需配置。'; fi
if [ -n "${UNKNOWN_DATABASE_URL:-}" ]; then export DATABASE_URL="$UNKNOWN_DATABASE_URL"; fi
API_PORT="${UNKNOWN_API_PORT:-8000}"
WEB_PORT="${UNKNOWN_WEB_PORT:-5173}"
# Vite forwards /api; custom API port is read by vite.config.ts.
export UNKNOWN_API_PORT="$API_PORT"
PYTHONPATH=backend backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!
(cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port "$WEB_PORT" --strictPort) &
WEB_PID=$!
cleanup(){ kill "$API_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
backend/.venv/bin/python - "$API_PORT" "$WEB_PORT" <<'PYREADY'
import sys,time,urllib.request
ports=sys.argv[1:]
for attempt in range(50):
    try:
        for port,path in [(ports[0],'/api/health'),(ports[1],'/')]:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:'+port+path,timeout=.5) as response:
                if response.status!=200: raise RuntimeError('service not ready')
        break
    except Exception:
        if attempt==49:
            print('启动未就绪，请检查上方错误和端口占用。',file=sys.stderr)
            raise SystemExit(1)
        time.sleep(.2)
PYREADY
kill -0 "$API_PID" 2>/dev/null || { echo '后端启动失败，请检查上方错误或端口占用。'; exit 1; }
kill -0 "$WEB_PID" 2>/dev/null || { echo '前端启动失败，请检查上方错误或端口占用。'; exit 1; }
echo "UnKnown: http://127.0.0.1:$WEB_PORT  API: http://127.0.0.1:$API_PORT/docs"
wait "$API_PID" "$WEB_PID"
