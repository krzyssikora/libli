(function () {
  "use strict";

  // ---------------------------------------------------------------------------
  // zone-editor.js — Rectangle-drawing authoring canvas for drag-to-image.
  //
  // For each [data-zone-editor] wrapper the canvas:
  //   1. Finds the chosen image via [data-media-preview][data-media-url] (set
  //      server-side on load and updated by media_picker.js after pick).
  //   2. Builds an absolutely-positioned overlay stage over the image.
  //      Draws existing zones from each [data-zone-row]'s x/y/w/h inputs
  //      (fractions 0..1 of the image dimensions).
  //   3. Pointer-drag on the image → adds a row by cloning <template data-zone-empty>
  //      (the formset empty_form), replacing every __prefix__ in name/id/for with the
  //      current zones-TOTAL_FORMS index, appending to [data-zone-rows], bumping
  //      TOTAL_FORMS, and writing the drawn fractional coords into the new row's inputs.
  //   4. Click a rect or its row → select (highlights both). Provides 8-handle resize
  //      and body-drag; clamps every change to [0,1] with x+w≤1 and y+h≤1; writes
  //      fractions back.
  //   5. Delete button on a rect → ticks the row's DELETE checkbox, removes the rect
  //      overlay (the row stays in the DOM so Django sees the deletion).
  //   6. After every add/delete, recompacts all kept (non-deleted) rows' `order` inputs
  //      0..n so ["order","pk"] stays gap-free and aligned with badge index.
  //
  // Exposes window.libliZoneEditor = init; self-inits on DOMContentLoaded.
  // Guards against double-init via dataset.zoneReady.
  // ---------------------------------------------------------------------------

  var HANDLE_SIZE = 8;  // px

  // -------------------------------------------------------------------------
  // Public entry point
  // -------------------------------------------------------------------------
  function init(root) {
    (root || document).querySelectorAll("[data-zone-editor]").forEach(setup);
  }

  // -------------------------------------------------------------------------
  // Per-editor setup
  // -------------------------------------------------------------------------
  function setup(editor) {
    if (editor.dataset.zoneReady) return;
    editor.dataset.zoneReady = "1";

    var preview = editor.querySelector("[data-media-preview]");
    var rowsList = editor.querySelector("[data-zone-rows]");
    var tmpl = editor.querySelector("template[data-zone-empty]");
    if (!rowsList || !tmpl) return;

    // The overlay stage sits on top of the image; we create it lazily when the
    // image URL is available.
    var wrap = null;     // .zone-stage-wrap (holds BOTH the <img> and the overlay)
    var stage = null;    // <div> overlay container
    var imgEl = null;    // the <img> inside the stage
    var rects = [];      // [{div, row}]
    var selected = null; // {div, row, rectIdx}

    // -----------------------------------------------------------------------
    // Stage creation / rebuild
    // -----------------------------------------------------------------------
    function buildStage(url) {
      // Remove any previous stage WRAP (it holds the old <img> + overlay). Removing only
      // the overlay `stage` would orphan the old image in the DOM → two stacked images
      // with no way to remove either. Zones live in the formset rows (fractional coords),
      // so they survive a rebuild and are redrawn below.
      if (wrap) { wrap.remove(); }
      wrap = null; stage = null; imgEl = null; rects = []; selected = null;

      // Wrap in a relative-positioned container that holds both the img and the overlay.
      wrap = document.createElement("div");
      wrap.className = "zone-stage-wrap";
      wrap.style.cssText = "position:relative;display:inline-block;user-select:none;-webkit-user-select:none;";

      imgEl = document.createElement("img");
      imgEl.src = url;
      imgEl.className = "zone-stage__img";
      imgEl.style.cssText = "display:block;max-width:100%;";
      imgEl.draggable = false;

      stage = document.createElement("div");
      stage.className = "zone-stage";
      stage.style.cssText = "position:absolute;inset:0;overflow:hidden;cursor:crosshair;";

      wrap.appendChild(imgEl);
      wrap.appendChild(stage);

      // Insert the stage wrapper right after [data-media-preview] (or before the alt label).
      var insertAfter = preview || rowsList;
      insertAfter.after(wrap);

      // Draw existing zone rows.
      Array.prototype.forEach.call(rowsList.querySelectorAll("[data-zone-row]"), function (row) {
        if (isDeletedRow(row)) return;
        addRect(row);
      });
      renumber();

      // Pointer-drag on the stage creates a new zone.
      wireDrawDrag(stage);

      // The image is now set: relabel the picker button "Change image" (translated text
      // comes from its data-change-label, set by the template).
      var pickBtn = editor.querySelector("[data-zone-pick]");
      if (pickBtn && pickBtn.dataset.changeLabel) pickBtn.textContent = pickBtn.dataset.changeLabel;
    }

    // -----------------------------------------------------------------------
    // Image URL observation: initial + after picker pick
    // -----------------------------------------------------------------------
    function tryBuildFromPreview() {
      if (!preview) return;
      var url = preview.dataset.mediaUrl;
      if (url) buildStage(url);
    }

    // NOTE: the initial buildStage and the MutationObserver wiring are deferred to the
    // END of setup() — buildStage → addRect → addHandles reads `var HANDLES`, which is
    // declared further down and so is still `undefined` here (var hoisting). Building an
    // existing question's stage during setup top would crash on HANDLES.forEach.

    // -----------------------------------------------------------------------
    // Helper: read x/y/w/h from a zone row's numeric inputs
    // -----------------------------------------------------------------------
    function readCoords(row) {
      function val(name) {
        var inp = row.querySelector('[name$="-' + name + '"]');
        return inp ? parseFloat(inp.value) || 0 : 0;
      }
      return { x: val("x"), y: val("y"), w: val("w"), h: val("h") };
    }

    function writeCoords(row, c) {
      ["x", "y", "w", "h"].forEach(function (f) {
        var inp = row.querySelector('[name$="-' + f + '"]');
        if (inp) inp.value = String(round6(c[f]));
      });
    }

    function isDeletedRow(row) {
      var chk = row.querySelector('[name$="-DELETE"]');
      return chk && chk.checked;
    }

    function round6(v) { return Math.round(v * 1e6) / 1e6; }

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    // -----------------------------------------------------------------------
    // Rect element helpers
    // -----------------------------------------------------------------------
    function rectStyle(c) {
      // c is fractions; convert to percent for CSS.
      return (
        "position:absolute;" +
        "left:" + (c.x * 100) + "%;" +
        "top:" + (c.y * 100) + "%;" +
        "width:" + (c.w * 100) + "%;" +
        "height:" + (c.h * 100) + "%;" +
        "box-sizing:border-box;" +
        "border:2px solid #3b82f6;" +
        "background:rgba(59,130,246,0.15);" +
        "cursor:move;"
      );
    }

    function applyRectStyle(div, c) {
      div.style.cssText = rectStyle(c);
      if (div.classList.contains("zone-rect--selected")) {
        div.style.border = "2px solid #1d4ed8";
        div.style.background = "rgba(29,78,216,0.25)";
      }
    }

    function createRectDiv(c) {
      var div = document.createElement("div");
      div.className = "zone-rect";
      div.style.cssText = rectStyle(c);
      // Number badge so each box visibly links to its label row + the student's badge.
      var num = document.createElement("span");
      num.className = "zone-rect__num";
      num.style.cssText = (
        "position:absolute;top:-10px;left:-10px;min-width:20px;height:20px;padding:0 4px;" +
        "border-radius:10px;background:#1d4ed8;color:#fff;display:flex;align-items:center;" +
        "justify-content:center;font-size:11px;font-weight:700;z-index:11;pointer-events:none;"
      );
      div.appendChild(num);
      div._num = num;
      addHandles(div);
      addDeleteBtn(div);
      return div;
    }

    // Number every rect by its row's position among kept (non-deleted) rows — matches the
    // row badge (a CSS counter) and the student-facing badge order.
    function renumber() {
      var kept = Array.prototype.filter.call(
        rowsList.querySelectorAll("[data-zone-row]"),
        function (r) { return !isDeletedRow(r); }
      );
      kept.forEach(function (row, i) {
        for (var k = 0; k < rects.length; k++) {
          if (rects[k].row === row && rects[k].div._num) {
            rects[k].div._num.textContent = String(i + 1);
          }
        }
      });
    }

    // -----------------------------------------------------------------------
    // Handles: 8 resize handles + body move
    // -----------------------------------------------------------------------
    var HANDLES = [
      "nw", "n", "ne",
      "w",         "e",
      "sw", "s", "se",
    ];

    function addHandles(div) {
      HANDLES.forEach(function (pos) {
        var h = document.createElement("div");
        h.className = "zone-handle";
        h.dataset.handle = pos;
        var s = HANDLE_SIZE + "px";
        h.style.cssText = (
          "position:absolute;width:" + s + ";height:" + s + ";background:#1d4ed8;" +
          "border:1px solid #fff;border-radius:2px;cursor:" + pos + "-resize;" +
          handleInset(pos, HANDLE_SIZE)
        );
        div.appendChild(h);
      });
    }

    function handleInset(pos, hs) {
      var half = "-" + Math.round(hs / 2) + "px";
      var mid = "calc(50% - " + Math.round(hs / 2) + "px)";
      var map = {
        nw: "top:" + half + ";left:" + half + ";",
        n:  "top:" + half + ";left:" + mid + ";",
        ne: "top:" + half + ";right:" + half + ";",
        w:  "top:" + mid  + ";left:" + half + ";",
        e:  "top:" + mid  + ";right:" + half + ";",
        sw: "bottom:" + half + ";left:" + half + ";",
        s:  "bottom:" + half + ";left:" + mid + ";",
        se: "bottom:" + half + ";right:" + half + ";",
      };
      return map[pos] || "";
    }

    // -----------------------------------------------------------------------
    // Delete button on rect
    // -----------------------------------------------------------------------
    function addDeleteBtn(div) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "×";
      btn.title = "Remove zone";
      btn.className = "zone-rect__del";
      btn.style.cssText = (
        "position:absolute;top:0;right:0;line-height:1;padding:0 3px;" +
        "background:#ef4444;color:#fff;border:none;border-radius:0 0 0 3px;" +
        "cursor:pointer;font-size:14px;z-index:10;"
      );
      div.appendChild(btn);
    }

    // -----------------------------------------------------------------------
    // Add a rect linked to an existing row
    // -----------------------------------------------------------------------
    function addRect(row) {
      var c = readCoords(row);
      if (c.w < 0.001 || c.h < 0.001) return;  // skip degenerate
      var div = createRectDiv(c);
      stage.appendChild(div);
      var entry = { div: div, row: row };
      rects.push(entry);
      wireRectInteraction(entry);
      return entry;
    }

    // -----------------------------------------------------------------------
    // Clone empty_form template, replace __prefix__, append row, bump TOTAL_FORMS
    // -----------------------------------------------------------------------
    function cloneEmptyRow(idx) {
      var content = tmpl.content.cloneNode(true);
      // Replace __prefix__ in all name/id/for attributes.
      Array.prototype.forEach.call(
        content.querySelectorAll("[name],[id],[for]"),
        function (el) {
          ["name", "id", "for"].forEach(function (attr) {
            var v = el.getAttribute(attr);
            if (v && v.indexOf("__prefix__") !== -1) {
              el.setAttribute(attr, v.replace(/__prefix__/g, String(idx)));
            }
          });
        }
      );
      return content;
    }

    function bumpTotalForms(editor) {
      var inp = editor.querySelector('[name="zones-TOTAL_FORMS"]');
      if (!inp) return -1;
      var idx = parseInt(inp.value, 10) || 0;
      inp.value = String(idx + 1);
      return idx;
    }

    // -----------------------------------------------------------------------
    // Draw-drag: pointer down on stage (not on a handle/rect/btn) → new zone
    // -----------------------------------------------------------------------
    function wireDrawDrag(stage) {
      stage.addEventListener("pointerdown", function (e) {
        // Ignore clicks on existing rects / handles / delete buttons.
        if (e.target.closest(".zone-rect")) return;
        e.preventDefault();
        stage.setPointerCapture(e.pointerId);

        var stageRect = stage.getBoundingClientRect();
        var startX = (e.clientX - stageRect.left) / stageRect.width;
        var startY = (e.clientY - stageRect.top) / stageRect.height;

        // Temporary preview div while dragging.
        var preview_div = document.createElement("div");
        preview_div.style.cssText = (
          "position:absolute;border:2px dashed #3b82f6;background:rgba(59,130,246,0.1);" +
          "pointer-events:none;box-sizing:border-box;"
        );
        stage.appendChild(preview_div);

        function onMove(ev) {
          var curX = clamp((ev.clientX - stageRect.left) / stageRect.width, 0, 1);
          var curY = clamp((ev.clientY - stageRect.top) / stageRect.height, 0, 1);
          var x = Math.min(startX, curX);
          var y = Math.min(startY, curY);
          var w = Math.abs(curX - startX);
          var h = Math.abs(curY - startY);
          preview_div.style.left = (x * 100) + "%";
          preview_div.style.top = (y * 100) + "%";
          preview_div.style.width = (w * 100) + "%";
          preview_div.style.height = (h * 100) + "%";
          preview_div._coords = { x: x, y: y, w: w, h: h };
        }

        function onUp(ev) {
          stage.removeEventListener("pointermove", onMove);
          stage.removeEventListener("pointerup", onUp);
          preview_div.remove();

          var c = preview_div._coords;
          if (!c || c.w < 0.01 || c.h < 0.01) return;  // too small — discard

          // Clone the empty form row, append to list, bump TOTAL_FORMS.
          var idx = bumpTotalForms(editor);
          if (idx < 0) return;
          var frag = cloneEmptyRow(idx);
          // Extract the <li> from the fragment.
          var newRow = frag.querySelector("[data-zone-row]");
          if (!newRow) return;
          rowsList.appendChild(frag);
          // After append, re-query to get the live DOM node.
          var liveRows = rowsList.querySelectorAll("[data-zone-row]");
          var liveRow = liveRows[liveRows.length - 1];

          // Write coordinates into the new row's inputs.
          writeCoords(liveRow, c);

          // Recompact order.
          recompactOrder();

          // Draw a rect for the new row.
          if (stage) {
            var entry = addRect(liveRow);
            if (entry) selectRect(entry);
          }
          renumber();
        }

        stage.addEventListener("pointermove", onMove);
        stage.addEventListener("pointerup", onUp);
        onMove(e);
      });
    }

    // -----------------------------------------------------------------------
    // Wire interaction on a single rect (select, move, resize, delete)
    // -----------------------------------------------------------------------
    function wireRectInteraction(entry) {
      var div = entry.div;
      var row = entry.row;

      // Clicking the rect selects it.
      div.addEventListener("pointerdown", function (e) {
        // Don't start a stage-draw when clicking a rect.
        e.stopPropagation();

        var handle = e.target.closest("[data-handle]");
        var delBtn = e.target.closest(".zone-rect__del");
        if (delBtn) return;  // handled by click below

        selectRect(entry);
        e.preventDefault();

        var stageRect = stage.getBoundingClientRect();
        var startCoords = readCoords(row);
        var startMouseX = e.clientX;
        var startMouseY = e.clientY;
        var handlePos = handle ? handle.dataset.handle : null;

        div.setPointerCapture(e.pointerId);

        function onMove(ev) {
          var dx = (ev.clientX - startMouseX) / stageRect.width;
          var dy = (ev.clientY - startMouseY) / stageRect.height;
          var c = applyDragOrResize(startCoords, dx, dy, handlePos);
          applyRectStyle(div, c);
          writeCoords(row, c);
        }

        function onUp() {
          div.removeEventListener("pointermove", onMove);
          div.removeEventListener("pointerup", onUp);
        }

        div.addEventListener("pointermove", onMove);
        div.addEventListener("pointerup", onUp);
      });

      // Delete button.
      div.addEventListener("click", function (e) {
        var delBtn = e.target.closest(".zone-rect__del");
        if (!delBtn) return;
        e.stopPropagation();
        // Tick the row's DELETE checkbox.
        var chk = row.querySelector('[name$="-DELETE"]');
        if (chk) chk.checked = true;
        row.classList.add("zone-row--del");
        // Remove the overlay rect.
        div.remove();
        rects = rects.filter(function (r) { return r !== entry; });
        if (selected && selected === entry) selected = null;
        recompactOrder();
        renumber();
      });
    }

    // -----------------------------------------------------------------------
    // Selection highlight
    // -----------------------------------------------------------------------
    function selectRect(entry) {
      // Deselect previous.
      if (selected && selected !== entry) {
        selected.div.classList.remove("zone-rect--selected");
        selected.div.style.border = "2px solid #3b82f6";
        selected.div.style.background = "rgba(59,130,246,0.15)";
        selected.row.classList.remove("zone-row--selected");
      }
      selected = entry;
      if (!entry) return;
      entry.div.classList.add("zone-rect--selected");
      entry.div.style.border = "2px solid #1d4ed8";
      entry.div.style.background = "rgba(29,78,216,0.25)";
      entry.row.classList.add("zone-row--selected");
    }

    // Click on a zone row (in the list) → select the matching rect.
    rowsList.addEventListener("click", function (e) {
      var rowEl = e.target.closest("[data-zone-row]");
      if (!rowEl) return;
      var found = null;
      for (var i = 0; i < rects.length; i++) {
        if (rects[i].row === rowEl) { found = rects[i]; break; }
      }
      if (found) selectRect(found);
    });

    // -----------------------------------------------------------------------
    // Move / resize computation
    // -----------------------------------------------------------------------
    function applyDragOrResize(base, dx, dy, handle) {
      var x = base.x, y = base.y, w = base.w, h = base.h;

      if (!handle) {
        // Body move: shift origin, keep size.
        x = clamp(x + dx, 0, 1 - w);
        y = clamp(y + dy, 0, 1 - h);
      } else {
        // Resize: adjust the relevant edges.
        var newX = x, newY = y, newW = w, newH = h;

        if (handle.indexOf("w") !== -1) {
          // Moving left edge: x changes, w shrinks/grows inversely.
          var leftEdge = clamp(x + dx, 0, x + w - 0.01);
          newW = (x + w) - leftEdge;
          newX = leftEdge;
        }
        if (handle.indexOf("e") !== -1) {
          // Moving right edge: w changes.
          newW = clamp(w + dx, 0.01, 1 - x);
        }
        if (handle.indexOf("n") !== -1) {
          // Moving top edge.
          var topEdge = clamp(y + dy, 0, y + h - 0.01);
          newH = (y + h) - topEdge;
          newY = topEdge;
        }
        if (handle.indexOf("s") !== -1) {
          // Moving bottom edge.
          newH = clamp(h + dy, 0.01, 1 - y);
        }

        // Final clamp so the rect never exceeds the image.
        if (newX + newW > 1) { newW = 1 - newX; }
        if (newY + newH > 1) { newH = 1 - newY; }
        x = newX; y = newY; w = newW; h = newH;
      }

      return { x: x, y: y, w: w, h: h };
    }

    // -----------------------------------------------------------------------
    // Recompact `order` inputs (0..n) for all kept (non-deleted) rows
    // -----------------------------------------------------------------------
    function recompactOrder() {
      var kept = Array.prototype.filter.call(
        rowsList.querySelectorAll("[data-zone-row]"),
        function (r) { return !isDeletedRow(r); }
      );
      kept.forEach(function (r, i) {
        var inp = r.querySelector('[name$="-order"]');
        if (inp) inp.value = String(i);
      });
    }

    // -----------------------------------------------------------------------
    // Initial build + media-pick observation (deferred to here so every helper —
    // notably `var HANDLES` — is assigned before buildStage can run).
    // -----------------------------------------------------------------------
    // Build on load if the URL is already known (editing an existing question).
    tryBuildFromPreview();

    // Re-build when media_picker.js updates data-media-url (dispatches change on the
    // <select name="media"> — we watch for that attribute mutation as a reliable hook).
    if (preview) {
      // MutationObserver on the data-media-url attribute of [data-media-preview].
      var mo = new MutationObserver(function () {
        var url = preview.dataset.mediaUrl;
        if (url && (!stage || imgEl.src !== url)) buildStage(url);
      });
      mo.observe(preview, { attributes: true, attributeFilter: ["data-media-url"] });
    }
  }

  // -------------------------------------------------------------------------
  // Module export + self-init
  // -------------------------------------------------------------------------
  window.libliZoneEditor = init;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(); });
  } else {
    init();
  }
})();
