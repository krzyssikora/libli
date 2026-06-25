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
  // after the pre-paint collapse restore has already run on <html>.
  var active = document.querySelector(".unit-tree__unit.is-active");
  if (active && !isCollapsed()) {
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    active.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  }
  // NOTE: spec §3.3 mandates scrollIntoView({block:"center"}). It walks every scrollable
  // ancestor, so in principle it could also nudge the window (jumping the article), not
  // just the sticky tree rail. If the Task-7 screenshot/e2e pass reveals a page jump,
  // switch to scrolling the container directly:
  //   var tree = document.querySelector("[data-unit-tree]");
  //   if (tree && active) tree.scrollTop = active.offsetTop - tree.clientHeight / 2;
  // (the sticky/overflow-y:auto tree is the intended scroll target).
})();
