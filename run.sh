#!/bin/bash
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "初始化虚拟环境..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

.venv/bin/python main.py
