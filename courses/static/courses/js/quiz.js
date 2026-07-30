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
      // The ephemeral (previewer) grading path is STATELESS, so the client owns the
      // attempt counter -- mirrors editor.js's authoring "try it" preview. No server
      // template emits data-attempts-made; it is created here on the first response.
      // The enrolled path ignores `attempt` entirely (its count comes from the
      // persisted QuestionResponse), so this is inert for students.
      const qEl = form.closest("[data-question]");
      const made = qEl
        ? parseInt(qEl.getAttribute("data-attempts-made") || "0", 10)
        : 0;
      const body = new FormData(form);
      body.append("attempt", String(made + 1));
      const res = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
        body: body,
      });
      if (res.status === 409) {
        window.location.reload();
        return;
      }
      const box = form.querySelector("[data-question-feedback]");
      box.innerHTML = await res.text();
      // An empty-answer validation doesn't consume an attempt; everything else does.
      if (qEl && !box.querySelector(".is-validation")) {
        qEl.setAttribute("data-attempts-made", String(made + 1));
      }
      // Disable inputs on ANY terminal state (correct, exhausted-incorrect, or
      // [N]/[R] recorded) — the server emits [data-quiz-locked] iff response.locked.
      // The selector covers three shapes: control-level (input/button), the
      // fieldset the 2D/grid types wrap their controls in, and the extended-response
      // <textarea>, which has NO wrapping fieldset and was previously left editable
      // beside "Submitted for review" until the next page load — on the ENROLLED
      // path too. `select` is defensive (those already sit inside the fieldset).
      if (box.querySelector("[data-quiz-locked]")) {
        form
          .querySelectorAll("input, button, select, textarea, fieldset")
          .forEach((n) => (n.disabled = true));
      }
      typeset(box);
    });
  });

  const finish = document.querySelector("[data-quiz-finish]");
  if (finish) {
    finish.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!window.confirm(finish.dataset.confirm)) return;
      // Record any answer the student typed but never "Checked": submit every
      // still-open question (its Check button not disabled) to its own endpoint
      // first, then finalize. quiz_answer no-ops on an empty or already-locked
      // answer, so flushing every open question is safe and idempotent.
      const open = Array.prototype.filter.call(
        document.querySelectorAll("form.question__form"),
        (f) => f.querySelector('button[type="submit"]:not([disabled])'),
      );
      await Promise.all(
        open.map((f) =>
          fetch(f.action, {
            method: "POST",
            headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
            body: new FormData(f),
          }).catch(() => {}),
        ),
      );
      finish.submit(); // programmatic submit does not re-fire this handler
    });
  }
})();
