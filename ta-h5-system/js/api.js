// ===== API 客户端 =====
// 封装 fetch，所有页面通过 window.API 拿数据
// - 启动时拉一次快照 + 报告 + jobs + watchlist
// - 缓存到 window.STATE（每个页用最新 state 渲染）
// - 失败时回退到 window.MOCK（保 demo 体验）

window.API = (function () {
  const base = "";  // 同源
  const STATE = {
    watchlist: [],
    snapshots: {},
    reports: [],
    jobs: [],
    health: null,
    loaded: false,
    lastError: null,
  };

  async function _fetch(path, opts = {}) {
    const res = await fetch(base + path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status}: ${text.slice(0, 200)}`);
    }
    return res.json();
  }

  async function refreshAll() {
    try {
      const [wl, sn, rp, jb] = await Promise.all([
        _fetch("/api/watchlist").catch((e) => { console.warn("watchlist fail", e); return null; }),
        _fetch("/api/snapshots").catch((e) => { console.warn("snapshots fail", e); return null; }),
        _fetch("/api/reports?limit=50").catch((e) => { console.warn("reports fail", e); return null; }),
        _fetch("/api/jobs").catch((e) => { console.warn("jobs fail", e); return null; }),
      ]);
      if (wl) STATE.watchlist = wl.items || [];
      if (sn) STATE.snapshots = sn.snapshots || {};
      if (rp) STATE.reports = rp.reports || [];
      if (jb) STATE.jobs = jb.jobs || [];
      STATE.loaded = true;
      STATE.lastError = null;
    } catch (e) {
      STATE.lastError = e.message;
      console.warn("[API] refreshAll failed:", e);
    }
    return STATE;
  }

  async function getReport(date, ticker) {
    return _fetch(`/api/reports/${encodeURIComponent(date)}/${encodeURIComponent(ticker)}`);
  }

  async function createWatchItem(item) {
    const r = await _fetch("/api/watchlist", { method: "POST", body: JSON.stringify(item) });
    await refreshAll();
    return r;
  }

  async function updateWatchItem(id, item) {
    const r = await _fetch(`/api/watchlist/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(item) });
    await refreshAll();
    return r;
  }

  async function deleteWatchItem(id) {
    await _fetch(`/api/watchlist/${encodeURIComponent(id)}`, { method: "DELETE" });
    await refreshAll();
  }

  async function runNow(tickers = null) {
    return _fetch("/api/jobs/run", { method: "POST", body: JSON.stringify({ tickers }) });
  }

  async function getRunStatus(runId) {
    return _fetch(`/api/jobs/run/${encodeURIComponent(runId)}/status`);
  }

  async function ask(question) {
    return _fetch("/api/ask", { method: "POST", body: JSON.stringify({ question }) });
  }

  return { STATE, refreshAll, getReport, createWatchItem, updateWatchItem, deleteWatchItem, runNow, getRunStatus, ask };
})();
