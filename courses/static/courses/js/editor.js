(function () {
  "use strict";
  var root = document.querySelector(".editor");
  if (!root) return;
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  // Inline math (\(...\) / \[...\]) for the live preview: stems, choices, and swapped
  // feedback slots. The student pages do this in question.js; the editor reuses the
  // same KaTeX auto-render so the preview matches what learners see. (math.js /
  // libliRenderMath only handles [data-katex] display elements, not inline delimiters.)
  function renderPreviewMath(scope) {
    if (typeof renderMathInElement !== "function" || !scope) return;
    try {
      renderMathInElement(scope, {
        delimiters: [
          { left: "\\(", right: "\\)", display: false },
          { left: "\\[", right: "\\]", display: true },
        ],
        throwOnError: false,
      });
    } catch (e) { /* leave raw LaTeX on error */ }
  }
  function msg(key, fallback) { return root.getAttribute("data-msg-" + key) || fallback; }

  // Re-run after every fragment swap: KaTeX preview render + MathLive/RTE surface mount
  // for any open editor form. (Media picker self-wires via delegated listeners on .editor
  // in media_picker.js, so it survives swaps without re-init here.)
  // The server re-renders the whole pane on every op, so any transient CLIENT state is
  // discarded on the swap unless we carry it across: which tab <details> are open (the
  // template always re-opens the first, snapping the author's choice back) and the pane
  // scroll positions (a drag-drop otherwise jumps to the very top). Keyed by a stable
  // (element pk, tab id) so a reorder that shuffles the DOM still restores correctly.
  function tabKey(details) {
    var row = details.closest(".el-row--tabs");
    return (row ? row.getAttribute("data-element") : "?") + ":" + details.getAttribute("data-tab-id");
  }
  function captureOpenTabs() {
    var map = {};
    root.querySelectorAll('[data-scope="editor"] details.tabs-rows').forEach(function (d) {
      map[tabKey(d)] = d.open;
    });
    return map;
  }
  function restoreOpenTabs(map) {
    root.querySelectorAll('[data-scope="editor"] details.tabs-rows').forEach(function (d) {
      // Only override a details whose element existed before the swap; a newly-added
      // tabs element is absent from the map and keeps the template's first-open default.
      var k = tabKey(d);
      if (Object.prototype.hasOwnProperty.call(map, k)) d.open = map[k];
    });
  }
  function paneBodies() { return root.querySelectorAll('[data-scope] .pane-body'); }
  function captureScroll() {
    var s = [];
    paneBodies().forEach(function (b) { s.push(b.scrollTop); });
    return s;
  }
  function restoreScroll(s) {
    paneBodies().forEach(function (b, i) { if (s[i] != null) b.scrollTop = s[i]; });
  }

  function applyFragments(html) {
    var openTabs = captureOpenTabs();
    var scrolls = captureScroll();
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    ["editor", "preview"].forEach(function (scope) {
      var incoming = tmp.querySelector('[data-scope="' + scope + '"]');
      var existing = root.querySelector('[data-scope="' + scope + '"]');
      if (incoming && existing) existing.replaceWith(incoming);
    });
    restoreOpenTabs(openTabs);
    var preview = root.querySelector('[data-scope="preview"]');
    if (preview && window.libliRenderMath) window.libliRenderMath(preview);
    if (preview) renderPreviewMath(preview);  // inline math in stems/choices
    if (preview && window.libliEnhanceDnd) window.libliEnhanceDnd(preview);  // re-inject drag chips/slots
    if (preview && window.libliInitGallery) window.libliInitGallery(preview);  // re-enhance galleries into carousels
    if (preview && window.libliInitTabs) window.libliInitTabs(preview);  // re-enhance tabs
    var editorPane = root.querySelector('[data-scope="editor"]');
    if (editorPane && window.libliInitMathLive) window.libliInitMathLive(editorPane);
    if (editorPane && window.libliInitRte) window.libliInitRte(editorPane);
    if (editorPane && window.libliInitTableEditor) window.libliInitTableEditor(editorPane);
    if (editorPane && window.libliInitGalleryEditor) window.libliInitGalleryEditor(editorPane);
    if (editorPane && window.libliInitTabsEditor) window.libliInitTabsEditor(editorPane);
    // Mount the drag-to-image zone-drawing canvas on a freshly-swapped edit form
    // (zone-editor.js otherwise only self-inits on DOMContentLoaded, before the form
    // is fetched). Idempotent via dataset.zoneReady, so a re-swap is safe.
    if (editorPane && window.libliZoneEditor) window.libliZoneEditor(editorPane);
    bindDnD();  // handlers re-bound after every swap (Task 8)
    bindHover();  // re-bind editor->preview hover after the pane is replaced
    restoreScroll(scrolls);  // last: after re-init so layout has settled
  }

  // Exposed so editor_dnd.js's drop handler reuses the SAME swap (re-init + open-tab +
  // scroll preservation) instead of a bespoke replaceWith that skipped all of it.
  window.__libliApplyFragments = applyFragments;

  // Hover an editor row -> highlight the matching element in the preview.
  function setHighlight(id, on) {
    if (!id) return;
    var prev = root.querySelector('.prev-el[data-element-id="' + id + '"]');
    if (prev) prev.classList.toggle("prev-el--hl", on);
  }
  function bindHover() {
    var rows = root.querySelectorAll(".el-row[data-element]");
    Array.prototype.forEach.call(rows, function (row) {
      var id = row.getAttribute("data-element");
      row.addEventListener("mouseenter", function () { setHighlight(id, true); });
      row.addEventListener("mouseleave", function () { setHighlight(id, false); });
    });
  }

  // Scroll ONLY the element's own pane (.pane-body) so its top aligns to the pane's content
  // top (inside the padding) — NEVER scrollIntoView, which also scrolls the overflow:hidden
  // page body. The user can't scroll that back, so it would strand the page header (and slide
  // the editor rows under the pointer, highlighting a neighbour) off-screen.
  function alignTopInPane(el, behavior) {
    if (!el) return;
    var body = el.closest(".pane-body");
    if (!body) return;
    var padTop = parseFloat(getComputedStyle(body).paddingTop) || 0;
    var delta = el.getBoundingClientRect().top - body.getBoundingClientRect().top - padTop;
    if (Math.abs(delta) < 1) return;  // already aligned -> don't fight a settled layout
    body.scrollTo({ top: body.scrollTop + delta, behavior: behavior || "auto" });
  }

  // Align the selected element to the top of the preview. The rebuilt preview grows AFTER
  // layout (sandboxed HTML iframes, images, KaTeX), so align now for feedback, then re-align
  // as that async content loads and once more shortly after.
  function scrollPreviewTo(id) {
    if (!id) return;
    var sel = '.prev-el[data-element-id="' + id + '"]';
    if (!root.querySelector(sel)) return;  // absent (failed/empty swap or deleted) -> no-op
    var smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    function toTop(behavior) { alignTopInPane(root.querySelector(sel), behavior); }
    requestAnimationFrame(function () { toTop(smooth ? "smooth" : "auto"); });
    var preview = root.querySelector('[data-scope="preview"]');
    if (preview) {
      Array.prototype.forEach.call(preview.querySelectorAll("img, iframe"), function (n) {
        n.addEventListener("load", function () { toTop("auto"); });
      });
    }
    setTimeout(function () { toTop("auto"); }, 500);
  }

  // Shared POST -> text -> applyFragments plumbing for the "add element" flows below
  // (normal add-via-editor-form and the field-less slide-break direct-create). Branch-
  // specific logic (extra form fields, post-success scrolling) stays in the callers.
  function postFragment(url, formData, onDone) {
    fetch(url, {
      method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: formData,
    }).then(function (r) { return r.text(); }).then(function (html) {
      applyFragments(html);
      if (onDone) onDone();
    });
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
    // "Try it" in the live preview: a question's answer form. Post to its
    // (manage-gated, non-persisting) action via fetch+CSRF header and inject the
    // feedback partial — mirrors question.js, but delegated on .editor so it survives
    // the fragment swaps that replace the preview pane.
    var tryForm = e.target.closest('[data-scope="preview"] form.question__form');
    if (tryForm) {
      e.preventDefault();
      var qEl = tryForm.closest("[data-question]");
      var made = qEl ? parseInt(qEl.getAttribute("data-attempts-made") || "0", 10) : 0;
      var body = new FormData(tryForm);
      if (e.submitter && e.submitter.name) body.append(e.submitter.name, e.submitter.value);
      body.append("attempt", String(made + 1));  // quiz gating; ignored by lessons
      fetch(tryForm.action, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: body,
      }).then(function (r) { return r.text(); }).then(function (html) {
        var slot = tryForm.querySelector("[data-question-feedback]");
        if (!slot) return;
        slot.innerHTML = html;
        if (window.libliRenderMath) window.libliRenderMath(slot);
        renderPreviewMath(slot);  // inline math in revealed answers / explanation
        if (!qEl) return;
        // An empty-answer validation doesn't consume an attempt; everything else does.
        if (!slot.querySelector(".is-validation")) {
          qEl.setAttribute("data-attempts-made", String(made + 1));
        }
        // Terminal quiz state (correct / out of attempts / [N]/[R]) -> freeze inputs,
        // mirroring the student quiz lock.
        if (slot.querySelector("[data-quiz-locked]")) {
          qEl.querySelectorAll("input, button[type=submit]").forEach(function (n) {
            n.disabled = true;
          });
        }
      });
      return;
    }
    var form = e.target.closest("form[data-op]");
    if (!form) return;
    e.preventDefault();
    // Remember which element this op acts on so we can keep its row in view after the
    // rebuild: collapsing the editor shrinks the (now height-capped) page, and the
    // browser's own scroll restoration otherwise jumps to the wrong place.
    var opRow = form.closest(".el-row[data-element]");
    var keepId = opRow ? opRow.getAttribute("data-element") : null;
    post(form, e.submitter).then(function (res) {
      if (res.status === 200 || res.status === 409 || res.status === 422) {
        applyFragments(res.text);
        if (res.status === 409) flash(msg("conflict", "This changed elsewhere — reloaded to the latest."));
        if (keepId) {
          alignTopInPane(root.querySelector('.el-row[data-element="' + keepId + '"]'));
          scrollPreviewTo(keepId);  // re-align the preview to the element, not reset to top
        }
      }
    });
  });

  root.addEventListener("click", function (e) {
    var toggle = e.target.closest("[data-add-toggle]");
    if (toggle) {
      // Scope to the clicked toggle's OWN add-menu: a tabs element renders a nested
      // add-menu per tab, so a bare root.querySelector would always toggle the first
      // (top-level) menu and leave every nested "Add element" unable to open its cards.
      var menu = (toggle.closest("[data-add-menu]") || root).querySelector("[data-type-menu]");
      if (menu) {
        menu.hidden = !menu.hidden;
        // The type menu is in-flow at the bottom of the editor pane; once open it can
        // extend past the fold. Bring it into the pane so its options are reachable.
        if (!menu.hidden) alignTopInPane(menu, "smooth");
      }
      return;
    }
    var add = e.target.closest("[data-add-type]");
    if (add) {
      var pane = root.querySelector('[data-scope="editor"]');
      var addType = add.getAttribute("data-add-type");
      // A nested add menu (inside a tabs element) carries the scope. element_add echoes
      // it back as hidden fields in the host form, so it survives the second hop to
      // element_save.
      var menu = add.closest("[data-add-menu]");
      var nestedParent = menu && menu.getAttribute("data-parent");
      // Slide break: a field-less delimiter with no editor form at all — create it
      // directly against the save endpoint (same one the editor forms submit to)
      // instead of the normal add -> open-editor flow. It is non-nestable, so the
      // fast-path can never fire from a nested menu (the card is hidden there, but be
      // explicit — the server rejects a nested slidebreak regardless).
      if (addType === "slidebreak" && !nestedParent) {
        var brkBody = new FormData();
        brkBody.append("type", "slidebreak");
        brkBody.append("unit", pane.getAttribute("data-unit"));
        brkBody.append("element", "new");
        brkBody.append("unit_token", pane.getAttribute("data-updated"));
        postFragment(pane.getAttribute("data-save-url"), brkBody);
        return;
      }
      var fd = new FormData();
      fd.append("type", addType);
      fd.append("unit", pane.getAttribute("data-unit"));
      if (nestedParent) {
        fd.append("parent", nestedParent);
        fd.append("tab", menu.getAttribute("data-tab"));
      }
      postFragment(pane.getAttribute("data-add-url"), fd, function () {
        // The new row + its (often tall) editor form append at the bottom of the pane;
        // align it to the pane top so the author doesn't have to scroll to start editing.
        var newForm = root.querySelector('[data-edit-slot] form[data-op="element-save"]');
        var newRow = newForm && newForm.closest(".el-row");
        if (newRow) alignTopInPane(newRow);
      });
      return;
    }
    var addChoice = e.target.closest("[data-choice-add]");
    if (addChoice) { addChoiceRow(); return; }
    var cancel = e.target.closest("[data-cancel-edit]");
    if (cancel) {
      var row = cancel.closest(".el-row");
      // Slot via the row, not closest(): the row-level ✕ (shown while editing) lives in the
      // row head, outside [data-edit-slot]; the in-form Cancel is inside it. Both reach it.
      var slot = row ? row.querySelector("[data-edit-slot]") : cancel.closest("[data-edit-slot]");
      if (slot) slot.innerHTML = "";
      if (row) {
        row.classList.remove("el-row--editing");
        // Drop an unsaved new row; for a saved row the form just collapses in place — the
        // editor pane keeps its scroll position, so the row stays in view (no scroll needed).
        if (!row.getAttribute("data-element")) row.remove();  // unsaved new row
      }
      return;
    }
    var sel = e.target.closest(".el-select");
    if (sel) {
      var selId = sel.getAttribute("data-element-id");
      fetch(sel.getAttribute("data-form-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          applyFragments(html);
          scrollPreviewTo(selId);
          // Two-pane: the editor scrolls inside its own pane, so after the rebuild bring
          // the freshly-opened edit form into view (align its row to the top of the pane).
          alignTopInPane(root.querySelector('.el-row[data-element="' + selId + '"]'));
        });
      return;
    }
    // Click anywhere else on an element row (not a control or the open editor) -> just
    // scroll the preview to that element, without opening its editor. The preview already
    // exists here (no fragment swap), so scrollPreviewTo aligns it immediately.
    var elRow = e.target.closest(".el-row[data-element]");
    if (elRow && !e.target.closest("button, a, input, textarea, select, label, form, [draggable='true'], [data-edit-slot]")) {
      scrollPreviewTo(elRow.getAttribute("data-element"));
    }
  });

  // --- Choice-question editor: dynamic option rows + correct-marker behaviour ---
  // Append a blank choice row by cloning the last one, renumbering its formset fields
  // to the next index, and bumping TOTAL_FORMS. No-JS authors still get the extra=2
  // blank rows server-side; this just removes the 2-row ceiling when JS is on.
  function addChoiceRow() {
    var list = root.querySelector("[data-choice-rows]");
    var total = root.querySelector('[name$="-TOTAL_FORMS"]');
    if (!list || !total) return;
    var rows = list.querySelectorAll("[data-choice-row]");
    var last = rows[rows.length - 1];
    if (!last) return;
    var idx = parseInt(total.value, 10);
    var clone = last.cloneNode(true);
    Array.prototype.forEach.call(clone.querySelectorAll("[name],[id],[for]"), function (el) {
      ["name", "id", "for"].forEach(function (attr) {
        var v = el.getAttribute(attr);
        // replace the form index (the first -N- / _N_ run) with the new index
        if (v) el.setAttribute(attr, v.replace(/([-_])\d+([-_])/, "$1" + idx + "$2"));
      });
    });
    Array.prototype.forEach.call(clone.querySelectorAll("input, textarea"), function (el) {
      if (el.type === "checkbox" || el.type === "radio") el.checked = false;
      else el.value = "";
    });
    clone.classList.remove("choice-row--del");
    list.appendChild(clone);
    total.value = idx + 1;
  }

  root.addEventListener("change", function (e) {
    // Single-choice correct-markers render as radios but each formset row has a DISTINCT
    // name, so the browser does not group them — enforce "only one" here.
    var correct = e.target.closest("[data-choice-correct]");
    if (correct && correct.type === "radio" && correct.checked) {
      var group = correct.closest("[data-choice-rows]");
      if (group) {
        Array.prototype.forEach.call(group.querySelectorAll("[data-choice-correct]"), function (r) {
          if (r !== correct && r.type === "radio") r.checked = false;
        });
      }
      return;
    }
    // Live feedback for the formset DELETE checkbox (otherwise "Remove" looks inert
    // until the form is saved). Reversible: untick to restore the row.
    var del = e.target.closest('[name$="-DELETE"]');
    if (del) {
      var row = del.closest("[data-choice-row]");
      if (row) row.classList.toggle("choice-row--del", del.checked);
    }
  });

  function flash(msg) {
    var bar = document.createElement("div"); bar.className = "op-error"; bar.textContent = msg;
    root.prepend(bar); setTimeout(function () { bar.remove(); }, 6000);
  }

  function bindDnD() { if (window.__libliEditorDnD) window.__libliEditorDnD(root); }
  bindDnD();
  bindHover();
  // Initial inline-math pass over the preview present at page load (auto-render.min.js
  // loads deferred, so guard via the typeof check inside renderPreviewMath).
  var initPreview = root.querySelector('[data-scope="preview"]');
  if (initPreview) renderPreviewMath(initPreview);

  // The build view's "+ Add element" links here with ?add=1 (plain "Open editor" does
  // not). Open the TOP-LEVEL add menu on load -- :not([data-parent]) excludes the nested
  // per-tab menus -- by re-using the toggle's own click handler, so without it the two
  // links land on an identical page and the add gesture is invisible.
  if (new URLSearchParams(location.search).get("add") === "1") {
    var addToggle = root.querySelector(
      '[data-scope="editor"] [data-add-menu]:not([data-parent]) [data-add-toggle]'
    );
    if (addToggle) addToggle.click();
  }
})();
