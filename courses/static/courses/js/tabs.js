(function () {
  "use strict";

  var i18n = window.TABS_I18N || { nav: "Tabs", prev: "Scroll tabs left", next: "Scroll tabs right" };

  function chevron(cls, pathD, label) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = cls;
    // Decorative: keyboard users move between tabs with the arrow keys, so the
    // chevrons are removed from the tab order and hidden from AT.
    b.setAttribute("aria-hidden", "true");
    b.tabIndex = -1;
    b.title = label;
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
      'focusable="false"><path d="' + pathD + '"/></svg>';
    return b;
  }

  function initOne(container) {
    // Idempotent: the editor preview pane is rebuilt on every fragment swap and re-runs
    // this over the whole pane. Re-entering would append a second tab bar.
    if (container.dataset.tabsReady === "1") return;

    var sections = Array.prototype.slice.call(container.querySelectorAll(".tabs__section"));
    if (!sections.length) return;
    container.dataset.tabsReady = "1";
    container.classList.add("tabs--js");

    // A tab id is unique only WITHIN one element. Namespace every DOM id with the join
    // row pk, or two tabs elements on one page produce duplicate ids and activating a
    // tab in one reveals a panel in the other.
    var eid = container.getAttribute("data-tabs-eid") || "0";

    var strip = document.createElement("div");
    strip.className = "tabs__strip";
    strip.setAttribute("role", "tablist");
    strip.setAttribute("aria-label", i18n.nav);

    var scroller = document.createElement("div");
    scroller.className = "tabs__scroller";
    scroller.appendChild(strip);

    var prev = chevron("tabs__chev tabs__chev--prev", "M15 6l-6 6 6 6", i18n.prev);
    var next = chevron("tabs__chev tabs__chev--next", "M9 6l6 6-6 6", i18n.next);

    var bar = document.createElement("div");
    bar.className = "tabs__bar";
    bar.appendChild(prev);
    bar.appendChild(scroller);
    bar.appendChild(next);
    container.insertBefore(bar, container.firstChild);

    var tabs = [];
    var panels = [];

    sections.forEach(function (section, k) {
      var label = section.querySelector("[data-tab-label]");
      var panel = section.querySelector("[data-tab-panel]");
      if (!label || !panel) return;
      var tid = panel.getAttribute("data-tab-id");
      var tabId = "tabs-" + eid + "-" + tid + "-tab";
      var panelId = "tabs-" + eid + "-" + tid + "-panel";

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tabs__tab";
      btn.id = tabId;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-controls", panelId);
      btn.textContent = label.textContent;
      strip.appendChild(btn);

      panel.id = panelId;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tabId);
      panel.tabIndex = 0;

      // The label headings STAY in the DOM (hidden by class on screen). @media print
      // reveals them; detaching or reusing the nodes would silently lose every panel
      // title from the printed lesson while the bodies still appear.
      btn.addEventListener("click", function () { select(k); });
      tabs.push(btn);
      panels.push(panel);
    });

    if (!tabs.length) return;

    var active = -1;
    function select(n, focus) {
      var i = Math.max(0, Math.min(tabs.length - 1, n));
      if (i === active) return;
      active = i;
      tabs.forEach(function (t, k) {
        var on = k === i;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;  // roving tabindex
        // `hidden` ATTRIBUTE, never an inline display:none -- an inline style cannot be
        // overridden by the @media print rule that reveals every panel.
        if (on) { panels[k].removeAttribute("hidden"); } else { panels[k].setAttribute("hidden", ""); }
      });
      if (focus) tabs[i].focus();
      scrollIntoStrip(tabs[i]);
      // A gallery inside a hidden panel measured zero height; tell it to re-measure now
      // that it is visible. gallery.js listens for this.
      panels[i].dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
    }

    strip.addEventListener("keydown", function (e) {
      var delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (delta) {
        e.preventDefault();
        // Automatic activation, per the ARIA authoring practices.
        select((active + delta + tabs.length) % tabs.length, true);
      } else if (e.key === "Home") {
        e.preventDefault(); select(0, true);
      } else if (e.key === "End") {
        e.preventDefault(); select(tabs.length - 1, true);
      }
    });

    function scrollIntoStrip(tab) {
      var l = tab.offsetLeft, r = l + tab.offsetWidth;
      if (l < scroller.scrollLeft) scroller.scrollLeft = l;
      else if (r > scroller.scrollLeft + scroller.clientWidth) scroller.scrollLeft = r - scroller.clientWidth;
    }

    // Overflow affordance: fade + chevron at whichever edge has more tabs.
    function updateOverflow() {
      if (!container.isConnected) {
        window.removeEventListener("resize", updateOverflow);
        return;
      }
      var max = scroller.scrollWidth - scroller.clientWidth;
      bar.classList.toggle("is-scroll-start", scroller.scrollLeft > 1);
      bar.classList.toggle("is-scroll-end", scroller.scrollLeft < max - 1);
    }
    scroller.addEventListener("scroll", updateOverflow);
    window.addEventListener("resize", updateOverflow);
    prev.addEventListener("click", function () { scroller.scrollLeft -= scroller.clientWidth * 0.7; });
    next.addEventListener("click", function () { scroller.scrollLeft += scroller.clientWidth * 0.7; });

    select(0);
    updateOverflow();
  }

  // Enhance every tabs element under `root`. Exposed so the editor can re-run it over
  // the live-preview pane after each fragment swap, like libliInitGallery. Idempotent.
  function initTabs(root) {
    var scope = root || document;
    if (scope.matches && scope.matches("[data-tabs]")) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-tabs]"), initOne);
  }

  window.libliInitTabs = initTabs;
  initTabs(document);
})();
