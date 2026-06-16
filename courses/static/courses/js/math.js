(function () {
  "use strict";
  function renderOne(el) {
    if (el.dataset.katexDone === "1") return;  // idempotent: skip already-rendered
    try {
      katex.render(el.textContent, el, { displayMode: true, throwOnError: false });
      el.dataset.katexDone = "1";
    } catch (e) {
      /* leave raw LaTeX on error */
    }
  }
  function renderMath(root) {
    if (typeof katex === "undefined") return;
    var scope = root || document;
    // querySelectorAll matches DESCENDANTS only — when a caller passes the math
    // target element itself (e.g. the [data-math-live][data-katex] live preview),
    // render it directly too.
    if (scope.matches && scope.matches("[data-katex]")) renderOne(scope);
    scope.querySelectorAll("[data-katex]").forEach(renderOne);
  }
  window.libliRenderMath = renderMath;  // swap handler calls window.libliRenderMath(subtree)
  renderMath(document);  // initial whole-document pass (1a lesson page behaviour preserved)
})();
