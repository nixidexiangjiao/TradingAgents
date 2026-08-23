// ===== 页面 5：Hermes 桥 =====
window.Pages.ask = function () {
  const root = document.getElementById("page-root");
  // chatHistory 仍存 window.Pages.ask 局部 state（不是 server 持久）
  if (!window.Pages._chatHistory) window.Pages._chatHistory = [];
  if (window.Pages._chatHistory.length === 0) {
    // 第一次进来给个示例对话
    window.Pages._chatHistory = [
      { role: "user", text: "BABA 现在 PE 多少？" },
      { role: "bot", text: "（试着问我：BABA PE / 0700.HK 报告 / 对比阿里腾讯 / cron 状态）" },
    ];
  }
  render();
};

function render() {
  const root = document.getElementById("page-root");
  const history = window.Pages._chatHistory || [];
  const suggestions = [
    "BABA 现在 PE 多少？",
    "0700.HK 跟 BABA 谁更便宜",
    "今天 cron 跑成功了吗？",
    "对比阿里腾讯的最近报告",
  ];
  root.innerHTML = `
    <div class="page">
      <h1 class="page-title">问 Hermes</h1>
      <p class="page-sub">自然语言查询 TradingAgents 跑过的数据</p>

      <div id="chat-list" class="mb-8">
        ${history.map(renderMsg).join("")}
      </div>

      <div class="chat-suggestions mb-8" id="chat-suggestions">
        ${suggestions.map((s) => `<span class="chip">${s}</span>`).join("")}
      </div>

      <div class="form-row" style="display:flex; gap:6px; position:sticky; bottom: 0; background: var(--bg); padding: 8px 0 4px;">
        <input class="form-input" id="chat-input" placeholder="例如：BABA 现在 PE 多少？" />
        <button class="btn small" id="chat-send" style="width:auto; padding: 0 18px;">发送</button>
      </div>

      <div class="card mt-16">
        <div class="card-title mb-8">数据源覆盖</div>
        <div class="muted small">
          ✅ watchlist 实时快照（yfinance）<br>
          ✅ 最近 batch_*.json 报告<br>
          ✅ cron 状态<br>
          ⏳ 飞书消息历史<br>
          ⏳ 自然语言 → 数据查询（PoC: 关键词路由）
        </div>
      </div>
    </div>
  `;
  bind();
}

function renderMsg(m) {
  const src = m.sources && m.sources.length ? `<div class="muted tiny mt-8">来源: ${m.sources.join(", ")}</div>` : '';
  return `<div class="chat-msg ${m.role}"><div class="bubble">${escapeHtml(m.text)}${src ? '<hr style="border:0;border-top:1px dashed var(--border);margin:6px 0;">' + src : ''}</div></div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function bind() {
  const input = document.getElementById("chat-input");
  const send = document.getElementById("chat-send");
  const list = document.getElementById("chat-list");

  const submit = async () => {
    const text = input.value.trim();
    if (!text) return;
    window.Pages._chatHistory.push({ role: "user", text });
    list.insertAdjacentHTML("beforeend", renderMsg({ role: "user", text }));
    input.value = "";
    list.scrollTop = list.scrollHeight;

    try {
      const r = await window.API.ask(text);
      const bot = { role: "bot", text: r.answer, sources: r.sources };
      window.Pages._chatHistory.push(bot);
      list.insertAdjacentHTML("beforeend", renderMsg(bot));
      list.scrollTop = list.scrollHeight;
    } catch (e) {
      const bot = { role: "bot", text: "❌ " + e.message };
      window.Pages._chatHistory.push(bot);
      list.insertAdjacentHTML("beforeend", renderMsg(bot));
    }
  };

  send.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  document.querySelectorAll("#chat-suggestions .chip").forEach((c) => {
    c.addEventListener("click", () => { input.value = c.textContent; submit(); });
  });
}
