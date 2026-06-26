(function () {
  "use strict";

  function gutterOf(field) {
    return field.querySelector(".code-field__gutter");
  }
  function textareaOf(field) {
    return field.querySelector(".code-field__area textarea");
  }

  // Render line numbers 1..N (N = logical lines, min 1) and keep the gutter's
  // vertical scroll aligned with the textarea after the content changes.
  function renderGutter(ta, gutter) {
    var lines = ta.value.split("\n").length || 1;
    var out = "1";
    for (var i = 2; i <= lines; i++) out += "\n" + i;
    gutter.textContent = out;
    gutter.scrollTop = ta.scrollTop;
  }

  function enhance(field) {
    if (field.dataset.codeFieldReady) return;
    var ta = textareaOf(field);
    var gutter = gutterOf(field);
    if (!ta || !gutter) return;
    field.dataset.codeFieldReady = "1";
    renderGutter(ta, gutter);
  }

  function enhanceAll(root) {
    var fields = (root || document).querySelectorAll("[data-code-field]");
    for (var i = 0; i < fields.length; i++) enhance(fields[i]);
  }

  function fieldFor(node) {
    return node && node.closest ? node.closest("[data-code-field]") : null;
  }

  // Delegated input → re-render that field's gutter.
  document.addEventListener("input", function (e) {
    if (!e.target || e.target.tagName !== "TEXTAREA") return;
    var field = fieldFor(e.target);
    if (field) renderGutter(e.target, gutterOf(field));
  });

  // Delegated scroll (capture: scroll does not bubble) → sync the gutter offset.
  document.addEventListener(
    "scroll",
    function (e) {
      if (!e.target || e.target.tagName !== "TEXTAREA") return;
      var field = fieldFor(e.target);
      if (field) gutterOf(field).scrollTop = e.target.scrollTop;
    },
    true
  );

  // Delegated Tab → indent; Shift-Tab → outdent (two spaces). Never move focus,
  // and NEVER delete a selection: a selected block is indented line-by-line, not
  // replaced. (Direct value mutation does not integrate with native undo — see the
  // documented-limitation note below the module.)
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Tab" || !e.target || e.target.tagName !== "TEXTAREA") return;
    var field = fieldFor(e.target);
    if (!field) return;
    e.preventDefault();
    var ta = e.target;
    var start = ta.selectionStart;
    var end = ta.selectionEnd;
    var val = ta.value;
    var TAB = "  ";
    if (start === end) {
      // Collapsed caret.
      if (e.shiftKey) {
        // Outdent: remove up to two leading spaces from the caret's line.
        var ls = val.lastIndexOf("\n", start - 1) + 1;
        var rm = 0;
        while (rm < 2 && val.charAt(ls + rm) === " ") rm++;
        if (rm) {
          ta.value = val.slice(0, ls) + val.slice(ls + rm);
          ta.selectionStart = ta.selectionEnd = Math.max(ls, start - rm);
        }
      } else {
        // Insert two spaces at the caret.
        ta.value = val.slice(0, start) + TAB + val.slice(start);
        ta.selectionStart = ta.selectionEnd = start + TAB.length;
      }
    } else {
      // Non-empty selection: (out)indent every line it touches; never delete it.
      var blockStart = val.lastIndexOf("\n", start - 1) + 1;
      // If the selection ends exactly at a line start, don't pull in that line.
      var blockEnd = val.charAt(end - 1) === "\n" ? end - 1 : end;
      var lines = val.slice(blockStart, blockEnd).split("\n");
      var firstDelta = 0;
      var totalDelta = 0;
      for (var i = 0; i < lines.length; i++) {
        if (e.shiftKey) {
          var r = 0;
          while (r < 2 && lines[i].charAt(r) === " ") r++;
          lines[i] = lines[i].slice(r);
          if (i === 0) firstDelta -= r;
          totalDelta -= r;
        } else {
          lines[i] = TAB + lines[i];
          if (i === 0) firstDelta += TAB.length;
          totalDelta += TAB.length;
        }
      }
      ta.value = val.slice(0, blockStart) + lines.join("\n") + val.slice(blockEnd);
      ta.selectionStart = Math.max(blockStart, start + firstDelta);
      ta.selectionEnd = end + totalDelta;
    }
    renderGutter(ta, gutterOf(field));
  });

  function init() {
    enhanceAll(document);
    if (typeof MutationObserver === "function") {
      var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var added = muts[i].addedNodes;
          for (var j = 0; j < added.length; j++) {
            var n = added[j];
            if (n.nodeType !== 1) continue;
            if (n.matches && n.matches("[data-code-field]")) enhance(n);
            if (n.querySelectorAll) enhanceAll(n);
          }
        }
      });
      mo.observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
