(function () {
  "use strict";

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function options(cycler) {
    return Array.prototype.slice.call(cycler.querySelectorAll(".switchgrid__option"));
  }

  function currentIndex(cycler) {
    var opts = options(cycler);
    for (var i = 0; i < opts.length; i++) {
      if (!opts[i].hidden) return i;
    }
    return 0;
  }

  function show(cycler, idx) {
    var opts = options(cycler);
    for (var i = 0; i < opts.length; i++) {
      opts[i].hidden = i !== idx;
      opts[i].classList.toggle("switchgrid__option--current", i === idx);
    }
  }

  function advance(cycler) {
    if (cycler.classList.contains("switchgrid--locked")) return;
    var opts = options(cycler);
    if (!opts.length) return;
    show(cycler, (currentIndex(cycler) + 1) % opts.length);
    cycler.classList.remove("switchgrid--correct", "switchgrid--incorrect");
  }

  function collect(root) {
    var lines = Array.prototype.slice.call(root.querySelectorAll("[data-line]"));
    return lines.map(function (line) {
      var cyclers = Array.prototype.slice.call(line.querySelectorAll("[data-switchgrid-cycler]"));
      return cyclers.map(currentIndex);
    });
  }

  function paint(root, cells) {
    var lines = Array.prototype.slice.call(root.querySelectorAll("[data-line]"));
    lines.forEach(function (line, i) {
      var cyclers = Array.prototype.slice.call(line.querySelectorAll("[data-switchgrid-cycler]"));
      var row = (cells && cells[i]) || [];
      cyclers.forEach(function (cyc, j) {
        cyc.classList.remove("switchgrid--correct", "switchgrid--incorrect");
        if (row[j] === true) cyc.classList.add("switchgrid--correct");
        else if (row[j] === false) cyc.classList.add("switchgrid--incorrect");
      });
    });
  }

  function lock(root) {
    root.querySelectorAll("[data-switchgrid-cycler]").forEach(function (c) {
      c.classList.add("switchgrid--locked");
    });
    var btn = root.querySelector(".switchgrid__confirm");
    if (btn) btn.hidden = true;
  }

  function summarize(root, ok) {
    var s = root.querySelector("[data-switchgrid-summary]");
    if (!s) return;
    s.hidden = false;
    s.classList.toggle("switchgrid--success", ok);
    s.classList.toggle("switchgrid--retry", !ok);
    s.textContent = ok ? s.dataset.successMsg || "Great!" : s.dataset.retryMsg || "Try again";
  }

  function submit(root) {
    var pk = root.dataset.elementPk;
    var url = root.dataset.checkUrl;
    if (!pk || pk === "0" || !url) return; // unsaved preview
    var body = new FormData();
    body.append("indices", JSON.stringify(collect(root)));
    fetch(url, { method: "POST", headers: { "X-CSRFToken": csrf() }, body: body, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        paint(root, data.cells || []);
        summarize(root, !!data.correct);
        if (data.correct) {
          lock(root);
          window.libliState.saveFlag(root, { done: true });
        }
      })
      .catch(function () { /* fail-open: leave widget interactive */ });
  }

  function initOne(root) {
    if (root.dataset.switchgridReady === "1") return;
    root.dataset.switchgridReady = "1";
    if (window.libliState.storedFlag(root, "done")) {
      // Server rendered it locked; do NOT arm cyclers/Confirm. Typeset THEN
      // return -- .switchgrid is excluded from math.js's global
      // renderInlineText list, so this file's own call is the ONLY thing
      // that typesets its math (mirrors switchgate.js's boot short-circuit).
      if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
      return;
    }
    root.querySelectorAll("[data-switchgrid-cycler]").forEach(function (cyc) {
      cyc.addEventListener("click", function () { advance(cyc); });
    });
    var btn = root.querySelector(".switchgrid__confirm");
    if (btn) btn.addEventListener("click", function () { submit(root); });
    // KaTeX auto-render (mirror switchgate.js's typeset call exactly)
    if (window.renderMathInElement) { try { window.renderMathInElement(root); } catch (e) {} }
  }

  function initSwitchGrids(root) {
    (root || document).querySelectorAll("[data-switchgrid]").forEach(initOne);
  }

  window.libliInitSwitchGrids = initSwitchGrids;
  initSwitchGrids(document);
})();
