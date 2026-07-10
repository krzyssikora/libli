(function () {
  "use strict";

  // ---- Table editor: progressively enhance [data-table-editor] blocks. ----
  // The hidden input[name="data"] is the SOLE authoritative form field; the grid
  // (td[contenteditable]) and controls (checkboxes/select) are name-less JS UI
  // mirrored into it via serialize(). Row/column insert+delete handles are
  // injected here (not server-rendered) so the DOM contract in
  // _edit_table.html stays exactly as authored by Task 6.

  var MAX_ROWS = 50;
  var MAX_COLS = 20;
  var HALIGNS = ["left", "center", "right"];
  var VALIGNS = ["top", "middle", "bottom"];

  // ---- grid helpers -------------------------------------------------------

  function dataRows(grid) {
    return Array.prototype.filter.call(grid.querySelectorAll("tr"), function (tr) {
      return !tr.hasAttribute("data-control-row");
    });
  }

  function dataCells(tr) {
    return tr.querySelectorAll("td[contenteditable]");
  }

  function rowCount(grid) { return dataRows(grid).length; }

  function colCount(grid) {
    var rows = dataRows(grid);
    return rows.length ? dataCells(rows[0]).length : 0;
  }

  function tableContainer(grid) {
    var firstRow = grid.querySelector("tr");
    return firstRow ? firstRow.parentNode : grid.querySelector("table");
  }

  function newCell() {
    var td = document.createElement("td");
    td.setAttribute("contenteditable", "true");
    td.dataset.halign = "left";
    td.dataset.valign = "top";
    td.className = "ta-left va-top";
    return td;
  }

  // Grid handles use the authoring UI's .iconbtn + sprite pattern (as the gallery
  // editor's server-rendered row controls do) rather than bare +/− glyphs. Their
  // labels ride on data-msg-* attributes because this markup is built client-side,
  // where {% trans %} is unavailable.
  function label(grid, key, fallback) {
    var editor = grid.closest("[data-table-editor]");
    return (editor && editor.getAttribute("data-msg-" + key)) || fallback;
  }

  function handleBtn(attr, symbol, text, danger) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "iconbtn" + (danger ? " iconbtn--danger" : "");
    b.setAttribute(attr, "");
    b.title = text;
    b.setAttribute("aria-label", text);
    b.innerHTML = '<svg class="ic" aria-hidden="true" focusable="false"><use href="#' +
      symbol + '"/></svg>';
    return b;
  }

  function rowCtl(grid) {
    var td = document.createElement("td");
    td.setAttribute("data-control", "");
    td.className = "table-editor__rowctl";
    td.appendChild(handleBtn("data-row-insert", "ed-plus", label(grid, "row-insert", "Insert row below")));
    td.appendChild(handleBtn("data-row-delete", "ed-minus", label(grid, "row-delete", "Delete row"), true));
    return td;
  }

  function colCtl(grid, index) {
    var td = document.createElement("td");
    td.setAttribute("data-control", "");
    td.className = "table-editor__colctl";
    var add = handleBtn("data-col-insert", "ed-plus", label(grid, "col-insert", "Insert column right"));
    add.dataset.colIndex = String(index);
    var del = handleBtn("data-col-delete", "ed-minus", label(grid, "col-delete", "Delete column"), true);
    del.dataset.colIndex = String(index);
    td.appendChild(add);
    td.appendChild(del);
    return td;
  }

  function buildRow(grid, cols) {
    var tr = document.createElement("tr");
    for (var i = 0; i < cols; i++) tr.appendChild(newCell());
    tr.appendChild(rowCtl(grid));
    return tr;
  }

  function ensureRowControls(grid) {
    dataRows(grid).forEach(function (tr) {
      if (!tr.querySelector("td[data-control]")) tr.appendChild(rowCtl(grid));
    });
  }

  function rebuildColControls(grid) {
    var old = grid.querySelector("tr[data-control-row]");
    if (old) old.remove();
    var cols = colCount(grid);
    if (!cols) return;
    var tr = document.createElement("tr");
    tr.setAttribute("data-control-row", "");
    for (var i = 0; i < cols; i++) tr.appendChild(colCtl(grid, i));
    // Spacer under the row-control column. Marked data-control so it is styled as
    // chrome (no border/min-width) rather than an empty bordered cell.
    var spacer = document.createElement("td");
    spacer.setAttribute("data-control", "");
    tr.appendChild(spacer);
    tableContainer(grid).appendChild(tr);
  }

  function refreshControlState(grid) {
    var rows = rowCount(grid);
    var cols = colCount(grid);
    Array.prototype.forEach.call(grid.querySelectorAll("[data-row-delete]"), function (b) {
      b.disabled = rows <= 1;
    });
    Array.prototype.forEach.call(grid.querySelectorAll("[data-row-insert]"), function (b) {
      b.disabled = rows >= MAX_ROWS;
    });
    Array.prototype.forEach.call(grid.querySelectorAll("[data-col-delete]"), function (b) {
      b.disabled = cols <= 1;
    });
    Array.prototype.forEach.call(grid.querySelectorAll("[data-col-insert]"), function (b) {
      b.disabled = cols >= MAX_COLS;
    });
  }

  function insertColumnAfter(grid, idx) {
    dataRows(grid).forEach(function (tr) {
      var cells = dataCells(tr);
      var ref = cells[idx];
      var td = newCell();
      if (ref) tr.insertBefore(td, ref.nextSibling);
      else tr.insertBefore(td, tr.firstChild);
    });
  }

  function deleteColumnAt(grid, idx) {
    dataRows(grid).forEach(function (tr) {
      var cells = dataCells(tr);
      if (cells[idx]) cells[idx].remove();
    });
  }

  // ---- wiring ---------------------------------------------------------

  function wire(editor) {
    if (editor.dataset.tableWired) return;
    editor.dataset.tableWired = "1";

    var hidden = editor.querySelector('input[name="data"]');
    var grid = editor.querySelector("[data-table-grid]");
    var toolbar = editor.querySelector("[data-table-toolbar]");
    var thRow = editor.querySelector("[data-th-row]");
    var thCol = editor.querySelector("[data-th-col]");
    var borderSel = editor.querySelector("[data-border]");
    if (!hidden || !grid) return; // defensive: markup changed

    function serialize() {
      var cells = [];
      dataRows(grid).forEach(function (tr) {
        var row = [];
        Array.prototype.forEach.call(dataCells(tr), function (td) {
          row.push({
            html: td.innerHTML,
            halign: td.dataset.halign || "left",
            valign: td.dataset.valign || "top",
          });
        });
        cells.push(row);
      });
      hidden.value = JSON.stringify({
        header_row: !!(thRow && thRow.checked),
        header_col: !!(thCol && thCol.checked),
        border: (borderSel && borderSel.value) || "grid",
        cells: cells,
      });
    }

    ensureRowControls(grid);
    rebuildColControls(grid);
    refreshControlState(grid);

    // Serialize on init ONLY when the hidden field is empty: covers the add
    // path (captures the default 2x2) and the edit path (captures the
    // server-rendered EXISTING grid, so a Save that never touches the grid
    // does not wipe it). A bound-invalid re-render already has the submitted
    // JSON in the hidden field, so it is skipped here.
    if (hidden.value === "") serialize();

    var focusedCell = null;

    function refreshAlignButtons() {
      if (!toolbar || !focusedCell) return;
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-halign]"), function (btn) {
        btn.classList.toggle(
          "is-on",
          btn.getAttribute("data-halign") === (focusedCell.dataset.halign || "left")
        );
      });
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-valign]"), function (btn) {
        btn.classList.toggle(
          "is-on",
          btn.getAttribute("data-valign") === (focusedCell.dataset.valign || "top")
        );
      });
    }

    grid.addEventListener("focusin", function (e) {
      var td = e.target.closest("td[contenteditable]");
      if (!td) return;
      focusedCell = td;
      if (toolbar) toolbar.hidden = false;
      refreshAlignButtons();
    });

    // Enter inserts a <br> instead of a new block element, so a cell's only
    // intra-content separator is <br> (matches CELL_TAGS).
    grid.addEventListener("keydown", function (e) {
      var td = e.target.closest("td[contenteditable]");
      if (!td) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        document.execCommand("insertHTML", false, "<br>");
        serialize();
      }
    });

    grid.addEventListener("input", function (e) {
      if (!e.target.closest("td[contenteditable]")) return;
      serialize();
    });

    // Row/column insert+delete handles (delegated).
    grid.addEventListener("click", function (e) {
      var rowInsert = e.target.closest("[data-row-insert]");
      if (rowInsert) {
        if (rowCount(grid) < MAX_ROWS) {
          var tr = rowInsert.closest("tr");
          var newRow = buildRow(grid, colCount(grid));
          tr.parentNode.insertBefore(newRow, tr.nextSibling);
          refreshControlState(grid);
          serialize();
        }
        return;
      }
      var rowDelete = e.target.closest("[data-row-delete]");
      if (rowDelete) {
        if (rowCount(grid) > 1) {
          rowDelete.closest("tr").remove();
          refreshControlState(grid);
          serialize();
        }
        return;
      }
      var colInsert = e.target.closest("[data-col-insert]");
      if (colInsert) {
        if (colCount(grid) < MAX_COLS) {
          insertColumnAfter(grid, parseInt(colInsert.dataset.colIndex, 10));
          rebuildColControls(grid);
          refreshControlState(grid);
          serialize();
        }
        return;
      }
      var colDelete = e.target.closest("[data-col-delete]");
      if (colDelete) {
        if (colCount(grid) > 1) {
          deleteColumnAt(grid, parseInt(colDelete.dataset.colIndex, 10));
          rebuildColControls(grid);
          refreshControlState(grid);
          serialize();
        }
        return;
      }
    });

    if (toolbar) {
      // Keep the cell's caret/selection intact: buttons must not steal focus.
      toolbar.addEventListener("mousedown", function (e) {
        if (e.target.closest("button")) e.preventDefault();
      });

      toolbar.addEventListener("click", function (e) {
        var cmdBtn = e.target.closest("[data-cmd]");
        if (cmdBtn && focusedCell) {
          var cmd = cmdBtn.getAttribute("data-cmd");
          focusedCell.focus();
          if (cmd === "bold" || cmd === "italic" || cmd === "underline") {
            // styleWithCSS=false forces execCommand to emit <b>/<i>/<u> tags
            // rather than inline style="" attributes (CELL_TAGS has no
            // attribute allowlist, so a style attribute would be dropped).
            document.execCommand("styleWithCSS", false, false);
            document.execCommand(cmd, false, null);
            serialize();
          } else if (cmd === "math") {
            if (!window.libliMathInput) return;
            var sel = window.getSelection();
            var range = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
            var cell = focusedCell;
            window.libliMathInput.open(function (latex) {
              cell.focus();
              var node = document.createTextNode("\\(" + latex + "\\)");
              if (range) {
                range.deleteContents();
                range.insertNode(node);
                range.setStartAfter(node);
                range.collapse(true);
                sel.removeAllRanges();
                sel.addRange(range);
              } else {
                cell.appendChild(node);
              }
              serialize();
            });
          }
          return;
        }
        var halignBtn = e.target.closest("[data-halign]");
        if (halignBtn && focusedCell) {
          var h = halignBtn.getAttribute("data-halign");
          focusedCell.dataset.halign = h;
          HALIGNS.forEach(function (v) { focusedCell.classList.remove("ta-" + v); });
          focusedCell.classList.add("ta-" + h);
          refreshAlignButtons();
          serialize();
          return;
        }
        var valignBtn = e.target.closest("[data-valign]");
        if (valignBtn && focusedCell) {
          var v = valignBtn.getAttribute("data-valign");
          focusedCell.dataset.valign = v;
          VALIGNS.forEach(function (vv) { focusedCell.classList.remove("va-" + vv); });
          focusedCell.classList.add("va-" + v);
          refreshAlignButtons();
          serialize();
          return;
        }
      });
    }

    if (thRow) thRow.addEventListener("change", serialize);
    if (thCol) thCol.addEventListener("change", serialize);
    if (borderSel) borderSel.addEventListener("change", serialize);
  }

  function initTableEditor(root) {
    (root || document).querySelectorAll("[data-table-editor]").forEach(wire);
  }

  window.libliInitTableEditor = initTableEditor;
  initTableEditor(document);
})();
