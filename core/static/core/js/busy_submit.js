// Busy cue for slow form POSTs (course import, course deletion): without it a
// long request looks exactly like an idle page, and a second click submits twice.
//
// <form data-busy-submit data-busy-message="…"> … <p data-busy-note></p>
//
// On submit the form's submit button is disabled (so a second click or Enter
// cannot resubmit) and marked [data-busy] for the spinner, and the message is
// written into the form's [data-busy-note] live region. The button carries no
// `name`, so disabling it inside the handler drops nothing from the POST.
// Progressive: with JS off the form submits as before, just without the cue.
(function () {
  "use strict";

  document.querySelectorAll("form[data-busy-submit]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) return;
      var button = form.querySelector('button[type="submit"]');
      if (button) {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        button.setAttribute("data-busy", "");
      }
      var note = form.querySelector("[data-busy-note]");
      if (note) note.textContent = form.getAttribute("data-busy-message") || "";
    });
  });

  // A Back navigation restored from bfcache must not leave a dead, spinning button.
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-busy-submit]").forEach(function (form) {
      form.querySelectorAll("[data-busy]").forEach(function (button) {
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.removeAttribute("data-busy");
      });
      var note = form.querySelector("[data-busy-note]");
      if (note) note.textContent = "";
    });
  });
})();
