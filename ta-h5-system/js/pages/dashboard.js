// ===== 页面 1：看板（首页） =====
window.Pages = window.Pages || {};

window.Pages.dashboard = async function () {
  const root = document.getElementById("page-root");
  root.innerHTML = `<div class="empty"><div class="emoji">⏳</div>加载中…</div>`;

  try {
    await window.API.refreshAll();
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="emoji">⚠️</div>无法连接后端<br><div class="hint">${e.message}</div></div>`;
    return;
  }

  const { watchlist, snapshots, reports, jobs } = window.API.STATE;
  const enabled = watchlist.filter((w) => w.enabled);
  const today = new Date().toISOString().slice(0, 10);
  const todayJobs = jobs.filter((j) => j.lastRun && j.lastRun.startsWith(today));

  root.innerHTML = `
    <div class="page">
      <h1 class="page-title">晚上好，${"靓仔"} 👋</h1>
      <p class="page-sub">${new Date().toLocaleString("zh-CN", { hour12: false })} · 港股已收盘</p>

      <div class="card">
        <div class="card-row mb-8">
          <div class="card-title">今日定时任务</div>
          <a class="card-link" href="#/jobs">查看全部 →</a>
        </div>
        ${todayJobs.length === 0 ? `<div class="muted small">今日还没有运行记录</div>` : todayJobs.map((j) => `
          <div class="row" style="padding: 6px 0; border-top: 1px solid var(--border);">
            <span class="signal ${j.lastStatus === 'success' ? 'bull' : 'bear'}">
              <span class="dot"></span>
            </span>
            <div style="flex:1; min-width:0;">
              <div style="font-size:14px; font-weight:500;">${j.name}</div>
              <div class="muted small">${j.schedule} · ${j.scope}</div>
            </div>
            <span class="pill ${j.lastStatus === 'success' ? 'green' : 'red'}">${j.lastStatus === 'success' ? '成功' : '失败'}</span>
          </div>
        `).join("")}
      </div>

      <div class="card-row mb-8" style="margin-top:4px;">
        <div class="card-title">关注中（${enabled.length}）</div>
        <a class="card-link" href="#/watchlist">管理 →</a>
      </div>
      ${enabled.map((w) => {
        const snap = snapshots[w.symbol] || { price: "—", chgPct: 0, signal: "neutral", error: "no data" };
        const chgClass = (snap.chgPct || 0) > 0 ? "up" : (snap.chgPct || 0) < 0 ? "down" : "flat";
        const signalText = { bull: "看多", bear: "看空", neutral: "中性" }[snap.signal || "neutral"];
        return `
          <a class="ticker-card" href="#/report">
            <span class="ticker-icon">${w.icon || "📊"}</span>
            <div class="ticker-info">
              <div class="ticker-symbol">${w.symbol} <span class="pill ${snap.signal === 'bull' ? 'green' : snap.signal === 'bear' ? 'red' : 'yellow'}">${signalText}</span></div>
              <div class="ticker-name">${w.name} · ${w.market}${snap.error ? ' · ⚠️' : ''}</div>
            </div>
            <div class="ticker-price">
              <div class="ticker-price-num">${snap.price ?? '—'}</div>
              <div class="ticker-price-chg ${chgClass}">${snap.chgPct != null ? (snap.chgPct > 0 ? "+" : "") + snap.chgPct + "%" : '—'}</div>
            </div>
          </a>
        `;
      }).join("")}

      <div class="card-row mb-8" style="margin-top:16px;">
        <div class="card-title">最近报告</div>
        <a class="card-link" href="#/report">全部 →</a>
      </div>
      ${reports.slice(0, 3).map((r) => `
        <a class="list-item" href="#/report/${r.id}" style="flex-direction:column; align-items:stretch; gap:6px;">
          <div class="row">
            <div class="main">
              <div class="title">${r.ticker} <span class="pill ${r.color}">${r.label}</span> <span class="muted small">· ${r.date}</span></div>
              <div class="sub">${r.name}</div>
            </div>
            <div class="right">→</div>
          </div>
          <div class="muted small">${r.summary_excerpt || '（无摘要）'}</div>
        </a>
      `).join("")}

      <div class="card mt-16">
        <div class="card-title mb-8">快捷操作</div>
        <div class="row" style="gap:8px; flex-wrap:wrap;">
          <button class="btn small secondary" onclick="window.Pages.openAddTicker()">+ 添加股票</button>
          <button class="btn small secondary" onclick="window.Pages.runNow()">⏰ 立即跑一次</button>
          <button class="btn small secondary" onclick="window.Router.go('/ask')">💬 问 Hermes</button>
        </div>
      </div>
    </div>
  `;
};

window.Pages.openAddTicker = function () {
  window.Router.go("/watchlist");
  setTimeout(() => {
    const btn = document.getElementById("btn-add-ticker");
    if (btn) btn.click();
  }, 100);
};

window.Pages.runNow = async function () {
  if (!confirm("立即按当前关注列表跑一次？")) return;
  try {
    const r = await window.API.runNow();
    alert(`已触发：${r.runId}\nTickers: ${r.tickers.join(", ")}\n\n到「任务」页看进度。`);
    window.Router.go("/jobs");
  } catch (e) {
    alert("触发失败：" + e.message);
  }
};
