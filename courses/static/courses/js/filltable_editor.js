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
    rebuildColControls(grid);
    refreshControlState(grid);

    // Serialize on init ONLY when the hidden field is empty: covers the add
    // path (captures the default 2x2) and the edit path (captures the
    // server-rendered EXISTING grid, so a Save that never touches the grid
    // does not wipe it). A bound-invalid re-render already has the submitted
    // JSON in the hidden field, so it is skipped here.
    if (hidden.value === "") serialize();

    var focusedCell = null;

    function answerPlaceholder() {
      return editor.getAttribute("data-msg-answer-placeholder") || "Accepted answer";
    }

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

    // Rich-text commands (bold/italic/underline/math) only make sense on a
    // contenteditable (static) cell; the "Answer cell" toggle stays live so
    // the author can always flip an answer cell back to static first.
    function refreshToolbarState() {
      if (!toolbar || !focusedCell) return;
      var isAnswer = focusedCell.hasAttribute("data-answer");
      var isImage = focusedCell.hasAttribute("data-image");
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-cmd]"), function (btn) {
        btn.disabled = isAnswer || isImage;
      });
      var answerBtn = toolbar.querySelector("[data-answer-toggle]");
      if (answerBtn) answerBtn.classList.toggle("is-on", isAnswer);
      if (imageAlt && !isImage) imageAlt.hidden = true;
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
      var target = focusedCell;          // the cell the toggle was clicked on
      return function (id, _name, url) { // picker callback: id is a STRING
        setImageCell(target, parseInt(id, 10), url, target.dataset.alt || "");
        focusedCell = target;            // keep focus on the converted cell
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
        focusedCell = td;
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
      focusedCell = td;
      refreshToolbarState();
      serialize();
    }

    grid.addEventListener("focusin", function (e) {
      var td = e.target.closest(
        "td[contenteditable], th[contenteditable], td[data-answer], th[data-answer], td[data-image], th[data-image]"
      );
      if (!td) return;
      focusedCell = td;
      if (toolbar) toolbar.hidden = false;
      refreshAlignButtons();
      refreshToolbarState();
      if (td.hasAttribute("data-image") && imageAlt) {
        imageAlt.hidden = false;
        imageAlt.value = td.dataset.alt || "";
      }
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

    // Row/column insert+delete handles (delegated). Any structural edit
    // discards the stash: a stash could otherwise restore into the wrong
    // node after the grid reshapes.
    grid.addEventListener("click", function (e) {
      var rowInsert = e.target.closest("[data-row-insert]");
      if (rowInsert) {
        if (rowCount(grid) < MAX_ROWS) {
          var tr = rowInsert.closest("tr");
          var newRow = buildRow(grid, colCount(grid));
          tr.parentNode.insertBefore(newRow, tr.nextSibling);
          cellStash.clear();
          refreshControlState(grid);
          serialize();
        }
        return;
      }
      var rowDelete = e.target.closest("[data-row-delete]");
      if (rowDelete) {
        if (rowCount(grid) > 1) {
          rowDelete.closest("tr").remove();
          cellStash.clear();
          refreshControlState(grid);
          serialize();
        }
        return;
      }
      var colInsert = e.target.closest("[data-col-insert]");
      if (colInsert) {
        if (colCount(grid) < MAX_COLS) {
          insertColumnAfter(grid, parseInt(colInsert.dataset.colIndex, 10));
          cellStash.clear();
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
          cellStash.clear();
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
        var answerToggleBtn = e.target.closest("[data-answer-toggle]");
        if (answerToggleBtn) {
          if (focusedCell) toggleAnswerCell(focusedCell);
          return;
        }
        var cmdBtn = e.target.closest("[data-cmd]");
        if (cmdBtn && focusedCell && focusedCell.hasAttribute("contenteditable")) {
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

    if (imageAlt) {
      imageAlt.addEventListener("input", function () {
        if (!focusedCell || !focusedCell.hasAttribute("data-image")) return;
        focusedCell.dataset.alt = imageAlt.value;
        var img = focusedCell.querySelector(".filltable-editor__img");
        if (img) img.setAttribute("alt", imageAlt.value);
        serialize();
      });
    }

    if (thRow) thRow.addEventListener("change", serialize);
    if (thCol) thCol.addEventListener("change", serialize);
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
