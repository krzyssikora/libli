// courses/static/courses/js/math_input.js
(function () {
  "use strict";
  var modal, field, cb;

  function build() {
    modal = document.createElement("div");
    modal.className = "math-modal";
    modal.hidden = true;
    modal.innerHTML =
      '<div class="math-modal__backdrop" data-math-cancel></div>' +
      '<div class="math-modal__card" role="dialog" aria-modal="true">' +
      '  <math-field class="math-modal__field"></math-field>' +
      '  <div class="math-modal__actions">' +
      '    <button type="button" class="btn btn--small" data-math-insert></button>' +
      '    <button type="button" class="btn btn--small btn--ghost" data-math-cancel></button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(modal);
    field = modal.querySelector("math-field");
    // Labels are injected from data-* on the editor root (i18n, set in Task 1 Step 3).
    var root = document.querySelector(".editor");
    modal.querySelector(".math-modal__card").setAttribute(
      "aria-label", (root && root.getAttribute("data-msg-math")) || "Insert math");
    modal.querySelector("[data-math-insert]").textContent =
      (root && root.getAttribute("data-msg-insert")) || "Insert";
    modal.querySelector(".math-modal__actions [data-math-cancel]").textContent =
      (root && root.getAttribute("data-msg-cancel")) || "Cancel";
    modal.addEventListener("click", function (e) {
      if (e.target.closest("[data-math-cancel]")) { close(); return; }
      if (e.target.closest("[data-math-insert]")) {
        var latex = (field.value || "").trim();
        // When MathLive is in 'latex' command mode, .value is "" but the raw
        // characters are accessible via getValue("ascii-math").
        if (!latex && typeof field.getValue === "function") {
          latex = (field.getValue("ascii-math") || "").trim();
        }
        var onInsert = cb;
        close();
        if (latex && onInsert) onInsert(latex);
      }
    });
    document.addEventListener("keydown", function (e) {
      if (!modal.hidden && e.key === "Escape") close();
    });
  }

  function close() { if (modal) { modal.hidden = true; field.value = ""; } cb = null; }

  function open(onInsert) {
    if (!modal) build();
    cb = onInsert;
    field.value = "";
    modal.hidden = false;
    setTimeout(function () { field.focus(); }, 0);
  }

  function fieldOf(trigger) {
    var wrap = trigger.closest("[data-math-field]");
    return wrap ? wrap.querySelector("input, textarea") : null;
  }
  function previewOf(trigger) {
    var wrap = trigger.closest("[data-math-field]");
    return wrap ? wrap.querySelector("[data-math-preview]") : null;
  }
  function insertAtCaret(input, text) {
    var s = input.selectionStart, e = input.selectionEnd;
    if (s == null) { input.value += text; }
    else { input.value = input.value.slice(0, s) + text + input.value.slice(e); var p = s + text.length; input.setSelectionRange(p, p); }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  }
  function renderPreview(input, preview) {
    if (!preview) return;
    preview.textContent = input.value;
    if (typeof renderMathInElement === "function") {
      try { renderMathInElement(preview, { delimiters: [{ left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true }], throwOnError: false }); } catch (e) { /* raw */ }
    }
  }
  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-math-trigger]");
    if (!trigger) return;
    var input = fieldOf(trigger);
    if (!input) return;
    open(function (latex) {
      insertAtCaret(input, "\\(" + latex + "\\)");
      renderPreview(input, previewOf(trigger));
    });
  });
  document.addEventListener("input", function (e) {
    var wrap = e.target.closest && e.target.closest("[data-math-field]");
    if (!wrap) return;
    renderPreview(e.target, wrap.querySelector("[data-math-preview]"));
  });

  window.libliMathInput = { open: open };
})();
