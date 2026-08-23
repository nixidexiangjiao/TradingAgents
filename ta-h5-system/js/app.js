// ===== 应用入口：注册路由 + 启动 =====
document.addEventListener("DOMContentLoaded", () => {
  window.Router.on("dashboard", window.Pages.dashboard);
  window.Router.on("watchlist", window.Pages.watchlist);
  window.Router.on("jobs", window.Pages.jobs);
  window.Router.on("report", window.Pages.report);
  window.Router.on("report/:id", window.Pages.reportDetail);
  window.Router.on("ask", window.Pages.ask);

  // 默认进 dashboard
  if (!location.hash) location.hash = "#/dashboard";
  window.Router.resolve();

  // 模拟 status 灯微动效（demo 用）
  setInterval(() => {
    const dot = document.querySelector(".status-dot.live");
    if (!dot) return;
    dot.style.opacity = dot.style.opacity === "0.5" ? "1" : "0.5";
  }, 1200);
});
