(function () {
  "use strict";

  // Parse-time boot flag, mirroring fillgate.js / switchgate.js: lesson_unit.html's
  // prepaint watchdog disarms the pre-hide at DOMContentLoaded if this is still
  // falsy, so a dead filltable.js cannot trap content permanently hidden.
  window.__fillTableBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function inputs(root) {
    return Array.prototype.slice.call(root.querySelectorAll(".filltable__input"));
  }

  function paint(root, cells) {
    (cells || []).forEach(function (cell) {
      var inp = root.querySelector(
        '.filltable__input[data-r="' + cell.r + '"][data-c="' + cell.c + '"]'
      );
      if (!inp) return;
      inp.classList.remove("filltable__input--correct", "filltable__input--incorrect");
      if (cell.correct === true) inp.classList.add("filltable__input--correct");
      else if (cell.correct === false) inp.classList.add("filltable__input--incorrect");
    });
  }

  function lock(root) {
    inputs(root).forEach(function (inp) {
      inp.disabled = true;
    });
    var btn = root.querySelector(".filltable__confirm");
    if (btn) btn.hidden = true;
  }

  function summarize(root, ok) {
    var s = root.querySelector(".filltable__summary");
    if (!s) return;
    s.hidden = false;
    s.classList.toggle("filltable__summary--success", ok);
    s.classList.toggle("filltable__summary--retry", !ok);
    s.textContent = ok
      ? root.dataset.successMsg || "Great!"
      : root.dataset.retryMsg || "Try again";
  }

  function submit(root) {
    var pk = root.dataset.elementPk;
    var url = root.dataset.checkUrl;
    if (!pk || pk === "0" || !url) return; // unsaved preview
    var body = new FormData();
    inputs(root).forEach(function (inp) {
      body.append("r" + inp.dataset.r + "c" + inp.dataset.c, inp.value);
    });
    fetch(url, { method: "POST", headers: { "X-CSRFToken": csrf() }, body: body, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        paint(root, data.cells || []);
        summarize(root, !!data.all_correct);
        if (data.all_correct === true && (data.cells || []).length > 0) {
          lock(root);
          // The attribute guard is load-bearing: without it an UNGATED table also
          // cascades, adding .reveal-shown to its siblings and -- since `focus`
          // defaults to true -- moving focus and scrolling on every correct answer.
          // The libliRevealCascade guard is a defensive load-order check mirroring
          // fillgate.js/switchgate.js (reveal.js is loaded before this file, and
          // unconditionally in the editor).
          if (root.hasAttribute("data-reveal-gate") && window.libliRevealCascade) {
            // hideWrapper:false -- the solved table stays on screen with its green
            // cells; unlike a button gate, its content IS the student's work.
            window.libliRevealCascade(root, { hideWrapper: false });
          }
          // UNCHANGED: state.py::_val_done stores only {"done": True}, so sending
          // `open` here would be dead code. The restore path derives it in
          // FillTableElement.render instead.
          window.libliState.saveFlag(root, { done: true });
        }
      })
      .catch(function () { /* fail-open: leave widget interactive */ });
  }

  function initOne(root) {
    if (root.dataset.filltableReady === "1") return;
    root.dataset.filltableReady = "1";
    if (window.libliState.storedFlag(root, "done")) {
      // Server rendered it locked; do NOT arm Check. Typeset THEN return --
      // .el--filltable is excluded from math.js's global renderInlineText
      // list, so this file's own call is the ONLY thing that typesets its
      // static cells' math (mirrors switchgrid.js's boot short-circuit).
      if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
      return;
    }
    var btn = root.querySelector(".filltable__confirm");
    if (btn) btn.addEventListener("click", function () { submit(root); });
    // Enter in any cell submits, matching the inline fill-blank (whose <form>
    // gives Enter-submit for free); the table has no <form>, so bind it here.
    inputs(root).forEach(function (inp) {
      inp.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); submit(root); }
      });
    });
    // KaTeX auto-render (mirror switchgrid.js's typeset call exactly)
    if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
  }

  function initFillTables(root) {
    (root || document).querySelectorAll(".filltable").forEach(initOne);
  }

  window.libliInitFillTables = initFillTables;
  initFillTables(document);
})();
