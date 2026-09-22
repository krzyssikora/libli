# Course glance bars

**Date:** 2026-09-22
**Status:** approved by the owner in brainstorming (this conversation)

## Purpose

### Problem

The anonymous landing page (`templates/core/landing.html:20-24`) advertises three
boxes — "Hiszpański A2 · 62%", "Matematyka · 30%", "Biology · 88%" — but no such
course-level summary exists anywhere in the app. They are hardcoded, mixed-language,
untranslated decoration. For a logged-in student:

- the dashboard's "My learning" panel (`templates/core/home.html`) is a bare list of titles;
- My courses (`templates/courses/my_courses.html`) is titles + a "My results" link;
- the outline shows per-section "lessons: 3/7" but never a course total;
- My results (`templates/courses/course_results.html`) shows quiz done/total and a score %.

### Goal

Under each enrolled course's title, two thin horizontal bars give an at-a-glance
picture — **progress** and **results** — with no numbers visible. Details stay on
the My results page. The landing page shows the same card, with fixed sample values.

## Owner decisions (verbatim intent — reviewers must NOT reverse these)

| # | Decision |
|---|----------|
| D1 | **Results** = cumulative score over SUBMITTED quizzes: Σscore / Σmax. E.g. 9/10, 3/5, 4/5 → 16/20 = 80%. NOT a mean of per-quiz percentages. This is exactly `build_course_results(...)["percent"]` today, which excludes quizzes awaiting review — reuse it, do not re-derive it. |
| D2 | **Progress** = completed obligatory (required) lessons / all required lessons. Quizzes and "additional" lessons do NOT count. Details live in My results / the outline. |
| D3 | Results with NO submitted quiz → only the light track. Results submitted with score 0 → a visible **dot at the left end** of the track (0% ≠ "nothing yet"). |
| D4 | Progress with 0 of N done → track only, **no dot** (every untouched course starts there). Course with no required lessons → track only. |
| D5 | **No visible numbers.** Label + bar only. Labels ("Progress", "Results") are small and muted — `--text-secondary`, NOT `--text-tertiary` (fails AA). |
| D6 | Screen readers DO get the figures (a spoken value per bar), invisible on screen. |
| D7 | Bars appear in **both** My courses and the dashboard's "My learning" panel, from ONE shared partial. Enrolled courses only — "Teaching" and "Studio" panels unchanged. |
| D8 | Landing page: three sample cards drawn by the **same partial**, fixed values, translated names **Spanish A2 / Mathematics / Biology** (pl: Hiszpański A2 / Matematyka / Biologia). Values cover the states: Spanish high progress + good result; Mathematics little progress + middling result; Biology barely started + results track only. Whole block stays `aria-hidden`; not clickable. |

## Architecture / components

### 1. Data — `course_glance(course, user)` in `courses/rollups.py`

Returns a flat dict:

```python
{
    "progress_done": int,        # required lessons completed
    "progress_total": int,       # required lessons in the course (0 → no progress figure)
    "progress_pct": int | None,  # round(100*done/total); None iff total == 0
    "results_pct": int | None,   # build_course_results(...)["percent"]; None iff nothing counted
}
```

- Progress sums `required_done` / `required_total` over the top-level items of
  `build_outline(course, user, drafts=...)`. No new arithmetic for "required".
- Results is `build_course_results(course, user, drafts=...)["percent"]` verbatim (D1).
- `drafts` is chosen exactly as `course_outline` / `course_results` choose it
  (`"keep" if can_see_drafts(user, course) else "hide"`), so the glance, the outline
  and My results never disagree.
- `results_pct` is `None` when no quiz is counted; `0` when counted and scored 0. The
  distinction is load-bearing (D3) — never coerce `None` to 0 or 0 to falsy in a template
  `{% if %}` (use `is None` / `is not None`).
- Cost: one outline walk + one results walk per enrolled course. Acceptable for a
  student's handful of courses; a test pins the query count per course so it cannot
  grow with the number of units/elements.

### 2. Display — `templates/courses/_course_glance.html`

Takes flat context: `progress_pct`, `progress_done`, `progress_total`, `results_pct`,
and optional `decorative` (landing). Renders two rows, each: small muted label, then a
track with an optional fill.

Fill rules:

| Bar | Value | Renders |
|-----|-------|---------|
| Progress | `None` (no required lessons) | track only |
| Progress | 0 (0 of N) | track only (D4) |
| Progress | >0 | fill `width: pct%` |
| Results | `None` | track only |
| Results | 0 | dot at left end (D3) |
| Results | >0 | fill `width: pct%` |

- A non-zero fill has a min-width equal to the dot's diameter, so a tiny value
  (e.g. 1%) is still visible and the 0-dot and a 1% fill look continuous.
- Width is an inline `style="width: N%"` (inline styles already in use, no CSP block).
- Accessibility (D6): each bar is `role="img"` with an `aria-label` carrying the
  figure — "Progress: 12 of 40 lessons", "Progress: no lessons to track",
  "Results: 80%", "Results: none yet". All strings translated. The visible label text
  is `aria-hidden` inside the bar's labelled group so it is not read twice.
- When `decorative` is set (landing) no roles/labels are emitted; the landing wrapper's
  `aria-hidden` covers it.
- Forced-colors: the fill must stay distinguishable from the track (e.g. fill uses
  `CanvasText`/`Highlight`, track a border) under `@media (forced-colors: active)`.
- CSS lives in `core/static/core/css/app.css` next to `.dash-card` (the partial is used
  on core and courses pages, both of which load app.css).

### 3. Placement

- **My courses** (`courses/views.py:my_courses`): pass `(course, glance)` pairs; each
  `.dash-card` renders the partial between the title and the actions.
- **Dashboard** (`core/views.py:home`): `enrolled_courses` becomes `(course, glance)`
  pairs for "My learning"; each `<li>` gets the partial under the link. Teaching /
  Studio / Admin panels unchanged.
- **Landing** (`templates/core/landing.html`): replace the three `.card` boxes with
  three cards using the partial with `decorative=True` and literal values, e.g.
  Spanish A2 progress 70 / results 85; Mathematics progress 20 / results 55;
  Biology progress 5 / results None. Titles `{% trans %}`'d; pl catalog entries added.
  Wrapper keeps `aria-hidden="true"`; no links.

## Data flow

1. `my_courses` / `home` view: for each enrolled course (ordered by title, as today), call
   `course_glance(course, request.user)` and pass `(course, glance)` pairs to the template.
2. `course_glance` picks `drafts` via `can_see_drafts`, calls `build_outline` and
   `build_course_results`, and returns the flat dict of section 1.
3. The template includes `courses/_course_glance.html` with the dict's keys as flat context.
4. The landing template includes the same partial with literal values and `decorative=True`
   — no database access.

## Error handling

- Nothing new can fail: both rollups already run on every outline / My results request.
- `None` vs `0` is the only correctness hazard (D3/D4); templates must test `is None`, never
  truthiness.
- `progress_total == 0` must not divide (→ `progress_pct = None`).
- Enrolled courses only: a course a user can no longer access (e.g. enrollment removed) is
  simply not in the enrolled queryset, as today; no access check is added or relaxed.

## Testing

### Tests

Unit (`course_glance`):
- 9/10 + 3/5 + 4/5 submitted → `results_pct == 80` (not 77).
- no submission → `results_pct is None`; a submitted quiz scored 0 → `results_pct == 0`.
- a quiz awaiting review is excluded (matches `build_course_results`).
- no required lessons → `progress_pct is None`; 0 of N → `progress_pct == 0`.
- additional lessons and quizzes do not move progress.
- draft units hidden for a student.
- query count per course is constant w.r.t. number of units (pin it).

Render:
- each fill-table row above (track only / dot / fill with width) on My courses and dashboard.
- `aria-label`s carry the figures; no visible digits in the card.
- landing in pl shows Hiszpański A2 / Matematyka / Biologia, is `aria-hidden`, has no links, emits no `role="img"`.
- Teaching/Studio panels unchanged for a teacher.

Screenshots: light + dark (dark judged separately), plus forced-colors for the fill.

Falsification: before trusting the suite, mutate `None`→0 in results, drop the dot
branch, and swap D1 for a mean of percentages — each must go RED.

## Out of scope

- Visible numbers, tooltips, per-section bars, teacher-side aggregates.
- Any change to how `build_outline` / `build_course_results` compute their figures.
