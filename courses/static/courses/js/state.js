(function () {
  "use strict";

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  window.libliState = {
    storedFlag: function (el, key) {           // strict shape, not truthiness
      try {
        var raw = el && el.dataset.state;
        if (!raw) return false;
        var blob = JSON.parse(raw);
        return !!(blob && blob[key] === true);
      } catch (e) {
        return false;
      }
    },
    saveFlag: function (container, stateObj) {  // fire-and-forget, keepalive, swallow errors
      var url = container.dataset.stateUrl;
      if (!url) return;                          // editor preview "" -> no-op
      var eid = parseInt(container.dataset.elementPk, 10);
      if (!eid) return;                          // pk 0 -> no join row
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ element: eid, state: stateObj }),
        keepalive: true,
      }).catch(function () {});
    },
  };
})();
