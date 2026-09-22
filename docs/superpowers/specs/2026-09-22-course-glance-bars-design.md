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
| D9 | Owner's words: "The lines would have a certain width shown in a **light colour**, and a part of the width would be shown in brighter colour or thicker." The TRACK is deliberately light; it is NOT held to a 3:1 contrast target (that would make it dark). The FILL carries the information and is. |
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
  `build_outline(course, user, drafts=drafts)`. No new arithmetic for "required". The same
  sum already exists as `course_progress` in the unit-navigation helper
  (`courses/rollups.py`, ~line 1104); extract it into one small helper
  (e.g. `_course_required_totals(tree) -> (done, total)`) used by both, so the twins cannot drift.
- The width arithmetic lives in two pure helpers, `_progress_width(done, total)` and
  `_results_width(score, max_score, percent)`, which `course_glance` calls; the boundary
  tests target these directly (no 250-row fixtures).
- Results is `build_course_results(course, user, drafts=drafts)`; `results_pct` is its
  `percent` verbatim (D1 — cumulative Σscore/Σmax over counted quizzes; pending excluded).
- `progress_width`:
  - `None` if `progress_total == 0` or `progress_done == 0` (D4: track only, no dot);
  - `100` if `done >= total`; else `round(100*done/total)` clamped to **1..99**.
    So 1/250 still draws a sliver and 199/200 never draws a full bar.
- `results_width` — checks in THIS order (the order is load-bearing):
  1. `None` if `results_pct is None` (nothing counted: track only). This MUST come first:
     `build_course_results` returns `score == Decimal("0")` (not None) whenever any quiz is
     submitted, including when every submission is awaiting review or has `max_score == 0`
     — both have `percent is None` and must draw track only, not the dot;
  2. `0` if the summary's `score` is exactly 0 (D3: the zero-dot);
  3. `100` if `score >= max_score`; else the existing `_pct(score, max_score)` (Decimal,
     ROUND_HALF_EVEN — the same rounding as `percent`, so mid-range width == spoken figure)
     clamped to **1..99**. So 1/300 draws a sliver, not the zero-dot, and 299/300 is not full.
     Branching is on `score`, never on the rounded percent.
- Accepted asymmetry: the SPOKEN results figure stays `percent` verbatim (so it always equals
  the My results headline, D1), so at the extremes it can disagree with the drawn width
  (1/300 is spoken "0%" but drawn as a sliver; 299/300 spoken "100%", drawn 99). This is
  intentional; do not clamp the spoken figure.
- The `None` vs `0` distinction is load-bearing (D3/D4) — templates test `is None` /
  `== 0`, never truthiness.
- Cost: one outline walk + one results walk per enrolled course. The query count per course
  is constant **for a fixed set of question types, once every query branch is non-empty**:
  `_quiz_review_maps` does a generic-FK prefetch (one query per distinct question content
  type) and skips queries entirely for empty `__in` lists. Within that envelope it must not
  grow with the number of units, quizzes, submissions or reviewed responses (see Testing).

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
- The branch inside the track is exactly
  `{% if w is None %}{% elif w == 0 %}<dot>{% else %}<fill>{% endif %}` — never an ordering
  comparison such as `w > 0`, which Django silently evaluates as False on `None`.
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
- track: height 6px, fully rounded, `background: var(--border-subtle)`, `display: flex`
  (so the inline-span fill and dot honour width/height; fill and dot also get
  `display: block` — without it the bars render empty and no DOM test would notice, so the
  screenshot review must confirm a visible fill);
- track `overflow: hidden`; fill same height, `border-radius: 999px`,
  `background: var(--accent)`, `min-width: 6px`; both bars share the accent colour.
  The 0-vs-tiny-nonzero difference (dot vs 1% fill) is STRUCTURAL (`.glance__dot` vs
  `.glance__fill`) and visually identical by design — D3 only requires 0 to look different
  from "nothing yet" (track only), which it does. DOM tests, not screenshots, guard it;
- dot: 6px circle, `background: var(--accent)`, at the track's left end;
- `.glance` is a two-column grid (`grid-template-columns: max-content 1fr`,
  `.glance__row { display: contents }`) with `var(--space-1)` row gap, so the label column
  is as wide as the longest label in the current language and both tracks start at the
  same x; labels `white-space: nowrap`; `align-items: center` on `.glance` so each 6px
  track sits level with its label; `.glance { margin-top: var(--space-1) }` separates it
  from the course title (the dashboard `<li>` holds an inline `<a>` then the block `.glance`);
- `@media (forced-colors: active)`: track gets a `1px solid CanvasText` border and
  transparent background; fill and dot use `background: Highlight` with
  `forced-color-adjust: none`, so they stay visible.
- Exact values may be tuned during the screenshot review (light + dark judged separately);
  the tokens above are the target.

Strings (all translated, with pl entries):
All strings below carry `context "course glance"` (Django template syntax — there is no
`{% pgettext %}` tag; the repo precedent is `{% trans "Open" context "course visibility" %}`):
- labels: `{% trans "Progress" context "course glance" %}` /
  `{% trans "Results" context "course glance" %}` — context-scoped so the existing unscoped
  "Progress"/"Results" msgids elsewhere cannot silently change them;
- progress figure:
  `{% blocktrans with done=progress_done count counter=progress_total context "course glance" %}Progress: {{ done }} of {{ counter }} lesson{% plural %}Progress: {{ done }} of {{ counter }} lessons{% endblocktrans %}`
  with EVERY Polish `msgstr[n]` index filled (pl has nplurals=3), each grammatically correct;
- `progress_total == 0`: "Progress: no lessons to track";
- results figure:
  `{% blocktrans with pct=results_pct context "course glance" %}Results: {{ pct }}%{% endblocktrans %}`
  — the msgid becomes `Results: %(pct)s%%` and the pl msgstr must also use `%%`; a render
  test asserts the pl `aria-label` reads exactly `Wyniki: 80%` (single `%`);
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
  `<div class="glance-card">` elements, each:
  `<p class="glance-card__title">{% trans "Mathematics" context "course glance" %}</p>` (all
  three titles carry the same context, so no other msgid can hijack them)
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
3. The template includes the partial with explicit keys and `only` (so no outer
   `decorative` or other variable leaks in); the partial does its own `{% load i18n %}`:
   `{% include "courses/_course_glance.html" with progress_width=glance.progress_width results_width=glance.results_width progress_done=glance.progress_done progress_total=glance.progress_total results_pct=glance.results_pct only %}`
4. The landing template includes the same partial with literal widths — no database access:
   `{% include "courses/_course_glance.html" with progress_width=70 results_width=85 decorative=True only %}`
   (for Biology, `results_width=None`). EVERY include passes BOTH widths explicitly: under
   `only` a missing key resolves to `""`, which is neither `None` nor `0` and would render a
   broken `width: %` fill.
5. Context key names stay as today: `courses` (my_courses) and `enrolled_courses` (home);
   their values become lists of `(course, glance)` pairs.

## Error handling

- Containment: both rollups can raise (some on purpose, e.g. on an inconsistent tree). Today
  that breaks one course's outline/results page; unguarded, it would 500 the dashboard — the
  post-login landing page — and My courses for every student in that course. So BOTH views
  import ONE shared helper, `courses.rollups.course_glance_or_unknown(course, user, *, drafts)`,
  which catches `Exception` around `course_glance` (looked up as a module global, which is
  what the containment test patches: `courses.rollups.course_glance`), logs it with
  `logger.exception` (course pk in the message), and substitutes the "unknown" glance:
  `progress_done=0, progress_total=0, results_pct=None, progress_width=None,
  results_width=None` (track only, spoken "no lessons to track" / "no scores yet"). The
  course's own outline/results pages still raise as today, so the bug stays visible there
  and in the logs. A test forces `course_glance` to raise and asserts the dashboard and
  My courses still return 200, render the other courses' glances, and log the error.
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
- ONLY a pending-review submission → `results_width is None` (not 0).
- one submitted quiz with `max_score == 0` → `results_width is None` (not 0).
- no required lessons → `progress_width is None`; 0 of N → `progress_width is None`,
  `progress_done == 0`.
- boundaries, on the pure helpers: `_progress_width(1, 250) == 1`; `(199, 200) == 99`;
  `(N, N) == 100`; `(0, N) is None`; `(0, 0) is None`; `_results_width` with 1/300 → 1
  (not the dot), 299/300 → 99, 0/10 → 0, `percent=None` with `score=0` → None, score > max
  → 100, and a .5 boundary (1/8 → 12, equal to `_pct(1, 8)`). One or two DB-level `course_glance` tests cover the wiring.
- additional lessons and quizzes do not move progress.
- draft units hidden with `drafts="hide"`.
- query count: warm the ContentType cache first. Both fixtures have at least one required
  lesson, one COMPLETED required lesson, one additional lesson, one quiz, one submission and
  one reviewed response, all quizzes with the SAME single question type; the larger one only
  has more of each. Assert the counts
  are EQUAL. At view level, for EACH of My courses and the dashboard: measure the request with
  N = 1, 2, 3 enrolled courses, every course built from that same fixture shape, and assert
  `count(3) - count(2) == count(2) - count(1)` (N = 0 is excluded because the per-request
  permission cache fills on the first course).

Render:
- each row of the "Fill rules" table above (track only / dot / fill with `width: N%`) on
  My courses and dashboard.
- a 0-of-N progress row emits neither `.glance__dot` nor `.glance__fill` (D4).
- `aria-label`s carry the figures. en: totals 1 and 2 render "… of 1 lesson" vs
  "… of 2 lessons" (this is what catches a dropped `count`). pl: every `msgstr[n]` index is
  filled and totals 1, 3, 5 render the exact expected strings (the pl genitive may be
  identical across forms, so this test does not claim to prove plural selection).
- no visible digits: collect the text content of the `.glance` block only (not the title,
  not attributes) and assert it contains no digit. Fixtures use digit-free course titles.
- landing in pl shows Hiszpański A2 / Matematyka / Biologia, is inside `aria-hidden`; the
  `.landing-visual` block (not the whole page, which has CTAs and footer links) contains no
  `<a>` and no `role="img"`, and cards use `.glance-card` (not `.dash-card`).
- landing D8 states: Spanish A2 has fills `width: 70%` and `width: 85%`; Mathematics
  `width: 20%` and `width: 55%`; Biology exactly one fill (`width: 5%`) and neither fill nor
  dot in its results row; no `width: %` anywhere on the page.
- Teaching/Studio panels unchanged for a teacher.

Screenshots: light + dark (dark judged separately), plus forced-colors for the fill. The
checklist explicitly covers the track-only and zero-dot states in both themes: an empty
track must read as an empty bar, not a missing one. If `--border-subtle` disappears on the
card surface, switch the track to a stronger existing border token (it stays LIGHT — D9).
Measured contrast, recorded in the PR for light and dark: the fill (and dot) must reach
≥3:1 against BOTH the track and the card surface (WCAG 1.4.11; `--accent` is the target, a
darker accent variant if it falls short). The track's own ratio against the surface is
recorded but deliberately not held to 3:1 (D9); the spoken figure (D6) carries the
information for users who cannot perceive the track's ends. It also checks that
labels neither wrap nor clip in pl and that both tracks align, including in the narrow
dashboard "My learning" panel.

Timing: the dashboard is the post-login landing page and previously ran no rollups. Before
and after the change, time the dashboard and My courses for a student enrolled in the largest
local course available (and in several courses), and record the numbers in the PR body so a
noticeable slowdown is visible before merge.

Falsification — each must go RED before the suite is trusted:
- `results_width` `None`→0 (dot on "nothing submitted");
- drop the dot branch;
- replace D1 with a mean of per-quiz percentages;
- branch results width on rounded percent instead of `score` (1/300 → dot);
- remove the 99 clamp;
- add a visible `{{ results_pct }}` to the partial;
- test `score == 0` before `percent is None` (pending-only course → dot);
- `progress_width` returns 0 instead of None for 0 of N (progress row draws a dot).

Scoped regression run (the context values of these two views change type): the tests
touching them — `tests/test_consumption_pages.py`, `tests/test_courses_views.py`,
`tests/test_surfaces.py`, `tests/test_help.py`, `tests/test_subject_admin_views.py`,
`tests/test_dashboard_panels.py`, `tests/test_nav_structure.py`,
`tests/test_grouping_course_links.py`, `tests/test_auth_login.py`,
`tests/test_ui_foundation.py` — plus every non-e2e file a grep of `tests/` for
`reverse("home")`, `my_courses`, `landing`, `"/home/"` or `"/courses/"` turns up, plus the
new tests.

## Out of scope

- Visible numbers, tooltips, per-section bars, teacher-side aggregates.
- Any change to how `build_outline` / `build_course_results` compute their figures.
