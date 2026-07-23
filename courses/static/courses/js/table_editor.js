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
    // A "data cell" is any non-chrome cell, TD or TH. A <th> that only half
    // the selectors match would be un-focusable, un-alignable and invisible to
    // serialization.
    return tr.querySelectorAll("td:not([data-control]), th:not([data-control])");
  }

  // Layout column count. The old body read row 0's CELL count, which is wrong
  // the moment a span exists: a row-0 colspan makes the control strip too short
  // and every handle lands under the wrong column.
  function colCount(desc) {
    return window.libliTableGrid.layoutWidth(desc);
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

  function ensureRowControls(grid) {
    dataRows(grid).forEach(function (tr) {
      if (!tr.querySelector("td[data-control]")) tr.appendChild(rowCtl(grid));
    });
  }

  function rebuildColControls(grid, desc) {
    var old = grid.querySelector("tr[data-control-row]");
    if (old) old.remove();
    var cols = colCount(desc);
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

  function refreshControlState(grid, desc) {
    var sm = window.libliTableGrid.slotMap(desc);
    var rows = sm.height;
    var cols = sm.width;
    // Insert is capped; delete keeps today's FLOOR guard, restated in layout
    // terms -- "one layout column left" is not "one cell left in row 0".
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

    // Descriptor handed to table_grid.js. `rows`/`cells` are this editor's own
    // helpers, so there is exactly one definition of "data cell" per editor and
    // the module inherits it.
    var desc = {
      rows: function () { return dataRows(grid); },
      cells: function (tr) { return Array.prototype.slice.call(dataCells(tr)); },
      makeCell: newCell,
      makeRow: function () {
        var tr = document.createElement("tr");
        tr.appendChild(rowCtl(grid));
        return tr;
      },
      maxCols: MAX_COLS,
      maxRows: MAX_ROWS,
    };

    function serialize() {
      var cells = [];
      dataRows(grid).forEach(function (tr) {
        var row = [];
        Array.prototype.forEach.call(dataCells(tr), function (td) {
          var cell = {
            html: td.innerHTML,
            halign: td.dataset.halign || "left",
            valign: td.dataset.valign || "top",
          };
          // Emit spans ONLY when > 1 and header ONLY for TH, so a table with
          // no merges and no header cells serializes byte-identically to
          // before this feature existed.
          if (td.colSpan > 1) cell.colspan = td.colSpan;
          if (td.rowSpan > 1) cell.rowspan = td.rowSpan;
          if (td.tagName === "TH") cell.header = true;
          row.push(cell);
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
    rebuildColControls(grid, desc);
    refreshControlState(grid, desc);

    // Serialize on init ONLY when the hidden field is empty: covers the add
    // path (captures the default 2x2) and the edit path (captures the
    // server-rendered EXISTING grid, so a Save that never touches the grid
    // does not wipe it). A bound-invalid re-render already has the submitted
    // JSON in the hidden field, so it is skipped here.
    if (hidden.value === "") serialize();

    // focusCell (the existing declaration, renamed) is the SINGLE authority for
    // what the toolbar acts on. It is set on plain click/focusin and
    // deliberately NOT moved by Shift+click: suppressing the Shift mousedown
    // also suppresses focus movement, so document.activeElement is unusable.
    var focusCell = null;
    var rangeAnchor = null;   // a cell node
    var rangeEnd = null;      // a LAYOUT {r, c} coordinate, not a node

    function clearRange(announce) {
      rangeEnd = null;
      Array.prototype.forEach.call(
        grid.querySelectorAll(".is-range"),
        function (c) { c.classList.remove("is-range"); }
      );
      if (announce) say("range-cleared");
      refreshToolbarState();
    }

    // Every client-built string rides on a data-msg-* attribute, because this
    // markup is created in JS where {% trans %} is unavailable.
    function msg(key) {
      return editor.getAttribute("data-msg-" + key) || "";
    }

    function say(key) {
      var region = editor.querySelector("[data-range-status]");
      if (region) region.textContent = msg(key);
    }

    // A range that is legal in SHAPE but larger than a table may be -- e.g.
    // all 26 columns of the grandfathered table. canMerge already refuses it;
    // this is only so the button can say WHY instead of greying out silently.
    function tooBig() {
      if (!rangeAnchor || !rangeEnd) return false;
      var rg = libliTableGrid.rangeCells(desc, rangeAnchor, rangeEnd);
      if (!rg) return false;
      return (rg.c1 - rg.c0 + 1) > desc.maxCols ||
             (rg.r1 - rg.r0 + 1) > desc.maxRows;
    }

    function paintRange() {
      Array.prototype.forEach.call(
        grid.querySelectorAll(".is-range"),
        function (c) { c.classList.remove("is-range"); }
      );
      if (!rangeAnchor || !rangeEnd) return;
      var rg = libliTableGrid.rangeCells(desc, rangeAnchor, rangeEnd);
      if (!rg) return;
      rg.cells.forEach(function (c) { c.classList.add("is-range"); });
      say("range-selected");
      refreshToolbarState();
    }

    function refreshAlignButtons() {
      if (!toolbar || !focusCell) return;
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-halign]"), function (btn) {
        btn.classList.toggle(
          "is-on",
          btn.getAttribute("data-halign") === (focusCell.dataset.halign || "left")
        );
      });
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-valign]"), function (btn) {
        btn.classList.toggle(
          "is-on",
          btn.getAttribute("data-valign") === (focusCell.dataset.valign || "top")
        );
      });
    }

    function refreshToolbarState() {
      if (!toolbar) return;
      var mergeBtn = toolbar.querySelector("[data-merge]");
      var splitBtn = toolbar.querySelector("[data-split]");
      var headerBtn = toolbar.querySelector("[data-header-toggle]");
      // These three must be settled even when focusCell is null -- a delete
      // that nulls it would otherwise leave Merge enabled. "Toolbar hidden" is
      // a different mechanism and does not substitute.
      if (mergeBtn) {
        var ok = rangeAnchor && rangeEnd &&
                 libliTableGrid.canMerge(desc, rangeAnchor, rangeEnd);
        mergeBtn.disabled = !ok;
        mergeBtn.title = tooBig() ? msg("merge-too-big") : msg("merge");
      }
      if (splitBtn) {
        splitBtn.disabled = !(focusCell &&
          (libliTableGrid.colspanOf(focusCell) > 1 ||
           libliTableGrid.rowspanOf(focusCell) > 1));
      }
      // Task 12 already renders [data-header-toggle], so headerBtn is non-null
      // throughout Task 13 -- but refreshHeaderButton only exists from Task 14.
      // Ship the stub below in THIS task so refreshToolbarState cannot throw a
      // ReferenceError (which would take paintRange, clearRange and the whole
      // merge/split enablement down with it); Task 14 replaces its body.
      if (headerBtn) refreshHeaderButton(headerBtn);
      refreshAlignButtons();
    }

    // Replaced wholesale in Task 14.
    function refreshHeaderButton(btn) {
      btn.disabled = true;
    }

    // Non-empty means: static html that is not blank, OR any answer cell, OR
    // any image cell -- so a merge can never silently lose an accepted answer
    // or an image's media pk. (table_editor.js has no kinds; the kind clauses
    // live in filltable_editor.js's override.)
    function absorbedNonEmpty(rg) {
      for (var i = 0; i < rg.cells.length; i++) {
        var c = rg.cells[i];
        if (c === rg.anchor) continue;
        if (cellIsNonEmpty(c)) return true;
      }
      return false;
    }

    function cellIsNonEmpty(c) {
      return c.textContent.trim() !== "" || c.querySelector("img") !== null;
    }

    grid.addEventListener("focusin", function (e) {
      var td = e.target.closest("td[contenteditable], th[contenteditable]");
      if (!td) return;
      focusCell = td;
      rangeAnchor = td;   // a plain click ALWAYS re-seats the anchor, so a
                          // stale anchor from an earlier merge can never
                          // silently re-appear in the next range
      clearRange(false);  // ... and drops any live range
      if (toolbar) toolbar.hidden = false;
      refreshToolbarState();   // replaces the bare refreshAlignButtons() call:
                               // Split and Header enablement both read
                               // focusCell, so the toolbar must recompute
                               // whenever focus moves
    });

    // Chrome and genuine multi-line controls are excluded, but the fill-table's
    // ANSWER INPUT is not: it is styled full-cell, so it covers essentially the
    // whole answer cell. Excluding it would leave an author with no way to make
    // an answer cell a range endpoint at all -- which Task 16's first test
    // requires. Shift+click text-selection inside a one-line input is the
    // (marginal) thing traded away; the caret still lands there on a plain click.
    var SHIFT_EXEMPT = "textarea, select, button, [data-control]";

    grid.addEventListener("mousedown", function (e) {
      if (!e.shiftKey) return;
      if (e.target.closest(SHIFT_EXEMPT)) return;
      e.preventDefault();   // stop contenteditable starting a text selection
    });

    grid.addEventListener("click", function (e) {
      if (!e.shiftKey) return;
      if (e.target.closest(SHIFT_EXEMPT)) return;
      var td = e.target.closest("td, th");
      if (!td || td.hasAttribute("data-control")) return;
      // First gesture in a fresh editor: no focusin has fired, so there is no
      // anchor yet. Behave exactly like a plain click -- never reach
      // rangeCells with a null anchor.
      if (!rangeAnchor) {
        rangeAnchor = td;
        focusCell = td;
        // Focus explicitly: the mousedown above already preventDefault'ed, so
        // nothing in the grid has DOM focus and the grid-scoped keyboard chord
        // would stay unreachable until the author clicked again.
        td.focus();
        refreshToolbarState();
        return;
      }
      var sm = libliTableGrid.slotMap(desc);
      rangeEnd = libliTableGrid.anchorOf(sm, td);
      paintRange();
    });

    // Enter inserts a <br> instead of a new block element, so a cell's only
    // intra-content separator is <br> (matches CELL_TAGS).
    grid.addEventListener("keydown", function (e) {
      var td = e.target.closest("td[contenteditable], th[contenteditable]");
      if (!td) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        document.execCommand("insertHTML", false, "<br>");
        serialize();
      }
    });

    grid.addEventListener("input", function (e) {
      if (!e.target.closest("td[contenteditable], th[contenteditable]")) return;
      serialize();
    });

    // Every structural edit ends the same way.
    function afterStructuralEdit() {
      clearRange(false);
      rebuildColControls(grid, desc);
      refreshControlState(grid, desc);
      refreshToolbarState();
      serialize();
    }

    // Row/column insert+delete handles (delegated).
    grid.addEventListener("click", function (e) {
      var rowInsert = e.target.closest("[data-row-insert]");
      if (rowInsert) {
        // rowCtl() carries no index, so read the row's position from desc.
        var ri = desc.rows().indexOf(rowInsert.closest("tr"));
        if (ri >= 0 && window.libliTableGrid.slotMap(desc).height < MAX_ROWS) {
          libliTableGrid.insertRow(desc, ri + 1); // "insert below" == at ri+1
          afterStructuralEdit();
        }
        return;
      }
      var rowDelete = e.target.closest("[data-row-delete]");
      if (rowDelete) {
        var rd = desc.rows().indexOf(rowDelete.closest("tr"));
        // Floor guard, in LAYOUT terms (today's rowCount(grid) > 1).
        if (rd >= 0 && window.libliTableGrid.slotMap(desc).height > 1) {
          libliTableGrid.deleteRow(desc, rd);
          afterStructuralEdit();
        }
        return;
      }
      var colInsert = e.target.closest("[data-col-insert]");
      if (colInsert) {
        // "Insert column right" of layout column i is an insert AT i + 1.
        // insertColumn(grid, width) appends. Consequence worth knowing: on a
        // colspan's LAST covered slot this yields layoutCol == c + s, so the
        // span does not grow -- a new cell appears after it.
        var i = parseInt(colInsert.dataset.colIndex, 10);
        if (colCount(desc) < MAX_COLS) { // colCount is the layoutWidth wrapper
                                          // Task 6 introduced -- keep ONE spelling
          libliTableGrid.insertColumn(desc, i + 1);
          afterStructuralEdit();
        }
        return;
      }
      var colDelete = e.target.closest("[data-col-delete]");
      if (colDelete) {
        if (colCount(desc) > 1) {
          libliTableGrid.deleteColumn(desc, parseInt(colDelete.dataset.colIndex, 10));
          afterStructuralEdit();
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
        if (cmdBtn && focusCell) {
          var cmd = cmdBtn.getAttribute("data-cmd");
          focusCell.focus();
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
            var cell = focusCell;
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
        if (halignBtn && focusCell) {
          var h = halignBtn.getAttribute("data-halign");
          focusCell.dataset.halign = h;
          HALIGNS.forEach(function (v) { focusCell.classList.remove("ta-" + v); });
          focusCell.classList.add("ta-" + h);
          refreshAlignButtons();
          serialize();
          return;
        }
        var valignBtn = e.target.closest("[data-valign]");
        if (valignBtn && focusCell) {
          var v = valignBtn.getAttribute("data-valign");
          focusCell.dataset.valign = v;
          VALIGNS.forEach(function (vv) { focusCell.classList.remove("va-" + vv); });
          focusCell.classList.add("va-" + v);
          refreshAlignButtons();
          serialize();
          return;
        }
        var mergeBtn = e.target.closest("[data-merge]");
        if (mergeBtn && !mergeBtn.disabled) {
          var rg = libliTableGrid.rangeCells(desc, rangeAnchor, rangeEnd);
          if (rg && absorbedNonEmpty(rg)) {
            if (!window.confirm(msg("merge-confirm"))) return;   // cancel: no change
          }
          var kept = libliTableGrid.merge(desc, rangeAnchor, rangeEnd);
          if (kept) {
            focusCell = kept;
            rangeAnchor = kept;
            // Not decoration: the toolbar's mousedown handler above already
            // preventDefault'ed, so the button never took focus. If focusCell
            // was an ABSORBED cell, merge just detached that node and DOM
            // focus fell to <body> -- without this, the grid-scoped keyboard
            // chord (Alt+Shift+Arrow, Task 15) would go dead until the author
            // clicked a cell again.
            kept.focus();
          }
          afterStructuralEdit();   // owns range clearing; do not clear here too
          return;
        }
        var splitBtn = e.target.closest("[data-split]");
        if (splitBtn && !splitBtn.disabled && focusCell) {
          var anchor = focusCell;
          libliTableGrid.split(desc, anchor);
          // The anchor survives a split, so focus simply stays on it.
          focusCell = anchor;
          rangeAnchor = anchor;
          anchor.focus();
          afterStructuralEdit();
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
