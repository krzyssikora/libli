(function () {
  "use strict";

  // ---- Fill-in table editor: progressively enhance [data-filltable-editor]
  // blocks. Twin of table_editor.js with one extra cell kind: an ANSWER cell
  // is a <td data-answer> holding a plain <input>, not contenteditable HTML.
  // The hidden input[name="data"] is the SOLE authoritative form field; the
  // grid (td[contenteditable] + td[data-answer]) and controls (checkboxes,
  // select, prompt field) are name-less JS UI mirrored into it via serialize().
  // Row/column insert+delete handles are injected here, exactly as in
  // table_editor.js, so the DOM contract in _edit_filltable.html stays as
  // authored by Task 6.

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

  // A "data cell" is any non-chrome cell, TD or TH: static (contenteditable),
  // answer (td/th[data-answer], NO contenteditable attr), or image. Row/column
  // counting and insert/delete MUST see all kinds, or an answer column would
  // be silently skipped during resize -- and a <th> matched by only half the
  // selectors would be un-focusable, un-alignable and invisible to
  // serialization.
  function dataCells(tr) {
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
    // Inserted rows/columns default to a static cell; the author toggles a
    // specific cell to an answer via the "Answer cell" button afterward.
    var td = document.createElement("td");
    td.setAttribute("contenteditable", "true");
    td.dataset.halign = "left";
    td.dataset.valign = "top";
    td.className = "ta-left va-top";
    return td;
  }

  // Grid handles use the authoring UI's .iconbtn + sprite pattern. Their
  // labels ride on data-msg-* attributes because this markup is built
  // client-side, where {% trans %} is unavailable.
  function label(grid, key, fallback) {
    var editor = grid.closest("[data-filltable-editor]");
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

  // ---- answer helpers (mirror courses.filltable.is_blank_answer in Python) --

  function isBlankAnswer(value) {
    if (typeof value !== "string") return true;
    var parts = value.split("|").map(function (p) { return p.trim(); })
      .filter(function (p) { return p !== ""; });
    return parts.length === 0;
  }

  // ---- wiring ---------------------------------------------------------

  function wire(editor) {
    if (editor.dataset.filltableWired) return;
    editor.dataset.filltableWired = "1";

    var hidden = editor.querySelector('input[name="data"]');
    var grid = editor.querySelector("[data-table-grid]");
    var toolbar = editor.querySelector("[data-table-toolbar]");
    var thRow = editor.querySelector("[data-th-row]");
    var thCol = editor.querySelector("[data-th-col]");
    var borderSel = editor.querySelector("[data-border]");
    var caseSensitive = editor.querySelector("[data-case-sensitive]");
    var promptField = editor.querySelector("[data-prompt]");
    var imageAlt = editor.querySelector("[data-image-alt]");
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

    // Per-node stash of the content the OTHER kind held, so an accidental
    // static<->answer toggle round-trip does not lose the author's work.
    // Keyed by the live <td> node (not row/col index, which shifts on
    // insert/delete) and cleared on any structural edit — see below.
    var cellStash = new Map();

    function serialize() {
      var cells = [];
      dataRows(grid).forEach(function (tr) {
        var row = [];
        Array.prototype.forEach.call(dataCells(tr), function (td) {
          if (td.hasAttribute("data-image")) {
            var cell = {
              kind: "image",
              media: parseInt(td.dataset.media, 10),
              alt: td.dataset.alt || "",
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
            if (td.colSpan > 1) cell.colspan = td.colSpan;
            if (td.rowSpan > 1) cell.rowspan = td.rowSpan;
            if (td.tagName === "TH") cell.header = true;
            row.push(cell);
          } else if (td.hasAttribute("data-answer")) {
            var input = td.querySelector(".filltable-editor__answer");
            var cell = {
              kind: "answer",
              answer: input ? input.value : "",
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
            if (td.colSpan > 1) cell.colspan = td.colSpan;
            if (td.rowSpan > 1) cell.rowspan = td.rowSpan;
            if (td.tagName === "TH") cell.header = true;
            row.push(cell);
          } else {
            var cell = {
              kind: "static",
              html: td.innerHTML,
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
            if (td.colSpan > 1) cell.colspan = td.colSpan;
            if (td.rowSpan > 1) cell.rowspan = td.rowSpan;
            if (td.tagName === "TH") cell.header = true;
            row.push(cell);
          }
        });
        cells.push(row);
      });
      hidden.value = JSON.stringify({
        header_row: !!(thRow && thRow.checked),
        header_col: !!(thCol && thCol.checked),
        border: (borderSel && borderSel.value) || "grid",
        case_sensitive: !!(caseSensitive && caseSensitive.checked),
        prompt: (promptField && promptField.value) || "",
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

    // focusCell is the SINGLE authority for what the toolbar acts on
    // (Task 16 renamed this from the file's earlier per-cell tracking var).
    // It is set on plain click/focusin
    // and deliberately NOT moved by Shift+click: suppressing the Shift
    // mousedown also suppresses focus movement, so document.activeElement is
    // unusable.
    var focusCell = null;
    var rangeAnchor = null;   // a cell node
    var rangeEnd = null;      // a LAYOUT {r, c} coordinate, not a node

    function answerPlaceholder() {
      return editor.getAttribute("data-msg-answer-placeholder") || "Accepted answer";
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

    function clearRange(announce) {
      rangeEnd = null;
      Array.prototype.forEach.call(
        grid.querySelectorAll(".is-range"),
        function (c) { c.classList.remove("is-range"); }
      );
      if (announce) say("range-cleared");
      refreshToolbarState();
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
      var locked = focusCell ? headerLocked(focusCell) : true;
      btn.disabled = !focusCell || locked;
      btn.setAttribute(
        "aria-pressed", String(!!focusCell && focusCell.tagName === "TH")
      );
      btn.classList.toggle("is-on", !!focusCell && focusCell.tagName === "TH");
      btn.title = locked ? msg("header-locked") : msg("header");
    }

    // Rich-text commands (bold/italic/underline/math) only make sense on a
    // contenteditable (static) cell; the "Answer cell" toggle stays live so
    // the author can always flip an answer cell back to static first.
    function refreshToolbarState() {
      if (!toolbar) return;              // was part of the combined guard
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
      if (headerBtn) refreshHeaderButton(headerBtn);
      if (!focusCell) return;            // the rest of the original body
      var isAnswer = focusCell.hasAttribute("data-answer");
      var isImage = focusCell.hasAttribute("data-image");
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-cmd]"), function (btn) {
        btn.disabled = isAnswer || isImage;
      });
      var answerBtn = toolbar.querySelector("[data-answer-toggle]");
      if (answerBtn) answerBtn.classList.toggle("is-on", isAnswer);
      if (imageAlt && !isImage) imageAlt.hidden = true;
      refreshAlignButtons();   // this file's refreshToolbarState owns the
                                // align-button refresh too (see focusin below)
    }

    // Per-node stash holding BOTH kinds' last-known content, so a toggle
    // round-trip is fully reversible in either direction: each side seeds from
    // its own remembered value rather than the far side clobbering a single
    // slot. First-time static->answer seeds empty (no answer stashed yet).
    function stashFor(td) {
      var s = cellStash.get(td);
      if (!s) {
        s = { html: null, answer: null };
        cellStash.set(td, s);
      }
      return s;
    }

    // Convert `td` to an image cell holding the picked asset. Stashes the
    // prior kind's content (reusing stashFor, so the toggle back to static
    // via toggleAnswerCell restores it) and immediately reveals + populates
    // the alt input — a later focusin is NOT relied upon, since the caller
    // (the picker callback) already knows which cell it targeted.
    function setImageCell(td, mediaInt, url, alt) {
      var s = stashFor(td);
      if (td.hasAttribute("data-answer")) {
        var input = td.querySelector(".filltable-editor__answer");
        s.answer = input ? input.value : "";
      } else {
        s.html = td.innerHTML;
      }
      td.setAttribute("data-image", "");
      td.dataset.media = String(mediaInt);
      td.dataset.alt = alt || "";
      td.setAttribute("tabindex", "0");
      td.innerHTML = "";
      // DOM property assignment (not innerHTML string concat) so a `"` or `<`
      // in a free-typed alt cannot break out of the attribute/markup.
      var img = document.createElement("img");
      img.className = "filltable-editor__img";
      img.src = url;
      img.alt = alt || "";
      td.appendChild(img);
      td.removeAttribute("contenteditable");
      td.removeAttribute("data-answer");
      if (imageAlt) {
        imageAlt.hidden = false;
        imageAlt.value = td.dataset.alt || "";
      }
    }

    // Single global; assumes one fill-table editor per page (like libliGalleryAdd).
    window.libliFillTablePickImage = function (_pick) {
      var target = focusCell;          // the cell the toggle was clicked on
      return function (id, _name, url) { // picker callback: id is a STRING
        setImageCell(target, parseInt(id, 10), url, target.dataset.alt || "");
        focusCell = target;            // keep focus on the converted cell
        serialize();
      };
    };

    // Toggle the tracked active cell between static (contenteditable HTML)
    // and answer (plain <input>). Reversible: the content being replaced is
    // remembered in the node's stash so toggling back restores it (rather than
    // silently discarding whatever the author had typed on either side).
    function toggleAnswerCell(td) {
      if (!td) return;
      if (td.hasAttribute("data-image")) {          // image -> static (one step)
        var stashed = stashFor(td);
        td.removeAttribute("data-image");
        delete td.dataset.media;
        delete td.dataset.alt;
        td.removeAttribute("tabindex");
        td.innerHTML = stashed.html != null ? stashed.html : "";
        td.setAttribute("contenteditable", "true");
        if (imageAlt) imageAlt.hidden = true;
        focusCell = td;
        refreshToolbarState();
        serialize();
        return;
      }
      var s = stashFor(td);
      if (td.hasAttribute("data-answer")) {
        // answer -> static: remember the typed answer, restore stashed html
        var input = td.querySelector(".filltable-editor__answer");
        s.answer = input ? input.value : "";
        td.innerHTML = s.html != null ? s.html : "";
        td.setAttribute("contenteditable", "true");
        td.removeAttribute("data-answer");
      } else {
        // static -> answer: remember the html, restore stashed answer (empty first time)
        s.html = td.innerHTML;
        td.innerHTML = "";
        var inp = document.createElement("input");
        inp.type = "text";
        inp.className = "filltable-editor__answer";
        inp.placeholder = answerPlaceholder();
        inp.value = s.answer != null ? s.answer : "";
        td.appendChild(inp);
        td.setAttribute("data-answer", "");
        td.removeAttribute("contenteditable");
        inp.focus();
      }
      focusCell = td;
      refreshToolbarState();
      serialize();
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
      // cellStash is LIVE here (unlike table_editor.js's no-op guard), so a
      // stashed answer/html round-trip must follow the node.
      if (cellStash.has(td)) {
        cellStash.set(next, cellStash.get(td));
        cellStash.delete(td);
      }
      if (focusCell === td) focusCell = next;
      if (rangeAnchor === td) rangeAnchor = next;   // rangeEnd is a coordinate
      // .focus() is a no-op on a <td data-answer> (no tabindex, not
      // contenteditable) -- fall back to its live answer input so the
      // grid-scoped keyboard chord (Alt+Shift+Arrow) stays reachable.
      (next.querySelector(".filltable-editor__answer") || next).focus();
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

    // A merge must not silently lose an accepted answer or an image's media
    // pk, so ANY answer or image cell counts as non-empty regardless of what
    // it displays.
    function cellIsNonEmpty(c) {
      if (c.hasAttribute("data-answer") || c.hasAttribute("data-image")) return true;
      return c.textContent.trim() !== "";
    }

    grid.addEventListener("focusin", function (e) {
      var td = e.target.closest(
        "td[contenteditable], th[contenteditable], td[data-answer], th[data-answer], td[data-image], th[data-image]"
      );
      if (!td) return;
      focusCell = td;
      rangeAnchor = td;   // a plain click ALWAYS re-seats the anchor, so a
                          // stale anchor from an earlier merge can never
                          // silently re-appear in the next range
      clearRange(false);  // ... and drops any live range
      if (toolbar) toolbar.hidden = false;
      refreshToolbarState();   // ends with refreshAlignButtons(): Split and
                               // Header enablement both read focusCell, so
                               // the toolbar must recompute whenever focus
                               // moves, and alignment tracks it too
      if (td.hasAttribute("data-image") && imageAlt) {
        imageAlt.hidden = false;
        imageAlt.value = td.dataset.alt || "";
      }
    });

    // Chrome and genuine multi-line controls are excluded, but the fill-table's
    // ANSWER INPUT is not: it is styled full-cell, so it covers essentially the
    // whole answer cell. Excluding it would leave an author with no way to make
    // an answer cell a range endpoint at all -- which this task's first test
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
        // nothing in the grid has DOM focus and the grid-scoped keyboard
        // chord would stay unreachable until the author clicked again.
        // .focus() is a no-op on a <td data-answer> -- fall back to its
        // live answer input.
        (td.querySelector(".filltable-editor__answer") || td).focus();
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
    // intra-content separator is <br> (matches CELL_TAGS). Answer cells are
    // plain <input> elements, so this never applies to them.
    grid.addEventListener("keydown", function (e) {
      var td = e.target.closest("td[contenteditable], th[contenteditable]");
      if (!td) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        document.execCommand("insertHTML", false, "<br>");
        serialize();
      }
    });

    // Delegated on the grid so it also covers .filltable-editor__answer
    // inputs — including ones created later by the Answer-cell toggle,
    // without needing a per-input listener.
    grid.addEventListener("input", function (e) {
      if (e.target.closest("td[contenteditable], th[contenteditable]")) { serialize(); return; }
      if (e.target.classList && e.target.classList.contains("filltable-editor__answer")) {
        serialize();
      }
    });

    // Every structural edit ends the same way.
    function afterStructuralEdit() {
      cellStash.clear(); // fill-table only
      clearRange(false);
      rebuildColControls(grid, desc);
      refreshControlState(grid, desc);
      refreshToolbarState();
      serialize();
    }

    // Row/column insert+delete handles (delegated). Any structural edit
    // discards the stash: a stash could otherwise restore into the wrong
    // node after the grid reshapes.
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
        var answerToggleBtn = e.target.closest("[data-answer-toggle]");
        if (answerToggleBtn) {
          if (focusCell) toggleAnswerCell(focusCell);
          return;
        }
        var cmdBtn = e.target.closest("[data-cmd]");
        if (cmdBtn && focusCell && focusCell.hasAttribute("contenteditable")) {
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
            // chord (Alt+Shift+Arrow) would go dead until the author clicked
            // a cell again. .focus() is a no-op on an answer <td> -- fall
            // back to its live answer input.
            (kept.querySelector(".filltable-editor__answer") || kept).focus();
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
          (anchor.querySelector(".filltable-editor__answer") || anchor).focus();
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
        var img = focusCell.querySelector(".filltable-editor__img");
        if (img) img.setAttribute("alt", imageAlt.value);
        serialize();
      });
    }

    if (thRow) thRow.addEventListener("change", function () { serialize(); refreshToolbarState(); });
    if (thCol) thCol.addEventListener("change", function () { serialize(); refreshToolbarState(); });
    if (borderSel) borderSel.addEventListener("change", serialize);
    if (caseSensitive) caseSensitive.addEventListener("change", serialize);
    if (promptField) {
      promptField.addEventListener("input", serialize);
      promptField.addEventListener("change", serialize);
    }

    // Exposed per-editor so the capture-phase submit guard can flush a final
    // serialize() over the live DOM before validating/POSTing.
    editor.__filltableSerialize = serialize;
  }

  // ---- submit guard: block save when no answer cell exists, or one is
  // blank, using the SAME blank rule as courses.filltable.is_blank_answer
  // (split on "|", trim, drop empties). Registered on the document in the
  // CAPTURE phase so it runs before editor.js's bubble-phase save handler
  // (mirrors switchgrid_editor.js's onSubmit). ----

  function clearAnswerError(editor) {
    var el = editor.querySelector("[data-answer-error]");
    if (el) el.remove();
  }

  function showAnswerError(editor, text) {
    clearAnswerError(editor);
    var p = document.createElement("p");
    p.className = "field-error el-editor__answer-error";
    p.setAttribute("data-answer-error", "");
    p.textContent = text;
    editor.appendChild(p);
    p.scrollIntoView({ block: "center" });
  }

  function onSubmit(e) {
    var form = e.target;
    if (!form.querySelector) return;
    var editor = form.querySelector("[data-filltable-editor]");
    if (!editor) return;
    var grid = editor.querySelector("[data-table-grid]");
    if (!grid) return;
    if (editor.__filltableSerialize) editor.__filltableSerialize();
    clearAnswerError(editor);
    var answerInputs = Array.prototype.slice.call(
      grid.querySelectorAll(
        "td[data-answer] .filltable-editor__answer, th[data-answer] .filltable-editor__answer"
      )
    );
    if (answerInputs.length === 0) {
      e.preventDefault();
      e.stopPropagation();
      showAnswerError(
        editor,
        editor.getAttribute("data-msg-no-answer") ||
          "Mark at least one answer cell (use the “Answer cell” button)."
      );
      return;
    }
    var blank = answerInputs.some(function (inp) { return isBlankAnswer(inp.value); });
    if (blank) {
      e.preventDefault();
      e.stopPropagation();
      showAnswerError(
        editor,
        editor.getAttribute("data-msg-answer-blank") ||
          "An answer cell is blank — type its accepted answer, or make it a normal cell."
      );
    }
  }

  document.addEventListener("submit", onSubmit, true); // capture: run before the POST

  function initFillTableEditor(root) {
    (root || document).querySelectorAll("[data-filltable-editor]").forEach(wire);
  }

  window.libliInitFillTableEditor = initFillTableEditor;
  initFillTableEditor(document);
})();
