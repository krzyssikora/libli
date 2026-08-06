(function () {
  "use strict";

  // ---- Tabs editor: progressively enhance [data-tabs-editor] blocks. ----
  // The hidden input[name="data"] is the SOLE authoritative form field; the label
  // rows are name-less JS UI mirrored into it via serialize() as {"tabs":[{id,label}]}.
  // Each row carries its tab id in data-tab-id so the id ROUND-TRIPS on save; a
  // brand-new row has an empty data-tab-id and the server mints its id. Add/remove are
  // gated by the MIN/MAX bounds the server writes into data-min-tabs / data-max-tabs.

  // JS-built controls cannot call {% trans %}; user-facing strings ride on data-msg-*
  // attributes and are read via this helper (mirrors table_editor.js's label()).
  function label(root, key, fallback) {
    return root.getAttribute("data-msg-" + key) || fallback;
  }

  function wire(editor) {
    // NOTE for tests: this flag is set FIRST, before any listener is attached below,
    // so `[data-tabs-editor-ready]` is not a barrier proving the delegated `input`
    // listener exists. It is safe to drive the editor as soon as the flag appears
    // only because wire() is fully synchronous on both entry paths (initTabsEditor at
    // parse time, and editor.js's applyFragments after a swap), so no intermediate
    // state is ever observable. Move any init work behind a rAF/await and that stops
    // being true -- move this assignment to the end of wire() if you do.
    if (editor.dataset.tabsEditorReady) return;
    editor.dataset.tabsEditorReady = "1";

    var hidden = editor.querySelector('input[name="data"]');
    var rows = editor.querySelector("[data-tab-list]");
    var addBtn = editor.querySelector("[data-tab-add]");
    var displaySel = editor.querySelector("[data-tab-display]");
    var labelPosSel = editor.querySelector("[data-tab-label-pos]");
    var labelPosRow = editor.querySelector("[data-tab-label-pos-row]");
    if (!hidden || !rows) return; // defensive: markup changed

    var minTabs = parseInt(editor.getAttribute("data-min-tabs"), 10) || 0;
    var maxTabs = parseInt(editor.getAttribute("data-max-tabs"), 10) || Infinity;

    function rowEls() {
      return Array.prototype.slice.call(rows.querySelectorAll("[data-tab-row]"));
    }

    function serialize() {
      var tabs = rowEls().map(function (li) {
        var input = li.querySelector("[data-tab-label-input]");
        return {
          id: li.getAttribute("data-tab-id") || "",
          label: input ? input.value : "",
        };
      });
      hidden.value = JSON.stringify({
        tabs: tabs,
        // Read from the DOM, never from a captured initial value: this function is the
        // only thing that writes the authoritative field, and a saved carousel that
        // re-serialises without these silently reverts to tabs on a no-op Save.
        display: displaySel ? displaySel.value : "tabs",
        label_pos: labelPosSel ? labelPosSel.value : "above",
      });
    }

    // Gate the controls at the bounds: no removing below MIN, no adding above MAX.
    function refreshControlState() {
      var n = rowEls().length;
      Array.prototype.forEach.call(rows.querySelectorAll("[data-tab-remove]"), function (b) {
        b.disabled = n <= minTabs;
      });
      if (addBtn) addBtn.disabled = n >= maxTabs;
    }

    function syncLabelPosRow() {
      if (!labelPosRow) return;
      var on = displaySel && displaySel.value === "carousel";
      if (on) { labelPosRow.removeAttribute("hidden"); }
      else { labelPosRow.setAttribute("hidden", ""); }
    }

    // Character counter. Rebuilds the row's entire counter state from `n` on every
    // call -- a pure function of the current value, never an incremental mutation, so
    // the at-cap state cannot be stranded when the author deletes back below the cap.
    function refreshCount(li, announce) {
      if (!li) return;
      var input = li.querySelector("[data-tab-label-input]");
      var num = li.querySelector("[data-tab-num]");
      if (!input || !num) return;
      // The server already wrote maxlength="{{ tb.label_max }}"; reading it back means
      // no new data-* plumbing and no way to drift from LABEL_MAX. Absent -> -1.
      var max = input.maxLength;
      if (!max || max < 0) {
        num.hidden = true;
        num.textContent = "";
        num.classList.remove("is-near", "is-at-cap");
        return;
      }
      var n = input.value.length; // UTF-16 units, matching what maxlength counts
      // 80 * 0.8 is exactly 64.0 in IEEE-754, so ceil and floor are indistinguishable
      // at the current cap; ceil is chosen for a LABEL_MAX where it is fractional.
      var threshold = Math.ceil(max * 0.8);
      var atCap = n >= max; // >= not ==, so an over-length value degrades sanely
      num.hidden = n < threshold;
      num.textContent = n < threshold ? "" : n + "/" + max;
      num.classList.toggle("is-near", n >= threshold && !atCap);
      num.classList.toggle("is-at-cap", atCap);
      if (!announce) return;
      var region = editor.querySelector("[data-tab-cap]");
      if (!region) return;
      var msg = "";
      if (atCap) {
        // {n} is the row's 1-based position -- NOT decoration. A row-agnostic phrase
        // would be byte-identical between rows, so the change-guard below would
        // suppress the write when a SECOND row reaches the cap and nothing would be
        // announced. split/join, never .replace: that replaces one occurrence only.
        msg = label(editor, "cap", "Tab {n} label limit reached — {max} characters")
          .split("{n}")
          .join(rowEls().indexOf(li) + 1)
          .split("{max}")
          .join(max);
      }
      // Guarded on change: `input` keeps firing at the cap in some browsers, and
      // re-assigning the same string replaces the text node -- a mutation many screen
      // readers announce again. Do not write "" over an already-empty region either.
      if (region.textContent !== msg) region.textContent = msg;
    }

    function clearCapRegion() {
      var region = editor.querySelector("[data-tab-cap]");
      if (region && region.textContent !== "") region.textContent = "";
    }

    if (displaySel) displaySel.addEventListener("change", function () {
      syncLabelPosRow();
      serialize();
    });
    if (labelPosSel) labelPosSel.addEventListener("change", serialize);

    rows.addEventListener("input", function (e) {
      if (!e.target.closest("[data-tab-label-input]")) return;
      serialize();
      refreshCount(e.target.closest("[data-tab-row]"), true);
    });

    rows.addEventListener("click", function (e) {
      var li = e.target.closest("[data-tab-row]");
      if (!li) return;
      if (e.target.closest("[data-tab-remove]")) {
        if (rowEls().length <= minTabs) return;
        if (!window.confirm(label(editor, "confirm", "Delete this tab?"))) return;
        li.remove();
        refreshControlState();
        serialize();
        clearCapRegion();
        return;
      }
      if (e.target.closest("[data-tab-up]")) {
        var prev = li.previousElementSibling;
        if (prev) rows.insertBefore(li, prev);
        serialize();
        clearCapRegion();
        return;
      }
      if (e.target.closest("[data-tab-down]")) {
        var next = li.nextElementSibling;
        if (next) rows.insertBefore(next, li);
        serialize();
        clearCapRegion();
        return;
      }
    });

    if (addBtn) {
      addBtn.addEventListener("click", function () {
        var existing = rowEls();
        if (existing.length >= maxTabs) return;
        // Clone an existing row rather than server-rendering a hidden template: it keeps
        // the row markup (icons, labels) in ONE place and never adds an extra
        // data-tab-row to the initial HTML (the partial test counts that substring).
        var proto = existing[existing.length - 1];
        if (!proto) return;
        var li = proto.cloneNode(true);
        li.setAttribute("data-tab-id", ""); // empty -> the server mints the id on save
        var input = li.querySelector("[data-tab-label-input]");
        if (input) input.value = "";
        rows.appendChild(li);
        if (input) input.focus();
        refreshControlState();
        serialize();
        // The clone copies the digits span INCLUDING its text, class and `hidden`
        // state, so cloning an at-cap row would otherwise show a stale 80/80 on a
        // brand-new empty input. Clear the region first, then rebuild last.
        clearCapRegion();
        refreshCount(li, false);
      });
    }

    refreshControlState();
    // Once at init, not only from the change listener: wire() runs once per editor and
    // `change` fires only on interaction, so a listener-only version shows the row on
    // every saved TABS element until the author touches the Display select. The
    // template renders the initial `hidden` too -- this is the idempotent re-assertion.
    syncLabelPosRow();
    // Serialize on init ONLY when the hidden field is empty: covers the add path
    // (captures the two default tabs) and the edit path (captures the server-rendered
    // EXISTING tabs + their ids, so a Save that never touches the labels preserves
    // them). A bound-invalid 422 re-render already carries the submitted JSON, so it
    // is skipped here.
    if (hidden.value === "") serialize();
    // Init: a saved label may already be at 80, and the digits must be right before
    // the author touches anything -- the one path a delegated input listener cannot
    // cover. announce=false: opening an editor is not an event to announce.
    rowEls().forEach(function (li) { refreshCount(li, false); });
  }

  function initTabsEditor(root) {
    (root || document).querySelectorAll("[data-tabs-editor]").forEach(wire);
  }

  window.libliInitTabsEditor = initTabsEditor;
  initTabsEditor(document);
})();
