// Quiz interactions: per-question submit (swap feedback) + Finish confirmation.
(function () {
  function csrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  // Inline-math delimiters, matching question.js / dnd.js so quiz stems typeset
  // identically to the lesson page.
  const DELIMS = [
    { left: "\\(", right: "\\)", display: false },
    { left: "\\[", right: "\\]", display: true },
  ];
  function typeset(root) {
    if (!window.renderMathInElement || !root) return;
    try {
      window.renderMathInElement(root, { delimiters: DELIMS, throwOnError: false });
    } catch (e) {
      /* leave raw LaTeX on error */
    }
  }

  // Initial pass over the fresh stems/choices. The quiz page loads quiz.js
  // instead of question.js (which owns the lesson-side pass), so without this
  // \(...\) math in a fresh quiz never renders. No-op when auto-render.min.js
  // wasn't loaded (a quiz with no math).
  document.querySelectorAll("[data-question]").forEach(typeset);

  document.querySelectorAll("form.question__form").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const res = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
        body: new FormData(form),
      });
      if (res.status === 409) {
        window.location.reload();
        return;
      }
      const box = form.querySelector("[data-question-feedback]");
      box.innerHTML = await res.text();
      // Disable inputs on ANY terminal state (correct, exhausted-incorrect, or
      // [N]/[R] recorded) — the server emits [data-quiz-locked] iff response.locked.
      if (box.querySelector("[data-quiz-locked]")) {
        form.querySelectorAll("input, button").forEach((n) => (n.disabled = true));
      }
      typeset(box);
    });
  });

  const finish = document.querySelector("[data-quiz-finish]");
  if (finish) {
    finish.addEventListener("submit", (e) => {
      if (!window.confirm(finish.dataset.confirm)) {
        e.preventDefault();
      }
    });
  }
})();
