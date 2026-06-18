// courses/static/courses/js/html_element.js
(function () {
  "use strict";
  var MIN = 40, MAX = 20000;
  function clamp(h) {
    h = parseInt(h, 10);
    if (isNaN(h)) return null;
    return Math.max(MIN, Math.min(MAX, h));
  }
  window.addEventListener("message", function (e) {
    var d = e.data;
    if (!d || d.type !== "libli:htmlel:height") return;  // only our contract
    var h = clamp(d.h);
    if (h === null) return;
    // Resolve sender among HTML-element iframes ONLY (never other iframes,
    // e.g. GeoGebra). Enumerated at message time → survives preview swaps.
    var frames = document.querySelectorAll(".html-el iframe");
    for (var i = 0; i < frames.length; i++) {
      if (frames[i].contentWindow === e.source) {
        frames[i].style.height = h + "px";
        return;
      }
    }
  });
})();
