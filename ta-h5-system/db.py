"""
SQLite 持久化层
================
只存可变状态：watchlist + jobs_state（jobs 实际数据来自 hermes cron，state 只存我们的 metadata 标签）
不用 SQLAlchemy，直接 sqlite3 stdlib，够用且零依赖。
"""
import sqlite3
import json
import time
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

log = logging.getLogger("h5.db")

DB_PATH = Path(__file__).resolve().parent / "data" / "ta_h5.db"

# Schema：watchlist 是核心表，其它预留
SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    id TEXT PRIMARY KEY,
    symbol TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    market TEXT NOT NULL,           -- HK / US / CN / CRYPTO
    currency TEXT,
    icon TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,  -- 0/1
    notes TEXT,
    added_at TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    -- 我们的 metadata：标签、分组、买入价位、目标价...
    tags TEXT,                     -- JSON array
    target_price REAL,
    stop_loss REAL,
    cron_id TEXT,                     -- 关联的 hermes cron job_id（自动创建时填）
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchlist_enabled ON watchlist(enabled);
CREATE INDEX IF NOT EXISTS idx_watchlist_market ON watchlist(market);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,          -- create/update/delete/run_now/...
    actor TEXT,                    -- 'web' / 'hermes' / 'system'
    details TEXT                   -- JSON
);

CREATE INDEX IF NOT EXISTS idx_action_log_ts ON action_log(ts);
"""


@contextmanager
def conn():
    """短连接，每个操作开/关一次。SQLite WAL 模式够用。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db() -> None:
    """启动时跑一次，建表 + 灌入默认 watchlist"""
    with conn() as c:
        c.executescript(SCHEMA)
        # 幂等迁移：给已存在的表加新列（CREATE TABLE IF NOT EXISTS 不会改 schema）
        for col in ("cron_id",):
            try:
                c.execute(f"ALTER TABLE watchlist ADD COLUMN {col} TEXT")
            except Exception:
                pass  # 列已存在
        cur = c.execute("SELECT COUNT(*) AS n FROM watchlist")
        if cur.fetchone()["n"] == 0:
            log.info("首次启动，灌入默认 watchlist")
            now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            defaults = [
                ("w1", "0700.HK", "腾讯控股", "HK", "HKD", "🎮", 1, "游戏 + 视频号 + AI 投入", "2026-05-12", 1),
                ("w2", "9988.HK", "阿里巴巴-W", "HK", "HKD", "🛒", 1, "电商 + 云 + AI 资本开支", "2026-05-12", 2),
                ("w3", "BABA", "Alibaba (ADR)", "US", "USD", "🛍️", 1, "9988.HK 的 ADR proxy", "2026-05-20", 3),
                ("w4", "3690.HK", "美团-W", "HK", "HKD", "🍱", 0, "暂停观察", "2026-06-04", 4),
            ]
            c.executemany(
                "INSERT INTO watchlist (id, symbol, name, market, currency, icon, enabled, notes, added_at, sort_order, tags, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?)",
                [(*d, now) for d in defaults],
            )


# ==================== watchlist CRUD ====================
def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["enabled"] = bool(d["enabled"])
    d["tags"] = json.loads(d.get("tags") or "[]")
    return d


def list_watchlist(enabled_only: bool = False) -> list[dict]:
    with conn() as c:
        if enabled_only:
            rows = c.execute("SELECT * FROM watchlist WHERE enabled=1 ORDER BY sort_order, symbol").fetchall()
        else:
            rows = c.execute("SELECT * FROM watchlist ORDER BY sort_order, symbol").fetchall()
        return [_row_to_dict(r) for r in rows]


def get_watchlist_item(item_id: str) -> Optional[dict]:
    with conn() as c:
        r = c.execute("SELECT * FROM watchlist WHERE id=?", (item_id,)).fetchone()
        return _row_to_dict(r) if r else None


def get_watchlist_by_symbol(symbol: str) -> Optional[dict]:
    with conn() as c:
        r = c.execute("SELECT * FROM watchlist WHERE UPPER(symbol)=?", (symbol.upper(),)).fetchone()
        return _row_to_dict(r) if r else None


def create_watchlist_item(data: dict, actor: str = "web") -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    item_id = f"w{int(time.time() * 1000)}"
    added_at = data.get("addedAt") or now[:10]
    currency = data.get("currency") or {"HK": "HKD", "US": "USD", "CN": "CNY", "CRYPTO": "USD"}.get(data["market"], "USD")
    with conn() as c:
        try:
            c.execute(
                "INSERT INTO watchlist (id, symbol, name, market, currency, icon, enabled, notes, added_at, sort_order, tags, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id, data["symbol"].upper(), data["name"], data["market"], currency,
                    data.get("icon") or "📊", 1 if data.get("enabled", True) else 0,
                    data.get("notes") or "", added_at,
                    data.get("sortOrder") or 999,
                    json.dumps(data.get("tags") or [], ensure_ascii=False),
                    now,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"symbol 已存在: {data['symbol']}") from e
        _log_action(c, actor, "create", {"id": item_id, "symbol": data["symbol"]})
    return get_watchlist_item(item_id)


def update_watchlist_item(item_id: str, data: dict, actor: str = "web") -> Optional[dict]:
    now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    with conn() as c:
        cur = c.execute("SELECT * FROM watchlist WHERE id=?", (item_id,)).fetchone()
        if not cur:
            return None
        merged = dict(cur)
        for k in ("symbol", "name", "market", "currency", "icon", "notes", "target_price", "stop_loss", "cron_id"):
            if k in data:
                merged[k] = data[k]
        if "enabled" in data:
            merged["enabled"] = 1 if data["enabled"] else 0
        if "tags" in data:
            merged["tags"] = json.dumps(data["tags"] or [], ensure_ascii=False)
        if "sortOrder" in data:
            merged["sort_order"] = data["sortOrder"]
        merged["updated_at"] = now
        c.execute(
            "UPDATE watchlist SET symbol=?, name=?, market=?, currency=?, icon=?, enabled=?, notes=?, "
            "tags=?, target_price=?, stop_loss=?, sort_order=?, cron_id=?, updated_at=? WHERE id=?",
            (
                merged["symbol"].upper(), merged["name"], merged["market"], merged["currency"],
                merged["icon"], merged["enabled"], merged["notes"], merged["tags"],
                merged.get("target_price"), merged.get("stop_loss"), merged["sort_order"],
                merged.get("cron_id"), now, item_id,
            ),
        )
        _log_action(c, actor, "update", {"id": item_id, "symbol": merged["symbol"]})
    return get_watchlist_item(item_id)


def delete_watchlist_item(item_id: str, actor: str = "web") -> bool:
    with conn() as c:
        cur = c.execute("SELECT symbol FROM watchlist WHERE id=?", (item_id,)).fetchone()
        if not cur:
            return False
        c.execute("DELETE FROM watchlist WHERE id=?", (item_id,))
        _log_action(c, actor, "delete", {"id": item_id, "symbol": cur["symbol"]})
    return True


# ==================== action log ====================
def _log_action(c: sqlite3.Connection, actor: str, action: str, details: dict) -> None:
    c.execute(
        "INSERT INTO action_log (ts, action, actor, details) VALUES (?, ?, ?, ?)",
        (time.strftime("%Y-%m-%dT%H:%M:%S+08:00"), action, actor, json.dumps(details, ensure_ascii=False)),
    )


def recent_actions(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


# ==================== meta ====================
def set_meta(key: str, value: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO app_meta (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, time.strftime("%Y-%m-%dT%H:%M:%S+08:00")),
        )


def get_meta(key: str) -> Optional[str]:
    with conn() as c:
        r = c.execute("SELECT value FROM app_meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None
