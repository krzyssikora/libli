(function () {
  "use strict";

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
        if (data.all_correct === true && (data.cells || []).length > 0) lock(root);
      })
      .catch(function () { /* fail-open: leave widget interactive */ });
  }

  function initOne(root) {
    if (root.dataset.filltableReady === "1") return;
    root.dataset.filltableReady = "1";
    var btn = root.querySelector(".filltable__confirm");
    if (btn) btn.addEventListener("click", function () { submit(root); });
    // KaTeX auto-render (mirror switchgrid.js's typeset call exactly)
    if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
  }

  function initFillTables(root) {
    (root || document).querySelectorAll(".filltable").forEach(initOne);
  }

  window.libliInitFillTables = initFillTables;
  initFillTables(document);
})();
