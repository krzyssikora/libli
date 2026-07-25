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

  function init(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    root.querySelectorAll("[data-scroll-x]").forEach(wire);
    // A scope that is itself a wrapper (a swapped-in fragment root) is not
    // returned by its own querySelectorAll.
    if (root.matches && root.matches("[data-scroll-x]")) wire(root);
  }

  window.libliInitScrollAffordance = init;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(document); });
  } else {
    init(document);
  }
})();
