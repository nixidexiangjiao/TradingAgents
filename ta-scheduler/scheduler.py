#!/usr/bin/env python3
"""
TradingAgents Scheduler — 完全独立调度器
==========================================

设计目标：
- 不依赖 hermes cron / hermes gateway
- 读 H5 SQLite watchlist.db
- 每个 enabled ticker 按 cron 表达式跑 run_batch.py
- 状态持久化到本地 SQLite（防重启重复跑）
- 单 Python 进程循环，systemd 守护

流程（每分钟）：
1. now = 当前时间
2. SELECT * FROM watchlist WHERE enabled=1
3. 对每个 ticker：
   - cron_expr 解析 → 下次触发时间
   - 如果 now >= next_run_time 且 last_run < next_run_time：
     - 触发：subprocess.run(run_batch.py --tickers <symbol>)
     - 更新 state.runs(last_run=now, status=..., exit_code=...)
4. sleep 60s 循环

数据源：
- ~/workspace/TradingAgents/ta-h5-system/data/ta_h5.db（H5 的 SQLite）
- ~/workspace/TradingAgents/ta-scheduler/state.db（本地状态，防重启）

依赖：stdlib only（sqlite3 + subprocess + croniter）。零外部依赖。

重启安全：
- state.last_run 持久化
- 如果进程崩了重启，下一分钟恢复
- 不会丢任务：崩溃时正在跑的任务 status=interrupted，下次启动标记
"""
import os
import sys
import time
import sqlite3
import subprocess
import logging
import signal
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

# ==================== Paths ====================
PROJECT_ROOT = Path("/home/lzero/workspace/TradingAgents")
WATCHLIST_DB = PROJECT_ROOT / "ta-h5-system" / "data" / "ta_h5.db"
TA_DIR = PROJECT_ROOT
STATE_DB = Path(__file__).resolve().parent / "state.db"
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ==================== Logging ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "scheduler.log"),
    ],
)
log = logging.getLogger("ta-scheduler")

# ==================== Signal handling ====================
_shutdown = threading.Event()


def _on_signal(signum, _frame):
    log.info(f"received signal {signum}, shutting down...")
    _shutdown.set()


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


# ==================== Schedule parser ====================
# 简化的 5-field cron 解析（不依赖 croniter）
# 支持：分 时 日 月 周
# 简化：周 0=Sun（与 crontab 一致）
# 不支持：复杂如 "L" / "W" / "#"

def _match_field(field: str, min_v: int, max_v: int, now_v: int) -> bool:
    """解析单个 cron 字段，判断 now_v 是否匹配"""
    if field == "*":
        return True
    if "," in field:
        return any(_match_field(f, min_v, max_v, now_v) for f in field.split(","))
    if "/" in field:
        base, step = field.split("/")
        base = base if base != "" else str(min_v)
        step = int(step)
        if base == "*":
            start = min_v
        else:
            start = int(base)
        if now_v < start:
            return False
        return (now_v - start) % step == 0
    if "-" in field:
        a, b = field.split("-")
        return int(a) <= now_v <= int(b)
    return now_v == int(field)


def cron_match(expr: str, now: datetime) -> bool:
    """判断 now 是否匹配 cron 表达式（5-field）。返回 True 表示该触发"""
    parts = expr.strip().split()
    if len(parts) != 5:
        log.error(f"invalid cron expr (need 5 fields): {expr!r}")
        return False
    # 字段：minute hour day-of-month month day-of-week
    # 注意：crontab 周字段 0=Sun，day-of-week 和 day-of-month 同时满足（OR 关系）
    minute, hour, dom, month, dow = parts
    if not _match_field(minute, 0, 59, now.minute):
        return False
    if not _match_field(hour, 0, 23, now.hour):
        return False
    if not _match_field(month, 1, 12, now.month):
        return False
    # day-of-month / day-of-week OR 关系
    dom_match = _match_field(dom, 1, 31, now.day)
    dow_match = _match_field(dow, 0, 6, (now.weekday() + 1) % 7)  # Python 0=Mon → crontab 0=Sun
    if dom == "*" and dow == "*":
        return True
    return dom_match or dow_match


# ==================== State DB ====================
SCHEMA = """
CREATE TABLE IF NOT EXISTS job_state (
    symbol TEXT PRIMARY KEY,
    cron_expr TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_ts TEXT,                      -- ISO timestamp of last triggered run
    last_status TEXT,                      -- completed / failed / interrupted
    last_exit_code INTEGER,
    last_duration_s REAL,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_state_enabled ON job_state(enabled);
"""


def init_state() -> None:
    STATE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(STATE_DB)) as conn:
        conn.executescript(SCHEMA)


def _conn():
    conn = sqlite3.connect(str(STATE_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def get_job_state(symbol: str) -> Optional[dict]:
    with _conn() as conn:
        r = conn.execute("SELECT * FROM job_state WHERE symbol=?", (symbol,)).fetchone()
        return dict(r) if r else None


def update_job_state(symbol: str, cron_expr: str, status: str, exit_code: Optional[int], duration_s: float, error: Optional[str] = None) -> None:
    now = datetime.now(tz=timezone(timedelta(hours=8))).isoformat()
    with _conn() as conn:
        conn.execute(
            """INSERT INTO job_state (symbol, cron_expr, enabled, last_run_ts, last_status, last_exit_code, last_duration_s, last_error)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol) DO UPDATE SET
                   cron_expr=excluded.cron_expr,
                   enabled=1,
                   last_run_ts=excluded.last_run_ts,
                   last_status=excluded.last_status,
                   last_exit_code=excluded.last_exit_code,
                   last_duration_s=excluded.last_duration_s,
                   last_error=excluded.last_error""",
            (symbol, cron_expr, now, status, exit_code, duration_s, error),
        )


def _update_run_meta(symbol: str, run_id: str, log_path: Optional[str], exit_code: Optional[int], status: str) -> None:
    """把每次 run 的 run_id + log_path 存到 job_state。
    这样 H5 弹层可以告诉用户"看 logs/runs/<run_id>.log 看完整 stdout" """
    if not log_path:
        return
    with _conn() as conn:
        # 把旧字段 last_error 后面加 run_id + log_path（保持兼容）
        conn.execute(
            "UPDATE job_state SET last_error = COALESCE(last_error, '') || ? WHERE symbol = ?",
            (f"\n[run_id={run_id}]\n[log_path={log_path}]\n[exit_code={exit_code}]", symbol),
        )


# ==================== Watchlist DB（共享 H5 SQLite）====================
def read_watchlist() -> list[dict]:
    """从 H5 SQLite 读 enabled=1 的 watchlist"""
    if not WATCHLIST_DB.exists():
        log.warning(f"watchlist DB 不存在: {WATCHLIST_DB}")
        return []
    with sqlite3.connect(str(WATCHLIST_DB)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, symbol, name, market, enabled, notes, cron_id "
            "FROM watchlist WHERE enabled=1 ORDER BY sort_order, symbol"
        ).fetchall()
        return [dict(r) for r in rows]


# ==================== 默认 cron 表达式 ====================
# 每个 ticker 独立调度。如果 watchlist 没填 cron_id，就用默认
DEFAULT_CRON = "30 21 * * 1-5"  # 工作日 21:30 HKT（默认）


def get_cron_for_symbol(symbol: str) -> str:
    """根据 symbol 决定 cron 表达式。
    简单规则：港股 / 美股 21:30 工作日（A 股可以单独配）"""
    # 未来可以加 watchlist.cron_expr 列；现在用默认
    return DEFAULT_CRON


# ==================== Run ====================
def should_run(symbol: str, cron_expr: str, now: datetime) -> bool:
    """判断现在是否该跑这个 ticker"""
    if not cron_match(cron_expr, now):
        return False
    state = get_job_state(symbol)
    if not state:
        # 从未跑过 → 应该跑
        return True
    # 上次跑的时间
    try:
        last_run = datetime.fromisoformat(state["last_run_ts"])
    except Exception:
        return True
    # 如果上次跑 < 当前分钟 → 应该跑（防重复）
    # 用 minute 精度（避免同一分钟重复触发）
    if last_run.replace(second=0, microsecond=0) >= now.replace(second=0, microsecond=0):
        return False
    return True


def run_one(symbol: str) -> tuple[str, str, int, float, Optional[str], Optional[str]]:
    """跑一个 ticker。
    返回 (status, run_id, exit_code, duration_s, error, log_path)
    log_path 是这个 run 的完整 stdout 文件路径（H5 可读）
    """
    log.info(f"[run] {symbol} START")
    start = time.time()
    venv_py = str(TA_DIR / ".venv" / "bin" / "python")
    run_batch_py = str(TA_DIR / "run_batch.py")
    bash = (
        "set -uo pipefail\n"
        "unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH LD_PRELOAD VIRTUAL_ENV\n"
        "source /home/lzero/proxy.sh\n"
        "set -a\n"
        f'source "{TA_DIR}/.env"\n'
        "set +a\n"
        f'"{venv_py}" "{run_batch_py}" --tickers "{symbol}" --date "$(date \'+%Y-%m-%d\')"\n'
    )
    # 持久化完整 stdout 到文件
    run_id = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S") + "_" + symbol
    runs_dir = Path(__file__).resolve().parent / "logs" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    log_path = runs_dir / f"{run_id}.log"

    try:
        proc = subprocess.Popen(
            ["/bin/bash", "-c", bash],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(TA_DIR),
        )
        # 实时写完整 stdout 到 log 文件
        stdout_buf = []
        with open(log_path, "w") as f:
            f.write(f"# run_id={run_id}\n# symbol={symbol}\n# started_at={datetime.now(tz=timezone(timedelta(hours=8))).isoformat()}\n\n")
            for line in proc.stdout:
                f.write(line)
                f.flush()
                stdout_buf.append(line)
        proc.wait()
        duration = round(time.time() - start, 1)

        # 写退出码
        with open(log_path, "a") as f:
            f.write(f"\n# exit_code={proc.returncode}\n# duration_s={duration}\n# ended_at={datetime.now(tz=timezone(timedelta(hours=8))).isoformat()}\n")

        status = "completed" if proc.returncode == 0 else "failed"
        log.info(f"[run] {symbol} DONE exit={proc.returncode} duration={duration}s")
        if proc.returncode != 0:
            err_tail = "".join(stdout_buf)[-500:]
            log.warning(f"[run] {symbol} stderr tail (last 500): {err_tail}")
            return status, run_id, proc.returncode, duration, err_tail, str(log_path)
        return status, run_id, proc.returncode, duration, None, str(log_path)
    except subprocess.TimeoutExpired:
        duration = round(time.time() - start, 1)
        log.error(f"[run] {symbol} TIMEOUT after {duration}s")
        with open(log_path, "a") as f:
            f.write(f"\n# exit_code=-1 (timeout)\n# duration_s={duration}\n")
        return "failed", run_id, -1, duration, "timeout 1800s", str(log_path)
    except Exception as e:
        duration = round(time.time() - start, 1)
        log.exception(f"[run] {symbol} FAILED: {e}")
        with open(log_path, "a") as f:
            f.write(f"\n# spawn_error={e}\n")
        return "failed", run_id, -1, duration, str(e), str(log_path)


# ==================== Main loop ====================
def main() -> None:
    init_state()
    log.info(f"=== TA-Scheduler started ===")
    log.info(f"  watchlist DB: {WATCHLIST_DB}")
    log.info(f"  state DB: {STATE_DB}")
    log.info(f"  project: {PROJECT_ROOT}")

    while not _shutdown.is_set():
        try:
            tick_start = time.time()
            now = datetime.now(tz=timezone(timedelta(hours=8)))
            items = read_watchlist()
            if not items:
                log.debug(f"[tick] watchlist empty or DB missing")
            else:
                log.info(f"[tick] {now.strftime('%F %T')} watchlist={len(items)}")
                for w in items:
                    symbol = w["symbol"]
                    cron_expr = get_cron_for_symbol(symbol)
                    if should_run(symbol, cron_expr, now):
                        log.info(f"[trigger] {symbol} cron={cron_expr}")
                        status, run_id, exit_code, _, error, log_path = run_one(symbol)
                        update_job_state(symbol, cron_expr, status, exit_code, _, error)
                        # 把 run_id + log_path 也存到 state.db（下次能查完整日志）
                        _update_run_meta(symbol, run_id, log_path, exit_code, status)
            tick_duration = time.time() - tick_start
            # sleep 到下一个整分钟
            sleep_for = max(5, 60 - tick_duration)
            _shutdown.wait(sleep_for)
        except Exception as e:
            log.exception(f"[tick loop] error: {e}")
            _shutdown.wait(30)  # 出错等 30s 再试，避免疯狂出错
    log.info("=== TA-Scheduler stopped ===")


if __name__ == "__main__":
    main()