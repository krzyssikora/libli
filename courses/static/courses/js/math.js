(function () {
  "use strict";
  if (typeof katex === "undefined") return;
  document.querySelectorAll("[data-katex]").forEach(function (el) {
    try {
      katex.render(el.textContent, el, { displayMode: true, throwOnError: false });
    } catch (e) {
      /* leave raw LaTeX on error */
    }
  });
})();
