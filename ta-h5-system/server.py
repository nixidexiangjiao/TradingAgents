"""
TradingAgents H5 系统 — production 化
======================================
变更 vs PoC：
- watchlist 改 SQLite (db.py)
- jobs 全部走 hermes cron (hermes_bridge.py)
- 鉴权：可选 simple token（通过 env TA_H5_TOKEN 启用，默认 disabled 适合内网/Tailscale）
- 启动：systemd user service，端口由 TA_H5_PORT 决定

API：
  /api/health
  /api/gateway                       GET  Hermes 网关状态
  /api/watchlist                     GET/POST
  /api/watchlist/{id}                PUT/DELETE
  /api/snapshots                     GET  yfinance 实时（15min cache）
  /api/reports?limit&ticker          GET  列表
  /api/reports/{date}/{ticker}       GET  详情
  /api/jobs                          GET  全部 hermes cron
  /api/jobs/runs/{job_id}            GET  某个 job 的历史
  /api/jobs/run/{job_id}             POST 立刻跑
  /api/jobs/create                   POST 新建
  /api/jobs/{job_id}/pause           POST 暂停
  /api/jobs/{job_id}/resume          POST 启用
  /api/jobs/{job_id}                 DELETE 删除
  /api/ask                           POST 自然语言查询
  /api/actions                       GET 我们的操作日志
  /                                   GET  H5 入口
"""
import os
import re
import json
import time
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ⚠️ 必须在 import yfinance 之前设 proxy
_proxy_file = os.path.expanduser("~/proxy.sh")
if os.path.exists(_proxy_file):
    for line in open(_proxy_file):
        line = line.strip()
        if line.startswith("export "):
            kv = line[7:].split("=", 1)
            if len(kv) == 2 and kv[0] in ("http_proxy", "https_proxy", "no_proxy"):
                os.environ[kv[0]] = kv[1].strip('"').strip("'")

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import db
import hermes_bridge

# ==================== Paths ====================
APP_DIR = Path(__file__).resolve().parent
TA_DIR = Path("/home/lzero/workspace/TradingAgents")
RESULTS_DIR = TA_DIR / "results"
LOG_DIR = APP_DIR / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ==================== Logging ====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "server.log"),
    ],
)
log = logging.getLogger("h5")

# ==================== App ====================
app = FastAPI(title="TradingAgents H5", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # PoC: 内网 / Tailscale 用
    allow_methods=["*"],
    allow_headers=["*"],
)

# 鉴权：默认不启用（trust LAN/Tailscale）；用环境变量启用 simple token
TA_H5_TOKEN = os.environ.get("TA_H5_TOKEN", "").strip()


def require_auth(x_token: Optional[str] = Header(None)):
    if not TA_H5_TOKEN:
        return  # disabled
    if x_token != TA_H5_TOKEN:
        raise HTTPException(401, "invalid or missing X-Token header")


@app.on_event("startup")
def _startup():
    db.init_db()
    log.info(f"TradingAgents H5 started (auth={'on' if TA_H5_TOKEN else 'off'})")


# ==================== Watchlist (SQLite) ====================
class WatchItemIn(BaseModel):
    symbol: str
    name: str
    market: str
    currency: Optional[str] = None
    icon: Optional[str] = "📊"
    enabled: bool = True
    notes: Optional[str] = ""
    sortOrder: Optional[int] = None
    tags: Optional[list[str]] = []
    targetPrice: Optional[float] = None
    stopLoss: Optional[float] = None


class WatchItemUpdate(BaseModel):
    name: Optional[str] = None
    market: Optional[str] = None
    currency: Optional[str] = None
    icon: Optional[str] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None
    sortOrder: Optional[int] = None
    tags: Optional[list[str]] = None
    targetPrice: Optional[float] = None
    stopLoss: Optional[float] = None


@app.get("/api/watchlist")
def get_watchlist(enabled_only: bool = False, _=Depends(require_auth)):
    return {"items": db.list_watchlist(enabled_only=enabled_only)}


@app.post("/api/watchlist")
def create_watchlist_item(item: WatchItemIn, _=Depends(require_auth)):
    try:
        new = db.create_watchlist_item(item.dict(), actor="web")
        return new
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.put("/api/watchlist/{item_id}")
def update_watchlist_item(item_id: str, item: WatchItemUpdate, _=Depends(require_auth)):
    data = {k: v for k, v in item.dict().items() if v is not None}
    updated = db.update_watchlist_item(item_id, data, actor="web")
    if not updated:
        raise HTTPException(404, "not found")
    return updated


@app.delete("/api/watchlist/{item_id}")
def delete_watchlist_item(item_id: str, _=Depends(require_auth)):
    if not db.delete_watchlist_item(item_id, actor="web"):
        raise HTTPException(404, "not found")
    return {"ok": True}


# ==================== Snapshots ====================
SNAPSHOT_CACHE = {}  # symbol -> (ts, data)
SNAPSHOT_TTL = 60 * 15


def fetch_snapshot(symbol: str) -> dict:
    now = time.time()
    if symbol in SNAPSHOT_CACHE:
        ts, data = SNAPSHOT_CACHE[symbol]
        if now - ts < SNAPSHOT_TTL and "price" in data and data["price"] is not None:
            return data

    data = {"symbol": symbol, "price": None, "chgPct": None, "asOf": None, "error": None}
    try:
        import yfinance as yf
        yf_symbol = symbol if "." in symbol else f"{symbol}.HK"
        ticker = yf.Ticker(yf_symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        prev = getattr(info, "previous_close", None)
        if price and prev:
            data["price"] = round(float(price), 3)
            data["chgPct"] = round((float(price) - float(prev)) / float(prev) * 100, 2)
            data["asOf"] = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M HKT")
        else:
            data["error"] = "no price from yfinance"
    except Exception as e:
        log.warning(f"yfinance {symbol} 失败: {e}")
        data["error"] = str(e)[:80]

    SNAPSHOT_CACHE[symbol] = (now, data)
    return data


@app.get("/api/snapshots")
def get_snapshots(_=Depends(require_auth)):
    items = db.list_watchlist(enabled_only=True)
    out = {}
    for w in items:
        out[w["symbol"]] = fetch_snapshot(w["symbol"])
    return {"snapshots": out}


# ==================== Reports (read-only) ====================
DECISION_MAP = {
    "Overweight": ("bull", "green", "加仓"),
    "Buy": ("bull", "green", "买入"),
    "Hold": ("neutral", "yellow", "持有"),
    "Neutral": ("neutral", "yellow", "中性"),
    "Underweight": ("bear", "red", "减仓"),
    "Sell": ("bear", "red", "卖出"),
}


def parse_decision(d: Optional[str]) -> tuple:
    if not d:
        return ("neutral", "yellow", "未知")
    return DECISION_MAP.get(d, ("neutral", "yellow", d))


def parse_final_report(md: str) -> dict:
    if not md:
        return {"rating": None, "summary": None, "thesis": None}
    m = re.search(r"\*\*Rating\*\*:\s*([^\n]+)", md)
    rating = m.group(1).strip() if m else None
    m = re.search(r"\*\*Executive Summary\*\*:\s*(.+?)(?=\n\n\*\*|\Z)", md, re.DOTALL)
    summary = m.group(1).strip() if m else None
    m = re.search(r"\*\*Investment Thesis\*\*:\s*(.+)$", md, re.DOTALL)
    thesis = m.group(1).strip() if m else None
    return {"rating": rating, "summary": summary, "thesis": thesis}


def ticker_name(symbol: str) -> str:
    item = db.get_watchlist_by_symbol(symbol)
    return item["name"] if item else symbol


def list_all_reports() -> list[dict]:
    out = []
    if not RESULTS_DIR.exists():
        return out
    for p in sorted(RESULTS_DIR.glob("batch_*.json"), reverse=True):
        date = p.stem.replace("batch_", "")
        try:
            arr = json.loads(p.read_text())
        except Exception as e:
            log.warning(f"解析 {p} 失败: {e}")
            continue
        for r in arr:
            if not isinstance(r, dict):
                continue
            decision = r.get("decision")
            signal, color, label_zh = parse_decision(decision)
            md = r.get("final_trade_decision", "")
            parsed = parse_final_report(md)
            out.append({
                "id": f"{date}__{r.get('ticker', 'unknown')}",
                "ticker": r.get("ticker"),
                "name": ticker_name(r.get("ticker", "")),
                "date": date,
                "decision": decision,
                "label": label_zh,
                "signal": signal,
                "color": color,
                "elapsed_s": r.get("elapsed_s"),
                "error": r.get("error"),
                "summary_excerpt": (parsed["summary"] or "")[:200] if parsed["summary"] else None,
            })
    out.sort(key=lambda x: (x["date"], x["ticker"] or ""), reverse=True)
    return out


def get_report(date: str, ticker: str) -> Optional[dict]:
    p = RESULTS_DIR / f"batch_{date}.json"
    if not p.exists():
        return None
    try:
        arr = json.loads(p.read_text())
    except Exception:
        return None
    for r in arr:
        if isinstance(r, dict) and r.get("ticker", "").upper() == ticker.upper():
            decision = r.get("decision")
            signal, color, label_zh = parse_decision(decision)
            parsed = parse_final_report(r.get("final_trade_decision", ""))
            return {
                "ticker": r.get("ticker"),
                "name": ticker_name(r.get("ticker", "")),
                "date": date,
                "decision": decision,
                "label": label_zh,
                "signal": signal,
                "color": color,
                "elapsed_s": r.get("elapsed_s"),
                "error": r.get("error"),
                "rating": parsed["rating"],
                "summary": parsed["summary"],
                "thesis": parsed["thesis"],
                "raw_md": r.get("final_trade_decision", ""),
            }
    return None


@app.get("/api/reports")
def get_reports(limit: int = 50, ticker: Optional[str] = None, _=Depends(require_auth)):
    all_reports = list_all_reports()
    if ticker:
        all_reports = [r for r in all_reports if r["ticker"] and r["ticker"].upper() == ticker.upper()]
    return {"reports": all_reports[:limit]}


@app.get("/api/reports/{date}/{ticker}")
def get_report_endpoint(date: str, ticker: str, _=Depends(require_auth)):
    r = get_report(date, ticker)
    if not r:
        raise HTTPException(404, f"report {date}/{ticker} not found")
    return r


# ==================== Jobs (Hermes cron) ====================
class JobCreate(BaseModel):
    name: str
    schedule: str = Field(..., description="'30 21 * * 1-5' 或 '30m' / 'every 2h'")
    script: Optional[str] = None
    prompt: Optional[str] = None
    deliver: str = "origin"
    repeat: Optional[int] = None
    noAgent: bool = False
    workdir: Optional[str] = None


@app.get("/api/gateway")
def get_gateway(force: bool = False, _=Depends(require_auth)):
    return hermes_bridge.gateway_status(force=force)


@app.get("/api/jobs")
def get_jobs(refresh: bool = False, _=Depends(require_auth)):
    """列出 hermes cron 全部 job。refresh=true 强制重读（写操作后用）"""
    return {"jobs": hermes_bridge.list_jobs(force=refresh)}


@app.get("/api/jobs/runs/{job_id}")
def get_job_runs(job_id: str, limit: int = 20, _=Depends(require_auth)):
    return {"runs": hermes_bridge.get_runs(job_id, limit=limit)}


@app.post("/api/jobs/run/{job_id}")
def run_job_now(job_id: str, _=Depends(require_auth)):
    """立刻跑一个 hermes cron job（用 hermes cron run，非手动启 subprocess）"""
    log.info(f"POST /api/jobs/run/{job_id}")
    r = hermes_bridge.run_now(job_id)
    return r


@app.post("/api/jobs/create")
def create_job(req: JobCreate, _=Depends(require_auth)):
    """创建新 cron job。
    注意：tradingagent 类必须用 script + noAgent=true（跟现有 tradingagents_nightly.sh 一致）"""
    log.info(f"POST /api/jobs/create name={req.name} schedule={req.schedule}")
    r = hermes_bridge.create_job(
        name=req.name,
        schedule=req.schedule,
        script=req.script,
        prompt=req.prompt,
        deliver=req.deliver,
        repeat=req.repeat,
        no_agent=req.noAgent,
        workdir=req.workdir,
    )
    return r


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str, _=Depends(require_auth)):
    return hermes_bridge.pause_job(job_id)


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str, _=Depends(require_auth)):
    return hermes_bridge.resume_job(job_id)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, _=Depends(require_auth)):
    return hermes_bridge.remove_job(job_id)


# ==================== Ask (关键词路由 PoC) ====================
def ask_router(question: str) -> dict:
    q = question.strip()
    q_lower = q.lower()
    sources = []

    # 找 ticker
    symbols = []
    for w in db.list_watchlist():
        if w["symbol"].upper() in q.upper():
            symbols.append(w["symbol"])
    if not symbols and re.search(r"\b(腾讯|0700)\b", q):
        symbols = ["0700.HK"]
    if not symbols and re.search(r"\b(阿里|巴巴|baba|9988)\b", q, re.I):
        symbols = ["BABA", "9988.HK"]

    if re.search(r"cron|跑成功|定时|任务", q_lower):
        jobs = hermes_bridge.list_jobs()
        tradingagent_jobs = [j for j in jobs if j.get("tradingagent_related")]
        lines = [f"Hermes cron 状态（共 {len(jobs)} 个，其中 tradingagent 相关 {len(tradingagent_jobs)} 个）："]
        for j in tradingagent_jobs[:6]:
            status_emoji = "✅" if j.get("last_status") == "success" else "❌"
            lines.append(f"{status_emoji} {j['name']} — {j['schedule']} — 上次 {j.get('last_run_ts', '?')[:16]} — {j.get('last_status')}")
        gw = hermes_bridge.gateway_status()
        lines.append(f"\n网关：{'运行中' if gw.get('running') else '挂了'} (PID {gw.get('pid')}, heartbeat {gw.get('heartbeat_age_s')}s)")
        return {"answer": "\n".join(lines), "sources": ["hermes:cron list", "hermes:cron status"]}

    if "pe" in q_lower or "估值" in q:
        if not symbols:
            return {"answer": "请告诉我查询哪只股票的 PE（例：BABA 现在 PE 多少？）", "sources": []}
        snap = fetch_snapshot(symbols[0])
        return {
            "answer": f"{symbols[0]} 当前价 {snap.get('price', 'N/A')}，涨跌 {snap.get('chgPct', 'N/A')}%。\n\n"
                      f"⚠️ 详细 PE 在 Investment Thesis 段落，去报告页查 batch。",
            "sources": [f"snapshot:{symbols[0]}", "yfinance"],
        }

    if symbols and re.search(r"对比|比较|跟|vs", q):
        all_reports = list_all_reports()
        per = {}
        for s in symbols:
            for r in all_reports:
                if r["ticker"] and r["ticker"].upper() == s.upper():
                    per[s] = r
                    break
        lines = [f"对比 {', '.join(symbols)}："]
        for s in symbols:
            r = per.get(s)
            if r:
                lines.append(f"• {s}（{r['name']}）— {r['date']} — **{r['label']}** — {r['summary_excerpt'] or '（无摘要）'}")
            else:
                lines.append(f"• {s} — 无报告")
        return {"answer": "\n".join(lines), "sources": ["api:/api/reports"]}

    if symbols and len(symbols) == 1:
        r_list = [r for r in list_all_reports() if r["ticker"] and r["ticker"].upper() == symbols[0].upper()]
        if r_list:
            r = r_list[0]
            return {
                "answer": f"{r['ticker']}（{r['name']}）最新报告 @ {r['date']}\n\n决策：**{r['label']}**\n\n摘要：{r['summary_excerpt']}",
                "sources": [f"report:{r['date']}/{r['ticker']}"],
            }

    return {
        "answer": "demo 阶段支持：\n"
                  "• 某 ticker 的当前价 / PE\n"
                  "• 某 ticker 的最近报告\n"
                  "• 对比两只 ticker\n"
                  "• cron 状态 / 网关状态",
        "sources": [],
    }


class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
def ask(req: AskRequest, _=Depends(require_auth)):
    if not req.question.strip():
        raise HTTPException(400, "empty question")
    return ask_router(req.question)


# ==================== Meta ====================
@app.get("/api/health")
def health():
    gw = hermes_bridge.gateway_status()
    return {
        "ok": True,
        "ts": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "results_count": len(list(RESULTS_DIR.glob("batch_*.json"))) if RESULTS_DIR.exists() else 0,
        "watchlist_count": len(db.list_watchlist()),
        "watchlist_enabled": len(db.list_watchlist(enabled_only=True)),
        "hermes_gateway_running": gw.get("running", False),
        "hermes_active_jobs": gw.get("active_jobs", 0),
        "auth_enabled": bool(TA_H5_TOKEN),
    }


@app.get("/api/actions")
def get_actions(limit: int = 50, _=Depends(require_auth)):
    return {"actions": db.recent_actions(limit=limit)}


# ==================== Static (H5) ====================
@app.get("/")
def root():
    return FileResponse(APP_DIR / "index.html")


app.mount("/css", StaticFiles(directory=APP_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=APP_DIR / "js"), name="js")


# ==================== Main ====================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("TA_H5_PORT", "8765"))
    host = os.environ.get("TA_H5_HOST", "127.0.0.1")  # 默认仅本机，外部走 Tailscale
    log.info(f"TradingAgents H5 starting on {host}:{port} (auth={'on' if TA_H5_TOKEN else 'off'})")
    uvicorn.run(app, host=host, port=port, log_level="info")
