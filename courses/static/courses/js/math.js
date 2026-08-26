(function () {
  "use strict";
  function renderOne(el) {
    if (el.dataset.katexDone === "1") return;  // idempotent: skip already-rendered
    try {
      katex.render(el.textContent, el, {
        displayMode: true,
        throwOnError: false,
        // \htmlClass is the ONLY trusted command, matched by EQUALITY, and its
        // class VALUE is bounded as well. \htmlStyle and \htmlData would let
        // authored LaTeX inject arbitrary CSS and data attributes; \href and \url
        // arbitrary URLs. A prefix test would admit all of them.
        //
        // The value check closes the second axis. KaTeX hands the class over in
        // the SAME context object ({command: "\\htmlClass", class: ...}), so a
        // command-only predicate lets authored LaTeX put any class the stylesheet
        // already defines into the top-level lesson DOM -- a full-viewport
        // `position: fixed; inset: 0` overlay, or a .visually-hidden-shaped class
        // that conceals content. No script, no URL and no HTML injection (the
        // value reaches the DOM as className on a node KaTeX builds), so the
        // ceiling is visual -- but the mk-* highlight vocabulary is the whole
        // requirement, so nothing else needs to get through.
        // Deliberately NOT added to renderInlineText below: that path covers
        // author prose in .el--text and every other element, and does not need it.
        trust: function (c) { return c.command === "\\htmlClass" && /^mk mk-[a-z]+$/.test(c.class); },
      });
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
  var INLINE_DELIMS = [
    { left: "\\(", right: "\\)", display: false },
    { left: "\\[", right: "\\]", display: true },
  ];
  function renderInlineText(root) {
    // Inline \(...\) math typed into a text element's PROSE, and into a node
    // TITLE ([data-math-title], added by the read-only display sites). Question
    // stems and choices are typeset by question.js/quiz.js, and math elements
    // use the [data-katex] path above; text elements, fill-gate stems and
    // titles are covered here. No-op if auto-render.min.js wasn't loaded.
    if (typeof window.renderMathInElement !== "function") return;
    (root || document).querySelectorAll(".el--text, .el--table, .el--gallery, .el--tabs, .fillgate, .stepper, .markdone, .guessnumber, .spoiler__toggle, .callout__heading, [data-math-title]").forEach(function (el) {
      var text = el.textContent;
      if (text.indexOf("\\(") === -1 && text.indexOf("\\[") === -1) return;
      try {
        window.renderMathInElement(el, {
          delimiters: INLINE_DELIMS,
          throwOnError: false,
        });
      } catch (e) {
        /* leave raw LaTeX on error */
      }
    });
  }
  window.libliRenderMath = renderMath;  // swap handler calls window.libliRenderMath(subtree)
  renderMath(document);  // initial whole-document pass (1a lesson page behaviour preserved)
  renderInlineText(document);  // inline prose math in text elements
})();
