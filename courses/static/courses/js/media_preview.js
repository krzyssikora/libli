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
      captionOnly();
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

  var GRACE_MS = 300;
  var hideTimer = null;

  function captionOnly() {
    overlayImg.hidden = true;
    // Null the expected source, or a load still in flight for a PREVIOUS asset
    // would still compare equal (this branch assigns no src) and would un-hide
    // the image, painting A's frame under B's caption.
    expectedSrc = null;
  }

  function cancelHide() {
    if (hideTimer !== null) { clearTimeout(hideTimer); hideTimer = null; }
  }

  function startHide() {
    cancelHide();
    var gen = generation;
    hideTimer = setTimeout(function () {
      hideTimer = null;
      if (gen !== generation) return;   // a later open superseded this timer
      close();
    }, GRACE_MS);
  }

  function teardownOpenBindings() {
    // Everything open() registers. Called from open() itself (an in-place swap
    // re-enters without closing) and from close(). Task 7 adds the observer and
    // the scroll/resize/keydown listeners here.
    if (dwellTimer !== null) { clearTimeout(dwellTimer); dwellTimer = null; }
  }

  function open(anchor) {
    if (!overlay) build();
    var cell = anchor.closest(".asset-cell");
    if (!cell) return;
    teardownOpenBindings();
    cancelHide();
    generation += 1;
    overlayImg.hidden = true;
    overlayCaption.textContent = cell.getAttribute("data-name") || "";
    openAnchor = anchor;

    var src = anchor.currentSrc || anchor.getAttribute("src") || "";
    if (!src || (anchor.complete && anchor.naturalWidth === 0)) {
      // The thumbnail itself failed, so there is nothing to copy. Assigning ""
      // does not reliably fire error and can leave the previous image showing.
      captionOnly();
    } else {
      overlayImg.src = src;
      expectedSrc = src;
      if (overlayImg.getAttribute("src") === expectedSrc
          && overlayImg.complete && overlayImg.naturalWidth > 0) {
        overlayImg.hidden = false;   // ahead of measure -- see Task 5
      }
    }

    // ONE shared tail, reached by both branches.
    overlay.style.visibility = "hidden";
    overlay.hidden = false;
    place();
    overlay.style.visibility = "";
    bindOpenListeners();             // Task 7 fills this in; a no-op until then
  }

  function bindOpenListeners() {}    // Task 7

  function close() {
    teardownOpenBindings();
    cancelHide();
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
      cancelHide();          // ANY anchor entry cancels a pending hide
      if (anchor === openAnchor) return;   // same anchor: the cancel above IS
                                           // the work -- not a bare no-op
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
      // Arm ONLY for the open anchor. Otherwise the A-hovered/B-open case tears
      // itself down: pointer on A, user Tabs into cell B, pointer drifts off A,
      // and 300ms later a mouse twitch kills a keyboard user's overlay.
      if (anchor !== openAnchor) return;
      startHide();
    });
  }
})();
