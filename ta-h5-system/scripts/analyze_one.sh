#!/bin/bash
# TradingAgents — 单 ticker 分析 wrapper
# 用法：bash scripts/analyze_one.sh <TICKER>
#
# 设计：跟 tradingagents_nightly.sh 同样模式，但只跑一个 ticker，
# 适合每个 ticker 一个 cron job（粒度更细，方便 H5 跟踪每只的状态）。
#
# 调用方：hermes cron --no-agent（exit code 直接送到 deliver 渠道）

set -uo pipefail

TICKER="${1:-}"
if [ -z "$TICKER" ]; then
    echo "[FATAL] 用法: $0 <TICKER>"
    exit 2
fi

PROJ="/home/lzero/workspace/TradingAgents"
VENV_PY="$PROJ/.venv/bin/python"

# 跟 nightly 一样的环境净化 + proxy + .env
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH LD_PRELOAD VIRTUAL_ENV
source /home/lzero/proxy.sh
set -a
source "$PROJ/.env"
set +a

if [ ! -x "$VENV_PY" ]; then
    echo "[FATAL] venv python not found: $VENV_PY"
    exit 3
fi

# 0700.HK 这种以 0 开头的 ticker 必须用引号
"$VENV_PY" "$PROJ/run_batch.py" --tickers "$TICKER" --date "$(date '+%Y-%m-%d')"
RC=$?

echo "[done] $TICKER @ $(date '+%F %T %Z') exit=$RC"
# 飞书/Telegram 看板上点链接直达 H5
H5_BASE="${TA_H5_PUBLIC_BASE:-http://127.0.0.1:8765}"
echo
echo "🔗 在 H5 看板看完整报告："
echo "   $H5_BASE/#/report/$(date '+%Y-%m-%d')__${TICKER}"
exit $RC
