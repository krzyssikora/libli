(function () {
  "use strict";

  // The unit page's "Start fresh" control renders INACTIVE (no href, aria-disabled)
  // until this viewer has stored practice state. The four state writers announce a
  // STORED save with `libli:state-saved`; this flips the control live. One-way by
  // design (spec 2026-10-15 D6): a save that empties state never re-disables it.
  // The data-reset-* hooks stay on purpose: they make this idempotent.
  document.addEventListener("libli:state-saved", function () {
    document
      .querySelectorAll('[data-reset-control][aria-disabled="true"]')
      .forEach(function (a) {
        a.setAttribute("href", a.getAttribute("data-reset-href"));
        a.removeAttribute("aria-disabled");
        a.removeAttribute("role");
        a.removeAttribute("title");
      });
  });
})();
