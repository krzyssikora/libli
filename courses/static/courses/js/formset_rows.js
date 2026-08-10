/* Generic add/remove for Django inline formsets, driven entirely by data
   attributes so no per-element JS is needed. Sibling module: switchgate_editor.js
   (a positional list, NOT a formset — it detaches rows; this one never does).

   Contract on the wrapper: data-fsrows="<prefix>", -confirm, -list, -min, -max,
   -hint, -atmin, -atcap, -add, -template. Per row: data-fsrow-item,
   data-fsrow-del, data-fsrow-remove.

   Delegated at document level (like switchgrid_editor.js) so fragment swaps need
   no re-wiring; the exported init pass exists for the progressive-enhancement
   reveal and the 422 reconciliation, which delegation cannot do. */
(function () {
  "use strict";
  var WRAP = "[data-fsrows]";
  var FALLBACK_CONFIRM = "Remove this row?";

  function wrappers(root) {
    var scope = root || document;
    // querySelectorAll finds DESCENDANTS only; addChoiceRow hands us the wrapper
    // itself while editor.js hands us an ancestor. Mirrors syncChoiceFeedback.
    if (scope.matches && scope.matches(WRAP)) return [scope];
    return Array.prototype.slice.call(scope.querySelectorAll(WRAP));
  }

  function rowsOf(wrap) {
    var list = wrap.querySelector("[data-fsrows-list]");
    if (!list) return [];
    return Array.prototype.slice.call(list.querySelectorAll("[data-fsrow-item]"));
  }

  function visibleRows(wrap) {
    return rowsOf(wrap).filter(function (r) { return !r.hidden; });
  }

  function firstText(row) {
    return row.querySelector('input[type="text"]') || row.querySelector("textarea");
  }

  function filledCount(wrap) {
    return visibleRows(wrap).filter(function (r) {
      var f = firstText(r);
      return f && f.value.trim() !== "";
    }).length;
  }

  function isEmptyRow(row) {
    var fields = row.querySelectorAll('input[type="text"], textarea');
    for (var i = 0; i < fields.length; i++) {
      if (fields[i].value.trim() !== "") return false;
    }
    return true;
  }

  function totalInput(wrap) {
    var prefix = wrap.getAttribute("data-fsrows") || "";
    return wrap.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');
  }

  function delInput(row) { return row.querySelector('[name$="-DELETE"]'); }

  function num(wrap, attr, fallback) {
    var raw = wrap.getAttribute(attr);
    if (raw === null || raw === "") return fallback;
    var n = parseInt(raw, 10);
    return isNaN(n) ? fallback : n;
  }

  /* ---- job 3: bounds ---- */
  function recompute(wrap) {
    var min = num(wrap, "data-fsrows-min", 1);
    var max = num(wrap, "data-fsrows-max", Infinity);
    var visible = visibleRows(wrap);
    var atMin = visible.length <= min;
    // The max counts NON-BLANK rows, not rows: extra=1 means a 19-step stepper
    // renders 20 rows, and a row-based cap would disable Add at nineteen.
    var atMax = filledCount(wrap) >= max;

    visible.forEach(function (row) {
      var btn = row.querySelector("[data-fsrow-remove]");
      if (btn) btn.disabled = atMin;
    });

    var add = wrap.querySelector("[data-fsrows-add], [data-choice-add]");
    if (add) add.disabled = atMax;

    var hint = wrap.querySelector("[data-fsrows-hint]");
    if (!hint) return;
    var msg = atMax
      ? wrap.getAttribute("data-fsrows-atcap")
      : atMin
        ? wrap.getAttribute("data-fsrows-atmin")
        : null;
    // A greyed-out control with no explanation is its own small version of the
    // dead-button defect this module exists to fix.
    hint.textContent = msg || "";
    hint.hidden = !msg;
  }

  /* ---- init: three idempotent jobs ---- */
  function initOne(wrap) {
    // job 1 — swap the no-JS DELETE label for the JS-only buttons.
    // Array.prototype.forEach.call, not NodeList.forEach: matches editor.js and the
    // rest of this file's ES5 idiom.
    Array.prototype.forEach.call(wrap.querySelectorAll("[data-fsrow-item]"), function (row) {
      var label = row.querySelector("[data-fsrow-del]");
      if (!label) {
        if (window.console) console.warn("formset_rows: row without [data-fsrow-del]", row);
        return;
      }
      label.hidden = true;
      var btn = row.querySelector("[data-fsrow-remove]");
      if (btn) btn.hidden = false;
    });
    var add = wrap.querySelector("[data-fsrows-add], [data-choice-add]");
    if (add) add.hidden = false;

    // job 2 — reconcile a 422 re-render, but never below the minimum. Without the
    // floor, a no-JS author who ticked every row and hit a validation error comes
    // back to zero visible rows, no way to untick, and (for choice) nothing to
    // clone: an unrecoverable editor.
    var min = num(wrap, "data-fsrows-min", 1);
    var ticked = rowsOf(wrap).filter(function (r) {
      var d = delInput(r);
      return d && d.checked;
    });
    var keepVisible = rowsOf(wrap).length - ticked.length;
    ticked.forEach(function (row) {
      var d = delInput(row);
      if (keepVisible < min) {
        // State and appearance must never disagree — so un-tick AND un-hide.
        // Un-ticking alone holds today only because every reachable caller runs on
        // a server-fresh DOM where nothing is hidden yet. On the addRow -> init
        // re-init path the ticked rows are already hidden, so a row rescued here
        // would post as KEPT (silently resurrecting its old content) while staying
        // invisible to the author.
        d.checked = false;
        row.hidden = false;
        keepVisible += 1;
        return;
      }
      row.hidden = true;
    });

    // job 3 — bounds.
    recompute(wrap);
  }

  function initFormsetRows(root) { wrappers(root).forEach(initOne); }

  /* ---- add ---- */
  function addRow(wrap) {
    var tmpl = wrap.querySelector("[data-fsrows-template]");
    var list = wrap.querySelector("[data-fsrows-list]");
    var total = totalInput(wrap);
    if (!tmpl || !list || !total) {
      // Loud, because a silent no-op here IS the reported defect.
      if (window.console) console.warn("formset_rows: add is not wired on", wrap);
      return;
    }
    var idx = parseInt(total.value, 10) || 0;
    var holder = document.createElement("div");
    holder.innerHTML = tmpl.innerHTML.replace(/__prefix__/g, String(idx)).trim();
    var row = holder.firstElementChild;
    if (!row) return;
    list.appendChild(row);
    total.value = String(idx + 1);
    // Mandatory: the blueprint copies the loop body verbatim, so the new row
    // arrives with a VISIBLE DELETE label and a HIDDEN remove button.
    initFormsetRows(wrap);
    if (window.libliAlignTopInPane) window.libliAlignTopInPane(row);
    var target = firstText(row);
    // preventScroll: the editor viewport is overflow:hidden, so a bare focus()
    // scrolls every ancestor scrollport and the author cannot scroll back.
    if (target) target.focus({ preventScroll: true });
  }

  /* ---- remove ---- */
  function focusable(el) { return el && !el.hidden && !el.disabled; }

  function removeRow(wrap, row) {
    var min = num(wrap, "data-fsrows-min", 1);
    if (visibleRows(wrap).length <= min) return;   // guard; button is disabled too
    if (!isEmptyRow(row)) {
      var msg = wrap.getAttribute("data-fsrows-confirm");
      if (!msg) {
        if (window.console) console.warn("formset_rows: no data-fsrows-confirm on", wrap);
        msg = FALLBACK_CONFIRM;   // never window.confirm(null) -> a dialog reading "null"
      }
      if (!window.confirm(msg)) return;
    }
    var d = delInput(row);
    if (!d) {
      if (window.console) console.warn("formset_rows: row has no DELETE input", row);
      return;
    }
    var after = visibleRows(wrap).filter(function (r) {
      return r !== row && row.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING;
    });
    var before = visibleRows(wrap).filter(function (r) {
      return r !== row && row.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_PRECEDING;
    });

    d.checked = true;
    row.hidden = true;
    recompute(wrap);   // AFTER hiding, so the disabled state reflects the new count

    // Focus would otherwise fall to <body>. Candidates must be FOCUSABLE, not
    // merely present: at the minimum boundary recompute() has just disabled every
    // remove button, and focus() on a disabled button is a silent no-op.
    var candidates = [];
    if (after[0]) candidates.push(after[0].querySelector("[data-fsrow-remove]"));
    if (before[before.length - 1]) {
      candidates.push(before[before.length - 1].querySelector("[data-fsrow-remove]"));
    }
    var near = after[0] || before[before.length - 1];
    if (near) candidates.push(firstText(near));   // always focusable; min >= 1
    for (var i = 0; i < candidates.length; i++) {
      if (focusable(candidates[i])) {
        candidates[i].focus({ preventScroll: true });
        return;
      }
    }
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest) return;   // non-Element target (synthetic dispatch)
    var add = e.target.closest("[data-fsrows-add]");
    if (add) {
      var w = add.closest(WRAP);
      if (w) addRow(w);
      return;
    }
    var rm = e.target.closest("[data-fsrow-remove]");
    if (rm) {
      var wrap = rm.closest(WRAP);
      var row = rm.closest("[data-fsrow-item]");
      if (wrap && row) removeRow(wrap, row);
    }
  });

  // The max counts non-blank rows, so typing can cross it.
  document.addEventListener("input", function (e) {
    var wrap = e.target.closest && e.target.closest(WRAP);
    if (wrap) recompute(wrap);
  });

  window.libliInitFormsetRows = initFormsetRows;
  document.addEventListener("DOMContentLoaded", function () {
    initFormsetRows(document);
  });
})();
