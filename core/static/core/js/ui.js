"use strict";
(function () {
  var THEMES = ["light", "dark", "auto"];
  var COOKIE = "libli_theme";
  var el = document.documentElement;

  function getCookie(name) {
    var m = document.cookie.match("(?:^|; )" + name + "=([^;]+)");
    return m ? decodeURIComponent(m[1]) : null;
  }
  function setCookie(name, value) {
    var secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = name + "=" + value + "; Path=/; Max-Age=31536000" +
      "; SameSite=Lax" + secure;
  }
  function effective(pref) {
    if (pref === "auto") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark" : "light";
    }
    return pref;
  }

  // Theme toggle: cycle pref, update DOM + cookie now; persist if authenticated.
  var toggle = document.querySelector("[data-theme-toggle]");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var cur = el.getAttribute("data-theme-pref") || "auto";
      var next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
      el.setAttribute("data-theme-pref", next);
      el.setAttribute("data-theme", effective(next));
      setCookie(COOKIE, next);
      if (el.getAttribute("data-authenticated") === "1") {
        var body = new URLSearchParams({ theme: next });
        fetch("/ui/set-theme/", {
          method: "POST", headers: { "X-CSRFToken": getCookie("csrftoken") },
          body: body, credentials: "same-origin",
        });
      }
    });
  }

  // Account menu: open/close with outside-click + Escape.
  var menu = document.querySelector("[data-account-menu]");
  if (menu) {
    var trigger = menu.querySelector("[data-menu-trigger]");
    var panel = menu.querySelector("[data-menu-panel]");
    function close() {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }
    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = panel.hidden;
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target)) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }
})();
