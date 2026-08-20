"use strict";
// The allocation assignment grid (allocation_assign.html): a live summary and
// row-state recompute driven by the PENDING radio selection, plus name/cohort
// filters. Progressive enhancement: with JS off the server-rendered grid still
// works exactly as-is — native radios, a static summary, no filters. Every
// input stays in the DOM; filtering only ever sets `hidden`, never `disabled`
// (a disabled input is dropped from the POST, silently changing what saves).
(function () {
  var summary = document.querySelector("[data-grid-summary]");
  var rows = Array.prototype.slice.call(
    document.querySelectorAll("[data-grid-row]")
  );
  if (!rows.length) return; // an empty state page has no grid to wire

  var searchInput = document.querySelector("[data-grid-search]");
  var cohortSelect = document.querySelector("[data-grid-cohort]");
  var sections = Array.prototype.slice.call(
    document.querySelectorAll("[data-grid-section]")
  );

  var assignedEl = summary && summary.querySelector("[data-grid-assigned]");
  var unassignedEl = summary && summary.querySelector("[data-grid-unassigned]");
  var conflictEl = summary && summary.querySelector("[data-grid-conflict]");

  // The pending state of a row: whichever radio in its group is currently
  // checked, not what the server last saved. A conflict row starts with NONE
  // checked (the row union's third state), so "nothing checked" IS the
  // conflict reading — never a bug to guard against.
  function rowState(row) {
    var radios = row.querySelectorAll('input[type="radio"]');
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) {
        return radios[i].value === "" ? "unassigned" : "assigned";
      }
    }
    return "conflict";
  }

  // Row-state classes and the non-colour markers follow the SAME
  // pending-selection rule as the summary (spec row 36): recomputed here, on
  // every radio change, from the checked radio — never left at the
  // server-rendered state until save.
  function refreshRow(row) {
    var state = rowState(row);
    row.classList.remove("is-assigned", "is-unassigned", "is-conflict");
    row.classList.add("is-" + state);
    // Both marker spans are always present (allocation_assign.html renders
    // one hidden) — toggle the EXISTING, already-{% trans %}'d element.
    // Composing "not placed"/"conflict" text here would leak English onto a
    // Polish page exactly as a JS-composed summary would (spec row 35b).
    var warn = row.querySelector(".badge--warn");
    var danger = row.querySelector(".badge--danger");
    if (warn) warn.hidden = state !== "unassigned";
    if (danger) danger.hidden = state !== "conflict";
  }

  // The summary always covers EVERY row, filtered or not (spec row 35: a
  // filter must never change these counts) — this never reads `row.hidden`.
  // And it only ever substitutes a number into an already-translated span;
  // the surrounding "Students: " / "Assigned: " text is server-rendered and
  // untouched, so this can never leak an English literal onto a Polish page.
  function refreshSummary() {
    if (!summary) return;
    var counts = { assigned: 0, unassigned: 0, conflict: 0 };
    rows.forEach(function (row) {
      counts[rowState(row)] += 1;
    });
    if (assignedEl) assignedEl.textContent = String(counts.assigned);
    if (unassignedEl) unassignedEl.textContent = String(counts.unassigned);
    if (conflictEl) conflictEl.textContent = String(counts.conflict);
  }

  function onGridChange(evt) {
    var radio = evt.target;
    if (!radio || radio.type !== "radio") return;
    var row = radio.closest ? radio.closest("[data-grid-row]") : null;
    if (row) refreshRow(row);
    refreshSummary();
  }

  rows.forEach(function (row) {
    row.addEventListener("change", onGridChange);
  });

  // --- Filters: hide only, never disable; match data-name/data-cohort only. ---

  function rowName(row) {
    var explicit = row.getAttribute("data-name");
    return (explicit !== null ? explicit : "").toLowerCase();
  }

  function matchesCohort(row, cohort) {
    if (!cohort) return true; // "" -> All cohorts
    var rowCohort = row.getAttribute("data-cohort") || "";
    // The sentinel is deliberately NOT "" (that would tie with "All cohorts"
    // under a straight `!cohort || rowCohort === cohort` port of
    // roster_filter.js and show every row instead of isolating outsiders —
    // spec row 35c). It gets its own branch instead.
    if (cohort === "__none__") return rowCohort === "";
    return rowCohort === cohort;
  }

  function applyFilter() {
    var term = searchInput ? searchInput.value.trim().toLowerCase() : "";
    var cohort = cohortSelect ? cohortSelect.value : "";
    rows.forEach(function (row) {
      var matchName = !term || rowName(row).indexOf(term) !== -1;
      row.hidden = !(matchName && matchesCohort(row, cohort));
    });
    sections.forEach(function (section) {
      var heading = section.querySelector("[data-grid-section-heading]");
      if (!heading) return;
      var sectionRows = Array.prototype.slice.call(
        section.querySelectorAll("[data-grid-row]")
      );
      // An empty section (no rows at all, e.g. "(no students)") has nothing
      // for the filter to hide FROM — its heading stays put, so that note
      // never disappears just because a search term is active.
      heading.hidden =
        sectionRows.length > 0 && sectionRows.every(function (r) { return r.hidden; });
    });
  }

  if (searchInput) searchInput.addEventListener("input", applyFilter);
  if (cohortSelect) cohortSelect.addEventListener("change", applyFilter);
  applyFilter();
})();
