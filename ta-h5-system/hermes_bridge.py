"""
Hermes cron 包装层
==================
所有定时任务全部走 hermes cron。后端只做：
  - 解析 hermes cron list 文本
  - 调 hermes cron runs / status 拿历史
  - 创建/暂停/启用/删除/立刻跑都走 subprocess
  - 缓存 5 秒（避免每个 request 都打 hermes）

注意：
  - hermes 是个 subprocess，调用要 timeout
  - 文本解析要稳（hermes 输出格式变了整个 endpoint 都会挂）
"""
import os
import re
import json
import time
import subprocess
import shutil
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("h5.hermes")

# ==================== 缓存 ====================
_CACHE = {
    "list": (0.0, []),
    "status": (0.0, {}),
    "ttl_list": 5.0,        # list 5s（可能频繁改）
    "ttl_status": 30.0,     # status 30s
}


def _hermes_bin() -> str:
    """hermes CLI 绝对路径。subprocess 必须用绝对路径（systemd 启动时 PATH 可能不包含 ~/.local/bin）"""
    found = shutil.which("hermes")
    if found:
        return found
    # fallback：常见位置
    for p in ("/home/lzero/.local/bin/hermes", "/usr/local/bin/hermes", "/usr/bin/hermes"):
        if os.path.exists(p):
            return p
    return "hermes"  # 留个名字，至少报错信息能看清


def _run_hermes(args: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """调 hermes cron <args>，返回 (returncode, stdout, stderr)"""
    cmd = [_hermes_bin(), "cron"] + args
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PATH"] = env.get("PATH", "") + ":/home/lzero/.local/bin"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"hermes cron {' '.join(args)} timeout after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"hermes CLI not found at {_hermes_bin()}"
    except Exception as e:
        return -1, "", f"hermes cron 调用失败: {e}"


# ==================== list 解析 ====================
# hermes cron list 输出形如:
#
#   8c3ba2ccf6d1 [active]
#     Name:      tradingagents-batch-baba-0700
#     Schedule:  30 21 * * 1-5
#     Repeat:    ∞
#     Next run:  2026-08-24T21:30:00+08:00
#     Deliver:   origin
#     Script:    tradingagents_nightly.sh
#     Mode:      no-agent (script stdout delivered directly)
#     Last run:  2026-08-22T21:30:40.131973+08:00  ok
#     Execution: completed  8072f0ad89754809b179262a163891cb
#
# 失败时:
#     Last run:  2026-08-21T09:00:23.768130+08:00  error: cannot import name ...
#     Execution: failed  6ab04c7bd84f44fa8917326e2e47014e


_JOB_HEADER_RE = re.compile(r"^\s*([0-9a-f]{12})\s+\[(\w+)\]\s*$")
_FIELD_RE = re.compile(r"^\s{4}([A-Z][\w /()-]+?):\s+(.+?)\s*$")
# 特殊：Last run 和 Execution 在同一行 / 多行


def _parse_list_output(text: str) -> list[dict]:
    """解析 hermes cron list 文本"""
    jobs = []
    current = None
    for line in text.splitlines():
        m = _JOB_HEADER_RE.match(line)
        if m:
            if current:
                jobs.append(current)
            current = {
                "id": m.group(1),
                "status": m.group(2),  # active / paused
            }
            continue
        if not current:
            continue

        m = _FIELD_RE.match(line)
        if m:
            key, val = m.group(1).strip(), m.group(2).strip()
            key_norm = key.lower().replace(" ", "_")
            # Last run + Execution 比较特殊，可能跨多行
            if key_norm == "name":
                current["name"] = val
            elif key_norm == "schedule":
                current["schedule"] = val
            elif key_norm == "repeat":
                current["repeat"] = val
            elif key_norm == "next_run":
                current["next_run"] = val
            elif key_norm == "deliver":
                current["deliver"] = val
            elif key_norm == "script":
                current["script"] = val
            elif key_norm == "mode":
                current["mode"] = val
            elif key_norm == "skills":
                current["skills"] = val
            elif key_norm == "last_run":
                # 形如 "2026-08-22T21:30:40.131973+08:00  ok" 或 "error: ..."
                parts = val.split(None, 1)
                current["last_run_ts"] = parts[0]
                current["last_status_note"] = parts[1] if len(parts) > 1 else ""
                current["last_status"] = "failed" if "error" in current.get("last_status_note", "") else "success"
            elif key_norm == "execution":
                # 形如 "completed  8072f0ad89754809b179262a163891cb"
                parts = val.split(None, 1)
                current["last_execution_status"] = parts[0]
                current["last_execution_id"] = parts[1] if len(parts) > 1 else ""
            continue

        # 续行（Last run 的 error 信息可能换行）—— 看是否以空白起头
        if line.startswith("    ") and "last_status_note" in current and current.get("last_status_note", "").startswith("error:"):
            current["last_status_note"] = (current["last_status_note"] + " " + line.strip()).strip()

    if current:
        jobs.append(current)
    return jobs


def list_jobs(force: bool = False) -> list[dict]:
    """调 hermes cron list，5s 缓存。返回标准化后的 job 列表"""
    now = time.time()
    if not force and (now - _CACHE["list"][0]) < _CACHE["ttl_list"]:
        return _CACHE["list"][1]

    rc, out, err = _run_hermes(["list"])
    if rc != 0:
        log.warning(f"hermes cron list 失败: rc={rc} err={err[:200]}")
        # 缓存失败时返回空，但保留时间戳避免反复打 hermes
        _CACHE["list"] = (now, [])
        return []

    jobs = _parse_list_output(out)
    # 标准化字段
    for j in jobs:
        j.setdefault("name", "(unnamed)")
        j.setdefault("last_status", "unknown")
        j.setdefault("last_execution_status", "unknown")
        # 推断 scope（按 cron name 关键词）
        j["scope"] = _infer_scope(j)
        # 推断我们关心的字段
        j["tradingagent_related"] = (
            "tradingagent" in j.get("name", "").lower()
            or "tradingagent" in j.get("script", "").lower()
            or "baba" in j.get("name", "").lower()
            or "0700" in j.get("name", "").lower()
        )
    _CACHE["list"] = (now, jobs)
    log.info(f"hermes cron list: {len(jobs)} jobs")
    return jobs


def _infer_scope(job: dict) -> str:
    name = (job.get("name") or "").lower()
    if "baba" in name and "0700" in name:
        return "BABA + 0700.HK"
    if "baba" in name or "9988" in name or "alibaba" in name:
        return "BABA / 9988.HK"
    if "0700" in name or "tencent" in name or "腾讯" in name:
        return "0700.HK"
    if "watchlist" in name:
        return "watchlist 全部"
    if "version" in name:
        return "system"
    return name or "?"


# ==================== 状态 ====================
def gateway_status(force: bool = False) -> dict:
    """hermes cron status -> {running, pid, jobs_count, next_run, ticker_heartbeat_age_s}"""
    now = time.time()
    if not force and (now - _CACHE["status"][0]) < _CACHE["ttl_status"]:
        return _CACHE["status"][1]

    rc, out, err = _run_hermes(["status"])
    if rc != 0:
        return {"running": False, "error": err[:200]}

    info = {"running": "running" in out.lower() and "is running" in out.lower()}
    for line in out.splitlines():
        line = line.strip()
        m = re.search(r"PID:\s*(\d+)", line)
        if m:
            info["pid"] = int(m.group(1))
        m = re.search(r"(\d+)\s+active job", line)
        if m:
            info["active_jobs"] = int(m.group(1))
        m = re.search(r"Next run:\s*(.+)", line)
        if m:
            info["next_run"] = m.group(1).strip()
        m = re.search(r"Ticker heartbeat:\s*(\d+)s ago", line)
        if m:
            info["heartbeat_age_s"] = int(m.group(1))
    _CACHE["status"] = (now, info)
    return info


# ==================== runs 历史 ====================
_RUNS_RE = re.compile(
    r"^([0-9a-f]{32})\s+(\w+)\s+job=([0-9a-f]{12})\s+source=(\w+)\s+(\S+)\s*$"
)


def get_runs(job_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """hermes cron runs [job_id] --limit N"""
    args = ["runs"]
    if job_id:
        args.append(job_id)
    args.extend(["--limit", str(limit)])
    rc, out, err = _run_hermes(args)
    if rc != 0:
        log.warning(f"hermes cron runs 失败: {err[:200]}")
        return []
    runs = []
    for line in out.splitlines():
        m = _RUNS_RE.match(line)
        if m:
            runs.append({
                "execution_id": m.group(1),
                "status": m.group(2),       # completed / failed / running
                "job_id": m.group(3),
                "source": m.group(4),
                "ts": m.group(5),
            })
    return runs


# ==================== 操作 ====================
def run_now(job_id: str) -> dict:
    """立刻跑一个 job（hermes cron run <id>）"""
    rc, out, err = _run_hermes(["run", job_id], timeout=20)
    return {
        "ok": rc == 0,
        "returncode": rc,
        "stdout": out[-500:] if out else "",
        "stderr": err[-500:] if err else "",
    }


def pause_job(job_id: str) -> dict:
    rc, out, err = _run_hermes(["pause", job_id])
    _invalidate_cache()
    return {"ok": rc == 0, "returncode": rc, "stdout": out[-300:], "stderr": err[-300:]}


def resume_job(job_id: str) -> dict:
    rc, out, err = _run_hermes(["resume", job_id])
    _invalidate_cache()
    return {"ok": rc == 0, "returncode": rc, "stdout": out[-300:], "stderr": err[-300:]}


def remove_job(job_id: str) -> dict:
    rc, out, err = _run_hermes(["remove", job_id])
    _invalidate_cache()
    return {"ok": rc == 0, "returncode": rc, "stdout": out[-300:], "stderr": err[-300:]}


def create_job(
    name: str,
    schedule: str,
    script: Optional[str] = None,
    prompt: Optional[str] = None,
    deliver: str = "origin",
    repeat: Optional[int] = None,
    no_agent: bool = False,
    workdir: Optional[str] = None,
    skills: Optional[list[str]] = None,
) -> dict:
    """创建 hermes cron job
    - 跑 tradingagent 必须用 --script + --no-agent（no_agent=true 直接送 stdout）
    - schedule 支持 '30 21 * * 1-5'  或 '30m' / 'every 2h'
    """
    if not script and not prompt:
        return {"ok": False, "stderr": "script 或 prompt 必须二选一"}

    args = ["create", schedule, "--name", name, "--deliver", deliver]
    if script:
        args.extend(["--script", script])
        if no_agent:
            args.append("--no-agent")
    elif prompt:
        args.append(prompt)
    if repeat is not None:
        args.extend(["--repeat", str(repeat)])
    if workdir:
        args.extend(["--workdir", workdir])
    if skills:
        for s in skills:
            args.extend(["--skill", s])

    rc, out, err = _run_hermes(args, timeout=30)
    _invalidate_cache()
    # 解析 output 拿新 job id（hermes create 通常会输出 job id）
    job_id = None
    m = re.search(r"\b([0-9a-f]{12})\b", out)
    if m:
        job_id = m.group(1)
    return {
        "ok": rc == 0,
        "returncode": rc,
        "job_id": job_id,
        "stdout": out[-500:],
        "stderr": err[-500:],
    }


# ==================== watchlist ↔ cron 联动 ====================
# 一个 ticker 对应一个 hermes cron job，name 形如：ta-batch-<SYMBOL_NORMALIZED>
# 例如 BABA -> ta-batch-BABA，0700.HK -> ta-batch-0700HK


def _normalize_for_cron(symbol: str) -> str:
    s = symbol.upper().replace(".", "").replace("-", "")
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s


def find_cron_for_symbol(symbol: str) -> Optional[dict]:
    """在 hermes cron list 里找 name=ta-batch-<SYMBOL_NORMALIZED> 的 job"""
    target = f"ta-batch-{_normalize_for_cron(symbol)}"
    for j in list_jobs(force=True):
        if j.get("name") == target:
            return j
    return None


def ensure_cron_for_symbol(symbol: str, schedule: str = "30 21 * * 1-5",
                            script_name: str = "analyze_one.sh",
                            deliver: str = "origin") -> dict:
    """为某个 ticker 确保有 cron job。已存在 → 跳过；不存在 → 创建并返回 {created, job_id, name}
    script_name 必须是 ~/.hermes/scripts/ 下的文件名（hermes 强制要求）"""
    normalized = _normalize_for_cron(symbol)
    name = f"ta-batch-{normalized}"
    existing = find_cron_for_symbol(symbol)
    if existing:
        return {"created": False, "job_id": existing["id"], "name": name, "already": True}
    r = create_job(
        name=name,
        schedule=schedule,
        script=script_name,
        no_agent=True,
        deliver=deliver,
    )
    return {
        "created": r["ok"],
        "job_id": r.get("job_id"),
        "name": name,
        "stderr": r.get("stderr", ""),
        "stdout_tail": r.get("stdout", "")[-200:],
    }


def remove_cron_for_symbol(symbol: str) -> dict:
    """删除 ticker 对应的 cron"""
    existing = find_cron_for_symbol(symbol)
    if not existing:
        return {"removed": False, "reason": "not found"}
    r = remove_job(existing["id"])
    return {"removed": r["ok"], "job_id": existing["id"], "name": existing["name"]}


def _invalidate_cache():
    _CACHE["list"] = (0.0, [])
    _CACHE["status"] = (0.0, {})
