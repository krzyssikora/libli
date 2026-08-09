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
  function parseFragment(html) {
    var d = document.createElement("div");
    d.innerHTML = html.trim();
    return d;
  }
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

  // ---- open-set collector + busy counter -------------------------------------
  // The collector observes the DOM, so it can only ever emit an enumeration;
  // `all` originates from the server, never from here.
  function collectOpen() {
    var out = [];
    root.querySelectorAll("ol.tree__scope[data-scope]").forEach(function (ol) {
      var s = ol.getAttribute("data-scope");
      if (s && s !== "top") out.push(s);
    });
    return out.join(",");
  }
  // ---- the applied-q tracker -------------------------------------------------
  // The floor applies in the COMPARISON, never in either value. Storing the
  // effective form makes a ?q=a page send q="" on the first toggle, and
  // syncUrl then strips the `a` from the address bar.
  // TWO values, and conflating them breaks the clear path (spec 5z).
  //   appliedQ  -- what the pane is SHOWING; written when a response lands;
  //                read by the five senders, syncUrl and rewriteBulkHrefs
  //   pendingQ  -- what the latest ISSUED request will apply; written at issue
  //                time; read by the skip-comparison, and only that
  // appliedQ alone is stale during an in-flight filter: type `trygo`, click
  // Clear before it lands, and the clear compares "" against "" (appliedQ has
  // not advanced), returns early, issues NO request and never bumps treeGen --
  // so the filter response lands unopposed and repaints filtered markup over
  // an empty box. The counter cannot save it: the losing path sends nothing.
  var appliedQ = root.getAttribute("data-applied-q") || "";
  var pendingQ = appliedQ;
  var qMin = parseInt(root.getAttribute("data-q-min"), 10) || 2;

  function effectiveQ(s) {
    // Mirrors builder_filter.is_active. NFC, not NFD: measured over all of
    // Unicode, an NFD client measure exceeds the server's fold for 11,371
    // characters (Hangul, Hebrew, Katakana, Arabic, Indic), NFC for 83, and
    // Latin for 0 either way.
    //
    // The explicit class, not trim(): Python's str.strip() takes U+0085 and
    // U+001C-1F, which trim() does not, so "a\u0085" would be 2 to the client
    // and 1 to the server -- the direction that collapses the tree.
    //
    // [...s].length, not .length: .length counts UTF-16 units and Python
    // counts code points, so every astral character measures 2 here and 1
    // there -- the same dangerous direction, for the whole astral plane.
    // Every class member is written as an ESCAPE, never a literal byte:
    // U+001C-001F and U+0085 are invisible in an editor and in a diff, and
    // if one is lost to a paste that normalises whitespace the client floor
    // silently disagrees with str.strip() in the direction that collapses
    // the tree. Same for the combining-mark class.
    var TRIM = /^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$/g;
    var MARKS = /[\u0300-\u036f]/g;
    var t = (s || "").replace(TRIM, "").normalize("NFC").replace(MARKS, "");
    return [...t].length >= qMin ? (s || "").replace(TRIM, "") : "";
  }

  // SET, never append: mutation forms already carry a hidden q, so appending
  // puts two values in the FormData and QueryDict.get returns the LAST -- the
  // collector would win only by accident of ordering.
  function setTreeParams(target, opts) {
    var open = (opts && opts.openOverride !== undefined)
      ? opts.openOverride
      : collectOpen();
    if (target.set) {                       // FormData or URLSearchParams
      target.set("open", open);
      target.set("q", appliedQ);
    } else {                                // a URL
      target.searchParams.set("open", open);
      target.searchParams.set("q", appliedQ);
    }
    return target;
  }
  function withOpen(body) { return setTreeParams(body); }

  function syncUrl() {
    // Present-but-empty, never omitted: dropping the parameter makes the next
    // page GET see `open` as ABSENT and re-seed from the session.
    var u = new URL(window.location.href);
    u.searchParams.set("open", collectOpen());
    // Writes the TRACKER, not "whatever this request sent" -- which is
    // undefined for the clear fetch (sends no q) and for collapse-all (issues
    // no request at all, yet calls this). Deletes only when the tracker is
    // blank, so a below-floor `a` survives in the address bar.
    if (appliedQ) u.searchParams.set("q", appliedQ);
    else u.searchParams.delete("q");
    history.replaceState(null, "", u.toString());
  }

  var busy = 0;
  function busyStart() { busy++; root.setAttribute("data-busy", "1"); }
  function busyEnd() { if (--busy <= 0) { busy = 0; root.removeAttribute("data-busy"); } }

  // Run `fn` once the frame our DOM writes land in has actually been PAINTED.
  //
  // TWO nested rAFs, and one is not enough: a rAF callback runs BEFORE its
  // frame's style/layout/paint, so a single one would fire while the browser
  // still has all that work ahead of it. The second callback runs in the NEXT
  // frame, i.e. after the first frame's paint reached the screen.
  //
  // This exists because busyEnd() was clearing `data-busy` at the end of the
  // JS task, while the browser had not yet laid out or painted a single one of
  // the ~40,000 elements applyFragment had just inserted. Measured on mat-pp:
  // `data-busy` was removed at t=1438 ms and a 491 ms main-thread block STARTED
  // at t=1438 ms. The dim therefore covered the fetch and nothing else -- the
  // author saw an un-dimmed, apparently-finished tree while the main thread was
  // still blocked, and any click they made in that window (Collapse all being
  // the obvious one) sat undispatched until it ended, which reads as a dead
  // button. The work is not made faster here; the indicator is made honest.
  function afterPaint(fn) {
    requestAnimationFrame(function () { requestAnimationFrame(fn); });
  }

  // True only for the synchronous duration of the scope swap in applyFragment. Chromium
  // DOES dispatch focusout for a focused input inside the subtree being removed, and it
  // dispatches it from INSIDE replaceWith() -- at a point where the input and its form
  // still report isConnected === true, relatedTarget is null and document.hasFocus() is
  // true. Every isConnected/hasFocus test therefore reads "attached and focused" and the
  // rename bail-outs let a half-typed title through. This flag is the only signal that
  // distinguishes "the author blurred the field" from "the field was torn out under them".
  var swapping = false;

  // Replace the tree element whose data-scope matches the returned fragment's root.
  function applyFragment(html) {
    var tmp = parseFragment(html);
    var incoming = tmp.firstElementChild;
    if (!incoming) return;
    var scope = incoming.getAttribute("data-scope");
    var existing = root.querySelector('[data-scope="' + scope + '"]');
    if (existing) {
      swapping = true;
      try { existing.replaceWith(incoming); } finally { swapping = false; }
    }
    // No append fallback: the target [data-scope] element is always present after the
    // first render (the tree-pane root for "top", a nested <ol> otherwise). Appending
    // on a missed selector would DUPLICATE the tree, so a miss is intentionally a no-op.
  }

  // A rename changes no structure, so its 200 is applied IN PLACE -- no scope swap,
  // so the focused input, its caret, and document scroll are all untouched.
  function applyRename(form, html) {
    // A foreign applyFragment can land between this POST and its response, replacing
    // the row. The swapped-in markup is already server-rendered, so there is nothing
    // to patch -- and patching would be harmful: that render can PREDATE this commit,
    // so writing our committed title into its defaultValue while leaving the displayed
    // old value alone would leave the row dirty against a stale value, from which the
    // next blur would post the old title back and silently undo the rename.
    if (!form.isConnected) return;
    var data = parseFragment(html).querySelector("[data-rename-for]");
    if (!data) return;                       // unexpected body: silent no-op
    var row = form.closest("li.tree__row");
    if (!row) return;
    var nodePk = row.getAttribute("data-node");
    var token = data.getAttribute("data-updated");
    var title = data.getAttribute("value");

    var input = form.querySelector("input.tree__title");
    if (input) {
      input.value = title;
      input.defaultValue = title;            // makes the field clean again
      input.title = title;
    }

    // Every carrier of this node's `updated`, scoped so descendant rows are untouched.
    var head = row.querySelector(":scope > .tree__rowhead");
    if (head) {
      head.querySelectorAll("input[name=token]").forEach(function (el) {
        el.value = token;                    // rename + reorder + duplicate (units)
      });
    }
    row.setAttribute("data-updated", token); // dragstart reads this as node_token
    var scope = row.querySelector(":scope > ol.tree__scope");
    if (scope) {
      scope.setAttribute("data-updated", token);   // drop target's parent_token
      // Pk-anchored, NOT a descendant query: _add_affordance renders its add row LAST
      // in every scope, so a nested child row's own add form precedes it in document
      // order and a plain querySelector would return a GRANDCHILD's parent_token.
      var add = root.querySelector(
        'form.tree__add[data-add-scope="' + nodePk + '"] input[name=parent_token]'
      );
      if (add) add.value = token;
    }
  }

  function notice(text) {
    var bar = document.createElement("div");
    bar.className = "op-error";
    bar.textContent = text;
    panel.prepend(bar);
    setTimeout(function () { bar.remove(); }, 6000);
  }
  function msg(key, fallback) { return root.getAttribute("data-msg-" + key) || fallback; }

  // Release a form from its in-flight state. Only a rename LOCKS anything, so the
  // op gate spares every add/reorder/duplicate/reparent submission a querySelector
  // that can never match.
  //
  // Takes the RESOLVED op, and touches `submitting` only on the rename arm. Since
  // a row is one shared form (see _tree_node.html), an unconditional
  // `delete form.dataset.submitting` here would let a reorder response clear the
  // flag belonging to a rename still in flight on the SAME form -- and leave the
  // title input readOnly forever, because the reorder arm returns before the
  // unlock. Reorder and duplicate never set the flag in the first place, so
  // skipping them is behaviour-preserving.
  function releaseForm(form, op) {
    if (op !== "rename") return;
    delete form.dataset.submitting;
    var ti = form.querySelector("input.tree__title");
    if (ti) ti.readOnly = false;
  }

  // Intercept any builder form with data-op; POST via fetch and swap the response.
  root.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-op]");
    if (!form) return;
    e.preventDefault();
    // The op and the endpoint come from the BUTTON when it declares them: one row
    // is one form serving rename + reorder + duplicate, and each button carries
    // its own data-op/formaction. The form-level fallback is not a nicety -- it is
    // the rename path, where commitRename() calls requestSubmit() with no argument
    // and `e.submitter` is therefore null.
    //
    // getAttribute("formaction"), never the .formAction PROPERTY: the property
    // reflects the FORM's action when the attribute is absent, so every no-formaction
    // submitter would silently read as "overridden" and the `||` would never fall
    // through.
    var op = (e.submitter && e.submitter.getAttribute("data-op"))
      || form.getAttribute("data-op");
    var action = (e.submitter && e.submitter.getAttribute("formaction")) || form.action;
    var inPanel = panel.contains(form);
    var body = new FormData(form);
    // include the submitter's name/value (e.g. direction=up)
    if (e.submitter && e.submitter.name) body.append(e.submitter.name, e.submitter.value);
    // Enhancement: for the Move picker (reparent), read the selected option's data-updated
    // and append it as parent_token so the server can verify the destination's token.
    // The server treats parent_token as optional (existence-only when absent = no-JS path),
    // so skipping it here is safe — we just add it when available for the stricter JS path.
    if (op === "reparent") {
      var sel = form.querySelector("select[name='new_parent']");
      if (sel) {
        var opt = sel.options[sel.selectedIndex];
        if (opt && opt.getAttribute("data-updated")) {
          body.append("parent_token", opt.getAttribute("data-updated"));
        }
      }
    }

    // Double-submit guard for the flag ops (Task 14): `disabled` for the unit
    // toggle and the strip's own submit buttons; `aria-disabled` alongside,
    // harmless on a button and load-bearing on the confirming anchor's OWN
    // click handler below, which bails on it. SET here, synchronously, at
    // submit time -- never in the response handler, where `text` already
    // exists and the control would sit enabled for the whole in-flight
    // window (no guard at all; that is E2E6's Mutant B, reached from the
    // "set too late" side rather than the "cleared too rarely" side below).
    //
    // `e.submitter` is NULL on the rename path -- commitRename() calls
    // requestSubmit() with no argument, and every other read of it in this
    // file is guarded the same way, with the same reason. An unguarded
    // `control.disabled = true` here throws inside this listener, AFTER
    // preventDefault() already ran, so the fetch never fires and inline
    // rename goes dead on every row in the builder. Guard it, and scope it
    // to the flag ops so no other op's button is touched.
    var control = e.submitter;
    if (control && (op === "flag" || op === "flag-confirm")) {
      control.disabled = true;
      control.setAttribute("aria-disabled", "true");
    }
    // Cleared exactly once, from wherever the in-flight request settles:
    // ordinary success/409/422, a strip response (which does NOT re-render
    // the tree, so the original control survives in the DOM and a clear
    // placed only inside applyFragment never runs for it -- the button
    // would stay dead until a reload), or a network rejection (the second
    // arm of the dispatch below, which never reaches the success `.then`
    // and its `finally` at all). Missing any ONE of the three leaves some
    // control permanently disabled.
    var releaseControl = function () {
      if (control) {
        control.disabled = false;
        control.removeAttribute("aria-disabled");
      }
    };

    busyStart();
    var finish = function () { busyEnd(); };
    fetch(action, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
      body: withOpen(body),
    }).then(function (r) {
      return r.text().then(function (text) {
        applyInfo(r);          // FIRST, on every arm. A rename 200 and a 422
                               // carry no header, so this is a no-op there --
                               // by construction, not by a call-site list.
        try {
          if (r.status === 200 || r.status === 409) {
            // A rename's 200 is patched in place; its 409 deliberately still goes through
            // applyFragment -- there the tree genuinely diverged and _conflict_scope must
            // be applied, or the stale row is never reloaded.
            if (r.status === 200 && op === "rename") {
              applyRename(form, text);
            } else {
              var incoming = parseFragment(text).firstElementChild;
              if (incoming && incoming.matches("[data-flag-strip]")) {
                // The server is asking, not answering: a confirmation is
                // still needed (a stale page, or a click that raced the
                // node's own first write landing elsewhere). This root
                // carries no data-scope, so applyFragment would silently
                // no-op on it -- branch before calling it.
                insertStripAfterRowhead(incoming, control || form);
                focusInto(incoming);
                return;   // no tree re-render on this arm; releaseControl()
                          // below still runs, via the `finally`.
              }
              applyFragment(text);
              syncUrl();
              if (op === "flag" || op === "flag-confirm") {
                restoreFlagFocus(op, control, body);
              }
            }
            if (r.status === 409) notice(msg("conflict", "This changed elsewhere — reloaded to the latest."));
            // Only the Move picker remains as a panel form with data-op; it resets the
            // panel to neutral. (The panel's rename form is gone, so the re-token helper
            // that existed solely to refresh it was deleted along with it.)
            if (inPanel) setPanel(neutralPanel);
            clearMoving();
            if (appliedQ) preFilterOpen = null;   // the tree changed underneath it
          } else if (r.status === 422) {
            notice(parseFragment(text).textContent.trim());
          }
        } finally {
          releaseControl();
        }
        releaseForm(form, op);
      });
    }, function () {
      notice(msg("network", "Network error — please try again."));   // network only
      releaseControl();
      releaseForm(form, op);
    }).then(finish, function (e) { finish(); if (window.console) console.error(e); });        // BOTH arms, like every other site
  });

  // ---- publish / obligatory flag toggles + confirm strip (Task 14) --------
  //
  // The unit toggle buttons (data-op="flag") ride the generic submit dispatch
  // above unmodified beyond the guard/focus hooks already threaded through
  // it. What is new here is the GET-driven confirm strip: a container's (or
  // a confirming quiz's) `<a data-flag-confirm>` fetches the strip instead of
  // navigating, and the strip dismisses via its own "x" -- added here, since
  // the server-rendered fragment carries none, being shared with the no-JS
  // interstitial, which dismisses via a plain page Cancel link instead -- or
  // via Esc.

  // After a flag write's applyFragment (a fresh `top` scope replaces the row,
  // destroying whatever control was actually activated), land focus back on
  // whichever flag control the re-rendered row now carries. TWO different
  // targets, because a confirmed write can leave either a confirming anchor
  // behind (a container, or a still-submission-bearing published quiz) or a
  // plain button -- a unit toggle always leaves one, and so does a confirmed
  // write that just UNPUBLISHED a quiz: a drafted quiz needs no confirmation
  // to be re-published, so that row renders a button, not an anchor. Trying
  // the container selector FIRST and falling back to the unit one covers all
  // three cases (E2E4) without the caller having to say which one this is.
  function restoreFlagFocus(op, control, body) {
    var pk = body.get("node");
    var flag = (control && control.getAttribute("data-flag")) || body.get("flag");
    if (!pk || !flag) return;
    var rowSel = '[data-node="' + pk + '"] ';
    var el = null;
    if (op === "flag-confirm") {
      el = root.querySelector(rowSel + '[data-flag-confirm="' + pk + '"][data-flag="' + flag + '"]');
    }
    if (!el) el = root.querySelector(rowSel + '[data-op="flag"][data-flag="' + flag + '"]');
    if (el) el.focus();
  }

  // Opening a strip closes any other -- remove every `[data-flag-strip]`
  // (including one already open on THIS row, the re-ask-on-POST case) before
  // inserting the fresh one, or exclusivity would leave two siblings.
  function insertStripAfterRowhead(incoming, opener) {
    var pk = incoming.getAttribute("data-flag-strip");
    var row = root.querySelector('li.tree__row[data-node="' + pk + '"]');
    if (!row) return;
    root.querySelectorAll("[data-flag-strip]").forEach(function (s) { s.remove(); });
    var rowhead = row.querySelector(":scope > form.tree__rowhead");
    if (!rowhead) return;
    var closeBtn = document.createElement("button");
    closeBtn.type = "button";                       // never a submitter
    closeBtn.className = "flag-strip__dismiss";
    closeBtn.setAttribute("data-flag-dismiss", "");
    closeBtn.setAttribute("aria-label", msg("close", "Close"));
    closeBtn.textContent = "×";
    incoming.insertBefore(closeBtn, incoming.firstChild);
    incoming.setAttribute("tabindex", "-1");   // a focus target for focusInto()
    incoming._flagOpener = opener || null;     // dismiss returns focus here
    rowhead.insertAdjacentElement("afterend", incoming);
  }

  function focusInto(strip) { strip.focus(); }

  function dismissStrip(strip) {
    if (!strip) return;
    var opener = strip._flagOpener;
    strip.remove();
    if (opener && opener.isConnected && typeof opener.focus === "function") {
      opener.focus();
    }
  }

  // The confirming anchor: GET the strip and insert it, rather than navigate.
  root.addEventListener("click", function (e) {
    var a = e.target.closest("[data-flag-confirm]");
    if (!a) return;
    e.preventDefault();                                       // it is an <a href>
    if (!a.getAttribute("href")) return;                       // inert: no href
    if (a.getAttribute("aria-disabled") === "true") return;    // inert, or already in flight
    a.setAttribute("aria-disabled", "true");
    fetch(a.getAttribute("href"), { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var incoming = parseFragment(html).firstElementChild;
        if (!incoming) return;
        insertStripAfterRowhead(incoming, a);
        focusInto(incoming);
      })
      .catch(function () { notice(msg("network", "Network error — please try again.")); })
      .then(function () { a.removeAttribute("aria-disabled"); },
            function (err) { a.removeAttribute("aria-disabled"); if (window.console) console.error(err); });
  });

  // Dismiss via the injected "x".
  root.addEventListener("click", function (e) {
    var x = e.target.closest("[data-flag-dismiss]");
    if (!x) return;
    e.preventDefault();
    dismissStrip(x.closest("[data-flag-strip]"));
  });

  // Dismiss via Esc, while focus is inside the strip (focusInto() lands it
  // there, on the strip's own tabindex="-1" root).
  root.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var strip = e.target.closest("[data-flag-strip]");
    if (!strip) return;
    dismissStrip(strip);
  });
  // ---- end publish / obligatory flag toggles + confirm strip --------------

  // Node selection -> load the detail panel fragment.
  root.addEventListener("click", function (e) {
    // Move… links open their picker inline (fetch GET).
    var mv = e.target.closest("[data-move]");
    if (mv) {
      e.preventDefault();
      // Set ONLY `q`, not setTreeParams: the href already carries a rendered
      // `q`, so appending would yield `?node=5&q=X&q=X` and work only because
      // QueryDict.get takes the last -- and setTreeParams would additionally
      // stamp `open`, which _move_picker never reads (views_manage.py:1075-1111),
      // so after an expand-all every picker GET would carry a ~1 KB pk list.
      var u = new URL(mv.getAttribute("href"), window.location.origin);
      u.searchParams.set("q", appliedQ);
      fetch(u.pathname + u.search, { headers: { "X-Requested-With": "fetch" } })
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
  // The value setter only resets the caret when the value actually CHANGES, so plain
  // assignment is safe.
  //
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
    // Mark consumption and timer clearing run for EVERY focusin, whatever the
    // target, BEFORE the .tree__title test. Tab now goes toggle -> title ->
    // ~6 cluster controls -> next title, and those stops can span more than
    // 150ms; if only titles cleared the timer, row A's fetch would fire while
    // the author was still inside A's cluster.
    var byPointer = pointerFocus;
    pointerFocus = false;
    if (panelTimer) { clearTimeout(panelTimer); panelTimer = null; }
    var t = e.target.closest(".tree__title");
    if (!t) return;
    var row = t.closest("li.tree__row");
    if (!row) return;
    var tpl = root.getAttribute("data-panel-url") || "";
    if (!tpl) return;
    // $-anchored: a `0` inside the course slug must not match.
    var url = tpl.replace(/\/0\/$/, "/" + row.getAttribute("data-node") + "/");
    clearMoving();
    // A deliberate click must not gain 150ms of latency; only keyboard
    // traversal is debounced, so tabbing across ten rows issues one fetch.
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
  // form.tree__rowhead: the row's single form (was form.tree__rename, which no
  // longer exists -- the title is now a direct child of the rowhead form).
  function titleForm(input) { return input.closest("form.tree__rowhead"); }

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
    // would leave the untrimmed string in the POST body.
    input.value = trimmed;
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
      commitRename(input);   // itself null-guards the form and checks dataset.submitting
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
    // 3. Another op's applyFragment is destroying, or has destroyed, this row. Committing
    //    would post a token that swap already superseded, and applyRename would then
    //    no-op on the detached form -- leaving the tree showing the old title while the
    //    database holds the new one, with no notice and a stale row token.
    //    `swapping` carries this, NOT isConnected: Chromium delivers the focusout from
    //    inside replaceWith(), while the doomed subtree still reports isConnected true
    //    (measured; the add flow's guard at the bottom of this file reads isConnected a
    //    timer later, by which point it is false, so that one works as written).
    //    isConnected is kept for the asynchronous case: a focusout queued before a swap
    //    and delivered after it.
    if (swapping || !form.isConnected) return;
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

  // ---- expand / collapse -----------------------------------------------------
  function scopeUrlFor(pk) {
    // pk=0 sentinel, replaced with an $-ANCHORED match so a `0` inside the
    // course slug can never be hit. A string placeholder is impossible: the
    // route is <int:pk> and reverse() rejects a non-numeric pk.
    var tpl = root.getAttribute("data-node-scope-url") || "";
    return tpl.replace(/\/0\/scope\/$/, "/" + pk + "/scope/");
  }

  // ---- title filter: the fetch, the clear path and the pre-filter stash ------
  // Steps 3-6 below are ONE ordered block: `var box` (Step 5) must precede the
  // `if (box)` wiring (Step 6), because `var` hoists the declaration but not
  // the assignment -- pasted the other way round `box` is undefined at the
  // guard, all three entry points are silently unwired, and nothing logs.
  // ---- the info slot ---------------------------------------------------------
  var infoSlot = root.querySelector("[data-info]");

  function applyInfo(response) {
    // header ABSENT -> not a tree-pane response, ignore ENTIRELY. A rename
    // 200, a 422 and both panel fetches never reach _render_scope, so they
    // neither set nor clear -- by construction, not by a call-site list.
    var raw = response.headers.get("X-Builder-Info");
    if (raw === null || !infoSlot) return;

    if (raw === "none") { infoSlot.replaceChildren(); return; }

    // FULL STATE, not a delta. The header lists every entry that applies to
    // the response, so a key it OMITS must be REMOVED.
    //
    // The reachable case is a REFINE, not a clear: the slot holds
    // truncation + filter, the author narrows the query, the new chain set
    // fits under the ceiling, and the response carries `filter` with no
    // `truncation` -- so without this loop the stale truncation entry
    // survives over a tree that is no longer truncated.
    //
    // A CLEAR is already covered by `none` above, and cannot reach here: it
    // sends `open=<enumeration>` derived from the DOM, whose scopes a
    // previous _finalize already capped at <= CEILING, so `len(kept) >
    // CEILING` is False and the response is never truncated.
    var incoming = raw.split(", ").map(function (e) { return e.split(";")[0]; });
    infoSlot.querySelectorAll("[data-info-key]").forEach(function (li) {
      if (incoming.indexOf(li.getAttribute("data-info-key")) === -1) li.remove();
    });

    // grammar:  entry ( ", " entry )*   with   entry := key ( ";" name "=" value )*
    raw.split(", ").forEach(function (entry) {
      var parts = entry.split(";");
      var key = parts[0];
      var params = {};
      parts.slice(1).forEach(function (p) {
        var kv = p.split("=");
        params[kv[0]] = kv[1];
      });
      var template = msg(key, "");
      if (!template) return;
      var text = template.replace(/%\((\w+)\)s/g, function (_m, name) {
        return params[name] !== undefined ? params[name] : "";
      });
      // Replace by KEY -- the info key, the code prefix and the data-msg-*
      // suffix are deliberately the same token, so no prefix->key map exists
      // to get wrong.
      var existing = infoSlot.querySelector('[data-info-key="' + key + '"]');
      var li = document.createElement("li");
      li.setAttribute("data-info-key", key);
      li.textContent = text;             // element nodes only: never leave a
      if (existing) existing.replaceWith(li);   // text node inside the slot,
      else infoSlot.appendChild(li);            // or :empty stops matching
    });
  }

  function rewriteBulkHrefs() {
    // These two sit in .builder__tree's header, OUTSIDE every fragment
    // applyFragment swaps and outside what manage_tree returns -- so unlike
    // the delete and Move hrefs, nothing else refreshes them.
    //
    // Called from the response handlers AND from the two request-less paths
    // that still change `appliedQ`: the clear skip branch (Task 11 Step 5)
    // and collapse-all, which issues no fetch at all. What must NOT happen is
    // relying on a click-time rewrite ALONE -- a middle-click dispatches
    // auxclick, not click, so it would never run for the case this exists for.
    root.querySelectorAll("[data-expand-all], [data-collapse-all]").forEach(
      function (el) {
        var href = el.getAttribute("href");
        if (!href) return;       // never ADD one: over the ceiling the control
                                 // is href-less on purpose, and
                                 // new URL(null, origin) yields "/null"
        var u = new URL(href, window.location.origin);
        if (appliedQ) u.searchParams.set("q", appliedQ);
        else u.searchParams.delete("q");
        el.setAttribute("href", u.pathname + u.search);
      }
    );
  }

  // null, NOT "" -- a legitimately empty pre-filter set stashes as "", and
  // `if (!stash)` misreads that as absent, so an author who had everything
  // collapsed, filtered, then cleared would get the filter's chains open
  // instead of the empty tree they started from.
  var preFilterOpen = null;
  // ONE counter for EVERY data-tree-url request: filter, clear and
  // expand-all all applyFragment the same pane. With a counter per path, a
  // filter response landing after a clear repaints filtered markup, writes
  // the tracker back and restores ?q= -- filtered markup over an empty box.
  var treeGen = 0;
  var filterTimer = null;

  var box = root.querySelector("#builder-q");

  function updateClearVisibility() {
    var clear = root.querySelector("[data-filter-clear]");
    if (clear) clear.hidden = !box.value;
  }

  function applyFilterState(live) {
    var eff = effectiveQ(live);
    // Compared against pendingQ, not appliedQ (see above). Guarded on what is
    // APPLIED-or-IN-FLIGHT, not on what the box contains: otherwise the first
    // character typed into an unfiltered tree takes the clear path, the stash
    // is null, and the fallback re-renders everything the author had open --
    // on mat-pp after an expand-all, the multi-second render, from one
    // keystroke.
    if (eff === effectiveQ(pendingQ)) {
      // No FETCH is needed -- the pane already shows the right thing -- but
      // the tracker still moved, and syncUrl/rewriteBulkHrefs are otherwise
      // only ever called from a response handler. Skipping them here strands
      // a below-floor query: load ?q=a, click Clear, and eff === "" on both
      // sides, so without these two lines `?q=a` stays in the address bar and
      // in both bulk hrefs while the box reads empty -- a reload or a
      // middle-click silently restores a filter the author just cleared.
      appliedQ = live;
      pendingQ = live;
      rewriteBulkHrefs();
      syncUrl();
      return;
    }
    pendingQ = live;          // at ISSUE time, before the fetch

    var url = new URL(root.getAttribute("data-tree-url"), window.location.origin);
    if (eff) {
      // Entering a filter: stash BEFORE the first fetch, and only on the
      // unfiltered -> filtered transition (refining does not re-stash).
      if (preFilterOpen === null) preFilterOpen = collectOpen();
      url.searchParams.set("q", live);
      // NO `open`: step 2 outranks step 3, so a filter fetch carrying it
      // would return only the scopes that happened to be open already, and a
      // match three levels down inside a collapsed branch would never appear.
    } else {
      // Clearing. Never omits `open`: that is the fragment-absent path, i.e.
      // the EMPTY set, which would collapse the course to its top rows.
      url.searchParams.set(
        "open", preFilterOpen === null ? collectOpen() : preFilterOpen
      );
    }

    var gen = ++treeGen;
    busyStart();
    // afterPaint: this path applyFragment's the WHOLE pane, so clearing the dim
    // synchronously would un-dim before the swapped-in tree is painted. Clearing
    // a filter is the large case -- it restores the pre-filter open set, which
    // after an expand-all is the entire course.
    var finish = function () { afterPaint(busyEnd); };
    fetch(url.toString(), { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        return r.text().then(function (text) {
          if (gen !== treeGen) return;          // stale: touch NOTHING --
                                                // a newer issue owns pendingQ
          if (r.status !== 200) {
            // Roll pendingQ BACK. It advanced at issue time, and only the
            // success path advances appliedQ -- so without this, retrying the
            // identical query hits `eff === effectiveQ(pendingQ)`, takes the
            // skip branch, issues NO request, and still writes appliedQ,
            // syncUrl and the bulk hrefs. The tracker would then claim the
            // pane shows `trygo` while it shows the pre-filter tree, and the
            // next toggle would send q=trygo against unfiltered markup: the
            // exact desync the tracker exists to prevent.
            pendingQ = appliedQ;
            notice(msg("network", "Network error — please try again."));
            return;
          }
          applyFragment(text);
          applyInfo(r);                          // Task 12
          appliedQ = live;                       // BEFORE syncUrl and the rewrite
          if (!eff) preFilterOpen = null;        // consumed on APPLY, not on issue
          rewriteBulkHrefs();                    // Task 13
          syncUrl();
        });
      }, function () {
        // Gen-guarded: a STALE request rejecting must not clobber the pendingQ
        // a newer issue owns. Dropping this line reintroduces the desync
        // test_retrying_the_same_query_after_a_FAILED_fetch_issues_a_new_request
        // exists to catch -- and that row fails at Task 14 Step 5 with nothing
        // pointing back at this rewrite as the cause.
        if (gen === treeGen) pendingQ = appliedQ;
        notice(msg("network", "Network error — please try again."));
      })
      .then(finish, function (e) { finish(); if (window.console) console.error(e); });
  }

  if (box) {
    root.addEventListener("input", function (e) {
      if (e.target !== box) return;
      updateClearVisibility();
      clearTimeout(filterTimer);
      filterTimer = setTimeout(function () { applyFilterState(box.value); }, 300);
    });
    // Enter / the Filter button. Without this the most obvious "apply the
    // filter" gesture is a full-page navigation that discards the stash.
    root.addEventListener("submit", function (e) {
      var form = e.target.closest("[data-filter]");
      if (!form) return;
      e.preventDefault();
      clearTimeout(filterTimer);
      applyFilterState(box.value);
    });
    root.addEventListener("click", function (e) {
      if (!e.target.closest("[data-filter-clear]")) return;
      e.preventDefault();
      clearTimeout(filterTimer);        // else it fires and issues a SECOND clear
      box.value = "";
      updateClearVisibility();          // box.value = "" fires no input event
      applyFilterState("");
    });
  }
  // ---- end title filter ------------------------------------------------------

  root.addEventListener("pointerdown", function (e) {
    // Armed HERE, not around the <ol> removal: a click moves focus at
    // mousedown, so a dirty title's focusout fires BEFORE this handler's click
    // would -- and the rename guard reads `swapping`, which would still be
    // false, so the rename would commit on mouse-collapse but abandon on
    // keyboard-collapse.
    //
    // NARROW to the subtree actually being torn out. Arming for ANY toggle
    // click would swallow an unrelated pending rename: edit row A's title,
    // click row B's toggle, and A's focusout is suppressed while focus has
    // already left it -- the edit is lost silently, with no further commit
    // opportunity.
    var t = e.target.closest("[data-toggle]");
    if (!t) return;
    var row = t.closest("li.tree__row");
    var scope = row && row.querySelector(":scope > ol.tree__scope");
    var active = document.activeElement;
    if (scope && active && scope.contains(active)) swapping = true;
  });
  document.addEventListener("pointerup", function () { swapping = false; });
  document.addEventListener("pointercancel", function () { swapping = false; });
  // `swapping` latches true if pointerup never fires (window blur mid-press);
  // `pointerFocus` has the same shape.
  window.addEventListener("blur", function () { swapping = false; pointerFocus = false; });

  root.addEventListener("click", function (e) {
    var t = e.target.closest("[data-toggle]");
    if (!t) return;
    e.preventDefault();                       // it is an <a href>; do not navigate
    if (t.dataset.submitting) return;         // ignore repeat activations
    var pk = t.getAttribute("data-toggle");
    var row = t.closest("li.tree__row");
    if (!row) return;
    var existing = row.querySelector(":scope > ol.tree__scope");
    if (existing) {
      swapping = true;
      try { existing.remove(); } finally { swapping = false; }
      t.setAttribute("aria-expanded", "false");
      t.removeAttribute("aria-controls");
      if (t.dataset.labelExpand) t.setAttribute("aria-label", t.dataset.labelExpand);
      syncUrl();
      return;
    }
    t.dataset.submitting = "1";
    busyStart();
    // the toggle -- clear `submitting` on BOTH paths, or the row wedges
    var finish = function () {
      var ctl2 = root.querySelector('[data-toggle="' + pk + '"]');
      if (ctl2) delete ctl2.dataset.submitting;
      busyEnd();
    };
    var open = collectOpen();
    var body = setTreeParams(new URLSearchParams(), {
      openOverride: open ? open + "," + pk : pk,
    });
    fetch(scopeUrlFor(pk) + "?" + body.toString(), {
      headers: { "X-Requested-With": "fetch" },
    }).then(function (r) {
      // NESTED so `r` survives into the body handler. applyInfo needs the
      // Response; the old `return r.text()` threw it away.
      return r.text().then(function (html) {
        // The non-200 branch moves HERE and stops being a `throw`. The
        // two-argument `.then(finish, ...)` below is the rejection handler
        // for this whole chain, and it always calls `finish()` and returns
        // undefined -- so it RESOLVES the chain rather than re-rejecting it.
        // A thrown "bad status" here would land there: finish() still runs
        // (a console.error trace fires), but there is no notice() and no
        // unhandled-rejection event -- do not make this a `throw`.
        if (r.status !== 200) {
          notice(msg("network", "Network error — please try again."));
          return;
        }
        // A foreign applyFragment may have replaced this row while we waited.
        var live = root.querySelector('li.tree__row[data-node="' + pk + '"]');
        var ctl = live && live.querySelector(':scope > .tree__rowhead [data-toggle]');
        if (!live || !ctl || !ctl.dataset.submitting) return;
        var incoming = parseFragment(html).firstElementChild;
        if (!incoming) return;
        // Replace, never blind-append: a scope arriving while one is already
        // present would leave two sibling <ol data-scope> elements, and the
        // `:scope > ol.tree__scope` lookup would then deterministically match
        // the FIRST one in document order -- not necessarily this response's.
        var dup = live.querySelector(":scope > ol.tree__scope");
        if (dup) dup.remove();
        live.appendChild(incoming);
        ctl.setAttribute("aria-expanded", "true");
        ctl.setAttribute("aria-controls", "tree-scope-" + pk);
        if (ctl.dataset.labelCollapse) {
          ctl.setAttribute("aria-label", ctl.dataset.labelCollapse);
        }
        applyInfo(r);   // AFTER the staleness guard: a response whose row
                        // vanished must not repaint the info slot either.
        syncUrl();
      });
    }, function () {
      notice(msg("network", "Network error — please try again."));   // network only
    }).then(finish, function (e) { finish(); if (window.console) console.error(e); });
  });

  // The delete link is a plain navigation for everyone -- node_confirm_delete's
  // form has no data-op and there is no [data-delete] fetch handler. So stamp
  // the LIVE open set onto the href at click time and let the navigation
  // proceed: no preventDefault.
  root.addEventListener("click", function (e) {
    var del = e.target.closest("[data-delete]");
    if (!del) return;
    var u = new URL(del.getAttribute("href"), window.location.origin);
    u.searchParams.set("open", collectOpen());
    del.setAttribute("href", u.pathname + u.search);
  });

  // ---- bulk expand / collapse ------------------------------------------------
  root.addEventListener("click", function (e) {
    var el = e.target.closest("[data-expand-all]");
    if (!el) return;
    e.preventDefault();
    // Both bails, but only the first is decisive today: it shares its
    // `{% if expand_all_disabled %}` with data-expand-all-disabled
    // (builder.html:19/35) and runs first, so over the ceiling it always
    // fires before the second is even reached. The second is deliberate
    // defence-in-depth, kept for the day the anchor becomes a <button
    // disabled> or an a11y pass drops aria-disabled.
    //
    // hasAttribute, never getAttribute: builder.html:19 emits this attribute
    // BY PRESENCE, so under that markup getAttribute would return null/""
    // (both falsy) and the bail could never fire -- hasAttribute is the only
    // accessor that sees it. A VALUE form (e.g. ="False") would be fatal
    // under either accessor; the bare form is pinned by
    // tests/test_builder_filter_views.py:932, which asserts the attribute is
    // ABSENT from the under-ceiling render.
    if (el.getAttribute("aria-disabled") === "true") return;
    if (root.hasAttribute("data-expand-all-disabled")) return;

    var url = new URL(root.getAttribute("data-tree-url"), window.location.origin);
    setTreeParams(url, { openOverride: "all" });   // sends the APPLIED q
    var gen = ++treeGen;
    busyStart();
    // afterPaint: the largest swap in the app. Without it the dim is dropped
    // while the browser still has the whole expanded tree to lay out and paint,
    // which is exactly the window an author clicks Collapse all in.
    var finish = function () { afterPaint(busyEnd); };
    fetch(url.toString(), { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) {
        return r.text().then(function (text) {
          if (gen !== treeGen) return;
          if (r.status !== 200) { notice(msg("network", "Network error — please try again.")); return; }
          applyFragment(text);
          applyInfo(r);
          rewriteBulkHrefs();
          syncUrl();          // writes the resulting ENUMERATION: the
        });                   // collector can only ever emit one
      }, function () {
        notice(msg("network", "Network error — please try again."));   // network only
      })
      .then(finish, function (e) { finish(); if (window.console) console.error(e); });
  });

  root.addEventListener("pointerdown", function (e) {
    // Arm `swapping` BEFORE the click: a mouse click moves focus at
    // mousedown, so a dirty title's focusout fires first, and the rename
    // guard would read swapping === false and isConnected === true and commit.
    // Slice 1's arming is deliberately NARROWED to the clicked toggle's own
    // subtree, so this control inherits neither half.
    if (!e.target.closest("[data-collapse-all]")) return;
    var active = document.activeElement;
    if (active && active.closest("ol.tree__scope[data-scope]:not([data-scope='top'])")) {
      swapping = true;
    }
  });

  root.addEventListener("click", function (e) {
    if (!e.target.closest("[data-collapse-all]")) return;
    e.preventDefault();          // it is an <a href>; "no request at all" is
                                 // false without this, and the navigation
                                 // would discard the stash
    // KNOWN LIMITATION, not fixed here: this does not bump treeGen, so an
    // in-flight expand-all still passes `gen === treeGen` and repaints the
    // fully-expanded tree over this collapse. The obvious fix -- ++treeGen
    // here too -- is WRONG: it would also invalidate an in-flight FILTER
    // response, advancing pendingQ with no success path left to advance
    // appliedQ to match, and no rollback (the rollback only runs on a non-200
    // or a caught rejection) -- the exact desync the :671-678 comment exists
    // to prevent. The pre-existing toggle-collapse path has the identical
    // hole and already shipped; this one is not new.
    swapping = true;
    try {
      root
        .querySelectorAll('ol.tree__scope[data-scope]:not([data-scope="top"])')
        .forEach(function (ol) { ol.remove(); });
    } finally {
      swapping = false;
    }
    root.querySelectorAll("[data-toggle]").forEach(function (t) {
      t.setAttribute("aria-expanded", "false");
      t.removeAttribute("aria-controls");
      // The server-rendered label pair: JS cannot select a Polish plural form.
      var label = t.getAttribute("data-label-expand");
      if (label) t.setAttribute("aria-label", label);
    });
    rewriteBulkHrefs();
    syncUrl();
  });
  // ---- end bulk expand / collapse --------------------------------------------

  // --- WS2 drag-and-drop ----------------------------------------------------
  var RANK = { part: 0, chapter: 1, section: 2, unit: 3 };
  var drag = null;  // { pk, kind, token }
  root.addEventListener("dragstart", function (e) {
    var grip = e.target.closest(".ica--grip");
    if (!grip) return;
    if (grip.disabled) { e.preventDefault(); return; }
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
  var markedScope = null, markedLine = null;   // tracked, not re-queried
  function clearDropMarks() {
    if (markedScope) { markedScope.classList.remove("drop-target"); markedScope = null; }
    if (markedLine) { markedLine.remove(); markedLine = null; }
  }
  var pendingFrame = null, lastY = 0, lastScope = null;
  function cancelFrame() {
    if (pendingFrame !== null) { cancelAnimationFrame(pendingFrame); pendingFrame = null; }
  }
  function paintDropMarks() {
    pendingFrame = null;
    if (!drag || !lastScope) return;           // outlived drop/dragend
    clearDropMarks();
    lastScope.classList.add("drop-target");
    markedScope = lastScope;
    var t = targetFor(lastY, lastScope);
    var line = document.createElement("li");
    line.className = "drop-line";
    if (t.before) lastScope.insertBefore(line, t.before); else lastScope.appendChild(line);
    markedLine = line;
    lastScope.dataset.dropIndex = t.index;
    lastScope.dataset.dropParent = lastScope.getAttribute("data-scope");
    lastScope.dataset.dropToken = lastScope.getAttribute("data-updated");
    drag.targetScope = lastScope;
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
    // Both rejecting branches cancel: a frame scheduled by the PREVIOUS legal
    // dragover would otherwise re-mark a target just rejected and re-set
    // targetScope, so a drop there would post an illegal move.
    if (!scope) { cancelFrame(); return; }
    var destRow = scope.closest(".tree__row");               // the container row (null for top)
    var parentKind = destRow ? destRow.getAttribute("data-kind") : null;
    // forbid dropping into self/descendant: scope must not be inside the dragged row
    var draggedRow = root.querySelector('.tree__row[data-node="' + drag.pk + '"]');
    if (!legal(parentKind) || (draggedRow && draggedRow.contains(scope))) {
      cancelFrame(); clearDropMarks(); drag.targetScope = null; return;
    }
    // Legality costs no layout, so it stays synchronous -- and preventDefault
    // stays conditional on it, or every illegal spot advertises as droppable.
    e.preventDefault();
    lastY = e.clientY;                        // the LATEST event, not the one
    lastScope = scope;                        // that scheduled the frame
    if (pendingFrame === null) pendingFrame = requestAnimationFrame(paintDropMarks);
  });
  root.addEventListener("drop", function (e) {
    if (!drag) return;
    // FLUSH, don't cancel. Capture the id FIRST: paintDropMarks() nulls
    // pendingFrame on its first line, so a following cancelFrame() would see
    // null and never call cancelAnimationFrame.
    if (pendingFrame !== null) {
      var _id = pendingFrame; pendingFrame = null;
      cancelAnimationFrame(_id); paintDropMarks();
    }
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
    withOpen(body);
    busyStart();
    var finish = function () { busyEnd(); };
    fetch(root.getAttribute("data-node-move-url"), {
      method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: body,
    }).then(function (r) { return r.text().then(function (text) {
      if (r.status === 200 || r.status === 409) {
        applyFragment(text);
        applyInfo(r);
        syncUrl();
        if (appliedQ) preFilterOpen = null;   // the tree changed underneath it
        if (r.status === 409) notice(msg("conflict", "This changed elsewhere — reloaded to the latest."));
        // A drag bypasses the submit handler's panel-refresh. If the panel holds a token-bearing
        // form (e.g. the dragged node's Move picker / rename), it is now stale — clear it so
        // reusing it can't spuriously 409.
        if (panel.querySelector("form[data-op]")) setPanel("");
      } else if (r.status === 422) { notice(msg("illegal", "That move isn't allowed here.")); }
    }); }, function () {
      notice(msg("network", "Network error — please try again."));   // network only
    }).then(finish, function (e) { finish(); if (window.console) console.error(e); });
  });
  root.addEventListener("dragend", function () {
    cancelFrame(); clearDropMarks(); drag = null; pointerFocus = false;
  });
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
