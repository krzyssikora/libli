(function () {
  "use strict";

  // Fail-open boot flag: the lesson_unit.html prepaint watchdog disarms the
  // pre-hide if this is still falsy at DOMContentLoaded, so a dead switchgate.js
  // can never trap content hidden.
  window.__switchGateBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function ring(cycler) {
    // ordered ring entries: placeholder first, then each option span
    var ph = cycler.querySelector(".switchgate__placeholder");
    var opts = cycler.querySelectorAll(".switchgate__option");
    return [ph].concat(Array.prototype.slice.call(opts));
  }

  function currentIndex(cycler) {
    // -1 == placeholder visible; else the 0-based option index
    var entries = ring(cycler);
    for (var i = 1; i < entries.length; i++) {
      if (!entries[i].hasAttribute("hidden")) return i - 1;
    }
    return -1;
  }

  function showEntry(cycler, ringPos) {
    var entries = ring(cycler);
    for (var i = 0; i < entries.length; i++) {
      if (i === ringPos) entries[i].removeAttribute("hidden");
      else entries[i].setAttribute("hidden", "");
    }
  }

  function advance(container) {
    var cycler = container.querySelector("[data-switchgate-cycler]");
    var entries = ring(cycler);
    // find current visible ring position (0 == placeholder)
    var pos = 0;
    for (var i = 0; i < entries.length; i++) {
      if (!entries[i].hasAttribute("hidden")) { pos = i; break; }
    }
    showEntry(cycler, (pos + 1) % entries.length);
    hideFeedback(container);  // a fresh attempt starts clean
  }

  function hideFeedback(container) {
    var fb = container.querySelector("[data-switchgate-feedback]");
    if (fb) fb.hidden = true;
  }

  function lock(container) {
    var cycler = container.querySelector("[data-switchgate-cycler]");
    if (cycler) cycler.disabled = true;
    var confirm = container.querySelector(".switchgate__confirm");
    if (confirm) confirm.remove();
    container.classList.add("switchgate--done");
  }

  function submit(container) {
    var pk = container.getAttribute("data-element-pk");
    var url = container.getAttribute("data-check-url");
    if (!pk || pk === "0" || !url) return;  // unsaved preview: no-op
    var cycler = container.querySelector("[data-switchgate-cycler]");
    var body = new FormData();
    body.append("choice", String(currentIndex(cycler)));
    fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf() },
      body: body,
    })
      .then(function (r) { return r.ok ? r.json() : { correct: false }; })
      .then(function (data) {
        if (data.correct) {
          lock(container);
          if (window.libliRevealCascade) {
            window.libliRevealCascade(container, { hideWrapper: false });
          }
        } else {
          var fb = container.querySelector("[data-switchgate-feedback]");
          if (fb) fb.hidden = false;
        }
      })
      .catch(function () { /* leave gate closed, widget editable */ });
  }

  function typesetMath(container) {
    if (window.renderMathInElement) {
      try { window.renderMathInElement(container); } catch (e) { /* noop */ }
    }
  }

  function initOne(container) {
    if (container.dataset.switchgateReady === "1") return;
    container.dataset.switchgateReady = "1";
    var cycler = container.querySelector("[data-switchgate-cycler]");
    var confirm = container.querySelector(".switchgate__confirm");
    if (confirm) confirm.hidden = false;  // arm Confirm now that JS is live
    if (cycler) {
      cycler.addEventListener("click", function () { advance(container); });
    }
    if (confirm) {
      confirm.addEventListener("click", function () { submit(container); });
    }
    typesetMath(container);
  }

  // Idempotent; re-run over the editor preview after each fragment swap.
  function initSwitchGates(root) {
    var scope = root || document;
    Array.prototype.forEach.call(
      scope.querySelectorAll("[data-switchgate]"), initOne
    );
  }

  window.libliInitSwitchGates = initSwitchGates;
  initSwitchGates(document);
})();
