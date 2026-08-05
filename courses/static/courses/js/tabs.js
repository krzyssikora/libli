(function () {
  "use strict";

  // Per-key defaults. `window.TABS_I18N || {…}` uses the fallback object ONLY when the
  // global is entirely absent — and all three templates always define it. So a template
  // missing a carousel key yields undefined, not English: aria-label="undefined" and a
  // throw on .replace. Read every key through t().
  var i18n = window.TABS_I18N || {};
  function t(key, fallback) {
    // `|| fallback`, deliberately NOT a typeof check. A type guard would be marginally
    // safer at runtime but would swallow the ONE injection the error-bail e2e uses to
    // force a throw (a truthy non-string that passes the default and then dies on
    // .replace) — leaving the try/catch with no test that can go RED. Spec wording:
    // "Read every new key as `i18n.x || "…"`".
    return i18n[key] || fallback;
  }
  var FADE_MS = 320;  // MUST match the .el--tabs carousel transition in courses.css

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

  // --- scoping ---------------------------------------------------------------
  // Since the depth-3 lift a tabs element may legally contain ANOTHER tabs element
  // (outer [data-tabs] > .tabs__section > .tabs__panel > .tabs__child > inner
  // [data-tabs] > its own .tabs__section). querySelectorAll is DESCENDANT-wide, so an
  // unscoped lookup from the outer container swallows the inner instance's nodes: the
  // outer strip grows the inner element's labels as extra buttons, the outer rewrites
  // the inner's panel ids, and selecting one of those stray buttons hides the outer
  // panel that CONTAINS it -- the element goes blank. Every lookup below therefore
  // rejects nodes owned by a nested instance, which also makes initTabs' visit order
  // irrelevant.

  // The .tabs__section elements belonging to `container` itself.
  function ownSections(container) {
    var all = Array.prototype.slice.call(container.querySelectorAll(".tabs__section"));
    return all.filter(function (s) {
      return s.closest("[data-tabs]") === container;
    });
  }

  // The first node matching `selector` that belongs to `section` itself. Scanning all
  // matches rather than taking querySelector's first keeps this correct even if the
  // template ever wraps the label or panel: a nested instance's node is skipped
  // instead of being mistaken for this section's own.
  function ownPart(section, selector) {
    var nodes = section.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].closest(".tabs__section") === section) return nodes[i];
    }
    return null;
  }

  function initOne(container) {
    // Idempotent: the editor preview pane is rebuilt on every fragment swap and re-runs
    // this over the whole pane. Re-entering would append a second tab bar.
    if (container.dataset.tabsReady === "1") return;

    var sections = ownSections(container);
    if (!sections.length) return;
    container.dataset.tabsReady = "1";
    container.classList.add("tabs--js");

    // EXACT match only: null, "", a stale cached fragment or a future third mode all
    // fall through to the tab strip. There is no undefined third path. (The CSS keys
    // tabs-mode rules on the literal [data-display="tabs"] — a deliberate asymmetry,
    // since a blank element is a worse failure than a duplicated label.)
    //
    // No `eid` argument: the carousel branch does NO id work (the template already emits
    // both the -panel and -label ids, namespaced). Passing it here would also read the
    // variable before `var eid = …` assigns it a few lines below.
    if (container.getAttribute("data-display") === "carousel") {
      initCarousel(container, sections);
      return;
    }

    // A tab id is unique only WITHIN one element. Namespace every DOM id with the join
    // row pk, or two tabs elements on one page produce duplicate ids and activating a
    // tab in one reveals a panel in the other.
    var eid = container.getAttribute("data-tabs-eid") || "0";

    var strip = document.createElement("div");
    strip.className = "tabs__strip";
    strip.setAttribute("role", "tablist");
    strip.setAttribute("aria-label", t("nav", "Tabs"));

    var scroller = document.createElement("div");
    scroller.className = "tabs__scroller";
    scroller.appendChild(strip);

    var prev = chevron("tabs__chev tabs__chev--prev", "M15 6l-6 6 6 6", t("prev", "Scroll tabs left"));
    var next = chevron("tabs__chev tabs__chev--next", "M9 6l6 6-6 6", t("next", "Scroll tabs right"));

    var bar = document.createElement("div");
    bar.className = "tabs__bar";
    bar.appendChild(prev);
    bar.appendChild(scroller);
    bar.appendChild(next);
    container.insertBefore(bar, container.firstChild);

    var tabs = [];
    var panels = [];

    sections.forEach(function (section, k) {
      var label = ownPart(section, "[data-tab-label]");
      var panel = ownPart(section, "[data-tab-panel]");
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
      // CLONE the heading's child nodes -- never copy its textContent. math.js runs
      // BEFORE this file in document order on every page that loads both, so by now a
      // label carrying inline math is already a <span class="katex"> subtree, and
      // textContent would flatten it to KaTeX's mangled fallback ("x2x^2x2" for x^2).
      // Cloning also makes the order irrelevant: if math.js has NOT run yet the button
      // receives the raw text and, since the strip lives inside `.el--tabs`, the later
      // auto-render pass typesets the button itself. Cloning (not innerHTML) keeps a
      // label that is plain text plain text -- the escaping the server did survives.
      Array.prototype.forEach.call(label.childNodes, function (n) {
        btn.appendChild(n.cloneNode(true));
      });
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

  // NOTE: this helper does NOT set the class — `b.className = cls` would be a parameter,
  // and the drift guard only matches a string LITERAL on the right of `className =`. The
  // caller assigns it literally (see initCarousel), exactly the trap the existing
  // chevron(cls, …) helper falls into for .tabs__chev.
  function iconBtn(pathD, label) {
    var b = document.createElement("button");
    b.type = "button";
    b.setAttribute("aria-label", label);
    b.title = label;
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
      'focusable="false"><path d="' + pathD + '"/></svg>';
    return b;
  }

  function initCarousel(container, sections) {
    var stage = container.querySelector(":scope > .tabs__stage");  // :scope, not a bare query:
    // the branch must never depend on tree order to avoid a nested instance's stage
    if (!stage || sections.length < 2) {
      // Route the degenerate case through the same undo as a bail: initOne has already
      // added .tabs--js, and courses.css separates stacked slides with
      // `:not(.tabs--js) .tabs__section + .tabs__section { margin-top }` — leaving the
      // class here makes the slides butt together. Reachable from a stale cached
      // fragment served before the template change.
      container.classList.remove("tabs--js");
      return;
    }

    // PER-INSTANCE closure state, declared together (gallery.js:31-32). Never at module
    // scope: a shared `pending` would let one carousel finalise another's in-flight
    // fade, and a carousel may legally contain a carousel.
    var idx = -1, dead = false, pending = null;
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");

    function clamp(n) { return Math.max(0, Math.min(sections.length - 1, n)); }

    function settleHidden(el) {
      el.classList.remove("is-active");
      el.style.opacity = "";
      el.setAttribute("aria-hidden", "true");
      el.setAttribute("inert", "");
    }

    function finalizePending() {
      if (!pending) return;          // REQUIRED: pending is unset for the first TWO calls
      clearTimeout(pending.timer);
      if (pending.out && pending.out !== pending.inn) settleHidden(pending.out);
      pending.inn.classList.add("is-active");
      pending.inn.style.opacity = "";
      pending = null;
    }

    function updateIndicator() {
      dots.forEach(function (d, k) {
        d.classList.toggle("is-active", k === idx);
        if (k === idx) { d.setAttribute("aria-current", "true"); }
        else { d.removeAttribute("aria-current"); }
      });
      // Folded in here exactly as gallery.js does (:95), NOT deferred: the first show
      // must evaluate this string — the forced-throw e2e depends on it.
      status.textContent = t("slidePos", "Slide {n} of {total}")
        .replace("{n}", idx + 1).replace("{total}", sections.length);
    }

    function show(n) {
      if (dead) return;                                     // DEPARTURE: error-bail guard
      var target = clamp(n);
      if (idx !== -1 && target === idx) return;             // sentinel-aware
      finalizePending();
      var focusedArrow = document.activeElement === prev ? prev
                       : document.activeElement === next ? next : null;   // capture, see 4b
      var out = sections[idx];       // undefined on the first call, because idx === -1
      idx = target;
      var inn = sections[idx];
      updateIndicator();
      prev.disabled = idx === 0;
      prev.setAttribute("aria-disabled", idx === 0 ? "true" : "false");
      next.disabled = idx === sections.length - 1;
      next.setAttribute("aria-disabled", idx === sections.length - 1 ? "true" : "false");
      // 4b, DEPARTURE: disabling the focused element blurs it to <body>, which puts
      // focus outside the container and kills the keydown handler. Mutually exclusive
      // with rescueFocus by construction (that returns early when focus is on the bar).
      if (focusedArrow && focusedArrow.disabled) {
        (focusedArrow === prev ? next : prev).focus();
      }
      inn.removeAttribute("aria-hidden");
      inn.removeAttribute("inert");   // must precede any focus move into this subtree
      if (!out) {                     // first show — no rescue, no fade
        inn.style.opacity = "";
        inn.classList.add("is-active");
        inn.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
        return;
      }
      rescueFocus(out, inn);
      out.setAttribute("aria-hidden", "true");
      out.setAttribute("inert", "");
      inn.style.opacity = "0";
      void inn.offsetWidth;
      inn.classList.add("is-active");
      inn.style.opacity = "1";
      out.style.opacity = "0";
      var delay = reduce && reduce.matches ? 0 : FADE_MS;
      pending = { out: out, inn: inn, timer: null };
      pending.timer = setTimeout(function () {
        settleHidden(out); inn.style.opacity = ""; pending = null;
      }, delay);
      // DEPARTURE: bubbles is load-bearing — a nested gallery's own container listener
      // cannot see an event dispatched on an ancestor section; only the
      // document-delegated listener rescues it, and that needs the event to reach it.
      inn.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
    }

    // rescueFocus and the keyboard handler are added in Task 8. Stub for now:
    function rescueFocus(_out, _inn) {}

    function bail() {
      dead = true;
      sections.forEach(function (s) {
        s.removeAttribute("inert");
        s.removeAttribute("aria-hidden");
        s.classList.remove("is-active");
        s.style.opacity = "";
      });
      if (nav && nav.parentNode) nav.parentNode.removeChild(nav);
      stage.style.minHeight = "";
      container.classList.remove("tabs--carousel");
      // .tabs--js too: courses.css separates stacked slides with
      // `:not(.tabs--js) .tabs__section + .tabs__section { margin-top }`, and the class
      // is added before the branch is entered. Leaving it makes the slides butt together.
      container.classList.remove("tabs--js");
    }

    // NOTE ON STRUCTURE: `nav` is declared here (so bail() closes over it) but everything
    // that can THROW — the i18n .replace calls, the DOM construction — happens inside the
    // try below. `.tabs--js` is already applied by initOne, so an uncaught throw anywhere in
    // the branch would leave tabsReady="1", no nav and no bail, and the stacked slides would
    // butt together. The spec's promise is "ANY throw inside the branch", not one culprit.
    var nav = null, prev = null, next = null, dotWrap = null, dots = [], status = null;

    try {
      nav = document.createElement("nav");
      nav.className = "tabs__cbar";
      nav.setAttribute("aria-label", t("carouselNav", "Carousel"));
      prev = iconBtn("M15 6l-6 6 6 6", t("prevSlide", "Previous slide"));
      prev.className = "tabs__cprev";   // literal, single token: the drift guard needs both
      next = iconBtn("M9 6l6 6-6 6", t("nextSlide", "Next slide"));
      next.className = "tabs__cnext";
      dotWrap = document.createElement("div");
      dotWrap.className = "tabs__dots";
      dots = sections.map(function (_s, k) {
        var d = document.createElement("button");
        d.type = "button";
        d.className = "tabs__dot";
        d.setAttribute("aria-label", t("goToSlide", "Go to slide {n}").replace("{n}", k + 1));
        d.addEventListener("click", function () { show(k); });
        dotWrap.appendChild(d);
        return d;
      });
      status = document.createElement("span");
      status.className = "tabs__status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      nav.appendChild(prev); nav.appendChild(dotWrap); nav.appendChild(next);
      nav.appendChild(status);   // inside the <nav>, as gallery.js does

      sections.forEach(function (s) {
        s.setAttribute("role", "group");
        s.setAttribute("aria-roledescription", "slide");
        // A named bare <section> maps to `region` — a LANDMARK — per HTML-AAM; without
        // the group role, 10 slides would become 10 landmarks per carousel.
        var label = ownPart(s, "[data-tab-label]");
        if (label && label.id) s.setAttribute("aria-labelledby", label.id);
        s.setAttribute("aria-hidden", "true");
        s.setAttribute("inert", "");
      });
      container.appendChild(nav);
      prev.addEventListener("click", function () { show(idx - 1); });
      next.addEventListener("click", function () { show(idx + 1); });
      show(0);
      container.classList.add("tabs--carousel");   // LAST: the gate
    } catch (e) {
      bail();
      if (window.console && console.error) console.error(e);
    }
  }

  // Enhance every tabs element under `root`. Exposed so the editor can re-run it over
  // the live-preview pane after each fragment swap, like libliInitGallery. Idempotent.
  function initTabs(root) {
    var scope = root || document;
    if (scope.matches && scope.matches("[data-tabs]")) initOne(scope);
    // DESCENDANT-wide on purpose, and the ONE lookup in this file that must stay so:
    // a tabs element nested inside another tabs element is itself a [data-tabs] that
    // needs its own strip. initOne only ever touches its own sections (ownSections),
    // so visiting outer-before-inner is safe.
    Array.prototype.forEach.call(scope.querySelectorAll("[data-tabs]"), initOne);
  }

  window.libliInitTabs = initTabs;
  initTabs(document);
})();
