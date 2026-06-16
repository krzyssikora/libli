(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var root = document.querySelector(".builder");
  var panel = root && root.querySelector("[data-panel]");
  if (!root || !panel) return;

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
          clearMoving();
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
      clearMoving();
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
        .then(function (html) {
          panel.innerHTML = html;
          initPicker(parseInt(mv.getAttribute("data-move"), 10));
        })
        .catch(function () { panel.innerHTML = '<div class="op-error" role="alert">Network error — please reload.</div>'; });
      return;
    }
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
        if (r.status === 409) notice("This changed elsewhere — refreshed to the latest.");
        // A drag bypasses the submit handler's panel-refresh. If the panel holds a token-bearing
        // form (e.g. the dragged node's Move picker / rename), it is now stale — clear it so
        // reusing it can't spuriously 409.
        if (panel.querySelector("form[data-op]")) panel.innerHTML = "";
      } else if (r.status === 422) { notice("That move isn't allowed here."); }
    }); }).catch(function () { notice("Network error — please try again."); });
  });
  root.addEventListener("dragend", function () { clearDropMarks(); drag = null; });
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
    var t = form.querySelector("[data-add-title]");
    if (t && t.value.trim()) {
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
