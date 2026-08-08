(function () {
  "use strict";

  // Set at PARSE TIME, as reveal.js:9 and stepper.js:6 do: the IIFE runs after
  // parsing and before DOMContentLoaded, which is what lets the inline watchdog
  // see the engine is alive. Because it is already true by the time init runs,
  // the watchdog CANNOT catch a mid-init throw -- hence the try/catch below,
  // mirroring tabs.js's bail() (:435-450).
  window.__beforeAfterBooted = true;

  var AFTER = "after"; // must match BeforeAfterElement.AFTER_SLOT_ID (guard test)

  function ownPanels(container) {
    // Ownership, not containment: a before/after may legally contain another one,
    // and a descendant-wide lookup would let the outer instance drive the inner's
    // panels (tabs.js:34-63).
    var all = container.querySelectorAll(".ba__panel");
    var mine = [];
    for (var i = 0; i < all.length; i++) {
      if (all[i].closest("[data-beforeafter]") === container) mine.push(all[i]);
    }
    return mine;
  }

  function ownToggle(container) {
    var all = container.querySelectorAll(".ba__toggle");
    for (var i = 0; i < all.length; i++) {
      if (all[i].closest("[data-beforeafter]") === container) return all[i];
    }
    return null;
  }

  // Per-instance recovery: un-arm THIS container only, so one bad instance never
  // strands its siblings. .ba--dead is the per-instance analogue of
  // html:not(.ba-js) and shares its declarations by grouped selector.
  function killOne(container) {
    var panels = ownPanels(container);
    for (var i = 0; i < panels.length; i++) panels[i].removeAttribute("hidden");
    delete container.dataset.baReady;
    container.classList.add("ba--dead");
  }

  function initOne(container) {
    // Idempotent: the editor preview pane is rebuilt on every fragment swap and
    // re-runs init over the whole pane. Read/write through the dataset PROPERTY --
    // setAttribute("data-baReady", ...) lowercases to data-baready, which
    // dataset.baReady would never read, silently defeating this guard.
    if (container.dataset.baReady === "1") return;

    try {
      var panels = ownPanels(container);
      var toggle = ownToggle(container);
      if (panels.length !== 2 || !toggle) {
        // NOT a bare `return`. A malformed instance that simply returns gets no
        // `hidden` (fine) but also no `.ba--dead`, so once the boot removes
        // ba-armed the page shows both panels with the headings still
        // .visually-hidden and a live-but-dead toggle -- the exact "unlabelled
        // panels with a dead button" state the recovery contract exists to
        // exclude. Route it into the SAME degraded state as every other failure.
        killOne(container);
        if (window.console && console.error) {
          console.error("beforeafter.js: malformed instance", container);
        }
        return;
      }
      container.dataset.baReady = "1";

      for (var i = 0; i < panels.length; i++) {
        if (panels[i].getAttribute("data-ba-side") === AFTER) {
          // `hidden` ATTRIBUTE, never an inline display:none -- an inline style
          // cannot be overridden by the @media print rule that reveals both.
          panels[i].setAttribute("hidden", "");
        }
      }

      toggle.addEventListener("click", function () {
        var showingAfter = toggle.getAttribute("aria-pressed") === "true";
        var incoming = null;
        var outgoing = null;
        for (var k = 0; k < panels.length; k++) {
          var isAfter = panels[k].getAttribute("data-ba-side") === AFTER;
          if (isAfter === !showingAfter) incoming = panels[k];
          else outgoing = panels[k];
        }
        // ORDER IS LOAD-BEARING: un-hide the incoming panel FIRST, then hide the
        // outgoing one, then aria-pressed, then dispatch. A listener that measures
        // synchronously would read zero if the event fired first -- and the
        // gallery e2e would not catch it, because tabs.js's listener is
        // rAF-deferred and would mask the ordering.
        incoming.removeAttribute("hidden");
        outgoing.setAttribute("hidden", "");
        toggle.setAttribute("aria-pressed", showingAfter ? "false" : "true");
        // bubbles: a gallery/carousel/table inside the panel measured zero height
        // while hidden and needs to re-measure now that it is visible.
        incoming.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      });
    } catch (e) {
      killOne(container);
      if (window.console && console.error) console.error(e);
    }
  }

  // Root-scoped ENHANCER. Wraps each initOne so a throw can never escape into the
  // caller: editor.js calls this in a sequence of re-init calls, and an escaping
  // throw would abort every enhancer sequenced after it.
  function initAll(root) {
    var scope = root || document;
    if (scope.matches && scope.matches("[data-beforeafter]")) initOne(scope);
    var nodes = scope.querySelectorAll("[data-beforeafter]");
    for (var i = 0; i < nodes.length; i++) {
      try {
        initOne(nodes[i]);
      } catch (e) {
        if (window.console && console.error) console.error(e);
      }
    }
  }

  window.libliInitBeforeAfter = initAll;

  // Document-level boot: the ONLY place that mutates <html>.
  try {
    initAll(document);
    document.documentElement.classList.remove("ba-armed");
  } catch (e) {
    if (window.__baDisarm) window.__baDisarm();
    if (window.console && console.error) console.error(e);
  }
})();
