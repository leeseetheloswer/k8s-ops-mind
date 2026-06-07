#!/bin/bash
# 启动 Web 模式：FastAPI 后端 + React 前端开发服务器
cd "$(dirname "$0")"

# 确保 Python 虚拟环境存在
if [ ! -d ".venv" ]; then
    echo "初始化 Python 虚拟环境..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

# 确保前端依赖存在
if [ ! -d "frontend/node_modules" ]; then
    echo "安装前端依赖..."
    cd frontend && npm install && cd ..
fi

echo "启动后端 http://localhost:8000"
.venv/bin/uvicorn server:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "启动前端 http://localhost:5173"
cd frontend && npm run dev &
FRONTEND_PID=$!

echo ""
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:5173"
echo ""
echo "按 Ctrl+C 停止所有服务"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
