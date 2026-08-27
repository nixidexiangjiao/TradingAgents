// ===== 页面 3：任务中心 =====
// ⚠️ 内部函数不要用通用名（render），会被 ask.js 覆盖。
window.Pages.jobs = async function () {
  const root = document.getElementById("page-root");
  root.innerHTML = `<div class="empty"><div class="emoji">⏳</div>加载中…</div>`;
  try {
    await window.API.refreshAll();
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="emoji">⚠️</div>无法连接后端<br><div class="hint">${e.message}</div></div>`;
    return;
  }
  renderJobs();
};

function renderJobs() {
  const root = document.getElementById("page-root");
  const jobs = window.API.STATE.jobs;
  root.innerHTML = `
    <div class="page">
      <h1 class="page-title">任务中心</h1>
      <p class="page-sub">ta-scheduler + TradingAgents CLI</p>

      <button class="btn mb-8" id="btn-run-now">▶ 立即跑整个 watchlist</button>

      <div class="card">
        <div class="card-title mb-8">定时任务（点行内按钮立刻跑 / 看日志）</div>
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
              <span class="pill ${j.lastStatus === 'success' ? 'green' : j.lastStatus === 'failed' ? 'red' : j.lastStatus === 'running' ? 'yellow' : j.lastStatus === 'unknown' ? 'yellow' : 'yellow'}" style="margin-left:8px;">${j.lastStatus === 'success' ? '成功' : j.lastStatus === 'failed' ? '失败' : j.lastStatus === 'running' ? '运行中' : j.lastStatus === 'unknown' ? '未知' : '未运行'}</span>
            </div>
            <div class="row" style="gap:6px;">
              <span class="pill">cron: ${j.cronId}</span>
              <div class="spacer"></div>
              <button class="btn small" data-run-job="${j.id}" data-run-name="${j.name}">▶ 立刻跑</button>
              <button class="btn small secondary" data-logs-job="${j.id}" data-logs-name="${j.name}">📋 日志</button>
            </div>
          </div>
        `).join("")}
      </div>

      <div class="card">
        <div class="card-title mb-8">最近 5 份分析报告（来自 results/batch_*.json）</div>
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
          • 调度由 ta-scheduler 负责（独立 Python 进程，跟 hermes 无关）<br>
          • 立刻跑 → 直接调 run_batch.py，同步等结果（10+ 分钟）<br>
          • 「📋 日志」显示状态（pending/completed/failed）+ 最近一次错误
        </div>
      </div>
    </div>
  `;

  document.getElementById("btn-run-now").addEventListener("click", runNowAndMonitor);

  // 每行的 ▶ 立刻跑 按钮
  document.querySelectorAll("[data-run-job]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const jobId = btn.dataset.runJob;
      const name = btn.dataset.runName;
      runSpecificJob(jobId, name);
    });
  });

  // 每行的 📜 看完整日志 按钮
  document.querySelectorAll("[data-load-full-log]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const runId = btn.dataset.loadFullLog;
      openFullLogSheet(runId);
    });
  });

  // 每行的 📋 日志 按钮
  document.querySelectorAll("[data-logs-job]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const jobId = btn.dataset.logsJob;
      const name = btn.dataset.logsName;
      openLogsSheet(jobId, name);
    });
  });
}

// ===== 立刻跑指定 job =====
async function runSpecificJob(jobId, name) {
  if (!confirm(`立刻跑 "${name}"？\n\n后台调 run_batch.py（10+ 分钟），同步等结果。\n跑完会自动更新状态到「📋 日志」。`)) return;
  try {
    const r = await fetch("/api/jobs/run/" + encodeURIComponent(jobId), { method: "POST" });
    const data = await r.json();
    // ta-scheduler trigger 路径：同步等结果（10+ 分钟），完成后 state.db 写入状态
    if (data.ok) {
      alert(`已跑完：${name}\n\n退出码 ${data.returncode}\n${(data.stdout || '').slice(-200)}`);
    } else if (data.stderr && (data.stderr.includes("timeout") || data.stderr.includes("Timed out"))) {
      alert(`ta-scheduler trigger 超时（但任务在后台跑）：${name}\n\n去「📋 日志」看进度。`);
    } else {
      alert(`跑失败：${name}\n${JSON.stringify(data, null, 2).slice(0, 500)}`);
    }
  } catch (e) {
    alert("触发失败：" + e.message);
  }
}

// ===== 日志弹层 =====
async function openLogsSheet(jobId, name) {
  const overlay = document.createElement("div");
  overlay.className = "sheet-overlay open";
  overlay.innerHTML = `
    <div class="sheet" onclick="event.stopPropagation()" style="max-height: 85vh;">
      <h2>📋 日志 · ${name}</h2>
      <p class="muted small" style="margin-top:-8px;">cron job_id: ${jobId}</p>
      <div id="logs-list" class="muted small">加载中…</div>
      <button class="btn secondary" style="margin-top:12px;" onclick="this.closest('.sheet-overlay').remove()">关闭</button>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

  const list = overlay.querySelector("#logs-list");
  try {
    const r = await fetch("/api/jobs/" + encodeURIComponent(jobId) + "/logs?limit=5");
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    const runs = data.runs || [];
    if (runs.length === 0) {
      list.innerHTML = '<div class="empty"><div class="emoji">📭</div>暂无执行历史<br><div class="hint">点「▶ 立刻跑」或等定时任务触发</div></div>';
      return;
    }
    const statusPill = (s) => {
      if (s === 'completed') return '<span class="pill green">完成</span>';
      if (s === 'failed') return '<span class="pill red">失败</span>';
      if (s === 'running') return '<span class="pill yellow">运行中</span>';
      if (s === 'unknown') return '<span class="pill yellow">未知</span>';
      return `<span class="pill">${escapeHtml(s)}</span>`;
    };
    list.innerHTML = runs.map((run, idx) => {
      const isFailed = run.status === 'failed';
      const hasError = run.error && run.error.trim();
      const detailsId = `log-details-${idx}-${Math.random().toString(36).slice(2, 8)}`;
      return `
      <div style="margin-bottom:8px; padding:10px; background: var(--bg-elev); border-radius: 6px;">
        <div class="row" style="margin-bottom:4px;">
          <strong style="font-size:13px;">${run.ts}</strong>
          ${statusPill(run.status)}
          <div class="spacer"></div>
          <span class="muted tiny">${run.source}</span>
        </div>
        <div class="muted tiny">execution_id: ${escapeHtml(run.execution_id)}${run.duration_s ? ' · 用时 ' + run.duration_s.toFixed(1) + 's' : ''}${run.exit_code != null ? ' · exit=' + run.exit_code : ''}</div>
        <div style="margin-top:6px;">
          <button class="btn small secondary btn-load-full-log" data-load-full-log="${escapeHtml(run.execution_id)}" style="font-size:12px; padding:4px 10px;">
            📜 看完整日志
          </button>
        </div>
        ${hasError ? `
        <details id="${detailsId}" style="margin-top:8px;">
          <summary style="cursor:pointer; padding:4px 8px; background: var(--bg); border-radius: 4px; color: var(--red); font-size:12px;">
            ⚠️ 失败摘要（点击展开）
          </summary>
          <pre style="background: var(--bg); padding:8px; border-radius: 4px; font-size: 11px; white-space: pre-wrap; word-wrap: break-word; margin-top:6px; max-height: 200px; overflow:auto; font-family: ui-monospace, Menlo, monospace;">${escapeHtml(run.error)}</pre>
        </details>
        ` : ''}
      </div>
    `;
    }).join("");

    // 弹层渲染后，给 📜 按钮单独绑事件（不能用 forEach on document.querySelectorAll，否则弹层外也算）
    list.querySelectorAll(".btn-load-full-log").forEach((btn) => {
      btn.addEventListener("click", () => {
        const runId = btn.dataset.loadFullLog;
        openFullLogSheet(runId);
      });
    });
    // 顶部加说明
    const note = document.createElement("div");
    note.className = "muted small";
    note.style.marginBottom = "10px";
    note.innerHTML = "💡 完整 stdout 写入 ta-scheduler 的 logs/scheduler.log。失败原因显示在卡片下方。";
    list.prepend(note);
  } catch (e) {
    list.innerHTML = `<div class="muted">加载失败：${e.message}</div>`;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}


// ===== 看完整日志弹层（从 /api/runs/<id>/log 拿完整 stdout）=====
async function openFullLogSheet(runId) {
  const overlay = document.createElement("div");
  overlay.className = "sheet-overlay open";
  overlay.innerHTML = `
    <div class="sheet" onclick="event.stopPropagation()" style="max-height: 90vh;">
      <h2>📜 完整日志 · ${runId}</h2>
      <p class="muted small" style="margin-top:-8px;">从 ta-scheduler/logs/runs/<run_id>.log 读取</p>
      <div id="full-log" class="muted small" style="max-height: 70vh; overflow:auto; background: var(--bg); padding:12px; border-radius: 6px; font-family: ui-monospace, Menlo, monospace; font-size: 11px; white-space: pre-wrap; word-wrap: break-word;">加载中…</div>
      <button class="btn secondary" style="margin-top:12px;" onclick="this.closest('.sheet-overlay').remove()">关闭</button>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });

  const logDiv = overlay.querySelector("#full-log");
  try {
    const r = await fetch("/api/runs/" + encodeURIComponent(runId) + "/log?full=true");
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    const text = data.content || "(empty)";
    logDiv.textContent = text.length > 50000
      ? text.slice(0, 50000) + "\n\n... (截断到 50000 字符，完整日志在服务器文件里) ..."
      : text;
  } catch (e) {
    logDiv.textContent = "❌ 加载失败：" + e.message;
  }
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
          renderJobs();
          return;
        }
      } catch (e) { /* 忽略单次失败 */ }
    }
    alert("已超时（>3 分钟），请到任务日志看实际进度");
  } catch (e) {
    alert("触发失败：" + e.message);
  }
}
