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

  window.libliMathInput = { open: open };
})();
