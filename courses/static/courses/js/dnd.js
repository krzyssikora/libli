// Progressive drag-and-drop enhancement for drag-fill-blanks, match-pairs, and
// drag-to-image. The <select name="slot"> elements are the source of truth and the
// no-JS fallback; this script only ever SETS a select's value (it never
// reorders/removes selects), so drag, tap, keyboard, and no-JS produce byte-identical
// answers.
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

  // Typeset inline KaTeX (\(…\)/\[…\]) in JS-injected DOM (chips, slots, overlay
  // targets). Mirrors the delimiters question.js uses so a label typesets identically
  // wherever it appears. No-op when auto-render.min.js wasn't loaded (no-math page).
  var MATH_DELIMS = [
    { left: "\\(", right: "\\)", display: false },
    { left: "\\[", right: "\\]", display: true },
  ];
  function typeset(el) {
    if (!el || typeof window.renderMathInElement !== "function") return;
    try {
      window.renderMathInElement(el, { delimiters: MATH_DELIMS, throwOnError: false });
    } catch (e) { /* leave raw LaTeX on error */ }
  }

  function enhance(block) {
    if (block.dataset.dndReady) return;
    block.dataset.dndReady = "1";
    var selects = Array.prototype.slice.call(block.querySelectorAll('select[name="slot"]'));
    if (!selects.length) return;
    var pool = block.querySelector("[data-dnd-pool]");
    if (!pool) return;

    // ── Shared "armed chip" tap state ──────────────────────────────────────
    // Only one chip is armed at a time. Tapping a chip toggles its armed state;
    // tapping a target then assigns/overwrites/clears per the tap state table.
    var armed = null; // the currently-armed chip element, or null

    function disarm() {
      if (armed) armed.classList.remove("dnd__chip--armed");
      armed = null;
    }
    function toggleArm(chip) {
      if (armed === chip) {
        disarm();
      } else {
        disarm();
        armed = chip;
        chip.classList.add("dnd__chip--armed");
      }
    }

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
        // A drag supersedes any pending tap-arm.
        disarm();
      });
      // Tap-to-arm (toggle). Shared by all three DnD types.
      chip.addEventListener("click", function () {
        toggleArm(chip);
      });
      pool.appendChild(chip);
    });
    // The page's KaTeX pass ran before these chips existed; typeset them now so a
    // \(…\) label shows as math in the chip (the native <option> keeps raw source).
    typeset(pool);

    // Tap handler factory for a target (a slot or an overlay drop-zone). `getValue`
    // reads the linked select's current value so we can tell empty vs filled.
    function tapTarget(sel) {
      // Tap state table (spec §):
      //   armed + empty   → assign,    disarm
      //   armed + filled  → overwrite, disarm
      //   unarmed + filled→ clear
      //   unarmed + empty → no-op
      if (armed) {
        setSelect(sel, armed.dataset.token);
        disarm();
      } else if (sel.value) {
        setSelect(sel, "");
      }
    }

    // ── Discriminator: image-overlay block vs inline-slot block ────────────
    var stage = block.querySelector("[data-dragimage-stage]");
    if (stage) {
      buildOverlayTargets(block, stage, selects, tapTarget);
    } else {
      buildInlineSlots(selects, tapTarget);
    }
  }

  // ── Drag-to-image: absolutely-positioned overlay drop-targets on the stage ──
  function buildOverlayTargets(block, stage, selects, tapTarget) {
    var badges = Array.prototype.slice.call(stage.querySelectorAll("[data-zone]"));
    badges.forEach(function (badge) {
      var zoneIdx = Number(badge.dataset.zone);
      var sel = selects[zoneIdx];
      if (!sel) return;

      var target = document.createElement("span");
      target.className = "dragimage__target";
      target.tabIndex = 0;
      // Position from the badge's raw fractional geometry (JS is independent of the
      // no-JS percentage CSS on the badge itself).
      var x = parseFloat(badge.dataset.x) || 0;
      var y = parseFloat(badge.dataset.y) || 0;
      var w = parseFloat(badge.dataset.w) || 0;
      var h = parseFloat(badge.dataset.h) || 0;
      target.style.left = x * 100 + "%";
      target.style.top = y * 100 + "%";
      target.style.width = w * 100 + "%";
      target.style.height = h * 100 + "%";

      function paint() {
        target.dataset.value = sel.value || "";
        target.textContent = sel.value || "";
        target.classList.toggle("dragimage__target--filled", !!sel.value);
      }
      paint();

      target.addEventListener("dragover", function (e) { e.preventDefault(); });
      target.addEventListener("drop", function (e) {
        e.preventDefault();
        setSelect(sel, e.dataTransfer.getData("text/plain"));
      });
      target.addEventListener("click", function () { tapTarget(sel); });
      target.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          sel.style.display = "";
          sel.focus();
        }
      });
      sel.addEventListener("change", function () {
        paint();
        typeset(target);
      });
      // The native selects are kept (source of truth) but hidden under JS.
      sel.style.display = "none";
      stage.appendChild(target);
      typeset(target);
    });
  }

  // ── Drag-fill / match-pairs: a visible inline drop-slot per select ──────────
  function buildInlineSlots(selects, tapTarget) {
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
      }
      slot.addEventListener("dragover", function (e) { e.preventDefault(); });
      slot.addEventListener("drop", function (e) {
        e.preventDefault();
        accept(e.dataTransfer.getData("text/plain"));
      });
      slot.addEventListener("click", function () { tapTarget(sel); });
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
        typeset(slot);
      });
      typeset(slot);
    });
  }

  function init(root) {
    (root || document).querySelectorAll("[data-dnd]").forEach(enhance);
  }
  // Exposed so the manage editor can re-enhance its live preview after a fragment
  // swap (student pages never re-render stems, so they only need the load-time pass).
  // enhance() is idempotent via the data-dndReady guard, so calling this is safe.
  window.libliEnhanceDnd = init;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(); });
  } else {
    init();
  }
})();
