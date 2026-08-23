#!/usr/bin/env bash
# TradingAgents H5 — 一键部署（systemd user unit + Tailscale serve）
# 用法：bash scripts/install.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
echo "[install] cwd: $HERE"

# 1) venv
if [ ! -x "$HERE/.venv-demo/bin/python" ]; then
    echo "[install] 创建 venv ..."
    python3 -m venv "$HERE/.venv-demo"
fi
echo "[install] 装依赖 ..."
"$HERE/.venv-demo/bin/pip" install -q -r "$HERE/requirements.txt"

# 1.5) 复制 wrapper script 到 ~/.hermes/scripts/（hermes cron 强制要求）
SCRIPT_SRC="$HERE/scripts/analyze_one.sh"
SCRIPT_DST="$HOME/.hermes/scripts/analyze_one.sh"
if [ -f "$SCRIPT_SRC" ] && [ ! -f "$SCRIPT_DST" ]; then
    echo "[install] 复制 analyze_one.sh -> ~/.hermes/scripts/ ..."
    cp "$SCRIPT_SRC" "$SCRIPT_DST"
    chmod +x "$SCRIPT_DST"
fi

# 2) systemd user unit
mkdir -p ~/.config/systemd/user
cp "$HERE/systemd/ta-h5.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable ta-h5
systemctl --user restart ta-h5
sleep 2
echo "[install] systemd status:"
systemctl --user --no-pager status ta-h5 || true

# 3) 校验
echo
echo "[install] 健康检查："
curl -s http://127.0.0.1:8765/api/health | python3 -m json.tool || echo "FAILED"

# 4) Tailscale
if command -v tailscale >/dev/null 2>&1; then
    echo
    read -p "[install] 是否配置 Tailscale Serve (https)？[y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        tailscale serve https / http://127.0.0.1:8765
        tailscale serve status
    fi
fi

echo
echo "[install] ✅ 完成"
echo "[install] 手机浏览器打开（如果有 Tailscale）："
echo "[install]   https://$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || echo '<node-name>.<tailnet>.ts.net')/"
