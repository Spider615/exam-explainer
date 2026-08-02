#!/usr/bin/env bash
# 起 exam-explainer：后端 FastAPI + 已构建的 React 前端，同一个端口。
set -e
cd "$(dirname "$0")"
[ -d web/dist ] || (cd web && npm install && npm run build)
exec .venv/bin/uvicorn pipeline.api:app --host 127.0.0.1 --port "${PORT:-8712}"
