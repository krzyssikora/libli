(function () {
  "use strict";
  // Non-modal hover preview for the media manager grid (spec §5).
  //
  // NOT imagezoom.js: that is a click-triggered modal <dialog>. The task here
  // is SCANNING a row of near-identical thumbnails, where a modal costs a click
  // to open, Escape to dismiss and a click for the next. Being non-modal means
  // this module deliberately re-implements none of imagezoom's modal machinery
  // -- no showModal, no scroll lock, no focus trap, no Escape arbitration.
  var root = document.querySelector(".media-manager");
  if (!root) return;

  var DWELL_MS = 250;
  var GAP = 8;

  var overlay = null, overlayImg = null, overlayCaption = null;
  var hoveredAnchor = null;   // pointer bookkeeping only
  var openAnchor = null;      // the anchor the overlay is RENDERING
  var expectedSrc = null;     // guards the load/error handlers
  var generation = 0;         // guards deferred work
  var dwellTimer = null;

  // Evaluated ONCE at load. On touch a tap synthesises hover events with no
  // matching leave, which would strand the overlay over the grid. The focus
  // path (Task 7) is armed unconditionally -- a keyboard attached to a
  // touch-first device is real, and the touch failure mode does not apply.
  var canHover = window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  function build() {
    overlay = document.createElement("div");
    overlay.className = "asset-preview";
    overlay.setAttribute("aria-hidden", "true");
    overlay.hidden = true;
    overlayImg = document.createElement("img");
    overlayImg.setAttribute("data-asset-preview-img", "");
    overlayImg.alt = "";
    overlayImg.hidden = true;
    overlayCaption = document.createElement("div");
    overlayCaption.className = "asset-preview__caption";
    overlay.appendChild(overlayImg);
    overlay.appendChild(overlayCaption);

    // Bound ONCE at creation, not per open: per-open addEventListener without
    // removal accumulates one handler per hover for the page's lifetime.
    // These must exist from Task 5 -- on a COLD open the image is not yet
    // complete, so the synchronous reveal in open() does not fire and `load`
    // is the only thing that ever lifts overlayImg.hidden.
    overlayImg.addEventListener("load", function () {
      if (!openAnchor) return;                                    // closed since
      if (overlayImg.getAttribute("src") !== expectedSrc) return; // stale source
      overlayImg.hidden = false;
      place();   // the first measurement saw a caption-only box
    });
    overlayImg.addEventListener("error", function () {
      if (!openAnchor) return;
      if (overlayImg.getAttribute("src") !== expectedSrc) return;
      overlayImg.hidden = true;
    });

    // document.body, NOT .media-manager: position:fixed resolves against the
    // nearest ancestor with transform/filter/contain/will-change, so nesting it
    // would make the overlay hostage to any future such property on the shell.
    document.body.appendChild(overlay);
  }

  function place() {
    if (!openAnchor) return;
    // The reference box is the CELL, not the thumb: the thumb is inset by the
    // cell's padding and border and is materially shorter.
    var cell = openAnchor.closest(".asset-cell");
    if (!cell) return;
    var c = cell.getBoundingClientRect();
    var o = overlay.getBoundingClientRect();
    // documentElement.clientWidth, not innerWidth or 100vw: those include the
    // scrollbar, and only clientWidth describes the space a fixed box can
    // actually occupy.
    var vw = document.documentElement.clientWidth;
    var vh = document.documentElement.clientHeight;
    var left, top;
    if (vw - c.right - GAP >= o.width) { left = c.right + GAP; top = c.top; }
    else if (c.left - GAP >= o.width) { left = c.left - GAP - o.width; top = c.top; }
    else if (vh - c.bottom - GAP >= o.height) { left = c.left; top = c.bottom + GAP; }
    else if (c.top - GAP >= o.height) { left = c.left; top = c.top - GAP - o.height; }
    else { left = (vw - o.width) / 2; top = (vh - o.height) / 2; }
    // Clamp with an 8px margin so a card near an edge cannot push it offscreen.
    // Top and left win when the box exceeds an axis.
    left = Math.max(GAP, Math.min(left, vw - o.width - GAP));
    top = Math.max(GAP, Math.min(top, vh - o.height - GAP));
    overlay.style.left = left + "px";
    overlay.style.top = top + "px";
  }

  function open(anchor) {
    if (!overlay) build();
    var cell = anchor.closest(".asset-cell");
    if (!cell) return;
    generation += 1;
    // Reset the singleton. Does NOT clear src: both src="" and
    // removeAttribute("src") yield a null selected source and QUEUE AN ERROR
    // that lands after the new source is assigned, flipping a good overlay to
    // caption-only. Assigning over the old source queues nothing.
    overlayImg.hidden = true;
    var src = anchor.currentSrc || anchor.getAttribute("src") || "";
    overlayImg.src = src;
    expectedSrc = src;
    // textContent, NEVER innerHTML: getAttribute returns display_name FULLY
    // DECODED, and it falls back to an attacker-controlled uploaded filename.
    overlayCaption.textContent = cell.getAttribute("data-name") || "";
    openAnchor = anchor;
    // Reveal synchronously when the image is already complete. Re-opening the
    // SAME anchor assigns an identical src, and whether that re-queues `load`
    // on a complete image is engine behaviour we will not bet on -- without
    // this the image would stay hidden forever on the commonest repeat action.
    // Position matters: ahead of measure, because on this path there may be no
    // `load` at all and the measurement below is the only one.
    if (overlayImg.getAttribute("src") === expectedSrc
        && overlayImg.complete && overlayImg.naturalWidth > 0) {
      overlayImg.hidden = false;
    }
    // Measure only after unhiding: a display:none element has no box, so every
    // "does it fit?" test would compare against width 0 and answer yes.
    overlay.style.visibility = "hidden";
    overlay.hidden = false;
    place();
    overlay.style.visibility = "";
  }

  function close() {
    if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
    if (!overlay) return;
    overlay.hidden = true;
    overlayImg.hidden = true;
    openAnchor = null;
    expectedSrc = null;
  }

  if (canHover) {
    // mouseenter/mouseleave do NOT bubble, so they cannot be delegated -- and
    // the manager replaces cells and grids constantly (upload insertCell,
    // rename/replace cell.replaceWith, every filter keystroke swapping the
    // whole grid). Per-node listeners bound at load would go silently dead on
    // every swapped-in cell. mouseover/mouseout bubble, so no arming pass and
    // no per-cell listener is needed at all.
    root.addEventListener("mouseover", function (e) {
      var anchor = e.target.closest && e.target.closest("[data-asset-preview]");
      if (!anchor) return;
      // Defensive, not currently reachable: the anchor is a replaced <img> with
      // no descendants, so relatedTarget can never be inside it. Kept against a
      // future non-replaced anchor.
      if (e.relatedTarget && anchor.contains(e.relatedTarget)) return;
      hoveredAnchor = anchor;
      if (anchor === openAnchor) return;
      if (openAnchor) { open(anchor); return; }   // in-place swap, no dwell
      if (dwellTimer !== null) return;
      dwellTimer = setTimeout(function () {
        dwellTimer = null;
        // The grid may have been swapped during the dwell, when nothing is
        // observing yet. A detached anchor measures as zeros, "fits on the
        // right" trivially passes, and the overlay pins to the corner with no
        // anchor left to fire mouseout.
        if (!anchor.isConnected) return;
        open(anchor);
      }, DWELL_MS);
    });

    root.addEventListener("mouseout", function (e) {
      var anchor = e.target.closest && e.target.closest("[data-asset-preview]");
      if (!anchor) return;
      if (e.relatedTarget && anchor.contains(e.relatedTarget)) return;
      if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
      hoveredAnchor = null;
      if (anchor === openAnchor) close();
    });
  }
})();
