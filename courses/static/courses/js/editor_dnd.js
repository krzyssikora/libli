(function () {
  "use strict";
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  var EDGE = 56;       // px band at each pane edge that triggers auto-scroll
  var MAX_SPEED = 16;  // px per animation frame at the very edge

  // Exposed so editor.js can (re)bind after each fragment swap.
  window.__libliEditorDnD = function (root) {
    var pane = root.querySelector('[data-scope="editor"]');
    var list = pane && pane.querySelector(".element-list");
    if (!list || list.__dndBound) return;
    list.__dndBound = true;
    var paneBody = pane.querySelector(".pane-body");  // the scroll container
    var drag = null;      // { pk, row }
    var lastY = 0;        // last pointer clientY, so the rAF loop can re-place the line
    var vel = 0;          // current auto-scroll velocity (px/frame)
    var rafId = null;

    function clearMarks() {
      Array.prototype.slice.call(list.querySelectorAll(".el-drop-line")).forEach(function (n) { n.remove(); });
      Array.prototype.slice.call(list.querySelectorAll(".el-row.lifted")).forEach(function (n) { n.classList.remove("lifted"); });
    }

    // Place the drop line at the pointer. DIRECT children only (":scope >"): a nested
    // tabs child is a descendant `.el-row` but not a child of `list`, so using one as
    // the insertBefore reference throws NotFoundError. This matches the drop handler,
    // which counts position over list.children.
    function placeLine(clientY) {
      clearMarks();
      if (drag) drag.row.classList.add("lifted");
      var rows = Array.prototype.slice.call(list.querySelectorAll(":scope > .el-row"))
        .filter(function (r) { return r.getAttribute("data-element") !== drag.pk; });
      var before = null;
      for (var i = 0; i < rows.length; i++) {
        var box = rows[i].getBoundingClientRect();
        if (clientY < box.top + box.height / 2) { before = rows[i]; break; }
      }
      var line = document.createElement("li"); line.className = "el-drop-line";
      if (before) list.insertBefore(line, before); else list.appendChild(line);
    }

    // Auto-scroll: dragover stops firing when the pointer holds still at a pane edge, so
    // an off-screen target would be unreachable without an animation-frame loop that
    // keeps scrolling (and re-places the line under the still cursor) until the pointer
    // leaves the edge band or the drag ends.
    function tick() {
      if (!drag || vel === 0 || !paneBody) { rafId = null; return; }
      var before = paneBody.scrollTop;
      paneBody.scrollTop += vel;
      if (paneBody.scrollTop !== before) placeLine(lastY);  // content moved -> re-place
      rafId = requestAnimationFrame(tick);
    }
    function updateAutoScroll(clientY) {
      if (!paneBody) { vel = 0; return; }
      var r = paneBody.getBoundingClientRect();
      if (clientY < r.top + EDGE) {
        vel = -Math.ceil(MAX_SPEED * (1 - (clientY - r.top) / EDGE));
      } else if (clientY > r.bottom - EDGE) {
        vel = Math.ceil(MAX_SPEED * (1 - (r.bottom - clientY) / EDGE));
      } else {
        vel = 0;
      }
      if (vel !== 0 && rafId === null) rafId = requestAnimationFrame(tick);
    }
    function stopAutoScroll() { vel = 0; if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; } }

    list.addEventListener("dragstart", function (e) {
      var grip = e.target.closest(".ica--grip");
      if (!grip) { e.preventDefault(); return; }
      var row = grip.closest(".el-row");
      // Only TOP-LEVEL rows drag: a nested tabs child is a `.el-row` too, but its drop
      // position would be computed against the top-level list and land in the wrong tab.
      // Nested rows reorder via the up/down buttons instead.
      if (row.parentNode !== list) { e.preventDefault(); return; }
      drag = { pk: row.getAttribute("data-element"), row: row };
      row.classList.add("lifted");
      e.dataTransfer.effectAllowed = "move";
    });

    list.addEventListener("dragover", function (e) {
      if (!drag) return;
      e.preventDefault();
      lastY = e.clientY;
      placeLine(e.clientY);
      updateAutoScroll(e.clientY);
    });

    list.addEventListener("dragend", function () { stopAutoScroll(); clearMarks(); drag = null; });

    list.addEventListener("drop", function (e) {
      if (!drag) return;
      e.preventDefault();
      stopAutoScroll();
      // post-removal index = number of NON-dragged rows before the drop line
      var nodes = Array.prototype.slice.call(list.children);
      var lineIdx = -1;
      for (var j = 0; j < nodes.length; j++) {
        if (nodes[j].classList && nodes[j].classList.contains("el-drop-line")) { lineIdx = j; break; }
      }
      // No drop line (drop fired without a preceding dragover) -> no-op, don't reorder to 0.
      if (lineIdx === -1) { drag = null; clearMarks(); return; }
      var moveUrl = pane.getAttribute("data-move-url");
      if (!moveUrl) { drag = null; clearMarks(); return; }
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
      drag = null; clearMarks();
      fetch(moveUrl, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          // Reuse the editor's full swap (re-init galleries/tabs/RTE + restore scroll &
          // open tabs). The old bespoke replaceWith skipped all of that and jumped the
          // pane to the top. Fall back to a minimal swap only if editor.js is absent.
          if (window.__libliApplyFragments) { window.__libliApplyFragments(html); return; }
          var tmp = document.createElement("div"); tmp.innerHTML = html.trim();
          ["editor", "preview"].forEach(function (scope) {
            var inc = tmp.querySelector('[data-scope="' + scope + '"]');
            var ex = root.querySelector('[data-scope="' + scope + '"]');
            if (inc && ex) ex.replaceWith(inc);
          });
          if (window.__libliEditorDnD) window.__libliEditorDnD(root);
        });
    });
  };
})();
