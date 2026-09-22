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

### 1. Data — `course_glance(course, user, *, drafts)` in `courses/rollups.py`

`drafts` is REQUIRED and chosen by the caller, following the rollups convention that every
caller decides drafts (rollups.py imports no access-layer code). Callers use exactly what
`course_outline` / `course_results` use: `"keep" if can_see_drafts(user, course) else "hide"`,
so the glance, the outline and My results never disagree.

Returns a flat dict. The **spoken figures** and the **drawn widths** are separate keys:
the figures are exact, the widths are clamped so rounding can never lie visually.

```python
{
    # spoken figures (aria-label)
    "progress_done": int,         # required lessons completed
    "progress_total": int,        # required lessons in the course
    "results_pct": int | None,    # build_course_results(...)["percent"] verbatim (D1)
    # drawn widths (template); None = draw no fill; 0 = draw the zero-dot
    "progress_width": int | None,
    "results_width": int | None,
}
```

- Progress sums `required_done` / `required_total` over the top-level items of
  `build_outline(course, user, drafts=drafts)`. No new arithmetic for "required".
- Results is `build_course_results(course, user, drafts=drafts)`; `results_pct` is its
  `percent` verbatim (D1 — cumulative Σscore/Σmax over counted quizzes; pending excluded).
- `progress_width`:
  - `None` if `progress_total == 0` or `progress_done == 0` (D4: track only, no dot);
  - else `round(100*done/total)`, clamped to **1..99** unless `done == total` (then 100).
    So 1/250 still draws a sliver and 199/200 never draws a full bar.
- `results_width`:
  - `None` if `results_pct is None` (nothing counted: track only);
  - `0` if the summary's `score` is exactly 0 (D3: the zero-dot);
  - else `round(100*score/max_score)`, clamped to **1..99** unless `score == max_score`
    (then 100). So 1/300 draws a sliver, not the zero-dot, and 299/300 is not full.
    Branching is on `score`, never on the rounded percent.
- The `None` vs `0` distinction is load-bearing (D3/D4) — templates test `is None` /
  `== 0`, never truthiness.
- Cost: one outline walk + one results walk per enrolled course; must be a constant number
  of queries per course, independent of units, quizzes, submissions and reviewed responses
  (see Testing).

### 2. Display — `templates/courses/_course_glance.html`

Context: `progress_width`, `results_width`, and — unless `decorative` — `progress_done`,
`progress_total`, `results_pct`. In decorative mode ONLY the two widths are read.

Exact markup for one row (the other row is identical with `results`):

```html
<div class="glance">
  <div class="glance__row">
    <span class="glance__label" aria-hidden="true">{label}</span>
    <div class="glance__track" role="img" aria-label="{spoken figure}">
      <span class="glance__fill" style="width: {width}%"></span>   <!-- only if width > 0 -->
      <span class="glance__dot"></span>                            <!-- only if width == 0 -->
    </div>
  </div>
  ...
</div>
```

- The label is a sibling of the track, `aria-hidden` so it is not read twice; the track
  carries the accessible name.
- `decorative=True`: same markup but the track has NO `role` and NO `aria-label` (the
  landing wrapper's `aria-hidden` covers the block).

Fill rules (by width):

| width | Renders |
|-------|---------|
| `None` | track only |
| `0` (results only) | `.glance__dot` at the left end |
| 1..100 | `.glance__fill` with `width: N%` |

Styling (in `core/static/core/css/app.css`, next to `.dash-card`; both page families load it):
- labels: `font-size: .75rem`, `color: var(--text-secondary)` (D5; NOT `--text-tertiary`);
- track: height 6px, fully rounded, `background: var(--border-subtle)`;
- fill: same height, `background: var(--accent)`, `min-width: 6px` (so the 1% sliver and the
  zero-dot read as continuous); both bars share the accent colour;
- dot: 6px circle, `background: var(--accent)`, at the track's left end;
- rows stacked with `var(--space-1)` gap; label and track on one line (label fixed width,
  track `flex: 1 1 0`);
- `@media (forced-colors: active)`: track gets a `1px solid CanvasText` border and
  transparent background; fill and dot use `background: Highlight` with
  `forced-color-adjust: none`, so they stay visible.
- Exact values may be tuned during the screenshot review (light + dark judged separately);
  the tokens above are the target.

Strings (all translated, with pl entries):
- labels: `{% pgettext "course glance" "Progress" %}` / `"Results"` — context-scoped so the
  existing unscoped "Progress"/"Results" msgids elsewhere cannot silently change them;
- progress figure: a `{% blocktrans count counter=progress_total %}` block
  ("Progress: {done} of {counter} lesson" / "... lessons") with EVERY Polish `msgstr[n]`
  index filled per the catalog's `Plural-Forms` header, each grammatically correct;
- `progress_total == 0`: "Progress: no lessons to track";
- results figure: "Results: {pct}%";
- `results_pct is None`: "Results: no scores yet" (covers both "nothing submitted" and
  "submitted but awaiting review / ungraded" — neutral on purpose).

### 3. Placement

- **My courses** (`courses/views.py:my_courses`): pass `(course, glance)` pairs; each
  `.dash-card` renders the partial between the title and the actions.
- **Dashboard** (`core/views.py:home`): "My learning" iterates `(course, glance)` pairs;
  each `<li>` gets the partial under the link. Every existing truthiness check on
  `enrolled_courses` in `home.html` must keep working (a list of pairs is truthy iff
  non-empty). Teaching / Studio / Admin panels unchanged.
- **Landing** (`templates/core/landing.html`): replace the three `.card` boxes inside
  `.landing-visual` (wrapper keeps `aria-hidden="true"`) with three
  `<div class="glance-card">` elements, each: `<p class="glance-card__title">{% trans "…" %}</p>`
  then the partial with `decorative=True`. `.glance-card` is its own static class — NOT
  `.dash-card` (whose hover lift signals a click target) and NOT the old `.card` rules. It
  looks like a dash-card at rest (surface, border, radius, small shadow), width ~14rem,
  left-aligned text, no hover effect, no links. The old `.landing-visual .card` rule is
  removed if nothing else uses it.
  Final values (D8):

  | Title (en / pl) | progress_width | results_width |
  |---|---|---|
  | Spanish A2 / Hiszpański A2 | 70 | 85 |
  | Mathematics / Matematyka | 20 | 55 |
  | Biology / Biologia | 5 | None |

## Data flow

1. `my_courses` / `home` view: for each enrolled course (ordered by title, as today), compute
   `drafts` as above and call `course_glance(course, request.user, drafts=drafts)`; pass
   `(course, glance)` pairs to the template.
2. `course_glance` calls `build_outline` and `build_course_results` and returns the flat dict
   of section 1.
3. The template includes `courses/_course_glance.html` with the dict's keys as flat context.
4. The landing template includes the same partial with literal widths and `decorative=True`
   — no database access.

## Error handling

- Nothing new can fail: both rollups already run on every outline / My results request.
- `None` vs `0` is the main correctness hazard (D3/D4); templates test `is None` / `== 0`,
  never truthiness.
- No division when `progress_total == 0` or when results are `None`.
- Enrolled courses only: a course the user is no longer enrolled in is simply not in the
  enrolled queryset, as today; no access check is added or relaxed.

## Testing

Unit (`course_glance`):
- 9/10 + 3/5 + 4/5 submitted → `results_pct == 80` (not 77) and `results_width == 80`.
- no submission → `results_pct is None`, `results_width is None`.
- one submitted quiz scored 0 → `results_pct == 0`, `results_width == 0`.
- a quiz awaiting review is excluded (matches `build_course_results`).
- no required lessons → `progress_width is None`; 0 of N → `progress_width is None`,
  `progress_done == 0`.
- boundaries: 1 of 250 lessons → `progress_width == 1`; 199 of 200 → 99; N of N → 100;
  results 1/300 → `results_width == 1` (not the dot); 299/300 → 99.
- additional lessons and quizzes do not move progress.
- draft units hidden with `drafts="hide"`.
- query count: warm the ContentType cache first, then assert the count is EQUAL for a small
  and a larger course that differ in units, quizzes, submissions and reviewed responses
  together. At view level: My courses and the dashboard with 3 vs 2 enrolled courses differ by
  exactly the same per-course constant.

Render:
- each fill-table row (track only / dot / fill with `width: N%`) on My courses and dashboard.
- `aria-label`s carry the figures; pl labels use the right plural form for totals 1, 3, 5.
- no visible digits: collect the text content of the `.glance` block only (not the title,
  not attributes) and assert it contains no digit. Fixtures use digit-free course titles.
- landing in pl shows Hiszpański A2 / Matematyka / Biologia, is inside `aria-hidden`, has no
  `<a>`, emits no `role="img"`, and cards use `.glance-card` (not `.dash-card`).
- Teaching/Studio panels unchanged for a teacher.

Screenshots: light + dark (dark judged separately), plus forced-colors for the fill.

Falsification — each must go RED before the suite is trusted:
- `results_width` `None`→0 (dot on "nothing submitted");
- drop the dot branch;
- replace D1 with a mean of per-quiz percentages;
- branch results width on rounded percent instead of `score` (1/300 → dot);
- remove the 99 clamp;
- add a visible `{{ results_pct }}` to the partial.

## Out of scope

- Visible numbers, tooltips, per-section bars, teacher-side aggregates.
- Any change to how `build_outline` / `build_course_results` compute their figures.
