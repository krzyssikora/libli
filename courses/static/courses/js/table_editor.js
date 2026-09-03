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
  // data-cmd values whose active state is queryCommandState-derived, and the
  // colour slots whose active state comes from the caret's ancestor class. The
  // data-cmd value and the execCommand name are deliberately the same string
  // here (unlike the align buttons), so one list serves both.
  var INLINE_CMDS = ["bold", "italic", "underline"];
  var COLOUR_SLOTS = ["red", "blue", "green", "orange"];
  var CELL_IMAGE_DEFAULT = "full";
  var CELL_IMAGE_INSERT = "medium";
  // Whole-literal class names: `classList.add('table-editor__img--' + size)` would
  // leave only a stem literal in the source, making test_table_css.py's assertion
  // pass with three of four modifiers unstyled.
  var CELL_IMG_CLASS = {
    small: "table-editor__img--small",
    medium: "table-editor__img--medium",
    large: "table-editor__img--large",
    full: "table-editor__img--full",
  };

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

  // Module-level, keyed by editor root: wire() publishes its per-editor handle
  // here, and ONE module-scope hook looks it up. A per-editor closure re-assigned
  // to one global would still be last-wins regardless of what it inspects.
  var PICK_HANDLES = new WeakMap();

  window.libliTablePickImage = function (pick) {
    var root = pick.closest("[data-table-editor]");
    var handle = root && PICK_HANDLES.get(root);
    if (!handle) return null;   // media_picker.js already tests for truthiness
    return handle(pick);
  };

  function wire(editor) {
    if (editor.dataset.tableWired) return;
    editor.dataset.tableWired = "1";

    var hidden = editor.querySelector('input[name="data"]');
    var grid = editor.querySelector("[data-table-grid]");
    var toolbar = editor.querySelector("[data-table-toolbar]");
    var imageAlt = editor.querySelector("[data-image-alt]");
    var sizeSel = editor.querySelector("[data-image-size]");
    var removeBtn = editor.querySelector("[data-image-remove]");
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
          var isImage = td.hasAttribute("data-image");
          if (!isImage) {
            if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });
          }
          var cell;
          if (isImage) {
            cell = {
              kind: "image",
              media: parseInt(td.dataset.media, 10),   // dataset is a STRING
              alt: td.dataset.alt || "",
              size: td.dataset.size || CELL_IMAGE_DEFAULT,
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
          } else {
            cell = {
              html: td.innerHTML,
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
          }
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

    // Declared at the same relative position as the fill table's (above the
    // focusCell/rangeAnchor declarations): afterStructuralEdit, setImageCell and the
    // Remove-image listener all dereference it, and the init-time refreshToolbarState
    // runs after those declarations.
    var cellStash = new Map();

    function stashFor(td) {
      var s = cellStash.get(td);
      if (!s) {
        s = { html: null, answer: null };
        cellStash.set(td, s);
      }
      return s;
    }

    PICK_HANDLES.set(editor, function (_pick) {
      var target = focusCell;          // captured when the picker OPENS
      return function (id, _name, url) {
        // Guard on the CAPTURED target, not focusCell: it is `target` the argument
        // list dereferences, so the early return must precede argument evaluation.
        // Defence-in-depth — unreachable through the UI while [data-image-toggle]
        // is disabled with no focused cell.
        if (!target) return;
        // id is a STRING (media_picker.js passes the raw data-asset-id).
        setImageCell(target, parseInt(id, 10), url, target.dataset.alt || "");
        focusCell = target;
        refreshToolbarState();   // see below: nothing else paints the new controls
        serialize();
      };
    });

    function setImageCell(td, mediaInt, url, alt) {
      // Stash ONLY on a genuine text->image conversion. On a RE-PICK the cell
      // already carries data-image, and an unconditional stash write would
      // overwrite s.html with the preview <img> markup — Remove image would then
      // restore an <img> into a contenteditable cell, sanitize_cell would strip it
      // to "", and the author's original text would be permanently lost.
      if (!td.hasAttribute("data-image")) {
        stashFor(td).html = td.innerHTML;
      }
      td.setAttribute("data-image", "");
      td.dataset.media = String(mediaInt);
      td.dataset.alt = alt || "";
      // `|| CELL_IMAGE_INSERT` serves conversion AND re-pick from ONE call site: a
      // literal "medium" would demote an author's `full` cell on every re-pick,
      // while a literal "preserve" would leave a converted cell with no size.
      td.dataset.size = td.dataset.size || CELL_IMAGE_INSERT;
      var size = td.dataset.size;      // read AFTER the assignment
      td.setAttribute("tabindex", "0");
      // NOT cosmetic: without this the runtime guard
      // `if (cmdBtn && focusCell && focusCell.hasAttribute("contenteditable"))`
      // passes on an image cell, and the Enter/input handlers (deliberately left
      // [contenteditable]-only) start firing on it.
      td.removeAttribute("contenteditable");
      td.innerHTML = "";
      // DOM property assignment, not innerHTML concat, so a `"` or `<` in a
      // free-typed alt cannot break out of the markup.
      var img = document.createElement("img");
      img.className = "table-editor__img";        // lone assignment: the guard regex
      img.classList.add(CELL_IMG_CLASS[size]);    // literal map, not concatenation
      img.src = url;
      img.alt = alt || "";
      td.appendChild(img);
    }

    // focusCell (the existing declaration, renamed) is the SINGLE authority for
    // what the toolbar acts on. It is set on plain click/focusin and
    // deliberately NOT moved by Shift+click: suppressing the Shift mousedown
    // also suppresses focus movement, so document.activeElement is unusable.
    var focusCell = null;
    var rangeAnchor = null;   // a cell node
    var rangeEnd = null;      // a LAYOUT {r, c} coordinate, not a node

    refreshToolbarState();   // init-time paint: every cell-scoped control starts
                              // disabled/hidden with nothing focused, matching
                              // the markup's own `disabled` attributes.

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
      if (!toolbar) return;
      var h = focusCell ? (focusCell.dataset.halign || "left") : null;
      var v = focusCell ? (focusCell.dataset.valign || "top") : null;
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-halign]"), function (btn) {
        btn.classList.toggle("is-on", btn.getAttribute("data-halign") === h);
      });
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-valign]"), function (btn) {
        btn.classList.toggle("is-on", btn.getAttribute("data-valign") === v);
      });
    }

    // B/I/U and the swatches read the SELECTION, not the cell's own attributes,
    // so they cannot ride along in refreshAlignButtons: they must be repainted on
    // every caret move, not only when focus lands on a different cell. This
    // mirrors text_toolbar.js's refreshActive -- without it these are the only
    // controls in the toolbar that never light up, and a click on Bold reads as a
    // dead button (the format IS applied; nothing on screen says so).
    function refreshInlineButtons() {
      if (!toolbar) return;
      // The caret must be inside the cell the toolbar acts on. focusCell is never
      // nulled on blur, so without this the buttons would keep reporting the state
      // of a selection that has since moved to another element entirely.
      var live = false;
      if (focusCell && focusCell.hasAttribute("contenteditable")) {
        var sel = window.getSelection();
        live = !!(sel && sel.rangeCount &&
                  focusCell.contains(sel.getRangeAt(0).commonAncestorContainer));
      }
      INLINE_CMDS.forEach(function (cmd) {
        var btn = toolbar.querySelector('[data-cmd="' + cmd + '"]');
        if (!btn) return;
        var on = false;
        if (live) {
          try { on = document.queryCommandState(cmd); } catch (e) { on = false; }
        }
        btn.classList.toggle("is-on", !!on);
      });
      // The active slot comes from the caret's ancestor class, not from
      // queryCommandState -- colour is a class, not an execCommand format.
      var slot = (live && window.libliColour)
        ? window.libliColour.activeSlot(focusCell) : null;
      COLOUR_SLOTS.forEach(function (name) {
        var btn = toolbar.querySelector('[data-cmd="colour-' + name + '"]');
        if (btn) btn.classList.toggle("is-on", slot === name);
      });
    }

    function refreshToolbarState() {
      if (!toolbar) return;
      var mergeBtn = toolbar.querySelector("[data-merge]");
      var splitBtn = toolbar.querySelector("[data-split]");
      var headerBtn = toolbar.querySelector("[data-header-toggle]");
      var imgBtn = toolbar.querySelector("[data-image-toggle]");
      // Derived ONCE at the top, null-safe, and used by BOTH the [data-cmd] loop and
      // the showCellCtl block below. `var` hoisting would otherwise leave it
      // `undefined` at the loop, making the predicate `!focusCell || undefined` ->
      // falsy -> [data-cmd] ENABLED on a focused image cell.
      var isImage = !!focusCell && focusCell.hasAttribute("data-image");
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
      // Task 12 already renders [data-header-toggle], so headerBtn is non-null.
      if (headerBtn) refreshHeaderButton(headerBtn);

      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-cmd]"), function (btn) {
        btn.disabled = !focusCell || isImage;
      });
      // Its OWN predicate: it must stay ENABLED on an image cell, because that is the
      // re-pick path. Folding it into the loop above makes re-pick unreachable.
      if (imgBtn) imgBtn.disabled = !focusCell;
      Array.prototype.forEach.call(
        toolbar.querySelectorAll("[data-halign], [data-valign]"),
        function (btn) { btn.disabled = !focusCell; }
      );

      var showCellCtl = isImage;
      if (imageAlt) {
        imageAlt.hidden = !showCellCtl;
        if (showCellCtl) imageAlt.value = focusCell.dataset.alt || "";
      }
      if (sizeSel) {
        sizeSel.hidden = !showCellCtl;
        if (showCellCtl) sizeSel.value = focusCell.dataset.size || CELL_IMAGE_DEFAULT;
      }
      if (removeBtn) removeBtn.hidden = !showCellCtl;

      refreshAlignButtons();
      refreshInlineButtons();
    }

    // "Already promoted" must mean exactly what the RENDER templates mean, or
    // the editor and the renderer disagree about which cells are covered:
    //   header_row -> row 0
    //   header_col -> each row's POSITIONALLY FIRST cell (forloop.first), NOT
    //                 layout column 0 -- on a ragged grid these diverge.
    function headerLocked(td) {
      var tr = td.parentNode;
      var rows = desc.rows();
      if (thRow && thRow.checked && rows.indexOf(tr) === 0) return true;
      if (thCol && thCol.checked && desc.cells(tr)[0] === td) return true;
      return false;
    }

    function refreshHeaderButton(btn) {
      var locked = focusCell ? headerLocked(focusCell) : false;
      btn.disabled = !focusCell || locked;
      btn.setAttribute(
        "aria-pressed", String(!!focusCell && focusCell.tagName === "TH")
      );
      btn.classList.toggle("is-on", !!focusCell && focusCell.tagName === "TH");
      btn.title = locked ? msg("header-locked") : msg("header");
    }

    // td <-> th is a NEW element, so every live reference to the old node must
    // be re-pointed or it silently dangles.
    function toggleHeaderCell(td) {
      if (!td) return;
      var tag = td.tagName === "TH" ? "td" : "th";
      var next = document.createElement(tag);
      var i;
      for (i = 0; i < td.attributes.length; i++) {
        next.setAttribute(td.attributes[i].name, td.attributes[i].value);
      }
      // MOVE the children rather than re-serializing: a live
      // .filltable-editor__answer input must keep its typed value and its
      // event bindings.
      while (td.firstChild) next.appendChild(td.firstChild);
      td.replaceWith(next);
      // A stashed cell's html must follow the node, or header-toggling an image
      // cell orphans its stash and Remove image restores nothing.
      if (cellStash.has(td)) {
        cellStash.set(next, cellStash.get(td));
        cellStash.delete(td);
      }
      if (focusCell === td) focusCell = next;
      if (rangeAnchor === td) rangeAnchor = next;   // rangeEnd is a coordinate
      next.focus();
      refreshToolbarState();
      serialize();
    }

    // Non-empty means: static html that is not blank, OR any answer cell, OR
    // any image cell -- so a merge can never silently lose an accepted answer
    // or an image's media pk.
    function absorbedNonEmpty(rg) {
      for (var i = 0; i < rg.cells.length; i++) {
        var c = rg.cells[i];
        if (c === rg.anchor) continue;
        if (cellIsNonEmpty(c)) return true;
      }
      return false;
    }

    function cellIsNonEmpty(c) {
      return c.textContent.trim() !== ""
        || c.querySelector("img") !== null
        || c.hasAttribute("data-image");
    }

    grid.addEventListener("focusin", function (e) {
      var td = e.target.closest(
        "td[contenteditable], th[contenteditable], td[data-image], th[data-image]"
      );
      if (!td) return;
      focusCell = td;
      rangeAnchor = td;   // a plain click ALWAYS re-seats the anchor, so a
                          // stale anchor from an earlier merge can never
                          // silently re-appear in the next range
      clearRange(false);  // ... and drops any live range
      refreshToolbarState();   // replaces the bare refreshAlignButtons() call:
                               // Split and Header enablement both read
                               // focusCell, so the toolbar must recompute
                               // whenever focus moves
    });

    // Caret moves inside a cell change the inline state without ever changing
    // focusCell, so focusin alone would leave the buttons reporting whatever the
    // format was when the cell was entered. selectionchange is document-scoped
    // (there is no element-scoped equivalent) and cheap: refreshInlineButtons
    // reads a handful of nodes and settles to "all off" for any selection that
    // is not inside this editor's focused cell -- which is exactly what clicking
    // away must do. isConnected skips grids left behind by a fragment swap.
    document.addEventListener("selectionchange", function () {
      if (!grid.isConnected) return;
      refreshInlineButtons();
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

    // Registered on the GRID, not the document, so it is scoped to the editor
    // that owns it (a page can hold more than one).
    grid.addEventListener("keydown", function (e) {
      if (!e.altKey || !e.shiftKey) return;
      var delta = { ArrowRight: [0, 1], ArrowLeft: [0, -1],
                    ArrowDown: [1, 0], ArrowUp: [-1, 0] }[e.key];
      if (!delta) return;
      e.preventDefault();
      if (!focusCell) return;                   // no-op, never a throw
      var sm = libliTableGrid.slotMap(desc);
      if (!rangeEnd) {
        // Seed from focusCell's ANCHOR slot AND apply the move in the same
        // keystroke, so one press already selects two slots.
        rangeEnd = libliTableGrid.anchorOf(sm, focusCell);
        if (!rangeEnd) return;
        rangeAnchor = focusCell;
      }
      var r = Math.min(Math.max(rangeEnd.r + delta[0], 0), sm.height - 1);
      var c = Math.min(Math.max(rangeEnd.c + delta[1], 0), sm.width - 1);
      rangeEnd = { r: r, c: c };                // clamped; edge press is a no-op
      paintRange();                             // re-normalises every keystroke
    });

    grid.addEventListener("keydown", function (e) {
      // Only act -- and only swallow the event -- when a range is actually
      // live, so a stray Escape still reaches the media-picker and math-input
      // modals that share this page.
      if (e.key !== "Escape" || !rangeEnd) return;
      e.stopPropagation();
      clearRange(true);        // rangeAnchor stays at focusCell
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
      // execCommand fires "input" SYNCHRONOUSLY, so apply()'s own execCommand
      // call re-enters this listener while it is still mid-flight, before it
      // has found its SENTINEL markers. Without this guard, mapColours below
      // would strip those markers first and colour-none would be a silent
      // no-op -- see text_toolbar.js's identical guard.
      if (window.libliColour && window.libliColour.isApplying()) return;
      var cell = e.target.closest && e.target.closest("[contenteditable]");
      if (cell && window.libliColour) {
        window.libliColour.mapColours(cell, { dropUnmapped: true });
        if (e.inputType === "insertFromPaste" || e.inputType === "insertFromDrop") {
          window.libliColour.tidyPastedSpans(cell);
        }
      }
      serialize();
    });

    // Every structural edit ends the same way.
    function afterStructuralEdit() {
      cellStash.clear();
      // focusCell is never re-nulled by any delete/merge path, so deleting the row
      // holding the focused image cell leaves it pointing at a DETACHED <td>: the
      // per-cell controls stay visible and populated, and edits write to a node no
      // longer in the grid — silently lost at the next serialize(). Position
      // matters as much as the bytes: placed after this function's
      // refreshToolbarState()/serialize() calls, the toolbar would be repainted
      // from the still-detached node.
      if (focusCell && !focusCell.isConnected) { focusCell = null; rangeAnchor = null; }
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
        if (cmdBtn && focusCell && focusCell.hasAttribute("contenteditable")) {
          var cmd = cmdBtn.getAttribute("data-cmd");
          focusCell.focus();
          if (cmd.indexOf("colour-") === 0 && window.libliColour) {
            var slot = cmd === "colour-none" ? null : cmd.slice("colour-".length);
            // styleWithCSS must be TRUE for colour (this file forces it false for
            // bold/italic/underline); apply() sets and resets it itself.
            window.libliColour.apply(focusCell, slot);
            serialize();
            refreshInlineButtons();
            return;
          }
          if (cmd === "bold" || cmd === "italic" || cmd === "underline") {
            // styleWithCSS=false forces execCommand to emit <b>/<i>/<u> tags
            // rather than inline style="" attributes (CELL_TAGS has no
            // attribute allowlist, so a style attribute would be dropped).
            document.execCommand("styleWithCSS", false, false);
            document.execCommand(cmd, false, null);
            serialize();
            refreshInlineButtons();
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
        var hdrBtn = e.target.closest("[data-header-toggle]");
        if (hdrBtn && !hdrBtn.disabled && focusCell) {
          toggleHeaderCell(focusCell);
          return;
        }
      });
    }

    if (imageAlt) {
      imageAlt.addEventListener("input", function () {
        if (!focusCell || !focusCell.hasAttribute("data-image")) return;
        focusCell.dataset.alt = imageAlt.value;
        var img = focusCell.querySelector(".table-editor__img");
        if (img) img.setAttribute("alt", imageAlt.value);
        serialize();
      });
    }

    if (sizeSel) {
      sizeSel.addEventListener("change", function () {
        if (!focusCell || !focusCell.hasAttribute("data-image")) return;
        focusCell.dataset.size = sizeSel.value;
        var img = focusCell.querySelector(".table-editor__img");
        if (img) {
          // REMOVE all four first: classList.add alone accumulates, and the four
          // modifiers are single-class selectors of identical specificity, so the
          // winner would then be decided by stylesheet source order rather than
          // the author's pick.
          Object.keys(CELL_IMG_CLASS).forEach(function (k) {
            img.classList.remove(CELL_IMG_CLASS[k]);
          });
          img.classList.add(CELL_IMG_CLASS[sizeSel.value]);
        }
        serialize();
      });
    }

    if (removeBtn) {
      removeBtn.addEventListener("click", function () {
        if (!focusCell || !focusCell.hasAttribute("data-image")) return;   // no-op
        var stashed = cellStash.get(focusCell);
        // The NO-STASH case is the DOMINANT one, not an edge case: the stash is
        // populated only by an in-session conversion, so any author who saves,
        // reloads and then removes a server-rendered image cell hits it. A bare
        // `stashed.html` would write the string "undefined".
        focusCell.innerHTML = (stashed && stashed.html != null) ? stashed.html : "";
        focusCell.removeAttribute("data-image");
        delete focusCell.dataset.media;
        delete focusCell.dataset.alt;
        delete focusCell.dataset.size;
        focusCell.removeAttribute("tabindex");
        focusCell.setAttribute("contenteditable", "true");
        refreshToolbarState();
        serialize();
      });
    }

    if (thRow) thRow.addEventListener("change", function () { serialize(); refreshToolbarState(); });
    if (thCol) thCol.addEventListener("change", function () { serialize(); refreshToolbarState(); });
    if (borderSel) borderSel.addEventListener("change", serialize);
  }

  function initTableEditor(root) {
    (root || document).querySelectorAll("[data-table-editor]").forEach(wire);
  }

  window.libliInitTableEditor = initTableEditor;
  initTableEditor(document);
})();
