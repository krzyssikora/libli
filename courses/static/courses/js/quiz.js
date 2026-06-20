// Quiz interactions: per-question submit (swap feedback) + Finish confirmation.
(function () {
  function csrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

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
      if (window.renderMathInElement) {
        window.renderMathInElement(box);
      }
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
