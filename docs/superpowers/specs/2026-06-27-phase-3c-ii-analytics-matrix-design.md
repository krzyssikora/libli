# Phase 3c-ii — Analytics matrix (core): design

**Date:** 2026-06-27
**Status:** Spec (awaiting review)
**Depends on:**
- Phase 3a (grouping substrate — `groups_visible_to`, `_is_platform_admin`; `Group`/`Collection` each carry a per-course FK; `GroupMembership.student`).
- Phase 3c-i (`reviewable_students(user, course)`, `can_review_course(user, course)` in `grouping/scoping.py`; the manage `/manage/courses/<slug>/…` surface convention).
- Phase 2e / 3c-i (`build_course_results` headline math + the `awaiting_review` derivation: a SUBMITTED quiz is pending while `reviewed_R_count < total_R_count`).
- PR #43 per-course structure/depth presets (Flat/Chapters/Parts/Full) — determines what the matrix's **top-level columns** are.
- `courses/rollups.py` `build_outline` / `_walk_preorder` / `quiz_units_in_order` (the shared traversal substrate).

## Goal

Give teachers a per-course **configurable matrix**: the scoped students (rows) × the
course's top-level components (columns), every cell a percentage colored by a per-course
band table. A **Progress ↔ Results** toggle switches what the cells measure; a scope picker
(**all enrolled / a group / a collection**) chooses the rows. A small **color-band config**
UI (owner/PA) makes the band table editable. The matrix is **read-only** — all drill-down
(column-expand into sections/units, per-student breakdown) is **3c-iii**.

This is the **second and final** Phase-3c slice. It activates the cross-student reporting
half of the analytics requirement (view-inventory 4.5) on top of the per-student rollups
that 2e/3c-i produced.

## Locked decisions (from brainstorming)

1. **3c split rebalanced.** 3c-ii = core matrix **+ per-course color-band config UI**.
   3c-iii = **column drill-down + per-student drill** (the interaction-heavy "go deeper"
   slice). Color-band config was pulled *into* 3c-ii (it is small, low-interaction-risk, and
   belongs next to its only consumer — the matrix) to balance the two slices and to avoid
   shipping throwaway hardcoded bands that 3c-iii would have to rewrite.
2. **One configurable matrix**, per the accepted mockup
   (`docs/mockups/analytics-matrix_accepted-option1.html`) and roadmap §"Teacher analytics
   matrix". Not several purpose-built views.
3. **Per-course.** Both `Group` and `Collection` carry a `course` FK, so the matrix is
   inherently scoped to one course; the scope picker only chooses **which students** on that
   course. URL `/manage/courses/<slug>/analytics/`.
4. **Cell metrics:**
   - **Progress** = required-lesson completion %: `required_done / required_total` within a
     column's subtree, exactly as `build_outline` rolls up (quizzes have `required_total == 0`
     and are excluded; Progress measures obligatory lesson material).
   - **Results** = quiz score %: `Σ earned / Σ max` over the column's quiz units, mirroring
     `build_course_results`'s headline math; **not-started, in-progress, and awaiting-review
     quizzes are excluded from the ratio** and shown as neutral markers (not 0).
5. **Columns = the depth-1 structural nodes** (the roots of the `build_outline` tree):
   chapters/parts for a structured course, or units directly for a Flat course (PR #43). Plus
   an **"Overall"** column (course rollup) and a **"Group avg"** footer row.
6. **Group-avg row = the mean of the *defined* student cell percentages** per column (cells
   with no denominator excluded). Same rule in both modes — one explanation.
7. **Color bands:** a fixed **5 bands** (none / weak / ok / good / excellent), each with an
   editable **lower-bound % + color**. Stored as one JSON field on `Course`; sensible
   built-in defaults so the matrix is colored before anyone configures anything.
8. **Scope controls:** all-enrolled / a group / a collection. **No** per-student cherry-pick
   subset (deferred to 3c-iii).
9. **Read-only matrix.** No clickable cells/rows in this slice; all drill-down is 3c-iii.
10. **State via GET query params** (`?scope=…&mode=…`) — server-rendered, no-JS-required,
    matching the project's progressive-enhancement convention. No client framework.

## Non-goals

- Column drill-down (click a chapter → expand into its sections/units) — **3c-iii**.
- Per-student breakdown page (click a student → their own detail) — **3c-iii**.
- Per-student cherry-pick subset filter ("Students: All ↔ chosen") — **3c-iii**.
- Per-**group** color-band override (roadmap explicitly "later") — config is course-level only.
- CSV / printable gradebook export (roadmap "deferred"; the matrix builders return plain
  dicts, export-friendly when that lands).
- Charts/graphs, trend-over-time, any cross-**course** dashboard.
- Notifications. Editing any student/quiz/group data from the matrix (it is read-only).

## Architecture

### 1. Entry & access

- **URL** `/manage/courses/<slug>/analytics/` (manage namespace, parallel to 3c-i's
  `review-queue/`). Resolve the course by **slug**; any mismatch → **404**.
- **Page gate:** reuse **`can_review_course(user, course)`** (3c-i) — the analytics audience
  (view-inventory 4.5: T/CA/PA with reach) is exactly the review audience (PA, course owner,
  or a teacher of a non-archived group on the course). No new page-gate helper. Non-staff /
  out-of-scope → **404** (never 403; manage convention).
- **Entry link** from the manage course area (the `course_list` row and/or the manage course
  nav), beside the 3c-i "Review" entry. Exact placement/label settled in the plan.

### 2. Scope resolution — `grouping/scoping.py`

Scoping lives where `reviewable_students` / `groups_visible_to` already live (the established
`grouping → courses` import direction; no cycle).

- **`collections_visible_to(user, course) -> QuerySet[Collection]`** *(new)* — collections the
  user may see on this course: **`collections_manageable_by(user)`** ∪ **collections whose
  `groups` include a group the user teaches**, filtered to `course=course`, `.distinct()`.
  Mirrors the `groups_visible_to` = manageable ∪ taught shape. (A teacher who teaches one group
  in a collection can view the whole collection's matrix — intended; reporting reach, not edit
  reach.)
- **`analytics_scope_choices(user, course) -> list`** — the picker options, in order:
  1. **"All my students"** — value `all`. (For owner/PA this is every enrolled student; for a
     group teacher it is the union of their groups' students — both via `students_in_scope`'s
     `all` branch below, so the label is uniform and the set always matches the user's reach.)
  2. each **non-archived** group in `groups_visible_to(user).filter(course=course,
     archived=False)` — value `group:<pk>`.
  3. each collection in `collections_visible_to(user, course)` — value `collection:<pk>`.
  Returns label + value pairs (group/collection display names; locale-aware where the model
  provides it). The exact dict/namedtuple shape is settled in the plan.
- **`students_in_scope(user, course, scope) -> QuerySet[User]`** — resolves a scope **value**
  to a student queryset, **always re-deriving from the user's reach** (never trusting the param
  as authority):
  - `all` → `reviewable_students(user, course)` (3c-i: owner/PA = all enrolled; group teacher
    = their groups' union).
  - `group:<pk>` → if that pk is in `groups_visible_to(user).filter(course=course,
    archived=False)`, the group's `GroupMembership.student` set; else fall back to default.
  - `collection:<pk>` → if that pk is in `collections_visible_to(user, course)`, the union of
    its non-archived groups' members; else fall back to default.
  - **Unreachable / malformed / unknown scope → silently return the default** (`all`). The
    scope is a URL query param, **not** a security boundary: the returned student set is always
    a subset of the user's reach, so a forged `group:999` can at worst show the user their own
    default scope, never another teacher's students. (We deliberately do **not** 404 on a bad
    scope param — friendlier, and there is nothing to leak.) `.distinct()` everywhere a student
    could appear via multiple groups.

### 3. Cross-student aggregation — `courses/rollups.py`

The engineering core. Two builders, each producing the full grid for one mode with **no N+1
over students** — query count is constant in the number of students (asserted in tests, the
3c-i precedent). Each returns a plain dict (export-friendly, template-ready).

**Shared shape (both builders return):**

```text
{
  "columns": [ {"node": <root ContentNode>, "title": str}, ... ],   # depth-1 nodes, outline order
  "rows": [
     {"student": <User>,
      "cells": [ {"percent": Decimal|None, "label": str} , ... ],   # one per column, same order
      "overall": {"percent": Decimal|None, "label": str}},
     ...
  ],
  "averages": [ {"percent": Decimal|None}, ... ],   # one per column
  "overall_average": {"percent": Decimal|None},
  "mode": "progress" | "results",
}
```

- **`percent` is `Decimal|None`.** `None` ≡ **no denominator** (nothing assigned/attempted for
  that student×column) → renders neutral "—", bypassing the band lookup. `Decimal("0")` ≡
  attempted/assigned but scored 0 → the lowest **band**. **This distinction is load-bearing;
  no builder or template may collapse `None` to `0`.**

- **Columns** = the roots of the `build_outline` tree (depth-1 nodes), in outline order. For a
  Flat course these roots are the units themselves; for a structured course they are
  chapters/parts. One structural walk (`_walk_preorder`) supplies both the column list and, per
  column, the set of relevant descendant unit pks (obligatory lesson units for Progress; quiz
  units for Results). A unit's column = the root of the subtree it lives in (computed once from
  the walk, not per student).

- **`build_progress_matrix(course, students)`**
  1. From the structural walk: per column, the set of **obligatory lesson** unit pks in its
     subtree and the total count; the course total = Σ.
  2. **One** batched query: `UnitProgress.objects.filter(unit__course=course, completed=True,
     student__in=students).values_list("student_id", "unit_id")` → a `{student_id:
     set(unit_ids)}` map. (Restrict to the relevant pks if cheap; correctness holds either way.)
  3. cell = `done / total` (Decimal, where `done` = |completed ∩ column_required_pks|);
     `total == 0` (a column with no obligatory lessons, e.g. an all-quiz chapter) → `None`.
     overall = Σ done / Σ total across columns (`None` if course has no obligatory lessons).
  4. averages: per column, mean of the **defined** cell percentages (decision #6). With a
     constant per-column denominator this equals `Σ done / (n · total)`, but compute it as the
     **mean of defined cells** so the rule is identical to Results mode.

- **`build_results_matrix(course, students)`**
  1. From the structural walk: per column, its **quiz unit** pks; the union = all quiz units.
  2. Batched inputs (the same ones `build_course_results` uses, fetched **once for all
     students**, not per student):
     - `QuizSubmission.objects.filter(unit__course=course, student__in=students)` (need
       `unit_id`, `student_id`, `status`, `score`, `max_score`).
     - the reviewed-`[R]`-count-per-submission aggregation (3c-i / `build_course_results`
       §"ONE batched query") to derive **pending** (`awaiting_review`).
     - the course-wide per-unit `total_review` map (one `Element` query) to know each unit's
       `[R]` count.
  3. A submission **counts** iff `status == SUBMITTED` **and not pending** (`reviewed_R_count
     >= total_R_count`). not-started (no row), in-progress, and awaiting-review are **excluded
     from the ratio** (decision #4). cell = `Σ counted score / Σ counted max` over the column's
     quiz units; `Σ max == 0` (no counted quiz) → `None`. overall = Σ across columns.
  4. averages: per column, mean of the **defined** cell percentages (decision #6).

- **Single-source discipline (anti-drift, recurring project value):** the per-submission
  "does this count, and what are its (score, max)" + pending logic MUST be a **single helper**
  shared by `build_course_results` and `build_results_matrix`, so the student summary and the
  teacher matrix cannot diverge on what "graded / awaiting / counted" means. `build_course_results`
  is refactored to call it; its existing behavior and tests are unchanged. Exact factoring
  settled in the plan; the **rule** ("SUBMITTED ∧ not pending counts; its (score,max) are
  `sub.score`/`sub.max_score`") is the contract.

- **Percent precision:** percentages are computed as `Decimal` and rounded to a whole number
  for display (matching `build_course_results`'s `int(round(100 * score / max))`). Banding (§4)
  operates on the same rounded value, so the cell's shown number and its color always agree.

### 4. Color bands — `courses/color_bands.py` + one migration in `courses`

- **Schema:** add `Course.color_bands = models.JSONField(blank=True, default=list)`. The
  migration adds the column with `default=list`; **no data backfill** — every existing course
  reads `[]` and falls through to the defaults via the accessor below.
- **`default_color_bands() -> list[dict]`** — the built-in 5 bands. Each band:
  `{"key": str, "label": <translatable>, "min": Decimal, "color": "#rrggbb"}`, ascending by
  `min`, first band `min = 0`. Keys/labels fixed: `none / weak / ok / good / excellent`
  (decision #7 — labels are not user-editable). Default thresholds & palette derived from the
  accepted mockup (e.g. green for high, amber/orange mid, neutral low); exact values in the plan.
- **`course_color_bands(course) -> list[dict]`** — `course.color_bands or default_color_bands()`.
  The **single read seam**: the matrix, the legend, and the config form all go through it, so an
  unconfigured course is colored and a configured one overrides cleanly. Stored bands store
  `key`/`min`/`color`; the **label is always re-resolved from the fixed key** (so labels stay
  translatable and a stored stale label can't leak).
- **`band_for(percent, bands) -> dict | None`** — returns the highest band whose `min <=
  percent`, or `None` when `percent is None` (no-data cell → neutral, **not** a band). Pure.
- **Readable text color:** the cell's text color is derived from the band's bg via a small
  **luminance** helper (`text_on(color)` → black/white) rather than stored, so an author can
  pick any bg and the number stays legible (and it works in both light and dark themes). A
  template filter exposes it. Exact threshold in the plan.
- **Config UI** — `/manage/courses/<slug>/analytics/colors/` (GET renders the form, POST saves):
  - **Gate: `can_manage_course(user, course)` (owner/PA only).** Group teachers can view the
    matrix with whatever bands are set but cannot edit course-level config (per-group override
    is the roadmap's deferred item). Mismatch → 404.
  - A `ColorBandsForm`: 5 fixed-label rows, each editable **`min` (0–100) + `color` (hex)**.
    Validation: thresholds **strictly ascending**, first row `min = 0` (enforced/forced),
    colors valid `#rrggbb`. On save, writes the normalized list to `Course.color_bands`.
    A "reset to defaults" affordance clears the field back to `[]` (→ defaults).
  - The form is its own page (not folded into the large course-edit form) to keep that form lean
    and the bands editor focused; linked from the matrix ("Configure colors").

### 5. Views / URLs — `courses` (manage namespace)

All `login_required`; all resolve the course by slug → 404 on mismatch.

- **`analytics_matrix` (GET)** — `/manage/courses/<slug>/analytics/`. `can_review_course` or 404.
  Reads `scope` (default `all`) and `mode` (default `progress`) from the query string. Builds
  `analytics_scope_choices`, resolves `students_in_scope` (ordered by name), then calls
  `build_progress_matrix` or `build_results_matrix`. Renders the matrix, the scope/mode controls
  (as a GET form / links), the band legend (`course_color_bands`), and — for owner/PA — a
  "Configure colors" link. Empty states (no students in scope; Results mode with no quiz units).
- **`analytics_bands` (GET/POST)** — `/manage/courses/<slug>/analytics/colors/`.
  `can_manage_course` or 404. GET renders `ColorBandsForm` seeded from `course_color_bands`.
  POST validates and saves (or resets), then redirects back to the matrix with a `{% trans %}`
  success message. CSRF enforced.

### 6. UI / i18n

- **Bespoke, token-driven** matrix matching the manage ledger (PR #34) / roster (PR #29/#32)
  patterns — dark-mode-aware, no Bootstrap/React.
- **Layout:** a table; sticky-ish first column (Student) is a nice-to-have. A **horizontal-scroll
  wrapper** for the grid — a wide matrix (many columns) cannot fully reflow on a phone, so it
  scrolls horizontally rather than breaking layout. The controls and legend stack above it.
- **Cells:** background = `band_for(percent, …).color`, text = `text_on(color)`, content = the
  rounded `%`. `None` cells → a neutral muted style with "—". The "Overall" column and "Group
  avg" row are visually distinguished (heavier weight / divider), same banding.
- **Controls:** a scope `<select>` and a Progress/Results toggle, both submitting via **GET**
  (so state lives in the URL, is shareable/bookmarkable, and needs no JS). A `<noscript>`-safe
  submit fallback; optional JS auto-submit-on-change as progressive enhancement.
- **Legend:** the 5 bands with their colors + labels + ranges (from `course_color_bands`).
- **Bands page:** 5 labelled rows, each a min-% input + a color input, Save + Reset.
- **i18n:** EN + PL for **every** new string at build time (recurring project requirement —
  grouping shipped untranslated in 3a and had to be backfilled; do not repeat). Band labels are
  translatable (re-resolved from key). Compile `.mo`.

### 7. Access — unchanged

`can_access_course` / `can_manage_course` untouched. The matrix's view reach is the existing
**`can_review_course`** (broad: PA/owner/group-teacher); band **editing** is the narrower
**`can_manage_course`** (owner/PA). The student-facing results/consumption paths are unchanged
— this slice adds only teacher-facing read surfaces plus one course-config field.

## Edge cases

| Case | Behavior |
|---|---|
| No students in scope | Matrix renders headers + an empty-state row ("no students in this scope"). |
| Results mode, course has no quiz units | Every cell `None`; an empty-state note ("no quizzes yet"). Progress mode still works. |
| Progress mode, a column has no obligatory lessons (e.g. all-quiz chapter) | That column's cells are `None` ("—"), excluded from the group avg. |
| Flat course (no chapters/parts) | Columns = the units directly (roots of `build_outline`). |
| Quiz awaiting review (≥1 unreviewed `[R]`) | Excluded from the Results ratio → contributes to neither the student cell nor the avg (neutral), consistent with `build_course_results`. |
| Attempted but scored 0 | `Decimal("0")` → lowest band (not neutral). Distinct from `None`. |
| Student in several of the user's groups / a collection's overlapping groups | `.distinct()` → one row. |
| Forged / unreachable `scope` param (`group:999`, `collection:0`, garbage) | Silently falls back to the default (`all`) scope; never errors, never leaks (set is always within the user's reach). |
| Owner-less course (`owner=None`, `SET_NULL`) | `can_review_course`/`can_manage_course` → PA-only, per the existing convention. |
| Unconfigured `Course.color_bands` (`[]`) | `course_color_bands` returns `default_color_bands()` — matrix is fully colored. |
| Band config with non-ascending thresholds / bad hex | Form rejects with field errors; nothing saved. |
| Many students (perf) | Both builders are batched — query count constant in student count (asserted). |

## Testing

- **`build_progress_matrix`** — correct `done/total` per column & overall; quizzes excluded;
  `None` for a column with no obligatory lessons and for a course with none; group avg = mean of
  defined cells; **query count constant vs. number of students** (assert).
- **`build_results_matrix`** — correct `Σscore/Σmax` per column & overall; not-started /
  in-progress / awaiting-review excluded from the ratio (neutral, not 0); attempted-0 is band-0
  not neutral; group avg = mean of defined cells; **no N+1** (assert); **parity with
  `build_course_results`** via the shared counted/pending helper (same submission set counts the
  same way in both).
- **Scoping** — `collections_visible_to` (manageable ∪ taught, course-filtered, distinct);
  `analytics_scope_choices` per role (owner/PA see "all" + groups + collections; group teacher
  sees their reachable subset); `students_in_scope` resolves each scope correctly and **falls
  back to default** for an unreachable/garbage value; non-staff hitting any analytics URL → 404.
- **Color bands** — `default_color_bands` shape/ordering; `course_color_bands` fallback +
  override + label re-resolution from key; `band_for` boundaries (exact threshold, top, `None`);
  `text_on` luminance picks readable text; `ColorBandsForm` rejects non-ascending thresholds and
  bad hex, accepts a valid edit, reset clears to defaults.
- **Views** — matrix renders the right rows/columns for a given scope+mode; mode/scope from
  query params; legend reflects configured bands; "Configure colors" shown only to owner/PA;
  bands page is owner/PA-only (group teacher → 404); CSRF on the bands POST; every URL 404s for
  an out-of-scope user.
- **e2e** — a teacher opens the analytics matrix → toggles Progress ↔ Results → switches scope
  (all → a group) → sees colored cells update; an owner opens the colors page, edits a band
  threshold, saves, and a known cell changes band on the matrix. Drive the **real** click/submit
  path (no `page.evaluate` shortcuts — the e2e-must-drive-real-UI lesson).

## Decisions deferred to the implementation plan

- Exact factoring of the shared counted/pending helper out of `build_course_results` (the §3
  *rule* is fixed; the refactor shape is not).
- Exact batched-query shapes for the two matrix builders (the *no-N+1* invariant is fixed).
- Exact default band thresholds/palette and the `text_on` luminance threshold (derive from the
  accepted mockup).
- Module placement of the new views (extend an existing `courses/views_*.py` vs. a new
  `views_analytics.py`) and of the scope-choice return shape.
- Exact placement/label of the "Analytics" entry in the manage course area, and whether
  scope/mode controls auto-submit (progressive-enhancement JS) or require a submit button.
- Sticky first column vs. plain horizontal scroll for the matrix on narrow screens.
