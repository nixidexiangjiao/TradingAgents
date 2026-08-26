#!/bin/bash
# TradingAgents — 单 ticker 分析 wrapper
# 用法：bash scripts/analyze_one.sh <TICKER> [--date YYYY-MM-DD]
#
# 设计：跟 tradingagents_nightly.sh 同样模式，但只跑一个 ticker，
# 适合每个 ticker 一个 cron job（粒度更细，方便 H5 跟踪每只的状态）。
#
# 日期推断：
# - 没传 --date  → 当前 HKT 日期
# - 当前是周末  → 上一个工作日（保证能跑出报告）
# - 手动传 --date → 用指定日期（建议传工作日；run_batch.py 周末会 skip）
#
# 调用方：hermes cron --no-agent（exit code 直接送到 deliver 渠道）

set -uo pipefail

TICKER="${1:-}"
DATE="${2:-$(date '+%Y-%m-%d')}"

if [ -z "$TICKER" ]; then
    echo "[FATAL] 用法: $0 <TICKER> [--date YYYY-MM-DD]"
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

# 周末自动 fallback 到上一个工作日（不传 --date 时）
if [ "$DATE" = "$(date '+%Y-%m-%d')" ]; then
    # 用 date 命令算 weekday：1=Mon..7=Sun
    DOW=$(date '+%u')
    if [ "$DOW" -ge 6 ]; then
        # Sat=6 → 上周五；Sun=7 → 上周五
        if command -v gdate >/dev/null 2>&1; then
            FALLBACK=$(gdate -d 'last friday' '+%Y-%m-%d')
        else
            # GNU date: "last friday" 不一定支持；用 -d "-1 day" 两次
            FALLBACK=$(date -d 'last friday' '+%Y-%m-%d' 2>/dev/null || date '+%Y-%m-%d')
        fi
        if [ -n "$FALLBACK" ] && [ "$FALLBACK" != "$(date '+%Y-%m-%d')" ]; then
            echo "[info] 当前是周末，自动 fallback 到最近工作日 $FALLBACK"
            DATE="$FALLBACK"
        fi
    fi
fi

# 0700.HK 这种以 0 开头的 ticker 必须用引号
"$VENV_PY" "$PROJ/run_batch.py" --tickers "$TICKER" --date "$DATE"
RC=$?

echo "[done] $TICKER @ $DATE $(date '+%T %Z') exit=$RC"
# 飞书/Telegram 看板上点链接直达 H5
H5_BASE="${TA_H5_PUBLIC_BASE:-http://127.0.0.1:8765}"
echo
echo "🔗 在 H5 看板看完整报告："
echo "   $H5_BASE/#/report/${DATE}__${TICKER}"
exit $RC
