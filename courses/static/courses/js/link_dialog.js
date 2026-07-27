(function () {
  "use strict";

  // Bail leaves window.libliLinkDialog UNDEFINED -- the export is the capability
  // signal, not merely a platform signal. A page that loaded this script without the
  // partial would otherwise pass text_toolbar.js's guard and then throw on a null
  // query. Follows imagezoom.js's precedent; the button becomes a no-op, an accepted
  // regression from window.prompt on browsers lacking <dialog>.
  if (typeof document.createElement("dialog").showModal !== "function") return;
  var dialog = document.querySelector(".link-dialog");
  if (!dialog) return;

  var pickerUrl = dialog.getAttribute("data-link-picker-url");
  var filterEl = dialog.querySelector("[data-link-filter]");
  var mount = dialog.querySelector("[data-link-tree]");
  var urlEl = dialog.querySelector("[data-link-url]");
  var textEl = dialog.querySelector("[data-link-text]");
  var insertBtn = dialog.querySelector("[data-link-insert]");
  var removeBtn = dialog.querySelector("[data-link-remove]");
  var cancelBtn = dialog.querySelector("[data-link-cancel]");
  var retryBtn = dialog.querySelector("[data-link-retry]");
  var countEl = dialog.querySelector("[data-link-count]");
  var countLabel = dialog.querySelector("[data-count-template]");
  var tabsEl = dialog.querySelector(".picker__tabs");
  // Digit run capped at 12, mirroring courses/richtext.py's _PERMALINK (I1: CPython's
  // int() raises past a 4300-digit conversion; the Python side now caps at 12 to match
  // transfer/schema.py's link_nodes key cap). JS's parseInt never throws, so nothing
  // here crashes without the cap -- this keeps the two definitions of "internal link"
  // honest with each other rather than letting them silently diverge.
  var PERMALINK = /^\/courses\/n\/(\d{1,12})\/$/;

  var callback = null;        // pending; a second open() is REJECTED, not superseding
  var committed = null;       // set by Insert/Remove; the close handler reads it
  var treeHtml = null;        // cached SUCCESSFUL response, for the life of the page
  var pending = null;         // in-flight fetch, reused by a second open()
  var aborter = null;
  var aborted = false;        // distinguishes a deliberate abort from a real failure
  var wantNode = null;        // preselection requested before the payload arrived
  var filterTimer = null;

  function msg(key, on) {
    var el = dialog.querySelector('[data-msg="' + key + '"]');
    if (el) el.hidden = !on;
  }
  // scope defaults to the whole dialog (a full reset -- loadTree/paint/open all want
  // that). urlEl's own input handler passes ITS panel only: every [data-msg] element
  // lives inside exactly one panel, and the node panel's "fetch" message holds the
  // Retry button -- an unscoped clear from a keystroke on the OTHER tab hides that
  // button with no way to bring it back except closing and reopening the dialog.
  function clearMessages(scope) {
    var all = (scope || dialog).querySelectorAll("[data-msg]");
    for (var i = 0; i < all.length; i++) all[i].hidden = true;
  }

  // ---- tabs ---------------------------------------------------------------
  // editor.css styles the active tab as .picker__tab.is-on and hides panels via
  // .picker__panel[hidden] -- the pair media_picker.js already toggles. Without both,
  // two panels render at once. role="tab" also implies the tablist keyboard contract,
  // so the tabs are ONE tab stop with Left/Right between them.
  function showTab(name, focusField) {
    var tabs = dialog.querySelectorAll(".picker__tab");
    for (var i = 0; i < tabs.length; i++) {
      var on = tabs[i].getAttribute("data-tab") === name;
      tabs[i].classList.toggle("is-on", on);
      tabs[i].setAttribute("aria-selected", on ? "true" : "false");
      tabs[i].tabIndex = on ? 0 : -1;
    }
    var panels = dialog.querySelectorAll(".picker__panel");
    for (var j = 0; j < panels.length; j++) {
      panels[j].hidden = panels[j].getAttribute("data-panel") !== name;
    }
    if (focusField) (name === "node" ? filterEl : urlEl).focus();
    refresh();
  }
  tabsEl.addEventListener("click", function (e) {
    var t = e.target.closest(".picker__tab");
    if (t) showTab(t.getAttribute("data-tab"), true);
  });
  tabsEl.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var next = activeTab() === "node" ? "url" : "node";
    showTab(next, false);
    dialog.querySelector('[data-tab="' + next + '"]').focus();
    e.preventDefault();
  });

  function activeTab() {
    var on = dialog.querySelector(".picker__tab.is-on");
    return on ? on.getAttribute("data-tab") : "node";
  }

  // ---- picker -------------------------------------------------------------
  function rows() { return mount.querySelectorAll(".link-picker__item"); }
  function selectedRow() { return mount.querySelector('[aria-selected="true"]'); }

  function rovingSet() {
    var out = [], all = rows();
    for (var i = 0; i < all.length; i++) {
      if (!all[i].hidden && all[i].getAttribute("aria-disabled") !== "true") {
        out.push(all[i]);
      }
    }
    return out;
  }

  function setTabStop() {
    // The tab stop is a function of the roving set ALONE: the selected row only when
    // it is IN that set. Otherwise a filter that hides the selection would put
    // tabindex="0" on an unfocusable element and strand the tree with no tab stop.
    var set = rovingSet(), all = rows();
    for (var i = 0; i < all.length; i++) all[i].tabIndex = -1;
    var sel = selectedRow();
    var target = (sel && set.indexOf(sel) !== -1) ? sel : set[0];
    if (target) target.tabIndex = 0;
  }

  function selectRow(row) {
    var all = rows();
    for (var i = 0; i < all.length; i++) all[i].setAttribute("aria-selected", "false");
    if (row) {
      row.setAttribute("aria-selected", "true");
      if (!textEl.value) textEl.value = row.getAttribute("data-title") || "";
      row.scrollIntoView({ block: "nearest" });
    }
    setTabStop();
    refresh();
  }

  function applyFilter() {
    var q = (filterEl.value || "").trim().toLowerCase();
    var all = rows(), shown = 0;
    for (var i = 0; i < all.length; i++) {
      var title = (all[i].getAttribute("data-title") || "").toLowerCase();
      // Title only -- the kind label is a translated word and would match half the
      // tree in Polish.
      var hit = !q || title.indexOf(q) !== -1;
      all[i].hidden = false;
      all[i].setAttribute("aria-disabled", hit ? "false" : "true");
      if (hit) shown++;
    }
    if (q) {
      // Non-matching rows stay visible as ancestor context, recessed and
      // aria-disabled -- so the indentation still reads as a path -- but a row with
      // no matching descendant is hidden outright.
      for (var j = all.length - 1; j >= 0; j--) {
        if (all[j].getAttribute("aria-disabled") === "true" &&
            !all[j].querySelector('[aria-disabled="false"]')) {
          all[j].hidden = true;
        }
      }
    }
    msg("nomatch", !!(q && shown === 0));
    mount.hidden = !!(q && shown === 0);
    setTabStop();
    // Debounced: a polite region that changes every keystroke queues one utterance per
    // character and drowns the "No matches." case it exists for.
    clearTimeout(filterTimer);
    if (!q) {
      // No filter, nothing to announce -- an empty query means "every row shown",
      // which nobody asked a screen reader about. Without this, ~400ms after EVERY
      // open() (applyFilter runs once from paint(), always with q === "") the live
      // region reads out the whole tree's row count unprompted.
      countEl.hidden = true;
      countEl.textContent = "";
      return;
    }
    filterTimer = setTimeout(function () {
      // Announce a COUNT WITH A LABEL, never a naked digit. The zero-match line lives
      // inside this same region, so entering and leaving that state is announced too.
      countEl.hidden = false;
      countEl.textContent =
        shown + " " + (countLabel ? countLabel.textContent.trim() : "");
    }, 400);
  }
  filterEl.addEventListener("input", applyFilter);

  mount.addEventListener("click", function (e) {
    var row = e.target.closest(".link-picker__item");
    if (row && row.getAttribute("aria-disabled") !== "true") selectRow(row);
  });

  mount.addEventListener("keydown", function (e) {
    var set = rovingSet();
    var cur = document.activeElement.closest
      ? document.activeElement.closest(".link-picker__item")
      : null;
    var i = set.indexOf(cur);
    if (e.key === "ArrowDown" && i > -1 && set[i + 1]) {
      set[i + 1].focus(); e.preventDefault();
    } else if (e.key === "ArrowUp" && i > 0) {
      set[i - 1].focus(); e.preventDefault();
    } else if (e.key === "Home" && set[0]) {
      set[0].focus(); e.preventDefault();
    } else if (e.key === "End" && set.length) {
      set[set.length - 1].focus(); e.preventDefault();
    } else if ((e.key === "Enter" || e.key === " ") && cur) {
      // Enter SELECTS a row here; it never inserts. Otherwise arrowing to a new row
      // and pressing Enter would fire Insert against the previously selected node.
      selectRow(cur); e.preventDefault();
    }
  });

  function loadTree() {
    clearMessages();
    msg("loading", true);
    if (treeHtml !== null) { paint(treeHtml); return; }
    // NOTE: this only guards a re-entrant loadTree() from the Retry button. A second
    // open() while one is pending is rejected in open() itself, and close() aborts and
    // nulls `pending`, so there is no cross-open "reuse the in-flight request" path.
    if (pending) return;
    aborted = false;
    aborter = new AbortController();
    pending = fetch(pickerUrl, {
      headers: { "X-Requested-With": "fetch" },
      signal: aborter.signal
    }).then(function (r) {
      // "Successful" means ok AND not redirected: link_picker is @login_required, so an
      // expired session gives 302 -> login page -> 200, and fetch follows it. Caching
      // that would inject the login page into the tree mount AS the tree.
      if (!r.ok || r.redirected) throw new Error("bad");
      return r.text();
    }).then(function (html) {
      treeHtml = html;                 // cache SUCCESSES only
      pending = null;
      paint(html);
    }).catch(function () {
      pending = null;
      if (aborted) return;             // a deliberate abort is not a failure
      clearMessages();
      msg("fetch", true);              // not cached -> the next open() retries
    });
  }

  function paint(html) {
    // Server-rendered, autoescaped markup: innerHTML is correct here. The
    // never-innerHTML rule governs author-supplied strings crossing into an editing
    // surface, which this is not.
    mount.innerHTML = html;
    clearMessages();
    if (!rows().length) msg("empty", true);
    if (wantNode) {
      var row = mount.querySelector('[data-node="' + wantNode + '"]');
      if (row) selectRow(row); else msg("foreign", true);
      wantNode = null;
    }
    applyFilter();
  }
  retryBtn.addEventListener("click", loadTree);

  // ---- validity -----------------------------------------------------------
  function currentHref() {
    if (activeTab() === "node") {
      var row = selectedRow();
      return row ? row.getAttribute("data-href") : null;
    }
    var res = window.libliLinkApply.normalizeUrl(urlEl.value, window.location.origin);
    return res.href || null;
  }

  function refresh() {
    insertBtn.disabled = !(currentHref() && textEl.value.trim());
  }
  urlEl.addEventListener("input", function () {
    clearMessages(urlEl.closest(".picker__panel"));
    var res = window.libliLinkApply.normalizeUrl(urlEl.value, window.location.origin);
    var bad = !!(res.reject && urlEl.value.trim());
    if (bad) msg(res.reject, true);
    urlEl.setAttribute("aria-invalid", bad ? "true" : "false");
    refresh();
  });
  // Normalise IN THE FIELD on blur, not inside the insert handler: commit() closes the
  // dialog on the next statement, so a value rewritten there is never seen. The author
  // must be able to see (and reject) https:// being prepended.
  urlEl.addEventListener("blur", function () {
    var res = window.libliLinkApply.normalizeUrl(urlEl.value, window.location.origin);
    if (res.href) urlEl.value = res.href;
    refresh();
  });
  textEl.addEventListener("input", refresh);

  function commit(result) { committed = result; dialog.close(); }
  insertBtn.addEventListener("click", function () {
    var href = currentHref();
    if (href) commit({ href: href, text: textEl.value });
  });
  removeBtn.addEventListener("click", function () { commit({ remove: true }); });
  cancelBtn.addEventListener("click", function () { dialog.close(); });

  // Enter inserts from the URL and Link-text fields only (the tree owns its own Enter).
  function enterInserts(e) {
    if (e.key === "Enter" && !insertBtn.disabled) { insertBtn.click(); e.preventDefault(); }
  }
  urlEl.addEventListener("keydown", enterInserts);
  textEl.addEventListener("keydown", enterInserts);

  // A modal <dialog> does NOT close on a backdrop click by itself; only Escape is
  // native. The content lives in an inner card and the dialog carries no padding, so
  // e.target === dialog means the backdrop and never the card's own padding. (Note
  // imagezoom.js closes on EVERY click inside it -- copying that here would make this
  // dialog unusable.)
  //
  // click's target is the nearest common ancestor of mousedown and mouseup, NOT
  // wherever the mouse went down -- so selecting text in the URL field and dragging
  // the mouse up past the card's edge fires a click whose target IS the dialog, even
  // though the gesture started inside the input. MEASURED in Chromium. Requiring the
  // mousedown to have ALSO landed on the backdrop confines this to an actual backdrop
  // click.
  var backdropMousedown = false;
  dialog.addEventListener("mousedown", function (e) {
    backdropMousedown = e.target === dialog;
  });
  dialog.addEventListener("click", function (e) {
    if (e.target === dialog && backdropMousedown) dialog.close();
  });

  // Every dismissal path routes through ONE close handler, which fires the callback
  // exactly once -- pinning the classic double-fire where a button handler and a close
  // handler both call back.
  dialog.addEventListener("close", function () {
    var cb = callback, result = committed;
    callback = null;
    committed = null;
    if (aborter) { aborted = true; aborter.abort(); aborter = null; pending = null; }
    clearTimeout(filterTimer);   // a timer armed by the last keystroke would otherwise
                                 // fire up to 400ms later, repainting the count AFTER
                                 // the next open()'s reset
    if (cb) cb(result || null);
  });

  window.libliLinkDialog = {
    open: function (opts, cb) {
      if (callback) return;            // one dialog at a time; the pending call stands
      callback = cb;
      committed = null;

      // Reset BEFORE preselection: the tree DOM is cached and aria-selected is the only
      // record of the target, so without this the second open arrives pre-armed with
      // the previous session's target and filter.
      filterEl.value = "";
      urlEl.value = "";
      urlEl.setAttribute("aria-invalid", "false");
      textEl.value = "";
      var all = rows();
      for (var i = 0; i < all.length; i++) {
        all[i].setAttribute("aria-selected", "false");
        all[i].hidden = false;
        all[i].setAttribute("aria-disabled", "false");
      }
      clearMessages();
      // NOT statusEl.textContent = "" -- that replaces ALL children, destroying the
      // [data-msg="nomatch"] and [data-link-count] spans that live inside the region.
      // They never come back, and the debounce then throws on a null element.
      countEl.textContent = "";
      countEl.hidden = true;
      clearTimeout(filterTimer);
      wantNode = null;

      var existing = opts.existing;
      removeBtn.disabled = !(opts.touchedAnchors > 0);

      // Prefill precedence: when an anchor ENCLOSES the range (i.e. rule 1 will fire)
      // existing.text wins, so the field shows the WHOLE text the mutation will
      // operate on. Prefilling a partial selection would show "vertex" in a field
      // whose edit replaces "the vertex form unit" -- three words lost, no undo.
      if (existing) textEl.value = existing.text || "";
      else if (opts.selectionText) textEl.value = opts.selectionText;

      var m = existing && PERMALINK.exec(existing.href || "");
      var tab = "node";
      // The raw stored href goes into the URL field WHENEVER there is one, including
      // for an internal permalink: if the pk turns out not to be in this course's
      // tree, paint() shows the "not in this course" line and the author still needs
      // to see and edit exactly what is stored. Setting it only on the else-branch
      // would leave that field empty in precisely that case.
      if (existing) urlEl.value = existing.href || "";
      if (m) { wantNode = m[1]; }
      else if (existing) { tab = "url"; }

      // showModal FIRST, then focus. A closed <dialog> is display:none, so a .focus()
      // before it is a no-op -- and showModal then autofocuses the first focusable
      // descendant, which is the first TAB BUTTON, not the field.
      showTab(tab, false);
      dialog.showModal();
      (tab === "node" ? filterEl : urlEl).focus();
      loadTree();
      refresh();
    }
  };
})();
