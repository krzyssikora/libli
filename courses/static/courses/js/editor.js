(function () {
  "use strict";
  var root = document.querySelector(".editor");
  if (!root) return;
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  function applyFragments(html) {
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    ["editor", "preview"].forEach(function (scope) {
      var incoming = tmp.querySelector('[data-scope="' + scope + '"]');
      var existing = root.querySelector('[data-scope="' + scope + '"]');
      if (incoming && existing) existing.replaceWith(incoming);
    });
    var preview = root.querySelector('[data-scope="preview"]');
    if (preview && window.libliRenderMath) window.libliRenderMath(preview);
    // A swapped-in editor fragment may contain a math editor whose inline live preview
    // must render immediately (e.g. opening an existing math element for edit), not only
    // on the next keystroke. text_toolbar.js exposes window.libliInitMathLive(root).
    var editorPane = root.querySelector('[data-scope="editor"]');
    if (editorPane && window.libliInitMathLive) window.libliInitMathLive(editorPane);
    // Likewise, a swapped-in text element needs its RTE surface mounted now, not on
    // first focus. text_toolbar.js exposes window.libliInitRte(root).
    if (editorPane && window.libliInitRte) window.libliInitRte(editorPane);
  }

  function post(form, submitter) {
    var body = new FormData(form);
    // Append the clicked submitter's name/value (e.g. direction=up) — passed in
    // explicitly from the submit event, NOT the deprecated global `event`
    // (mirrors builder.js's e.submitter usage; window.event is unset off-Chromium).
    if (submitter && submitter.name) body.append(submitter.name, submitter.value);
    return fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
      body: body,
    }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); });
  }

  // Intercept editor forms (save/move/delete) -> swap both fragments.
  root.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-op]");
    if (!form) return;
    e.preventDefault();
    post(form, e.submitter).then(function (res) {
      if (res.status === 200 || res.status === 409) {
        applyFragments(res.text);
        if (res.status === 409) flash("This changed elsewhere — refreshed to the latest.");
      } else if (res.status === 422) {
        applyFragments(res.text);  // editor fragment carries the form + field errors
      }
    });
  });

  // "+ Type" add buttons -> POST add (render-only) and swap in the pending form.
  root.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add-type]");
    if (add) {
      var pane = root.querySelector('[data-scope="editor"]');
      var fd = new FormData();
      fd.append("type", add.getAttribute("data-add-type"));
      fd.append("unit", pane.getAttribute("data-unit"));
      fetch(pane.getAttribute("data-add-url"), {
        method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd,
      }).then(function (r) { return r.text(); }).then(applyFragments);
      return;
    }
    var cancel = e.target.closest("[data-cancel-edit]");
    if (cancel) { var host = root.querySelector(".editor-form-host"); if (host) host.innerHTML = ""; return; }
    // Selecting an existing row -> GET its edit form (manage_element_form, built in
    // Task 6) via the button's data-form-url, and swap the editor fragment.
    var sel = e.target.closest(".el-select");
    if (sel) {
      fetch(sel.getAttribute("data-form-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); }).then(applyFragments);
    }
  });

  function flash(msg) {
    var bar = document.createElement("div"); bar.className = "op-error"; bar.textContent = msg;
    root.prepend(bar); setTimeout(function () { bar.remove(); }, 6000);
  }
})();
