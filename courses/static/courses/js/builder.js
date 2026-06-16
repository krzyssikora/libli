(function () {
  "use strict";
  var root = document.querySelector(".builder");
  var panel = root && root.querySelector("[data-panel]");
  if (!root || !panel) return;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  // Replace the tree element whose data-scope matches the returned fragment's root.
  function applyFragment(html) {
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    var incoming = tmp.firstElementChild;
    if (!incoming) return;
    var scope = incoming.getAttribute("data-scope");
    var existing = root.querySelector('[data-scope="' + scope + '"]');
    if (existing) {
      existing.replaceWith(incoming);
    }
    // No append fallback: the target [data-scope] element is always present after the
    // first render (the tree-pane root for "top", a nested <ol> otherwise). Appending
    // on a missed selector would DUPLICATE the tree, so a miss is intentionally a no-op.
  }

  function notice(msg) {
    var bar = document.createElement("div");
    bar.className = "op-error";
    bar.textContent = msg;
    panel.prepend(bar);
    setTimeout(function () { bar.remove(); }, 6000);
  }

  // The detail panel holds token-bearing forms (rename, unit-settings, the Move picker)
  // that the [data-scope] tree swap never refreshes — so after their own op those forms
  // keep a now-stale token and re-submitting them spuriously 409s ("can't move the lesson
  // back"). After a panel form's op, re-fetch the operated node's fresh detail panel
  // (fresh token); if the node is gone (e.g. it was reparented away and the row vanished
  // from the freshly-swapped tree) or unidentifiable, clear the panel to a neutral state.
  function refreshPanel(form) {
    var nodeInput = form.querySelector("input[name='node']");
    var btn = nodeInput && root.querySelector('[data-select="' + nodeInput.value + '"]');
    var url = btn && btn.getAttribute("data-panel-url");
    if (!url) { panel.innerHTML = ""; return; }
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.text(); })
      .then(function (html) { panel.innerHTML = html; })
      .catch(function () { panel.innerHTML = ""; });
  }

  // Intercept any builder form with data-op; POST via fetch and swap the response.
  root.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-op]");
    if (!form) return;
    e.preventDefault();
    // Forms inside the detail panel (rename/settings/Move picker) need a panel refresh
    // after their op; tree forms (reorder/add) self-refresh via the [data-scope] swap.
    var inPanel = panel.contains(form);
    var body = new FormData(form);
    // include the submitter's name/value (e.g. direction=up)
    if (e.submitter && e.submitter.name) body.append(e.submitter.name, e.submitter.value);
    // Enhancement: for the Move picker (reparent), read the selected option's data-updated
    // and append it as parent_token so the server can verify the destination's token.
    // The server treats parent_token as optional (existence-only when absent = no-JS path),
    // so skipping it here is safe — we just add it when available for the stricter JS path.
    if (form.getAttribute("data-op") === "reparent") {
      var sel = form.querySelector("select[name='new_parent']");
      if (sel) {
        var opt = sel.options[sel.selectedIndex];
        if (opt && opt.getAttribute("data-updated")) {
          body.append("parent_token", opt.getAttribute("data-updated"));
        }
      }
    }
    fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
      body: body,
    }).then(function (r) {
      return r.text().then(function (text) {
        if (r.status === 200 || r.status === 409) {
          applyFragment(text);
          if (r.status === 409) notice("This changed elsewhere — refreshed to the latest.");
          // The op bumped tokens (200) or the tree was reloaded to latest (409); either
          // way a panel form is now stale — re-fetch its node's fresh panel.
          if (inPanel) refreshPanel(form);
        } else if (r.status === 422) {
          var tmp = document.createElement("div");
          tmp.innerHTML = text.trim();
          notice(tmp.textContent.trim());
        }
      });
    }).catch(function () {
      notice("Network error — please try again.");
    });
  });

  // Node selection -> load the detail panel fragment.
  root.addEventListener("click", function (e) {
    var sel = e.target.closest("[data-select]");
    if (sel) {
      e.preventDefault();
      fetch(sel.getAttribute("data-panel-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { panel.innerHTML = html; })
        .catch(function () { panel.innerHTML = '<div class="op-error" role="alert">Network error — please reload.</div>'; });
      return;
    }
    // Move… links open their picker inline (fetch GET).
    var mv = e.target.closest("[data-move]");
    if (mv) {
      e.preventDefault();
      fetch(mv.getAttribute("href"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { panel.innerHTML = html; })
        .catch(function () { panel.innerHTML = '<div class="op-error" role="alert">Network error — please reload.</div>'; });
      return;
    }
  });

  // Reveal the unit_type select only when kind === 'unit' on add forms.
  root.addEventListener("change", function (e) {
    if (!e.target.matches("[data-kind-select]")) return;
    var form = e.target.closest("form");
    var ut = form.querySelector("[data-unit-type]");
    if (ut) ut.hidden = e.target.value !== "unit";
  });
})();
