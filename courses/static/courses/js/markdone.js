(function () {
  "use strict";
  window.__markdoneBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function persisted(root) {
    // last-known state = checkboxes' checked at init time
    var s = {};
    root.querySelectorAll('input[type="checkbox"][name="item"]').forEach(function (cb) {
      s[cb.value] = cb.checked;
    });
    return s;
  }

  function initOne(root) {
    if (root.dataset.markdoneReady === "1") return;
    root.dataset.markdoneReady = "1";
    var url = root.getAttribute("data-markdone-url");
    var saveBtn = root.querySelector("[data-markdone-save]");
    if (!url) return;              // preview/empty-URL: leave Save button, no auto-save
    if (saveBtn) saveBtn.hidden = true;
    var elInput = root.querySelector('input[name="element"]');
    var last = persisted(root);

    root.querySelectorAll('input[type="checkbox"][name="item"]').forEach(function (cb) {
      cb.addEventListener("change", function () {
        var li = cb.closest(".markdone__item");
        if (li) li.classList.toggle("on", cb.checked);
        var items = [];
        root.querySelectorAll('input[type="checkbox"][name="item"]:checked')
          .forEach(function (c) { items.push(parseInt(c.value, 10)); });
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({ element: parseInt(elInput.value, 10), items: items }),
          keepalive: true,
        })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(function () { last[cb.value] = cb.checked; })
          .catch(function () {
            // save failed: revert the toggle + on-class to last-known-persisted
            cb.checked = last[cb.value];
            if (li) li.classList.toggle("on", cb.checked);
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
