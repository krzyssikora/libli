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
    saveFlag: function (container, stateObj) {  // keepalive, swallow errors; announces a stored save
      var url = container.dataset.stateUrl;
      if (!url) return;                          // editor preview "" -> no-op
      var eid = parseInt(container.dataset.elementPk, 10);
      if (!eid) return;                          // pk 0 -> no join row
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ element: eid, state: stateObj }),
        keepalive: true,
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          // The echo is what is STORED (REJECT echoes the stored blob too), so a
          // non-empty echo means there is now something "Start fresh" can clear.
          if (data && data.state && Object.keys(data.state).length) {
            document.dispatchEvent(new CustomEvent("libli:state-saved"));
          }
        })
        .catch(function () {});
    },
  };
})();
