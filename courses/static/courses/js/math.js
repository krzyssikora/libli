(function () {
  "use strict";
  function renderMath(root) {
    if (typeof katex === "undefined") return;
    (root || document).querySelectorAll("[data-katex]").forEach(function (el) {
      if (el.dataset.katexDone === "1") return;  // idempotent: skip already-rendered
      try {
        katex.render(el.textContent, el, { displayMode: true, throwOnError: false });
        el.dataset.katexDone = "1";
      } catch (e) {
        /* leave raw LaTeX on error */
      }
    });
  }
  window.libliRenderMath = renderMath;  // swap handler calls window.libliRenderMath(subtree)
  renderMath(document);  // initial whole-document pass (1a lesson page behaviour preserved)
})();
