# Analytics pupil pages — order, breakdown, per-question — design

**Status:** approved in brainstorming 2026-09-16 (three sections, each approved in turn).
spec-review in progress. Not planned, not built.
**Parent work:** `docs/superpowers/specs/2026-09-14-per-question-drill-down-design.md` ("the PR 5
spec"), shipped as #322; and `docs/superpowers/specs/2026-09-12-demo-access-for-schools-design.md`
("the demo spec"), whose PR 4 shipped as #323. Master `359b4d1b`.

**Why now.** These two pages are what a school rep is shown in a demo kit, and the owner read them
on prod on 2026-09-15 and had to stop and work out what he was looking at. The defects are not
bugs in the sense of wrong data — every number is right — but the pages do not say what they mean.
The PR 5 spec ran no design pass (no `frontend-design`, no design section beyond "Styling"), and
the pupil breakdown page predates it entirely.

**Scope.** Three changes, in rising size:

1. **Pupil order and names** in the analytics matrix and the gradebook export.
2. **The pupil results page** (`analytics_student.html` + `_breakdown_node.html`) follows the
   matrix's Progress/Results view, and its emphasis is corrected.
3. **The per-question page** (`analytics_student_quiz.html`) shows every option of a choice
   question, labels the pupil's answer, and carries the outcome in colour — with the outcome
   colours reconciled with what the pupil's own results page already paints.

---

## 1. Decisions taken in brainstorming

Each was the owner's choice, recorded here so the plan does not re-open them.

- **D1 — The pupil page follows the matrix mode.** Not a page-local toggle as the only source, and
  not "results first, always". The mode already reaches the view; it is simply unused (§2.4).
- **D2 — A choice question shows EVERY option**, marked with what the pupil picked and what was
  correct. Rejected: labelled lines only (keeps the defect); options only when wrong (two layouts
  for one type).
- **D3 — The full option list is built teacher-side**, by extending the PR 5 answer builder.
  Rejected: reusing the pupil's own interactive choice markup, which is pupil-voice and carries
  inputs and scripts (§2.6).
- **D4 — Outcome colour is reconciled across both pages.** The badge markup on the two pages is a
  deliberate copy (PR 5 spec §5.1), and a demo rep sees the pupil page through the Student login.
  ⚠️ **Amended in review:** the pupil page already tints its whole question panel by outcome
  (§2.7), so "add the same filled badge to both" would have painted green on green. §5.4 settles
  the treatment that satisfies the decision without that collision.
- **D5 — Order: surname, then first name, Polish alphabetical, username as tiebreak. Display:
  "First Surname".** The owner stated this explicitly against a three-option question.
- **D6 — The pupil page carries a switch to the other view**, so a teacher need not go back to the
  matrix. Approved as one of three "my call" items in section 2.
- **D7 — Chapter headings drop the `x/y required` chip in Results mode** (it counts lessons only,
  §2.3). Approved with D6.
- **D8 — Optional lessons are tagged in Progress mode.** Approved with D6. §2.3 settles the word:
  reuse the existing legend term "Optional" / „Opcjonalne".
- **D9 — The coloured card edge, the decimal comma, and the multi-part header row** were offered as
  flippable and the owner approved all three ("looks good").

**Non-goals.** N1 no new analytics numbers — nothing here changes a score, a percentage or a
rollup. N2 the review queue's own order is untouched (it sorts by title then username, demo spec
§3.2). N3 no change to what the matrix itself renders per cell. N4 no pagination of the pupil page.
N5 the Groups pages keep their current sort and labels — this design borrows their key, it does not
change them.

---

## 2. Findings that constrain the design

All verified against master `359b4d1b` on 2026-09-16.

### 2.1 The matrix and the export sort by username, and nothing pins it

`courses/views_analytics.py:108,110` order the pool by `username` (subset branch and full branch);
`courses/views_export.py:50-54` repeats the identical expression for the gradebook export. A grep
over `tests/` and `courses/tests/` found **no test asserting pupil row order** on either surface,
so the current order is unpinned in both directions: changing it breaks nothing, and nothing would
notice if it silently reverted. §7.1's tests must therefore create the pinning that does not exist.

⚠️ For a demo kit this is why the matrix looks unordered: kit usernames are
`<label>-p01 … -p20` in generation order and the rep's own Student sorts last (demo spec §4.4).

### 2.2 The pieces of the wanted order already exist

- `accounts/models.py:45-55` — `User.sort_name` is `"Last First"` when both structured names
  exist, else `display_name or username`. ⚠️ Its docstring still ends "the app does no locale-aware
  collation anywhere yet", which `grouping/views.py:434,561,605,612,712` already contradicts; §8
  schedules a line-count-neutral repair.
- `accounts/models.py:57-72` — `User.list_display_name` is `"First Last"` with the same fallback,
  **appending the display name in parentheses when it carries information the label does not
  already show** (`:69-71`). §3.2 specifies what that means on each surface.
- `core/collation.py:28-43` — `polish_sort_key` maps each letter to its Polish-alphabet position;
  **whitespace ranks BELOW letters** (`_RANK_SPACE = 0`, `:23`), which is exactly what makes
  `"Nowak Anna"` sort before `"Nowakowska Beata"` through a `"Last First"` key.
- `grouping/views.py:434` — the roster key in use today is
  `(polish_sort_key(student.sort_name), student.username)`.

So D5 is `sorted(pool, key=lambda u: (polish_sort_key(u.sort_name), u.username))` — the same
expression the Groups pages already use, not a second ordering.

⚠️ **The fallback places a no-names login by its display name.** A demo kit's Teacher and Student
carry `display_name = "Uczeń demo — <label> (#pk)"` and no first/last name (demo spec §4.4 steps
2-3), so they sort under "U" among the surnames. That is accepted, not a defect to fix here.

### 2.3 What the pupil page's tree actually holds

`courses/rollups.py:215-263` (`build_outline`) yields node dicts with `node`, `children`,
`required_total`, `required_done`, `additional_done`, `is_unit`, `completed`, `depth`.
`build_student_breakdown` (`:522-542`) folds in a `pill` on every quiz unit, via
`_quiz_pill` (`:498-519`), and returns `{"student": …, "tree": …}`.

- **`required` counts obligatory LESSON units only** (`:221-222`, and `is_obligatory_lesson` at
  `:141-148` is the single source: kind UNIT, type LESSON, `node.obligatory`). Quizzes are excluded
  from both `required_total` and `additional_done`. Hence D7: in a quizzes-only view the chip
  would describe rows that are no longer on the page.
- **The tree knows which lessons are optional but never shows it** — the template renders neither
  `additional_done` nor the per-unit obligatory flag. Hence D8.
- **`Optional` / „Opcjonalne" already exists** as a msgid, used by the course-tree flag legend
  (`templates/courses/manage/_flag_legend.html:57`). D8 reuses it rather than adding a synonym, so
  the tag and the legend agree.
- **`completed` is set for EVERY unit, quizzes included**, but `_breakdown_node.html:4-13` renders
  a pill and no `badge--done` on a quiz row. A submitted quiz can carry `completed=False`, so the
  two signals are not interchangeable — §4.2 settles which row gets which.
- **Callers of `build_student_breakdown`:** one production caller
  (`courses/views_analytics.py:268`) plus **four** test call sites
  (`tests/test_analytics_rollups.py:537,574,775` and `tests/test_publish_analytics.py:263`). A new
  keyword argument with a default is therefore cheap, but two of those tests assert tree shape and
  must be read.

### 2.4 The mode already reaches both drill-down pages — but too late, and not into the context

`_drill_params` (`courses/views_analytics.py:214-222`) parses `scope, mode, expand_pks,
subset_pks, values` from the querystring, and both the pupil page (`:271`) and the per-question
page (`:384`) already call it — to rebuild the *back* link only.

Two consequences the design must handle explicitly:

- ⚠️ **`build_student_breakdown` is called at `:268`, before `_drill_params` runs at `:271`.** The
  mode does not exist yet at the call site §4.1 changes.
- ⚠️ **The pupil view's context is `course, student, breakdown, back_url, drill_qs, has_math`
  (`:281-288`) — no `mode`.** A missing context key is silently falsy in a Django template, so
  every mode-conditional rule would no-op with no error.

`_expand_qs(scope, mode, …)` (`:196-211`) is the single builder for such a querystring, and the
matrix's own view switch is two calls to it with `"progress"` / `"results"` hardcoded
(`:137-138`). D1 and D6 reuse that pattern against the pupil page's own path.

⚠️ **Unknown values already normalise to `progress`** (`:218`: `"results" if … == "results" else
"progress"`), on every surface. The pupil page must not invent a second rule.

### 2.5 Why finished lessons look dimmer than unfinished ones

`core/static/core/css/app.css:1012` is the only emphasis rule on the tree:
`.breakdown-unit__title.is-done{color:var(--text-secondary)}`. A completed unit is therefore
*greyed*, and an incomplete one keeps the primary text colour — so the units a teacher has no
action on shout, and the done ones fade. Chapter heads are `font-weight:600` (`:1009-1010`), which
is what makes a bright incomplete unit title read as another heading.

`.breakdown-unit__link` (`:1014-1015`) sets `color:inherit;text-decoration:none`, with an underline
only on hover/focus — so **the one clickable thing on the page is invisible until hovered**. The
owner hit exactly this: he asked what to click.

⚠️ **`is-done` is only ever emitted on the lesson branch** (`_breakdown_node.html:16`), and CSS has
no notion of the page's mode. So changing that rule is mode-independent, and any rule phrased as
"in Progress mode only" would need a mode class on `.breakdown__tree` to mean anything. §4.2 is
written accordingly.

⚠️ **Three test files depend on this tree's markup, and not only on its class names.**
`tests/test_title_math_markers.py:452-464` selects
`div.breakdown-unit:has(.pill) > span.breakdown-unit__title` — a **direct-child** combinator, in
three assertions — and `tests/test_title_math_css.py` / `tests/test_title_math_assets.py` name the
same classes; `app.css:2092` names `.breakdown-unit__title` in a contrast comment. **Introducing a
wrapper element around the title would break those selectors with a failure that reads as "title
maths marker missing".** §4.2 therefore achieves its right-hand column without a wrapper. Renaming
these classes stays out of scope; restyling them is in scope, and any edit that shifts `app.css`
line numbers re-points the citations in the same commit (repo convention).

### 2.6 The per-question page and its answer builder

- `courses/answer_summary.py` is teacher-voice by construction (PR 5 spec §4). `Part` (`:32-48`) is
  a frozen dataclass of `kind, label_is_content, label, given, expected, ok`, with a `mark`
  **property** deriving the ✓/✗ glyph. `_choice` (`:87-104`) joins the picked option texts into one
  string and the correct ones into another, then calls `_single` — which is precisely why the page
  shows two bare runs and never the options.
- ⚠️ **`_extendedresponse` (`:125-155`) is neither "single-part" nor "multi-part" in the sense §5.2
  uses:** it emits one `kind="answer"` part **plus N `kind="keyword"` parts** whose `label` is
  `"Required: x"` / `"Avoid: x"` and whose `given` and `expected` are both `None`. §5.2 names this
  case explicitly.
- `question.choices.all()` is already prefetched for this page
  (`courses/views.py:354`, `prefetch_related_objects(choice_qs, "choices")`), so D2 adds **no
  queries**. `tests/test_analytics_student_quiz.py:857`
  (`test_t38_query_count_does_not_grow_with_questions`) is the guard that must stay green.
- `Choice` (`courses/models.py:2447-2459`) has `text` (plain text plus KaTeX delimiters, never
  sanitised), `feedback`, `is_correct`, `order`, ordered by `("order", "pk")`.
  `ChoiceQuestionElement.multiple` (`:2279`) distinguishes single from multi-select.
- **The pupil's own results page already has the per-option vocabulary** D2 needs:
  `ChoiceQuestionElement.MARK_GLYPHS` (`courses/models.py:2309-2313`) maps
  `correct → ("✓", "your answer, correct")`, `wrong → ("✗", "your answer, incorrect")`,
  `missed → ("＋", "correct answer, not chosen")`, and `choice_marks` (`:2315-2356`) computes them
  per option. ⚠️ **Those labels are written in the PUPIL's voice**, so the teacher page reuses the
  three *kinds* and *glyphs* but needs its own labels (§6). `test_t35_teacher_voice_only` is the
  guard.
  The matching colours already exist: `courses/static/courses/css/courses.css:377,382-386`
  (`answer-wrong` danger, mark `correct` success, `wrong` danger, `missed` warning).
- ⚠️ **Two decode paths for one stored answer.** `choice_marks` is fed
  `selected_ids(answer_from_json(question, response.latest_answer))` (`courses/views.py:1766-1776`,
  `:1813-1821`) and short-circuits to `{}` when `mark_result is None` or the question is not
  locked; `_choice` instead reads `response.latest_answer` directly. §5.1 settles which is the
  single source, because "both pages agree" is otherwise an assertion rather than a mechanism.
- **`_answers_have_math` (`courses/views_analytics.py:346-360`) scans the unit title, each
  question, review feedback and `part.given/expected/label` — NOT option texts.** Option texts may
  carry KaTeX (`Choice.text`'s own comment says so), so D2 must extend this scan or a maths option
  renders as raw source. This is the one place where D2 can silently half-work.

### 2.7 The pupil's results page already carries outcome colour

⚠️ **This finding reverses a premise of the original D4.** `templates/courses/quiz_results.html:30`
wraps every question's verdict in `question__feedback-panel question__feedback-panel--{{
row.outcome }}`, and `courses/static/courses/css/courses.css:281-302` paints those panels:
`--correct` gets a `--success` left border on `--success-subtle`, `--incorrect` the `--danger`
pair, `--partial` the `--warning` pair, while `--not_answered` deliberately stays neutral. The
badge sits **inside** that panel (`:31-37`).

So a badge filled with `--success-subtle` would land green-on-green and read as *less* signal, not
more. §5.4 picks the treatment that works on both a tinted panel and an untinted card.

Also on those pages: `.badge--review` and `.badge--muted` live in `courses.css:712-716`, not in
`app.css` beside `.badge--open` — and `.badge--muted` uses `--text-tertiary`, which this repo
records as failing AA at body size (a badge is smaller still).

### 2.8 The status pill is shared, and its text is pinned to the breakdown's

`templates/courses/manage/_quiz_pill.html` is included by **both**
`analytics_student_quiz.html:16` and `_breakdown_node.html:8`, and its `scored` branch (`:7`) is
the only place the score pill renders `scored {{s}}/{{m}} ({{percent}}%)`.

⚠️ **`tests/test_analytics_student_quiz.py::test_t36_header_pill_matches_the_breakdown_pill`
asserts the header pill's text equals the breakdown row's pill text, across five pill kinds.** Any
change to either one turns it red. §5.3 changes the header; §7.3 schedules the guard's replacement
and states the invariant that survives.

⚠️ **`_quiz_pill` carries `score`/`max_score`/`percent` ONLY for `kind == "scored"`**
(`rollups.py:503-512`). The page is also reachable with `submitted` (submitted but `max_score ==
0`), `awaiting` and `in_progress`, which carry none of those fields — §5.3 defines all four.

### 2.9 Marks are formatted two different ways on one page

`marks_filter` (`courses/templatetags/courses_extras.py:577-589`) formats a Decimal to at most 2dp
with an ASCII dot and trims trailing zeros; the status pill instead uses `floatformat`
(`_quiz_pill.html:7`), which localises. In Polish the same page therefore prints a badge `0.5/1`
next to a pill „0,5" — observed in the PR 5 implementation log as a "cosmetic, inherited" note and
never fixed.

- The filter is used **15 times across three templates**: `quiz_results.html`,
  `analytics_student_quiz.html`, `course_results.html` (the pupil's course-level results).
- **Four tests pin its current output**: `tests/test_quiz_scoring.py:33-45` expect `"2"`, `"1.5"`,
  `"0.67"`, `"10"`; a fifth asserts `None → "—"`.
- ⚠️ **The CSV/XLSX export does NOT use this filter** — `courses/gradebook.py` builds cells as
  Decimals in Python (`:80-140`) — so localising the filter cannot put a decimal comma into an
  exported file, where it would break parsing. This is what makes D9's decimal comma safe.

### 2.10 Existing tests that assert a rendered pupil name

§3.2 changes how a pupil is named on four surfaces, so these are the tests and comments that
encode today's spelling:

- `tests/demo/test_provision.py:48-49` carries the comment "The analytics templates render
  `display_name|default:username` and nothing else, so a pupil without one shows as
  'sp-12-p01'" — which §3.2 falsifies. Repaired line-count-neutral (repo convention).
- `tests/test_analytics_views.py` and `tests/test_e2e_analytics.py` both build pupils with
  `UserFactory(display_name="Ada L.")`; `tests/test_views_export.py` covers the export.
  **The plan's first task on §3.2 is to grep these three files for name assertions and list them**
  — the count is not asserted here because it was not measured.

### 2.11 The help screenshots these changes invalidate

`tests/capture_help_screenshots.py` captures 26 PNGs. Two shot definitions are affected:

- `:174-180` — `analytics-matrix`, from `manage_analytics` clipped to `.analytics__matrix`, whose
  row headers are the pupil names **whose order and spelling §3 changes**. Invalidated by PR A.
- `:181-187` — `drill-down`, from `manage_analytics_student` for `demo_s1`, clipped to
  `.breakdown__tree`. Invalidated by PR B (§4).

⚠️ **The script rewrites all 26 PNGs on a local renderer and is NOT `@pytest.mark.e2e`** (demo spec
findings; the owner's memory records both). Each PR regenerates its own two shots (en + pl) and
restores the rest with `git checkout -- core/static/core/img/help/`.

---

## 3. Pupil order and names

### 3.1 One ordering helper

A single function — `ordered_students(queryset)` in **`grouping/scoping.py`**, beside
`students_in_scope`, which is where both call sites get their pool from
(`courses/views_analytics.py:37` and `courses/views_export.py:16` both do
`from grouping import scoping`). It gains a `from core.collation import polish_sort_key` import,
which that module does not have today. It returns a **list**:

```python
def ordered_students(students):
    """Register order: surname, then first name, Polish alphabetical (spec §3.1)."""
    return sorted(students, key=lambda u: (polish_sort_key(u.sort_name), u.username))
```

**Rejected: `courses/ordering.py`.** That module exists, but it is the *content-node* ordering
space (move / assign / compact / place, over `ContentNode` and `Element`); a pupil-display helper
there would overload the name and drag `accounts`/collation imports into it. Placing the helper
beside the pool's producer keeps "who may be listed" and "in what order they are listed" together.

Both matrix builders already call `list(students)` internally
(`courses/rollups.py:753,811`), and both gradebook builders preserve the order they are handed
(`courses/gradebook.py:76,105` iterate the list; `build_matrix_table:40-48` maps matrix rows in
order), so a list is a safe substitute for the queryset at every call site.

**Call sites changed:** `views_analytics.py:107-110` and `views_export.py:50-54`. The helper
wraps the **whole** subset/no-subset expression, so the two views cannot drift on where it is
applied:

```python
students = scoping.ordered_students(
    pool.filter(pk__in=subset_pks) if subset_pks else pool
)
```

**Why a helper rather than four inline `sorted(...)` calls:** the matrix and the export must not be
able to drift apart — a teacher comparing the screen with the file is the case that catches a
divergence, and it is the one case nobody tests by hand.

### 3.2 One display label

`list_display_name` replaces `display_name|default:username` in:

- `templates/courses/manage/analytics_matrix.html:144` (the checkbox's `aria-label`) and `:145`
  (the row's name cell, linked and unlinked branches);
- `courses/gradebook.py:42,133` (the exported `name` column, both shapes).

The two drill-down page headings (`analytics_student.html:9`,
`analytics_student_quiz.html:11`) also switch to it, but **in PR B**, where those headings are
rewritten anyway (§8) — PR A must not touch those two lines.

⚠️ **The parenthetical branch is reachable here.** A pupil with first + last **and** an unrelated
display name renders `"Anna Nowak (Uczeń demo — sp-12 (#41))"` (`accounts/models.py:69-71`). That
is accepted as-is on every surface, including the matrix row header and the CSV column: it is the
app-wide roster convention, it is information the teacher may need, and truncating it in a row
header would hide exactly the disambiguation it exists for. No `middle_truncate`, no ellipsis.
§7.1 T3 covers the case so the rendering is at least pinned.

Unchanged by decision: the review queue and review submission screens (N2), and everything under
`grouping/`, which already uses `list_display_name`.

### 3.3 What this does not do

No index, no `db_collation`, no `Func`-based ordering in SQL. The sort is in Python over a pool
that is already fully materialised for rendering; a class is tens of pupils, and the matrix builder
lists it regardless. If a future box ever needs thousands of rows on one screen, that is a
different design.

---

## 4. The pupil results page

### 4.1 Mode reaches the tree, the context and the template

`build_student_breakdown(course, student, *, drafts, with_data=None, mode="progress")` gains a
keyword argument, defaulted so the four existing test call sites (§2.3) keep their behaviour.

**The view (`analytics_student`, `views_analytics.py:257-289`) changes in three ways:**

1. `_drill_params(request)` moves **above** the `build_student_breakdown` call — today it runs
   after it (§2.4) — so the mode exists when the builder is called.
2. The builder receives `mode=mode`.
3. The context gains `mode` and `other_view_url` (§4.3). `_breakdown_node.html` reads `mode` from
   the inherited context: its recursive `{% include %}` (`:26`) passes `with item=child
   course=course` and **no `only`**, so outer context stays visible — the plan must not add `only`.

⚠️ **`has_math` (`:277`) now scans the PRUNED tree.** That is intended: in Results mode a lesson
title carrying maths is not on the page, so KaTeX need not load for it. It is stated because the
line reads as unchanged while its meaning moves.

**In `results` mode the tree is pruned** after the pill pass:

- keep every quiz unit, with its pill;
- keep a container iff it has a kept descendant;
- drop every lesson unit;
- the containers' `required_total` / `required_done` / `additional_done` stay on the dict; the
  template stops **rendering** the chip when `mode == "results"` (D7).

**In `progress` mode the tree is unchanged**, lessons included.

⚠️ **Pruning runs after `attach`, never before**: `_quiz_pill` is keyed off
`build_course_results`' rows, and a container dropped early would take its quiz with it.

⚠️ **A quiz with no submission keeps its `not_started` pill and stays on the page** — the gaps are
the point of the view. `_quiz_pill`'s fallback branch (`rollups.py:519`) already returns that kind
with no `submission_pk`, and `_breakdown_node.html:6` already renders an unlinked title for it.

### 4.2 What each row shows

**The right-hand column, in both modes.** A quiz row carries its **pill**; a lesson row carries its
**completion marker**. They share the column's *position*, not its contents — a quiz row never
grows a completion marker, because `completed` and "submitted" are different facts (§2.3) and two
status signals per row would contradict each other.

⚠️ **The alignment is achieved without a new wrapper element** — `margin-left:auto` on the
right-hand item, mirroring `.badge--done` (`app.css:739`) — because a wrapper would break the
three direct-child selectors in `tests/test_title_math_markers.py:452-464` (§2.5). If the design
pass concludes a wrapper is unavoidable, updating those three selectors moves into the same commit,
with their docstrings amended to say why.

**Both modes**
- A quiz title is a **visible link** when it has a submission: link colour plus a persistent
  underline, not `color:inherit` with a hover-only underline (§2.5). An unstarted quiz stays plain
  text.
- The `Review` link for a quiz awaiting review is unchanged (`_breakdown_node.html:9-11`).

**Lesson rows (Progress mode is the only mode that renders them)**
- Every unit title uses the **normal text colour**: `.breakdown-unit__title.is-done`
  (`app.css:1012`) no longer greys a completed lesson. The rule change needs no mode scoping —
  `is-done` is only ever emitted on the lesson branch (§2.5), which Results mode does not render.
- A finished lesson is marked by a ✓, an unfinished one by an **empty circle** with an accessible
  name („Nieukończone"), so "no mark" cannot be confused with "not rendered" and colour is not the
  signal.
- An **optional lesson** carries a quiet „Opcjonalne" tag (D8, §2.3), so an unfinished lesson that
  does not count toward `x/y wymagane` says so.

**Results mode only**
- Lessons are absent; chapters with no quiz are absent; the chapter chip is not rendered (D7).

### 4.3 The page's name, its heading and the view switch

**"Breakdown" / „Szczegóły ucznia" is retired as the page's name.** The owner's own term for this
page in prose is „wyniki ucznia" (settled while merging #323, and now used in
`docs/help/teacher/drill-down.pl.md`). Keeping a third name for one page is what makes the back
link („← Szczegóły ucznia") read as a different destination than the page it returns to.

| surface | today | after |
|---|---|---|
| `analytics_student.html:3` `head_title` | `Breakdown` / „Szczegóły ucznia" | `Pupil results` / „Wyniki ucznia" |
| `analytics_student.html:9` `h1` | „Szczegóły ucznia — X" | „Wyniki — X" or „Postęp — X" (the view) |
| `analytics_student_quiz.html:12` back link | „← Szczegóły ucznia" | „← Wyniki ucznia" |
| `docs/help/teacher/drill-down.{md,pl.md}` | "Per-student breakdown" / „Wyniki pojedynczego ucznia" | follows the table above |

- The `h1` names the **view**, reusing the matrix's own msgids (`Results` / `Progress`,
  `locale/pl:2628,2633`), with the pupil's `list_display_name`.
- Beside it, a link to the **other** view of the same pupil: `f"{student_path}?{_expand_qs(scope,
  other_mode, expand_pks, subset_pks, values)}"`, built exactly as the matrix builds its own pair
  (§2.4) and passed to the template as `other_view_url`. It preserves scope, expanded columns,
  subset and values.
- „← Analityka" is unchanged, and the per-question page's back link already carries the mode.

---

## 5. The per-question page

### 5.1 A choice question shows every option

`_choice` (§2.6) stops emitting the two joined runs and returns **one part of a new kind**:

```python
Part(kind="options", label=None, label_is_content=False, given=None, expected=None, ok=None)
```

`Part` gains an `options` field defaulting to `None`, so every other builder is untouched and its
existing `mark` property is unaffected. `Option` is a frozen dataclass **in
`courses/answer_summary.py`**, beside `Part`:

```python
@dataclass(frozen=True)
class Option:
    text: str
    picked: bool
    correct: bool | None   # None when the question is not auto-marked

    @property
    def mark(self):        # derived, mirroring Part.mark
        ...
```

`mark` is a **property**, not a stored field, for the same reason `Part.mark` is: one rule, no way
to construct a record whose flags and glyph disagree.

**The `mark` rule, with its precedence stated:**

1. **If `correct is None` (the question is not auto-marked), `mark` is `None` for every option,
   whether picked or not.** There is no key, so no verdict may be implied.
2. Otherwise: picked and correct → `"correct"`; picked and not correct → `"wrong"`; not picked and
   correct → `"missed"`; not picked and not correct → `None`.

Rule 1 wins over rule 2. Stated because the naive reading of rule 2 alone marks every pick on a
REVIEW question `"wrong"`.

**`picked` reads `response.latest_answer` directly**, the shortcut `_choice` already takes today,
and **that raw read is declared the single source** for both pages. The pupil page's
`choice_marks` path decodes via `selected_ids(answer_from_json(...))` (§2.6); the two are expected
to agree, and §7.3 T13b renders the same submission on both pages and asserts identical per-option
kinds rather than leaving the agreement asserted in prose.

**Rules**
- **A picked option that no longer exists** renders as an extra row reading „(usunięta opcja)",
  reusing the existing msgid (`locale/pl:423`) that `_choice` already emits today.
- **Not answered** — every option is listed, none picked, the key still marked. The row badge
  („Bez odpowiedzi") carries the not-answered state; the options block itself renders no
  „Not answered" fallback text, because the block is a list of options, not an answer run.
- **Not auto-marked** — options listed with picks only; the „Poprawna odpowiedź" column is omitted
  entirely (not rendered empty).
- **In progress** — the key is shown, exactly as PR 5 decided for the rest of the page (that
  spec's D5: a teacher sees the key even with attempts left).

**Markup.** A `<table class="answers__options">` inside the part loop, with a new
`{% if part.kind == "options" %}` branch in `analytics_student_quiz.html:61-75` — placed **before**
the existing `kind == "answer"` branch (`:64`), which stays untouched for every other type. Two
narrow leading columns („Wybór ucznia", „Poprawna odpowiedź") carry the markers, the third the
option text (`lang="{{ course.language }}"`, since options are course content). The header cells
are real `<th>` elements, so the column meaning is available to a screen reader on every row; each
marker cell pairs an `aria-hidden` glyph with its own teacher-voice `sr-only` label (§6).

At 390px the table keeps its shape: the two marker columns are ~2rem each and the text column
takes the rest. It is **not** subject to `.answers__part`'s `@media (max-width:640px)`
column-stacking rule (`app.css:1036-1039`), which applies to `.answers__part`, not to this table;
the plan asserts that in the phone screenshot rather than assuming it.

### 5.2 Every other type keeps its parts, and gains labels

- **Single-part types** (short text, short numeric, choice-as-single is gone by §5.1) render
  „Odpowiedź ucznia: …" and, only where the part is not right, „Poprawna odpowiedź: …" (the latter
  msgid exists, `locale/pl:5459`).
- **Multi-part types** — fill-in-the-blank, matching pairs, both grids, drag-to-image — keep their
  per-part content label and gain **one header row per question**: „Odpowiedź ucznia" |
  „Poprawna odpowiedź" (D9). To give that header something to head, `.answers__parts` becomes a
  **three-column grid** (label | given | expected) for these types, and the per-part
  „Poprawna odpowiedź:" prefix (`analytics_student_quiz.html:71`) is dropped where the header row
  is present — otherwise the page says it twice. At 390px the existing stacking behaviour wins:
  the header row is hidden and each part's expected value regains its inline prefix.
- ⚠️ **Extended response with keywords is neither.** `_extendedresponse` emits one `answer` part
  plus N `keyword` parts carrying only a label and a ✓/✗ (§2.6). Its answer part takes the
  single-part label („Odpowiedź ucznia:"); its keyword parts keep today's label-plus-glyph shape,
  get **no** header row and **no** columns. A question mixing the two must not be forced into the
  grid.
- `Part.label_is_content` still decides `lang` tagging (PR 5 spec §5.1) — the new header row and
  the option table's `<th>`s are interface text and carry no `lang`.

### 5.3 The header

- **Two lines, not one dash-joined title:** the pupil's `list_display_name` on a small line above,
  the quiz title as the `h1` below. Today's `"{{ unit.title }} — {{ student… }}"`
  (`analytics_student_quiz.html:11`) produced „Zbiory - quiz — Mateusz Adamczyk", two dashes of
  different meaning in one line.
- The back button sits beside the heading and does not wrap beneath a long title (the PR 5
  implementation log records the wrap).
- **The score becomes the page's most prominent figure, for the one pill kind that has one.** The
  header renders, by pill kind:

  | pill kind | prominent figure | state shown |
  |---|---|---|
  | `scored` | „1 / 5 pkt" + „20%" | — |
  | `submitted` (ungraded, `max_score == 0`) | none | „przesłano" |
  | `awaiting` | none | „oczekuje na ocenę" + the „Sprawdź" link |
  | `in_progress` | none | „w toku" + „Odpowiedzi: 3 z 6" (existing plural msgid, `locale/pl:6229`) |

  No dash, no „0 / 0" placeholder: a kind with no score renders no score element at all.
- **The shared pill partial is not mutilated.** `_quiz_pill.html` gains a `show_score` flag,
  defaulting to true, and the per-question header includes it as
  `{% include "courses/manage/_quiz_pill.html" with p=pill show_score=False %}` — the breakdown's
  include (`_breakdown_node.html:8`) is unchanged and its rows keep their scores (§2.8). Inside the
  partial, the `scored` branch renders the state word „przesłano" when `show_score` is false, so
  the pill is never empty.

### 5.4 Outcome colour, reconciled across both pages

⚠️ Per §2.7, the pupil's page already tints the whole question panel by outcome. The badge
therefore takes a treatment that reads on a tinted panel **and** on the teacher page's untinted
card: **an outlined badge** — transparent background, `1px` border and text in the outcome colour —
not a `-subtle` fill.

| outcome | badge | applies to |
|---|---|---|
| `correct` | outlined `--success` | both pages |
| `partial` | outlined `--warning` | both pages |
| `incorrect` | outlined `--danger` | both pages |
| `not_answered` | muted — moved from `--text-tertiary` to `--text-secondary` (§2.7) | both pages |
| `recorded`, `reviewed` | unchanged (neutral) | both pages |
| `review` | unchanged `.badge--review` (`courses.css:712`) | both pages |

The modifiers are defined in **`courses/static/courses/css/courses.css`, beside `.badge--review`
and `.badge--muted` (`:712-716`)** — both consuming pages link that sheet, and splitting the badge
family across two files for no reason is how the next person fails to find them.

Applied in `templates/courses/manage/analytics_student_quiz.html:46-52` and
`templates/courses/quiz_results.html:31-37`, which stay deliberate copies of one another (PR 5
spec §5.1); the drift note in both templates is updated to say the modifier is part of the copy.

**On the teacher page only, the question card's left edge takes the outcome colour**
(`.answers__item.is-correct` / `.is-partial` / `.is-incorrect` — classes the template already emits
at `:28` and which today have no rules at all; the PR 5 log flagged them as unstyled). This is the
teacher-page equivalent of the pupil page's panel tint, so the two pages end up with the same
information in the same visual language. Colour is never the only signal: the badge word and the
✓/✗ glyph stay.

⚠️ **Dark mode is not free here.** `.pill--scored` hardcodes `color:#fff` on `--primary`, and
`.pill--awaiting` hardcodes `#f5b942`/`#3a2a00` (`app.css:1044-1049`) — neither follows the theme.
Both are re-expressed in tokens as part of this section and judged in the dark screenshots, as is
the outlined badge's contrast on both a tinted panel and a plain card.

### 5.5 Marks read the same everywhere

`marks_filter` keeps its 2dp-and-trim rule and its `None → "—"` branch, and localises the decimal
separator by passing the trimmed string through
`django.utils.formats.number_format(value, decimal_pos=None, force_grouping=False)`.

- **`force_grouping=False` is required, not incidental:** `number_format` would otherwise apply
  `USE_THOUSAND_SEPARATOR` grouping, and in Polish that is a non-breaking space — „1 000" in a
  badge. Marks are a magnitude, not a quantity to group.
- The quantize-then-trim step runs first and `decimal_pos` is left `None`, so the trimming rule
  stays the filter's own and is not re-imposed by the formatter.
- In Polish a half mark reads „0,5" in the badge, matching the pill; in English it is unchanged.
- `tests/test_quiz_scoring.py:33-45` are updated to assert per-locale output rather than the ASCII
  form (the pinned values are the specification of the old behaviour, so they must move
  deliberately, not be deleted), and a value ≥ 1000 is added.
- The exported file is unaffected (§2.9) and T23 says so explicitly.

---

## 6. Interface text

New msgids, with the Polish for the owner to approve on the PR. Existing msgids are reused wherever
one exists — the right-hand column names them rather than re-inventing them.

| English (new) | Polski (proposed) | where |
|---|---|---|
| `Pupil's answer:` | „Odpowiedź ucznia:" | §5.2 single-part label |
| `Pupil's answer` | „Odpowiedź ucznia" | §5.2 multi-part header, §5.1 option column |
| `Pupil's choice` | „Wybór ucznia" | §5.1 option column header |
| `chosen, correct` | „wybrana, poprawna" | §5.1 screen-reader label |
| `chosen, incorrect` | „wybrana, niepoprawna" | §5.1 screen-reader label |
| `correct, not chosen` | „poprawna, niewybrana" | §5.1 screen-reader label |
| `%(s)s / %(m)s marks` | „%(s)s / %(m)s pkt" | §5.3 score stat |
| `Not completed` | „Nieukończone" | §4.2 empty-circle marker |
| `Pupil results` | „Wyniki ucznia" | §4.3 page name, back link |

⚠️ **The score's percentage is NOT in that msgid.** „1 / 5 pkt" and „20%" are two elements —
`<span class="answers__score">` and `<span class="answers__percent">` — with the separator supplied
by CSS, not by a literal „·" glued onto a translated string. A translator never receives half a
sentence, and the order of the two can change per language without a new msgid.

⚠️ **Three near-identical Polish words land in one question card** and want the owner's judgement
together, not row by row: „Poprawnie" (the verdict badge), „Poprawna odpowiedź:" (the key label,
existing) and „Poprawna odpowiedź" (the option column header, proposed). If that reads as
repetitive, „Klucz" is the alternative for the column header. Flag all three in the PR body as one
question.

Reused, not re-created: `Correct answer:` (`locale/pl:5459`), `(removed option)` (`:423`),
`(none)` (`:427`), `Not answered` (`:6243`), `Correct` / `Incorrect` / `Partial`, `Review`
(`:5636`), `Optional` (`:5670`), `Progress` / `Results` (`:2633,2628`), `Completed`,
`%(k)s of %(n)s question answered` (`:6229`), and every pill word (`:5395,5386,5912,5916,5920`).

⚠️ `makemessages` fuzzy-prefills new msgids from similar existing ones — it did exactly that twice
in #323. Every new entry above is checked by hand and the catalogs must end at 0 fuzzy.

---

## 7. Tests

Every rule below is falsified against a named mutant, run and observed red, then reverted by hand
(repo convention; the owner's memory records why a scripted revert is dangerous).

### 7.1 Order and names (§3)

- **T1** A class whose username order disagrees with surname order appears in the matrix in
  surname-then-first-name order. The fixture carries, deliberately:
  - `Świątek` — sorts after `S…`, before `T…` (Polish alphabet, not codepoint);
  - **`Nowak` and `Nowakowska`** — one surname a strict prefix of the other, which is the ONLY
    case that exercises `_RANK_SPACE = 0` (§2.2); *mutant:* `_RANK_SPACE = 3` → red;
  - two pupils sharing a surname with different first names (first-name tiebreak);
  - one login with no first/last name (display-name fallback).
  *Mutant:* restore `order_by("username")` → red.
- **T2** The same class exports in the same order, asserted on the parsed file, not the HTML.
  *Mutant:* order the export by username only → red. This is the pair T1 cannot catch alone.
- **T3** The matrix renders „Mateusz Adamczyk"; the checkbox label names the same string; a
  no-names login falls back to its display name; **and a pupil with first + last + an unrelated
  display name renders the parenthetical form in full** (§3.2). *Mutant:* revert to
  `display_name|default:username` → red for the structured-name pupil.
- **T4** Non-vacuity: the fixture's username order and surname order genuinely differ, asserted
  directly, so T1/T2 cannot pass by coincidence.
- **T5** The two drill-down headings still render `display_name|default:username` **after PR A**
  (they move in PR B, §8) — the guard that keeps PR A off PR B's lines.
- ⚠️ No assertion may rest on database ids — a pk-order coincidence is a known flake source in this
  repo (four occurrences).

### 7.2 The pupil page (§4)

- **T6** `?mode=results`: quiz titles present, **no lesson title present**, a chapter holding no
  quiz absent, an unstarted quiz present with its „nie rozpoczęto" pill.
  *Mutant:* skip the prune → red on the lesson assertion.
- **T7** `?mode=results`: a rendered chapter carries **no `.rollup` element** (D7).
  *Mutant:* keep the chip in both modes → red. Without this, leaving
  `{% if item.required_total %}` untouched ships D7's defect with T6 green.
- **T8** `?mode=progress`: lessons present, chapter chips present — today's behaviour.
  *Mutant:* prune unconditionally → red.
- **T9** No `mode`, and `?mode=nonsense`, both render Progress. *Mutant:* default to results → red.
- **T10** Pruning keeps an ancestor chain: a quiz nested three deep still renders with its part and
  chapter above it. *Mutant:* prune containers before `attach` → red (the quiz disappears).
- **T11** The view switch link points at the same pupil with the opposite mode and preserves scope,
  expand, subset and values. *Mutant:* drop `subset_pks` from its querystring → red.
- **T12** An optional lesson carries the „Opcjonalne" tag and an obligatory one does not.
  *Mutant:* tag every lesson → red.
- **T13** A quiz row carries a pill and **no** completion marker; a lesson row carries a marker and
  no pill, with the unfinished marker carrying its accessible name (§4.2).
  *Mutant:* render the marker on every unit → red (a `completed=False` submitted quiz would show
  an empty circle beside its „przesłano" pill).
- **T14** The quiz title's link is **visibly** a link — underline present without hover — via
  T27's computed-style A/B. `test_t37_quiz_titles_link_iff_the_pupil_has_a_submission` already
  covers the `<a>`-presence half across five submission states and is **not** duplicated here.
- **T15** The four existing `build_student_breakdown` call sites still pass with the default
  argument — i.e. the default really is `progress`.
- **T16** `has_math` is computed from the pruned tree: a Results-mode page whose only maths title
  belongs to a lesson does not load KaTeX (§4.1). *Mutant:* scan before pruning → red.

### 7.3 The per-question page (§5)

- **T17** Builder, one case each: picked-and-correct, picked-and-wrong, missed, untouched,
  deleted-but-picked, not answered, `multiple=True`.
  *Mutants:* invert `picked`; drop `missed` — each red on its own case.
- **T18** A **non-auto-marked** choice question yields `mark is None` for every option, including
  the picked ones, and renders no „Poprawna odpowiedź" column (§5.1 rule 1).
  *Mutant:* apply rule 2 without rule 1 → red (the pick shows „wybrana, niepoprawna").
- **T19** The same submission renders identical per-option kinds on the teacher page and on the
  pupil's results page (`choice_marks`), including a multi-select with one right and one missed
  option. *Mutant:* make the teacher page treat an unpicked correct option as `None` → red. This
  is the mechanism behind §5.1's single-source claim.
- **T20** The rendered page lists **every** option of a choice question, in author order, not only
  the picked ones. *Mutant:* render only picked options → red.
- **T21** Teacher voice: `test_t35_teacher_voice_only` is extended over the new labels — no
  „twoja"/"your" anywhere in the options block.
  *Mutant:* reuse `MARK_GLYPHS`' pupil-voice labels → red (§2.6 makes this a live risk).
- **T22** A maths delimiter **in an option text** loads KaTeX. *Mutant:* leave
  `_answers_have_math` unextended → red. Without this, §5.1 ships a page that renders raw LaTeX to
  a school rep.
- **T23** `test_t38_query_count_does_not_grow_with_questions` still passes with options rendered.
  *Mutant:* re-query `question.choices.all()` outside the prefetch → red.
- **T24** Extended response with keywords: the answer part carries „Odpowiedź ucznia:", the keyword
  parts carry neither a column header nor an empty expected cell (§5.2).
  *Mutant:* route keyword parts through the multi-part grid → red.
- **T25** Badge modifier per outcome on **both** templates, asserted on the rendered class.
  *Mutant:* remove the modifier from one template → red (this is what stops the deliberate copy
  drifting). The card-edge class is asserted on the teacher page only.
- **T26** Header, per pill kind (§5.3): `scored` renders the score element; `submitted`,
  `awaiting` and `in_progress` render **no** score element, and `in_progress` renders the
  answered-count phrase. *Mutant:* render the score unconditionally → red on three of four kinds.
- **T27** `test_t36_header_pill_matches_the_breakdown_pill` is **replaced, not deleted**: its
  invariant becomes "the header pill and the breakdown pill show the same **state word**", since
  the header's pill no longer carries the score (§5.3). A second assertion pins the other half: the
  breakdown row **still shows the score** for a scored quiz. *Mutant:* let `show_score` default to
  false → red on the breakdown half.
- **T28** The heading renders the pupil's name and the quiz title as separate elements, and does
  not contain „ — ". *Mutant:* restore the joined title → red.
- **T29** In Polish, a half mark renders „0,5" in the badge **and** in the score; in English,
  „0.5"; a mark of 1000 renders without a thousands separator in both (§5.5).
  *Mutants:* revert `marks_filter` to the ASCII form → red; drop `force_grouping=False` → red on
  the 1000 case.
- **T30** The exported gradebook still writes a dot decimal (§2.9). *Mutant:* localise the
  export's numbers → red. T29 and T30 are a deliberate pair: one demands the comma, the other
  forbids it where it would corrupt a file.
- **T31** The options block renders as a table with real `<th>` column headers and per-marker
  `sr-only` labels (§5.1). *Mutant:* drop the `sr-only` labels → red.

### 7.4 Visual

- **T32** Screenshots, light and dark, desktop and 390px, on mat-pp data:
  - the Results and Progress pupil pages;
  - the per-question page for a submitted quiz with a wrong choice answer (the owner's
    „Zbiory - quiz" question 1 is the reference case), an in-progress quiz, and a quiz with a
    question awaiting review;
  - **`quiz_results.html`, the pupil's own results page** — §5.4 changes its badge on top of an
    already-tinted panel (§2.7), which is the drift-prone twin named in §9;
  - **`course_results.html`**, the third page §5.5's decimal comma reaches.
  Dark is judged on its own, not as "light but darker".
- **T33** Any CSS rule this design relies on is confirmed by comparing the computed style **with
  and without** the rule, never by asserting the rule exists (repo convention: a CSS existence
  check proves nothing). This covers the persistent underline (T14), the outlined badge, the card
  edge and the right-hand column's alignment.
- **T34** Help screenshots: each PR regenerates its own two shots (§2.11) and leaves the other 24
  untouched, asserted by `git status` listing exactly those two files.

---

## 8. Delivery

Two PRs, in order.

**PR A — pupil order and names (§3).** The helper, the two views, the matrix template's two lines
and `gradebook.py`'s two name fields; T1–T5. It regenerates `analytics-matrix.{en,pl}.png`
(§2.11), repairs the stale `sort_name` docstring and the stale `test_provision.py:48-49` comment,
both line-count-neutral, and inventories the name assertions listed in §2.10.

⚠️ **PR A must NOT touch `analytics_student.html:9` or `analytics_student_quiz.html:11`** — the
two headings PR B rewrites (§4.3, §5.3). T5 pins that boundary, so the two PRs cannot collide on
those lines and PR B needs no rebase beyond the ordinary one.

**PR B — the two pages (§4, §5, §6).** The design pass (`frontend-design`) runs inside this PR,
after the markup exists and before the screenshots are judged. It regenerates
`drill-down.{en,pl}.png`. Ships new msgids; no migration, no `FORMAT_VERSION` bump, no new
dependency.

**Docs.** `docs/help/teacher/drill-down.md` and `.pl.md` describe both pages and gain: the
Results/Progress distinction, the view switch, the optional tag, and the option list; their page
name follows §4.3's table. `docs/help/teacher/analytics.md` and `.pl.md` gain one sentence on pupil
order.

**Rollout.** Nothing here is gated by `LIBLI_VENDOR_INSTANCE`: these are ordinary teacher screens
on every box, including schools' real-pupil instances. The demo kit is only the reason the defects
were noticed.

---

## 9. Risks

1. **The maths-scan miss (§2.6).** The one defect that would ship silently and be seen first by a
   school rep. T22 is not optional.
2. **The deliberate template copy (§5.4).** `quiz_results.html` and `analytics_student_quiz.html`
   must stay parallel; T25 asserts both, and both templates carry the note.
3. **The shared pill partial (§2.8, §5.3).** A careless edit deletes the score from every quiz row
   on the breakdown; T27's second half is what catches it.
4. **Decimal comma reaches a third page** — `course_results.html` (§2.9), which nothing else in
   this design touches. Accepted deliberately: one rule for marks across the product beats two.
5. **Screenshot regeneration side effects (§2.11).** A careless run rewrites 26 committed PNGs on
   the local renderer. T34 pins the outcome, per PR.
6. **Structural test dependencies (§2.5).** Three title-maths test files select the breakdown tree
   by direct-child combinators; a wrapper element added for §4.2's column breaks them with a
   misleading message.
