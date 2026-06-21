(function () {
  "use strict";

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  function flash(host, msg) {
    var bar = document.createElement("div"); bar.className = "op-error"; bar.textContent = msg;
    host.prepend(bar); setTimeout(function () { bar.remove(); }, 6000);
  }

  // ---------------------------------------------------------------------------
  // Editor page: the media picker modal.
  // ---------------------------------------------------------------------------
  var editor = document.querySelector(".editor");
  if (editor) wireEditorPicker(editor);

  function wireEditorPicker(root) {
    var overlay = null;          // current modal overlay element
    var targetSelect = null;     // the <select name="media"> we are picking for
    var targetPreview = null;    // its sibling [data-media-preview]

    function closeModal() {
      if (overlay) { overlay.remove(); overlay = null; }
      targetSelect = null; targetPreview = null;
    }

    // The <select name="media"> is the SINGLE source of the media value. Adding an
    // <option> for the asset if it is not already present, then set select.value.
    // url is optional — stored as data-media-url on [data-media-preview] so other
    // modules (e.g. zone-editor.js) can read the chosen image URL without an extra fetch.
    function selectAsset(id, name, url) {
      if (!targetSelect) return;
      var has = false, opts = targetSelect.options, i;
      for (i = 0; i < opts.length; i++) { if (opts[i].value === String(id)) { has = true; break; } }
      if (!has) {
        var opt = document.createElement("option");
        opt.value = String(id); opt.textContent = name || ("#" + id);
        targetSelect.appendChild(opt);
      }
      targetSelect.value = String(id);
      if (targetPreview) {
        targetPreview.textContent = name || ("#" + id);
        if (url) targetPreview.dataset.mediaUrl = url;
      }
      closeModal();
      if (targetPreview) {
        targetSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function openModal(html) {
      closeModal();
      overlay = document.createElement("div");
      overlay.className = "picker-overlay";
      var card = document.createElement("div");
      card.className = "picker-card";
      card.innerHTML = html.trim();
      overlay.appendChild(card);
      overlay.addEventListener("click", function (e) { if (e.target === overlay) closeModal(); });
      document.body.appendChild(overlay);
    }

    // Open the picker for a [data-pick-media] button.
    root.addEventListener("click", function (e) {
      var pick = e.target.closest("[data-pick-media]");
      if (!pick) return;
      e.preventDefault();
      var field = pick.closest(".el-editor");
      targetSelect = field && field.querySelector("select[name='media']");
      targetPreview = field && field.querySelector("[data-media-preview]");
      var kind = pick.getAttribute("data-pick-media");
      var url = root.dataset.pickerUrl + "?kind=" + encodeURIComponent(kind);
      fetch(url, { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(openModal)
        .catch(function () { /* leave field untouched */ });
    });

    // Interactions inside the open modal: tabs, asset pick, upload.
    document.addEventListener("click", function (e) {
      if (!overlay) return;
      var tab = e.target.closest(".picker__tab");
      if (tab && overlay.contains(tab)) {
        var name = tab.getAttribute("data-tab");
        overlay.querySelectorAll(".picker__tab").forEach(function (t) {
          t.classList.toggle("is-on", t === tab);
        });
        overlay.querySelectorAll(".picker__panel").forEach(function (p) {
          p.hidden = p.getAttribute("data-panel") !== name;
        });
        return;
      }
      var assetBtn = e.target.closest(".asset-pick");
      if (assetBtn && overlay.contains(assetBtn)) {
        e.preventDefault();
        selectAsset(assetBtn.getAttribute("data-asset-id"), assetBtn.getAttribute("data-name"), assetBtn.getAttribute("data-url"));
      }
    });

    // Upload tab: a file chosen via [data-kind] file input -> POST -> auto-select.
    document.addEventListener("change", function (e) {
      if (!overlay) return;
      var file = e.target.closest(".picker__file");
      if (!file || !overlay.contains(file) || !file.files || !file.files.length) return;
      var picker = overlay.querySelector(".picker");
      var uploadUrl = picker.getAttribute("data-upload-url");
      var fd = new FormData();
      fd.append("file", file.files[0]);
      fd.append("kind", file.getAttribute("data-kind"));
      fetch(uploadUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: fd,
      }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
        .then(function (res) {
          if (res.status !== 200 && res.status !== 201) {
            var card = overlay && overlay.querySelector(".picker-card");
            if (card) flash(card, "Upload failed.");
            return;
          }
          var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
          var cell = tmp.querySelector("[data-asset-id]");
          if (cell) selectAsset(cell.getAttribute("data-asset-id"), cell.getAttribute("data-name"), cell.getAttribute("data-url"));
        });
    });

    // Debounced picker search: POST nothing, GET ?grid=1&kind=&q= → swap grid.
    var psTimer, psSeq = 0;
    document.addEventListener("input", function (e) {
      if (!overlay) return;
      var box = e.target.closest("[data-picker-search]");
      if (!box || !overlay.contains(box)) return;
      var picker = overlay.querySelector(".picker");
      var kind = picker.getAttribute("data-kind");
      var base = picker.getAttribute("data-search-url");
      clearTimeout(psTimer);
      psTimer = setTimeout(function () {
        var mine = ++psSeq;
        var url = base + "?grid=1&kind=" + encodeURIComponent(kind) + "&q=" + encodeURIComponent(box.value);
        fetch(url, { headers: { "X-Requested-With": "fetch" } })
          .then(function (r) { return r.text(); })
          .then(function (html) {
            if (mine !== psSeq) return;
            var host = overlay.querySelector("[data-picker-grid]");
            if (host) host.innerHTML = html.trim();
          });
      }, 250);
    });
  }

  // ---------------------------------------------------------------------------
  // Manager page: upload (form + drag/drop) and delete.
  // ---------------------------------------------------------------------------
  var manager = document.querySelector(".media-manager");
  if (manager) wireManager(manager);

  function msg(host, key, fallback) { return (host && host.getAttribute("data-msg-" + key)) || fallback; }

  function wireManager(root) {
    var grid = root.querySelector(".asset-grid");
    var uploadUrl = root.dataset.uploadUrl;

    function uploadFile(file, kind) {
      var fd = new FormData();
      fd.append("file", file);
      fd.append("kind", kind || guessKind(file));
      return fetch(uploadUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: fd,
      }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); });
    }

    function guessKind(file) {
      return file && file.type && file.type.indexOf("video") === 0 ? "video" : "image";
    }

    function insertCell(html) {
      if (!grid) return;
      var tmp = document.createElement("div"); tmp.innerHTML = html.trim();
      var cell = tmp.querySelector(".asset-cell");
      if (!cell) return;
      var empty = grid.querySelector(".empty-state");
      if (empty) empty.remove();
      grid.prepend(cell);
    }

    // Progressive enhancement: intercept the upload form so the grid updates in place.
    var form = root.querySelector(".media-upload");
    if (form) {
      form.addEventListener("submit", function (e) {
        var input = form.querySelector("input[type='file']");
        if (!input || !input.files || !input.files.length) return;  // let no-JS path run
        e.preventDefault();
        var kindSel = form.querySelector("select[name='kind']");
        uploadFile(input.files[0], kindSel ? kindSel.value : null).then(function (res) {
          if (res.status === 200 || res.status === 201) { insertCell(res.text); form.reset(); }
          else flash(root, "Upload failed.");
        });
      });
    }

    // Drag & drop onto the drop zone.
    var drop = root.querySelector(".media-drop");
    if (drop) {
      drop.hidden = false;
      ["dragenter", "dragover"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("is-over"); });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("is-over"); });
      });
      drop.addEventListener("drop", function (e) {
        var files = e.dataTransfer && e.dataTransfer.files;
        if (!files) return;
        Array.prototype.forEach.call(files, function (f) {
          uploadFile(f).then(function (res) {
            if (res.status === 200 || res.status === 201) insertCell(res.text);
            else flash(root, "Upload failed.");
          });
        });
      });
    }

    // Delete forms.
    root.addEventListener("submit", function (e) {
      var delForm = e.target.closest("form[data-op='asset-delete']");
      if (!delForm) return;
      e.preventDefault();
      var cell = delForm.closest(".asset-cell");
      fetch(delForm.action, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: new FormData(delForm),
      }).then(function (r) {
        if (r.status === 200) { if (cell) cell.remove(); }
        else if (r.status === 409) flash(root, msg(root, "conflict", "This changed elsewhere — reloaded to the latest."));
        else flash(root, "Could not delete.");
      });
    });

    // Inline rename: pencil swaps display name to an input; Enter saves, Esc cancels.
    var renameUrl = root.dataset.renameUrl;
    root.addEventListener("click", function (e) {
      var pen = e.target.closest("[data-rename-asset]");
      if (!pen) return;
      var cell = pen.closest(".asset-cell");
      var dname = cell.querySelector("[data-asset-dname]");
      if (!dname || cell.querySelector(".asset-rename-input")) return;
      var input = document.createElement("input");
      input.className = "asset-rename-input input"; input.value = dname.textContent.trim();
      dname.replaceWith(input); input.focus(); input.select();
      var done = false;
      function commit(save) {
        if (done) return;  // re-entrancy guard: Enter/Esc fires, then the focusout(blur) fires
        done = true;
        if (!save) { input.replaceWith(dname); return; }
        var fd = new FormData();
        fd.append("id", cell.getAttribute("data-asset-id"));
        fd.append("name", input.value);
        fetch(renameUrl, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd })
          .then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
          .then(function (res) {
            if (res.status !== 200) { input.replaceWith(dname); flash(root, "Rename failed."); return; }
            var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
            var fresh = tmp.querySelector(".asset-cell");
            if (fresh) cell.replaceWith(fresh);
          })
          .catch(function () {
            // Network failure: restore the name so the input doesn't wedge un-committable.
            if (input.parentNode) input.replaceWith(dname);
            flash(root, "Rename failed.");
          });
      }
      input.addEventListener("keydown", function (ev) {
        if (ev.key === "Enter") { ev.preventDefault(); commit(true); }
        if (ev.key === "Escape") { ev.preventDefault(); commit(false); }
      });
      input.addEventListener("blur", function () { commit(true); });
    });

    // Debounced server-side filter (kind + q), swaps the grid; drops stale responses.
    var filters = root.querySelector("[data-media-filters]");
    var listUrl = root.dataset.listUrl;
    if (filters) {
      var seq = 0, timer;
      function runFilter() {
        var kind = (filters.querySelector("[data-filter-kind]") || {}).value || "";
        var q = (filters.querySelector("[data-filter-q]") || {}).value || "";
        var mine = ++seq;
        var url = listUrl + "?kind=" + encodeURIComponent(kind) + "&q=" + encodeURIComponent(q);
        fetch(url, { headers: { "X-Requested-With": "fetch" } })
          .then(function (r) { return r.text(); })
          .then(function (html) {
            if (mine !== seq) return;  // superseded
            var oldGrid = root.querySelector(".asset-grid");
            var tmp = document.createElement("div"); tmp.innerHTML = html.trim();
            var newGrid = tmp.querySelector(".asset-grid");
            if (oldGrid && newGrid) oldGrid.replaceWith(newGrid);
            var count = root.querySelector("[data-media-count]");
            if (count) count.textContent = (newGrid ? newGrid.querySelectorAll(".asset-cell").length : 0) + " files";
          });
      }
      filters.addEventListener("submit", function (e) { e.preventDefault(); runFilter(); });
      filters.querySelector("[data-filter-kind]").addEventListener("change", runFilter);
      filters.querySelector("[data-filter-q]").addEventListener("input", function () {
        clearTimeout(timer); timer = setTimeout(runFilter, 250);
      });
    }
  }
})();
