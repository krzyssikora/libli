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
  // Which container <details> are open is CLIENT state the server never knows: the
  // template decides the open-state fresh on every render, so both a fragment rebuild
  // AND a full page refresh would snap the author's choice back. Persist it in
  // localStorage keyed by (element pk, slot id) -- the pk is globally unique, so no
  // unit scoping is needed -- and re-apply it after every swap and on initial load. A
  // slot with no stored entry (never toggled, or a brand-new element) keeps whatever
  // the template rendered.
  //
  // BOTH container kinds, tabs rows and columns rows. Columns were left out when this
  // was written and so had no memory at all: the author expanded column 2, clicked
  // Edit inside it, and the rebuilt pane put it straight back to shut.
  var SLOT_DETAILS = "details.tabs-rows, details.columns-rows";
  function slotStoreKey(details) {
    // Nearest element row, which for either kind is the container's OWN row -- a
    // <details> here is a child of that row and of nothing else in between. Keyed on
    // .el-row rather than on .el-row--tabs so one function serves both branches, and
    // so a container nested inside another container still keys on itself.
    var row = details.closest(".el-row[data-element]");
    // "tabopen" is now a misnomer for half the keys, and stays anyway: renaming the
    // prefix would orphan every tab preference the authors have already stored.
    return "libli:tabopen:" + (row ? row.getAttribute("data-element") : "?") +
      ":" + (details.getAttribute("data-tab-id") || details.getAttribute("data-column-id"));
  }
  function saveSlot(details) {
    try { localStorage.setItem(slotStoreKey(details), details.open ? "1" : "0"); }
    catch (e) { /* localStorage unavailable (private mode) -> in-session only */ }
  }
  function applyStoredSlots(scope) {
    (scope || root).querySelectorAll(SLOT_DETAILS)
      .forEach(function (d) {
        // A server-forced-open container ignores the stored preference. Without
        // this, the server renders the destination slot open and we immediately
        // re-collapse it, so a just-duplicated element is born invisible -- and the
        // form the author just opened would be hidden by their own stale collapse.
        // The author's toggle is still RECORDED by saveSlot and takes effect again as
        // soon as the force-open stops being rendered.
        if (d.hasAttribute("data-force-open")) return;
        var v;
        try { v = localStorage.getItem(slotStoreKey(d)); } catch (e) { v = null; }
        if (v !== null) d.open = v === "1";
      });
  }
  // Which tab a PREVIEW tabs element is showing is client state too, but of a
  // different kind from the editor <details> above: it is "what am I looking at right
  // now", not a stored preference. So it is carried across the swap in memory and
  // never written to localStorage -- a student's tabs element must still open on its
  // first tab, and a full page refresh legitimately starts over.
  //
  // Needed because applyFragments REPLACES the whole preview pane, destroying the
  // node that held tabs.js's active-tab state. Keyed on data-tabs-eid (the join row
  // pk), so a tabs element nested inside another restores independently.
  function captureActiveTabs() {
    var map = {};
    root.querySelectorAll('[data-scope="preview"] [data-tabs][data-tabs-eid]')
      .forEach(function (c) {
        var active = c.getAttribute("data-tabs-active");
        if (active) map[c.getAttribute("data-tabs-eid")] = active;
      });
    return map;
  }
  function restoreActiveTabs(preview, map) {
    preview.querySelectorAll("[data-tabs][data-tabs-eid]").forEach(function (c) {
      var active = map[c.getAttribute("data-tabs-eid")];
      // A stale id -- the author just deleted that tab -- is stamped anyway: tabs.js
      // resolves the hint against its OWN sections and falls back to the first, which
      // is the same answer as not stamping at all. Doing the existence check here
      // instead would have to guess at instance ownership, which tabs.js already knows.
      if (active) c.setAttribute("data-tabs-active", active);
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

  // Every element op bumps unit.updated (builder.save_element), and the swap below
  // re-renders the token carriers INSIDE the panes. The unit-level forms live OUTSIDE
  // both panes in editor.html -- the Settings <details> and the Lesson/Quiz type
  // toggle -- so they kept the token this page was FIRST rendered with, and the
  // author's next settings save / type switch 409'd with "This changed elsewhere",
  // succeeding only on the retry after the reload. Re-stamp them from the pane the
  // server just re-rendered. Anchored on the unit pk (each form carries name="node"),
  // so an unrelated token input is never touched. Mirrors the builder's applyRename,
  // which must likewise refresh EVERY carrier of a node's token.
  function refreshUnitTokens() {
    var pane = root.querySelector('[data-scope="editor"]');
    if (!pane) return;
    var updated = pane.getAttribute("data-updated");
    var unitPk = pane.getAttribute("data-unit");
    if (!updated || !unitPk) return;
    root.querySelectorAll('form input[name="token"]').forEach(function (input) {
      var node = input.form && input.form.querySelector('input[name="node"]');
      if (node && node.value === unitPk) input.value = updated;
    });
  }

  function applyFragments(html) {
    var scrolls = captureScroll();
    var activeTabs = captureActiveTabs();  // BEFORE the swap destroys the old pane
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    ["editor", "preview"].forEach(function (scope) {
      var incoming = tmp.querySelector('[data-scope="' + scope + '"]');
      var existing = root.querySelector('[data-scope="' + scope + '"]');
      if (incoming && existing) existing.replaceWith(incoming);
    });
    refreshUnitTokens();  // after the swap: the pane now carries the fresh token
    applyStoredSlots(root);
    var preview = root.querySelector('[data-scope="preview"]');
    if (preview && window.libliRenderMath) window.libliRenderMath(preview);
    if (preview) renderPreviewMath(preview);  // inline math in stems/choices
    if (preview && window.libliEnhanceDnd) window.libliEnhanceDnd(preview);  // re-inject drag chips/slots
    if (preview && window.libliInitGallery) window.libliInitGallery(preview);  // re-enhance galleries into carousels
    if (preview && window.libliInitImageZoom) window.libliInitImageZoom(preview);  // re-arm zoomable images
    // MUST precede libliInitTabs: the hint is read once, when the enhancer builds the
    // strip. Stamping it afterwards would leave the author on tab 1 with a data
    // attribute claiming otherwise.
    if (preview) restoreActiveTabs(preview, activeTabs);
    if (preview && window.libliInitTabs) window.libliInitTabs(preview);  // re-enhance tabs
    if (preview && window.libliInitBeforeAfter) window.libliInitBeforeAfter(preview);  // re-enhance before/after
    if (preview && window.libliInitRevealGates) window.libliInitRevealGates(preview);  // un-hide reveal-gate buttons
    if (preview && window.libliInitFillGates) window.libliInitFillGates(preview);  // re-arm fill-gates
    if (preview && window.libliInitSwitchGates) window.libliInitSwitchGates(preview);  // re-arm switch-gates
    if (preview && window.libliInitSwitchGrids) window.libliInitSwitchGrids(preview);  // re-arm switch-grids
    if (preview && window.libliInitFillTables) window.libliInitFillTables(preview);  // re-arm fill-tables
    if (preview && window.libliInitStepper) window.libliInitStepper(preview);  // step the preview
    if (preview && window.libliInitMarkDone) window.libliInitMarkDone(preview);  // enhance checklists
    if (preview && window.libliInitGuessNumbers) window.libliInitGuessNumbers(preview);  // re-arm guess-number
    var editorPane = root.querySelector('[data-scope="editor"]');
    if (editorPane && window.libliInitMathLive) window.libliInitMathLive(editorPane);
    if (editorPane && window.libliInitRte) window.libliInitRte(editorPane);
    if (editorPane && window.libliInitTableEditor) window.libliInitTableEditor(editorPane);
    if (editorPane && window.libliInitFillTableEditor) window.libliInitFillTableEditor(editorPane);
    if (editorPane && window.libliInitGalleryEditor) window.libliInitGalleryEditor(editorPane);
    if (editorPane && window.libliInitTabsEditor) window.libliInitTabsEditor(editorPane);
    if (editorPane && window.libliInitSwitchGridEditors) window.libliInitSwitchGridEditors(editorPane);
    if (editorPane && window.libliInitChoiceGrid) window.libliInitChoiceGrid(editorPane);  // re-sync matrix column/row selects
    if (editorPane && window.libliInitMultiGrid) window.libliInitMultiGrid(editorPane);  // re-sync multi-select grid checkboxes
    if (editorPane && window.libliInitFormsetRows) window.libliInitFormsetRows(editorPane);  // reveal JS-only row controls + reconcile a 422
    if (editorPane && window.libliInitSwitchGateEditor) window.libliInitSwitchGateEditor(editorPane);  // reveal switchgate's add/remove + renumber
    if (editorPane) syncChoiceFeedback(editorPane);  // adaptive per-option feedback prompts
    // Mount the drag-to-image zone-drawing canvas on a freshly-swapped edit form
    // (zone-editor.js otherwise only self-inits on DOMContentLoaded, before the form
    // is fetched). Idempotent via dataset.zoneReady, so a re-swap is safe.
    if (editorPane && window.libliZoneEditor) window.libliZoneEditor(editorPane);
    // Swapped-in tables/grids arrive with no scroll listener; re-arm both panes so
    // the edge affordance works on freshly rendered content as well as first paint.
    if (window.libliInitScrollAffordance) {
      if (editorPane) window.libliInitScrollAffordance(editorPane);
      if (preview) window.libliInitScrollAffordance(preview);
    }
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

  // Exposed for the sibling authoring modules (filltable_editor.js,
  // switchgrid_editor.js) that need to bring a validation message into view. They must
  // NOT reach for scrollIntoView for the reason above — it scrolls every scrollport up
  // the chain, the page viewport included, and that one is overflow:hidden. Both load
  // before editor.js but only call this from a submit handler, so it is always defined
  // by then; they still guard, so a missing helper degrades to "no scroll", never a
  // TypeError that would swallow their validation.
  window.libliAlignTopInPane = alignTopInPane;

  // --- Reveal a nested target's hiding ancestors ---------------------------------
  // Collection runs OUTWARD (target -> [data-scope="preview"]); reveal runs INWARD
  // (outermost first). Order is load-bearing, not cosmetic: select() calls
  // scrollIntoStrip(), which reads offsetLeft/offsetWidth/scrollLeft/clientWidth --
  // all zero while an outer ancestor is still display:none, leaving an inner strip
  // permanently mis-scrolled. The carousel's measure() reads geometry the same way.
  //
  // tabs.js's ownSections()/ownPart() and beforeafter.js's ownPanels()/ownToggle()
  // are closure-local and NOT exported, so this reimplements the predicate rather
  // than refactoring their exports. Ownership, not containment: a tabs element may
  // legally contain another (the depth-3 lift), and a descendant-wide lookup from
  // the outer container grabs the INNER instance's controls -- activating one hides
  // the outer panel that contains it and the element goes blank (tabs.js:33-43).
  function ownNodes(container, selector, ownerSelector) {
    var out = [];
    var all = container.querySelectorAll(selector);
    for (var i = 0; i < all.length; i++) {
      if (all[i].closest(ownerSelector) === container) out.push(all[i]);
    }
    return out;
  }

  // `s` is a FILTER over C's OWNED nodes -- never closest() from the target (which
  // returns the INNERMOST section for every ancestor in a stacked chain, so an outer
  // container indexes a section it does not own and reveals the wrong slide), and
  // never the child the climb passed through (that is .tabs__stage / .ba__panels --
  // neither a section nor a panel, no id, indexOf -> -1).
  function owningNode(container, selector, ownerSelector, target) {
    var owned = ownNodes(container, selector, ownerSelector);
    for (var i = 0; i < owned.length; i++) {
      if (owned[i].contains(target)) return { node: owned[i], all: owned };
    }
    return null;
  }

  function revealAncestors(target) {
    var stop = target.closest('[data-scope="preview"]');
    if (!stop) return;  // defensive; unobservable on today's page (see the spec)
    var chain = [];
    var node = target.parentElement;
    while (node && node !== stop) {
      if (node.tagName === "DETAILS") {
        if (!node.open) chain.push({ kind: "details", c: node });
      } else if (node.hasAttribute("data-tabs")) {
        // Collected UNCONDITIONALLY: select()/show() early-return on i === active,
        // so pre-checking would only risk skipping. "Hidden" is NOT decidable by the
        // [hidden] attribute here -- a carousel conceals by class/opacity/inert.
        var t = owningNode(node, ".tabs__section", "[data-tabs]", target);
        if (t) chain.push({ kind: "tabs", c: node, s: t.node, all: t.all });
      } else if (node.hasAttribute("data-beforeafter")) {
        var b = owningNode(node, ".ba__panel", "[data-beforeafter]", target);
        if (b && b.node.hasAttribute("hidden")) {
          chain.push({ kind: "ba", c: node });
        }
      }
      node = node.parentElement;
    }
    for (var k = chain.length - 1; k >= 0; k--) revealOne(chain[k]);  // outermost first
  }

  // Each step calls the element's own .click() -- a real DOM click, dispatching the
  // listener SYNCHRONOUSLY, so the step completes before the next ancestor inward is
  // measured. A missing control is SKIPPED, never thrown on: a throw would abort the
  // whole click handler and lose the scroll part 1 already earned.
  function revealOne(hit) {
    if (hit.kind === "details") {
      hit.c.open = true;
      // A <details> dispatches nothing of its own -- tabs.js's ResizeObserver is the
      // only other rescue. Dispatching here gives a nested carousel's scheduleMeasure
      // the signal it would otherwise miss.
      hit.c.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      return;
    }
    if (hit.kind === "ba") {
      var toggle = ownNodes(hit.c, ".ba__toggle", "[data-beforeafter]")[0];
      if (toggle) toggle.click();
      return;
    }
    // Branch on the CONTAINER's data-display, exact "carousel" match, mirroring
    // tabs.js:83 (null / "" / a stale fragment / a future third mode all fall through
    // to the strip). Keying on [data-tab-panel] instead would match a carousel
    // target, find no button, hit the skip above, and silently never reach the
    // carousel branch -- while looking like correct defensive code.
    if (hit.c.getAttribute("data-display") === "carousel") {
      // Dots are index-keyed with NO id, and are positionally 1:1 with
      // ownSections(container) (initCarousel builds them as sections.map(...)).
      // Nothing in tabs.js names or pins that invariant, so this depends on it
      // explicitly -- and derives the dot list with the SAME ownership filter used
      // for the sections, never a separate query.
      var dots = ownNodes(hit.c, ".tabs__dot", "[data-tabs]");
      var dot = dots[hit.all.indexOf(hit.s)];
      if (dot) dot.click();
      return;
    }
    // .tabs__section carries no id; the id [aria-controls] needs is on its panel.
    var panel = ownNodes(hit.s, "[data-tab-panel]", ".tabs__section")[0];
    if (!panel || !panel.id) return;
    // Document-rooted is safe: panel ids are namespaced by the join-row pk.
    var btn = document.querySelector('[aria-controls="' + panel.id + '"]');
    if (btn) btn.click();
  }

  // Align the selected element to the top of the preview. The rebuilt preview grows AFTER
  // layout (sandboxed HTML iframes, images, KaTeX), so align now for feedback, then re-align
  // as that async content loads and once more shortly after.
  function scrollPreviewTo(id) {
    if (!id) return;
    var sel = '.prev-el[data-element-id="' + id + '"]';
    var target = root.querySelector(sel);
    if (!target) return;  // absent (failed/empty swap or deleted) -> no-op
    // SYNCHRONOUS, after the absent-target guard and BEFORE the rAF below: revealing
    // inside that callback would measure the pre-reveal layout on the first pass and
    // leave the smooth scroll animating toward a stale position.
    revealAncestors(target);
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
    // getAttribute, NOT `form.action`: HTMLFormElement's named-property getter is
    // [LegacyOverrideBuiltIns], so a control NAMED "action" shadows the action-URL
    // property and `form.action` returns that input element. The clipboard's select
    // and cancel forms both carry <input name="action" value="select|cancel">, so
    // fetch() received the string "[object HTMLInputElement]", resolved it against
    // the editor URL and 404'd -- selecting an element did nothing in a real browser
    // while every server-side test stayed green. `|| location.href` mirrors HTML's
    // own default for an absent action (every data-op form has one today).
    return fetch(form.getAttribute("action") || location.href, {
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
      // Attribute, not property — same shadowing trap as post() above. No question
      // form carries a control named "action" today, so this is prophylactic; it is
      // also what lets the invariant be a simple blanket rule for this file.
      fetch(tryForm.getAttribute("action") || location.href, {
        method: "POST",
        headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: body,
      }).then(function (r) { return r.text(); }).then(function (html) {
        var slot = null;
        if (tryForm.hasAttribute("data-question-inline")) {
          // Choice preview (LESSON and QUIZ both): the response is the full element,
          // because this type's feedback is marked ON its options list, outside the
          // feedback box. Swap the live form's body — not the form — so the delegated
          // handler and the form node survive, then re-render math against the live
          // form (the pre-fetch slot is detached by the assignment).
          //
          // Do NOT return here. The quiz branch still needs the attempt counter and
          // the terminal-state freeze below, and those read the POST-swap slot; this
          // used to early-return, which was safe only while element_try's quiz branch
          // answered with a form-LESS fragment. A response with no <form> (a lesson
          // non-choice type, or a defensive miss) falls through to the plain swap.
          var doc = new DOMParser().parseFromString(html, "text/html");
          var newForm = doc.querySelector("form");
          if (newForm) {
            tryForm.innerHTML = newForm.innerHTML;
            if (window.libliRenderMath) window.libliRenderMath(tryForm);
            renderPreviewMath(tryForm);
            slot = tryForm.querySelector("[data-question-feedback]");
          }
        }
        if (!slot) {
          slot = tryForm.querySelector("[data-question-feedback]");
          if (!slot) return;
          slot.innerHTML = html;
          if (window.libliRenderMath) window.libliRenderMath(slot);
          renderPreviewMath(slot);  // inline math in revealed answers / explanation
        }
        if (!qEl) return;
        // An empty-answer validation doesn't consume an attempt; everything else does.
        if (!slot.querySelector(".is-validation")) {
          qEl.setAttribute("data-attempts-made", String(made + 1));
        }
        // Terminal quiz state (correct / out of attempts / [N]/[R]) -> freeze inputs,
        // mirroring the student quiz lock.
        if (slot.querySelector("[data-quiz-locked]")) {
          // Same three shapes as quiz.js's freeze; kept in lockstep deliberately.
          // The [type=submit] qualifier stays: this root is the whole [data-question]
          // element, not the form, so bare `button` could reach controls the quiz
          // freeze never touches.
          qEl
            .querySelectorAll("input, button[type=submit], select, textarea, fieldset")
            .forEach(function (n) {
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
    if (addChoice) { addChoiceRow(addChoice); return; }
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
  // Called with the clicked [data-choice-add] button so the wrapper is in hand;
  // resolving it from `root` would reintroduce the cross-talk closest() prevents.
  function addChoiceRow(btn) {
    var wrap = btn.closest("[data-fsrows]");
    if (!wrap) return;
    var list = wrap.querySelector("[data-fsrows-list]");
    // Read the prefix from the attribute, as module 1's totalInput() does —
    // hardcoding "choices" re-creates the drift hazard data-fsrows exists to remove.
    var total = wrap.querySelector(
      'input[name="' + wrap.getAttribute("data-fsrows") + '-TOTAL_FORMS"]'
    );
    if (!list || !total) return;
    var rows = list.querySelectorAll("[data-choice-row]");
    // Clone the last NON-HIDDEN row: cloning a removed one yields a new row the
    // author cannot see while TOTAL_FORMS still increments.
    var last = null;
    for (var i = rows.length - 1; i >= 0; i--) {
      if (!rows[i].hidden) { last = rows[i]; break; }
    }
    if (!last) {
      // Unreachable while init job 2's minimum floor holds; loud so a regression
      // of that floor shows up as a message rather than a mute button.
      if (window.console) console.warn("addChoiceRow: no visible row to clone");
      return;
    }
    var idx = parseInt(total.value, 10);
    var clone = last.cloneNode(true);
    // BOTH existing loops, unchanged and in order — reproduced in full rather than
    // described, because losing the second one ships clones carrying the source
    // row's option text, feedback textarea and is_correct state, and losing the
    // first produces duplicate choices-N-* names that silently corrupt the POST.
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
    clone.hidden = false;
    var del = clone.querySelector('[name$="-DELETE"]');
    if (del) del.checked = false;
    var rm = clone.querySelector("[data-fsrow-remove]");
    if (rm) rm.disabled = false;      // cloneNode(true) copies `disabled`
    list.appendChild(clone);
    total.value = idx + 1;
    syncChoiceFeedback(list);  // a fresh row is a distractor until ticked Correct
    if (window.libliInitFormsetRows) window.libliInitFormsetRows(wrap);
  }

  // Adaptive feedback placeholder: the per-option feedback prompt reflects whether the
  // option is currently marked Correct — teaching that feedback shows for BOTH a missed
  // correct answer and a wrongly-picked distractor. Placeholder-only, so the field works
  // identically without JS.
  function syncChoiceFeedback(scope) {
    scope = scope || root;
    // Accept either an ancestor (root / editor pane) or a [data-choice-rows] group
    // passed directly — querySelectorAll only finds DESCENDANTS, so a group handed to
    // us as `scope` would otherwise match nothing.
    var groups = scope.matches && scope.matches("[data-choice-rows]")
      ? [scope]
      : scope.querySelectorAll("[data-choice-rows]");
    Array.prototype.forEach.call(
      groups,
      function (group) {
        var ok = group.getAttribute("data-fb-correct") || "";
        var bad = group.getAttribute("data-fb-distractor") || "";
        Array.prototype.forEach.call(
          group.querySelectorAll("[data-choice-row]"),
          function (row) {
            var toggle = row.querySelector("[data-choice-correct]");
            var box = row.querySelector('textarea[name$="-feedback"]');
            if (box) box.setAttribute("placeholder", toggle && toggle.checked ? ok : bad);
          }
        );
      }
    );
  }

  root.addEventListener("change", function (e) {
    // Single-choice correct-markers render as radios but each formset row has a DISTINCT
    // name, so the browser does not group them — enforce "only one" here.
    var correct = e.target.closest("[data-choice-correct]");
    if (correct) {
      if (correct.type === "radio" && correct.checked) {
        var group = correct.closest("[data-choice-rows]");
        if (group) {
          Array.prototype.forEach.call(group.querySelectorAll("[data-choice-correct]"), function (r) {
            if (r !== correct && r.type === "radio") r.checked = false;
          });
        }
      }
      // Re-prompt the whole group: a radio flip also demotes the previous correct row.
      syncChoiceFeedback(correct.closest("[data-choice-rows]"));
      return;
    }
    var preset = e.target.closest("[data-size-preset]");
    if (preset) {
      // Live size preview with no save. classList.remove/add on just the
      // el--image--* token, never className assignment, so the swap cannot
      // clobber another class the figure carries now or later.
      var fig = document.querySelector(
        '.el--image[data-preview-el="' + preset.dataset.forElement + '"]'
      );
      if (fig) {
        fig.classList.remove(
          "el--image--small", "el--image--medium", "el--image--large", "el--image--full"
        );
        fig.classList.add("el--image--" + preset.value);
      }
      // On the CREATE flow data-for-element is "" (Task 2's template applies
      // |default_if_none:'' — without it Django would render the string "None")
      // and no figure exists yet, so the querySelector finds nothing and this is
      // inertly a no-op until first save. That is correct behaviour.
    }
  });

  function flash(msg) {
    var bar = document.createElement("div"); bar.className = "op-error"; bar.textContent = msg;
    root.prepend(bar); setTimeout(function () { bar.remove(); }, 6000);
  }

  function bindDnD() { if (window.__libliEditorDnD) window.__libliEditorDnD(root); }
  bindDnD();
  bindHover();

  // Persist a slot's open/closed state whenever the author toggles it. `toggle` does NOT
  // bubble, so listen in the CAPTURE phase (which still sees non-bubbling descendant
  // events) rather than by delegation.
  root.addEventListener("toggle", function (e) {
    if (e.target.matches && e.target.matches(SLOT_DETAILS)) saveSlot(e.target);
  }, true);
  applyStoredSlots(root);  // restore on initial page load (a refresh loses in-memory state)

  // Initial inline-math pass over the preview present at page load (auto-render.min.js
  // loads deferred, so guard via the typeof check inside renderPreviewMath).
  var initPreview = root.querySelector('[data-scope="preview"]');
  if (initPreview) renderPreviewMath(initPreview);
  syncChoiceFeedback(root);  // adaptive per-option feedback prompts on first paint

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

  // --- 3-way view toggle (Editor / Split / Preview) ---
  // The toggle lives in editor.html OUTSIDE the swapped [data-scope] panes, and
  // .editor-grid is never swapped by applyFragments — so these references and the
  // mode class both survive fragment updates. The enhancer TRUSTS the pre-paint DOM
  // on init (it does not re-read localStorage); it only reveals the control and wires
  // clicks. Validation on the write path keeps localStorage to the three known values.
  (function initViewToggle() {
    var toggle = root.querySelector(".view-toggle");
    var group = root.querySelector("[data-view-toggle]");
    var grid = root.querySelector(".editor-grid");
    if (!toggle || !group || !grid) return;
    var MODES = ["editor", "split", "preview"];
    function setMode(v) {
      if (MODES.indexOf(v) === -1) v = "split";
      MODES.forEach(function (m) { grid.classList.remove("is-mode-" + m); });
      grid.classList.add("is-mode-" + v);
      group.querySelectorAll("[data-view]").forEach(function (b) {
        var on = b.getAttribute("data-view") === v;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      try { localStorage.setItem("libli-editor-view", v); } catch (e) { /* in-session only */ }
    }
    group.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-view]");
      if (!btn || !group.contains(btn)) return;
      setMode(btn.getAttribute("data-view"));
    });
    toggle.hidden = false;  // reveal now that clicks are wired
  })();
})();
