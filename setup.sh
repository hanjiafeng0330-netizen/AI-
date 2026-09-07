#!/bin/bash
# AI 图书自动化 - 环境准备脚本

set -e

echo "===== 安装 Python 依赖 ====="
pip install -r requirements.txt

echo "===== 安装完成 ====="
echo "启动服务: python3 -m uvicorn main:app --host 0.0.0.0 --port 8902"
