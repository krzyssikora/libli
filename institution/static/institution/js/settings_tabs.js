// Settings tab row: when the row is scrolled sideways (a phone), bring the active
// tab into view on load. Loaded with `defer` by institution/manage/settings.html.
// scrollLeft only — scrollIntoView() would also scroll the PAGE vertically.
(function () {
  "use strict";

  // Keep the tab clear of the 1.5rem edge shade (.scroll-x::before/::after in
  // app.css), which would otherwise sit over its label.
  var EDGE = 24;

  function reveal() {
    var nav = document.querySelector(".settings__tabs");
    if (!nav || nav.scrollWidth <= nav.clientWidth) return;
    var tab = nav.querySelector(".settings__tab.is-on");
    if (!tab) return;
    var box = nav.getBoundingClientRect();
    var rect = tab.getBoundingClientRect();
    if (rect.right > box.right - EDGE) {
      nav.scrollLeft += rect.right - box.right + EDGE;
    } else if (rect.left < box.left + EDGE) {
      nav.scrollLeft -= box.left + EDGE - rect.left;
    }
  }

  reveal();
  // Web fonts can finish after the deferred run and widen the labels.
  window.addEventListener("load", reveal);
})();
