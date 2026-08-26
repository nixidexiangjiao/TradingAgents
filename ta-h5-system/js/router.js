// ===== 极简 hash 路由 =====
// 路由表：dashboard / watchlist / jobs / report / report/:id / ask
window.Router = (function () {
  const routes = {};

  function on(pattern, handler) {
    // pattern 支持 :param
    const keys = [];
    const regex = new RegExp(
      "^" + pattern.replace(/:[^/]+/g, (m) => { keys.push(m.slice(1)); return "([^/]+)"; }) + "$"
    );
    routes[pattern] = { regex, keys, handler };
    console.log("[router] registered:", pattern, "total routes:", Object.keys(routes).length);
  }

  function resolve() {
    // hash 形如 "#/dashboard" 或 "#/report/r1"，strip 掉前导 #/
    let hash = location.hash.slice(1) || "/dashboard";
    if (hash.startsWith("/")) hash = hash.slice(1);
    if (!hash) hash = "dashboard";
    for (const k in routes) {
      const { regex, keys, handler } = routes[k];
      const m = hash.match(regex);
      if (m) {
        const params = {};
        keys.forEach((key, i) => { params[key] = decodeURIComponent(m[i + 1]); });
        document.querySelectorAll(".tab").forEach((t) => {
          t.classList.toggle("active", t.dataset.route === k.split("/")[0] || (k === "report" && t.dataset.route === "report"));
        });
        try {
          handler(params);
        } catch (err) {
          console.error("[router] handler error:", err);
          document.getElementById("page-root").innerHTML =
            `<div class="empty"><div class="emoji">⚠️</div><div>页面渲染失败</div><div class="hint">${String(err.message || err)}</div></div>`;
        }
        return;
      }
    }
    // fallback
    location.hash = "#/dashboard";
  }

  function go(path) { location.hash = path; }

  window.addEventListener("hashchange", resolve);
  // 路由切换时关闭所有打开的 sheet（避免遮挡下一页面按钮）
  window.addEventListener("hashchange", () => {
    document.querySelectorAll(".sheet-overlay.open").forEach((el) => el.remove());
  });
  return { on, resolve, go };
})();
