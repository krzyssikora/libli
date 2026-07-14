(function () {
  "use strict";
  function initOne(editor) {
    if (editor.dataset.stepperEditorReady === "1") return;
    editor.dataset.stepperEditorReady = "1";
    var list = editor.querySelector("[data-stepper-rows]");
    var addBtn = editor.querySelector("[data-stepper-add-row]");
    var tmpl = editor.querySelector("[data-stepper-row-template]");
    var total = editor.querySelector('input[name="steps-TOTAL_FORMS"]');
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
  function initStepperEditor(root) {
    var scope = root || document;
    var sel = "[data-stepper-editor]";
    if (scope.matches && scope.matches(sel)) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(sel), initOne);
  }
  window.libliInitStepperEditor = initStepperEditor;
  initStepperEditor(document);
})();
