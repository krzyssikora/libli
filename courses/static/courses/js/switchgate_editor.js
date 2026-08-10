/* Choose & confirm (switchgate) option list.

   SIBLING FILES, ONE LETTER APART — do not confuse them:
     switchgate.js         student runtime for this element
     switchgrid_editor.js  a DIFFERENT element's editor

   Switchgate is NOT a formset: options are repeated name="option" inputs read
   positionally via getlist("option"), and the correct answer is a radio whose
   value is the option's INDEX. So a removed row must be DETACHED (a hidden input
   still submits, and clean() rejects interior blanks) and every survivor
   renumbered — otherwise `answer` points at the wrong option. */
(function () {
  "use strict";
  var WRAP = "[data-sgate]";
  var FALLBACK_CONFIRM = "Remove this option?";

  function wrappers(root) {
    var scope = root || document;
    if (scope.matches && scope.matches(WRAP)) return [scope];
    return Array.prototype.slice.call(scope.querySelectorAll(WRAP));
  }

  function rowsOf(wrap) {
    return Array.prototype.slice.call(wrap.querySelectorAll("[data-sgate-row]"));
  }

  function renumber(wrap) {
    // Never parse the rendered placeholder: it is a fully substituted TRANSLATED
    // literal ("Opcja 3" under pl) with no token left, and a /\d+$/ rewrite is
    // locale-fragile. Rebuild from the single template string instead.
    var tmpl = wrap.getAttribute("data-sgate-placeholder") || "";
    rowsOf(wrap).forEach(function (row, i) {
      var radio = row.querySelector('input[name="answer"]');
      if (radio) radio.value = String(i);            // 0-based
      var text = row.querySelector('input[name="option"]');
      if (text) text.placeholder = tmpl.replace(/__pos__/g, String(i + 1));  // 1-based
    });
  }

  function recompute(wrap) {
    var min = parseInt(wrap.getAttribute("data-sgate-min"), 10) || 2;
    var rows = rowsOf(wrap);
    var atMin = rows.length <= min;
    rows.forEach(function (row) {
      var btn = row.querySelector("[data-sgate-remove]");
      if (btn) btn.disabled = atMin;
    });
    var hint = wrap.querySelector("[data-sgate-hint]");
    if (!hint) return;
    var msg = atMin ? wrap.getAttribute("data-sgate-atmin") : null;
    hint.textContent = msg || "";
    hint.hidden = !msg;
  }

  function initOne(wrap) {
    Array.prototype.forEach.call(
      wrap.querySelectorAll("[data-sgate-add], [data-sgate-remove]"),
      function (b) { b.hidden = false; }
    );
    recompute(wrap);
    renumber(wrap);
  }

  function initSwitchGateEditor(root) { wrappers(root).forEach(initOne); }

  function addRow(wrap) {
    var tmpl = wrap.querySelector("[data-sgate-template]");
    var list = wrap.querySelector("[data-sgate-list]");
    if (!tmpl || !list) {
      if (window.console) console.warn("switchgate_editor: add is not wired on", wrap);
      return;
    }
    var idx = rowsOf(wrap).length;
    var holder = document.createElement("div");
    holder.innerHTML = tmpl.innerHTML
      .replace(/__index__/g, String(idx))
      .replace(/__pos__/g, String(idx + 1))
      .trim();
    var row = holder.firstElementChild;
    if (!row) return;
    list.appendChild(row);
    initSwitchGateEditor(wrap);   // the blueprint carries `hidden` on its remove button
    if (window.libliAlignTopInPane) window.libliAlignTopInPane(row);
    var text = row.querySelector('input[name="option"]');
    if (text) text.focus({ preventScroll: true });
  }

  function focusable(el) { return el && !el.hidden && !el.disabled; }

  function removeRow(wrap, row) {
    var min = parseInt(wrap.getAttribute("data-sgate-min"), 10) || 2;
    if (rowsOf(wrap).length <= min) return;
    var text = row.querySelector('input[type="text"]');
    if (text && text.value.trim() !== "") {
      var msg = wrap.getAttribute("data-sgate-confirm");
      if (!msg) {
        if (window.console) console.warn("switchgate_editor: no data-sgate-confirm");
        msg = FALLBACK_CONFIRM;
      }
      if (!window.confirm(msg)) return;
    }
    // Capture BEFORE detaching: once row.remove() runs, its siblings are null and
    // every focus candidate would resolve to nothing.
    var next = row.nextElementSibling;
    var prev = row.previousElementSibling;

    row.remove();
    initSwitchGateEditor(wrap);   // renumber + recompute; the guard is a live check

    var candidates = [];
    if (next) candidates.push(next.querySelector("[data-sgate-remove]"));
    if (prev) candidates.push(prev.querySelector("[data-sgate-remove]"));
    var near = next || prev;
    if (near) candidates.push(near.querySelector('input[name="option"]'));
    for (var i = 0; i < candidates.length; i++) {
      if (focusable(candidates[i])) {
        candidates[i].focus({ preventScroll: true });
        return;
      }
    }
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest) return;   // non-Element target (synthetic dispatch)
    var add = e.target.closest("[data-sgate-add]");
    if (add) {
      var w = add.closest(WRAP);
      if (w) addRow(w);
      return;
    }
    var rm = e.target.closest("[data-sgate-remove]");
    if (rm) {
      var wrap = rm.closest(WRAP);
      var row = rm.closest("[data-sgate-row]");
      if (wrap && row) removeRow(wrap, row);
    }
  });

  window.libliInitSwitchGateEditor = initSwitchGateEditor;
  document.addEventListener("DOMContentLoaded", function () {
    initSwitchGateEditor(document);
  });
})();
