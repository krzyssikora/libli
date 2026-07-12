(function () {
  "use strict";

  // Watchdog boot flag: the pre-hide <style> block in lesson_unit.html arms
  // `.reveal-armed` render-blocking (no flash of un-revealed content), then a
  // DOMContentLoaded fallback disarms it again if this script never boots
  // (e.g. blocked by an extension). Setting this eagerly, at parse time, is
  // what lets that fallback see the engine is alive.
  window.__revealBooted = true;

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
    return gate; // plain gate <button>
  }

  // Shared cascade engine. Reveals following siblings from `triggerEl`'s wrapper,
  // stops after the next gate wrapper, dispatches libli:reveal, and moves focus.
  // Hides the trigger's own wrapper only when hideWrapper !== false (the plain gate
  // self-consumes; the fill-gate keeps its answered Q&A visible).
  function cascadeFrom(triggerEl, opts) {
    opts = opts || {};
    var hideWrapper = opts.hideWrapper !== false;
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
    btn.addEventListener("click", function () { reveal(btn); });
  }

  // Enhance every reveal-gate button under `root`. Exposed so the editor can
  // re-run it over the live-preview pane after each fragment swap, like
  // libliInitTabs/libliInitGallery. Idempotent.
  function initRevealGates(root) {
    var scope = root || document;
    var sel = "button.reveal-gate[data-reveal-gate]";
    if (scope.matches && scope.matches(sel)) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(sel), initOne);
  }

  window.libliInitRevealGates = initRevealGates;
  window.libliRevealCascade = cascadeFrom;
  initRevealGates(document);
})();
