(function () {
  "use strict";
  var KEY = "libli_unit_tree_collapsed";
  var html = document.documentElement;

  function store(val) {
    try { localStorage.setItem(KEY, val); } catch (e) {}
  }
  function isCollapsed() { return html.classList.contains("unit-tree-collapsed"); }

  // Desktop collapse toggle.
  var toggle = document.querySelector("[data-unit-tree-toggle]");
  if (toggle) {
    var EXPAND = toggle.getAttribute("data-label-expand");
    var COLLAPSE = toggle.getAttribute("data-label-collapse");
    function syncToggle(collapsed) {
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      // Announce the ACTION the button performs in its current state.
      if (EXPAND && COLLAPSE) toggle.setAttribute("aria-label", collapsed ? EXPAND : COLLAPSE);
    }
    toggle.addEventListener("click", function () {
      var collapsed = html.classList.toggle("unit-tree-collapsed");
      store(collapsed ? "1" : "0");
      syncToggle(collapsed);
    });
    syncToggle(isCollapsed());
  }

  // Auto-scroll the active unit into view — only when expanded (labels visible),
  // after the pre-paint collapse restore has already run on <html>. Scroll the rail
  // CONTAINER directly rather than active.scrollIntoView({block:"center"}): the
  // latter walks every scrollable ancestor and could also nudge the window/article
  // on load. Scope the active lookup to the rail so the mobile drawer's second
  // .is-active node is never selected.
  var tree = document.querySelector("[data-unit-tree]");
  var active = tree && tree.querySelector(".unit-tree__unit.is-active");
  if (tree && active && !isCollapsed()) {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Center the active item within the rail, in the rail's scroll coordinates.
    // getBoundingClientRect().top is the border-box outer edge; clientTop (top
    // border, 0 today) reconciles it with scrollTop's padding-box origin so the
    // formula survives a future top-border. scrollTo clamps out-of-range targets.
    var delta = active.getBoundingClientRect().top - tree.getBoundingClientRect().top;
    var target = tree.scrollTop + delta - tree.clientTop - (tree.clientHeight - active.offsetHeight) / 2;
    tree.scrollTo({ top: target, behavior: reduce ? "auto" : "smooth" });
  }

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
      ).filter(function (el) { return el.checkVisibility(); });
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
