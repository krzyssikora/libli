// Progressive drag-and-drop enhancement for drag-fill-blanks & match-pairs.
// The <select name="slot"> elements are the source of truth and the no-JS fallback;
// this script only ever SETS a select's value (it never reorders/removes selects).
(function () {
  "use strict";

  function tokensFromSelects(selects) {
    var seen = Object.create(null);
    var tokens = [];
    selects.forEach(function (sel) {
      Array.prototype.forEach.call(sel.options, function (opt) {
        if (opt.value && !seen[opt.value]) {
          seen[opt.value] = true;
          tokens.push(opt.value);
        }
      });
    });
    return tokens;
  }

  function setSelect(sel, value) {
    sel.value = value;
    sel.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function enhance(block) {
    if (block.dataset.dndReady) return;
    block.dataset.dndReady = "1";
    var selects = Array.prototype.slice.call(block.querySelectorAll('select[name="slot"]'));
    if (!selects.length) return;
    var pool = block.querySelector("[data-dnd-pool]");
    if (!pool) return;

    // Build the draggable chip pool (JS-injected; absent with JS off).
    pool.hidden = false;
    tokensFromSelects(selects).forEach(function (tok) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "dnd__chip";
      chip.textContent = tok;
      chip.draggable = true;
      chip.dataset.token = tok;
      chip.addEventListener("dragstart", function (e) {
        e.dataTransfer.setData("text/plain", tok);
      });
      pool.appendChild(chip);
    });

    // Each select gets a visible drop-slot; the select itself is hidden but kept.
    selects.forEach(function (sel) {
      sel.classList.add("dnd__select--enhanced");
      var slot = document.createElement("span");
      slot.className = "dnd__slot";
      slot.tabIndex = 0;
      slot.textContent = sel.value || sel.dataset.placeholder || "…";
      sel.parentNode.insertBefore(slot, sel);
      sel.style.display = "none";

      function accept(tok) {
        setSelect(sel, tok);
        slot.textContent = tok || "…";
      }
      slot.addEventListener("dragover", function (e) { e.preventDefault(); });
      slot.addEventListener("drop", function (e) {
        e.preventDefault();
        accept(e.dataTransfer.getData("text/plain"));
      });
      // Keyboard fallback: focus the slot and use the hidden select via arrow keys
      // by re-showing it on Enter (kept simple; the select remains the source of truth).
      slot.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          sel.style.display = "";
          sel.focus();
        }
      });
      sel.addEventListener("change", function () {
        slot.textContent = sel.value || "…";
      });
    });
  }

  function init() {
    document.querySelectorAll("[data-dnd]").forEach(enhance);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
