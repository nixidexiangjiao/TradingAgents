#!/usr/bin/env bash
# TradingAgents H5 — 手动启动（systemd 之外的 quick start）
# 用法：bash scripts/run.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

if [ ! -d .venv-demo ]; then
    python3 -m venv .venv-demo
fi
.venv-demo/bin/pip install -q -r requirements.txt

# 启动（后台）
nohup .venv-demo/bin/python server.py > data/server.out 2>&1 < /dev/null &
echo "started pid $!"

sleep 2

echo "--- 健康检查 ---"
curl -s http://127.0.0.1:8765/api/health | python3 -m json.tool || echo "FAILED"

echo
echo "--- 可访问的 IP ---"
echo "Tailscale: $(tailscale ip -4 2>/dev/null | head -1)"
echo "LAN:      $(hostname -I | awk '{print $1}')"
echo
echo "--- 启动方式 ---"
echo "  • 浏览器（本机）: http://127.0.0.1:8765/"
echo "  • 浏览器（同 WiFi 手机）: http://$(hostname -I | awk '{print $1}'):8765/"
echo "  • 浏览器（Tailscale 手机）: http://$(tailscale ip -4 2>/dev/null | head -1):8765/"
echo
echo "--- 停止 ---"
echo "  pkill -f 'ta-h5-system/server.py'"
