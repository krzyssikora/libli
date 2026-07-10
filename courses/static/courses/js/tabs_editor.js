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
    if (editor.dataset.tabsEditorReady) return;
    editor.dataset.tabsEditorReady = "1";

    var hidden = editor.querySelector('input[name="data"]');
    var rows = editor.querySelector("[data-tab-list]");
    var addBtn = editor.querySelector("[data-tab-add]");
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
      hidden.value = JSON.stringify({ tabs: tabs });
    }

    // Gate the controls at the bounds: no removing below MIN, no adding above MAX.
    function refreshControlState() {
      var n = rowEls().length;
      Array.prototype.forEach.call(rows.querySelectorAll("[data-tab-remove]"), function (b) {
        b.disabled = n <= minTabs;
      });
      if (addBtn) addBtn.disabled = n >= maxTabs;
    }

    rows.addEventListener("input", function (e) {
      if (!e.target.closest("[data-tab-label-input]")) return;
      serialize();
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
        return;
      }
      if (e.target.closest("[data-tab-up]")) {
        var prev = li.previousElementSibling;
        if (prev) rows.insertBefore(li, prev);
        serialize();
        return;
      }
      if (e.target.closest("[data-tab-down]")) {
        var next = li.nextElementSibling;
        if (next) rows.insertBefore(next, li);
        serialize();
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
      });
    }

    refreshControlState();
    // Serialize on init ONLY when the hidden field is empty: covers the add path
    // (captures the two default tabs) and the edit path (captures the server-rendered
    // EXISTING tabs + their ids, so a Save that never touches the labels preserves
    // them). A bound-invalid 422 re-render already carries the submitted JSON, so it
    // is skipped here.
    if (hidden.value === "") serialize();
  }

  function initTabsEditor(root) {
    (root || document).querySelectorAll("[data-tabs-editor]").forEach(wire);
  }

  window.libliInitTabsEditor = initTabsEditor;
  initTabsEditor(document);
})();
