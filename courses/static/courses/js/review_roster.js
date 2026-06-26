(function () {
  "use strict";
  var KEY = "libli_review_roster_collapsed";
  var root = document.documentElement;

  // Collapse toggle — persist to localStorage; pre-paint script restores it.
  var toggle = document.querySelector("[data-roster-toggle]");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var collapsed = root.classList.toggle("review-roster-collapsed");
      try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
    });
  }

  // Force-submit-all confirm (same pattern as quiz-finish): block submit unless
  // the user confirms. data-confirm carries the localized prompt.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        e.preventDefault();
      }
    });
  });
})();
