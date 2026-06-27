# Phase 3c-iii-b — Analytics per-student cherry-pick subset: design

**Date:** 2026-06-28
**Status:** Spec (awaiting review)
**Depends on:**
- Phase 3c-ii (analytics matrix — `analytics_matrix` view, `build_progress_matrix` /
  `build_results_matrix` in `courses/rollups.py`, `analytics_scope_choices` /
  `students_in_scope` in `grouping/scoping.py`, the `/manage/courses/<slug>/analytics/`
  surface, the matrix template + horizontal-scroll wrapper). The matrix this slice narrows.
- Phase 3c-iii-a (the URL-state machinery this slice extends: `_clean_expand` / `_expand_qs` /
  `_decorate_links` / `_matrix_redirect` in `courses/views_analytics.py`; the repeatable
  `expand` param pattern; the freeze-panes matrix template with the **frozen Student column**;
  `reviewable_students` per-row breakdown gating). The cherry-pick subset rides the exact same
  self-cleaning, no-JS-required, server-rendered state mechanism `expand` established.

## Goal

Let a teacher **narrow the analytics matrix to an arbitrary subset of the students already in
the current scope** — a cherry-pick filter on top of the All / group / collection scope picker.
The teacher checks the students to keep, hits **Apply**, and the matrix re-renders with only
those rows (and its Average row, expand columns, and breakdown links following along). A
**Clear** resets to the full scope; a **Select-all** convenience checks everyone at once so the
common "show the majority — everyone except a couple" case is one click plus a few unchecks.

This is **3c-iii slice b** (cherry-pick half only). It adds **no model field and no migration** —
the subset is pure URL state, exactly like 3c-iii-a's `expand`. The per-group / per-collection
colour-band override (the other half the roadmap once bundled here) is **deferred to a later
slice (3c-iii-c)** — it is the one part that needs a schema migration, and keeping it out
preserves this slice as a focused read-only addition.

## Locked decisions (from brainstorming)

1. **Cherry-pick only this slice.** The per-group/collection colour-band override is split out to
   3c-iii-c (its own spec→plan→build). This slice ships no migration.
2. **Filter *within* scope, not a standalone mode.** The scope picker (All my students / a group /
   a collection) sets the **candidate pool**; the cherry-pick subset **narrows that pool**. The
   subset is always a subset of `students_in_scope(user, course, scope)` — it can only ever
   *narrow* what scope already authorizes, never widen reach.
3. **State = a repeatable `student` URL param**, same shape and discipline as `expand`
   (`?scope=…&mode=…&expand=…&student=<pk>&student=<pk>…`). Stateless, shareable, self-cleaning.
   **No DB, no session, no saved-per-teacher selection.**
4. **The load-bearing rule: empty subset ⇒ no filter (show the full scope).** A non-empty
   effective subset shows only those students; an empty one shows everyone in scope. This makes
   Clear trivial (drop all `student` params) and makes it **impossible to render an empty matrix**
   by unchecking everything — unchecking all and applying is just another way to Clear.
5. **Average over the subset.** When a subset is active the matrix is rebuilt with the **narrowed
   queryset**, so the Average row and `overall_average` recompute over exactly the displayed
   students ("how are *these* doing"). This falls out for free from passing a filtered queryset to
   the existing builder — **no second/baseline average, no builder change.**
6. **Interaction = row checkboxes + Apply + Clear**, server-rendered GET form, no-JS-functional.
   A **Select-all** toggle in the Student header is a **JS progressive enhancement** (checks/
   unchecks all *rendered* row checkboxes); no-JS users check individually. Growing an
   already-narrowed view is **Clear-then-repick** (acceptable: the "check majority" workflow
   starts from the full view, where Select-all + a few unchecks lands it in one pass).
7. **Checkbox placement = inside the existing frozen Student column** (Approach A), not a new
   column. The Student column is already `position:sticky` from 3c-iii-a's freeze-panes work;
   the checkbox sits just before the name in that same cell. No new frozen column, no sticky-
   offset / z-index recomputation, minimal CSS.
8. **Effective subset round-trips, not the raw request** — the pks actually present in the scope
   pool (forged / out-of-scope / non-int dropped), exactly as `expand` round-trips its reached
   `expanded_nodes` pks. The subset is preserved across every *state-preserving* navigation
   (Apply, the Progress/Results toggle, expand/collapse, the breakdown link **and its back
   link**, the Configure-colours round-trip) but is **deliberately reset by a scope change**
   (decision #9), so a scope switch always shows the new scope in full.
9. **A scope change resets the subset.** Changing the scope picker is a "start fresh on a new
   roster" gesture, so it must **not** carry the current checkboxes. This is realized
   structurally (§3): the scope picker lives in a **separate form** that submits only
   `scope`/`mode`/`expand` (no `student`), while the checkboxes live in the table form. This
   avoids the widening trap — `students_in_scope(user, course, "all")` is a *superset* of every
   group/collection, so if the scope form carried a group's checked pks into an "All my students"
   switch they would all survive the `∩ pool` step and silently filter "All" down to that one
   group. Resetting on scope change is both least-surprising and removes that trap by
   construction. (The `∩ pool` self-clean still runs on every request as defense-in-depth against
   forged/stale `student` pks arriving by hand-edited URL.)

## Non-goals

- **Per-group / per-collection colour-band override** — deferred to **3c-iii-c** (needs the
  migration).
- **Saved / persistent selection** (per-teacher, per-course, session-backed) — rejected in favour
  of stateless URL state (decision #3); raises whose/which-course storage questions this slice
  doesn't need.
- **Cross-scope selection** — the subset is always within the current scope's pool (decision #2);
  no "pick students from several groups at once".
- **A separate picker form / modal** — rejected in favour of in-matrix row checkboxes (decision
  #6), which keep the selection in the context the teacher is already reading.
- **Server-side Select-all (no-JS)** — Select-all is a JS convenience only; the no-JS path stays
  fully functional without it (decision #6).
- **Any change to scope semantics, the breakdown page *content*, the bands page band logic,
  drill-down (`expand`), the builders' aggregation, or gating.** This slice only adds a row filter
  and threads one more param. (The breakdown *view* gains exactly one thing — echoing the `student`
  subset into its `back_url`, C1 in §2 — but renders the same whole-roster content; the bands
  *view/template* gain only the `student` round-trip, not new band behaviour.)
- CSV/print export, charts, trend-over-time, cross-course dashboards.

## Architecture

### 1. State — the `student` subset param

The matrix URL gains a **repeatable `student` query param**. The view parses it with the **same
discipline as `expand`**: read `request.GET.getlist("student")`, keep entries that parse as
`int`. This is the **raw requested subset**. (Dedup is *not* done by `_clean_expand` — that helper
returns a plain list with duplicates intact; today the view dedupes by wrapping
`set(_clean_expand(...))`, line 49. The subset becomes a set the same way — by the `set()` wrap
and, ultimately, by `∩ pool` set membership — so reusing `_clean_expand` as-is is fine *provided*
the result is put through a set, not consumed as a list.)

**Effective subset = raw ∩ scope pool.** The scope pool is the existing
`students_in_scope(user, course, scope)` queryset. The view intersects the raw pks with the pool's
pks; the result is the **effective subset** — the pks that are *both* requested *and* authorized-
and-present. Forged pks, pks from another scope, pks of students who left the group, and non-int
junk all drop here. This is the single security-relevant step: **the subset can only narrow the
already-authorized pool, never widen it.**

**Applying the filter (decision #4):**
- effective subset **non-empty** → `pool.filter(pk__in=effective)` — the matrix shows only those.
- effective subset **empty** (none requested, or all requested pks dropped) → use the **full
  pool** — no filter. So an empty/forged/cleared subset is indistinguishable from "show all", and
  the matrix is never empty *because of* the filter (it can still be empty if the scope itself has
  no students — the existing 3c-ii empty-state).

The narrowed (or full) queryset is passed to the **existing builder unchanged**
(`build_progress_matrix` / `build_results_matrix`, with the existing `expand` set). Averages,
expand columns, `None`≠`0`, no-N+1 — all inherited untouched; the builder neither knows nor cares
that its `students` argument was filtered.

### 2. View — `courses/views_analytics.py` (`analytics_matrix`, extended)

Same URL `/manage/courses/<slug>/analytics/`, same `can_review_course`-or-404 gate, same
`scope` / `mode` / `expand` handling. Added:

- **Parse the subset.** A small helper mirroring `_clean_expand` (or a reuse of it — it is a
  generic "list of strings → list of ints, junk dropped"; the plan decides whether to reuse
  `_clean_expand` directly or add a thin `_clean_pks` alias). Produces the raw pk list.
- **Compute pool, then effective subset, then students.** Resolve `students_in_scope` once
  (already done today), intersect to get the effective subset, branch per decision #4 to get the
  final `students` queryset, keep the existing `.order_by("username")`.
- **Round-trip the *effective* subset through the anchor hrefs (decision #8).** Extend
  `_expand_qs` (today `_expand_qs(scope, mode, expand_pks)`) to also take and emit the subset pks.
  This one signature change threads the subset through the **anchor navigation links** the view
  builds via `_expand_qs` / `_decorate_links` / `_matrix_redirect`: the Progress/Results toggle,
  the Configure-colours link, the `expand`/`collapse` header links, the per-row breakdown links,
  and the Clear link. **Determinism (M2):** emit the subset pks in a **fixed order — sorted
  ascending** — so the round-tripped URLs are stable and exact-URL tests aren't brittle (`expand`
  already round-trips a deterministically ordered list; the subset must do the same rather than
  iterate a `set`). The *contract* (every anchor nav link preserves the subset) is fixed; the
  exact `_expand_qs` signature (extra positional arg vs. a small state object) is a plan detail.
  - **What `_expand_qs` does NOT thread (correcting a mechanism detail):** the two GET **forms**
    do not get their `student` state from `_expand_qs`. The scope form deliberately omits
    `student` (decision #9 — scope change resets the subset). The table form carries the subset
    via its **row checkboxes** (the checked boxes ARE the `student=` params on submit), with
    `scope`/`mode`/`expand` as template-rendered hidden inputs (a `{% for %}` loop, exactly as the
    template renders hidden `expand` today, line 17). So an implementer must **not** also add
    hidden `student` inputs to the table form — that would double-submit each pk alongside its
    checkbox.
- **Tell the template which rows are checked.** Pass the effective-subset set so the template can
  render each checkbox `checked` iff the row's student pk is in it. When the subset is empty, no
  box is checked and every scope row is shown (the pick-from-scratch state); when non-empty, every
  *rendered* row is checked (they are the subset) — unchecking and Apply shrinks, Clear regrows.
- **Breakdown back-link must preserve the subset (C1).** `analytics_student` builds its `back_url`
  from its own `request.GET` (today `…?{_expand_qs(scope, mode, expand_pks)}`, line 159) and does
  not read `student`. Since the matrix's per-row breakdown link now carries the subset into the
  breakdown URL, `analytics_student` must **read `request.GET.getlist("student")`, int-clean it
  (`_clean_expand` only — NOT `∩ pool`; this view resolves no scope pool, and the pks were already
  intersected when the matrix built the link, so the matrix re-cleans them on return), sort, and
  pass them through the extended `_expand_qs` when building `back_url`** — otherwise drilling into a
  student and clicking Back returns the teacher to the *full* scope, silently dropping the filter
  and violating the round-trip contract. (The breakdown's own content is whole-roster and ignores
  the subset — it only echoes it back into `back_url`.)
- **`_matrix_redirect` (POST→GET on the bands page) and `analytics_bands`** carry the subset too —
  so saving/resetting colours, which already round-trips `expand`, also preserves the subset.
  Concretely: `_matrix_redirect` reads `request.POST.getlist("student")` (int-cleaned, sorted) into
  the redirect querystring; the `analytics_bands` view reads the subset from
  **`src.getlist("student")`** — the same `src = request.POST if POST else request.GET` source it
  already uses for scope/mode/expand (lines 186, 205–207), int-cleaned — and passes it into its
  template context; and the bands template renders hidden `student` inputs (see §3). (Bands gate
  and band logic
  unchanged, exactly as 3c-iii-a left `expand`.)

**Gating unchanged (decision #2 / §1).** Breakdown links stay gated by `reviewable_students`
(3c-iii-a). The subset filter sits *after* scope authorization and only removes rows, so it
introduces no new reach. A forged `student` pk can't surface a student outside the pool (it's
intersected away) and can't drill into one (the breakdown view's own 404 guard is unchanged).

### 3. Templates — `analytics_matrix.html` and `analytics_bands.html`

Two templates change. `templates/courses/manage/analytics_matrix.html` gets the checkboxes +
controls; `templates/courses/manage/analytics_bands.html` gets one hidden-input loop (I2 below).

HTML forbids *nested* forms but allows sibling forms; the matrix cells already contain only `<a>`
links (expand / collapse / breakdown) and the controls row a `<select>` + anchor toggles — **all
form-safe**. So:

- **Two sibling GET forms, not one (decision #9).** Keep the existing `.analytics__controls` form
  as the **scope form** — the auto-submitting `scope` select plus `mode` + `expand` hidden inputs,
  and **no `student`**, so changing scope resets the subset. Add a **second, sibling table form**
  wrapping the `<table>`, carrying the row checkboxes plus its **own** hidden `mode`/`scope`/
  `expand` inputs (rendered by the same `{% for %}`-loop pattern, line 17) so that **Apply**
  preserves the current scope/mode/expand while applying the checked subset. The two forms are
  siblings (no nesting). The anchor links inside the table (expand/collapse, breakdown) are
  unaffected — anchors don't submit a form; each already carries full state (now incl. the subset)
  in its href.
- **Row checkbox in the frozen Student cell (decision #7).** In each `<tbody>` row's
  `.analytics__rowhead` `<td>`, render `<input type="checkbox" name="student" value="{{ pk }}"
  {% if checked %}checked{% endif %}>` before the existing name / breakdown-link markup. One
  small CSS rule aligns it; no new column, no freeze-pane change.
- **Apply + Clear.** **Apply** is the **table form's** submit button — so it renders **whenever
  there are rows** (the table form wraps the `<table>`, which today lives only in the rows-present
  branch). It must work *with* JS — checking boxes needs an explicit submit; this is unlike the
  scope form's `<noscript>`-only fallback. **Clear** is an `<a>` link to the matrix URL with the
  **same scope/mode/expand but no `student` params** (built via the extended `_expand_qs`).
- **The "N selected" indicator — one fixed contract.** A small **"N selected"** label (N = the
  **effective subset size**, which the view already has — *not* "Showing N of M", which would
  require a full-scope pool count the view does not otherwise compute). It renders **only when a
  subset is active** (a `student` param present / effective subset non-empty); it is **hidden in
  the no-subset state** ("0 selected" / "Showing M of M" reads oddly) **and in the no-rows state**.
  This single rule covers every state, so the count's appearance is a fixed contract, not an
  implementer guess.
- **No-rows visibility (M3).** When `matrix.rows` is empty the template renders a `<p>` empty-state
  instead of a `<tbody>`, so the table form, its checkboxes, and Apply **do not render at all** in
  that branch. Rule: **show Clear whenever a `student` param is present in the request** (even with
  zero rows), so a teacher who filtered into an empty intersection can escape back to the full
  scope. The plan must place Clear (and the scope form) so they survive the empty-state branch —
  i.e. in the always-rendered controls header **outside** the `{% if matrix.rows %}` table block,
  not inside the `<tbody>`.
- **Bands template (`analytics_bands.html`) — one hidden-input loop (I2).** The bands form already
  renders hidden `scope`/`mode` inputs and a `{% for pk in expand_pks %}` hidden-`expand` loop
  (lines 12–14). Add a parallel `{% for pk in subset %}<input type="hidden" name="student"
  value="{{ pk }}">{% endfor %}` so Save/Reset POST the subset, which `_matrix_redirect` reads back
  (§2). No other bands-template change.
- **Select-all (JS progressive enhancement).** A checkbox in the Student **header** `<th>` (which
  `rowspan`s the body) whose change handler toggles every rendered row checkbox. Pure enhancement:
  a tiny inline/script-file handler, `hidden`/inert with no-JS, and never required to produce a
  valid subset. The plan picks the script location (matching the project's existing
  scope-auto-submit JS convention).
- **No-JS path.** Scope auto-submit already degrades to the `<noscript>` Apply; checkboxes +
  Apply submit a normal GET; Clear is a link. Everything works without JS except the one-click
  Select-all.

### 4. UI / i18n

**Bespoke, token-driven, dark-mode-aware**, matching the 3c-ii / 3c-iii-a matrix. No new visual
language — a checkbox, two buttons/links, and a count.

- The checkbox is visually quiet (it shares the frozen Student cell with the name); the Average /
  Overall / header cells have **no** checkbox.
- **i18n:** EN + PL for every new string at build time (the recurring project requirement): the
  **Apply** button, **Clear** / "Show all" link, the **Select-all** aria-label, the checkbox
  per-row aria-label (e.g. "Select <student>"), and the "**N selected**" indicator. Compile `.mo`;
  clear any stray `#, fuzzy`; drop obsolete `#~` msgids so the repo's `test_po_catalog_clean`
  meta-test stays green (the 3c-iii-a i18n lesson).

### 5. Access — unchanged

`can_access_course` / `can_manage_course` / `can_review_course` / `reviewable_students` are
untouched. The subset filter adds no permission and no schema change; it only removes rows from an
already-authorized, already-rendered matrix. The view reach stays `can_review_course`; per-row
breakdown gating stays `reviewable_students`; the bands page stays `can_manage_course`.

## Edge cases

| Case | Behavior |
|---|---|
| `student` empty / absent | No filter → matrix shows the full scope (decision #4). Clear is shown whenever a `student` param is present in the request (M3), so it's absent here. |
| `student` names a pk **not in the current scope pool** (foreign group, left the group, forged) | Intersected away → not in the effective subset; if that empties the subset, the full scope shows. No leak, no 404 (the matrix simply doesn't include a row it never would have). |
| Non-integer `student` value (`?student=abc`) | Dropped during sanitization; ignored. |
| All requested pks drop (all forged / all out-of-scope) | Effective subset empty → full scope (decision #4) — never an empty matrix *from the filter*. |
| Uncheck every box and Apply | Submits zero `student` params → empty subset → full scope (Apply-with-none == Clear). |
| Select-all then Apply (no unchecks) | Subset == the whole scope pool → same rows as no filter; round-trip still records them (harmless; equivalent view). |
| Switch scope while a subset is active | **The subset is reset** (decision #9): the scope form does not carry `student`, so changing scope always shows the new scope in full. This avoids the widening trap — switching a fully-checked group to "All my students" must NOT silently filter "All" down to that group (since `students_in_scope("all")` is a superset of every group, intersection alone wouldn't drop the pks). |
| Subset active + a column expanded (`expand` set) | Orthogonal — `expand` regroups columns, `student` filters rows; both round-trip together; the builder gets the narrowed students *and* the expand set. |
| Subset of 1 student | Single-row matrix; Average row == that student's row. |
| Breakdown link for a subset row | Unchanged — rendered iff the student ∈ `reviewable_students` (3c-iii-a gating); the subset never widens this. |
| Scope itself has no students | Existing 3c-ii "No students in this scope" empty-state — independent of the subset. |
| URL length with a large subset | Bounded by the scope size; the feature's purpose is narrowing, so real subsets are small. Worst case (~all of a big group) is a few hundred chars — well under browser/server limits. No cap needed. |
| Non-staff / out-of-reach user hits the matrix URL with `student` params | **404** at the `can_review_course` gate (never reaches subset parsing); manage convention. |

## Testing

- **View — subset parsing & application** (`analytics_matrix`):
  - a non-empty in-scope `student` set narrows `matrix.rows` to exactly those students, in the
    existing `username` order;
  - **empty / absent `student`** → full scope (no filter); **all-forged / all-out-of-scope** →
    full scope (decision #4, the no-empty-matrix guarantee);
  - a **mixed** request (some valid, some forged) → only the valid in-scope pks survive (effective
    = raw ∩ pool);
  - **Average over subset** — `overall_average` / per-column averages computed over the narrowed
    set differ from the full-scope average where expected (a focused assertion on a known fixture);
  - **round-trip** — the toggle / colours / breakdown / Clear anchor links each carry the effective
    `student` pks **in sorted order** (M2), and the table form's checkboxes are `checked` for the
    effective pks; assert on the built URLs / rendered form, mirroring the 3c-iii-a `expand`
    round-trip tests. (Assert the **scope form carries NO `student`** — decision #9.);
  - **scope change resets the subset (I1)** — a `student` set valid for group A submitted under a
    switch to "All my students" (or to another scope) yields the **full new scope**, not a silently
    filtered one; the scope form emits no `student`;
  - **breakdown back-link preserves the subset (C1)** — open the matrix with a subset → follow a
    row's breakdown link → assert the breakdown page's `back_url` carries the same `student` pks
    (sorted) plus scope/mode/expand;
  - **orthogonality with `expand`** — subset + an expand set together: rows narrowed *and* columns
    expanded, both preserved in links;
  - **gating unchanged** — a forged subset pk never produces a breakdown link or a row for a
    student outside the pool; the per-row `reviewable_students` link gating is unaffected.
- **`_expand_qs` extension** (or whatever the helper becomes) — emits `scope`/`mode`/`expand` **and**
  `student` (repeatable), dropping `student` when the subset is empty; a focused unit test on the
  querystring output.
- **Bands round-trip** — saving / resetting colours on `analytics_bands` preserves the `student`
  subset in the post-save redirect (extends the 3c-iii-a `expand`-preservation test).
- **Template** — the matrix page has **two sibling `<form method="get">`s** (the scope form with
  no `student`; the table form with checkboxes + hidden scope/mode/expand); each body row carries a
  `name="student"` checkbox `checked` iff in the subset; the Average/Overall/header rows carry no
  row checkbox; **Apply renders when there are rows and is absent in the zero-rows empty-state**
  (I1); Clear renders whenever a `student` param is present (incl. the zero-rows empty-state, M3);
  the "N selected" count renders **only when a subset is active** and is hidden in the no-subset and
  no-rows states; the Select-all header control is present.
- **i18n** — the new msgids have PL translations; `.mo` compiled; `test_po_catalog_clean` green
  (no `#, fuzzy`, no `#~`).
- **e2e (real gestures — no `page.evaluate` shortcuts; the e2e-must-drive-real-UI lesson)** — a
  teacher opens the matrix → clicks **Select-all** → unchecks two students → clicks **Apply** →
  the matrix shows the rest, Average reflects them → clicks **Clear** → the full scope returns.
  (Driven with `-m e2e`, since addopts defaults to `-m "not e2e"`.)

## Decisions deferred to the implementation plan

- Whether to reuse `_clean_expand` directly for the `student` list or add a thin `_clean_pks`
  alias / rename (the *behavior* — list-of-strings → deduped ints, junk dropped — is fixed).
- The exact shape of the `_expand_qs` extension (an extra positional `subset_pks` arg vs. a small
  immutable state object threaded through `_decorate_links` / `_matrix_redirect`); the *contract*
  (every nav link preserves the effective subset) is fixed.
- Exact UI copy for the Apply / Clear / Select-all controls and the "N selected" count (the
  *form* of the count is fixed — effective-subset size, subset-active only, §3; only the wording
  is open), and whether Clear is a button or a link.
- Select-all script location (inline vs. a static JS file) and how it matches the existing
  scope-auto-submit JS convention.
- The CSS for the in-cell checkbox alignment (a single rule on `.analytics__rowhead`).
- Whether the "N selected" indicator counts the effective subset or the rendered rows (identical
  when a subset is active; differs only in the empty/all state — a copy choice).
