(function () {
  "use strict";

  // Gallery editor: progressively enhance [data-gallery-editor] blocks. The
  // hidden input[name="data"] is the SOLE authoritative field; rows + the
  // desc-position select are name-less JS UI mirrored into it via serialize().
  // New rows are cloned from the <template data-gallery-row-template>; images are
  // added via media_picker.js "append mode" (window.libliGalleryAdd below).

  var editors = [];

  function wire(editor) {
    if (editor.dataset.galleryWired) return;
    editor.dataset.galleryWired = "1";

    var hidden = editor.querySelector('input[name="data"]');
    var rows = editor.querySelector("[data-gallery-rows]");
    var posSel = editor.querySelector("[data-desc-pos]");
    var toolbar = editor.querySelector("[data-gallery-toolbar]");
    var tmpl = editor.querySelector("[data-gallery-row-template]");
    if (!hidden || !rows) return;
    editor._galleryTmpl = tmpl;

    function rowEls() {
      return Array.prototype.slice.call(rows.querySelectorAll("[data-gallery-row]"));
    }

    function serialize() {
      var images = rowEls().map(function (li) {
        var desc = li.querySelector("[data-gallery-desc]");
        return {
          media: parseInt(li.getAttribute("data-media-id"), 10),
          desc: desc ? desc.innerHTML : "",
        };
      }).filter(function (img) { return !isNaN(img.media); });
      hidden.value = JSON.stringify({
        desc_pos: (posSel && posSel.value) || "below",
        images: images,
      });
    }
    editor._gallerySerialize = serialize;

    // Focus tracking for the shared toolbar (which desc box commands apply to).
    var focusedDesc = null;
    rows.addEventListener("focusin", function (e) {
      var d = e.target.closest("[data-gallery-desc]");
      if (d) { focusedDesc = d; if (toolbar) toolbar.hidden = false; }
    });

    rows.addEventListener("input", serialize);

    rows.addEventListener("click", function (e) {
      var li = e.target.closest("[data-gallery-row]");
      if (!li) return;
      if (e.target.closest("[data-gallery-remove]")) { li.remove(); serialize(); return; }
      if (e.target.closest("[data-gallery-up]")) {
        var prev = li.previousElementSibling;
        if (prev) rows.insertBefore(li, prev);
        serialize(); return;
      }
      if (e.target.closest("[data-gallery-down]")) {
        var next = li.nextElementSibling;
        if (next) rows.insertBefore(next, li);
        serialize(); return;
      }
    });

    if (posSel) posSel.addEventListener("change", serialize);

    if (toolbar) {
      toolbar.addEventListener("click", function (e) {
        var btn = e.target.closest("[data-cmd]");
        if (!btn || !focusedDesc) return;
        var cmd = btn.getAttribute("data-cmd");
        focusedDesc.focus();
        if (cmd === "bold" || cmd === "italic" || cmd === "underline") {
          document.execCommand("styleWithCSS", false, false);
          document.execCommand(cmd, false, null);
          serialize();
        } else if (cmd === "math") {
          if (!window.libliMathInput) return;
          var sel = window.getSelection();
          var range = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
          var cell = focusedDesc;
          window.libliMathInput.open(function (latex) {
            cell.focus();
            var node = document.createTextNode("\\(" + latex + "\\)");
            if (range) {
              range.deleteContents(); range.insertNode(node);
              range.setStartAfter(node); range.collapse(true);
              sel.removeAllRanges(); sel.addRange(range);
            } else {
              cell.appendChild(node);
            }
            serialize();
          });
        }
      });
    }

    // Serialize on init only when the hidden field is empty (add path); an
    // invalid re-render already carries the submitted JSON.
    if (hidden.value === "") serialize();
    editors.push(editor);
  }

  // Called by media_picker.js append mode when the author picks an image.
  window.libliGalleryAdd = function (editor, id, name, url) {
    var tmpl = editor._galleryTmpl;
    var rows = editor.querySelector("[data-gallery-rows]");
    if (!tmpl || !rows) return;
    var li = tmpl.content.firstElementChild.cloneNode(true);
    li.setAttribute("data-media-id", String(id));
    var img = li.querySelector(".gallery-editor__thumb");
    if (img && url) img.src = url;
    rows.appendChild(li);
    if (editor._gallerySerialize) editor._gallerySerialize();
  };

  function initGalleryEditor(root) {
    (root || document).querySelectorAll("[data-gallery-editor]").forEach(wire);
  }

  window.libliInitGalleryEditor = initGalleryEditor;
  initGalleryEditor(document);
})();
