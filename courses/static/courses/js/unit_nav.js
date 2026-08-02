(function () {
  "use strict";
  var KEY = "libli_unit_tree_collapsed";
  var html = document.documentElement;

  function store(val) {
    try { localStorage.setItem(KEY, val); } catch (e) {}
  }
  function isCollapsed() { return html.classList.contains("unit-tree-collapsed"); }

  // checkVisibility() is Chromium 105 / Firefox 125 / Safari 17.4. On anything older the
  // method is undefined and calling it throws — and because centerActive() runs at module
  // scope, that throw would abort the rest of this file and leave the mobile drawer
  // unwired (its FAB ships [hidden] and is only revealed by the JS below). Fall back to
  // the historical offsetParent test: imperfect for content-visibility (it keeps a folded
  // group's hidden links in the focus trap, i.e. today's behaviour) but never fatal.
  function isVisible(el) {
    return el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null;
  }

  // Centre the active unit within the rail. Self-contained: re-queries at CALL time
  // (never a stale module-eval reference) and owns its own guards, so both call sites
  // are unconditional one-liners. Scroll the rail CONTAINER directly rather than
  // active.scrollIntoView({block:"center"}): the latter walks every scrollable
  // ancestor and could also nudge the window/article.
  function centerActive() {
    var tree = document.querySelector("[data-unit-tree]");
    // Only when expanded (labels visible).
    if (!tree || isCollapsed()) return;
    // Scope the lookup to the rail: the mobile drawer renders a SECOND .is-active node.
    var active = tree.querySelector(".unit-tree__unit.is-active");
    if (!active) return;
    // The student folded the group holding the active unit. NOT `offsetParent === null`:
    // a closed <details> hides content with content-visibility (Chromium 131+), so
    // offsetParent stays truthy and the element keeps a STALE non-zero rect — which the
    // arithmetic below turns into a positive, meaningless scroll target (measured: 383px).
    // checkVisibility() is false for both display:none and content-visibility-skipped.
    if (!isVisible(active)) return;

    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // getBoundingClientRect().top is the border-box outer edge; clientTop reconciles it
    // with scrollTop's padding-box origin. scrollTo clamps out-of-range targets.
    var delta = active.getBoundingClientRect().top - tree.getBoundingClientRect().top;
    var target = tree.scrollTop + delta - tree.clientTop - (tree.clientHeight - active.offsetHeight) / 2;
    tree.scrollTo({ top: target, behavior: reduce ? "auto" : "smooth" });
  }

  // TWO desktop collapse controls, each visible in exactly one state: the in-rail
  // `‹` while expanded, the gutter pin while collapsed. Looked up INDEPENDENTLY
  // and null-guarded. Note there is no `if (...) { ... }` wrapper and no early
  // return: centerActive() below and the whole mobile-drawer block after it must
  // run regardless, which an early return would silently kill (see the comment at
  // the top of this file for the same hazard from a different cause).
  var railToggle = document.querySelector("[data-unit-tree-toggle]");
  var pin = document.querySelector("[data-unit-tree-pin]");
  var controls = [railToggle, pin].filter(Boolean);

  // Module scope, and it ITERATES: both controls must report the same state. The
  // label swap applies only to controls carrying BOTH data-label-* attributes, so
  // the pin's static label is left alone — it is only ever visible collapsed, so
  // it has nothing to swap to.
  function syncToggle(collapsed) {
    controls.forEach(function (el) {
      el.setAttribute("aria-expanded", collapsed ? "false" : "true");
      var expand = el.getAttribute("data-label-expand");
      var collapse = el.getAttribute("data-label-collapse");
      if (expand && collapse) {
        el.setAttribute("aria-label", collapsed ? expand : collapse);
      }
    });
  }

  function onToggleClick() {
    // ORDER IS LOAD-BEARING. Flip first: the control we are about to focus is
    // display:none until the class changes, and .focus() on a display:none element
    // is a silent no-op that drops focus to <body> — exactly the failure the focus
    // move exists to prevent.
    var collapsed = html.classList.toggle("unit-tree-collapsed");
    store(collapsed ? "1" : "0");
    syncToggle(collapsed);
    // Whichever control was clicked is now display:none, so move focus to the one
    // that just became visible, or a keyboard user is stranded. preventScroll:
    // focus() otherwise scrolls .unit-tree (overflow-y:auto) into view right before
    // centerActive() issues its own scrollTo — and a UA scroll does NOT pass through
    // the rail.scrollTo monkeypatch that the folded-group test counts.
    var next = collapsed ? pin : railToggle;
    if (next) next.focus({ preventScroll: true });
    // Expanding restores the labels — re-centre, or the student lands at scroll-top
    // with the active unit an arbitrary distance away. Nothing to centre when collapsing.
    if (!collapsed) centerActive();
  }

  controls.forEach(function (el) {
    el.addEventListener("click", onToggleClick);
  });
  // Unconditional: with an empty list this is a no-op, so a guard would buy nothing.
  syncToggle(isCollapsed());

  centerActive();   // on load

  // ── Mobile drawer with a self-contained focus trap (catalog_modal.js has none). ──
  var fab = document.querySelector("[data-unit-drawer-open]");
  var drawer = document.querySelector("[data-unit-drawer]");
  if (fab && drawer) {
    var panel = drawer.querySelector(".unit-drawer__panel");
    var lastFocus = null;

    // Progressive enhancement: the FAB ships with [hidden] (inert with JS off). Reveal
    // it now that JS can open the drawer; the mobile CSS shows it via :not([hidden]).
    fab.hidden = false;

    function focusable() {
      return Array.prototype.slice.call(
        // `summary` is natively tabbable but matches none of the other selectors, so
        // without it a trailing folded group's summary sits in the tab order yet outside
        // the trap's items list — and Tab escapes the drawer.
        panel.querySelectorAll('a[href], button:not([disabled]), summary, [tabindex]:not([tabindex="-1"])')
        // checkVisibility(), NOT offsetParent: a closed <details> hides its content with
        // content-visibility (Chromium 131+), which leaves offsetParent truthy. offsetParent
        // would keep hidden unit links in the list, so items[last] would be unfocusable and
        // the wrap would never fire — the trap would still leak.
      ).filter(function (el) { return isVisible(el); });
    }
    function onKeydown(e) {
      if (e.key === "Escape") { closeDrawer(); return; }
      if (e.key !== "Tab") return;
      var items = focusable();
      if (!items.length) return;
      var first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
    function openDrawer() {
      if (!drawer.hidden) return; // already open — don't clobber lastFocus
      lastFocus = document.activeElement;
      drawer.hidden = false;
      fab.setAttribute("aria-expanded", "true");
      // scroll the active unit into view within the drawer
      var act = drawer.querySelector(".unit-tree__unit.is-active");
      if (act) act.scrollIntoView({ block: "center" });
      var items = focusable();
      (items[0] || panel).focus();
      document.addEventListener("keydown", onKeydown, true);
    }
    function closeDrawer() {
      drawer.hidden = true;
      fab.setAttribute("aria-expanded", "false");
      document.removeEventListener("keydown", onKeydown, true);
      if (lastFocus && lastFocus.focus) lastFocus.focus();
    }

    fab.addEventListener("click", openDrawer);
    drawer.addEventListener("click", function (e) {
      if (e.target.closest("[data-unit-drawer-close]")) closeDrawer();
    });

    // If the viewport crosses to desktop while open, close (the inline tree takes over).
    var mq = window.matchMedia("(min-width: 641px)");
    (mq.addEventListener ? mq.addEventListener.bind(mq, "change") : mq.addListener.bind(mq))(function (e) {
      if (e.matches && !drawer.hidden) closeDrawer();
    });
  }
})();
