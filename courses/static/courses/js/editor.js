(function () {
  "use strict";
  var root = document.querySelector(".editor");
  if (!root) return;
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  // Re-run after every fragment swap: KaTeX preview render + MathLive/RTE surface mount
  // for any open editor form. (Media picker self-wires via delegated listeners on .editor
  // in media_picker.js, so it survives swaps without re-init here.)
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
    var editorPane = root.querySelector('[data-scope="editor"]');
    if (editorPane && window.libliInitMathLive) window.libliInitMathLive(editorPane);
    if (editorPane && window.libliInitRte) window.libliInitRte(editorPane);
    bindDnD();  // handlers re-bound after every swap (Task 8)
  }

  function post(form, submitter) {
    var body = new FormData(form);
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
      if (res.status === 200 || res.status === 409 || res.status === 422) {
        applyFragments(res.text);
        if (res.status === 409) flash("This changed elsewhere — refreshed to the latest.");
      }
    });
  });

  root.addEventListener("click", function (e) {
    var toggle = e.target.closest("[data-add-toggle]");
    if (toggle) { var menu = root.querySelector("[data-type-menu]"); if (menu) menu.hidden = !menu.hidden; return; }
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
    if (cancel) {
      var row = cancel.closest(".el-row");
      var slot = cancel.closest("[data-edit-slot]");
      if (slot) slot.innerHTML = "";
      if (row) {
        row.classList.remove("el-row--editing");
        if (!row.getAttribute("data-element")) row.remove();  // unsaved new row
      }
      return;
    }
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

  function bindDnD() { if (window.__libliEditorDnD) window.__libliEditorDnD(root); }
  bindDnD();
})();
