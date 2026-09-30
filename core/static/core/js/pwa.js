/* PWA client (spec docs/superpowers/specs/2026-09-29-pwa-c1-installable-app-design.md §6).
   Loaded only when pwa_enabled. Registers /sw.js and drives the account menu's
   "Install app" item ([data-install-app]), which is a plain link to the install
   guide unless the browser hands us an install prompt. */
(function () {
  "use strict";

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .catch(function (err) {
        console.warn("libli: service worker registration failed", err);
      });
  }

  var kept = null; // the single-use beforeinstallprompt event

  function item() {
    return document.querySelector("[data-install-app]");
  }

  function hide() {
    var el = item();
    if (el) el.hidden = true;
  }

  function standalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      navigator.standalone === true;
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    // FIRST and unconditionally: no browser mini-infobar on any page (D3).
    event.preventDefault();
    var el = item();
    if (!el) return;
    kept = event;
    el.setAttribute("data-install-mode", "prompt");
  });

  window.addEventListener("appinstalled", hide);

  document.addEventListener("click", function (event) {
    var el = item();
    if (!el || !kept || !el.contains(event.target)) return;
    event.preventDefault();
    var prompt = kept;
    // Dropped synchronously: the event is single-use, and nothing here awaits
    // prompt()'s promise or userChoice.
    kept = null;
    el.removeAttribute("data-install-mode");
    var p = prompt.prompt();
    if (p && p.catch) p.catch(function () {});
  });

  if (standalone()) hide();
})();
