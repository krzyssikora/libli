(function () {
  "use strict";
  // Eager boot flag read by lesson_unit.html's DOMContentLoaded watchdog: if this
  // script never boots (blocked/404) the watchdog removes `stepper-armed` so the
  // full chain shows (fail-open). Set at parse time, like reveal.js.
  window.__stepperBooted = true;

  function initOne(root) {
    // Idempotent: the editor preview re-runs this after each fragment swap.
    if (root.dataset.stepperReady === "1") return;
    root.dataset.stepperReady = "1";
    var steps = Array.prototype.slice.call(
      root.querySelectorAll("[data-stepper-step]")
    );
    if (!steps.length) return;
    // Reveal step 0 + arm Layer B (courses.css hides steps without stepper-shown).
    steps[0].classList.add("stepper-shown");
    root.classList.add("is-stepping");
    var btn = root.querySelector("[data-stepper-next]");
    if (!btn) return;
    if (steps.length < 2) {
      btn.hidden = true; // nothing to reveal
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
      var remaining = steps.some(function (s) {
        return !s.classList.contains("stepper-shown");
      });
      if (!remaining) btn.hidden = true;
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
