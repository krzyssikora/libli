(function () {
  "use strict";

  // Parse-time boot flag: the lesson_unit.html prepaint watchdog fails the gate OPEN
  // (disarms the pre-hide) if this flag is still falsy at DOMContentLoaded, so a
  // booted reveal.js + a dead fillgate.js can't trap content permanently hidden.
  window.__fillGateBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function inputs(form) {
    return form.querySelectorAll('input[name="blank"]');
  }

  // Clear the previous attempt: drop wrong-markers and hide the message (never
  // destroy the message source node).
  function reset(form) {
    Array.prototype.forEach.call(inputs(form), function (inp) {
      inp.classList.remove("is-wrong");
    });
    var slot = form.querySelector("[data-fillgate-feedback]");
    if (slot) slot.hidden = true;
  }

  function showWrong(form, blanks) {
    var ins = inputs(form);
    for (var i = 0; i < ins.length; i++) {
      if (blanks && blanks[i] === false) ins[i].classList.add("is-wrong");
    }
    var msg = form.querySelector("[data-fillgate-message]");
    var slot = form.querySelector("[data-fillgate-feedback]");
    if (msg && slot) {
      slot.textContent = msg.textContent;  // copy the pre-translated text
      slot.hidden = false;
    }
  }

  function lock(form) {
    Array.prototype.forEach.call(inputs(form), function (inp) {
      inp.readOnly = true;
      inp.classList.add("is-correct");
    });
    var btn = form.querySelector(".fillgate__confirm");
    if (btn) btn.remove();  // Confirm is done
    var container = form.closest("[data-fillgate]");
    if (container) container.classList.add("fillgate--done");
    return container;
  }

  function submit(form) {
    var pk = form.getAttribute("data-element-pk");
    var url = form.getAttribute("data-check-url");
    if (!pk || pk === "0" || !url) return;  // unsaved preview: no-op
    reset(form);
    fetch(url, {
      method: "POST",
      headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
      body: new FormData(form),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.correct) {
          var container = lock(form);
          if (window.libliRevealCascade && container) {
            window.libliRevealCascade(container, { hideWrapper: false });
          }
        } else {
          showWrong(form, data.blanks);
        }
      })
      .catch(function () { /* leave gate closed, inputs editable */ });
  }

  function initOne(form) {
    if (form.dataset.fillgateReady === "1") return;
    form.dataset.fillgateReady = "1";
    var btn = form.querySelector(".fillgate__confirm");
    if (btn) btn.hidden = false;  // arm Confirm now that JS is live
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      submit(form);
    });
  }

  // Idempotent; re-run over the editor preview after each fragment swap.
  function initFillGates(root) {
    var scope = root || document;
    Array.prototype.forEach.call(
      scope.querySelectorAll("[data-fillgate] form"), initOne
    );
  }

  window.libliInitFillGates = initFillGates;
  initFillGates(document);
})();
