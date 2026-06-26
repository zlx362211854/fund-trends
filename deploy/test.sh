#!/usr/bin/env bash
# 在服务器上手动跑一次日报(测试用)
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
python scripts/run_daily.py
