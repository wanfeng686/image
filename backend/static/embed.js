/**
 * SmartSupport Widget Loader
 * 商户在自己网站贴：<script src="https://your-domain/embed.js" data-key="pk_..." async></script>
 * 作用：右下角注入客服气泡按钮 + iframe 聊天窗（iframe 与平台同源，天然无跨域问题）。
 */
(function () {
  "use strict";
  var script = document.currentScript;
  var key = script && script.getAttribute("data-key");
  var origin;
  try {
    origin = new URL(script.src).origin;
  } catch (e) {
    origin = "";
  }
  if (!key || !origin) {
    console.error("[SmartSupport] 需要 data-key 且以完整 URL 引入 embed.js");
    return;
  }

  var COLOR = "#4F46E5";       // 品牌主题色（boot 成功后更新）
  var TITLE = "智能客服";       // 悬浮提示

  var style = document.createElement("style");
  style.textContent = [
    ".ssw-launcher{position:fixed;right:22px;bottom:22px;width:56px;height:56px;border-radius:50%;",
    "background:" + COLOR + ";color:#fff;display:flex;align-items:center;justify-content:center;",
    "font-size:26px;cursor:pointer;box-shadow:0 6px 20px rgba(15,23,42,.28);z-index:99998;",
    "border:none;transition:transform .15s ease;font-family:system-ui,sans-serif}",
    ".ssw-launcher:hover{transform:scale(1.08)}",
    ".ssw-frame{position:fixed;right:22px;bottom:90px;width:384px;height:600px;max-width:calc(100vw - 32px);",
    "max-height:calc(100vh - 130px);border:none;border-radius:16px;box-shadow:0 12px 48px rgba(15,23,42,.30);",
    "z-index:99999;overflow:hidden;background:#fff;display:none}",
    ".ssw-frame.ssw-open{display:block}",
    "@media (max-width:480px){.ssw-frame{right:8px;bottom:86px;width:calc(100vw - 16px);height:calc(100vh - 110px)}}",
  ].join("");
  document.head.appendChild(style);

  var frame = document.createElement("iframe");
  frame.className = "ssw-frame";
  // o = 商户页面 origin，传给 iframe 作为白名单声明（iframe 本身与平台同源）
  var pageOrigin = "";
  try { pageOrigin = window.location.origin; } catch (e) { /* noop */ }
  frame.src = origin + "/widget/?key=" + encodeURIComponent(key)
            + "&embed=1&o=" + encodeURIComponent(pageOrigin);
  frame.setAttribute("title", TITLE);
  frame.allow = "clipboard-write";
  document.body.appendChild(frame);

  var launcher = document.createElement("button");
  launcher.className = "ssw-launcher";
  launcher.setAttribute("aria-label", "打开智能客服");
  launcher.textContent = "💬";
  document.body.appendChild(launcher);

  var open = false;
  function toggle(state) {
    open = typeof state === "boolean" ? state : !open;
    frame.classList.toggle("ssw-open", open);
    launcher.textContent = open ? "✕" : "💬";
    if (open) {
      try { frame.contentWindow.postMessage({ type: "ssw:focus" }, origin); } catch (e) { /* noop */ }
    }
  }
  launcher.addEventListener("click", function () { toggle(); });

  // Widget 内部请求开/关（如"最小化"按钮）；iframe 启动后回传品牌色给本按钮着色
  window.addEventListener("message", function (ev) {
    if (ev.origin !== origin || !ev.data) return;
    if (ev.data.type === "ssw:close") toggle(false);
    if (ev.data.type === "ssw:brand" && ev.data.color) {
      launcher.style.background = ev.data.color;
    }
  });
})();
