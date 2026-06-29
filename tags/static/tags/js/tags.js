(function () {
  "use strict";
  // Null-guarded: tags.js loads on the outline page too, which intentionally omits
  // #tags-i18n (the filter needs no labels). Never dereference it unconditionally.
  var i18nEl = document.getElementById("tags-i18n");
  var MSG = i18nEl ? i18nEl.dataset : {};

  var bar = document.querySelector("[data-tags-filter]");
  if (bar) setupFilter(bar);
  wirePanels();
  wireDeleteConfirm();

  function setupFilter(bar) {
    var chips = Array.prototype.slice.call(bar.querySelectorAll("a.tag-chip"));
    var active = new Set(
      chips.filter(function (c) { return c.classList.contains("is-active"); })
           .map(function (c) { return c.dataset.tagId; })
    );
    chips.forEach(function (chip) {
      chip.addEventListener("click", function (e) {
        e.preventDefault();
        var id = chip.dataset.tagId;
        if (active.has(id)) active.delete(id); else active.add(id);
        applyFilter(active);
        syncChips(chips, active);
        var ids = Array.from(active);
        var qs = ids.map(function (i) { return "tags=" + i; }).join("&");
        history.pushState(null, "", qs ? "?" + qs : location.pathname);
      });
    });
    applyFilter(active);
  }

  function applyFilter(active) {
    var units = document.querySelectorAll("li[data-unit]");
    units.forEach(function (li) {
      var tags = (li.dataset.tags || "").trim().split(/\s+/).filter(Boolean);
      var match = active.size === 0 || tags.some(function (t) { return active.has(t); });
      li.hidden = !match;
    });
    // bubble: container visible iff it has a visible descendant unit
    var containers = Array.prototype.slice.call(
      document.querySelectorAll("li.outline-node")
    ).reverse();
    containers.forEach(function (li) {
      if (li.hasAttribute("data-unit")) return;
      if (active.size === 0) { li.hidden = false; return; }
      li.hidden = !li.querySelector("li[data-unit]:not([hidden])");
    });
  }

  function syncChips(chips, active) {
    var ids = Array.from(active);
    chips.forEach(function (chip) {
      var id = chip.dataset.tagId;
      var on = active.has(id);
      chip.classList.toggle("is-active", on);
      if (on) chip.setAttribute("aria-current", "true");
      else chip.removeAttribute("aria-current");
      var rest = on ? ids.filter(function (i) { return i !== id; }) : ids.concat(id);
      var qs = rest.map(function (i) { return "tags=" + i; }).join("&");
      chip.setAttribute("href", qs ? "?" + qs : location.pathname);
    });
  }

  // Unit-panel fragment add/remove: intercept the panel forms, POST with the
  // fetch header, swap the returned .unit-tags panel HTML in place.
  function wirePanels() {
    document.addEventListener("submit", function (e) {
      var form = e.target;
      var panel = form.closest(".unit-tags");
      if (!panel) return;  // not a tag-panel form
      if (!form.matches(".unit-tags__add, .unit-tags__chips form")) return;
      e.preventDefault();
      var data = new FormData(form);
      fetch(form.action, {
        method: "POST",
        body: data,
        headers: { "X-Requested-With": "fetch" },
      })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          var tmp = document.createElement("div");
          tmp.innerHTML = html;
          var fresh = tmp.querySelector(".unit-tags");
          if (fresh) panel.replaceWith(fresh);  // wirePanels uses delegation, so the
                                                 // replacement's forms stay wired
        });
    });
  }

  // Inline delete-confirm on the My-tags page: intercept each trash link (a GET link to the
  // no-JS confirm page) and swap in a small Yes/No before POSTing to the same URL.
  function wireDeleteConfirm() {
    var links = document.querySelectorAll(".tag-section__manage a[href*='/delete/']");
    Array.prototype.forEach.call(links, function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        var span = document.createElement("span");
        span.className = "tag-delete-confirm";
        var form = document.createElement("form");
        form.method = "post";
        form.action = link.getAttribute("href");
        form.style.display = "inline";
        form.innerHTML =
          '<input type="hidden" name="csrfmiddlewaretoken" value="' + csrf() + '">' +
          "<span>" + (MSG.msgDeleteQ || "Delete?") + "</span> " +
          '<button type="submit">' + (MSG.msgYes || "Yes") + "</button>";
        var no = document.createElement("button");
        no.type = "button";
        no.textContent = MSG.msgNo || "No";
        no.addEventListener("click", function () { span.replaceWith(link); });
        form.appendChild(no);
        span.appendChild(form);
        link.replaceWith(span);
      });
    });
  }

  function csrf() {
    var el = document.querySelector("input[name=csrfmiddlewaretoken]");
    return el ? el.value : "";  // every My-tags page has the recolor form's token
  }
})();
