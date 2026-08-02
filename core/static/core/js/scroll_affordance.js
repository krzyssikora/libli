/* Edge affordance for horizontally scrollable boxes.

   Markup contract: a non-scrolling wrapper `.scroll-x[data-scroll-x]` around the
   element that actually scrolls. The wrapper carries the classes because its
   pseudo-elements must stay pinned to the visible edges — an overlay inside the
   scroller would slide away with the content.

   is-scroll-start / is-scroll-end mean "there is content past this edge", the
   same meaning tabs.js gives them on .tabs__bar.

   Progressive enhancement: with JS off no class is ever set, both gradients stay
   at opacity 0, and the box still scrolls. Nothing here is load-bearing. */
(function () {
  "use strict";

  function scrollerFor(wrap) {
    // The scroller is the wrapper's only element child in every current use, but
    // query rather than assume so a future wrapper with a caption still works.
    var el = wrap.firstElementChild;
    while (el) {
      if (el.scrollWidth > el.clientWidth || el.hasAttribute("data-scroll-x-viewport")) {
        return el;
      }
      el = el.nextElementSibling;
    }
    return wrap.firstElementChild;
  }

  function update(wrap, box) {
    if (!box) return;
    var max = box.scrollWidth - box.clientWidth;
    // 1px slack: fractional layout means scrollLeft rarely hits max exactly, and
    // a permanently-lit trailing edge on a box scrolled fully right reads as a bug.
    wrap.classList.toggle("is-scroll-start", box.scrollLeft > 1);
    wrap.classList.toggle("is-scroll-end", box.scrollLeft < max - 1);
  }

  function wire(wrap) {
    if (wrap.dataset.scrollXReady === "1") return;  // idempotent: safe to re-init
    var box = scrollerFor(wrap);
    if (!box) return;
    wrap.dataset.scrollXReady = "1";
    var apply = function () { update(wrap, box); };
    box.addEventListener("scroll", apply, { passive: true });
    // Content and available width both change without a scroll: a swapped editor
    // fragment, a tabs panel revealed after measuring 0 while hidden, a rotated
    // phone. Observe both boxes so the affordance re-measures instead of going stale.
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(apply);
      ro.observe(box);
      if (box.firstElementChild) ro.observe(box.firstElementChild);
    }
    apply();
  }

  /* ---- Block axis -------------------------------------------------------
     Same contract, one extra problem: on the inline axis the scroller is a fixed
     child, but a `[data-scroll-y]` wrapper can SWAP scrollers under us -- the
     slideshow stage holds every slide and only the active one is rendered. So the
     attribute carries a selector naming the live scroller and we re-resolve it on
     every measurement instead of binding one element at wire time. An empty value
     falls back to the first rendered child, matching the inline default. */
  function scrollerForY(wrap) {
    var sel = wrap.getAttribute("data-scroll-y");
    if (sel) return wrap.querySelector(sel);
    var el = wrap.firstElementChild;
    // checkVisibility, not offsetParent: a box hidden by content-visibility keeps a
    // truthy offsetParent, so that test would pick a scroller nobody can see.
    while (el) {
      if (!el.checkVisibility || el.checkVisibility()) return el;
      el = el.nextElementSibling;
    }
    return wrap.firstElementChild;
  }

  function updateY(wrap) {
    var box = scrollerForY(wrap);
    if (!box) return;
    var max = box.scrollHeight - box.clientHeight;
    // Same 1px slack as the inline axis, for the same fractional-layout reason.
    wrap.classList.toggle("is-scroll-top", box.scrollTop > 1);
    wrap.classList.toggle("is-scroll-bottom", box.scrollTop < max - 1);
  }

  function wireY(wrap) {
    if (wrap.dataset.scrollYReady === "1") return;  // idempotent
    wrap.dataset.scrollYReady = "1";
    var apply = function () { updateY(wrap); };
    // Capture, and bound to the WRAPPER: `scroll` does not bubble, so a listener on
    // the wrapper only sees it in the capture phase -- and that is what survives the
    // scroller being swapped, where a listener bound to one child would not.
    wrap.addEventListener("scroll", apply, true);
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(apply);
      ro.observe(wrap);
      // Every candidate scroller, not just the live one: a display:none child
      // reports no box and fires the moment it gains one, so this single
      // registration covers BOTH the slide swap and content growing inside a
      // slide (KaTeX finishing, an image loading, a reveal-gate opening).
      Array.prototype.forEach.call(wrap.children, function (c) { ro.observe(c); });
    }
    apply();
  }

  function init(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    root.querySelectorAll("[data-scroll-x]").forEach(wire);
    root.querySelectorAll("[data-scroll-y]").forEach(wireY);
    // A scope that is itself a wrapper (a swapped-in fragment root) is not
    // returned by its own querySelectorAll.
    if (root.matches && root.matches("[data-scroll-x]")) wire(root);
    if (root.matches && root.matches("[data-scroll-y]")) wireY(root);
  }

  window.libliInitScrollAffordance = init;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(document); });
  } else {
    init(document);
  }
})();
