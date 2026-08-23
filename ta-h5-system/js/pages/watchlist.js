// ===== 页面 2：关注列表 =====
window.Pages.watchlist = async function () {
  const root = document.getElementById("page-root");
  root.innerHTML = `<div class="empty"><div class="emoji">⏳</div>加载中…</div>`;
  try {
    await window.API.refreshAll();
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="emoji">⚠️</div>无法连接后端<br><div class="hint">${e.message}</div></div>`;
    return;
  }

  renderList();
};

function renderList() {
  const root = document.getElementById("page-root");
  const items = window.API.STATE.watchlist;
  const snapshots = window.API.STATE.snapshots;
  root.innerHTML = `
    <div class="page">
      <h1 class="page-title">关注列表</h1>
      <p class="page-sub">${items.length} 只股票，${items.filter(w=>w.enabled).length} 个启用中</p>

      <button id="btn-add-ticker" class="btn mb-8">+ 添加股票</button>

      <div id="watchlist-list">
        ${items.map((w) => renderItem(w, snapshots[w.symbol])).join("")}
      </div>

      <div class="card mt-16">
        <div class="card-title mb-8">提示</div>
        <div class="muted small">
          • 新增的股票会在下一个定时任务周期被自动分析<br>
          • 暂停（关闭）后保留历史，但不再触发新报告<br>
          • 港股代码以 .HK 结尾，美股直接用 ticker
        </div>
      </div>
    </div>
  `;
  document.getElementById("btn-add-ticker").addEventListener("click", () => openSheet());
  document.querySelectorAll("[data-action]").forEach((el) => {
    el.addEventListener("click", (e) => {
      const id = el.dataset.id;
      const action = el.dataset.action;
      if (action === "edit") openSheet(id);
      else if (action === "delete") delItem(id);
      else if (action === "toggle") toggleItem(id);
    });
  });
}

function renderItem(w, snap) {
  const chgClass = snap && snap.chgPct != null ? (snap.chgPct > 0 ? "up" : snap.chgPct < 0 ? "down" : "flat") : "flat";
  return `
    <div class="list-item">
      <span style="font-size:22px;">${w.icon || "📊"}</span>
      <div class="main">
        <div class="title">${w.symbol} <span class="pill ${w.market === 'HK' ? 'blue' : w.market === 'US' ? 'yellow' : ''}">${w.market}</span></div>
        <div class="sub">${w.name}</div>
        ${snap && snap.price ? `<div class="muted small mt-8">${snap.price} <span class="${chgClass}">${snap.chgPct > 0 ? '+' : ''}${snap.chgPct}%</span>${snap.error ? ' ⚠️ ' + snap.error : ''}</div>` : ''}
      </div>
      <div class="right" style="display:flex; flex-direction:column; align-items:flex-end; gap:4px;">
        <button class="icon-btn" data-action="toggle" data-id="${w.id}" title="${w.enabled ? '暂停' : '启用'}">${w.enabled ? '🟢' : '⏸️'}</button>
        <button class="icon-btn" data-action="edit" data-id="${w.id}">✏️</button>
        <button class="icon-btn" data-action="delete" data-id="${w.id}">🗑️</button>
      </div>
    </div>
  `;
}

async function toggleItem(id) {
  const w = window.API.STATE.watchlist.find((x) => x.id === id);
  if (!w) return;
  try {
    await window.API.updateWatchItem(id, { ...w, enabled: !w.enabled });
    renderList();
  } catch (e) { alert("更新失败：" + e.message); }
}

async function delItem(id) {
  if (!confirm("确定删除？历史报告不会受影响。")) return;
  try {
    await window.API.deleteWatchItem(id);
    renderList();
  } catch (e) { alert("删除失败：" + e.message); }
}

function openSheet(editId) {
  const editing = editId ? window.API.STATE.watchlist.find((x) => x.id === editId) : null;
  const overlay = document.createElement("div");
  overlay.className = "sheet-overlay open";
  overlay.innerHTML = `
    <div class="sheet" onclick="event.stopPropagation()">
      <h2>${editing ? "编辑" : "添加"}股票</h2>
      <div class="form-row">
        <label class="form-label">代码（如 0700.HK / BABA / 600519.SH）</label>
        <input class="form-input" id="f-symbol" value="${editing?.symbol || ''}" placeholder="0700.HK" autocapitalize="characters" />
      </div>
      <div class="form-row">
        <label class="form-label">名称</label>
        <input class="form-input" id="f-name" value="${editing?.name || ''}" placeholder="腾讯控股" />
      </div>
      <div class="form-row">
        <label class="form-label">市场</label>
        <select class="form-select" id="f-market">
          <option value="HK" ${editing?.market === 'HK' ? 'selected' : ''}>港股（.HK）</option>
          <option value="US" ${editing?.market === 'US' ? 'selected' : ''}>美股</option>
          <option value="CN" ${editing?.market === 'CN' ? 'selected' : ''}>A 股（.SH / .SZ）</option>
          <option value="CRYPTO" ${editing?.market === 'CRYPTO' ? 'selected' : ''}>加密币</option>
        </select>
      </div>
      <div class="form-row">
        <label class="form-label">图标（emoji，可选）</label>
        <input class="form-input" id="f-icon" value="${editing?.icon || '📊'}" maxlength="2" />
      </div>
      <div class="form-row">
        <label class="form-label">备注</label>
        <textarea class="form-textarea" id="f-notes" placeholder="为什么关注这只？">${editing?.notes || ''}</textarea>
      </div>
      <div class="form-row">
        <label class="form-label">
          <input type="checkbox" id="f-enabled" ${editing ? (editing.enabled ? 'checked' : '') : 'checked'} />
          立即启用（加入下一个 cron 周期）
        </label>
      </div>
      <div class="row" style="gap:8px; margin-top:16px;">
        <button class="btn secondary" id="f-cancel">取消</button>
        <div class="spacer"></div>
        <button class="btn" id="f-save">保存</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  document.getElementById("f-cancel").addEventListener("click", close);
  document.getElementById("f-save").addEventListener("click", async () => {
    const symbol = document.getElementById("f-symbol").value.trim().toUpperCase();
    if (!symbol) { alert("请输入代码"); return; }
    const data = {
      symbol,
      name: document.getElementById("f-name").value.trim() || symbol,
      market: document.getElementById("f-market").value,
      icon: document.getElementById("f-icon").value.trim() || "📊",
      notes: document.getElementById("f-notes").value.trim(),
      enabled: document.getElementById("f-enabled").checked,
    };
    try {
      if (editing) await window.API.updateWatchItem(editing.id, data);
      else await window.API.createWatchItem(data);
      close();
      renderList();
    } catch (e) { alert("保存失败：" + e.message); }
  });
  function close() { overlay.remove(); }
}
