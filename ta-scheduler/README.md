# TradingAgents Scheduler — runbook

独立调度器，完全不依赖 hermes cron。

## 设计目标

- **0 hermes 依赖**：不调 hermes CLI、不连 hermes 网关、不受 hermes gateway bug 影响
- **读 H5 SQLite watchlist**：`ta-h5-system/data/ta_h5.db` 里的 `enabled=1` ticker
- **每个 ticker 一个 cron 表达式**（写在代码里，默认 `30 21 * * 1-5` 工作日 21:30 HKT）
- **单进程循环**：每分钟 check 一次，触发时调 `run_batch.py --tickers <symbol>`
- **状态持久化**：本地 SQLite `state.db` 记录每个 ticker 的 last_run_ts / status
- **重启安全**：state 落盘，崩溃后不丢任务（不会重复跑同一分钟）

## 文件结构

```
ta-scheduler/
├── scheduler.py           # 主循环（每分钟 tick）
├── state.db               # 本地状态（每个 ticker 的 last_run）
├── logs/scheduler.log     # 运行日志
├── systemd/ta-scheduler.service   # systemd unit
├── scripts/install.sh   # 一键部署
└── README.md
```

## 部署（systemd 守护）

```bash
bash scripts/install.sh
# 自动：
# - 复用 TradingAgents 主 venv（scheduler.py 无新依赖）
# - 装 systemd user unit
# - 启动 + enable
```

## 手动跑（前台）

```bash
/home/lzero/workspace/TradingAgents/.venv/bin/python scheduler.py
# Ctrl+C 优雅退出（SIGTERM）
```

## 数据流

```
H5 SQLite watchlist.db
  ↓ SELECT * FROM watchlist WHERE enabled=1
scheduler tick (每分钟)
  ↓ 对每个 ticker:
     1. cron_expr 解析 → 当前分钟是否触发
     2. state.last_run_ts < 当前分钟  → 没跑过
     3. 满足则 subprocess.run(run_batch.py)
     4. 更新 state.last_run_ts/status
  ↓ sleep 60s
```

## 跟 hermes cron 的区别

| 维度 | hermes cron | ta-scheduler |
|------|-------------|--------------|
| 进程模型 | hermes gateway 单进程 | 独立 Python 进程 |
| 调度存储 | SQLite（hermes 内部） | SQLite（自己） |
| ticker 列表 | **写死在 script 里** | **读 H5 watchlist.db** |
| 执行 | hermes cron 调 script | scheduler 直接调 run_batch.py |
| 日志 | hermes cron runs（持久化 execution_id） | scheduler.py 写 logs/scheduler.log + state.db |
| 网关依赖 | 必须有 hermes gateway 运行 | 无 |

## 故障排查

```bash
# 看实时日志
tail -f logs/scheduler.log

# 看每个 ticker 的最近状态
sqlite3 state.db 'SELECT * FROM job_state'

# 手动跑一个 ticker
/home/lzero/workspace/TradingAgents/.venv/bin/python scheduler.py  # 前台跑，看日志

# systemd 状态
systemctl --user status ta-scheduler

# 强制重跑某个 ticker（清掉 state）
sqlite3 state.db "DELETE FROM job_state WHERE symbol='BABA'"
```