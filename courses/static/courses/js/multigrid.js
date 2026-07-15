(function () {
  "use strict";
  // Multi-select grid authoring enhancer. Mirrors choicegrid.js but each row shows a
  // checkbox per current column (multi-select) backed by a hidden comma-joined
  // correct_temp_ids field kept in sync. window.libliInitMultiGrid(root) re-syncs
  // after each editor.js fragment swap.
  var counter = 0;
  function freshTempId() { counter += 1; return "t" + Date.now().toString(36) + "-" + counter; }
  function cols(ed) { return Array.prototype.slice.call(ed.querySelectorAll("[data-multigrid-col]")); }
  function rows(ed) { return Array.prototype.slice.call(ed.querySelectorAll("[data-multigrid-row]")); }
  function tempIdInput(col) { return col.querySelector('input[name$="-temp_id"]'); }
  function labelInput(col) { return col.querySelector('input[name$="-label"]'); }
  function isDeleted(item) { var d = item.querySelector('input[name$="-DELETE"]'); return !!(d && d.checked); }
  function totalForms(ed, prefix) { return ed.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]'); }
  function editorOf(n) { return n.closest ? n.closest("[data-multigrid-editor]") : null; }

  function assignTempIds(ed) {
    cols(ed).forEach(function (col) { var ti = tempIdInput(col); if (ti && !ti.value) ti.value = freshTempId(); });
  }
  function currentColumns(ed) {
    return cols(ed).filter(function (c) { return !isDeleted(c); }).map(function (c) {
      var ti = tempIdInput(c), lbl = labelInput(c);
      return { tempId: ti ? ti.value : "", label: lbl ? lbl.value : "" };
    }).filter(function (c) { return c.tempId; });
  }
  // Rebuild each row's checkbox set from the current columns; a box is checked iff its
  // tempId is in the row's hidden correct_temp_ids (the single source of truth).
  function syncChecks(ed) {
    var columns = currentColumns(ed);
    rows(ed).forEach(function (row) {
      var hidden = row.querySelector("[data-multigrid-correct]");
      var host = row.querySelector("[data-multigrid-checks]");
      if (!hidden || !host) return;
      var chosen = (hidden.value || "").split(",").filter(Boolean);
      host.innerHTML = "";
      columns.forEach(function (col) {
        var lab = document.createElement("label");
        var box = document.createElement("input");
        box.type = "checkbox";
        box.value = col.tempId;
        box.checked = chosen.indexOf(col.tempId) !== -1;
        box.setAttribute("data-multigrid-box", "");
        lab.appendChild(box);
        lab.appendChild(document.createTextNode(" " + col.label));
        host.appendChild(lab);
      });
      // prune removed columns from the hidden value
      var live = columns.map(function (c) { return c.tempId; });
      hidden.value = chosen.filter(function (t) { return live.indexOf(t) !== -1; }).join(",");
    });
  }
  function writeHidden(row) {
    var hidden = row.querySelector("[data-multigrid-correct]");
    var host = row.querySelector("[data-multigrid-checks]");
    if (!hidden || !host) return;
    var picked = Array.prototype.slice.call(host.querySelectorAll("[data-multigrid-box]"))
      .filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
    hidden.value = picked.join(",");
  }
  function cloneTemplate(ed, sel) { var t = ed.querySelector("template[" + sel + "]"); return t ? t.content.firstElementChild.cloneNode(true) : null; }
  function renumber(node, idx) {
    Array.prototype.forEach.call(node.querySelectorAll("[name],[id],[for]"), function (el) {
      ["name", "id", "for"].forEach(function (a) { var v = el.getAttribute(a); if (v) el.setAttribute(a, v.split("__prefix__").join(idx)); });
    });
  }
  function addColumn(ed, label) {
    var total = totalForms(ed, "columns"), list = ed.querySelector("[data-multigrid-cols]");
    if (!total || !list) return null;
    var idx = parseInt(total.value, 10) || 0;
    var node = cloneTemplate(ed, "data-multigrid-col-template"); if (!node) return null;
    renumber(node, idx); list.appendChild(node); total.value = idx + 1;
    var ti = tempIdInput(node); if (ti) ti.value = freshTempId();
    if (label != null) { var lbl = labelInput(node); if (lbl) lbl.value = label; }
    return node;
  }
  function addRow(ed) {
    var total = totalForms(ed, "rows"), list = ed.querySelector("[data-multigrid-rows]");
    if (!total || !list) return null;
    var idx = parseInt(total.value, 10) || 0;
    var node = cloneTemplate(ed, "data-multigrid-row-template"); if (!node) return null;
    renumber(node, idx); list.appendChild(node); total.value = idx + 1;
    return node;
  }
  function seedIfFresh(ed) {
    if (cols(ed).length === 0 && rows(ed).length === 0) {
      addColumn(ed, ""); addColumn(ed, ""); addRow(ed); syncChecks(ed);
    }
  }
  function initEditor(ed) {
    assignTempIds(ed);
    if (!ed.dataset.multigridReady) { ed.dataset.multigridReady = "1"; seedIfFresh(ed); }
    syncChecks(ed);
  }
  document.addEventListener("click", function (e) {
    var ed = editorOf(e.target); if (!ed) return;
    if (e.target.closest("[data-multigrid-add-col]")) { addColumn(ed, ""); syncChecks(ed); return; }
    if (e.target.closest("[data-multigrid-add-row]")) { addRow(ed); syncChecks(ed); return; }
  });
  document.addEventListener("input", function (e) {
    var ed = editorOf(e.target); if (!ed) return;
    if (e.target.matches('[data-multigrid-col] input[name$="-label"]')) syncChecks(ed);
  });
  document.addEventListener("change", function (e) {
    var ed = editorOf(e.target); if (!ed) return;
    if (e.target.matches("[data-multigrid-box]")) { writeHidden(e.target.closest("[data-multigrid-row]")); return; }
    if (e.target.matches('[data-multigrid-col] input[name$="-DELETE"]')) syncChecks(ed);
  });
  window.libliInitMultiGrid = function (root) { (root || document).querySelectorAll("[data-multigrid-editor]").forEach(initEditor); };
  document.addEventListener("DOMContentLoaded", function () { window.libliInitMultiGrid(document); });
})();
