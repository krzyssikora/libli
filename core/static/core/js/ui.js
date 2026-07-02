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
        fetch(toggle.getAttribute("data-set-theme-url"), {
          method: "POST", headers: { "X-CSRFToken": getCookie("csrftoken") },
          body: body, credentials: "same-origin",
        }).catch(function () {});
      }
    });
  }

  // Dropdown menus (account, admin): open/close with outside-click + Escape.
  // Opening one closes the others. Each .menu owns a trigger + panel pair.
  var menus = [].slice.call(document.querySelectorAll(".menu"));
  function closeMenu(m) {
    var p = m.querySelector("[data-menu-panel]");
    var t = m.querySelector("[data-menu-trigger]");
    if (p) p.hidden = true;
    if (t) t.setAttribute("aria-expanded", "false");
  }
  menus.forEach(function (menu) {
    var trigger = menu.querySelector("[data-menu-trigger]");
    var panel = menu.querySelector("[data-menu-panel]");
    if (!trigger || !panel) return;
    trigger.addEventListener("click", function (e) {
      // Anchor triggers (the notifications bell) navigate via href with no JS.
      // With JS, a plain primary click toggles the panel instead — but let
      // modified clicks (ctrl/cmd/shift or non-primary button) through so
      // "open in new tab" on the underlying href still works.
      if (trigger.tagName === "A") {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
      }
      e.stopPropagation();
      var open = panel.hidden;
      menus.forEach(function (other) { if (other !== menu) closeMenu(other); });
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target)) closeMenu(menu);
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") menus.forEach(closeMenu);
  });

  // Notification bell rows: mark-read on click without blocking navigation.
  // Fire-and-forget POST (keepalive survives the unload); the <a href> still
  // navigates. redirect:"manual" stops at mark_read's 302 so the fetch doesn't
  // follow it into a wasted list render. Same CSRF idiom as the theme toggle.
  document.addEventListener("click", function (e) {
    var row = e.target.closest(".notif-menu__row[data-mark-read-url]");
    if (!row) return;
    fetch(row.getAttribute("data-mark-read-url"), {
      method: "POST",
      headers: { "X-CSRFToken": getCookie("csrftoken") },
      credentials: "same-origin",
      keepalive: true,
      redirect: "manual",
    }).catch(function () {});
  });

  // Primary nav: on mobile the hamburger toggles the dropdown (outside-click + Escape).
  var navToggle = document.querySelector("[data-nav-toggle]");
  var navPanel = document.querySelector("[data-nav-panel]");
  if (navToggle && navPanel) {
    var closeNav = function () {
      navPanel.removeAttribute("data-open");
      navToggle.setAttribute("aria-expanded", "false");
    };
    navToggle.addEventListener("click", function (e) {
      e.stopPropagation();
      if (navPanel.hasAttribute("data-open")) {
        closeNav();
      } else {
        navPanel.setAttribute("data-open", "");
        navToggle.setAttribute("aria-expanded", "true");
      }
    });
    document.addEventListener("click", function (e) {
      if (!navPanel.contains(e.target) && !navToggle.contains(e.target)) closeNav();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeNav();
    });
  }
})();
