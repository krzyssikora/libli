(function () {
  "use strict";

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function initOne(root) {
    if (root.dataset.guessnumberReady === "1") return;
    root.dataset.guessnumberReady = "1";

    var input = root.querySelector("[data-guess-input]");
    var check = root.querySelector("[data-guess-check]");
    var hint = root.querySelector("[data-guess-hint]");
    var success = root.querySelector("[data-guess-success]");
    var pk = root.getAttribute("data-element-pk");
    var url = root.getAttribute("data-check-url");
    if (pk === "0" || !url) return; // unsaved editor preview: no-op

    if (window.libliState.storedFlag(root, "done")) {
      // Server already rendered the locked/correct appearance (readonly
      // value, is-correct, success shown, Check omitted). No typeset call is
      // needed here -- unlike .switchgrid/.filltable/.switchgate, .guessnumber
      // IS in math.js's global renderInlineText list (math.js:31).
      return;
    }

    if (check) check.hidden = false; // arm Check now that JS is live

    var inFlight = false;
    var done = false;

    input.addEventListener("input", function () {
      // A fresh attempt starts clean (switchgate's hideFeedback rule).
      if (done) return;
      hint.hidden = true;
      input.classList.remove("is-wrong");
    });

    // No <form>, so no native submit to hook — deliberately: implicit
    // submission can't be suppressed without JS, and a stray Enter reload
    // would wipe reveal.js's in-memory cascade state.
    if (check) check.addEventListener("click", submit);
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") submit();
    });

    function submit() {
      if (inFlight || done) return; // in-flight + post-lock guards
      var value = (input.value || "").trim();
      if (!value) return;
      inFlight = true;
      fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
        body: "guess=" + encodeURIComponent(value),
      })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.correct) {
            done = true;
            hint.hidden = true;
            success.hidden = false;
            input.classList.remove("is-wrong");
            input.classList.add("is-correct");
            input.readOnly = true;
            if (check) check.remove(); // Check is spent (as fillgate/switchgate do)
            root.classList.add("guessnumber--done");
            window.libliState.saveFlag(root, { done: true });
          } else {
            input.classList.add("is-wrong");
            if (d.direction === "high" || d.direction === "low") {
              hint.textContent = root.getAttribute("data-msg-" + d.direction) || "";
              hint.hidden = false;
            } else {
              hint.hidden = true; // unparseable: red, no direction
            }
          }
        })
        .catch(function () { /* leave editable; never lock, never falsely pass */ })
        .then(function () { inFlight = false; });
    }
  }

  function init(scope) {
    (scope || document).querySelectorAll("[data-guessnumber]").forEach(initOne);
  }
  window.libliInitGuessNumbers = init;
  init(document);
})();
