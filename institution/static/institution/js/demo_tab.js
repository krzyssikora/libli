// PR 3 spec §4.2 / §4.4. Loaded with `defer` by _demo_tab.html.
(function () {
  "use strict";

  // Submit-once for Create (a ~40 s request) and for each row's Extend (two POSTs
  // would extend twice). The buttons carry no `name`, so disabling them inside the
  // handler drops nothing from the POST. Revoke is NOT disabled: its confirm
  // dialog already stops a double click, and a button disabled here would stay
  // dead after a cancelled confirm.
  function disableOnSubmit(selector) {
    document.querySelectorAll(selector).forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (event.defaultPrevented) return;
        var button = form.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        button.setAttribute("data-demo-disabled", "");
      });
    });
  }

  disableOnSubmit("form[data-demo-create]");
  disableOnSubmit("form[data-demo-extend]");

  window.addEventListener("pageshow", function (event) {
    // A Back navigation restored from bfcache must not leave dead buttons.
    document.querySelectorAll("[data-demo-disabled]").forEach(function (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.removeAttribute("data-demo-disabled");
    });
    // `no-store` only discourages bfcache (Chrome restores such pages when no
    // cookie changed), so a restored page drops its credential cards.
    if (event.persisted) {
      document.querySelectorAll("[data-demo-card]").forEach(function (card) {
        card.remove();
      });
    }
  });
})();
