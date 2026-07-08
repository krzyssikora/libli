(function () {
  "use strict";
  // Shared by progress.js and slideshow.js: flips the title's completion pill to
  // "✓ Completed" the moment the server reports the unit as done, without a reload.
  window.unitMarkDone = function () {
    var c = document.querySelector("[data-unit-done]");
    if (!c || c.classList.contains("is-complete")) return;
    c.classList.add("is-complete");
    var label = c.getAttribute("data-done-label") || "Completed";
    c.innerHTML =
      '<span class="unit-done__pill"><span class="unit-done__check" aria-hidden="true">' +
      "✓</span> " +
      label +
      "</span>";
  };
})();
