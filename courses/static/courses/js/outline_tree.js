(function () {
  "use strict";

  var tree = document.querySelector(".outline-tree");
  if (!tree) return;

  var KEY = "libli_outline_open:" + (tree.dataset.courseSlug || "");
  var groups = Array.prototype.slice.call(
    tree.querySelectorAll(".outline-node__group")
  );
  var button = document.querySelector("[data-outline-toggle-all]");
  var filterActive = false;

  // ── storage ──────────────────────────────────────────────────────────────
  // The value is a PARTITION, not an open-list. With an open-only list "not
  // listed" is ambiguous between "the student closed this" and "this container
  // did not exist last visit", and those need opposite treatments.
  // Ids are strings on BOTH sides: dataset.node yields a string and
  // [12].indexOf("12") is -1, so a numeric writer + dataset reader is a silent
  // no-op that still passes any test seeding storage the writer's own way.
  function read() {
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed || parsed.v !== 1) return null;
      return {
        open: (parsed.open || []).map(String),
        closed: (parsed.closed || []).map(String)
      };
    } catch (e) {
      return null; // unparseable, or Safari private mode. Never throw.
    }
  }

  // Full replacement, never a merge: ids of containers deleted since the last
  // visit self-prune on the next gesture. Last-write-wins across tabs is
  // accepted for a cosmetic preference — do NOT add a `storage` listener.
  function write() {
    if (filterActive) return; // D5 — the filtered view is transient by definition
    var open = [];
    var closed = [];
    groups.forEach(function (g) {
      (g.open ? open : closed).push(String(g.dataset.node));
    });
    try {
      localStorage.setItem(KEY, JSON.stringify({ v: 1, open: open, closed: closed }));
    } catch (e) {}
  }

  // A group in neither array is NEW since the last write: fall back to its own
  // data-depth default, so a newly authored top-level part behaves like a first
  // visit for that node instead of silently arriving folded.
  function applyPartition(state) {
    groups.forEach(function (g) {
      var id = String(g.dataset.node);
      if (state && state.open.indexOf(id) !== -1) g.open = true;
      else if (state && state.closed.indexOf(id) !== -1) g.open = false;
      else g.open = g.dataset.depth === "0";
    });
  }

  // ── label ────────────────────────────────────────────────────────────────
  // Names the ACTION OFFERED, not the current state. One shared function,
  // called at init and from the capture-phase toggle listener — never from the
  // toggle-all click handler, or the capture listener could be missing entirely
  // and no test would notice.
  function syncLabel() {
    if (!button) return;
    var anyClosed = groups.some(function (g) { return !g.open; });
    button.textContent = button.getAttribute(
      anyClosed ? "data-label-expand" : "data-label-collapse"
    );
  }

  // ── deep links ───────────────────────────────────────────────────────────
  function openHashTarget() {
    var m = /^#node-(\d+)$/.exec(location.hash);
    if (!m) return;
    var li = document.getElementById("node-" + m[1]);
    if (!li) return; // a draft the student cannot see, or a deleted node

    // The target's OWN group, if it has one. Every generated permalink names a
    // container (views.py sends units to lesson_unit/quiz_unit instead), so
    // ancestors-only would land the student on a highlighted head with its
    // contents folded. But id="node-N" is on EVERY <li>, units included, so a
    // bookmarked #node-<unit-pk> owns no <details> — this must not throw.
    var own = li.querySelector(":scope > .outline-node__group");
    if (own) own.open = true;

    var el = li.parentElement;
    while (el && tree.contains(el)) {
      if (el.tagName === "DETAILS") el.open = true;
      el = el.parentElement;
    }
    li.scrollIntoView({ block: "center" });
    write(); // D6 — a deliberate navigation. No-op while filterActive.
  }

  // ── init, in this order (§4.0) ───────────────────────────────────────────
  // 1. Seed filterActive FROM THE PAGE, before anything reads or writes. It must
  //    not wait for the libli:tagfilter event: that arrives after the steps
  //    below have run, so a ?tags=N#node-M URL would write the server's
  //    force-opened tree straight into storage.
  filterActive = !!document.querySelector("[data-tags-filter] a.tag-chip.is-active");

  // 2. Reveal the button — but not on a course with zero groups, where "every
  //    group is open" is vacuously true and the control would do nothing.
  if (button && groups.length) {
    button.hidden = false;
    button.disabled = filterActive;
  }

  // 3. Apply stored state — SKIPPED under a filter, where the server's D8 render
  //    is already correct. Key absent: do nothing at all, leaving the server's
  //    D1/D8 render. (The filter-clear restore below has the opposite rule.)
  if (!filterActive) {
    var stored = read();
    if (stored) applyPartition(stored);
  }

  // 4. Deep link.
  openHashTarget();
  window.addEventListener("hashchange", openHashTarget);

  // Spec §4.0 puts syncLabel() in step 2; it is called here instead, AFTER the
  // stored state and the deep link have changed the tree, so the very first label
  // describes the tree the student actually sees. Deliberate deviation from a
  // section the spec marks normative — the end state is identical because the
  // capture-phase listener below would correct it anyway, but this avoids a
  // one-frame stale label.
  syncLabel();

  // 5. Force a style recalculation BEFORE dropping the class. Whether a
  //    transition starts is decided from the after-change style, and the
  //    mutations above plus this removal happen in one synchronous task — so
  //    without the forced read the chevrons would have both the new rotation and
  //    a live transition at the next recalc, and the wave animates anyway. The
  //    class would be silently inert.
  void tree.offsetHeight;
  // Unconditionally, however the branches above went. Conditioning this on
  //    step 3 would leave the transition dead for the whole session on a
  //    filtered or first-time load.
  tree.classList.remove("outline-tree--booting");

  // ── persistence: on user gesture, never on `toggle` ──────────────────────
  // `toggle` fires ASYNCHRONOUSLY, so the obvious "set a programmatic flag,
  // mutate, clear the flag" approach clears the flag long before the queued
  // events run and persists every programmatic open — exactly the D5 failure,
  // invisible until a student clears a filter. So the gesture is the trigger.
  tree.addEventListener("click", function (e) {
    // closest(), not matches(): the summary contains an <svg>, the title span
    // and the rollup chips, so e.target is almost never the summary itself — a
    // matches() build fires only in the gaps between children and looks like it
    // works. closest() also resolves from inside the SVG. A click on the sibling
    // reset link yields null here and is ignored with no special-casing.
    if (!e.target.closest("summary.outline-node__head")) return;
    // The timeout is required, not decoration: <summary>'s activation behaviour
    // runs AFTER click dispatch, so reading .open in this handler reads the
    // pre-click state. Keyboard activation dispatches a real click too, so this
    // covers Enter/Space with no extra keydown handling.
    setTimeout(write, 0);
  });

  if (button) {
    button.addEventListener("click", function () {
      var expand = groups.some(function (g) { return !g.open; });
      groups.forEach(function (g) { g.open = expand; });
      write();
      // Deliberately NOT syncLabel() — spec §4.3 forbids the click handler
      // setting the label itself, because then the capture listener below could
      // be missing entirely and T9 would still pass. The programmatic `g.open`
      // mutations above fire `toggle`, which the listener handles.
    });
  }

  // CAPTURE phase: `toggle` does not bubble, so a plain delegated listener
  // silently never fires and the label just stops updating.
  tree.addEventListener("toggle", syncLabel, true);

  // ── tag filter (dispatcher lives in tags.js) ─────────────────────────────
  document.addEventListener("libli:tagfilter", function (e) {
    var count = e.detail ? e.detail.count : 0;
    if (count > 0) {
      filterActive = true;
      if (button) button.disabled = true;
      groups.forEach(function (g) {
        if (g.querySelector("li[data-unit]:not([hidden])")) g.open = true;
      });
    } else {
      // No-op unless a filter was actually active. tags.js ends setupFilter with
      // an unconditional applyFilter, so an UNFILTERED load that renders a filter
      // bar dispatches count:0 right after openHashTarget() ran — without this
      // guard that would slam the just-opened ancestors shut.
      if (!filterActive) return;
      filterActive = false;
      if (button) button.disabled = false;
      // Restore path: an absent key is an EMPTY PARTITION here, so every group
      // falls back to its data-depth default. (The load path leaves the DOM
      // alone instead — otherwise a first-visit student who filters and clears
      // is left with a fully force-opened tree.)
      applyPartition(read());
    }
    // No syncLabel() here either: the force-open / restore mutations above fire
    // `toggle`, and the capture listener owns the label. See §4.3.
  });
})();
