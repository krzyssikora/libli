(function () {
  "use strict";

  // Watchdog boot flag: the pre-hide <style> block in lesson_unit.html arms
  // `.reveal-armed` render-blocking (no flash of un-revealed content), then a
  // DOMContentLoaded fallback disarms it again if this script never boots
  // (e.g. blocked by an extension). The IIFE runs after parsing and before
  // DOMContentLoaded, which is what lets the watchdog see the engine is alive.
  window.__revealBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function storedOpen(btn) {
    try {
      var raw = btn.dataset.state;
      if (!raw) return false;
      var blob = JSON.parse(raw);
      return !!(blob && blob.open === true); // strict shape, not truthiness
    } catch (e) {
      return false; // drifted blob -> this gate simply stays live
    }
  }

  function save(btn) {
    var url = btn.dataset.stateUrl;
    if (!url) return; // editor preview: "" -> no-op
    var eid = parseInt(btn.dataset.elementPk, 10);
    if (!eid) return; // pk 0 == content object with no join row
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ element: eid, state: { open: true } }),
      keepalive: true, // survives unload
    }).catch(function () {}); // monotone: keep the DOM, ignore the body
  }

  // The nearest ancestor that defines a reveal cascade's boundary: a slide in
  // a slideshow lesson, or a tab panel inside a tabs element. The cascade
  // never crosses out of this scope.
  function scopeOf(btn) {
    return btn.closest("[data-tab-panel], .slide");
  }

  // The direct child of `scope` that contains `el` -- i.e. the wrapper node
  // the cascade walks sibling-by-sibling (a .lesson-block in a slide, or a
  // .tabs__child in a tab panel).
  function ownWrapper(el, scope) {
    var node = el;
    while (node && node.parentElement !== scope) node = node.parentElement;
    return node;
  }

  // Does this wrapper contain a reveal-gate button of its own? Mirrors the
  // pre-hide CSS selectors in lesson_unit.html exactly, since the JS cascade
  // and the CSS hide-guard must agree on where one gate's territory ends and
  // the next gate's begins.
  function isGateWrapper(wrapper, scope) {
    if (!wrapper) return false;
    var sel = scope.matches("[data-tab-panel]")
      ? ":scope > [data-reveal-gate]"
      : ":scope > .lesson-block__body > [data-reveal-gate]";
    return !!wrapper.querySelector(sel);
  }

  // The first sibling after a (now-consumed) gate wrapper that the cascade
  // revealed, used as a focus fallback when there is no next gate to land on.
  function firstRevealed(gateWrap, scope) {
    var n = gateWrap.nextElementSibling;
    while (n && !n.classList.contains("reveal-shown")) n = n.nextElementSibling;
    if (n && !n.hasAttribute("tabindex")) n.setAttribute("tabindex", "-1");
    return n;
  }

  // Resolve a FOCUSABLE node inside a gate wrapper. A plain gate is a <button>
  // (focusable); a fill-gate is a <div> whose first blank input is the focus target
  // (focusing the div itself is a silent no-op).
  function focusTargetIn(wrapper) {
    var gate = wrapper.querySelector("[data-reveal-gate]");
    if (!gate) return null;
    if (gate.matches("[data-fillgate]")) {
      var input = gate.querySelector('input[name="blank"]');
      if (input) return input;
      if (!gate.hasAttribute("tabindex")) gate.setAttribute("tabindex", "-1");
      return gate;
    }
    if (gate.matches("[data-switchgate]")) {
      return gate.querySelector("[data-switchgate-cycler]");
    }
    return gate; // plain gate <button>
  }

  // Shared cascade engine. Reveals following siblings from `triggerEl`'s wrapper,
  // stops after the next gate wrapper, dispatches libli:reveal, and moves focus.
  // Hides the trigger's own wrapper only when hideWrapper !== false (the plain gate
  // self-consumes; the fill-gate keeps its answered Q&A visible).
  function cascadeFrom(triggerEl, opts) {
    opts = opts || {};
    var hideWrapper = opts.hideWrapper !== false;
    var focus = opts.focus !== false;
    var scope = scopeOf(triggerEl);
    if (!scope) return;
    var gateWrap = ownWrapper(triggerEl, scope);
    if (!gateWrap) return;

    var node = gateWrap.nextElementSibling;
    var lastRevealed = null;
    while (node) {
      node.classList.add("reveal-shown");
      // Bubbling contract shared with tabs.js/gallery.js: a gallery or other
      // enhancer inside newly-visible content needs to know it just became
      // visible so it can re-measure (it was previously display:none).
      node.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      lastRevealed = node;
      if (isGateWrapper(node, scope)) break; // reveal the next gate, then stop
      node = node.nextElementSibling;
    }

    if (hideWrapper) {
      // Consume the trigger's gate: it has done its job, so drop it out of flow
      // rather than leaving a dead button behind.
      gateWrap.classList.remove("reveal-shown");
      gateWrap.hidden = true;
    }

    if (!focus) return; // restore skips focus-target resolution ENTIRELY

    // Focus management: land on the next gate's focusable target if the cascade
    // stopped at one, otherwise the first newly-revealed sibling, otherwise the
    // scope itself.
    var target =
      lastRevealed && isGateWrapper(lastRevealed, scope)
        ? focusTargetIn(lastRevealed)
        : null;
    target = target || firstRevealed(gateWrap, scope);
    if (!target) {
      scope.setAttribute("tabindex", "-1");
      // A non-slideshow `.slide` is `display: contents` (line in courses.css) so it
      // generates no box, and browsers refuse to move focus onto a box-less element —
      // focus() silently falls through to <body>. Promote it to a plain block (same
      // vertical flow, no visible change) so it can actually hold focus.
      if (window.getComputedStyle(scope).display === "contents") {
        scope.style.display = "block";
      }
      target = scope;
    }
    if (target && target.focus) target.focus();
  }

  function reveal(btn) {
    cascadeFrom(btn, { hideWrapper: true });
  }

  function initOne(btn) {
    // Idempotent: the editor preview pane is rebuilt on every fragment swap
    // and re-runs this over the whole pane. Re-entering would attach a
    // second click handler to the same button.
    if (btn.dataset.revealReady === "1") return;
    btn.dataset.revealReady = "1";
    btn.hidden = false; // un-hide every gate button; wrapper visibility gates it
    btn.addEventListener("click", function () { reveal(btn); save(btn); });
  }

  // RESTORABLE replaces initRevealGates's inline `sel`: ONE definition of "a plain gate",
  // read by both init and restore. MUST be assigned above initRevealGates and its call.
  var BARRIER    = "[data-reveal-gate]";                   // all three gate families
  var RESTORABLE = "button.reveal-gate[data-reveal-gate]"; // the plain gate only

  // Enhance every reveal-gate button under `root`. Exposed so the editor can
  // re-run it over the live-preview pane after each fragment swap, like
  // libliInitTabs/libliInitGallery. Idempotent.
  function initRevealGates(root) {
    var scope = root || document;
    var sel = RESTORABLE;
    if (scope.matches && scope.matches(sel)) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(sel), initOne);
  }

  function restoreGates(root) {
    // `ctx`, NOT `scope`: in this file "scope" means scopeOf()'s return. NO self-match
    // branch, deliberately -- restore is document-only and never exported, so `root`
    // can never itself be a gate.
    var ctx = root || document;
    var gates = Array.prototype.slice.call(ctx.querySelectorAll(BARRIER));

    // GROUP by scopeOf. Null-scope gates are dropped here and never bucketed.
    var scopes = [], buckets = [];
    gates.forEach(function (gate) {
      var scope = scopeOf(gate);
      if (!scope) return; // (b) null-scope: never walked
      var i = scopes.indexOf(scope);
      if (i === -1) { scopes.push(scope); buckets.push([gate]); }
      else { buckets[i].push(gate); }
    });

    // WALK each bucket in document order; `break` ends ONLY this bucket.
    buckets.forEach(function (bucket, bi) {
      var scope = scopes[bi];
      for (var j = 0; j < bucket.length; j++) {
        var gate = bucket[j];
        try {
          if (!isGateWrapper(ownWrapper(gate, scope), scope)) continue; // (a) mis-scoped
          if (!gate.matches(RESTORABLE)) break;   // fill/switch gate: a barrier
          if (!storedOpen(gate)) break;           // closed gate: prefix-closure
          cascadeFrom(gate, { hideWrapper: true, focus: false });
        } catch (e) {
          break; // unknown state: stop THIS scope
        }
      }
    });
  }

  window.libliInitRevealGates = initRevealGates;
  window.libliRevealCascade = cascadeFrom;
  // ORDER IS LOAD-BEARING, and it is the only thing guarding this: init MUST run first
  // so that even an uncaught throw inside restore leaves every gate un-hidden and
  // click-bound -- the student re-earns the content instead of being locked out of it.
  // There is no test for this (nothing in restore can throw once the null-scope discard
  // is in place); this comment is the guard. Do not reorder these two lines.
  initRevealGates(document);
  restoreGates(document);   // NEW -- restoreGates is NOT exported (editor.js:77 must not reach it)
})();
