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
  inputs and scripts (§2.6). ⚠️ **Refined twice in review:** the builder does not re-derive the
  per-option verdicts, and it does not re-issue the `choice_marks` call either — the marks dict the
  page already computes is **passed in** (§5.1), so there is exactly one call site.
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
- **D8 — Optional lessons are tagged in Progress mode.** Approved with D6. ⚠️ **The word is
  „Dodatkowa", not „Opcjonalne"** — §2.3 explains why the product already owns this vocabulary.
- **D9 — The coloured card edge, the decimal comma, and the multi-part header row** were offered as
  flippable and the owner approved all three ("looks good").

**Non-goals.** N1 no new analytics numbers — nothing here changes a score, a percentage or a
rollup. N2 the review queue's own order is untouched (it sorts by title then username, demo spec
§3.2), and so is how it names a pupil. N3 no change to what the matrix itself renders per cell.
N4 no pagination of the pupil page. N5 the Groups pages keep their current sort and labels — this
design borrows their key, it does not change them.

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
  `"Nowak Anna"` sort before `"Nowakowska Beata"` through a `"Last First"` key. ⚠️ That property
  is **already pinned** by `tests/test_collation.py::test_space_sorts_before_letters` — §7.1 T1
  must not claim it as its own falsification.
- `grouping/views.py:434` — the roster key in use today is
  `(polish_sort_key(student.sort_name), student.username)`.

So D5 is `sorted(pool, key=lambda u: (polish_sort_key(u.sort_name), u.username))` — the same
expression the Groups pages already use, not a second ordering.

⚠️ **A kit login sorts by its display name, and the two kit logins differ.** `demo/services.py:289`
gives the Teacher `"Nauczyciel demo — <label> (#pk)"` and `:305` gives the Student
`"Uczeń demo — <label> (#pk)"`, neither with first/last names — so the Teacher sorts under **"N"**
and the Student under **"U"**, among the pupils' surnames. The kit's generated pupils DO carry
`first_name`/`last_name` plus a matching `display_name` (`:320`), so they sort by surname properly.
This placement is accepted, not a defect to fix here.

### 2.3 What the pupil page's tree actually holds

`courses/rollups.py:215-263` (`build_outline`) yields node dicts with `node`, `children`,
`required_total`, `required_done`, `additional_done`, `is_unit`, `completed`, `depth`.
`build_student_breakdown` (`:522-542`) folds in a `pill` on every quiz unit, via
`_quiz_pill` (`:498-519`), and returns `{"student": …, "tree": …}`.

- **`required` counts obligatory LESSON units only** (`:221-222`, and `is_obligatory_lesson` at
  `:141-148` is the single source: kind UNIT, type LESSON, `node.obligatory`). Quizzes are excluded
  from both `required_total` and `additional_done`. Hence D7: in a quizzes-only view the chip
  would describe rows that are no longer on the page.
- ⚠️ **"Optional lesson" is already a named concept with ONE rule and ONE word.**
  `rollups.unit_marker` (`:169-195`) is documented as "the ONE student-facing kind rule" and
  returns `MARKER_ADDITIONAL` for exactly a non-obligatory LESSON unit; `UNIT_MARKER_LABELS`
  (`:163-166`) maps it to `Additional` / „Dodatkowa", and `marker_label` (`:198-203`) translates
  it. The flag legend's „Opcjonalne" (`_flag_legend.html:57`) is the *node-flag* vocabulary on the
  "Requirement" axis — a different surface for the author, not the reader.
  **D8 therefore reuses `unit_marker` / `marker_label`**, so the teacher's breakdown and the
  pupil's own outline call the same lesson by the same name.
  ⚠️ **But `unit_marker` also returns `MARKER_QUIZ` for every quiz unit** (`:190-191`), labelled
  `Quiz` / „Kwiz", and the existing chip partial (`templates/courses/_unit_kind_chip.html`) renders
  **any** truthy marker. Reusing that partial unguarded would put a „Kwiz" chip on every quiz row
  in both modes — something no decision here asks for. §4.1 stamps a boolean, not the raw marker.
  ⚠️ Its docstring forbids rewriting the rule as `not is_obligatory_lesson(node)` — do not
  "simplify" it in passing.
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

Three consequences the design must handle explicitly:

- ⚠️ **`build_student_breakdown` is called at `:268`, before `_drill_params` runs at `:271`.** The
  mode does not exist yet at the call site §4.1 changes.
- ⚠️ **The pupil view's context is `course, student, breakdown, back_url, drill_qs, has_math`
  (`:281-288`) — no `mode`.** A missing context key is silently falsy in a Django template, so
  every mode-conditional rule would no-op with no error.
- ⚠️ **That view computes `matrix_path` only** (`:272`); it has no `student_path`. §4.1 lists the
  `reverse()` the view switch needs.

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

⚠️ **FOUR test dependencies on this tree's markup, not merely on its class names:**

| file:line | selector | feeds |
|---|---|---|
| `tests/test_title_math_markers.py:452-464` | `div.breakdown-unit:has(.pill) > span.breakdown-unit__title` (three assertions, direct child) | title-maths markers |
| `tests/test_analytics_student_quiz.py:759` | `:scope > span.breakdown-unit__title` (direct child) | `test_t37_quiz_titles_link_iff_…` |
| `tests/test_analytics_student_quiz.py:325` | `div.breakdown-unit` → `.breakdown-unit__title` → `.pill` | `test_t36_header_pill_matches_…` |
| `tests/test_title_math_css.py`, `tests/test_title_math_assets.py` | the same class names | title-maths CSS/assets |

`app.css:2092` also names `.breakdown-unit__title` in a contrast comment. **Introducing a wrapper
element around the title would break the direct-child selectors with a failure that reads as "title
maths marker missing".** §4.2 therefore achieves its right-hand column without a wrapper. Renaming
these classes stays out of scope; restyling them is in scope, and any edit that shifts `app.css`
line numbers re-points the citations in the same commit (repo convention).

✅ **The right-hand column has a precedent three lines away:** `.rollup` (`app.css:608-612`) already
sits at the right of `.breakdown-node__head` via `margin-left:auto`, and `.rollup + .rollup`
(`:611`) shows how a *second* right-hand item avoids re-pushing. §4.2 follows both.

### 2.6 The per-question page and its answer builder

- `courses/answer_summary.py` is teacher-voice by construction (PR 5 spec §4). `Part` (`:32-48`) is
  a frozen dataclass of `kind, label_is_content, label, given, expected, ok`, with a `mark`
  **property** deriving the ✓/✗ glyph. `_choice` (`:87-104`) joins the picked option texts into one
  string and the correct ones into another, then calls `_single` — which is precisely why the page
  shows two bare runs and never the options.
- ⚠️ **`_choice` emits ONE placeholder PER missing pk today**:
  `texts += [_("(removed option)")] * len(picked - live)` (`:94`), pinned by
  `test_choice_removed_option_appended_after_live_texts`. §5.1 preserves that cardinality.
- ⚠️ **`_extendedresponse` (`:125-155`) is neither "single-part" nor "multi-part" in the sense §5.2
  uses:** it emits one `kind="answer"` part **plus N `kind="keyword"` parts** whose `label` is
  `"Required: x"` / `"Avoid: x"` and whose `given` and `expected` are both `None`. §5.2's predicate
  must exclude it.
- ⚠️ **Five existing tests pin `_choice`'s current output exactly** and are the specification of
  the behaviour §5.1 replaces: `tests/test_answer_summary.py` `test_choice_correct_wrong_unanswered`
  (`:35-39`), `test_choice_single_select` (`:42-46`),
  `test_choice_review_mode_has_no_expected_or_ok` (`:49-51`),
  `test_choice_removed_option_appended_after_live_texts` (`:54-60`),
  `test_choice_with_no_correct_option_expects_none_label` (`:63-66`). All compare against
  `_answer(given, expected, ok)` tuples that §5.1 deletes. §7.3 says what happens to each.
- ⚠️ **The page ALREADY computes per-option marks, and `summarise` does NOT receive them.**
  `_results_row` (`courses/views.py:1812-1830`) sets `row["choices"] = list(question.choices.all())`
  and `row["marks"] = question.choice_marks(choices, selected_ids(answer_from_json(...)),
  reveal_result, "quiz", True)`; but `_quiz_answer_rows` calls
  `summarise(question, response, row["reveal_result"])` (`views_analytics.py:332`), passing the
  `MarkResult` alone. §5.1 changes that signature rather than letting `_choice` issue a **second**
  `choice_marks` call with its own copies of the `"quiz"` / `locked=True` literals — two call sites
  agreeing by convention is the drift D3 says it removed.
- ⚠️ **"Two decode paths" was a false alarm** (an earlier draft of this spec said so):
  `answer_from_json` for a choice is literally `set(latest_answer or [])` (`courses/quiz.py:195-197`)
  and `selected_ids` passes a set through, so the raw read and the decoded read cannot disagree.
- ✅ **`reveal_result` and `marks` are set only inside `_results_row`'s AUTO branch**, so for a
  REVIEW/NOT_MARKED question `mark_result is None` and `choice_marks` returns `{}` — which is what
  makes §5.1's "no verdict without a key" fall out of the data rather than out of a hand-written
  rule.
- `question.choices.all()` is already prefetched for this page
  (`courses/views.py:354`), so D2 adds **no queries**.
  `tests/test_analytics_student_quiz.py:857` (`test_t38_query_count_does_not_grow_with_questions`)
  is the guard that must stay green.
- `Choice` (`courses/models.py:2447-2459`) has `text` (plain text plus KaTeX delimiters, never
  sanitised), `feedback`, `is_correct`, `order`, ordered by `("order", "pk")`.
  ⚠️ **`Choice.is_correct` must never be read by this design** — the key comes from
  `mark_result.reveal`, which is `None` for a non-auto question; reading the model field would make
  a key appear where the page must show none (§5.1).
- `ChoiceQuestionElement.multiple` (`:2279`) distinguishes single from multi-select. **The options
  table renders identically for both, deliberately** — the ✓/✗/＋ markers say what happened, and a
  radio-vs-checkbox affordance on a read-only teacher page would imply an interaction that does not
  exist.
- **The per-option vocabulary already exists:** `ChoiceQuestionElement.MARK_GLYPHS`
  (`courses/models.py:2309-2313`) maps `correct → ("✓", "your answer, correct")`,
  `wrong → ("✗", "your answer, incorrect")`, `missed → ("＋", "correct answer, not chosen")`.
  ⚠️ **Those labels are written in the PUPIL's voice**, so the teacher page reuses the three *kinds*
  and *glyphs* but needs its own labels (§6). `test_t35_teacher_voice_only` is the guard.
  The matching colours already exist: `courses/static/courses/css/courses.css:377,382-386`.
- ✅ **Maths inside option texts already loads KaTeX, today.** `_answers_have_math`
  (`courses/views_analytics.py:346-360`) delegates to `_question_has_math`
  (`courses/views.py:98-131`), whose `ChoiceQuestionElement` branch scans `c.text` **and**
  `c.feedback`. An earlier draft claimed the opposite and made it the design's headline risk; the
  mutant it proposed could not fail. §7.3's T22 mutates `views.py:104-107` instead.

### 2.7 The pupil's results page already carries outcome colour

⚠️ **This finding reverses a premise of the original D4.** `templates/courses/quiz_results.html:30`
wraps every question's verdict in `question__feedback-panel question__feedback-panel--{{
row.outcome }}`, and `courses/static/courses/css/courses.css:281-302` paints those panels:
`--correct` gets a `--success` left border on `--success-subtle`, `--incorrect` the `--danger`
pair, `--partial` the `--warning` pair, while `--not_answered` deliberately stays neutral. The
badge sits **inside** that panel (`:31-37`).

So a badge filled with `--success-subtle` would land green-on-green — and so would a *transparent*
badge, which simply lets the panel's tint through. §5.4 gives the badge an explicit surface of its
own for that reason.

Also on those pages: `.badge--review` and `.badge--muted` live in `courses.css:712-716`, not in
`app.css` beside `.badge--open` — and `.badge--muted` uses `--text-tertiary`, which this repo
records as failing AA at body size (a badge is smaller still).

### 2.8 The status pill is shared — its template AND its class

`templates/courses/manage/_quiz_pill.html` is included by **both**
`analytics_student_quiz.html:16` and `_breakdown_node.html:8`, and its `scored` branch (`:7`) is
the only place the score pill renders `scored {{s}}/{{m}} ({{percent}}%)`.

⚠️ **`tests/test_analytics_student_quiz.py::test_t36_header_pill_matches_the_breakdown_pill`
asserts the header pill's class list AND text equal the breakdown row's** (`:379-382`), over five
quizzes covering **four distinct kinds** (`reviewed` resolves to `scored`; `not_started` is
unreachable on this page, which 404s without a submission). §5.3 changes the header; §7.3 T27
replaces the guard with an invariant that holds for all four.

⚠️ **`.pill` is a GLOBAL class** (`app.css:1042`) emitted into both `.breakdown-unit` and the
per-question page's `.answers__status`, which is itself `display:flex` (`app.css:1020`). A bare
`.pill{margin-left:auto}` for §4.2's column would shove the per-question header's pill away from
the „Sprawdź" link and the answered count beside it — so §4.2's rule is scoped to the breakdown.

⚠️ **`_quiz_pill` carries `score`/`max_score`/`percent` ONLY for `kind == "scored"`**
(`rollups.py:503-512`). The page is also reachable with `submitted` (submitted but `max_score ==
0`), `awaiting` and `in_progress`, which carry none of those fields — §5.3 defines all four.

### 2.9 Marks are formatted two different ways on one page — separator AND precision

`marks_filter` (`courses/templatetags/courses_extras.py:577-589`) formats a Decimal to **at most 2
decimal places** with an ASCII dot and trims trailing zeros; the status pill instead uses
`floatformat` (`_quiz_pill.html:7`), which localises **and renders exactly one decimal place**. So
in Polish the same page prints a badge `0.5/1` beside a pill „0,5" — and a 0.67 mark
(`earned_marks` quantizes to 0.01) prints „0,7" in the pill against „0.67" in the badge. **Both
divergences are in scope for §5.5**; fixing only the separator leaves the page still disagreeing
with itself.

- The filter appears on **15 template lines / 25 occurrences** across three templates:
  `quiz_results.html` (7), `analytics_student_quiz.html` (5), `course_results.html` (3) — several
  lines apply it twice.
- **Five assertions across three tests pin its current output**:
  `test_marks_filter_trims_trailing_zeros` (`tests/test_quiz_scoring.py:33-36`, three assertions),
  `test_marks_filter_whole_tens_not_scientific` (`:39-41`), `test_marks_filter_none_is_dash`
  (`:44-45`). ⚠️ They call the filter directly, with **no active language**, so after §5.5 their
  output depends on whatever `LANGUAGE_CODE` happens to be — each updated assertion wraps in
  `translation.override(...)`.
- ⚠️ **`USE_THOUSAND_SEPARATOR` is not set anywhere in this repo**, so it holds Django's default
  `False`, and `django.utils.numberformat.format` groups only when
  `(use_l10n and settings.USE_THOUSAND_SEPARATOR) or force_grouping`. §5.5 is written knowing that
  passing `force_grouping=False` changes nothing today.
- ⚠️ **The CSV/XLSX export does NOT use this filter** — `courses/gradebook.py` builds cells as
  Decimals in Python (`:80-140`) — so localising the filter cannot put a decimal comma into an
  exported file, where it would break parsing. This is what makes D9's decimal comma safe.

### 2.10 Existing tests that assert a rendered pupil name

§3.2 changes how a pupil is named on four surfaces. What encodes today's spelling:

- `tests/demo/test_provision.py:48-49` carries the comment "The analytics templates render
  `display_name|default:username` and nothing else, so a pupil without one shows as
  'sp-12-p01'" — which §3.2 falsifies. Repaired line-count-neutral (repo convention).
- ✅ **`UserFactory` sets `display_name = Faker("name")` and NO `first_name`/`last_name`**
  (`tests/factories.py:58-65`). `list_display_name` therefore returns the display name unchanged
  for every factory-built pupil — including the `display_name="Ada L."` fixtures in
  `tests/test_analytics_views.py` and `tests/test_e2e_analytics.py`. **The §3.2 switch is invisible
  to the existing suite, and the inventory the plan runs is expected to come back EMPTY** — an
  empty result is the answer, not a failed search. T3 must therefore build its own pupil with
  first + last names.

### 2.11 The help screenshots these changes invalidate

`tests/capture_help_screenshots.py` holds **29 shot definitions** (`SHOTS`, `:129`), and
`core/static/core/img/help/` holds **58 committed PNGs** (29 × en/pl). Each tuple is
`(name, login_as, route-args, wait_selector, clip_selector)` (`:128`).

⚠️ **Both affected shots CLIP to `section.manage`** — an earlier draft of this spec named their
*wait* selectors instead, and so analysed the wrong region:

- `:174-180` — `analytics-matrix`, waits on `.analytics__matrix`, **clips `section.manage`**.
  Its crop carries the pupil-name row headers §3 respells.
- `:181-187` — `drill-down`, waits on `.breakdown__tree`, **clips `section.manage`**. Its crop
  carries the `h1` and the back link §4.3 renames, as well as the tree.

Re-checked against that wider crop: `review-queue` also clips `section.manage` and renders pupil
names (`review_queue.html:16,31`), but N2 leaves that template alone, so it is unaffected. No other
shot renders a pupil name or either changed page.

⚠️ **PR A's shot may come out byte-identical.** `courses/management/commands/seed_demo_course.py:
105-109` creates `demo_student`, `demo_s1..s3` with display names only ("Demo Student", "Ada Demo",
"Ben Demo", "Cleo Demo") and **no structured names**, so `list_display_name` returns the same
string and `sort_name` falls back to it — and their Polish order (Ada, Ben, Cleo, Demo Student)
already matches the username order. §8's checklist is written so that PR A passes whether or not
the pair changes.

⚠️ **The script rewrites all 58 PNGs on a local renderer and is NOT `@pytest.mark.e2e`** (demo spec
findings; the owner's memory records both). Each PR regenerates its own shot pair (en + pl) and
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

The two drill-down page headings (`analytics_student.html:8-9`,
`analytics_student_quiz.html:11`) also switch to it, but **in PR B**, where those headings are
rewritten anyway (§8) — PR A must not touch those lines.

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
keyword argument, defaulted so the four existing test call sites (§2.3) keep their behaviour. It
also stamps each **unit** dict with:

```python
d["additional"] = unit_marker(node) == MARKER_ADDITIONAL
```

— a **boolean**, not the raw marker, so no template can render a „Kwiz" chip from it (§2.3), and
the rule still lives in `unit_marker`. The visible word comes from
`marker_label(MARKER_ADDITIONAL)` → „Dodatkowa".

**The view (`analytics_student`, `views_analytics.py:257-289`) changes in four ways:**

1. `_drill_params(request)` moves **above** the `build_student_breakdown` call — today it runs
   after it (§2.4) — so the mode exists when the builder is called.
2. The builder receives `mode=mode`.
3. The view reverses its own path —
   `student_path = reverse("courses:manage_analytics_student", kwargs={"slug": course.slug,
   "student_pk": student.pk})` — which it does not compute today (§2.4).
4. The context gains `mode` and `other_view_url` (§4.3). `_breakdown_node.html` reads `mode` from
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
status signals per row would contradict each other. **A quiz row carries no kind chip either**
(§2.3, §4.1).

**The alignment reuses `.rollup`'s pattern** (`app.css:608-612`, §2.5) and adds no wrapper element,
because a wrapper breaks four direct-child selectors (§2.5):

- `.breakdown-unit .pill{margin-left:auto}` — ⚠️ **scoped to the breakdown**, never a bare
  `.pill{…}`: the same partial renders into the per-question page's flex header, where that rule
  would push the pill away from its „Sprawdź" link (§2.8).
- `.badge--done, .badge--todo{margin-left:auto}` — the declaration is **shared by an explicit
  selector list**, not "inherited": a sibling modifier inherits nothing, and an implementer who
  adds `.badge--todo{…}` alone would get a left-hugging circle that still looked spec-compliant.
- An **awaiting-review row has two right-hand items** — the pill, then the `Review` link
  (`_breakdown_node.html:9-11`). `margin-left:auto` sits on the **pill**, so the pair travels
  together in the order pill → link, exactly as `.rollup + .rollup` handles a second chip. T33
  A/Bs this row specifically.

**Both modes**
- A quiz title is a **visible link** when it has a submission: link colour plus a persistent
  underline, not `color:inherit` with a hover-only underline (§2.5). An unstarted quiz stays plain
  text.
- The `Review` link for a quiz awaiting review is unchanged in content.

**Lesson rows (Progress mode is the only mode that renders them)**
- Every unit title uses the **normal text colour**: `.breakdown-unit__title.is-done`
  (`app.css:1012`) loses its `color` declaration, so a completed lesson is no longer greyed. The
  rule change needs no mode scoping — `is-done` is only ever emitted on the lesson branch (§2.5),
  which Results mode does not render.
  ⚠️ **The `is-done` class keeps being emitted** (`_breakdown_node.html:16`): it is the DOM's only
  record of completion on a lesson row and it is what T33's A/B toggles against. Only the `color`
  declaration goes.
- A finished lesson is marked by today's `<span class="badge badge--done" aria-label="Completed">✓
  </span>`; an unfinished one by **`<span class="badge badge--todo" aria-label="Not completed">○
  </span>`** — a new modifier beside `badge--done` (`app.css:739`), with a muted border and no
  fill, sharing the `margin-left:auto` selector above. So "no mark" cannot be confused with "not
  rendered", and colour is not the signal.
- A lesson with `item.additional` true carries a quiet „Dodatkowa" tag (§4.1).

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
| `analytics_student.html:8-9` `h1` | „Szczegóły ucznia — X" | „Wyniki — X" or „Postęp — X" (the view) |
| `analytics_student_quiz.html:12` back link | „← Szczegóły ucznia" | „← Wyniki ucznia" |
| `docs/help/teacher/drill-down.{md,pl.md}` | "Per-student breakdown" / „Wyniki pojedynczego ucznia" | follows the table above |

⚠️ Those three template lines are the **only** consumers of the `Breakdown` msgid, so it goes
obsolete in both catalogs (§6).

- The `h1` names the **view**, reusing the matrix's own msgids (`Results` / `Progress`,
  `locale/pl:2628,2633`), with the pupil's `list_display_name`.
- Beside it, a link to the **other** view of the same pupil:
  `f"{student_path}?{_expand_qs(scope, other_mode, expand_pks, subset_pks, values)}"`, built
  exactly as the matrix builds its own pair (§2.4) and passed to the template as `other_view_url`.
  It preserves scope, expanded columns, subset and values.
- „← Analityka" is unchanged, and the per-question page's back link already carries the mode.

---

## 5. The per-question page

### 5.1 A choice question shows every option

**The builder's interface changes, so there is exactly one `choice_marks` call.**
`summarise(question, response, mark_result, *, option_marks=None)` gains a keyword argument, and
`_quiz_answer_rows` passes the dict `_results_row` already computed:
`summarise(question, response, row["reveal_result"], option_marks=row["marks"])`
(`views_analytics.py:332`). ⚠️ **`_choice` never calls `choice_marks` itself**: for a
`ChoiceQuestionElement` a missing `option_marks` is a programming error and raises, rather than
silently re-deriving the verdicts with a second copy of the `"quiz"` / `locked=True` literals
(§2.6). The five rewritten builder tests pass the dict through one shared helper, so the test suite
has one call site too.

`_choice` then returns **one part of a new kind**:

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
    mark: str | None       # "correct" | "wrong" | "missed" | None
```

- `text` — `choice.text`, in `Choice.Meta.ordering` order.
- `picked` — `choice.pk in selected_ids(answer_from_json(question, response.latest_answer))`, the
  decode `_results_row` already performs; for an unanswered response the set is empty.
- `correct` — `choice.pk in set(mark_result.reveal or ())` when the question is auto-marked,
  **`None` otherwise**. ⚠️ **Never `Choice.is_correct`** (§2.6).
- `mark` — `option_marks.get(choice.pk, {}).get("kind")`: **whatever `choice_marks` said**, and
  `None` where it said nothing. Because `choice_marks` returns `{}` for a non-auto question (§2.6),
  "no verdict without a key" is a property of the data, not a rule this spec has to restate.

**The kinds, for reference** (`models.py:2341-2349`): picked and in the key → `correct`; picked and
not → `wrong`; not picked and in the key → `missed`; otherwise absent → `None`.

**Rules**
- **Picked options that no longer exist** render after the live options as
  `Option(text=„(usunięta opcja)", picked=True, correct=None, mark=None)` — ⚠️ **one row per
  missing pk**, matching today's cardinality (§2.6); three deleted picks render three rows. They
  assert no verdict: `choice_marks` has no entry for them, and a deleted option's correctness is
  unknowable, so rendering them `wrong` would accuse a pupil on evidence that no longer exists.
- **An AUTO question whose key is empty** (today's „(none)" case) renders every option unmarked,
  plus a caption under the table reusing the „(none)" msgid: „poprawna odpowiedź: (brak)". Without
  the caption that question renders identically to a non-auto one, which is the distinction the
  design exists to preserve.
- **Not answered** — every option is listed, none picked, the key still marked. The row badge
  („Bez odpowiedzi") carries the not-answered state; the options block renders no „Not answered"
  fallback text, because the block is a list of options, not an answer run.
- **Not auto-marked** — options listed with picks only; the „Poprawna odpowiedź" column is omitted
  entirely (not rendered empty).
- **In progress** — the key is shown, exactly as PR 5 decided for the rest of the page (that
  spec's D5); `locked=True` comes from `_results_row`, unchanged.
- ⚠️ **A choice question loses its part-level ✓/✗ glyph.** `Part(kind="options", ok=None)` makes
  `Part.mark` `None`, so `analytics_student_quiz.html:69-70` renders no row-level glyph for this
  type — the per-option markers replace it. Stated because it is a visible behaviour change.

**Markup.** A `<table class="answers__options">` inside the part loop, with a new
`{% if part.kind == "options" %}` branch in `analytics_student_quiz.html:61-75` — placed **before**
the existing `kind == "answer"` branch (`:64`), which stays untouched for every other type.

- Three columns: „Wybór ucznia", „Poprawna odpowiedź", then the option text
  (`lang="{{ course.language }}"`, since options are course content).
- **The `<th>` text is visible at ≥640px and `.sr-only` below it** (`.sr-only` is a real global,
  `reset.css:25`). The two marker columns are therefore as wide as their header words on desktop —
  **not the ~2rem an earlier draft claimed** — and collapse to glyph width on a phone, where each
  marker cell's own `sr-only` label (§6) still carries the meaning.
- `width:100%` on the table with `table-layout:auto`; the two marker columns take
  `width:1%; white-space:nowrap` so the text column absorbs the rest. Without the explicit width
  the table shrink-wraps inside its flex parent (`.answers__part`, `app.css:1028`) and a long
  option can push past the card.
- Each marker cell pairs an `aria-hidden` glyph with its own teacher-voice `sr-only` label (§6).

### 5.2 Every other type keeps its parts, and gains labels

- **Single-part types** render „Odpowiedź ucznia: …" and, only where the part is not right,
  „Poprawna odpowiedź: …" (the latter msgid exists, `locale/pl:5459`).
- **ONE predicate decides both the grid and the header row**, computed in `_quiz_answer_rows`
  because the template has no question-type information:

  ```python
  row["columned"] = (
      len(parts) > 1
      and all(p.kind == ANSWER for p in parts)
      and any(p.expected for p in parts)
  )
  ```

  - `len(parts) > 1` alone is wrong — extended response emits one `answer` part plus N `keyword`
    parts (§2.6) — and a choice question's single `options` part fails the same test.
  - The `any(p.expected …)` term is what keeps an **all-correct** multi-part question out of the
    grid: `_answer_part` sets `expected=None if ok is True else expected`
    (`answer_summary.py:73-75`), so such a question has nothing to put in a third column and keeps
    today's label-and-answer shape. A partially-correct question shows the column with blanks
    against its correct parts, which is the honest rendering.
- **When `columned` is true**, `.answers__parts` gains `answers__parts--columned` and the layout
  becomes a real grid. ⚠️ **The mechanism must be stated, because the parts are `<div>`s**
  (`analytics_student_quiz.html:62`) and a grid on the parent would otherwise put each whole part
  in one cell:

  ```css
  .answers__parts--columned{display:grid;grid-template-columns:auto 1fr 1fr;
    column-gap:.6rem;row-gap:.35rem;align-items:baseline}
  .answers__parts--columned .answers__part{display:contents}
  ```

  `display:contents` means `.answers__part`'s own `padding`, `gap` and `overflow-wrap`
  (`app.css:1028-1031`) no longer apply to these questions: the row rhythm comes from the grid's
  `row-gap`, and `overflow-wrap:anywhere` moves onto the grid children (`.answers__label`,
  `.answers__given`, `.answers__expected`).
- **The 390px fallback is an explicit rule, not the old one.** `.answers__part`'s existing
  `@media (max-width:640px){flex-direction:column}` (`app.css:1036-1039`) is inert under
  `display:contents`, so the media query is extended:

  ```css
  @media (max-width:640px){
    .answers__parts--columned{display:block}
    .answers__parts--columned .answers__part{display:flex;flex-direction:column}
    .answers__parts--columned .answers__header-row{display:none}
  }
  ```

  The per-part „Poprawna odpowiedź:" prefix stays in the markup always and is hidden by CSS above
  640px (`.answers__parts--columned .answers__expected-label{display:none}`), so it "returns" on a
  phone without the template needing to know the viewport.
- ⚠️ **Extended response with keywords is neither shape.** Its answer part takes the single-part
  label; its keyword parts keep today's label-plus-glyph shape, get **no** header row and **no**
  columns — guaranteed by the `all(p.kind == ANSWER …)` term.
- `Part.label_is_content` still decides `lang` tagging (PR 5 spec §5.1) — the header row and the
  option table's `<th>`s are interface text and carry no `lang`.

### 5.3 The header

- **Two lines, not one dash-joined title:** the pupil's `list_display_name` on a small line above,
  the quiz title as the `h1` below. Today's `"{{ unit.title }} — {{ student… }}"`
  (`analytics_student_quiz.html:11`) produced „Zbiory - quiz — Mateusz Adamczyk", two dashes of
  different meaning in one line.
- The back button sits beside the heading and does not wrap beneath a long title (the PR 5
  implementation log records the wrap).
- **The header renders, by pill kind:**

  | pill kind | prominent figure | pill |
  |---|---|---|
  | `scored` | „1 / 5 pkt" + „20%" | **not rendered** |
  | `submitted` (ungraded, `max_score == 0`) | none | „przesłano" |
  | `awaiting` | none | „oczekuje na ocenę" + the „Sprawdź" link |
  | `in_progress` | none | „w toku" + „Odpowiedzi: 3 z 6" (existing plural msgid, `locale/pl:6229`) |

- **The score element uses the `marks` filter** — `{{ p.score|marks }} / {{ p.max_score|marks }}` —
  the same filter as the badges, so §5.5's rule reaches the page's most prominent figure too.
- ⚠️ **The shared pill partial is NOT modified.** For a `scored` quiz the header renders the score
  stat *instead of* the pill; for the other three kinds it includes `_quiz_pill.html` exactly as
  today. An earlier draft added a `show_score` flag that made the partial print „przesłano" for a
  scored quiz — the translation of a different msgid — and would have changed the breakdown's rows
  as well (`_breakdown_node.html:8`).
- No dash, no „0 / 0" placeholder: a kind with no score renders no score element at all.

### 5.4 Outcome colour, reconciled across both pages

⚠️ Per §2.7, the pupil's page already tints the whole question panel by outcome, so the badge needs
a surface of its own — a transparent badge simply shows the panel's tint through and stays
green-on-green. The badge is therefore: **`background: var(--surface-raised)`, a 1px border in the
outcome colour, and text in the outcome colour.**

| outcome | badge | class | applies to |
|---|---|---|---|
| `correct` | `--success` border + text on `--surface-raised` | `.badge--correct` | both pages |
| `partial` | `--warning` border + text | `.badge--partial` | both pages |
| `incorrect` | `--danger` border + text | `.badge--incorrect` | both pages |
| `not_answered` | muted — moved from `--text-tertiary` to `--text-secondary` (§2.7) | `.badge--muted` (existing) | both pages |
| `recorded`, `reviewed` | unchanged (neutral base) | — | both pages |
| `review` | unchanged | `.badge--review` (existing) | both pages |

The modifiers are defined in **`courses/static/courses/css/courses.css`, beside `.badge--review`
and `.badge--muted` (`:712-716`)** — both consuming pages link that sheet.

Applied in `templates/courses/manage/analytics_student_quiz.html:46-52` and
`templates/courses/quiz_results.html:31-37`, which stay deliberate copies of one another (PR 5
spec §5.1); the drift note in both templates is updated to say the modifier is part of the copy.

**On the teacher page only, the question card's left edge takes the outcome colour**
(`.answers__item.is-correct` / `.is-partial` / `.is-incorrect` — classes the template already emits
at `:28` and which today have no rules at all). This is the teacher-page equivalent of the pupil
page's panel tint, so the two pages carry the same information in the same visual language.

**Colour is never the only signal.** The badge's word carries the outcome on every type; non-choice
types keep their per-part ✓/✗; choice questions carry the per-option ✓/✗/＋ markers instead (§5.1).

⚠️ **Dark mode is not free here.** `.pill--scored` hardcodes `color:#fff` on `--primary`, and
`.pill--awaiting` hardcodes `#f5b942`/`#3a2a00` (`app.css:1044-1049`) — neither follows the theme.
Both are re-expressed in tokens as part of this section and judged in the dark screenshots.

### 5.5 Marks read the same everywhere — separator AND precision

Two changes, because §2.9 found two divergences:

1. **`marks_filter` localises its decimal separator.** It keeps its 2dp-and-trim rule and its
   `None → "—"` branch, passing the trimmed value through
   `django.utils.formats.number_format(value, decimal_pos=None, force_grouping=False)`.
   - ⚠️ **`force_grouping=False` is documented defensiveness, not a live fix.**
     `USE_THOUSAND_SEPARATOR` is unset in this repo (§2.9), so grouping is off today either way. It
     is passed so switching that setting on later cannot put „1 000" in a badge — and T29 tests it
     **under an override**, because without one the mutant cannot fail.
   - The quantize-then-trim step runs first and `decimal_pos` is left `None`, so the trimming rule
     stays the filter's own.
2. **The pill stops using `floatformat`.** `_quiz_pill.html:7` renders `{{ p.score|marks }}` /
   `{{ p.max_score|marks }}`, so a 0.67 mark reads „0,67" in the pill, the badge and the header
   score alike. Without this the page still contradicts itself at 2dp while agreeing on the comma.
   ⚠️ This changes the **breakdown's** pill text too (`_breakdown_node.html:8`) — intended, and
   T27's parity half asserts the new text.

- The five assertions across three tests (§2.9) move to per-locale expectations, each inside an
  explicit `translation.override(...)`, with a ≥ 1000 value added.
- The exported file is unaffected (§2.9) and T30 says so explicitly.

---

## 6. Interface text

New msgids, with the Polish for the owner to approve on the PR. Existing msgids are reused wherever
one exists.

| English (new) | Polski (proposed) | where |
|---|---|---|
| `Pupil's answer:` | „Odpowiedź ucznia:" | §5.2 single-part label |
| `Pupil's answer` | „Odpowiedź ucznia" | §5.2 multi-part header row |
| `Pupil's choice` | „Wybór ucznia" | §5.1 option column header |
| `chosen, correct` | „wybrana, poprawna" | §5.1 screen-reader label |
| `chosen, incorrect` | „wybrana, niepoprawna" | §5.1 screen-reader label |
| `correct, not chosen` | „poprawna, niewybrana" | §5.1 screen-reader label |
| `correct answer: %(key)s` | „poprawna odpowiedź: %(key)s" | §5.1 empty-key caption (`%(key)s` is the reused „(brak)") |
| `%(s)s / %(m)s marks` | „%(s)s / %(m)s pkt" | §5.3 score stat |
| `Not completed` | „Nieukończone" | §4.2 empty-circle marker |
| `Pupil results` | „Wyniki ucznia" | §4.3 page name, back link |

⚠️ **The score's percentage is NOT in that msgid.** „1 / 5 pkt" and „20%" are two elements —
`<span class="answers__score">` and `<span class="answers__percent">` — with the separator supplied
by CSS, not by a literal „·" glued onto a translated string.

⚠️ **`Breakdown` / „Szczegóły ucznia" goes OBSOLETE** in both catalogs: §4.3 replaces all three of
its consumers. `makemessages` will comment the entry out, and that obsolete block is an expected
part of PR B's diff — distinct from a fuzzy entry, which is not.

⚠️ **Three near-identical Polish words land in one question card** and want the owner's judgement
together, not row by row: „Poprawnie" (the verdict badge), „Poprawna odpowiedź:" (the key label,
existing) and „Poprawna odpowiedź" (the option column header, proposed). If that reads as
repetitive, „Klucz" is the alternative for the column header. Flag all three in the PR body as one
question.

Reused, not re-created: `Correct answer:` (`locale/pl:5459`), `(removed option)` (`:423`),
`(none)` (`:427`), `Not answered` (`:6243`), `Correct` / `Incorrect` / `Partial`, `Review`
(`:5636`), `Additional` / „Dodatkowa" (`rollups.UNIT_MARKER_LABELS`), `Progress` / `Results`
(`:2633,2628`), `Completed`, `%(k)s of %(n)s question answered` (`:6229`), and every pill word
(`:5395,5386,5912,5916,5920`).

⚠️ `makemessages` fuzzy-prefills new msgids from similar existing ones — it did exactly that twice
in #323. Every new entry above is checked by hand and the catalogs must end at 0 fuzzy.

---

## 7. Tests

Every rule below is falsified against a named mutant, run and observed red, then reverted by hand
(repo convention; the owner's memory records why a scripted revert is dangerous).

### 7.1 Order and names (§3)

- **T1** A class whose username order disagrees with surname order appears in the matrix in
  surname-then-first-name order. Fixture: `Świątek` (after `S…`, before `T…`), `Nowak` and
  `Nowakowska` (prefix pair), two pupils sharing a surname, one login with no first/last name.
  *Mutants:* restore `order_by("username")` → red; sort by the raw `sort_name` string without
  `polish_sort_key` → red on `Świątek`.
  ⚠️ **The `_RANK_SPACE` mutant belongs to `tests/test_collation.py::test_space_sorts_before_letters`,
  which already kills it** (§2.2) — T1 keeps the prefix pair as data but must not claim that
  falsification as its own.
- **T2** The same class exports in the same order, asserted on the parsed file, not the HTML.
  *Mutant:* order the export by username only → red. This is the pair T1 cannot catch alone.
- **T3** The matrix renders „Mateusz Adamczyk"; the checkbox label names the same string; a
  no-names login falls back to its display name; and a pupil with first + last + an unrelated
  display name renders the parenthetical form in full (§3.2).
  ⚠️ **T3 builds its own pupils with `first_name`/`last_name`** — `UserFactory` sets neither
  (§2.10), so a factory-built pupil cannot distinguish the two spellings.
  *Mutant:* revert to `display_name|default:username` → red for the structured-name pupil.
- **T4** Non-vacuity: the fixture's username order and surname order genuinely differ, asserted
  directly, so T1/T2 cannot pass by coincidence.
- **T5** The two drill-down headings still render `display_name|default:username` **after PR A**
  — the guard that keeps PR A off PR B's lines. ⚠️ **T5 is DELETED in PR B**, which rewrites both
  headings by design; its successors are T28 (per-question page) and T28b (pupil page). PR B's
  implementer must delete it, not weaken it.
- ⚠️ No assertion may rest on database ids — a pk-order coincidence is a known flake source in this
  repo (four occurrences).

### 7.2 The pupil page (§4)

- **T6** `?mode=results`: quiz titles present, **no lesson title present**, a chapter holding no
  quiz absent, an unstarted quiz present with its „nie rozpoczęto" pill.
  *Mutant:* skip the prune → red on the lesson assertion.
- **T7** `?mode=results`: a rendered chapter carries **no `.rollup` element** (D7).
  *Mutant:* keep the chip in both modes → red.
- **T8** `?mode=progress`: lessons present, chapter chips present — today's behaviour.
  *Mutant:* prune unconditionally → red.
- **T9** No `mode`, and `?mode=nonsense`, both render Progress. *Mutant:* default to results → red.
- **T10** Pruning keeps an ancestor chain: a quiz nested three deep still renders with its part and
  chapter above it. *Mutant:* prune containers before `attach` → red.
- **T11** The view switch link points at the same pupil with the opposite mode and preserves scope,
  expand, subset and values. *Mutant:* drop `subset_pks` from its querystring → red.
- **T12** A non-obligatory lesson carries the „Dodatkowa" tag; an obligatory one does not; **and a
  quiz row carries no kind chip at all** (§2.3).
  *Mutants:* tag every lesson → red; stamp the raw `unit_marker` and render it unguarded → red on
  the quiz row („Kwiz" appears).
- **T13** A quiz row carries a pill and **no** completion marker; a lesson row carries a marker and
  no pill; the unfinished marker is `.badge--todo` with its accessible name (§4.2).
  *Mutant:* render the marker on every unit → red.
- **T14** The quiz title's link is **visibly** a link — underline present without hover — via
  T33's computed-style A/B. `test_t37_quiz_titles_link_iff_the_pupil_has_a_submission` already
  covers the `<a>`-presence half and is **not** duplicated here.
- **T15** The four existing `build_student_breakdown` call sites still pass with the default
  argument — i.e. the default really is `progress`.
- **T16** `has_math` is computed from the pruned tree: a Results-mode page whose only maths title
  belongs to a lesson does not load KaTeX (§4.1). *Mutant:* scan before pruning → red.

### 7.3 The per-question page (§5)

- **T17** Builder, one case each: picked-and-correct, picked-and-wrong, missed, untouched,
  not answered, `multiple=True`. Each asserts the `Option` record's four fields.
  *Mutants:* invert `picked`; drop `missed` — each red on its own case.
- **T17b** **Two** picked-but-deleted options render **two** rows, last, each with `picked=True`,
  `correct=None` and `mark is None` (§5.1).
  *Mutants:* emit a single placeholder → red (the cardinality regression today's
  `test_choice_removed_option_appended_after_live_texts` catches); fall back to `wrong` for an
  unknown pk → red.
- **T17c** `summarise` raises for a choice question when `option_marks` is omitted (§5.1).
  *Mutant:* fall back to an internal `choice_marks` call → red. This is what keeps the call count
  at one.
- **T18** A **non-auto-marked** choice question yields `mark is None` and `correct is None` for
  every option, including picked ones, and renders no „Poprawna odpowiedź" column.
  *Mutant:* source `correct` from `Choice.is_correct` → red.
- **T19** For a **submitted, auto-marked** question over **live** options, the per-option kinds
  equal the `choice_marks` dict the page computed, and the pupil's results page renders the same
  kinds, with "absent from `choice_marks` ≡ `Option.mark is None`" asserted explicitly.
  ⚠️ **Scoped deliberately:** an in-progress submission, a non-auto question and a deleted option
  each break equality *by design* (§5.1).
  *Mutant:* pass a doctored `option_marks` and assert the page follows it (proving the page reads
  the dict rather than re-deriving) → red if `_choice` re-derives.
- **T20** The rendered page lists **every** option, in author order, not only the picked ones.
  *Mutant:* render only picked options → red.
- **T21** Teacher voice: `test_t35_teacher_voice_only` is extended over the new labels.
  *Mutant:* reuse `MARK_GLYPHS`' pupil-voice labels → red.
- **T22** Maths in an option text loads KaTeX. ⚠️ **The mutant is in `_question_has_math`'s choice
  branch** (`courses/views.py:104-107`) — delete it → red (§2.6).
- **T23** `test_t38_query_count_does_not_grow_with_questions` still passes with options rendered.
  *Mutant:* re-query `question.choices.all()` outside the prefetch → red.
- **T24** Extended response with two keywords: `row["columned"]` is False, the answer part carries
  „Odpowiedź ucznia:", the keyword parts get no header row (§5.2).
  *Mutant:* set `columned = len(parts) > 1` → red.
- **T24b** An **all-correct** multi-part question has `columned` False — no grid, no header row;
  a partially-correct one has it True (§5.2).
  *Mutant:* drop the `any(p.expected …)` term → red on the all-correct case.
- **T25** Badge modifier per outcome on **both** templates, asserted on the rendered class.
  *Mutant:* remove the modifier from one template → red. The card-edge class is asserted on the
  teacher page only.
- **T26** Header, per pill kind (§5.3): `scored` renders the score element and **no pill**;
  the other three render the pill and **no** score element; `in_progress` renders the
  answered-count phrase. *Mutant:* render the score unconditionally → red on three of four kinds.
- **T27** `test_t36_header_pill_matches_the_breakdown_pill` is **replaced, not deleted**: for
  `submitted`, `awaiting` and `in_progress` the header pill's class list and text still equal the
  breakdown row's; for `scored` the header renders **no** pill while the breakdown row still shows
  its score, now formatted by `marks` (§5.5) — the `scored` branch asserts the header's score
  element text too. *Mutant:* let the header keep rendering a pill for `scored` → red.
- **T28** The per-question heading renders the pupil's name and the quiz title as separate
  elements and contains no „ — ". *Mutant:* restore the joined title → red.
- **T28b** The pupil page's `h1` renders „Wyniki — <name>" in Results and „Postęp — <name>" in
  Progress, and the back link on the per-question page reads „← Wyniki ucznia" (§4.3).
  *Mutant:* keep the „Breakdown" msgid → red. Together with T28 this replaces T5.
- **T29** In Polish a half mark renders „0,5" and a 0.67 mark „0,67" in the badge, the pill **and**
  the header score; in English „0.5"/„0.67" — each inside an explicit `translation.override`.
  Under `override_settings(USE_THOUSAND_SEPARATOR=True)`, 1000 renders ungrouped.
  *Mutants:* revert `marks_filter` to the ASCII form → red; leave `floatformat` in the pill → red
  on the 0.67 case; drop `force_grouping=False` → red under the override only.
- **T30** The exported gradebook still writes a dot decimal (§2.9). *Mutant:* localise the
  export's numbers → red.
- **T31** The options block renders as a table whose `<th>`s carry the column words, with
  per-marker `sr-only` labels (§5.1). *Mutant:* drop the `sr-only` labels → red.
- **T32** An AUTO question with an empty key renders every option unmarked **and** the „(brak)"
  caption. *Mutant:* drop the caption → red (the page would be identical to T18's rendering).
- **The five existing `_choice` tests** (§2.6) are rewritten against `Option` records, one for one:
  correct/wrong/unanswered → T17; single-select → T17's `multiple=False` case; review mode → T18;
  removed option → T17b; no-correct-option → T32. **None is deleted without a successor.**

### 7.4 Visual

- **T33** Any CSS rule this design relies on is confirmed by comparing the computed style **with
  and without** the rule (repo convention). Cases: the persistent underline (T14); the breakdown
  pill's `margin-left:auto` **and** the per-question header pill's position being unchanged (§2.8);
  `.badge--todo`'s presence **and** its right alignment (§4.2); the awaiting-review row's pill+link
  pair; the card edge; the columned grid at desktop and its block fallback at 390px (§5.2).
- **T33b** The badge is legible on the pupil page's tinted panel: its computed background differs
  from the panel's, measured for `correct`, `partial` and `incorrect` in both themes (§5.4). A
  rule-presence A/B cannot see this, which is why it is its own case.
- **T34** Screenshots, light and dark, desktop and 390px, on mat-pp data:
  - the Results and Progress pupil pages;
  - the per-question page for a submitted quiz with a wrong choice answer (the owner's
    „Zbiory - quiz" question 1 is the reference case), an in-progress quiz, and a quiz with a
    question awaiting review;
  - **`quiz_results.html`**, the pupil's own results page (§5.4's badge on an already-tinted panel);
  - **`course_results.html`**, the third page §5.5's rule reaches.
  Dark is judged on its own, not as "light but darker".

---

## 8. Delivery

Two PRs, in order.

**PR A — pupil order and names (§3).** The helper, the two views, the matrix template's two lines
and `gradebook.py`'s two name fields; T1–T5. It repairs the stale `sort_name` docstring and the
stale `test_provision.py:48-49` comment, both line-count-neutral, and runs the §2.10 inventory
(expected to be empty).

⚠️ **PR A must NOT touch `analytics_student.html:8-9` or `analytics_student_quiz.html:11`** — the
headings PR B rewrites (§4.3, §5.3). T5 pins that boundary.

**PR B — the two pages (§4, §5, §6).** The design pass (`frontend-design`) runs inside this PR,
after the markup exists and before the screenshots are judged. Ships new msgids, one obsolete
msgid (§6); no migration, no `FORMAT_VERSION` bump, no new dependency. **Deletes T5** and relies on
T28/T28b in its place.

**Help screenshots — a manual checklist item in each PR, NOT a pytest.** The capture script runs
outside the e2e marker on a local renderer (§2.11), so no test process can observe its result. Each
PR's checklist reads: run the capture, keep this PR's own shot pair
(`analytics-matrix.{en,pl}.png` for PR A, `drill-down.{en,pl}.png` for PR B), restore every other
file with `git checkout -- core/static/core/img/help/`, and confirm `git status` shows **no file
outside this PR's own pair**. ⚠️ **The pair itself may be unchanged** — PR A's matrix shot probably
is (§2.11) — so the checklist asserts the absence of collateral changes, not the presence of a diff.

**Docs.** `docs/help/teacher/drill-down.md` and `.pl.md` describe both pages and gain: the
Results/Progress distinction, the view switch, the „Dodatkowa" tag, and the option list; their page
name follows §4.3's table. `docs/help/teacher/analytics.md` and `.pl.md` gain one sentence on pupil
order.

**Rollout.** Nothing here is gated by `LIBLI_VENDOR_INSTANCE`: these are ordinary teacher screens
on every box, including schools' real-pupil instances. The demo kit is only the reason the defects
were noticed.

---

## 9. Risks

1. **The deliberate template copy (§5.4).** `quiz_results.html` and `analytics_student_quiz.html`
   must stay parallel; T25 asserts both, and both templates carry the note.
2. **The shared pill (§2.8).** Shared twice over: one template included by two pages, and one
   global `.pill` class. §4.2's rule is scoped to `.breakdown-unit`, §5.3 leaves the partial alone,
   and T27 plus T33 pin both halves.
3. **`marks` now reaches three templates and the pill (§5.5).** Including `course_results.html`,
   which nothing else in this design touches. Accepted deliberately: one rule for marks across the
   product beats two.
4. **Screenshot regeneration side effects (§2.11).** A careless run rewrites all 58 committed PNGs
   on the local renderer; §8's checklist is per PR and asserts no collateral diff.
5. **Structural test dependencies (§2.5).** Four selectors reach into the breakdown tree by direct
   child; a wrapper element added for §4.2's column breaks them with a misleading message.
6. **Replacing a builder that five tests specify (§2.6, §7.3).** `_choice`'s rewrite is the only
   place where existing, passing tests are deliberately rewritten; each has a named successor.
7. **`display:contents` (§5.2).** It removes the part div from the box tree, so padding, borders
   and the old mobile rule silently stop applying. The 390px case is its own screenshot and its own
   A/B for that reason.
