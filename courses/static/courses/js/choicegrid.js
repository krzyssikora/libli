(function () {
  "use strict";

  // Matrix (choice-grid) authoring enhancer. The edit partial ships two inline
  // formsets — columns (label + hidden temp_id) and rows (statement + a
  // correct-column <select> bound to correct_temp_id) — plus <template> clone
  // blueprints and static control hooks. This script:
  //   * assigns a stable temp_id to every column that lacks one,
  //   * rebuilds each row's correct-column <select> from the current columns
  //     (option value = column temp_id, text = label) whenever columns change,
  //   * wires Add column / Add row / True-False preset / Remove,
  //   * seeds a starter UI (2 columns + 1 row) on a FRESH grid only, and
  //   * runs KaTeX auto-render over the editor if it is loaded.
  // Wiring mirrors switchgrid_editor.js: one set of document-level delegated
  // listeners (added once) plus window.libliInitChoiceGrid(root) for re-sync
  // after each editor.js fragment swap.

  var counter = 0;
  function freshTempId() {
    counter += 1;
    return "t" + Date.now().toString(36) + "-" + counter;
  }

  function cols(editor) {
    return Array.prototype.slice.call(
      editor.querySelectorAll("[data-choicegrid-col]")
    );
  }
  function rows(editor) {
    return Array.prototype.slice.call(
      editor.querySelectorAll("[data-choicegrid-row]")
    );
  }
  function tempIdInput(col) {
    return col.querySelector('input[name$="-temp_id"]');
  }
  function labelInput(col) {
    return col.querySelector('input[name$="-label"]');
  }
  function isDeleted(item) {
    var del = item.querySelector('input[name$="-DELETE"]');
    return !!(del && del.checked);
  }
  function totalForms(editor, prefix) {
    return editor.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');
  }
  function editorOf(node) {
    return node.closest ? node.closest("[data-choicegrid-editor]") : null;
  }

  // Inline math for the editor (labels/statements may carry \(...\) / \[...\]).
  // auto-render.min.js loads deferred, so guard on the global.
  function renderPreviewMath(scope) {
    if (typeof renderMathInElement !== "function" || !scope) return;
    try {
      renderMathInElement(scope, {
        delimiters: [
          { left: "\\(", right: "\\)", display: false },
          { left: "\\[", right: "\\]", display: true },
        ],
        throwOnError: false,
      });
    } catch (e) {
      /* leave raw LaTeX on error */
    }
  }

  // Ensure every column carries a temp_id. Saved columns keep whatever the
  // server rendered; a blank one (new or unseeded) gets a fresh id.
  function assignTempIds(editor) {
    cols(editor).forEach(function (col) {
      var ti = tempIdInput(col);
      if (ti && !ti.value) ti.value = freshTempId();
    });
  }

  // Current (non-deleted) columns as [{ tempId, label }].
  function currentColumns(editor) {
    return cols(editor)
      .filter(function (c) {
        return !isDeleted(c);
      })
      .map(function (c) {
        var ti = tempIdInput(c);
        var lbl = labelInput(c);
        return {
          tempId: ti ? ti.value : "",
          label: lbl ? lbl.value : "",
        };
      })
      .filter(function (c) {
        return c.tempId;
      });
  }

  // Rebuild each row's correct-column <select> from the current columns,
  // preserving the selected temp_id via the select's data-value (the single
  // source of truth: seeded by the server, updated on every user change).
  function syncSelects(editor) {
    var columns = currentColumns(editor);
    rows(editor).forEach(function (row) {
      var sel = row.querySelector("[data-choicegrid-correct]");
      if (!sel) return;
      var current = sel.getAttribute("data-value") || "";
      var placeholder = sel.querySelector('option[value=""]');
      var placeholderText = placeholder ? placeholder.textContent : "";
      sel.innerHTML = "";
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = placeholderText;
      sel.appendChild(blank);
      var matched = false;
      columns.forEach(function (col) {
        var opt = document.createElement("option");
        opt.value = col.tempId;
        opt.textContent = col.label;
        if (col.tempId === current) {
          opt.selected = true;
          matched = true;
        }
        sel.appendChild(opt);
      });
      // The selected column may have been removed -> fall back to the blank
      // option and keep data-value in step so a later resync doesn't resurrect it.
      if (!matched) {
        sel.value = "";
        sel.setAttribute("data-value", "");
      }
    });
  }

  function cloneTemplate(editor, sel) {
    var t = editor.querySelector("template[" + sel + "]");
    return t ? t.content.firstElementChild.cloneNode(true) : null;
  }

  // Renumber a cloned formset row: every __prefix__ placeholder -> idx.
  function renumber(node, idx) {
    Array.prototype.forEach.call(
      node.querySelectorAll("[name],[id],[for]"),
      function (el) {
        ["name", "id", "for"].forEach(function (attr) {
          var v = el.getAttribute(attr);
          if (v) el.setAttribute(attr, v.split("__prefix__").join(idx));
        });
      }
    );
  }

  function addColumn(editor, label) {
    var total = totalForms(editor, "columns");
    var list = editor.querySelector("[data-choicegrid-cols]");
    if (!total || !list) return null;
    var idx = parseInt(total.value, 10) || 0;
    var node = cloneTemplate(editor, "data-choicegrid-col-template");
    if (!node) return null;
    renumber(node, idx);
    list.appendChild(node);
    total.value = idx + 1;
    var ti = tempIdInput(node);
    if (ti) ti.value = freshTempId();
    if (label != null) {
      var lbl = labelInput(node);
      if (lbl) lbl.value = label;
    }
    return node;
  }

  function addRow(editor) {
    var total = totalForms(editor, "rows");
    var list = editor.querySelector("[data-choicegrid-rows]");
    if (!total || !list) return null;
    var idx = parseInt(total.value, 10) || 0;
    var node = cloneTemplate(editor, "data-choicegrid-row-template");
    if (!node) return null;
    renumber(node, idx);
    list.appendChild(node);
    total.value = idx + 1;
    return node;
  }

  // Localised True/False labels come from data-* attrs on the preset button
  // (JS strings are not extracted by makemessages); English is the fallback.
  function presetLabel(editor, which, fallback) {
    var btn = editor.querySelector("[data-choicegrid-tf-preset]");
    return (btn && btn.getAttribute("data-" + which)) || fallback;
  }

  function tfPreset(editor) {
    addColumn(editor, presetLabel(editor, "true", "True"));
    addColumn(editor, presetLabel(editor, "false", "False"));
    syncSelects(editor);
  }

  // A brand-new grid renders with zero column/row forms (extra=0). Seed the
  // starter UI so the author isn't shown a blank editor. Never re-seed an edit.
  function seedIfFresh(editor) {
    if (cols(editor).length === 0 && rows(editor).length === 0) {
      tfPreset(editor);
      addRow(editor);
      syncSelects(editor);
    }
  }

  function initEditor(editor) {
    assignTempIds(editor);
    if (!editor.dataset.choicegridReady) {
      editor.dataset.choicegridReady = "1";
      seedIfFresh(editor);
    }
    syncSelects(editor);
    renderPreviewMath(editor);
  }

  // ---- delegated events (added once) ----
  document.addEventListener("click", function (e) {
    var editor = editorOf(e.target);
    if (!editor) return;
    if (e.target.closest("[data-choicegrid-add-col]")) {
      addColumn(editor, "");
      syncSelects(editor);
      return;
    }
    if (e.target.closest("[data-choicegrid-tf-preset]")) {
      tfPreset(editor);
      return;
    }
    if (e.target.closest("[data-choicegrid-add-row]")) {
      addRow(editor);
      syncSelects(editor);
      return;
    }
  });

  document.addEventListener("input", function (e) {
    var editor = editorOf(e.target);
    if (!editor) return;
    // A column label changed -> refresh the option text in every row select.
    if (e.target.matches('[data-choicegrid-col] input[name$="-label"]')) {
      syncSelects(editor);
    }
  });

  document.addEventListener("change", function (e) {
    var editor = editorOf(e.target);
    if (!editor) return;
    // Remember the picked column so a later resync keeps it selected.
    if (e.target.matches("[data-choicegrid-correct]")) {
      e.target.setAttribute("data-value", e.target.value);
      return;
    }
    // A column toggled for removal -> drop it from every row select immediately.
    if (e.target.matches('[data-choicegrid-col] input[name$="-DELETE"]')) {
      syncSelects(editor);
    }
  });

  window.libliInitChoiceGrid = function (root) {
    (root || document)
      .querySelectorAll("[data-choicegrid-editor]")
      .forEach(initEditor);
  };
  document.addEventListener("DOMContentLoaded", function () {
    window.libliInitChoiceGrid(document);
  });
})();
