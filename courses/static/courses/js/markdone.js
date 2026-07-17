(function () {
  "use strict";
  window.__markdoneBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function boxes(root) {
    return root.querySelectorAll('input[type="checkbox"][name="item"]');
  }

  // Last-known-persisted as a {checkboxValue: bool} map over EVERY box -- deliberately
  // the DOM's shape, not the server's ({"items": [...]}), because paint() consumes it.
  // Adoption therefore TRANSLATES the echoed array into this shape; it is not an
  // assignment.
  function persisted(root) {
    var s = {};
    boxes(root).forEach(function (cb) { s[cb.value] = cb.checked; });
    return s;
  }

  function paint(root, map) {
    boxes(root).forEach(function (cb) {
      cb.checked = !!map[cb.value];
      var li = cb.closest(".markdone__item");
      if (li) li.classList.toggle("on", cb.checked);
    });
  }

  function initOne(root) {
    if (root.dataset.markdoneReady === "1") return;
    root.dataset.markdoneReady = "1";
    var url = root.getAttribute("data-markdone-url");
    var saveBtn = root.querySelector("[data-markdone-save]");
    // The Save button is the no-JS fallback only; whenever JS runs we hide it — incl.
    // the editor preview (empty url), where it can't submit anyway.
    if (saveBtn) saveBtn.hidden = true;
    if (!url) return;              // preview/empty-URL: nothing to auto-save
    var elInput = root.querySelector('input[name="element"]');
    var last = persisted(root);
    // Sequence guard. Adoption re-renders the widget from the echo, so without this a
    // burst (tick A -> tick B) lets A's echo {"items":[A]} arrive last and UNTICK B --
    // a regression this rewrite would otherwise introduce (the old client ignored the
    // response body entirely). Only the newest request may paint.
    var seq = 0;

    boxes(root).forEach(function (cb) {
      cb.addEventListener("change", function () {
        var li = cb.closest(".markdone__item");
        if (li) li.classList.toggle("on", cb.checked);
        var items = [];
        root.querySelectorAll('input[type="checkbox"][name="item"]:checked')
          .forEach(function (c) { items.push(parseInt(c.value, 10)); });
        var mine = ++seq;
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({
            element: parseInt(elInput.value, 10),
            state: { items: items },
          }),
          keepalive: true,
        })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(function (data) {
            if (mine !== seq) return;   // stale echo: a newer save is in flight
            // ADOPT the echo -- do not compare-and-revert. The server normalizes
            // (an empty selection DROPS the key and echoes {}), so a comparing
            // client would re-tick the box the student just unticked.
            var blob = (data && data.state) || {};
            var arr = Array.isArray(blob.items) ? blob.items : [];
            var next = {};
            arr.forEach(function (pk) { next[String(pk)] = true; });
            last = next;
            paint(root, last);
          })
          .catch(function () {
            if (mine !== seq) return;
            // Mark-done is REVERSIBLE, so a failed save reverts the DOM to
            // last-known-persisted. (Monotone types must NOT: slice 2.)
            paint(root, last);
            if (saveBtn) saveBtn.hidden = false;
          });
      });
    });
  }

  function initMarkDone(root) {
    root = root || document;
    if (root.matches && root.matches("[data-markdone]")) initOne(root);
    (root.querySelectorAll ? root.querySelectorAll("[data-markdone]") : []).forEach(initOne);
  }

  window.libliInitMarkDone = initMarkDone;
  initMarkDone(document);
})();
