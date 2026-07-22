(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var root = document.querySelector(".builder");
  var panel = root && root.querySelector("[data-panel]");
  if (!root || !panel) return;
  // The panel's neutral state == its server-rendered content at load (the course panel).
  // Restored after a Move so reordering by Move, arrows, and drag all leave the panel
  // unchanged rather than Move alone forcing the moved node's details into view.
  var neutralPanel = panel.innerHTML;

  // Single writer for panel content. The panel is a scroll container (builder.css), so
  // every swap must reset scrollTop or the next node's panel opens mid-way down. Nine
  // call sites funnel through here; tests/test_builder_js_invariants.py enforces it.
  function setPanel(html) {
    panel.innerHTML = html;
    panel.scrollTop = 0;
  }

  // ---- Move-picker state (declared early so the submit handler can call clearMoving) ----
  var movingPk = null;
  function clearMoving() {
    if (movingPk == null) return;
    var r = root.querySelector('[data-node="' + movingPk + '"]');
    if (r) r.classList.remove("moving");
    movingPk = null;
  }
  function escHtml(s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; }
  function renderSlots(kidsOl, nodePk, rawPos) {
    if (!kidsOl) return;
    kidsOl.hidden = false;
    // Cache the pristine children markup on first render so re-selecting a destination
    // re-reads the real children (<li data-child-pk>), not the slot/anchor <li>s we inject below.
    if (kidsOl.dataset.childrenSrc === undefined) kidsOl.dataset.childrenSrc = kidsOl.innerHTML;
    var src = document.createElement("ol");
    src.innerHTML = kidsOl.dataset.childrenSrc;
    // children excluding the moving node => "others"; slots are insert-before indices 0..N
    var others = Array.prototype.slice.call(src.querySelectorAll("li[data-child-pk]"))
      .filter(function (li) { return li.getAttribute("data-child-pk") !== String(nodePk); });
    var frag = "";
    function slotHtml(i) { return '<li class="move-slot" data-move-slot="' + i + '">'
      + '<span class="move-slot__mark"></span></li>'; }
    frag += slotHtml(0);
    others.forEach(function (li, i) { frag += '<li class="move-anchor">' + escHtml(li.textContent) + '</li>' + slotHtml(i + 1); });
    kidsOl.innerHTML = frag;
    rawPos.value = "";   // until a slot is chosen, empty => append
  }
  function initPicker(nodePk) {
    var form = panel.querySelector("form.move-picker");
    if (!form) return;
    clearMoving();
    movingPk = nodePk;
    var row = root.querySelector('[data-node="' + nodePk + '"]');
    if (row) row.classList.add("moving");
    form.querySelectorAll(".move-picker__raw").forEach(function (n){ n.hidden = true; });
    var tree = form.querySelector("[data-move-tree]");
    if (tree) tree.hidden = false;
    var rawSelect = form.querySelector("select[name='new_parent']");
    var rawPos = form.querySelector("input[name='position']");
    tree.addEventListener("click", function (e) {
      var dest = e.target.closest(".move-dest");
      if (dest) {
        tree.querySelectorAll(".move-dest").forEach(function(d){ d.classList.remove("sel"); });
        tree.querySelectorAll(".move-dest-children").forEach(function(o){ o.hidden = true; });
        dest.classList.add("sel");
        rawSelect.value = dest.getAttribute("data-dest");            // syncs parent_token source
        var kids = dest.getAttribute("data-dest") === "top"
          ? tree.querySelector('[data-children-for="top"]')          // top owns its own <ol>
          : dest.parentElement.querySelector(".move-dest-children");  // candidate's sibling <ol>
        renderSlots(kids, nodePk, rawPos);
        return;
      }
      var slot = e.target.closest("[data-move-slot]");
      if (slot) {
        tree.querySelectorAll("[data-move-slot]").forEach(function(s){ s.classList.remove("sel"); });
        slot.classList.add("sel");
        rawPos.value = slot.getAttribute("data-move-slot");
      }
    });
  }
  // Escape clears the moving highlight when the picker is open.
  root.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && panel.querySelector("form.move-picker")) clearMoving();
  });
  // ---- end Move-picker state ----

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

  function notice(text) {
    var bar = document.createElement("div");
    bar.className = "op-error";
    bar.textContent = text;
    panel.prepend(bar);
    setTimeout(function () { bar.remove(); }, 6000);
  }
  function msg(key, fallback) { return root.getAttribute("data-msg-" + key) || fallback; }

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
          if (r.status === 409) notice(msg("conflict", "This changed elsewhere — reloaded to the latest."));
          // Only the Move picker remains as a panel form with data-op; it resets the
          // panel to neutral. (The panel's rename form is gone, so the re-token helper
          // that existed solely to refresh it was deleted along with it.)
          if (inPanel) setPanel(neutralPanel);
          clearMoving();
        } else if (r.status === 422) {
          var tmp = document.createElement("div");
          tmp.innerHTML = text.trim();
          notice(tmp.textContent.trim());
        }
        delete form.dataset.submitting;
        var ti = form.querySelector("input.tree__title");
        if (ti) ti.readOnly = false;
      });
    }).catch(function () {
      notice(msg("network", "Network error — please try again."));
      delete form.dataset.submitting;
      var ti = form.querySelector("input.tree__title");
      if (ti) ti.readOnly = false;
    });
  });

  // Node selection -> load the detail panel fragment.
  root.addEventListener("click", function (e) {
    // Move… links open their picker inline (fetch GET).
    var mv = e.target.closest("[data-move]");
    if (mv) {
      e.preventDefault();
      fetch(mv.getAttribute("href"), { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          setPanel(html);
          initPicker(parseInt(mv.getAttribute("data-move"), 10));
        })
        .catch(function () { setPanel('<div class="op-error" role="alert">Network error — please reload.</div>'); });
      return;
    }
  });

  // ---- Inline rename: selection ------------------------------------------------
  // Selection moved from click to focusin: preventDefault() on a click into a text
  // input suppresses caret placement, so the click branch was removed outright.
  var panelReq = 0;        // last-request-wins id, allocated when a fetch is ISSUED
  var panelTimer = null;   // pending keyboard-debounce timer
  var pointerFocus = false;

  // pointerdown is scoped to the tree; the RELEASE listeners are on document, because a
  // pointerup landing outside .builder (drag-select out of the pane, release over
  // browser chrome, an HTML5 drag started from .ica--grip) would otherwise latch
  // pointerFocus true -- and the next KEYBOARD Tab would then fetch immediately,
  // silently defeating the debounce.
  root.addEventListener("pointerdown", function () { pointerFocus = true; });
  document.addEventListener("pointerup", function () { pointerFocus = false; });
  document.addEventListener("pointercancel", function () { pointerFocus = false; });

  function loadPanel(url) {
    var id = ++panelReq;
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.text(); })
      .then(function (html) { if (id === panelReq) setPanel(html); })
      .catch(function () {
        // The id check gates this branch too: an ungated slow FAILURE from an earlier
        // row would otherwise replace a later row's loaded panel with an error box.
        if (id === panelReq) {
          setPanel('<div class="op-error" role="alert">Network error — please reload.</div>');
        }
      });
  }

  root.addEventListener("focusin", function (e) {
    // Mark consumption and timer clearing run for EVERY focusin, whatever the target,
    // BEFORE the .tree__title test. Tab goes title -> ~6 cluster controls -> next
    // title, and those stops can span more than 150ms; if only titles cleared the
    // timer, row A's fetch would fire while the author was still inside A's cluster.
    var byPointer = pointerFocus;
    pointerFocus = false;
    if (panelTimer) { clearTimeout(panelTimer); panelTimer = null; }
    var t = e.target.closest(".tree__title");
    if (!t) return;
    var url = t.getAttribute("data-panel-url");
    if (!url) return;
    clearMoving();
    // A deliberate click must not gain 150ms of latency; only keyboard traversal is
    // debounced, so tabbing across ten rows issues one fetch rather than ten.
    if (byPointer) loadPanel(url);
    else panelTimer = setTimeout(function () { panelTimer = null; loadPanel(url); }, 150);
  });

  // Focus leaving the builder entirely fires no further focusin on root, so a pending
  // timer would still elapse and swap the panel for a row the author has left.
  root.addEventListener("focusout", function (e) {
    if (panelTimer && (!e.relatedTarget || !root.contains(e.relatedTarget))) {
      clearTimeout(panelTimer);
      panelTimer = null;
    }
  });

  // ---- Inline rename: commit ---------------------------------------------------
  function titleForm(input) { return input.closest("form.tree__rename"); }

  // Programmatic value assignment fires NO input event, so the tooltip must be synced
  // by hand here or it keeps showing abandoned text -- exactly on the truncated long
  // titles where the tooltip is the only way to read the name.
  function revert(input) {
    input.value = input.defaultValue;
    input.title = input.value;
  }

  function commitRename(input) {
    var form = titleForm(input);
    if (!form || form.dataset.submitting) return;
    var trimmed = input.value.trim();
    // Compare trimmed against trimmed: a legacy row whose stored title has stray
    // whitespace would otherwise post a rename on a bare focus-and-blur.
    if (trimmed === input.defaultValue.trim()) return;
    // Write the trim back -- FormData reads the LIVE value, so trimming into a local
    // would leave the untrimmed string in the POST body. GUARDED, because the HTML
    // value setter jumps the caret to the end and drops the selection even when
    // assigning an identical string; an unconditional write here would destroy the
    // mid-string caret before the POST is even issued.
    if (input.value !== trimmed) input.value = trimmed;
    input.title = input.value;
    if (!form.reportValidity()) return;   // native bubble; no state set, so no wedge
    form.dataset.submitting = "1";
    input.readOnly = true;           // AFTER validity: readonly is barred from it
    form.requestSubmit();
  }

  root.addEventListener("keydown", function (e) {
    var input = e.target.closest("input.tree__title");
    if (!input) return;
    if (e.key === "Enter") {
      // Unconditional, before any check: a text input in a form with a submit button
      // implicitly submits on Enter, which would post even an unchanged title and
      // would double-post alongside requestSubmit().
      e.preventDefault();
      if (titleForm(input).dataset.submitting) return;
      commitRename(input);
    } else if (e.key === "Escape") {
      e.preventDefault();
      if (titleForm(input).dataset.submitting) return;
      // Revert WITHOUT blurring: dropping focus to <body> would force someone who
      // abandoned an edit 300 rows down to Tab from the top of the document again.
      revert(input);
    }
  });

  root.addEventListener("focusout", function (e) {
    var input = e.target.closest("input.tree__title");
    if (!input) return;
    var form = titleForm(input);
    if (!form) return;
    // 1. A commit is already in flight. Nothing is lost -- readOnly means the field
    //    cannot have changed since the POST.
    if (form.dataset.submitting) return;
    // 2. The WINDOW lost focus, not the field. Chromium fires focusout when the tab
    //    or window is deactivated; committing here would persist half-typed text.
    if (e.relatedTarget === null && !document.hasFocus()) return;
    // 3. The form was detached by another op's applyFragment; committing would post a
    //    token that swap already superseded (cf. the add flow's isConnected guard).
    if (!form.isConnected) return;
    // 4. Emptied field = cancel. This MUST precede the dirty check inside
    //    commitRename: an emptied field IS dirty, so we would otherwise post "" and
    //    surface a 422 on an ambiguous gesture. Enter deliberately does not share
    //    this branch -- it relies on required + reportValidity's native bubble.
    if (!input.value.trim()) { revert(input); return; }
    commitRename(input);
  });

  // Keep the tooltip honest while typing. Delegated like every other handler here,
  // because applyFragment replaces whole scopes on other ops.
  root.addEventListener("input", function (e) {
    var input = e.target.closest("input.tree__title");
    if (input) input.title = input.value;
  });

  // --- WS2 drag-and-drop ----------------------------------------------------
  var RANK = { part: 0, chapter: 1, section: 2, unit: 3 };
  var drag = null;  // { pk, kind, token }
  root.addEventListener("dragstart", function (e) {
    var grip = e.target.closest(".ica--grip");
    if (!grip) return;
    var row = grip.closest(".tree__row");
    drag = { pk: row.getAttribute("data-node"), kind: row.getAttribute("data-kind"),
             token: row.getAttribute("data-updated") };
    e.dataTransfer.effectAllowed = "move";
  });
  function targetFor(y, scope) {
    // scope = the <ol data-scope>; rows = its direct .tree__row children excluding the dragged one
    var rows = Array.prototype.slice.call(scope.children)
      .filter(function (li) { return li.classList.contains("tree__row")
        && li.getAttribute("data-node") !== drag.pk; });
    var i = 0;
    for (; i < rows.length; i++) {
      var r = rows[i].getBoundingClientRect();
      if (y < r.top + r.height / 2) break;
    }
    return { index: i, before: rows[i] || null };   // insert-before index
  }
  function legal(parentKind) {
    return RANK[drag.kind] > (parentKind == null ? -1 : RANK[parentKind]);
  }
  function clearDropMarks() {
    root.querySelectorAll(".drop-target").forEach(function (n){ n.classList.remove("drop-target"); });
    root.querySelectorAll(".drop-line").forEach(function (n){ n.remove(); });
  }
  root.addEventListener("dragover", function (e) {
    if (!drag) return;
    // Determine the most-specific valid drop scope.
    // If the pointer is over a row that owns a direct child scope (i.e. a container node),
    // prefer that child scope over the ancestor scope the row itself lives in.
    // This avoids accidentally targeting the parent scope when hovering over a section header.
    var scope;
    var targetRow = e.target.closest(".tree__row");
    if (targetRow) {
      // Check if we are hovering over the row's own content (header area) vs. inside its child scope.
      var childScope = targetRow.querySelector(":scope > .tree__scope");
      if (childScope && !childScope.contains(e.target)) {
        // Pointer is in the row header — treat the child scope as the target.
        scope = childScope;
      }
    }
    if (!scope) scope = e.target.closest(".tree__scope");
    if (!scope) return;
    var destPk = scope.getAttribute("data-scope");          // "top" or pk
    var destRow = scope.closest(".tree__row");               // the container row (null for top)
    var parentKind = destRow ? destRow.getAttribute("data-kind") : null;
    // forbid dropping into self/descendant: scope must not be inside the dragged row
    var draggedRow = root.querySelector('.tree__row[data-node="' + drag.pk + '"]');
    if (!legal(parentKind) || (draggedRow && draggedRow.contains(scope))) { clearDropMarks(); drag.targetScope = null; return; }
    e.preventDefault();
    clearDropMarks();
    scope.classList.add("drop-target");
    var t = targetFor(e.clientY, scope);
    var line = document.createElement("li");
    line.className = "drop-line";
    if (t.before) scope.insertBefore(line, t.before); else scope.appendChild(line);
    scope.dataset.dropIndex = t.index;
    scope.dataset.dropParent = destPk;
    scope.dataset.dropToken = scope.getAttribute("data-updated");
    drag.targetScope = scope;
  });
  root.addEventListener("drop", function (e) {
    if (!drag) return;
    var scope = drag.targetScope;
    if (!scope || !scope.classList.contains("drop-target")) { clearDropMarks(); drag = null; return; }
    e.preventDefault();
    var body = new FormData();
    body.append("mode", "reparent");
    body.append("node", drag.pk);
    body.append("node_token", drag.token);
    body.append("new_parent", scope.dataset.dropParent);
    body.append("position", scope.dataset.dropIndex);
    body.append("parent_token", scope.dataset.dropToken);
    clearDropMarks(); drag = null; clearMoving();
    fetch(root.getAttribute("data-node-move-url"), {
      method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: body,
    }).then(function (r) { return r.text().then(function (text) {
      if (r.status === 200 || r.status === 409) {
        applyFragment(text);
        if (r.status === 409) notice(msg("conflict", "This changed elsewhere — reloaded to the latest."));
        // A drag bypasses the submit handler's panel-refresh. If the panel holds a token-bearing
        // form (e.g. the dragged node's Move picker / rename), it is now stale — clear it so
        // reusing it can't spuriously 409.
        if (panel.querySelector("form[data-op]")) setPanel("");
      } else if (r.status === 422) { notice(msg("illegal", "That move isn't allowed here.")); }
    }); }).catch(function () { notice(msg("network", "Network error — please try again.")); });
  });
  root.addEventListener("dragend", function () { clearDropMarks(); drag = null; pointerFocus = false; });
  // --- end WS2 drag-and-drop ------------------------------------------------

  // Reveal the unit_type select only when kind === 'unit' on add forms.
  // (This listener targets [data-kind-select] which no longer exists in the new
  // _add_affordance.html — it is left as a harmless no-op for backwards safety.)
  root.addEventListener("change", function (e) {
    if (!e.target.matches("[data-kind-select]")) return;
    var form = e.target.closest("form");
    var ut = form.querySelector("[data-unit-type]");
    if (ut) ut.hidden = e.target.value !== "unit";
  });

  // --- WS2 inline "+" add ---------------------------------------------------
  function closeAdd(form) {
    if (!form) return;
    form.classList.remove("is-adding");
    var t = form.querySelector("[data-add-title]");
    if (t) t.value = "";
    delete form.dataset.pendingKind;
    delete form.dataset.submitting;
  }
  function openAdd(form, kind) {
    // one open row at a time: commit/cancel any other open row first
    root.querySelectorAll("form.tree__add.is-adding").forEach(function (f) {
      if (f !== form) commitOrCancel(f);
    });
    form.dataset.pendingKind = kind;
    form.classList.add("is-adding");
    var t = form.querySelector("[data-add-title]");
    if (t) { t.focus(); }
  }
  function commitOrCancel(form) {
    if (form.dataset.submitting) return;        // a commit is already in flight
    var t = form.querySelector("[data-add-title]");
    if (t && t.value.trim()) {
      form.dataset.submitting = "1";
      var kind = form.dataset.pendingKind;
      var btn = form.querySelector('button[data-add-kind="' + kind + '"]');
      form.requestSubmit(btn);   // -> existing submit handler posts node_add
    } else {
      closeAdd(form);
    }
  }
  root.addEventListener("click", function (e) {
    var more = e.target.closest("[data-add-more]");
    if (more) { e.preventDefault(); more.closest(".tree__add").classList.toggle("show-overflow"); return; }
    var chip = e.target.closest("button[data-add-kind]");
    if (chip) {
      var form = chip.closest("form.tree__add");
      if (form.classList.contains("is-adding") && form.dataset.pendingKind === chip.value) {
        e.preventDefault();            // prevent native submit (commitOrCancel fires requestSubmit)
        commitOrCancel(form);          // second click on the active kind = commit
      } else {
        e.preventDefault();            // first click = open inline row, don't submit
        openAdd(form, chip.value);
      }
    }
  });
  root.addEventListener("keydown", function (e) {
    var t = e.target.closest("[data-add-title]");
    if (!t) return;
    if (e.key === "Enter") { e.preventDefault(); commitOrCancel(t.closest("form.tree__add")); }
    if (e.key === "Escape") { e.preventDefault(); closeAdd(t.closest("form.tree__add")); }
  });
  root.addEventListener("focusout", function (e) {
    var t = e.target.closest("[data-add-title]");
    if (!t) return;
    var form = t.closest("form.tree__add");
    // let a click on the same form's button win before blur closes it
    setTimeout(function () { if (form.isConnected && !form.contains(document.activeElement)) commitOrCancel(form); }, 120);
  });
})();
