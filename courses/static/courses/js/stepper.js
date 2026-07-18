(function () {
  "use strict";
  // Eager boot flag read by lesson_unit.html's DOMContentLoaded watchdog: if this
  // script never boots (blocked/404) the watchdog removes `stepper-armed` so the
  // full chain shows (fail-open). Set at parse time, like reveal.js.
  window.__stepperBooted = true;

  function shownCount(steps) {
    var n = 0;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].classList.contains("stepper-shown")) n++;
    }
    return n;
  }

  function restoreCount(root, total) {
    // Inline read of the {shown:N} blob -- storedFlag can't read a count. A missing
    // or non-integer `shown` (the fresh `{}` case) stays 1: never NaN, never 0 steps.
    var n = 1;
    try {
      var blob = JSON.parse(root.dataset.state || "{}");
      var parsed = parseInt(blob.shown, 10);
      if (parsed > 1) n = Math.min(parsed, total);
    } catch (e) {}
    return n;
  }

  function initOne(root) {
    // Idempotent: the editor preview re-runs this after each fragment swap.
    if (root.dataset.stepperReady === "1") return;
    root.dataset.stepperReady = "1";
    var steps = Array.prototype.slice.call(
      root.querySelectorAll("[data-stepper-step]")
    );
    if (!steps.length) return;
    // Restore: reveal the first N steps (N>=1). Boot only toggles classes -- it must
    // NOT call .focus()/scroll (that stays exclusive to user clicks below).
    var shown = restoreCount(root, steps.length);
    for (var i = 0; i < shown; i++) steps[i].classList.add("stepper-shown");
    root.classList.add("is-stepping");
    var btn = root.querySelector("[data-stepper-next]");
    if (!btn) return;
    if (shown >= steps.length) {
      btn.hidden = true; // nothing left to reveal
      return;
    }
    btn.hidden = false;
    btn.addEventListener("click", function () {
      var next = null;
      for (var i = 0; i < steps.length; i++) {
        if (!steps[i].classList.contains("stepper-shown")) {
          next = steps[i];
          break;
        }
      }
      if (!next) return;
      next.classList.add("stepper-shown");
      if (!next.hasAttribute("tabindex")) next.setAttribute("tabindex", "-1");
      next.focus();
      var count = shownCount(steps);
      // Fire-and-forget; no-ops in the editor preview (empty data-state-url).
      window.libliState.saveFlag(root, { shown: count });
      if (count >= steps.length) btn.hidden = true;
    });
  }

  function initStepper(root) {
    var scope = root || document;
    var sel = "[data-stepper]";
    if (scope.matches && scope.matches(sel)) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(sel), initOne);
  }

  window.libliInitStepper = initStepper;
  initStepper(document); // self-boot (lesson page + editor initial load)
})();
