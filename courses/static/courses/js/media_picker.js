(function () {
  "use strict";

  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  function flash(host, msg) {
    var bar = document.createElement("div"); bar.className = "op-error";
    // role=alert: the server's _op_error.html has it, this one did not, so a
    // flashed message was never announced. Insert EMPTY then fill -- a live
    // region that arrives already populated is the case screen readers announce
    // least reliably.
    bar.setAttribute("role", "alert");
    host.prepend(bar); bar.textContent = msg;
    setTimeout(function () { bar.remove(); }, 6000);
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
    var appendTarget = null;     // [data-gallery-editor] host when in "append mode"
    var fillTargetCb = null;     // callback from filltable_editor.js when in "cell" mode

    function removeOverlay() {
      if (overlay) { overlay.remove(); overlay = null; }
    }

    function closeModal() {
      removeOverlay();
      targetSelect = null; targetPreview = null;
    }

    // The <select name="media"> is the SINGLE source of the media value. Adding an
    // <option> for the asset if it is not already present, then set select.value.
    // url is optional — stored as data-media-url on [data-media-preview] so other
    // modules (e.g. zone-editor.js) can read the chosen image URL without an extra fetch.
    function selectAsset(id, name, url) {
      if (fillTargetCb) {
        var cb = fillTargetCb;
        fillTargetCb = null;
        closeModal();
        cb(id, name, url);   // id is a STRING (data-asset-id)
        return;
      }
      if (appendTarget && window.libliGalleryAdd) {
        window.libliGalleryAdd(appendTarget, id, name, url);
        appendTarget = null;
        closeModal();
        return;
      }
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
      // Capture the refs: closeModal() nulls targetSelect/targetPreview, so the
      // change dispatch must run on locals. Close BEFORE dispatch so the picker's
      // own document change-listener sees overlay === null (no re-entry).
      var sel = targetSelect;
      var hadPreview = targetPreview !== null;
      closeModal();
      if (hadPreview) {
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    function openModal(html) {
      // Only clear a stale overlay here — NOT the target refs the click handler just
      // set (closeModal() nulls them, which would make every asset-pick a no-op).
      removeOverlay();
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
      appendTarget = pick.getAttribute("data-pick-mode") === "append"
        ? pick.closest("[data-gallery-editor]")
        : null;
      fillTargetCb = null;
      if (pick.getAttribute("data-pick-mode") === "cell") {
        // Dispatch by OWNING EDITOR ROOT. Both editor scripts load on every editor
        // page, so a shared global means whichever runs last wins and one editor's
        // picker silently drives the other's callback.
        if (pick.closest("[data-table-editor]") && window.libliTablePickImage) {
          fillTargetCb = window.libliTablePickImage(pick);
        } else if (window.libliFillTablePickImage) {
          fillTargetCb = window.libliFillTablePickImage(pick);
        }
      }
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
      var fetchBtn = e.target.closest("[data-picker-fetch]");
      if (fetchBtn && overlay.contains(fetchBtn)) {
        var box = overlay.querySelector("[data-picker-url]");
        fetchPickerUrl(box ? box.value.trim() : "");
        return;
      }
    });

    document.addEventListener("keydown", function (e) {
      if (!overlay || e.key !== "Enter") return;
      var box = e.target.closest("[data-picker-url]");
      if (!box || !overlay.contains(box)) return;
      e.preventDefault();
      fetchPickerUrl(box.value.trim());
    });

    // Upload a chosen/dropped file -> POST -> auto-select. Shared by the file input
    // and the drag-and-drop zone so both behave identically.
    function uploadPickerFile(fileObj) {
      var picker = overlay && overlay.querySelector(".picker");
      if (!picker || !fileObj) return;
      var fd = new FormData();
      fd.append("file", fileObj);
      fd.append("kind", picker.getAttribute("data-kind"));
      fetch(picker.getAttribute("data-upload-url"), {
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
    }

    // From URL tab: fetch a hosted image by URL -> auto-select.
    // In-flight guard as a FLAG, not just a disabled button: the panel has a SECOND
    // activation route (Enter on [data-picker-url]) that never touches the button, so
    // DOM state alone lets two Enter presses create two duplicate assets.
    var fetchInFlight = false;

    function fetchPickerUrl(url) {
      var picker = overlay && overlay.querySelector(".picker");
      if (!picker || !url || fetchInFlight) return;
      var btn = overlay.querySelector("[data-picker-fetch]");
      fetchInFlight = true;
      if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
      function done() {
        fetchInFlight = false;
        if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
      }
      var fd = new FormData();
      fd.append("url", url);
      fetch(picker.getAttribute("data-fetch-url"), {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: fd,
      }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
        .then(function (res) {
          var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
          if (res.status !== 200 && res.status !== 201) {
            // Parse the fragment and flash its TEXT: _op_error.html is a full
            // <div class="op-error" role="alert">, and flash() sets textContent -- so
            // passing the raw body shows tags, and innerHTML would nest a second
            // role="alert" inside the flash's own.
            var err = tmp.querySelector(".op-error");
            var card = overlay && overlay.querySelector(".picker-card");  // NOT .picker
            // Guard like the model does (uploadPickerFile above): the author can close
            // the picker during a 20s fetch, leaving overlay null, and flash() would then
            // throw on host.prepend() -- inside the promise chain, before .finally.
            if (card) {
              flash(card, (err && err.textContent.trim()) ||
                          msg(picker, "fetch-failed", "Could not fetch that image."));
            }
            return;
          }
          var cell = tmp.querySelector("[data-asset-id]");
          if (cell) selectAsset(cell.getAttribute("data-asset-id"),
                               cell.getAttribute("data-name"),
                               cell.getAttribute("data-url"));
        })
        .catch(function () {
          // The THIRD outcome. uploadPickerFile has no .catch at all, so without this
          // a network drop leaves the button disabled for the life of the page.
          var card = overlay && overlay.querySelector(".picker-card");
          if (card) flash(card, msg(picker, "fetch-failed", "Could not fetch that image."));
        })
        .finally(done);
    }

    // Upload tab: a file chosen via the file input -> upload.
    document.addEventListener("change", function (e) {
      if (!overlay) return;
      var file = e.target.closest(".picker__file");
      if (!file || !overlay.contains(file) || !file.files || !file.files.length) return;
      uploadPickerFile(file.files[0]);
    });

    // Upload tab: drag-and-drop onto the picker drop zone (parity with the manager).
    // e.target during drag can be a TEXT NODE (the zone's label), which has no
    // .closest() — so resolve to an element first. And we must preventDefault on
    // dragover AND drop for ANY drop inside the open modal, otherwise the browser's
    // default action navigates to / opens the dropped file in a new tab.
    function dropZoneFrom(node) {
      var el = node && node.nodeType === 1 ? node : node && node.parentElement;
      return el ? el.closest("[data-picker-drop]") : null;
    }
    ["dragenter", "dragover"].forEach(function (ev) {
      document.addEventListener(ev, function (e) {
        if (!overlay || !overlay.contains(e.target)) return;
        e.preventDefault();  // mark the modal a valid drop target (no file navigation)
        var dz = dropZoneFrom(e.target);
        if (dz) dz.classList.add("is-over");
      });
    });
    document.addEventListener("dragleave", function (e) {
      var dz = dropZoneFrom(e.target);
      if (dz) dz.classList.remove("is-over");
    });
    document.addEventListener("drop", function (e) {
      if (!overlay || !overlay.contains(e.target)) return;
      e.preventDefault();  // stop the browser opening the dropped file
      var dz = dropZoneFrom(e.target);
      if (dz) dz.classList.remove("is-over");
      if (!dz) return;  // dropped in the modal but off the zone — swallow, no upload
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) uploadPickerFile(files[0]);
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
      // Re-query from root on every call, rather than capturing `grid` once at
      // wire time: the debounced filter's oldGrid.replaceWith(newGrid) (below)
      // detaches whatever node was captured earlier, and prepending into that
      // orphan would silently drop an upload performed after a filter swap.
      var grid = root.querySelector(".asset-grid");
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

    // Fetch-by-URL form: not generic with .media-upload above (that one early-returns
    // unless a file input has files, and builds a FormData carrying file + kind).
    var fetchForm = root.querySelector(".media-fetch");
    if (fetchForm) {
      var mgrInFlight = false;
      fetchForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (mgrInFlight) return;
        var btn = fetchForm.querySelector("[data-fetch-submit]");
        mgrInFlight = true;
        if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
        var fd = new FormData(fetchForm);
        fetch(root.dataset.fetchUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
          body: fd,
        }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
          .then(function (res) {
            var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
            if (res.status === 200 || res.status === 201) {
              insertCell(res.text);
              fetchForm.reset();   // else the URL stays and one more click duplicates
              return;
            }
            var err = tmp.querySelector(".op-error");
            flash(root, (err && err.textContent.trim()) ||
                        msg(root, "fetch-failed", "Could not fetch that image."));
          })
          .catch(function () { flash(root, msg(root, "fetch-failed", "Could not fetch that image.")); })
          .finally(function () {
            mgrInFlight = false;
            if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
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
      // Seed from the cell's data-name, NOT from the span's textContent: the
      // span now renders a middle-truncated name, and the blur handler below
      // commits with save=true -- so seeding from the DOM text would write
      // "head...tail" into MediaAsset.name permanently. No textContent
      // fallback: data-name is unconditional in _asset_cell.html and the pencil
      // only exists in cells rendered by it, so a null here is a broken
      // invariant that should fail loudly rather than silently corrupt a name.
      var seed = cell.getAttribute("data-name");
      if (seed === null) return;
      var input = document.createElement("input");
      input.className = "asset-rename-input input"; input.value = seed.trim();
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
            // `cell` may already be detached -- a replace's 200 for this same
            // asset landing first swaps it out. replaceWith() on a parentless
            // node is a spec'd silent no-op ("if parent is null, return"), so
            // this rename is simply dropped from the grid and the pre-rename
            // name stays on screen until the next grid render. That is the
            // mirror of the limitation documented at length in the replace
            // commit handler below; do NOT re-query by pk here to "fix" it
            // without reading that note first -- the fix is not symmetric and
            // patching one half reintroduces the other.
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

    // ----------------------------------------------------------------------
    // Replace: ⇄ opens the file dialog; a chosen file raises a confirm strip.
    // ----------------------------------------------------------------------
    // wireManager scope, unlike the per-strip `done` below. Its whole job is to
    // stop a ⇄ click on ANOTHER cell mid-request, which per-strip state cannot
    // see. It MUST be lowered in every exit, or replace works exactly once per
    // page load.
    var replaceBusy = false;

    // ONE shared file input, hoisted onto .media-manager itself (manager.html),
    // outside .asset-grid -- so neither a cell swap (inline rename's
    // cell.replaceWith(fresh)) nor a grid swap (the debounced filter's
    // oldGrid.replaceWith(newGrid)) can ever detach it while the OS file dialog
    // is open. Either one landing mid-dialog used to detach a per-cell input, so
    // its `change` bubbled only inside the orphaned tree and never reached this
    // delegated handler -- a silent dead click, no strip, no flash, no error.
    var replaceInput = root.querySelector("[data-replace-input]");
    // The pk of the cell the OPEN file dialog was raised for. Set at click time
    // (below), because the shared input carries no cell context of its own once
    // the dialog is open. Reset on every strip close and on a completed replace
    // so a stale pk can never be reused.
    var pendingReplacePk = null;

    function closeStrip(strip, clearInput) {
      strip.remove();
      if (clearInput) {
        if (replaceInput) replaceInput.value = "";
        pendingReplacePk = null;
      }
    }

    root.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-replace-asset]");
      if (!btn || replaceBusy || !replaceInput) return;
      var cell = btn.closest(".asset-cell");
      if (!cell) return;
      // `accept` is set HERE, per click, not in the template: one shared input
      // now serves both image and video assets, so this is what the per-cell
      // input's static `accept` attribute used to do.
      replaceInput.accept = cell.getAttribute("data-kind") === "image" ? "image/*" : "video/*";
      pendingReplacePk = cell.getAttribute("data-asset-id");
      // Tear NOTHING down here. The dialog may be dismissed (which fires no
      // change at all), and destroying an open strip first would silently lose
      // the author's pending selection. Teardown belongs to the change handler.
      // Clear the value first: the input is now shared and outlives every
      // cell, so a strip discarded WITHOUT going through closeStrip (a filter
      // swap, a delete, an inline rename, or fail()'s isConnected guard) can
      // leave a stale value behind. `change` fires only on a value CHANGE, so
      // re-picking the same file afterwards would be a silent dead click --
      // no strip, no flash. Assigning .value programmatically fires no change
      // event, so this cannot re-enter this handler.
      replaceInput.value = "";
      replaceInput.click();
    });

    root.addEventListener("change", function (e) {
      // Filter on the attribute, not on input.type: root is .media-manager,
      // which also holds the upload form's <input type="file" name="file">,
      // and change bubbles.
      var input = e.target.closest("[data-replace-input]");
      if (!input || !input.files || !input.files.length) return;
      // The input no longer sits inside a cell, so walking up from it is not
      // possible -- re-resolve the target from the live DOM by the pk the ⇄
      // click recorded. Same pattern the 200-response branch below already uses
      // for a detached strip.
      var cell = root.querySelector('.asset-cell[data-asset-id="' + pendingReplacePk + '"]');
      if (!cell) {
        // The asset was filtered out of view while the dialog was open. There
        // is no cell to attach a strip to.
        input.value = "";
        pendingReplacePk = null;
        return;
      }
      // Capture BEFORE any teardown: input.files cannot be restored
      // programmatically.
      var file = input.files[0];
      var open = root.querySelector("[data-replace-strip]");
      if (open) closeStrip(open, true);
      var strip = cell.appendChild(buildReplaceStrip(cell, file));
      // The file input is hidden and never takes focus, and role="group" is not
      // a live region, so without this a keyboard/screen-reader user is left on
      // ⇄ with no cue the strip appeared. Move focus to the strip's own commit
      // action -- the new content that just arrived.
      var commitBtn = strip.querySelector("[data-replace-commit]");
      if (commitBtn) commitBtn.focus();
    });

    function buildReplaceStrip(cell, file) {
      var strip = document.createElement("div");
      strip.className = "asset-replace-confirm";
      strip.setAttribute("data-replace-strip", "");
      strip.setAttribute("role", "group");
      strip.setAttribute("aria-label", msg(root, "replace-aria", "Confirm file replacement"));

      var label = document.createElement("span");
      label.className = "asset-replace-confirm__label";
      label.textContent = msg(root, "replace-confirm", "Replace with:");
      strip.appendChild(label);

      var fname = document.createElement("span");
      fname.className = "asset-replace-confirm__file";
      fname.setAttribute("data-replace-filename", "");
      fname.textContent = file.name;  // textContent: a crafted name cannot inject
      strip.appendChild(fname);

      // getAttribute yields a STRING: `if (cell.dataset.diUses)` is truthy for
      // "0" and would show the caution on every asset in the library.
      if (Number(cell.getAttribute("data-di-uses") || 0) > 0) {
        var warn = document.createElement("span");
        warn.className = "asset-replace-confirm__warn";
        warn.textContent = msg(root, "replace-drag-warning",
          "Used by a drag-to-image question. Drop zones are stored as fractions of the image, so a file with a different shape will move them.");
        strip.appendChild(warn);
      }

      var actions = document.createElement("div");
      actions.className = "asset-replace-confirm__actions";
      var commit = document.createElement("button");
      commit.type = "button"; commit.className = "btn btn--small";
      commit.setAttribute("data-replace-commit", "");
      commit.textContent = msg(root, "replace-commit", "Replace");
      var cancel = document.createElement("button");
      cancel.type = "button"; cancel.className = "btn btn--small btn--ghost";
      cancel.setAttribute("data-replace-cancel", "");
      cancel.textContent = msg(root, "replace-cancel", "Cancel");
      actions.appendChild(commit); actions.appendChild(cancel);
      strip.appendChild(actions);

      // Bound HERE, not delegated: `done` must be a per-strip closure, exactly
      // like the rename handler's. Hoisted to wireManager scope it would be set
      // by the first replace and silently swallow every one after it.
      var done = false;

      function focusTrigger(host) {
        var btn = (host || cell).querySelector("[data-replace-asset]");
        if (btn) btn.focus();
      }

      function fail(text) {
        if (strip.isConnected) { closeStrip(strip, true); focusTrigger(); }
        flash(root, text);
      }

      cancel.addEventListener("click", function () {
        if (done) return;
        closeStrip(strip, true);  // clear, so re-picking the same file re-fires
        focusTrigger();
      });

      commit.addEventListener("click", function () {
        if (done) return;  // the READ is the guard; disabling is the complement
        done = true;
        replaceBusy = true;
        commit.disabled = true;
        // Cancel is disabled too: the POST is unabortable server-side, so a
        // mid-flight cancel would say "nothing happened" and then land a 200.
        cancel.disabled = true;
        var pk = cell.getAttribute("data-asset-id");
        var fd = new FormData();
        fd.append("file", file);
        fetch(cell.getAttribute("data-replace-url"), {
          method: "POST",
          headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
          body: fd,
        })
          .then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
          .then(function (res) {
            var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
            var fresh = res.status === 200 ? tmp.querySelector(".asset-cell") : null;
            if (fresh) {
              if (strip.isConnected) {
                cell.replaceWith(fresh);
                focusTrigger(fresh);
              } else {
                // A grid or cell swap landed mid-flight and detached us. The
                // replace COMMITTED, but the refetched grid was rendered
                // pre-commit, so a no-op would leave a stale thumbnail. Query
                // from root: wireManager's `grid` local is the node the filter
                // replaced.
                //
                // KNOWN LIMITATION -- deliberate. Do not "fix" one half of it.
                //
                // This branch handles the filter swap it was written for. It
                // does NOT handle an inline rename of this same asset
                // committing during the flight: `fresh` was rendered by the
                // server BEFORE that rename, so this replaceWith puts the
                // pre-rename display name back on screen. The mirror case is
                // documented at the rename handler above -- flip the order and
                // its cell.replaceWith() runs on a parentless node and drops
                // the rename instead. One pair, two orderings.
                //
                // No client-side arbitration is correct. Both responses carry a
                // FULL cell rendered from a different DB snapshot and neither
                // snapshot is complete -- the replace's render can predate the
                // rename's commit, and the rename's render can predate the
                // replace's commit. The `seq` generation counter the filter
                // below uses does not transfer: it orders two responses to the
                // SAME request, not two different writes. Last-write-wins picks
                // a loser whichever way it is pointed. A field-level merge does
                // not separate them either, because display_name falls back to
                // original_filename (models.py), which a replace also writes.
                // Only a re-fetch issued after BOTH commits is authoritative,
                // and the client cannot know that it is one.
                //
                // So it is left as-is, on purpose. A single-cell refresh
                // endpoint would only narrow the window -- it is another round
                // trip a later rename can beat -- at the cost of a new view,
                // URL and permission surface. Closing it properly means gating
                // the rename and delete controls on replaceBusy AND cancelling
                // an open rename input at commit time, because clicking Replace
                // blurs that input and fires its commit(true) before the guard
                // is set. Neither is worth the residue: it needs ONE author
                // renaming the very asset whose replace strip is on screen with
                // both buttons disabled (there is no cross-session path -- this
                // page has no polling or sockets); the row, the file and the
                // thumbnail are all correct; and any grid re-render clears it,
                // whether a reload or a single keystroke in the filter box.
                var live = root.querySelector('.asset-cell[data-asset-id="' + pk + '"]');
                if (live) live.replaceWith(fresh);
              }
              // The completed replace's file is consumed; the shared input no
              // longer belongs to any cell being edited. Clear it here too --
              // this branch does not go through closeStrip.
              if (replaceInput) replaceInput.value = "";
              pendingReplacePk = null;
              return;
            }
            // Anything else -- other statuses, a rejected promise, AND a 200
            // whose body has no cell. fetch follows redirects, so a POST after
            // the session expires resolves as 200 carrying the login page: not
            // 422, not an error status, not a rejection. Without this branch
            // the strip stays open with both buttons disabled, unrecoverable.
            var text = "";
            if (res.status === 422) {
              var box = tmp.querySelector(".op-error");
              if (box) text = (box.textContent || "").trim();
            }
            fail(text || msg(root, "replace-failed", "Could not replace the file."));
          })
          .catch(function () {
            fail(msg(root, "replace-failed", "Could not replace the file."));
          })
          .then(function () { replaceBusy = false; });  // finally-equivalent
      });

      return strip;
    }

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
