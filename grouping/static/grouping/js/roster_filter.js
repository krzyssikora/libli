"use strict";
// Roster pickers (students + teachers): client-side filtering of a checkbox list by
// cohort (students only) and by name substring, plus a live "Added" count. Filtering
// only shows/hides items — every checkbox stays in the DOM, so a person selected
// outside the active filter is never dropped on save. Progressive enhancement: with
// JS off the full list shows, submits as before, and the server-rendered count holds.
(function () {
  Array.prototype.forEach.call(
    document.querySelectorAll("[data-roster]"),
    initRoster
  );
  // The allocation select sits OUTSIDE every [data-roster] fieldset, so it needs its
  // own entry point — a function merely appended below would never run.
  initAllocationFilter();

  function initRoster(root) {
    var list = root.querySelector("[data-roster-list]");
    if (!list) return;

    var cohortSel = root.querySelector("[data-roster-cohort]");
    var search = root.querySelector("[data-roster-search]");
    var shownEl = root.querySelector("[data-roster-count]");
    var selectedEl = root.querySelector("[data-roster-selected]");
    var addAllWrap = root.querySelector("[data-roster-all-wrap]");
    var addAll = root.querySelector("[data-roster-all]");
    var items = itemsOf(list);

    function itemName(item) {
      var explicit = item.getAttribute("data-name");
      return (explicit !== null ? explicit : item.textContent).toLowerCase();
    }

    function itemCheckbox(item) {
      return item.querySelector("input[type=checkbox]");
    }

    function visibleItems() {
      return items.filter(function (item) {
        return !item.hidden;
      });
    }

    function applyFilter() {
      var cohort = cohortSel ? cohortSel.value : "";
      var term = search ? search.value.trim().toLowerCase() : "";
      var shown = 0;
      items.forEach(function (item) {
        var matchCohort =
          !cohort || item.getAttribute("data-cohort") === cohort;
        var matchName = !term || itemName(item).indexOf(term) !== -1;
        var visible = matchCohort && matchName;
        item.hidden = !visible;
        if (visible) shown++;
      });
      if (shownEl) {
        var filtering = !!cohort || !!term;
        shownEl.hidden = !filtering;
        if (filtering) shownEl.textContent = shown + " / " + items.length;
      }
      syncAddAll();
    }

    function updateSelected() {
      if (!selectedEl) return;
      var live = list.querySelectorAll("input[type=checkbox]:checked").length;
      var saved = parseInt(selectedEl.getAttribute("data-roster-saved"), 10);
      // Surface the saved baseline only when the live selection has diverged from
      // it (an unsaved-changes hint); otherwise just the count, as before.
      if (!isNaN(saved) && live !== saved) {
        var label = selectedEl.getAttribute("data-saved-label") || "saved";
        selectedEl.textContent = live + " (" + label + ": " + saved + ")";
      } else {
        selectedEl.textContent = live;
      }
    }

    // Recomputes add-all's tri-state from VISIBLE items only, in strict
    // precedence order. Order matters: the zero-visible case must be checked
    // BEFORE the checked/unchecked/indeterminate rule, because "all visible
    // items are ticked" is vacuously true of an empty set — without this early
    // return the box would render checked when nothing is shown.
    function syncAddAll() {
      if (!addAll) return;
      var visible = visibleItems();
      if (visible.length === 0) {
        addAll.disabled = true;
        addAll.checked = false;
        addAll.indeterminate = false;
        return;
      }
      addAll.disabled = false;
      var checkedCount = visible.filter(function (item) {
        var cb = itemCheckbox(item);
        return !!cb && cb.checked;
      }).length;
      if (checkedCount === 0) {
        addAll.checked = false;
        addAll.indeterminate = false;
      } else if (checkedCount === visible.length) {
        addAll.checked = true;
        addAll.indeterminate = false;
      } else {
        // Partial selection. Pinning checked = false here is load-bearing:
        // `indeterminate` has no effect on what a click does — the browser just
        // flips whatever `checked` currently holds — so a stale `checked` would
        // make a click from here CLEAR the visible selection on some builds
        // instead of extending it. Forcing false means a click always ADDS,
        // which is the safe direction.
        addAll.indeterminate = true;
        addAll.checked = false;
      }
    }

    function onAddAllChange() {
      var checked = addAll.checked;
      visibleItems().forEach(function (item) {
        var cb = itemCheckbox(item);
        if (cb) cb.checked = checked;
      });
      // Setting .checked from script fires no `change` on the list, so the
      // counter and add-all's own tri-state need an explicit refresh here.
      updateSelected();
      syncAddAll();
    }

    if (cohortSel) cohortSel.addEventListener("change", applyFilter);
    if (search) search.addEventListener("input", applyFilter);
    list.addEventListener("change", function () {
      updateSelected();
      syncAddAll();
    });
    if (addAll) addAll.addEventListener("change", onAddAllChange);
    // Unconditional, NOT the [data-roster-count] "only while filtering"
    // treatment — otherwise add-all stays invisible until a filter is applied.
    if (addAllWrap) addAllWrap.hidden = false;
    applyFilter();
    updateSelected();
  }

  // Items to filter: explicitly tagged labels (the student picker), else every
  // checkbox <label> — which is the row anchor Django's CheckboxSelectMultiple
  // renders for teachers (as <div><label>…</label></div>, NOT <li>). Hiding the
  // label collapses its bare wrapper, so non-matching teacher rows disappear.
  function itemsOf(list) {
    var tagged = list.querySelectorAll("[data-roster-item]");
    if (tagged.length) return Array.prototype.slice.call(tagged);
    return Array.prototype.slice.call(list.querySelectorAll("label"));
  }

  // Client-side convenience filter for the group form's allocation select: on
  // the create form the course is chosen in the same submission, so narrow the
  // (already user-scoped) allocation options to the picked course. The server
  // re-validates the course match regardless, so this is convenience, never
  // the gate. On the edit form `course` is disabled (immutable after create)
  // and the queryset is already server-filtered to that one course, so this
  // is a no-op there — return early rather than run against a disabled select.
  function initAllocationFilter() {
    var select = document.querySelector("[data-allocation-select]");
    if (!select) return;
    var form = select.closest("form");
    var courseSel = form ? form.querySelector('[name="course"]') : null;
    if (!courseSel || courseSel.disabled) return;

    function courseOf(optgroup) {
      var opt = optgroup.querySelector("option[data-course]");
      return opt ? opt.getAttribute("data-course") : null;
    }

    function apply() {
      var course = courseSel.value;
      Array.prototype.forEach.call(
        select.querySelectorAll("optgroup"),
        function (group) {
          // With no course selected, every optgroup is hidden (no `data-course`
          // value can equal "" by construction — course ids are never blank).
          var match = !!course && courseOf(group) === course;
          group.hidden = !match;
          Array.prototype.forEach.call(
            group.querySelectorAll("option"),
            function (opt) {
              opt.hidden = !match;
            }
          );
        }
      );
      // The empty "— none —" option carries no data-course (see create_option's
      // guard) and lives outside any optgroup, so the loop above never touches
      // it — it is how a group is detached and must never be hidden.
      var selectedOpt = select.options[select.selectedIndex];
      if (
        selectedOpt &&
        selectedOpt.hasAttribute("data-course") &&
        selectedOpt.getAttribute("data-course") !== course
      ) {
        // A hidden-but-still-selected option would post a mismatched
        // allocation and return the very field error this filter exists to
        // prevent.
        select.value = "";
      }
    }

    courseSel.addEventListener("change", apply);
    apply();
  }
})();
