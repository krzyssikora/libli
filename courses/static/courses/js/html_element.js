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

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme"); // live resolved value
  }
  function postTheme(frame) {
    var t = currentTheme();
    if (t !== "light" && t !== "dark") return;
    try {
      frame.contentWindow.postMessage({ type: "libli:htmlel:theme", theme: t }, "*");
    } catch (err) { /* frame not ready; its load handler retries */ }
  }

  // Request a height from each HTML-element iframe present at load. This closes
  // the load-order race: a fast iframe can post its one-shot height before this
  // (bottom-of-body, deferred) script registers the listener above, so that post
  // is dropped. Asking explicitly — now for already-loaded frames, and again on
  // each frame's load for lazy/late ones — guarantees delivery. Iframes added
  // later (editor preview swaps) are covered by their own load-time post, which
  // the now-registered listener catches.
  function pingFrame(frame) {
    function ask() {
      try {
        frame.contentWindow.postMessage({ type: "libli:htmlel:req" }, "*");
      } catch (err) { /* frame not ready yet — its load handler will retry */ }
      postTheme(frame); // send current theme on the same schedule as height
    }
    ask();
    frame.addEventListener("load", ask);
  }
  function requestHeights() {
    var frames = document.querySelectorAll(".html-el iframe");
    for (var i = 0; i < frames.length; i++) pingFrame(frames[i]);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", requestHeights);
  } else {
    requestHeights();
  }

  // Live theme flips: the app toggle (ui.js) stamps data-theme on <html>; mirror it
  // into every HTML-element sandbox. Decoupled through the DOM attribute — no ui.js change.
  new MutationObserver(function () {
    var frames = document.querySelectorAll(".html-el iframe");
    for (var i = 0; i < frames.length; i++) postTheme(frames[i]);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})();
