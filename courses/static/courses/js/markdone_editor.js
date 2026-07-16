(function () {
  "use strict";
  function initOne(editor) {
    if (editor.dataset.markdoneEditorReady === "1") return;
    editor.dataset.markdoneEditorReady = "1";
    var list = editor.querySelector("[data-markdone-rows]");
    var addBtn = editor.querySelector("[data-markdone-add-row]");
    var tmpl = editor.querySelector("[data-markdone-row-template]");
    var total = editor.querySelector('input[name="items-TOTAL_FORMS"]');
    if (!list || !addBtn || !tmpl || !total) return;
    addBtn.addEventListener("click", function () {
      var idx = parseInt(total.value, 10) || 0;
      var html = tmpl.innerHTML.replace(/__prefix__/g, String(idx)).trim();
      var wrap = document.createElement("div");
      wrap.innerHTML = html;
      var row = wrap.firstElementChild;
      list.appendChild(row);
      total.value = String(idx + 1);
      var input = row.querySelector('input[type="text"]');
      if (input) input.focus();
    });
  }
  function initMarkDoneEditor(root) {
    var scope = root || document;
    var sel = "[data-markdone-editor]";
    if (scope.matches && scope.matches(sel)) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(sel), initOne);
  }
  window.libliInitMarkDoneEditor = initMarkDoneEditor;
  initMarkDoneEditor(document);
})();
