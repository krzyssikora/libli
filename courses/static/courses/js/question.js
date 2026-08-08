(function () {
  "use strict";
  var Q_DELIMS = [
    { left: "\\(", right: "\\)", display: false },
    { left: "\\[", right: "\\]", display: true },
  ];
  function renderQ(root) {
    // Inline math for a question subtree (stem/choices) or a swapped feedback slot.
    // No-op if auto-render.min.js wasn't loaded (question without math).
    if (typeof renderMathInElement !== "function" || !root) return;
    try {
      renderMathInElement(root, { delimiters: Q_DELIMS, throwOnError: false });
    } catch (e) { /* leave raw LaTeX on error */ }
  }
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }
  // A fully-correct answer finishes the question: hide the Check button (no re-check
  // needed), and — for a form that opts in with data-lock-on-correct (fill-blank) —
  // lock its blanks read-only so the answered text can no longer be retyped, which
  // would otherwise let an implicit Enter submit overwrite a correct stored answer
  // with a wrong one. Mirrors the server's locked render (fillblank.render_inputs)
  // and fillgate.js's lock(), `size` included: the width-release CSS only honours
  // `size`, so without it a long answer stays clipped to the fixed 8ch box.
  function finishSolved(form) {
    var btn = form.querySelector("button[type='submit'], input[type='submit']");
    if (btn) btn.hidden = true;
    if (!form.hasAttribute("data-lock-on-correct")) return;
    Array.prototype.forEach.call(
      form.querySelectorAll('input[name="blank"]'),
      function (inp) {
        inp.readOnly = true;
        inp.classList.add("is-correct");
        inp.size = Math.max(inp.value.length, 2);
      }
    );
  }

  var questions = document.querySelectorAll("[data-question]");
  questions.forEach(renderQ);  // initial inline-math pass over stems/choices
  questions.forEach(function (q) {
    var form = q.querySelector("form");
    if (!form) return;  // a join-row-less render has no form (Task 2 guard)
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var slot = q.querySelector("[data-question-feedback]");
      fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
        body: new FormData(form),
      })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          if (form.hasAttribute("data-question-inline")) {
            // Choice: response is the full element; swap the LIVE form's body so the
            // bound submit listener survives, then re-query against the live form
            // (the pre-fetch `slot` is detached by this assignment). If the response
            // has NO <form> (defensive — e.g. a form-less feedback fragment), fall
            // through to the bottom-slot swap rather than dropping the update.
            var doc = new DOMParser().parseFromString(html, "text/html");
            var newForm = doc.querySelector("form");
            if (newForm) {
              form.innerHTML = newForm.innerHTML;
              renderQ(form);
              if (form.querySelector(".question__verdict.is-correct")) finishSolved(form);
              return;
            }
          }
          if (!slot) return;
          slot.innerHTML = html;
          renderQ(slot);  // typeset revealed-choice / explanation math
          // A fully-correct answer needs no re-check: hide the Check button (and
          // lock the blanks on an opted-in form).
          if (slot.querySelector(".question__verdict.is-correct")) finishSolved(form);
        })
        .catch(function () { /* leave the form intact on network error */ });
    });
  });

  // Boot pass: a restored (or server-rendered) correct answer already shows its
  // verdict; hide its Check/Submit button so it matches the post-fetch behavior.
  // (The server already rendered an opted-in form's blanks locked, so finishSolved
  // is a no-op there — it is the safety net for any other path that reaches a
  // correct verdict without the locked render.) Scoped to questions that HAVE a
  // form (results/review pages render form-less [data-question] blocks and must be
  // untouched).
  questions.forEach(function (q) {
    var form = q.querySelector("form");
    if (!form) return;
    if (form.querySelector(".question__verdict.is-correct")) finishSolved(form);
  });
})();
