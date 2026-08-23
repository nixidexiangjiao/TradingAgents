# TradingAgents H5 管理后台

围绕 TradingAgents 的手机 H5 看板 + 后端，**所有定时任务都走 [Hermes cron](https://hermes-agent.nousresearch.com/)**，本服务只做"读取 + 立刻跑"的薄壳。

## 一句话定位

```
TradingAgents CLI  ←  跑分析 (BABA + 0700.HK + watchlist)
       ↓
   results/batch_*.json     ←  唯一真数据源
       ↓
TradingAgents H5  ←  读 + 看板 + 触发
       ↓
   手机浏览器
```

## 部署

### 1. 准备 Python 环境（独立 venv，不污染 TradingAgents venv）

```bash
cd /home/lzero/workspace/TradingAgents/ta-h5-system
python3 -m venv .venv-demo
.venv-demo/bin/pip install -r requirements.txt
```

### 2. 装 systemd user service（开机自启 + 守护）

```bash
mkdir -p ~/.config/systemd/user
cp systemd/ta-h5.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable ta-h5
systemctl --user start ta-h5
systemctl --user status ta-h5
```

服务只会 `listen 127.0.0.1:8765`，**不暴露公网**。

### 3. Tailscale Serve（手机访问入口）

```bash
# 把 127.0.0.1:8765 通过 Tailscale 暴露，拿到 https://<node-name>.<tailnet>.ts.net/
tailscale serve https / http://127.0.0.1:8765
# 查看状态
tailscale serve status
```

手机装 Tailscale App，浏览器打开 `https://<node-name>.<tailnet>.ts.net/` 即可。

### 4. 升级 / 重启

```bash
cd /home/lzero/workspace/TradingAgents/ta-h5-system
git pull  # 拉新代码
.venv-demo/bin/pip install -r requirements.txt  # 依赖变了的话
systemctl --user restart ta-h5
journalctl --user -u ta-h5 -n 50  # 看日志
```

## API

| 路径 | 方法 | 作用 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/gateway` | GET | Hermes 网关状态 |
| `/api/watchlist` | GET/POST | 列表 / 新增 ticker |
| `/api/watchlist/{id}` | PUT/DELETE | 修改 / 删除 |
| `/api/snapshots` | GET | yfinance 实时价（15min cache） |
| `/api/reports` | GET | 所有 batch_*.json 展平 |
| `/api/reports/{date}/{ticker}` | GET | 单份报告（解析 markdown） |
| `/api/jobs` | GET | 全部 Hermes cron |
| `/api/jobs/runs/{id}` | GET | 某个 job 的执行历史 |
| `/api/jobs/run/{id}` | POST | 立刻跑某个 job（调 hermes） |
| `/api/jobs/create` | POST | 新建 cron job |
| `/api/jobs/{id}/pause` | POST | 暂停 |
| `/api/jobs/{id}/resume` | POST | 启用 |
| `/api/jobs/{id}` | DELETE | 删除 |
| `/api/ask` | POST | 自然语言查询（PoC: 关键词路由） |
| `/api/actions` | GET | 我们做过的操作日志 |

可选鉴权：用 `TA_H5_TOKEN=xxx` 启 server，前端在 header 传 `X-Token: xxx`。默认 off（trust 127.0.0.1 + Tailscale）。

## 数据流

- **watchlist** → SQLite `data/ta_h5.db`，启动时自动建表 + 灌入默认（0700.HK / 9988.HK / BABA / 3690.HK）
- **reports** → 只读扫 `../results/batch_*.json`，不复制
- **jobs** → 100% 调 hermes CLI（list / runs / status / create / pause / resume / remove / run），5s 缓存
- **snapshots** → yfinance，带 15min TTL cache，失败时回退到 batch 最近决策

## 故障排查

```bash
# H5 server 状态
systemctl --user status ta-h5
journalctl --user -u ta-h5 -n 100

# Hermes cron 状态
hermes cron status
hermes cron list

# TradingAgents 自己的脚本日志（最近一次跑）
ls -lt /home/lzero/.hermes/logs/tradingagents/ | head -5
tail -100 /home/lzero/.hermes/logs/tradingagents/$(ls -t /home/lzero/.hermes/logs/tradingagents/ | head -1)

# 数据库
sqlite3 /home/lzero/workspace/TradingAgents/ta-h5-system/data/ta_h5.db '.schema watchlist'
sqlite3 ... 'SELECT id, symbol, name, enabled FROM watchlist'
```

## 不在范围内

- Hermes cron 自身的创建：交给 `hermes cron create` CLI，本服务只是 wrapper
- TradingAgents 引擎本身的修改：本服务零侵入 TA 仓库代码
- 推送通知：失败信息已经在 Hermes 那侧推送了，H5 只显示当前状态
