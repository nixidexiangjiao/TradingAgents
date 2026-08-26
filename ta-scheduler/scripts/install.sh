#!/usr/bin/env bash
# TradingAgents Scheduler — 一键部署
# 用法：bash scripts/install.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
echo "[install] cwd: $HERE"

# 1) 准备（无新 venv，复用 TradingAgents 主 venv）
if [ ! -x /home/lzero/workspace/TradingAgents/.venv/bin/python ]; then
    echo "[FATAL] TradingAgents venv not found. 先创建 TradingAgents 主 venv."
    exit 1
fi
echo "[install] 复用 TradingAgents 主 venv（scheduler.py 无新依赖，全是 stdlib）"

# 2) systemd user unit
mkdir -p ~/.config/systemd/user
cp "$HERE/systemd/ta-scheduler.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable ta-scheduler
systemctl --user restart ta-scheduler
sleep 2
echo "[install] systemd status:"
systemctl --user --no-pager status ta-scheduler || true

# 3) 校验
echo
echo "[install] 健康检查（读 state DB）:"
/home/lzero/workspace/TradingAgents/.venv/bin/python -c "
import sqlite3
conn = sqlite3.connect('$HERE/state.db')
cur = conn.execute('SELECT COUNT(*) FROM job_state')
print(f'  state.db jobs: {cur.fetchone()[0]}')
"

echo
echo "[install] ✅ 完成"
echo "[install] 查看实时日志: tail -f $HERE/logs/scheduler.log"
echo "[install] 停止:   systemctl --user stop ta-scheduler"
echo "[install] 启动:   systemctl --user start ta-scheduler"