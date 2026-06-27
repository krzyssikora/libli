# Phase 3c-iii-a — Analytics drill-down: design

**Date:** 2026-06-27
**Status:** Spec (awaiting review)
**Depends on:**
- Phase 3c-ii (analytics matrix — `analytics_matrix` view, `build_progress_matrix` /
  `build_results_matrix` in `courses/rollups.py`, `course_color_bands` / `band_for`,
  `analytics_scope_choices` / `students_in_scope`, the `/manage/courses/<slug>/analytics/`
  surface, the matrix template + horizontal-scroll wrapper). The matrix this slice makes
  interactive.
- Phase 3c-i (`reviewable_students(user, course)`, `can_review_course(user, course)` in
  `grouping/scoping.py`; the review views/URLs `courses:manage_review_submission` the
  breakdown cross-links to; the `/manage/courses/<slug>/…` manage convention, 404-not-403).
- Phase 2e / `courses/rollups.py` `build_outline(course, user)` (nested tree + per-unit
  `completed` + `required`/`additional` rollups) and `build_course_results(course, student)`
  (per-quiz rows carrying `status` ∈ {not_started, in_progress, awaiting_review, submitted},
  `score`, `max_score`, `pending`, `url_name`). The breakdown composes these two.
- `courses/rollups.py` `_walk_preorder` / `is_obligatory_lesson` / `is_quiz_unit` /
  `submission_is_counted` / `_quiz_review_maps` (the shared single-source traversal + counted
  predicates the drill-down must reuse, never re-derive).

## Goal

Make the 3c-ii analytics matrix **drill down**. Two interactions, both read-only:

1. **Column drill-down** — a teacher clicks a chapter/part column header and it expands
   *inline* into sub-columns for its children (sections → units), recursively, with no client
   framework. State lives in the URL.
2. **Per-student breakdown** — a teacher clicks a student's name and lands on a focused
   read-only page showing that student's whole course tree with per-unit lesson completion
   **and** per-quiz score + status (the per-submission status the 3c-ii spec parked here).

This is **3c-iii slice a**. It adds no model fields and no migration — it is pure
read/compute over existing data. The matrix stays the single configurable matrix; drill-down
only changes *which columns* it shows and makes its rows/headers clickable.

## Locked decisions (from brainstorming)

1. **3c-iii is split into two slices.** **3c-iii-a (this spec)** = column drill-down +
   per-student breakdown — the interaction-heavy "go deeper" pair the 3c-ii spec named.
   **3c-iii-b (next cycle, its own spec/plan)** = per-student cherry-pick subset + per-group
   colour-band override — two independent matrix refinements, one needing a schema migration.
   The split keeps each slice a focused spec→plan→build (the project cadence) and keeps the
   one migration out of this read-only slice.
2. **Recursive inline column expand**, not a focused sub-view page and not single-level. The
   matrix re-renders with the clicked column replaced by its children; children can themselves
   be expanded further, to any depth. The recursion is made safe by modelling state as a
   *sanitized set of node pks* and computing columns as a *pure frontier function* (§3) — the
   stale-pk cascade (the usual drill-down bug class) is structurally avoided, not patched.
3. **Header style = chip bar + flat headers**, not nested colspan group headers. The matrix
   header stays a single flat row; an "Expanded: …" chip bar above the matrix lists the
   expanded columns (breadcrumb-labelled), each chip carrying a ✕ collapse link. This avoids
   multi-level `<thead>` rendering entirely while delivering recursive drill-down. The chip
   bar is hidden when nothing is expanded.
4. **Clickable surface:** the **student name** links to that student's breakdown; a **column
   header that has children and is not yet expanded** is an expand link; data **cells stay
   non-interactive** (colouring every cell as a link is noisy). The **Average row** and the
   **Overall column** are never drill targets (one is an aggregate, the other already spans
   the whole course).
5. **Per-student breakdown = full outline, both modes** (not mode-scoped, not a redirect to
   the student-facing results page). One teacher-facing read-only page composing
   `build_outline` (tree + lesson completion) and `build_course_results` (per-quiz status +
   score) for that student.
6. **Review cross-link:** a quiz shown **awaiting_review** on the breakdown links into the
   existing 3c-i review view (`courses:manage_review_submission`) — pure URL reuse, no new
   review logic. The page gate already guarantees the viewer can review the course; the link
   is rendered only for an `awaiting_review` quiz that has a submission to review.
7. **State via GET query params**, server-rendered, no-JS-required — matching 3c-ii and the
   project convention. Drill-down adds a **repeatable `expand` param**
   (`?scope=…&mode=…&expand=<pk>&expand=<pk>…`). Every link round-trips the full
   `scope`/`mode`/`expand` state so no control silently resets another (the 3c-ii
   state-preservation rule, extended to `expand`).
8. **No new model fields, no migration.** Drill-down is read/compute only. (3c-iii-b adds the
   one schema field this phase needs.)

## Non-goals

- Per-student cherry-pick subset filter — **3c-iii-b**.
- Per-group / per-collection colour-band override — **3c-iii-b**.
- Nested colspan group headers — explicitly rejected in favour of the chip bar (decision #3).
- A focused per-column sub-view *page* — rejected in favour of inline expand (decision #2).
- Editing any student/quiz/band data from the drill-down (read-only; band editing stays on
  the untouched `analytics_bands` page).
- Per-cell drill (clicking an individual student×column cell) — the student name → whole-course
  breakdown already gives the full per-unit detail; a column-scoped per-student view is
  unnecessary.
- Drill-down *inside* the breakdown (it is already fully expanded — the whole tree).
- CSV/print export, charts, trend-over-time, cross-course dashboards, notifications.

## Architecture

### 1. The frontier model (column drill-down state)

**State.** The matrix URL gains a repeatable `expand` query param. The view parses it into a
**sanitized set of integer node pks**: read `request.GET.getlist("expand")`, keep entries that
parse as `int`, dedupe into a `set`. No per-pk existence check is required for *correctness*
(unreachable pks are inert — see below); an optional intersection with the course's node pks is
a tidiness refinement, settled in the plan.

**Frontier (pure function), `frontier_columns(course, expanded_pks)` in `courses/rollups.py`:**
build the column tree from **one `course.nodes` query + a `parent_id`-grouped recursion** —
exactly as `build_matrix_columns(course)` does today (a flat `_walk_preorder` generator is
*insufficient*: the frontier needs conditional recursion that *stops* at a non-expanded node, a
per-node "has children" test, and ancestor context for breadcrumb titles, none of which the flat
stream provides). It does **not** use `build_outline`, which needs a `user` and computes
per-unit completion the frontier does not. From the roots, for each node, **if
its pk ∈ `expanded_pks` *and* it has children → recurse into the children; else → the node is a
column.** The base case is **any node with no children** — a non-expandable column; this covers
leaf units **and** an empty structural node (a childless chapter/section, which renders as a
non-expandable `None`-valued column). Columns come out in outline (pre-order) order. This is the
entire correctness surface for drill-down and it is a pure function of (tree, pk-set),
unit-testable in isolation, taking no `user`.

**Relationship to `build_matrix_columns` (I4).** The existing `build_matrix_columns(course)`
(rollups.py:285) returns the depth-1 roots, each carrying its subtree's `lesson_pks` /
`quiz_pks` sets, and is called by both builders. `frontier_columns` **generalizes and replaces
it**: it returns the *frontier* nodes (roots when `expanded` is empty — identical to today),
each carrying the same `lesson_pks` / `quiz_pks` sets computed in the **one** structural walk.
So both builders keep doing a single `course.nodes` walk (the constant-query guarantee holds),
and `frontier_columns(course, set())` reproduces the same **column nodes, order, and
`lesson_pks`/`quiz_pks`** as `build_matrix_columns(course)` (functional equivalence — the per-
column dict additionally carries `depth`/`expandable`, so it is a *superset* shape, not byte-
identical).

Properties this buys:

- **Stale / forged pks are inert.** If a parent is collapsed (its pk removed) but a descendant
  pk lingers in the URL, the walk stops at the collapsed parent and never reaches the
  descendant — so the lingering pk has no effect. **No cascade-removal of descendant pks on
  collapse is needed** (the bug-prone heart of drill-downs is thereby avoided). A pk that names
  no node, or a leaf-unit pk, is likewise never acted on.
- **Aggregation already exists.** Each frontier column aggregates over **its subtree's relevant
  units** — exactly the per-node subtree logic the 3c-ii builders already compute for roots.
  Recursion only applies that logic to finer nodes; it introduces no new aggregation rule.

**Return shape — columns AND the active-expanded list (C1, I5).** Note that an expanded node is
*recursed past* and is therefore **never itself a column** — so a per-column `expanded` flag
would always be false (dead), and the actively-expanded ancestor nodes the chip bar must list
are not in the column list at all. `frontier_columns` therefore returns **two** ordered lists:

- **`columns`** — the frontier nodes (the leaves of the expansion), each with: `node`, `title`
  (breadcrumb-style — see §6), `depth`, `lesson_pks`, `quiz_pks`, and `expandable` (has children
  and pk ∉ expanded → renders an expand link). The `{"node": …, "title": …, "lesson_pks": …,
  "quiz_pks": …}` shape stays a superset of what 3c-ii's builders/template already consume, so
  the un-expanded matrix renders unchanged.
- **`expanded_nodes`** — the ordered list of nodes that were **actively recursed through** (pk ∈
  `expanded` *and* has children), each with a breadcrumb `title` and its pk. **The chip bar
  renders from this list, not from `columns`.** Because it is built from the walk (only nodes the
  walk actually reached), collapsing an ancestor automatically drops its descendants from
  `expanded_nodes` (a descendant pk left in the URL is never reached — decision #2), so **stale
  chips cannot appear** and a chip's ✕ always corresponds to a live expansion.

Exact dict/namedtuple shape settled in the plan; the two-list contract (frontier columns +
active-expanded nodes) is fixed.

### 2. Builders — `courses/rollups.py`

`build_progress_matrix(course, students, expanded=…)` and
`build_results_matrix(course, students, expanded=…)` gain an **`expanded` argument that defaults
to the empty set**, so the bare (un-expanded) matrix and **all existing 3c-ii tests are
behaviourally unchanged** (empty frontier == the current `parent_id is None` roots). The
builders **replace their `build_matrix_columns(course)` call with
`frontier_columns(course, expanded)`** (which generalizes it — §1): one structural walk still
supplies the column list **and** each column's `lesson_pks` / `quiz_pks`, so no second
`course.nodes` walk is introduced. (`build_matrix_columns` is thereby subsumed; whether it is
deleted or kept as a thin `frontier_columns(course, set())` alias is a plan detail.) The
single-source predicates
(`is_obligatory_lesson` for Progress, `is_quiz_unit` for Results) and the
`submission_is_counted` / `_quiz_review_maps` counted/pending machinery are **reused unchanged**
— drill-down must not re-derive any "counts toward Progress / Results" rule.

**Builder→template data contract (I1, I2).** Two changes to what the builders hand the view, so
the chip bar and expand links work with **no second walk**:

- Each builder's **result dict gains an `expanded_nodes` key** (the active-expanded list from
  the single `frontier_columns` call). The view passes it straight to the template; it must
  *not* call `frontier_columns` again (that would be a second `course.nodes` walk, breaking the
  no-N+1 guarantee). The existing keys (`columns`, `rows`, `averages`, `overall_average`,
  `has_quizzes`, `mode`) are unchanged.
- The **public column projection must be extended.** Today `_public_columns(columns)`
  (rollups.py:331) strips each column to `{node, title}`; the template now also needs
  **`expandable`** (which header is a clickable expand link) and the **node pk** (to build the
  expand URL). `_public_columns` must surface these (the `lesson_pks`/`quiz_pks` stay internal —
  the template doesn't need them). "Renders unchanged" applies to the *un-expanded* visual
  result, **not** to leaving `_public_columns` intact.

Unchanged semantics:

- **Overall column** is always the whole-course rollup (independent of expansion).
- **Average row / `overall_average`** — each per-column Average is the mean of that frontier
  column's *defined* student cell percentages; `overall_average` is the mean of defined
  per-student `overall` percentages. Identical rule to 3c-ii, now over frontier columns.
- **`percent` `int|None`, rounded once; `None` ≠ `0`** — the load-bearing 3c-ii invariant
  carries through unchanged.

**Partition invariant (the correctness anchor).** Expanding never adds or drops a unit — it
only regroups the same units into finer columns. So for **any** `expanded` set and any student:

- Progress: `Σ over frontier columns (done, total)` == the un-expanded `(Σdone, Σtotal)` for
  that student, and the student's `overall.percent` is unchanged by expansion.
- Results: `Σ over frontier columns (counted_score, counted_max)` == the un-expanded sums, and
  `overall.percent` is unchanged.

This invariant is the whole story for drill-down correctness and is asserted directly in tests
(several expand sets), in addition to the inherited 3c-ii Overall-parity tests
(`overall.percent` == `build_outline` / `build_course_results` derived percent), which must
stay green.

**No-N+1 survives expansion.** Query count stays constant in the number of students regardless
of expansion depth — the batched `UnitProgress` / `QuizSubmission` / `Element` /
`QuestionResponse` queries are unchanged; only the in-memory grouping of already-fetched rows
gets finer. The 3c-ii query-count tests are extended to assert constancy under an expanded set
too (warming the `ContentType` cache first, per the 3c-ii / 3c-i precedent, so the count does
not flap on the cold-cache first call).

### 3. Per-student breakdown — `courses/rollups.py` glue + a view

**Data = a composition, not new aggregation.** The breakdown merges, for one student:

- `build_outline(course, student)` → the nested tree with per-unit `completed` and the
  `required` / `additional` rollups (lesson side).
- `build_course_results(course, student)` → per-quiz rows carrying `status`
  (not_started / in_progress / awaiting_review / submitted), `score`, `max_score`, `pending`,
  `url_name` (quiz side).

A small **composition helper** (`build_student_breakdown(course, student)` in `rollups.py` —
"composition", not "pure": it calls the two query-backed builders below; only `frontier_columns`
is genuinely pure) joins them:
walk the `build_outline` tree, and for each **quiz unit** attach its
`build_course_results` row (keyed by `unit.pk` — `build_course_results` already emits one row
per quiz unit). Lesson units keep their `completed` flag. The result is one tree the breakdown
template renders. **Single-source:** the per-quiz status/score/pending come straight from
`build_course_results`'s rows (the same `submission_is_counted` rule the matrix uses) — the
breakdown and the matrix can never disagree on a quiz's state. The only genuinely new logic is
this join + the status→label mapping (§6); no scoring or counting is re-implemented.

**Status surfacing.** This is the **first** surface that shows per-*submission* status
(not_started / in_progress / awaiting_review / scored X/Y). The matrix only ever shows column
aggregates; per-submission status has no single meaning at the aggregate granularity, which is
exactly why 3c-ii deferred it to here.

**Review cross-link.** For a quiz whose row `status == "awaiting_review"`, render a link to
`courses:manage_review_submission` (3c-i), whose URL needs **both** `(course.slug,
submission_pk)` — the slug is trivially in scope, the **submission pk is not currently on the
row**. `build_course_results` rows carry `unit` / `status` / `graded` / `score` / `max_score` /
`pending` / `url_name` but **no submission pk**, so it must be threaded out explicitly — **the plan must
choose one**: (a) add `submission_pk` (or `submission_id`) to **every `build_course_results`
row that has a submission** (`None` on the `not_started` rows — a consistent row schema, not a
field that appears only on the awaiting-review branch; this touches the shared 2e function and
its tests — keep its existing behaviour, only *add* the field), or (b) re-query the SUBMITTED
`QuizSubmission` for that unit×student inside `build_student_breakdown`. This is a real touch-point, not free "plumbing".
The breakdown's per-student gate (`reviewable_students` — §4) guarantees the viewer may review
*this* student, so the link is always valid where rendered. No new review logic.

### 4. Views / URLs — `courses/views_analytics.py` (manage namespace)

All `@login_required`; course resolved by slug → **404** on mismatch.

- **`analytics_matrix` (extended)** — same URL `/manage/courses/<slug>/analytics/`,
  same `can_review_course`-or-404 gate. Additionally parses `expand` (repeatable) into the
  sanitized pk-set and threads it through the chosen builder. The template gains: the chip bar
  (one chip per active-expanded node — from `frontier_columns`' `expanded_nodes` list, §1 — each
  linking to "the same URL minus this pk"); expand links on expandable frontier columns (linking
  to "the same URL plus this pk"); and student-name links to the breakdown **rendered only for
  students the viewer can drill into** (I2 — see below).
- **State round-trip — the non-obvious half (I1, C1).** The 3c-ii scope control is **not a link,
  it is a GET `<form>`** (a `<select name="scope">` auto-submitting; the existing template carries
  only `mode` as a hidden input). So "round-trip everything" must be realized as: **the matrix
  form emits one `<input type="hidden" name="expand" value="<pk>">` per round-tripped expand pk**
  (so a scope change preserves expansion), **and** the Progress/Results toggle links and the
  "Configure colours" link carry the `expand` pks too. Without the hidden inputs, switching scope
  silently drops every `expand` — the exact failure decision #7 forbids.
  - **Which pk-set rides along (I1):** the round-tripped `expand` set is the **reached
    `expanded_nodes` pks** (the self-cleaning set), **not** the raw sanitized GET set. So once an
    ancestor is collapsed, its now-inert descendant pks are *not* carried forward through hidden
    inputs or any ±`expand` link — the URL self-heals on the next navigation instead of
    accreting dead pks. (This makes the §1 "optional intersection with the course's node pks" a
    pure tidiness nicety, since `expanded_nodes` already excludes unreached/forged pks.)
  - **The bands save path is part of the round-trip (C1):** `analytics_bands` is therefore **not
    fully untouched** — it must (a) read `expand` from `GET` and emit one hidden `expand` input
    per pk on its **save and reset** form, and (b) have `_matrix_redirect` (views_analytics.py:70)
    read `request.POST.getlist("expand")` and include those pks in the post-save redirect query.
    Otherwise saving/resetting colours redirects to the matrix with `expand` dropped — the same
    silent reset. (The bands *gate* and band logic are unchanged; only the state round-trip is
    extended.)
  - **Pre-built hrefs (data, not querydict arithmetic):** because templates can't do querydict
    math, the view attaches each navigation href as data — an **`expand_url`** per expandable
    frontier column, a **`collapse_url`** per `expanded_nodes` entry, and a **`breakdown_url`**
    per *drillable* student row (I4: `reverse('courses:manage_analytics_student', slug, student_pk)`
    + the round-tripped `scope`/`mode`/`expand`, so the breadcrumb-back restores matrix state) —
    all via one small helper (or a template tag). The template renders only pre-built hrefs.
    Exact mechanism (view-attached field vs. template tag) in the plan.
- **Per-row link gating (I2).** The matrix population is `students_in_scope`, but a **collection**
  scope can include students from groups the viewer does *not* teach, so it is a **superset** of
  `reviewable_students` (the breakdown's gate). Rendering a breakdown link for every row would
  produce links that 404 on click. Rule: **render the student name as a breakdown link iff that
  student ∈ `reviewable_students(user, course)`; otherwise render the name as plain text** (still
  a matrix row, just not drillable). The view passes a `reviewable` pk-set (computed once) to the
  template for this test. (For owner/PA, `reviewable_students` == all enrolled, so every row is a
  link; the gating only ever narrows a group-teacher's *collection*-scope view.)
- **`analytics_student` (new, GET)** — `/manage/courses/<slug>/analytics/student/<int:student_pk>/`,
  name `manage_analytics_student`. **Gate: `can_review_course(user, course)` AND `student_pk`
  ∈ `reviewable_students(user, course)` → else 404** (never 403; manage convention; prevents
  IDOR / peeking at a student outside the viewer's reach). Resolves the student, builds
  `build_student_breakdown`, renders the breakdown with a **breadcrumb back to the matrix**
  carrying the round-tripped `scope`/`mode`/`expand`. The breadcrumb state is read from the
  query string (the matrix passes it when linking in) purely for return navigation; the
  breakdown's own content is whole-course and ignores `expand`.

**Access otherwise unchanged.** View reach for both surfaces = `can_review_course`
(PA / course owner / teacher of a non-archived group on the course). Band editing stays on
`analytics_bands` (`can_manage_course`) — its gate and band logic are unchanged; the only edit
there is the `expand` round-trip (C1 above). No student-facing path changes.

### 5. URLs summary

```text
URL path                                                   view function      url name (Phase 3c-iii-a change)
/manage/courses/<slug>/analytics/                          analytics_matrix   manage_analytics          (parses ?expand=)
/manage/courses/<slug>/analytics/student/<int:student_pk>/ analytics_student  manage_analytics_student  (new)
/manage/courses/<slug>/analytics/colors/                   analytics_bands    manage_analytics_bands    (round-trips ?expand=)
```

### 6. UI / i18n

**Bespoke, token-driven, dark-mode-aware** — matching the 3c-ii matrix and 3b's outline
restyle. No Bootstrap/React.

- **Matrix:**
  - Header stays a **single flat row**. An expandable column header carries an affordance (a
    ▸ marker / underline) and is an `<a>` expand link; an already-expanded column's
    *children* render as ordinary headers (the parent is no longer a column). Non-expandable
    columns (units / Overall) render as today.
  - **Chip bar** above the matrix: "Expanded:" followed by one chip per **active-expanded node**
    (`frontier_columns`' `expanded_nodes`, §1 — *not* the frontier columns), breadcrumb-labelled
    (e.g. `Ch.1 ▸ Sec.2`), each with a ✕ link that removes that pk. Hidden entirely when nothing
    is expanded. Because the list comes from the walk, collapsing an ancestor auto-drops its
    descendant chips (no stale chips).
  - **Breadcrumb-style column titles** disambiguate repeated child titles (two chapters each
    with a "Summary" section). The exact format / truncation (full path vs. parent▸self vs.
    self-only with title attr) is a plan detail; the requirement is "enough context to
    disambiguate without overflowing the header". **Invariant (I2):** the breadcrumb prefix
    applies **only to columns produced by an actual expansion**; a root / depth-1 frontier
    column's `title` must equal `node.title` (no prefix), so the **un-expanded matrix is
    byte-identical to 3c-ii** — the functional-equivalence guarantee (§2) covers the rendered
    `title`, not just the node set.
  - **Student names** become links to the breakdown **when the student is in the viewer's
    `reviewable_students` reach** (I2); otherwise the name renders as plain text (a row a
    collection-scope viewer can see but not drill into). `None` / Overall / Average styling and
    the horizontal-scroll wrapper are unchanged.
- **Breakdown:** reuses the calm Part/Chapter/Section/unit hierarchy visual language from 3b's
  course-outline restyle, read as "this student's course". Per **lesson** unit: completion tick
  (done / not; obligatory vs additional already distinguished by `build_outline`). Per **quiz**
  unit: a status pill keyed off the `build_course_results` row's `status` **and `graded` flag**:
  - `submitted` **and `graded`** (`max_score > 0`) → **scored X/Y (Z%)** (`Z%` only computed
    when `max_score > 0`).
  - `submitted` **and not `graded`** (`max_score == 0` — e.g. a review-only quiz with no
    auto-marked question) → a plain **submitted** pill, **no X/Y, no percent** (dividing by a
    `0` max is undefined — the pill must not render "0/0" or compute `Z%`).
  - `awaiting_review` → **awaiting review** pill + the review cross-link.
  - `in_progress` → **in progress**; `not_started` → **not started**.

  **No other quiz link (I3).** The `build_course_results` row's inherited `url_name` (∈
  `courses:quiz_unit` / `courses:quiz_results`) is **student-facing** consumption (gated to the
  student/owner) and is **unused on this teacher surface** — the breakdown renders **no** quiz
  hyperlink except the `awaiting_review` → `manage_review_submission` cross-link. (Naively linking
  a quiz title via `url_name` would give teachers links that 404/redirect.)

  Breadcrumb back to the matrix (carrying round-tripped state).
- **Progressive enhancement:** everything works no-JS via GET links. Any existing scope/mode
  auto-submit JS is untouched; expand/collapse are plain links (no JS required).
- **i18n:** EN + PL for **every** new string at build time (the recurring project requirement —
  no untranslated ship): "Expanded:", the ✕/expand affordance labels, the four quiz-status
  labels, "X / Y", the breadcrumb/back label, breakdown section headers, the review-link label.
  Compile `.mo` (clear stray `#, fuzzy`).

### 7. Access — unchanged

`can_access_course` / `can_manage_course` / `can_review_course` / `reviewable_students` are
untouched. Drill-down adds only teacher-facing **read** surfaces under the existing
`can_review_course` reach, plus the per-student-reach 404 guard on the breakdown. No new
permission, no schema change.

## Edge cases

| Case | Behavior |
|---|---|
| `expand` empty / absent | Frontier == roots → matrix identical to 3c-ii. |
| `expand` names a leaf unit / a non-existent pk / a foreign-course node | Inert — frontier walk never acts on it; matrix renders as if it weren't there. |
| Collapsed parent with a lingering descendant `expand` pk in the URL | Walk stops at the collapsed parent; descendant pk never reached → no effect (no cascade-removal needed). |
| Non-integer `expand` value (`?expand=abc`) | Dropped during sanitization; ignored. |
| Expand a column whose children mix units and deeper structure | Frontier handles it — each child is a column (unit) or recursion point (has children). |
| Expand to full depth (chapter→section→units) | Works; matrix widens; horizontal-scroll wrapper absorbs it. No depth cap. |
| Flat course (units are the roots) | Roots are leaf units → nothing expandable; matrix == 3c-ii; no chips. |
| Empty course (no nodes) | Zero frontier columns regardless of `expand`; the 3c-ii empty-state applies. |
| Childless structural node (empty chapter/section) reached as a frontier column | Non-expandable, `None`-valued column (no units in subtree) — same as any all-`None` column. |
| Leaf **non-obligatory lesson** reached as a frontier column (after expanding its parent) | Non-expandable; its `lesson_pks` (obligatory only) and `quiz_pks` are both empty → renders `—` in **both** modes (counts toward neither Progress nor Results). Correct but visually surprising; covered by a builder test. |
| Collection-scope row for a student the viewer doesn't *teach* (in `students_in_scope` but not `reviewable_students`) | Row renders; name is **plain text, not a link** (I2) — visible in the aggregate, not drillable. |
| Student name link → breakdown for a student **outside** the viewer's reach (forged/guessed pk) | `student_pk ∉ reviewable_students` → **404** (the link is never rendered for such a student, but the view still guards directly). |
| Breakdown for a student with no submissions / no progress | Tree renders; every quiz "not started", every lesson "not done". |
| Breakdown quiz **awaiting_review** | Status pill + review cross-link to `manage_review_submission`. |
| Breakdown quiz scored 0 | "scored 0/Y (0%)" — distinct from "not started". |
| Non-staff / out-of-reach user hits any analytics URL | **404** (never 403; manage convention). |
| Partition under expansion | `Σ frontier == un-expanded totals`; `overall.percent` unchanged by any `expand` set (asserted). |
| Many students × deep expansion (perf) | Query count constant in student count and in expansion depth (asserted; only in-memory grouping changes). |

## Testing

- **`frontier_columns`** (pure) — empty set → the `build_matrix_columns` roots (with identical
  `lesson_pks`/`quiz_pks`); expand a chapter → its children replace it in `columns`, in outline
  order, and the chapter appears in `expanded_nodes`; **recursive** expand (chapter, then a
  section under it → units); leaf/childless node never `expandable`; **stale descendant pk inert
  + dropped from `expanded_nodes`** when its parent is collapsed (the no-stale-chip guarantee);
  non-existent / foreign-course / non-int pk ignored; `expandable`/`depth` flags correct on
  `columns`.
- **Builders with `expanded`** — correct per-frontier-column aggregates in both modes; the
  **partition invariant** (`Σ frontier (done,total)` / `(score,max)` == un-expanded totals, and
  `overall.percent` unchanged) for several expand sets; the inherited 3c-ii Overall-parity
  tests still green; `None`≠`0` preserved at finer columns (a sub-column with no obligatory
  lessons → `None`; an attempted-0 quiz sub-column → `0`); the result dict **carries
  `expanded_nodes`** (the active-expanded list) and the public columns carry `expandable` + the
  node pk; **query count constant** in students *and* in expansion depth (warm the ContentType
  cache first).
- **`build_student_breakdown`** — quiz units carry the right `status`/`score`/`max_score`/
  `pending`/`graded` from `build_course_results` (one case each: not_started, in_progress,
  awaiting_review, submitted-counted-graded, submitted-graded-0, **submitted-ungraded
  (`max_score == 0`, the no-percent pill, I3)**); lesson units carry the right `completed`; the
  join keys correctly by `unit.pk`; the awaiting-review row exposes a `submission_pk` for the
  cross-link; status→label mapping single-sourced (no re-derivation of counted/pending).
- **Views** — `analytics_matrix` parses `expand` (repeatable, sanitized) and renders the chip
  bar + expand links + student links; **the scope form emits a hidden `expand` input per active
  pk** so a scope change preserves expansion (I1 — assert the rendered form carries them), and
  the mode/colours links carry `expand`; **per-row link gating** — in a collection scope, a
  student in `reviewable_students` renders a breakdown link while one only in `students_in_scope`
  renders plain text (I2); `analytics_student` renders the right breakdown, **404s** for a
  student outside the viewer's reach and for a non-staff user; the review cross-link appears iff
  a quiz is awaiting_review (and the breakdown renders no `url_name`-based quiz link); **saving
  or resetting colours on `analytics_bands` preserves `expand`** in the post-save redirect (C1 —
  assert the redirect URL keeps the pks); all three URLs 404 for an out-of-scope user.
- **e2e (real gestures — no `page.evaluate` shortcuts; the e2e-must-drive-real-UI lesson)** — a
  teacher opens the matrix → clicks a chapter header to expand → sees sub-columns + a chip →
  recursively expands a section → collapses via the chip ✕ → clicks a student name → lands on
  the breakdown showing per-quiz statuses → clicks an awaiting-review review link (or asserts it
  is present) → uses the breadcrumb back and returns to the **same** matrix state (scope+mode+
  remaining expand preserved).

## Decisions deferred to the implementation plan

- Exact dict/namedtuple shape of `frontier_columns`' two returned lists (`columns` +
  `expanded_nodes`); the two-list contract itself is fixed (§1).
- Whether `build_matrix_columns` is deleted or kept as a thin `frontier_columns(course, set())`
  alias (§2).
- Exact breadcrumb-title format / truncation for deep frontier columns and chip labels.
- The query-string helper for building ±`expand` links and the hidden-`expand`-input emission in
  the scope form (and whether to intersect `expand` with the course's node pks for tidiness).
- The I3 submission-pk choice: add `submission_pk` to the `build_course_results` row vs. re-query
  inside `build_student_breakdown` (the *rule* — link from `(course.slug, submission_pk)` — is
  fixed; the source is not).
- Breakdown template structure (extend an existing outline partial vs. a new template) and the
  status-pill styling tokens.
- Whether `analytics_student` lives in `views_analytics.py` (default) or a sibling module.
