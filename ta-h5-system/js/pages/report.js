// ===== 页面 4：报告 =====
window.Pages.report = async function () { await renderList(); };
window.Pages.reportDetail = async function (params) { await renderDetail(params.id); };

async function renderList() {
  const root = document.getElementById("page-root");
  root.innerHTML = `<div class="empty"><div class="emoji">⏳</div>加载中…</div>`;
  try {
    await window.API.refreshAll();
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="emoji">⚠️</div>${e.message}</div>`;
    return;
  }
  const reports = window.API.STATE.reports;
  root.innerHTML = `
    <div class="page">
      <h1 class="page-title">分析报告</h1>
      <p class="page-sub">按日期倒序，最近 ${reports.length} 份</p>
      <div class="chip-row mb-8" id="filter-chips">
        <span class="chip pill blue">全部</span>
        ${[...new Set(reports.map(r => r.ticker).filter(Boolean))].map(s => `<span class="chip pill">${s}</span>`).join("")}
      </div>
      ${reports.length === 0 ? `<div class="empty"><div class="emoji">📑</div>暂无报告<div class="hint">立即跑一次或等定时任务</div></div>` : reports.map((r) => `
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
    </div>
  `;
  document.querySelectorAll("#filter-chips .chip").forEach((c) => {
    c.addEventListener("click", () => {
      document.querySelectorAll("#filter-chips .chip").forEach((x) => x.classList.remove("blue"));
      c.classList.add("blue");
      // 简单过滤：非"全部"则按 ticker 过滤
      const isAll = c.textContent === "全部";
      document.querySelectorAll(".list-item").forEach((item) => {
        const t = item.querySelector(".title")?.textContent || "";
        item.style.display = (isAll || t.includes(c.textContent)) ? "" : "none";
      });
    });
  });
}

async function renderDetail(id) {
  const root = document.getElementById("page-root");
  root.innerHTML = `<div class="empty"><div class="emoji">⏳</div>加载中…</div>`;

  // 解析 id: {date}__{ticker}
  const [date, ticker] = id.split("__");
  let r;
  try {
    r = await window.API.getReport(date, ticker);
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="emoji">⚠️</div>未找到报告<div class="hint">${e.message}</div></div>`;
    return;
  }

  root.innerHTML = `
    <div class="page">
      <a class="card-link" href="#/report" style="display:inline-block; margin-bottom:8px;">← 返回列表</a>
      <h1 class="page-title">${r.ticker} · ${r.date}</h1>
      <p class="page-sub">${r.name} · 用时 ${r.elapsed_s ? Math.round(r.elapsed_s) + 's' : '—'}</p>

      <div class="card">
        <div class="card-row mb-8">
          <span class="signal ${r.signal === 'bull' ? 'bull' : r.signal === 'bear' ? 'bear' : 'neutral'}">
            <span class="dot"></span>
            ${r.label}（${r.decision}）
          </span>
        </div>
        ${r.rating ? `<div class="muted small">Rating: ${r.rating}</div>` : ''}
      </div>

      ${r.summary ? `
      <div class="report-section">
        <h3>📋 Executive Summary</h3>
        <p>${escapeHtml(r.summary)}</p>
      </div>` : ''}

      ${r.thesis ? `
      <div class="report-section" style="border-color: var(--accent);">
        <h3>🎯 Investment Thesis（完整）</h3>
        <pre style="white-space: pre-wrap; word-wrap: break-word; font-family: inherit; font-size: 14px; line-height: 1.6; margin: 0; color: var(--text);">${escapeHtml(r.thesis)}</pre>
      </div>` : ''}

      ${r.error ? `<div class="card" style="border-color: var(--red);"><div class="muted small">⚠️ 错误：${escapeHtml(r.error)}</div></div>` : ''}

      <button class="btn secondary" onclick="alert('导出 PDF（demo）')">📄 导出 PDF</button>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
