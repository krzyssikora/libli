(function () {
  "use strict";
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  // Exposed so editor.js can (re)bind after each fragment swap.
  window.__libliEditorDnD = function (root) {
    var pane = root.querySelector('[data-scope="editor"]');
    var list = pane && pane.querySelector(".element-list");
    if (!list || list.__dndBound) return;
    list.__dndBound = true;
    var drag = null;  // { pk, row }

    function clearMarks() {
      Array.prototype.slice.call(list.querySelectorAll(".el-drop-line")).forEach(function (n) { n.remove(); });
      Array.prototype.slice.call(list.querySelectorAll(".el-row.lifted")).forEach(function (n) { n.classList.remove("lifted"); });
    }

    list.addEventListener("dragstart", function (e) {
      var grip = e.target.closest(".ica--grip");
      if (!grip) { e.preventDefault(); return; }
      var row = grip.closest(".el-row");
      drag = { pk: row.getAttribute("data-element"), row: row };
      row.classList.add("lifted");
      e.dataTransfer.effectAllowed = "move";
    });

    list.addEventListener("dragover", function (e) {
      if (!drag) return;
      e.preventDefault();
      clearMarks(); drag.row.classList.add("lifted");
      var rows = Array.prototype.slice.call(list.querySelectorAll(".el-row"))
        .filter(function (r) { return r.getAttribute("data-element") !== drag.pk; });
      var before = null;
      for (var i = 0; i < rows.length; i++) {
        var box = rows[i].getBoundingClientRect();
        if (e.clientY < box.top + box.height / 2) { before = rows[i]; break; }
      }
      var line = document.createElement("li"); line.className = "el-drop-line";
      if (before) list.insertBefore(line, before); else list.appendChild(line);
    });

    list.addEventListener("dragend", clearMarks);

    list.addEventListener("drop", function (e) {
      if (!drag) return;
      e.preventDefault();
      // post-removal index = number of NON-dragged rows before the drop line
      var nodes = Array.prototype.slice.call(list.children);
      var lineIdx = -1;
      for (var j = 0; j < nodes.length; j++) {
        if (nodes[j].classList && nodes[j].classList.contains("el-drop-line")) { lineIdx = j; break; }
      }
      var position = 0;
      for (var i = 0; i < lineIdx; i++) {
        var n = nodes[i];
        if (n.classList && n.classList.contains("el-row") && n.getAttribute("data-element") !== drag.pk) position++;
      }
      var fd = new FormData();
      fd.append("ctx", "editor");
      fd.append("element", drag.pk);
      fd.append("unit", pane.getAttribute("data-unit"));
      fd.append("unit_token", pane.getAttribute("data-updated"));
      fd.append("position", String(position));
      var moveUrl = pane.getAttribute("data-move-url");
      drag = null; clearMarks();
      fetch(moveUrl, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          var tmp = document.createElement("div"); tmp.innerHTML = html.trim();
          ["editor", "preview"].forEach(function (scope) {
            var inc = tmp.querySelector('[data-scope="' + scope + '"]');
            var ex = root.querySelector('[data-scope="' + scope + '"]');
            if (inc && ex) ex.replaceWith(inc);
          });
          if (window.__libliEditorDnD) window.__libliEditorDnD(root);  // re-bind
          var prev = root.querySelector('[data-scope="preview"]');
          if (prev && window.libliRenderMath) window.libliRenderMath(prev);
        });
    });
  };
})();
