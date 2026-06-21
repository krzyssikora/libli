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
    if (preview) renderPreviewMath(preview);  // inline math in stems/choices
    if (preview && window.libliEnhanceDnd) window.libliEnhanceDnd(preview);  // re-inject drag chips/slots
    var editorPane = root.querySelector('[data-scope="editor"]');
    if (editorPane && window.libliInitMathLive) window.libliInitMathLive(editorPane);
    if (editorPane && window.libliInitRte) window.libliInitRte(editorPane);
    bindDnD();  // handlers re-bound after every swap (Task 8)
    bindHover();  // re-bind editor->preview hover after the pane is replaced
  }

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

  // Scroll the preview to a just-selected element after the fragment swap rebuilt it.
  // Deferred one frame: applyFragments runs KaTeX / inline-math / DnD enhancement
  // synchronously, but scrollIntoView must read geometry AFTER the browser's layout
  // flush, or a re-rendered element that grew above the target throws the landing off.
  // querySelector returns null when the id is absent (failed/empty swap, or a deleted
  // element) and the guard makes it a no-op, so this can never throw.
  function scrollPreviewTo(id) {
    if (!id) return;
    var el = root.querySelector('.prev-el[data-element-id="' + id + '"]');
    if (!el) return;
    var smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    requestAnimationFrame(function () {
      el.scrollIntoView({ block: "nearest", behavior: smooth ? "smooth" : "auto" });
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
    post(form, e.submitter).then(function (res) {
      if (res.status === 200 || res.status === 409 || res.status === 422) {
        applyFragments(res.text);
        if (res.status === 409) flash(msg("conflict", "This changed elsewhere — reloaded to the latest."));
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
    var addChoice = e.target.closest("[data-choice-add]");
    if (addChoice) { addChoiceRow(); return; }
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
      var selId = sel.getAttribute("data-element-id");
      fetch(sel.getAttribute("data-form-url"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) { applyFragments(html); scrollPreviewTo(selId); });
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
})();
