(function () {
  "use strict";
  var lesson = document.querySelector(".lesson[data-seen-url]");
  if (!lesson || !("IntersectionObserver" in window)) return;
  var url = lesson.getAttribute("data-seen-url");
  var seen = new Set();
  var timer = null;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }
  function payload() {
    return JSON.stringify(Array.from(seen));
  }
  // Always fetch+keepalive (NOT sendBeacon): the request needs the X-CSRFToken header,
  // which sendBeacon cannot send. keepalive lets the request outlive the page on unload.
  function flush() {
    if (!seen.size) return;
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: payload(),
      keepalive: true,
    });
  }
  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(flush, 500);
  }

  var obs = new IntersectionObserver(function (entries) {
    var added = false;
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        var id = parseInt(e.target.getAttribute("data-element-id"), 10);
        if (!seen.has(id)) { seen.add(id); added = true; }
        obs.unobserve(e.target);
      }
    });
    if (added) schedule();
  }, { threshold: 0, rootMargin: "0px 0px -10% 0px" });

  document.querySelectorAll("[data-element-id]").forEach(function (el) { obs.observe(el); });
  window.addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flush();
  });
})();
