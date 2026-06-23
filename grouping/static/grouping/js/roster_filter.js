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

  function initRoster(root) {
    var list = root.querySelector("[data-roster-list]");
    if (!list) return;

    var cohortSel = root.querySelector("[data-roster-cohort]");
    var search = root.querySelector("[data-roster-search]");
    var shownEl = root.querySelector("[data-roster-count]");
    var selectedEl = root.querySelector("[data-roster-selected]");
    var items = itemsOf(list);

    function itemName(item) {
      var explicit = item.getAttribute("data-name");
      return (explicit !== null ? explicit : item.textContent).toLowerCase();
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

    if (cohortSel) cohortSel.addEventListener("change", applyFilter);
    if (search) search.addEventListener("input", applyFilter);
    list.addEventListener("change", updateSelected);
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
})();
