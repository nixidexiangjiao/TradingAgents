// ===== 页面 3：任务中心 =====
window.Pages.jobs = async function () {
  const root = document.getElementById("page-root");
  root.innerHTML = `<div class="empty"><div class="emoji">⏳</div>加载中…</div>`;
  try {
    await window.API.refreshAll();
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="emoji">⚠️</div>无法连接后端<br><div class="hint">${e.message}</div></div>`;
    return;
  }
  render();
};

function render() {
  const root = document.getElementById("page-root");
  const jobs = window.API.STATE.jobs;
  root.innerHTML = `
    <div class="page">
      <h1 class="page-title">任务中心</h1>
      <p class="page-sub">Hermes cron + TradingAgents CLI</p>

      <button class="btn mb-8" id="btn-run-now">▶ 立即跑一次（按当前关注列表）</button>

      <div class="card">
        <div class="card-title mb-8">定时任务</div>
        ${jobs.map((j) => `
          <div class="list-item" style="flex-direction:column; align-items:stretch; gap:8px;">
            <div class="row">
              <div class="main">
                <div class="title">${j.name}</div>
                <div class="sub">${j.schedule} · ${j.scope}</div>
              </div>
              <span class="pill ${j.status === 'active' ? 'green' : 'yellow'}">${j.status === 'active' ? '运行中' : (j.status || '已暂停')}</span>
            </div>
            <div class="row" style="font-size:12px; color: var(--text-dim);">
              <span>📅 上次：${j.lastRun || '暂无'}</span>
              <span class="spacer"></span>
              <span>⏱ ${j.duration || '—'}</span>
              <span class="pill ${j.lastStatus === 'success' ? 'green' : j.lastStatus === 'failed' ? 'red' : 'yellow'}" style="margin-left:8px;">${j.lastStatus === 'success' ? '成功' : j.lastStatus === 'failed' ? '失败' : '未运行'}</span>
            </div>
            <div class="row" style="gap:6px;">
              <span class="pill">cron: ${j.cronId}</span>
              <div class="spacer"></div>
              <button class="btn small secondary" onclick="alert('查看日志（demo）')">📋 日志</button>
            </div>
          </div>
        `).join("")}
      </div>

      <div class="card">
        <div class="card-title mb-8">执行历史（最近报告）</div>
        ${(window.API.STATE.reports || []).slice(0, 5).map((r) => `
          <div class="row" style="padding: 6px 0; border-top: 1px solid var(--border);">
            <span class="signal ${r.signal === 'bull' ? 'bull' : r.signal === 'bear' ? 'bear' : 'neutral'}">
              <span class="dot"></span>
            </span>
            <div style="flex:1; min-width:0;">
              <div style="font-size:14px; font-weight:500;">${r.ticker} — ${r.label}</div>
              <div class="muted small">${r.date} · ${r.elapsed_s ? Math.round(r.elapsed_s) + 's' : '—'}</div>
            </div>
          </div>
        `).join("")}
      </div>

      <div class="card">
        <div class="card-title mb-8">说明</div>
        <div class="muted small">
          • 定时任务由 Hermes 网关调度<br>
          • 立即跑会调用 <code>run_batch.py</code>，写 <code>batch_YYYY-MM-DD.json</code><br>
          • 后台异步执行，进度可看「任务日志」
        </div>
      </div>
    </div>
  `;

  document.getElementById("btn-run-now").addEventListener("click", runNowAndMonitor);
}

async function runNowAndMonitor() {
  if (!confirm("立即按当前关注列表跑一次分析？")) return;
  const root = document.getElementById("page-root");
  try {
    const r = await window.API.runNow();
    // 显示进度面板
    const panel = document.createElement("div");
    panel.id = "run-monitor";
    panel.className = "card";
    panel.innerHTML = `
      <div class="card-title mb-8">▶ 正在跑 · runId=${r.runId}</div>
      <div class="muted small">Tickers: ${r.tickers.join(", ")}</div>
      <pre id="run-log" style="background: var(--bg); padding: 8px; border-radius: 8px; max-height: 200px; overflow: auto; font-size: 11px; white-space: pre-wrap; word-wrap: break-word; margin-top: 8px;">⏳ 启动中…</pre>
    `;
    document.querySelector(".page").prepend(panel);

    // 轮询状态
    for (let i = 0; i < 60; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      try {
        const s = await window.API.getRunStatus(r.runId);
        const log = document.getElementById("run-log");
        if (log) log.textContent = s.tail || "（无日志）";
        if (s.status === "completed") {
          if (log) log.textContent += `\n\n[exitCode=${s.exitCode}] ✅ 完成`;
          await window.API.refreshAll();
          render();
          return;
        }
      } catch (e) { /* 忽略单次失败 */ }
    }
    alert("已超时（>3 分钟），请到任务日志看实际进度");
  } catch (e) {
    alert("触发失败：" + e.message);
  }
}
