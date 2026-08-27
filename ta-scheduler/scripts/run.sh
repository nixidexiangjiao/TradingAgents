#!/usr/bin/env bash
# TradingAgents Scheduler — 手动启动（systemd user 不可用时的替代）
# 跟 H5 server 用同样的方式：nohup + setsid
# 用法：bash scripts/run.sh

set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

# 检查依赖
if [ ! -x /home/lzero/workspace/TradingAgents/.venv/bin/python ]; then
    echo "[FATAL] TradingAgents venv 不存在"
    exit 1
fi

# 防重复启动：如果已有 scheduler 在跑，直接报错退出
# 注意：pgrep -f 会匹配到自己的 run.sh 进程，要排除 bash
EXISTING=$(pgrep -f "ta-scheduler/scheduler.py" | grep -v "$$" | grep -v "bash" | head -1)
if [ -n "$EXISTING" ]; then
    echo "[FATAL] scheduler 已在运行 (pid=$EXISTING)，不重复启动"
    echo "  停止现有: kill $EXISTING"
    exit 1
fi

# 后台启动（用 setsid 脱离父进程，nohup 不需要）
setsid /home/lzero/workspace/TradingAgents/.venv/bin/python scheduler.py \
    > logs/scheduler.out 2>&1 < /dev/null &
PID=$!
sleep 2

echo "[run] scheduler pid: $PID"
echo "[run] logs: $HERE/logs/scheduler.log"
echo "[run] stdout: $HERE/logs/scheduler.out"
echo
echo "--- 健康检查 ---"
ps -p $PID > /dev/null && echo "✅ 运行中" || echo "❌ 已退出（看日志排查）"
echo
echo "--- 启动日志 ---"
tail -10 logs/scheduler.log 2>/dev/null || tail -10 logs/scheduler.out
echo
echo "--- 可访问的 IP ---"
echo "Tailscale: $(tailscale ip -4 2>/dev/null | head -1)"
echo "LAN:      $(hostname -I | awk '{print $1}')"
echo
echo "--- 停止 ---"
echo "  pkill -f 'ta-scheduler/scheduler.py'"
echo
echo "--- 状态 ---"
echo "  tail -f $HERE/logs/scheduler.log"
echo "  cat $HERE/state.db | sqlite3 'SELECT * FROM job_state'"