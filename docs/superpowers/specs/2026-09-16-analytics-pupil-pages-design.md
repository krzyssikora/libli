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
design borrows their key, it does not change them (see §3.1's follow-up note).

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
  **whitespace ranks BELOW letters** (`_RANK_SPACE = 0`, `:23`), which is what makes `"Nowak Anna"`
  sort before `"Nowakowska Beata"` through a `"Last First"` key. ⚠️ That property is **already
  pinned** by `tests/test_collation.py::test_space_sorts_before_letters` — §7.1 T1 must not claim
  it as its own falsification.
- `grouping/views.py:434` — the roster key in use today is
  `(polish_sort_key(student.sort_name), student.username)`.

So D5 is `sorted(pool, key=lambda u: (polish_sort_key(u.sort_name), u.username))` — the same
expression the Groups pages already use, not a second ordering.

⚠️ **A no-names login sorts by its display name — but which kit login is even IN the roster depends
on the viewer.** `reviewable_students` (`grouping/scoping.py:76-93`) returns
`Enrollment`-derived users for a PA or the course owner, and **`GroupMembership`-derived users for
a group teacher**. `demo/services.py` attaches the kit Teacher with `group.teachers.add(teacher)`
(`:301`) and enrols only the Student and the pupils
(`add_students_to_group(group, [student, *pupil_users], …)`, `:337`).

- **Viewed as the kit Teacher — the demo path this design exists for — the Teacher's own row is not
  in the matrix at all.** Only the Student („Uczeń demo — <label> (#pk)", `:305`) appears among the
  pupils, sorting under **"U"**.
- Viewed as the owner or a PA, the roster is enrolment-derived, so the same holds: the Teacher
  („Nauczyciel demo — …", `:289`) has no `Enrollment` and does not appear.

The kit's generated pupils DO carry `first_name`/`last_name` plus a matching `display_name`
(`:320`), so they sort by surname properly. The Student's placement under "U" is accepted, not a
defect to fix here. ⚠️ An earlier draft of this spec claimed both kit logins sit among the
surnames; the Teacher never does.

### 2.3 What the pupil page's tree actually holds

`courses/rollups.py:215-263` (`build_outline`) yields node dicts with `node`, `children`,
`required_total`, `required_done`, `additional_done`, `is_unit`, `completed`, `depth`.
`build_student_breakdown` (`:522-542`) folds in a `pill` on every quiz unit, via
`_quiz_pill` (`:498-519`), and returns `{"student": …, "tree": …}`.

- **`required` counts obligatory LESSON units only** (`:221-222`, and `is_obligatory_lesson` at
  `:141-148` is the single source). Quizzes are excluded from both `required_total` and
  `additional_done`. Hence D7: in a quizzes-only view the chip would describe rows that are no
  longer on the page.
- ⚠️ **"Optional lesson" is already a named concept with ONE rule and ONE word.**
  `rollups.unit_marker` (`:169-195`) is documented as "the ONE student-facing kind rule" and
  returns `MARKER_ADDITIONAL` for exactly a non-obligatory LESSON unit; `UNIT_MARKER_LABELS`
  (`:163-166`) maps it to `Additional` / „Dodatkowa". The flag legend's „Opcjonalne"
  (`_flag_legend.html:56`) is the *node-flag* vocabulary on the "Requirement" axis — the author's
  surface, not the reader's. **D8 reuses `unit_marker` / `marker_label`.**
  ⚠️ **But `unit_marker` also returns `MARKER_QUIZ` for every quiz unit** (`:190-191`), labelled
  `Quiz` / „Kwiz", and the existing chip partial (`templates/courses/_unit_kind_chip.html`) renders
  **any** truthy marker — so an unguarded reuse puts a „Kwiz" chip on every quiz row. §4.1 stamps a
  boolean, not the raw marker.
  ⚠️ Its docstring forbids rewriting the rule as `not is_obligatory_lesson(node)`.
- **`completed` is set for EVERY unit, quizzes included**, but `_breakdown_node.html:4-13` renders
  a pill and no `badge--done` on a quiz row. A submitted quiz can carry `completed=False`, so the
  two signals are not interchangeable — §4.2 settles which row gets which.
- **Callers of `build_student_breakdown`:** one production caller
  (`courses/views_analytics.py:268`) plus **four** test call sites
  (`tests/test_analytics_rollups.py:537,574,775` and `tests/test_publish_analytics.py:263`), two of
  which assert tree shape. §4.1 states which function owns the prune, because that is what decides
  whether those four see any change.

### 2.4 The mode already reaches both drill-down pages — but too late, and not into the context

`_drill_params` (`courses/views_analytics.py:214-222`) parses `scope, mode, expand_pks,
subset_pks, values` from the querystring, and both the pupil page (`:271`) and the per-question
page (`:384`) already call it — to rebuild the *back* link only.

- ⚠️ **`build_student_breakdown` is called at `:268`, before `_drill_params` runs at `:271`.**
- ⚠️ **The pupil view's context is `course, student, breakdown, back_url, drill_qs, has_math`
  (`:281-288`) — no `mode`.** A missing context key is silently falsy in a Django template, so
  every mode-conditional rule would no-op with no error.
- ⚠️ **That view computes `matrix_path` only** (`:272`); it has no `student_path`.

`_expand_qs(scope, mode, …)` (`:196-211`) is the single builder for such a querystring, and the
matrix's own view switch is two calls to it with `"progress"` / `"results"` hardcoded
(`:137-138`). D1 and D6 reuse that pattern against the pupil page's own path.

⚠️ **Unknown values already normalise to `progress`** (`:218`). The pupil page must not invent a
second rule.

### 2.5 Why finished lessons look dimmer than unfinished ones

`core/static/core/css/app.css:1012` is the only emphasis rule on the tree:
`.breakdown-unit__title.is-done{color:var(--text-secondary)}`. A completed unit is therefore
*greyed*, and an incomplete one keeps the primary text colour. Chapter heads are `font-weight:600`
(`:1009-1010`), which is what makes a bright incomplete unit title read as another heading.

`.breakdown-unit__link` (`:1014-1015`) sets `color:inherit;text-decoration:none`, with an underline
only on hover/focus — so **the one clickable thing on the page is invisible until hovered**. The
owner hit exactly this: he asked what to click.

⚠️ **`is-done` is only ever emitted on the lesson branch** (`_breakdown_node.html:16`), and CSS has
no notion of the page's mode, so changing that rule is mode-independent.

⚠️ **FOUR test dependencies on this tree's markup, not merely on its class names:**

| file:line | selector | feeds |
|---|---|---|
| `tests/test_title_math_markers.py:452-464` | `div.breakdown-unit:has(.pill) > span.breakdown-unit__title` (three assertions, direct child) | title-maths markers |
| `tests/test_analytics_student_quiz.py:759` | `:scope > span.breakdown-unit__title` (direct child) | `test_t37_quiz_titles_link_iff_…` |
| `tests/test_analytics_student_quiz.py:325` | `div.breakdown-unit` → `.breakdown-unit__title` → `.pill` | `test_t36_header_pill_matches_…` |
| `tests/test_title_math_css.py`, `tests/test_title_math_assets.py` | the same class names | title-maths CSS/assets |

**A wrapper element around the title would break the direct-child selectors** with a failure that
reads as "title maths marker missing". §4.2 adds none.

✅ **The right-hand column has a precedent three lines away:** `.rollup` (`app.css:608-612`) sits at
the right of `.breakdown-node__head` via `margin-left:auto`, and `.rollup + .rollup` (`:611`) shows
how a second right-hand item avoids re-pushing.

⚠️ **`.badge--done` ALREADY carries `margin-left:auto`** (`app.css:739`), and
`courses.css:897`'s `.unit-tree__check{margin-left:0}` exists **specifically to cancel it** on
rows where the tick leads rather than trails (`courses.css:870-873` says so). Any new rule must
therefore join the `app.css:739` selector list — a duplicate landing in `courses.css` after `:897`
would silently un-cancel that reset on the unit tree and the pupil outline.

### 2.6 The per-question page and its answer builder

- `courses/answer_summary.py` is teacher-voice by construction (PR 5 spec §4). `Part` (`:32-48`) is
  a frozen dataclass of `kind, label_is_content, label, given, expected, ok`, with a `mark`
  **property**. `_choice` (`:87-104`) joins picked option texts into one string and correct ones
  into another — which is why the page shows two bare runs and never the options.
- ⚠️ **`summarise` dispatches through a table of ten adapters that share one signature**
  (`:336-352`): `_ADAPTERS[type(question)](question, response, mark_result)`. §5.1 says how a new
  argument reaches `_choice` without touching the other nine.
- ⚠️ **`_choice` emits ONE placeholder PER missing pk today**:
  `texts += [_("(removed option)")] * len(picked - live)` (`:94`).
- ⚠️ **`_extendedresponse` (`:125-155`) emits one `kind="answer"` part PLUS N `kind="keyword"`
  parts** whose `label` is `"Required: x"` / `"Avoid: x"` and whose `given`/`expected` are `None`.
- ⚠️ **Five existing tests pin `_choice`'s output exactly** (`tests/test_answer_summary.py:35-66`)
  and are the specification of what §5.1 replaces. §7.3 gives each a successor.
- ⚠️ **They all reach `summarise` through ONE shared fixture, and so do the other nine types.**
  `tests/answer_summary_fixtures.py:117-128` (`summarise_stored`, docstring: "summarise() fed
  exactly as views._results_row feeds it") builds the `MarkResult` itself and calls
  `summarise(question, response, mark_result)` positionally. §5.1's new required argument therefore
  breaks **every** choice call through it, and teaching it to pass `option_marks` means the helper
  mirrors `_results_row`'s `choice_marks` call. That is accepted: **D3's rule is one call site in
  PRODUCTION code**, and the fixture's whole purpose is to imitate the view. §5.1 says what the
  helper does; §7.3 treats it as a named deliverable, not an incidental edit.
- ⚠️ **`response` may be `None`.** `_quiz_answer_rows` does `response = responses.get(el.pk)`
  (`views_analytics.py:329`) — a question the pupil never touched has no row at all. Today's
  `_choice` reads `latest_answer` only inside `if _answered(response)` (`:90-91`); §5.1 keeps that
  guard, because the unguarded expression raises `AttributeError`.
- ⚠️ **What `_results_row` actually hands over** (`courses/views.py:1770-1830`):
  - `row["marks"]` and `row["choices"]` are initialised to **`None`** (`:1773-1774`) and are
    overwritten **only inside the AUTO branch**. For a REVIEW/NOT_MARKED choice question they stay
    `None` — **not `{}`**. An earlier draft of this spec said `{}`, and `None.get(...)` raises.
  - Inside that branch: `row["marks"] = question.choice_marks(choices,
    selected_ids(answer_from_json(...)), reveal_result, "quiz", True)`.
  - `summarise` is called as `summarise(question, response, row["reveal_result"])`
    (`views_analytics.py:332`) — it does **not** receive the marks today.
- ⚠️ **`choice_marks` marks a picked option `wrong` when the key is EMPTY.** `models.py:2346-2347`
  is `elif picked: marks[c.pk] = "correct" if c.pk in correct else "wrong"`, and an empty
  `reveal` makes every pick `wrong`. So "an empty-key question renders every option unmarked" is
  false for any pupil who answered (§5.1 states what actually happens).
- ✅ **`reveal_result` is `None` outside the AUTO branch**, so `choice_marks` is never called for a
  non-auto question — which is what makes "no verdict without a key" a property of the data.
- `question.choices.all()` is already prefetched (`courses/views.py:354`), so D2 adds **no
  queries**; `test_t38_query_count_does_not_grow_with_questions` is the guard.
- `Choice` (`courses/models.py:2447-2459`): `text` (plain text plus KaTeX delimiters, never
  sanitised), `feedback`, `is_correct`, `order`, ordered by `("order", "pk")`.
  ⚠️ **`Choice.is_correct` must never be read by this design** — the key comes from
  `mark_result.reveal`, which is `None` for a non-auto question.
- `ChoiceQuestionElement.multiple` (`:2279`) distinguishes single from multi-select. **The options
  table renders identically for both, deliberately.**
- **The per-option vocabulary already exists:** `MARK_GLYPHS` (`courses/models.py:2309-2313`) maps
  `correct → ("✓", "your answer, correct")`, `wrong → ("✗", …)`, `missed → ("＋", …)`.
  ⚠️ **Those labels are pupil-voice**, so the teacher page reuses the *kinds* and needs its own
  labels (§6). `test_t35_teacher_voice_only` is the guard. Colours exist at
  `courses/static/courses/css/courses.css:377,382-386`.
- ✅ **Maths inside option texts already loads KaTeX.** `_answers_have_math`
  (`views_analytics.py:346-360`) delegates to `_question_has_math` (`courses/views.py:98-131`),
  whose `ChoiceQuestionElement` branch scans `c.text` and `c.feedback`. §7.3's T22 mutates
  `views.py:104-107`.

### 2.7 The pupil's results page already carries outcome colour

`templates/courses/quiz_results.html:30` wraps every verdict in `question__feedback-panel
question__feedback-panel--{{ row.outcome }}`, and `courses.css:281-302` paints those panels:
`--correct` gets a `--success` left border on `--success-subtle`, `--incorrect` the `--danger`
pair, `--partial` the `--warning` pair; `--not_answered` stays neutral. The badge sits **inside**
that panel (`:31-37`).

So a badge filled with `--success-subtle` would land green-on-green — and so would a *transparent*
badge, which lets the panel's tint through. §5.4 gives the badge its own surface for that reason.

⚠️ **`.badge--muted` has FOUR consumers, not two:** `quiz_results.html:34`,
`analytics_student_quiz.html:49`, `review_submission.html:76,78` and `course_results.html:24,34`.
§5.4's recolour reaches all four (§2.11 and §7.4 follow).

### 2.8 The status pill is shared — its template AND its class

`templates/courses/manage/_quiz_pill.html` is included by **both**
`analytics_student_quiz.html:16` and `_breakdown_node.html:8`, and its `scored` branch (`:7`, a
`{% blocktrans %}` carrying the msgid `scored %(s)s/%(m)s`) is the only place the score pill renders
`scored {{s}}/{{m}} ({{percent}}%)`.

⚠️ **`test_t36_header_pill_matches_the_breakdown_pill` asserts the header pill's class list AND
text equal the breakdown row's** (`:379-382`), over five quizzes covering **four distinct kinds**
(`reviewed` resolves to `scored`; `not_started` is unreachable here). §7.3 T27 replaces it.

⚠️ **`_quiz_pill.html:1 loads only `{% load i18n %}`**, and an included template does not inherit
the includer's libraries — so §5.5's filter change must add `courses_extras` to that line or the
page raises `TemplateSyntaxError`.

⚠️ **`.pill` is a GLOBAL class** (`app.css:1042`) rendered into both `.breakdown-unit` and the
per-question page's `.answers__status`, which is itself `display:flex` (`app.css:1020`). A bare
`.pill{margin-left:auto}` would shove the header's pill away from its „Sprawdź" link — §4.2's rule
is scoped to the breakdown.

⚠️ **`_quiz_pill` carries `score`/`max_score`/`percent` ONLY for `kind == "scored"`**
(`rollups.py:503-512`); `percent` comes from `_pct` (`:709-711`) and is an **int**.

### 2.9 Marks are formatted two different ways on one page — separator AND precision

`marks_filter` (`courses/templatetags/courses_extras.py:577-589`) formats a Decimal to at most 2
decimal places with an ASCII dot, trimming trailing zeros; the pill uses `floatformat`
(`_quiz_pill.html:7`), which localises and renders **one decimal place for a fractional value and
none for a whole one**. So in Polish the page prints a badge `0.5/1` beside a pill „0,5", and a
0.67 mark prints „0,7" in the pill against „0.67" in the badge. **Both divergences are in scope**;
fixing only the separator leaves the page disagreeing with itself.

- The filter appears on **15 template lines / 25 occurrences** across three templates:
  `quiz_results.html` (7), `analytics_student_quiz.html` (5), `course_results.html` (3).
- **Five assertions across three tests pin its current output** (`tests/test_quiz_scoring.py:33-45`).
  ⚠️ They call the filter directly with **no active language**, so each updated assertion wraps in
  `translation.override(...)`.
- ⚠️ **Grouping cannot be suppressed by the caller.** `django/utils/numberformat.py:32-33`
  computes `use_grouping = use_l10n and settings.USE_THOUSAND_SEPARATOR`, then
  `use_grouping = use_grouping or force_grouping` — so `force_grouping` can only ever **add**
  grouping, never remove it, and `False` is its default. `USE_THOUSAND_SEPARATOR` is unset in this
  repo, so no mark groups today; if it were ever switched on, marks would group like every other
  number on the site. §5.5 states that rather than pretending to override it — an earlier draft
  claimed `force_grouping=False` was load-bearing and specified a test whose mutant could not fail.
- ⚠️ **The CSV/XLSX export does NOT use this filter** — `courses/gradebook.py` builds Decimals in
  Python (`:80-140`) — so localising cannot corrupt an exported file.

### 2.10 Existing tests that assert a rendered pupil name

- `tests/demo/test_provision.py:48-49` carries a comment stating the analytics templates render
  `display_name|default:username` "and nothing else" — which §3.2 falsifies. Repaired
  line-count-neutral (repo convention).
- ✅ **`UserFactory` sets `display_name = Faker("name")` and NO `first_name`/`last_name`**
  (`tests/factories.py:58-65`), so `list_display_name` returns the display name unchanged for every
  factory-built pupil. **The §3.2 switch is invisible to the existing suite, and the inventory the
  plan runs is expected to come back EMPTY.** T3 must build its own first+last pupil.

### 2.11 The help screenshots these changes invalidate

`tests/capture_help_screenshots.py` holds **29 shot definitions** (`SHOTS`, `:129`), and
`core/static/core/img/help/` holds **58 committed PNGs**. Each tuple is
`(name, login_as, route-args, wait_selector, clip_selector)` (`:128`).

**Affected shots, checked two ways — by page and by CSS class:**

| shot | clip | why it changes | PR |
|---|---|---|---|
| `analytics-matrix` (`:174-180`) | `section.manage` | pupil names respelled/reordered (§3) | A |
| `drill-down` (`:181-187`) | `section.manage` | the tree, the `h1` and the back link (§4) | B |
| `review-submission` (`:196-201`) | `.review-shell` | renders `.badge--muted` twice (`review_submission.html:76,78`), which §5.4 recolours | B |

⚠️ **An earlier draft named the two *wait* selectors as clips and analysed the wrong region**, and
its "no other shot is affected" check tested only for pupil names — which cannot see a shared
class. `review-queue` also clips `section.manage` and renders pupil names, but N2 leaves that
template alone.

⚠️ **PR A's shot may come out byte-identical.** `courses/management/commands/seed_demo_course.py:
105-109` creates `demo_student`, `demo_s1..s3` with display names only and **no structured
names**, so `list_display_name` returns the same string and their Polish order already matches the
username order. §8's checklist asserts the absence of collateral changes, not the presence of a
diff.

⚠️ **The script rewrites all 58 PNGs on a local renderer and is NOT `@pytest.mark.e2e`.** Each PR
regenerates its own shots and restores the rest with
`git checkout -- core/static/core/img/help/`.

---

## 3. Pupil order and names

### 3.1 One ordering helper

A single function — `ordered_students(students)` in **`grouping/scoping.py`**, beside
`students_in_scope`, which is where both call sites get their pool from
(`courses/views_analytics.py:37`, `courses/views_export.py:16`). It gains
`from core.collation import polish_sort_key`, which that module does not have today, and returns a
**list**:

```python
def ordered_students(students):
    """Register order: surname, then first name, Polish alphabetical (spec §3.1)."""
    return sorted(students, key=lambda u: (polish_sort_key(u.sort_name), u.username))
```

**Rejected: `courses/ordering.py`** — that module is the *content-node* ordering space (move /
assign / compact / place); a pupil-display helper there would overload the name.

Both matrix builders already call `list(students)` (`courses/rollups.py:753,811`), and both
gradebook builders preserve the order they are handed (`courses/gradebook.py:76,105`;
`build_matrix_table:40-48`), so a list is a safe substitute at every call site.

**Call sites changed:** `views_analytics.py:107-110` and `views_export.py:50-54`. The helper wraps
the **whole** subset/no-subset expression, so the two views cannot drift on where it is applied:

```python
students = scoping.ordered_students(
    pool.filter(pk__in=subset_pks) if subset_pks else pool
)
```

⚠️ **`grouping/views.py:434,561,605,612,712` keep their inline copies of the key** — deliberately
out of scope. Those five sites sort teachers and memberships as well as pupils, and repointing them
widens PR A from two views to a second app's page set. **Recorded as follow-up work**, not as an
oversight; §9 lists the duplication as a risk.

### 3.2 One display label

`list_display_name` replaces `display_name|default:username` in:

- `templates/courses/manage/analytics_matrix.html:144` (checkbox `aria-label`) and `:145` (the row
  name cell, linked and unlinked branches);
- `courses/gradebook.py:42,133` (the exported `name` column, both shapes).

The two drill-down headings (`analytics_student.html:8-9`, `analytics_student_quiz.html:11`) switch
too, but **in PR B**, where they are rewritten anyway (§8).

⚠️ **The parenthetical branch is reachable here.** A pupil with first + last **and** an unrelated
display name renders `"Anna Nowak (Uczeń demo — sp-12 (#41))"` (`accounts/models.py:69-71`).
Accepted as-is on every surface: it is the app-wide roster convention, and truncating it in a row
header would hide exactly the disambiguation it exists for. §7.1 T3 pins it.

Unchanged by decision: the review queue and review submission screens (N2), and everything under
`grouping/`, which already uses `list_display_name`.

### 3.3 What this does not do

No index, no `db_collation`, no SQL-side ordering. The sort is in Python over a pool already
materialised for rendering; a class is tens of pupils. Thousands of rows on one screen is a
different design.

---

## 4. The pupil results page

### 4.1 Mode reaches the tree, the context and the template

**`build_student_breakdown` owns the prune.** Its signature becomes
`build_student_breakdown(course, student, *, drafts, with_data=None, mode="progress")`, and the
`tree` it returns is **already pruned** when `mode == "results"`. The four existing call sites
(§2.3) omit the argument, so they keep today's unpruned tree — which is what leaves the two
tree-shape tests untouched — and `has_math` at `views_analytics.py:277` automatically scans the
pruned tree without any re-ordering.

It also stamps each **unit** dict with:

```python
d["additional"] = unit_marker(node) == MARKER_ADDITIONAL
```

— a **boolean**, not the raw marker, so no template can render a „Kwiz" chip from it (§2.3), while
the rule still lives in `unit_marker`. The visible word comes from
`marker_label(MARKER_ADDITIONAL)` → „Dodatkowa".

**The view (`analytics_student`, `views_analytics.py:257-289`) changes in four ways:**

1. `_drill_params(request)` moves **above** the `build_student_breakdown` call (§2.4).
2. The builder receives `mode=mode`.
3. The view reverses its own path — `student_path = reverse("courses:manage_analytics_student",
   kwargs={"slug": course.slug, "student_pk": student.pk})` — which it does not compute today.
4. The context gains `mode` and `other_view_url` (§4.3). `_breakdown_node.html` reads `mode` from
   the inherited context: its recursive `{% include %}` (`:26`) passes `with item=child
   course=course` and **no `only`** — the plan must not add `only`.

**The prune, in `results` mode**, runs after the pill pass:

- **keep a unit iff `is_quiz_unit(node)`** (`rollups.py:151`), with its pill;
- keep a container iff it has a kept descendant;
- the containers' rollup counts stay on the dict; the template stops **rendering** the chip when
  `mode == "results"` (D7).

⚠️ **Stated as ONE predicate on purpose.** `ContentNode.unit_type` is `null=True`
(`courses/models.py:212-214`), and `unit_marker`'s docstring names "a unit whose unit_type is
unset" as a real case — so a pair of rules phrased as "keep quizzes, drop lessons" leaves that unit
undefined, and a "keep everything that is not a quiz" reading would silently put it back into
Results mode. `is_quiz_unit` decides it the same way the rest of the codebase does.

⚠️ **Pruning runs after `attach`, never before**: `_quiz_pill` is keyed off
`build_course_results`' rows, and a container dropped early would take its quiz with it.

⚠️ **A quiz with no submission keeps its `not_started` pill and stays on the page** — the gaps are
the point of the view.

### 4.2 What each row shows

**The right-hand column, in both modes.** A quiz row carries its **pill**; a lesson row carries its
**completion marker**. They share the column's *position*, not its contents — a quiz row never
grows a completion marker (§2.3), and carries no kind chip either.

**The alignment reuses `.rollup`'s pattern** (`app.css:608-612`) and adds no wrapper element (§2.5):

⚠️ **Every rule in this section goes in `core/static/core/css/app.css`.**
`templates/courses/manage/analytics_student.html:4` overrides `extra_css` with the KaTeX include
alone, so this page loads only `reset.css`, `tokens.css` and `app.css` from `base.html:44-46` —
**`courses.css` is not linked here at all**. A breakdown rule placed beside the badge family in
`courses.css` (where §5.4's modifiers correctly go, because both verdict pages do link it) would
render nothing on this page.

- `.breakdown-unit .pill{margin-left:auto}` — ⚠️ **scoped to the breakdown**, never a bare
  `.pill{…}`, which would break the per-question header (§2.8).
- **`.badge--todo` shares only the ALIGNMENT**, via a new
  `.badge--done, .badge--todo { margin-left: auto; }` rule in `app.css`, with
  `.badge--done`'s existing declaration block left otherwise intact and `.badge--todo` given its
  own muted-border, no-fill rule.
  ⚠️ **`app.css:739-740` is not an alignment rule**: it is
  `.badge--done { margin-left: auto; background: var(--success-subtle); color: var(--success);
  border-color: … }`. An earlier draft said `.badge--todo` should join that selector list, which
  would have painted "not completed" in the same green as "completed" — the opposite of the signal
  — while T13 (class + accessible name) and T33 (alignment) both stayed green.
  ⚠️ The alignment must also stay cancellable: `courses.css:897`'s `.unit-tree__check{margin-left:0}`
  resets it at equal specificity on leading-tick rows, so the shared rule stays in `app.css`, ahead
  of that reset (§2.5).
- An **awaiting-review row has two right-hand items** — the pill, then the `Review` link
  (`_breakdown_node.html:9-11`). `margin-left:auto` sits on the **pill**, so the pair travels
  together in the order pill → link, as `.rollup + .rollup` handles a second chip. T33 A/Bs it.

**Both modes**
- A quiz title is a **visible link** when it has a submission: link colour plus a persistent
  underline (§2.5). An unstarted quiz stays plain text.
- The `Review` link's content is unchanged.

**Lesson rows (Progress mode only renders them)**
- Every unit title uses the **normal text colour**: `.breakdown-unit__title.is-done`
  (`app.css:1012`) loses its `color` declaration. ⚠️ **The `is-done` class keeps being emitted**
  (`_breakdown_node.html:16`): it is the DOM's only record of completion on a lesson row and what
  T33's A/B toggles against.
- A finished lesson keeps `<span class="badge badge--done" aria-label="Completed">✓</span>`; an
  unfinished one gets `<span class="badge badge--todo" aria-label="Not completed">○</span>` — a
  muted border, no fill.
- A lesson with `item.additional` true carries a `<span class="badge breakdown-unit__tag">`
  („Dodatkowa"), **placed after the title and before the right-aligned marker**, so the marker
  column stays the row's last element. T12 asserts that order.

**Results mode only** — lessons absent, quiz-less chapters absent, chapter chip not rendered (D7).

### 4.3 The page's name, its heading and the view switch

**"Breakdown" / „Szczegóły ucznia" is retired as the page's name**, in favour of the owner's own
term „wyniki ucznia" (settled while merging #323). ⚠️ **The mode is NOT part of the page's name** —
an earlier draft put the view word in the `h1` and left „Wyniki ucznia" in the tab and the back
link, which gave one page two names again, and made the Progress view's tab say „Wyniki".

| surface | today | after |
|---|---|---|
| `analytics_student.html:3` `head_title` | `Breakdown` / „Szczegóły ucznia" | `Pupil results` / „Wyniki ucznia" |
| `analytics_student.html:8-9` `h1` | „Szczegóły ucznia — X" | „Wyniki ucznia — X" (mode-independent) |
| the view | not shown | **the switch below the heading**, two links marked current/other |
| `analytics_student_quiz.html:12` back link | „← Szczegóły ucznia" | „← Wyniki ucznia" |
| `docs/help/teacher/drill-down.{md,pl.md}` | "Per-student breakdown" | follows this table |

⚠️ Those three template lines are the **only** consumers of the `Breakdown` msgid, so it goes
obsolete in both catalogs (§6).

- **The switch** carries the mode words (`Results` / `Progress`, `locale/pl:2628,2633`), the
  current one marked (`aria-current="page"`), the other linking to
  `f"{student_path}?{_expand_qs(scope, other_mode, expand_pks, subset_pks, values)}"` — built as
  the matrix builds its own pair (§2.4), passed as `other_view_url`. It preserves scope, expanded
  columns, subset and values.
- „← Analityka" is unchanged, and the per-question page's back link already carries the mode.

---

## 5. The per-question page

### 5.1 A choice question shows every option

**Interface.** `summarise(question, response, mark_result, *, option_marks=_MISSING)` gains a
keyword argument with a **module-level `_MISSING` sentinel**, and dispatches as today for nine
adapters while passing the extra argument to `_choice` alone:

```python
_MISSING = object()

def summarise(question, response, mark_result, *, option_marks=_MISSING):
    adapter = _ADAPTERS[type(question)]
    if adapter is _choice:
        if option_marks is _MISSING:
            raise TypeError("summarise() needs option_marks for a choice question")
        return _choice(question, response, mark_result, option_marks)
    return adapter(question, response, mark_result)
```

⚠️ **The sentinel is not `None`.** `None` is what `_results_row` legitimately hands over for a
non-auto choice question (§2.6), so a guard keyed on `None` would 500 every REVIEW choice question
while failing to detect a genuinely omitted argument. The nine other adapters keep their exact
signature.

`_quiz_answer_rows` passes the dict the page already computed, normalised at the call site:

```python
row["parts"] = summarise(
    question, response, row["reveal_result"], option_marks=row["marks"] or {}
)
```

⚠️ **`row["marks"] or {}` is required, not cosmetic** — the value is `None` outside the AUTO branch
(§2.6), and `_choice` must not have to know that. ⚠️ **`_choice` never calls `choice_marks`
itself**: one call site is the whole point (D3).

**The record.** `Option` is a frozen dataclass in `courses/answer_summary.py`, beside `Part`:

```python
@dataclass(frozen=True)
class Option:
    text: str
    picked: bool
    correct: bool | None   # None when the question is not auto-marked
    mark: str | None       # "correct" | "wrong" | "missed" | None
```

- `text` — `choice.text`, in `Choice.Meta.ordering` order.
- `picked` — `choice.pk in picked_ids`, where **`picked_ids = set(response.latest_answer or [])`
  computed inside today's `if _answered(response)` guard**, else an empty set. ⚠️ **The guard is
  load-bearing**: `response` is `None` for an untouched question (§2.6).
  ⚠️ **Deliberately NOT routed through `selected_ids(answer_from_json(...))`**, as an earlier draft
  had it: for a choice question `answer_from_json` returns exactly `set(latest_answer or [])`
  (`courses/quiz.py:195-197`) and `selected_ids` passes a set through, so the detour is equivalent
  — and it would add a `courses.quiz` import to `answer_summary.py`, which today imports only
  `courses.fillblank` and `courses.models`. Neither path filters stale pks, which is what keeps the
  one-row-per-missing-pk rule below working.
- `correct` — `choice.pk in set(mark_result.reveal or ())` when the question is auto-marked,
  **`None` otherwise**. ⚠️ **Never `Choice.is_correct`**.
- `mark` — `option_marks.get(choice.pk, {}).get("kind")`: whatever `choice_marks` said, `None`
  where it said nothing.

**The part** carries the options and two flags the template cannot derive:

```python
Part(kind="options", label=None, label_is_content=False, given=None, expected=None, ok=None,
     options=[Option(...), ...], options_auto=_is_auto(question), options_empty_key=<see below>)
```

`Part` gains `options` (default `None`), `options_auto` (default `None`) and `options_empty_key`
(default `False`); every other builder is untouched and `Part.mark` is unaffected.
`options_empty_key` is `options_auto and not set(mark_result.reveal or ())`. ⚠️ **Both flags are
computed in the builder** because a Django template cannot evaluate a condition across a list, and
a per-row heuristic is unreliable (a removed-option row carries `correct=None` even on an auto
question).

**Rules**
- **Picked options that no longer exist** render after the live options as
  `Option(text=„(usunięta opcja)", picked=True, correct=None, mark=None)` — ⚠️ **one row per
  missing pk** (§2.6): three deleted picks render three rows. They assert no verdict, because a
  deleted option's correctness is unknowable.
- **An AUTO question whose key is empty** (`options_empty_key`): ⚠️ **every PICKED option is marked
  `wrong`**, because that is what `choice_marks` does with an empty key (§2.6); unpicked options
  are unmarked, and only an *unanswered* pupil's table is fully unmarked. The table carries a
  caption reusing the „(none)" msgid — „poprawna odpowiedź: (brak)" — which is the element that
  distinguishes this case from a non-auto one.
- **Not answered** — every option listed, none picked, the key still marked. The row badge („Bez
  odpowiedzi") carries the state; the options block renders no „Not answered" fallback text.
- **Not auto-marked** (`options_auto` false) — options listed with picks only; the „Poprawna
  odpowiedź" column is omitted entirely.
- **In progress** — the key is shown (PR 5's D5); `locked=True` comes from `_results_row`.
- ⚠️ **A choice question loses its part-level ✓/✗ glyph**: `ok=None` makes `Part.mark` `None`, so
  `analytics_student_quiz.html:69-70` renders no row-level glyph — the per-option markers replace
  it.

**Markup.** A `<table class="answers__options">` in a new `{% if part.kind == "options" %}` branch
in `analytics_student_quiz.html:61-75`, placed **before** the `kind == "answer"` branch (`:64`).

- Three columns, with **all three header words specified**: „Wybór ucznia", „Poprawna odpowiedź"
  (the whole column omitted when `options_auto` is false), and „Odpowiedź" over the option text
  (`lang="{{ course.language }}"` on the cells, not the header). No empty `<th>`: a header cell
  with no word is a column a screen reader cannot name.
- **Cell by cell** — the rule an earlier draft left open:
  - column 1 renders a filled dot (●) **iff `picked`**, otherwise an empty one (○);
  - column 2 renders ✓ **iff `correct` is true**, otherwise nothing;
  - the row's `mark` drives its colour class (`is-correct` / `is-wrong` / `is-missed`, reusing the
    `courses.css:382-386` palette) and **one** `sr-only` label, emitted **once, in column 1**
    („wybrana, poprawna" / „wybrana, niepoprawna" / „poprawna, niewybrana", §6), so assistive tech
    hears the verdict once rather than per cell. Rows with `mark is None` get no label.
- **`<th>` text is visible at ≥640px and `.sr-only` below** (`.sr-only` is a real global,
  `reset.css:25`), so the marker columns are as wide as their header words on desktop and collapse
  to glyph width on a phone, where each row's own label still carries the meaning.
- `width:100%` with `table-layout:auto`; the marker columns take `width:1%; white-space:nowrap`.
  Without the explicit width the table shrink-wraps inside its flex parent (`app.css:1028`).

### 5.2 Every other type keeps its parts, and gains labels

- **Single-part types** render „Odpowiedź ucznia: …" and, only where the part is not right,
  „Poprawna odpowiedź: …" (`locale/pl:5459`).
- **ONE predicate decides both the grid and the header row**, computed in `_quiz_answer_rows`
  (`from courses.answer_summary import ANSWER`, which is defined at `answer_summary.py:28`):

  ```python
  row["columned"] = (
      len(parts) > 1
      and all(p.kind == ANSWER for p in parts)
      and any(p.expected for p in parts)
  )
  ```

  - `len(parts) > 1` alone is wrong — extended response emits one `answer` part plus N `keyword`
    parts (§2.6) — and a choice question's single `options` part fails the same test.
  - The `any(p.expected …)` term keeps an **all-correct** multi-part question out of the grid:
    `_answer_part` sets `expected=None if ok is True else expected` (`answer_summary.py:73-75`), so
    such a question has nothing to put in a third column.
- **The grid, and every child that lands in it.** ⚠️ `.answers__part` emits up to **five** element
  children today (`analytics_student_quiz.html:63-71`): `.answers__label`,
  `.answers__given`/`.answers__muted`, `.answers__glyph`, a bare `<span class="sr-only">`, and
  `.answers__expected`. Under `display:contents` all five would become grid items and the three
  columns would never form (`.sr-only` is clipped, not `display:none`, so it still occupies a
  track). **The columned branch therefore emits exactly three children per part:**

  1. `.answers__label`
  2. `.answers__given-cell` — wrapping the given value (or `.answers__muted`), the glyph and its
     `sr-only` label
  3. `.answers__expected` — **emitted unconditionally**, empty when `part.expected` is falsy,
     because under `display:contents` a missing child does not leave a blank cell: the next part's
     label slides into the vacated track.

  `.answers__given-cell` is emitted in **both** layouts and is `display:contents` in the
  non-columned one, so today's flex rendering is unchanged.

  ```css
  .answers__parts--columned{display:grid;grid-template-columns:auto 1fr 1fr;
    column-gap:.6rem;row-gap:.35rem;align-items:baseline}
  .answers__parts--columned .answers__part{display:contents}
  .answers__parts--columned .answers__header-row{display:contents}
  ```

  ⚠️ **The header row needs `display:contents` too** — it is a direct child of the grid, so without
  it the three header words sit in one cell in column 1. **It emits three spans, one per column:**
  an empty one over the label column (the labels are the row's own names — „Luka 1", „kot" — and a
  header over them would name nothing), „Odpowiedź ucznia" over the given column, and
  „Poprawna odpowiedź" over the expected column. The empty span is still emitted, because the grid
  needs the cell.
  ⚠️ `display:contents` also means `.answers__part`'s own `padding`, `gap` and `overflow-wrap`
  (`app.css:1028-1031`) stop applying to these questions: row rhythm comes from the grid's
  `row-gap`, and `overflow-wrap:anywhere` moves onto the three children.
- **The 390px fallback is an explicit rule, not the old one.** `.answers__part`'s existing
  `@media (max-width:640px){flex-direction:column}` (`app.css:1036-1039`) is inert under
  `display:contents`:

  ```css
  @media (max-width:640px){
    .answers__parts--columned{display:block}
    .answers__parts--columned .answers__part{display:flex;flex-direction:column}
    .answers__parts--columned .answers__given-cell{display:contents}
    .answers__parts--columned .answers__header-row{display:none}
  }
  ```

  The per-part „Poprawna odpowiedź:" prefix stays in the markup always and is hidden by CSS above
  640px (`.answers__parts--columned .answers__expected-label{display:none}`), so it "returns" on a
  phone without the template knowing the viewport.
- ⚠️ **Extended response with keywords is neither shape** — guaranteed by the
  `all(p.kind == ANSWER …)` term.
- `Part.label_is_content` still decides `lang` tagging; the header row and the option table's
  `<th>`s are interface text and carry no `lang`.

### 5.3 The header

- **Two lines, not one dash-joined title:** the pupil's `list_display_name` on a small line above,
  the quiz title as the `h1` below (today: `"{{ unit.title }} — {{ student… }}"`, `:11`).
- **The back button does not wrap beneath a long title**, by rule rather than by hope:
  `.manage__head{flex-wrap:nowrap}`, `min-width:0` on the title block and `flex-shrink:0` on the
  button. T33 A/Bs it with a deliberately long quiz title.
- **The header renders, by pill kind:**

  | pill kind | prominent figure | pill |
  |---|---|---|
  | `scored` | „1 / 5 pkt" + „20%" | **not rendered** |
  | `submitted` (ungraded, `max_score == 0`) | none | „przesłano" |
  | `awaiting` | none | „oczekuje na ocenę" + the „Sprawdź" link |
  | `in_progress` | none | „w toku" + „Odpowiedzi: 3 z 6" (`locale/pl:6229`) |

- **The score element uses the `marks` filter** — `{{ p.score|marks }} / {{ p.max_score|marks }}` —
  so §5.5's rule reaches the page's most prominent figure. **The percentage renders unfiltered**
  (`{{ p.percent }}%`): `_pct` returns an `int` (§2.8), so no decimal can appear.
- ⚠️ **The shared pill partial's LOGIC is not modified.** For a `scored` quiz the header renders the
  score stat *instead of* the pill; the other three kinds include `_quiz_pill.html` as today. (§5.5
  does edit that file — one filter and one `{% load %}` — for both its consumers alike.)
- No dash, no „0 / 0" placeholder: a kind with no score renders no score element.

### 5.4 Outcome colour, reconciled across both pages

⚠️ Per §2.7 the pupil's page already tints the whole question panel, so a transparent badge shows
that tint through and stays green-on-green. The badge therefore **keeps the base `.badge`'s
`background: var(--surface-sunken)`** (`app.css:145-156`) and takes **a 1px border and text in the
outcome colour**.

⚠️ **The fill must differ from BOTH backdrops.** An earlier draft said
`background: var(--surface-raised)` — which is exactly what `.answers__item`, the teacher page's
question card, already uses (`app.css:1023-1024`). That would have cured green-on-green on the
pupil page by creating raised-on-raised on the teacher page. `--surface-sunken` differs from the
card and from every `*-subtle` panel tint, and T33b measures both.

| outcome | badge | class | applies to |
|---|---|---|---|
| `correct` | `--success` border + text on `--surface-raised` | `.badge--correct` | both verdict pages |
| `partial` | `--warning` border + text | `.badge--partial` | both verdict pages |
| `incorrect` | `--danger` border + text | `.badge--incorrect` | both verdict pages |
| `not_answered` | muted — `--text-tertiary` → `--text-secondary` (AA repair) | `.badge--muted` | ⚠️ **four templates**, §2.7 |
| `recorded`, `reviewed` | unchanged (neutral base) | — | both verdict pages |
| `review` | unchanged | `.badge--review` | both verdict pages |

⚠️ **The `.badge--muted` recolour is global by design.** Its four consumers are
`quiz_results.html:34`, `analytics_student_quiz.html:49`, `review_submission.html:76,78` and
`course_results.html:24,34`. The change is an accessibility repair, so applying it everywhere is
intended — but it is why §2.11 lists a third help screenshot and §7.4 lists two extra surfaces.

The modifiers are defined in `courses/static/courses/css/courses.css`, beside `.badge--review` and
`.badge--muted` (`:712-716`) — both verdict pages link that sheet.

Applied in `analytics_student_quiz.html:46-52` and `quiz_results.html:31-37`, which stay deliberate
copies of one another (PR 5 spec §5.1); the drift note in both templates gains the modifier.

**On the teacher page only, the question card's left edge takes the outcome colour**
(`.answers__item.is-correct` / `.is-partial` / `.is-incorrect` — classes the template already emits
at `:28` with no rules today), mirroring the pupil page's panel tint.

**Colour is never the only signal.** The badge's word carries the outcome on every type; non-choice
types keep their per-part ✓/✗; choice questions carry the per-option markers (§5.1).

⚠️ **Dark mode is not free here.** `.pill--scored` hardcodes `color:#fff` on `--primary`, and
`.pill--awaiting` hardcodes `#f5b942`/`#3a2a00` (`app.css:1044-1049`). Both are re-expressed in
tokens here and judged in the dark screenshots.

### 5.5 Marks read the same everywhere — separator AND precision

1. **`marks_filter` localises its decimal separator.** It keeps its 2dp-and-trim rule and its
   `None → "—"` branch, passing the trimmed value through
   `django.utils.formats.number_format(value, decimal_pos=None)`.
   ⚠️ **Grouping is deliberately left to the project setting** (§2.9): `force_grouping` cannot
   suppress grouping — it only ever adds it — so passing `False` would be decoration, and a test
   that "proves" it could never fail. `USE_THOUSAND_SEPARATOR` is unset today; if it is ever
   switched on, marks group like every other number on the site, which is the consistent outcome.
2. **The pill stops using `floatformat`.** In `_quiz_pill.html:7` the two filters **inside the
   existing `{% blocktrans with s=… m=… %}`** change from `|floatformat` to `|marks`; the
   `scored %(s)s/%(m)s` msgid, the „scored" word and the trailing `({{ p.percent }}%)` are
   **unchanged**. So a 0.67 mark reads „0,67" in the pill, the badge and the header score alike.
   ⚠️ **Line 1 of that partial becomes `{% load i18n courses_extras %}`** — an included template
   does not inherit its includer's libraries (§2.8), and without the load the page raises
   `TemplateSyntaxError`. ⚠️ This changes the **breakdown's** pill text too; T27's parity half
   asserts the full rendered string, „scored" word included.

- The five assertions across three tests (§2.9) move to per-locale expectations, each inside an
  explicit `translation.override(...)`, with a ≥ 1000 value added.
- The exported file is unaffected (§2.9) and T30 says so.

---

## 6. Interface text

| English (new) | Polski (proposed) | where |
|---|---|---|
| `Pupil's answer:` | „Odpowiedź ucznia:" | §5.2 single-part label |
| `Pupil's answer` | „Odpowiedź ucznia" | §5.2 multi-part header row |
| `Pupil's choice` | „Wybór ucznia" | §5.1 option column header |
| `Correct answer` (no colon) | „Poprawna odpowiedź" | §5.1 option column header, §5.2 header row — ⚠️ a NEW msgid: the reused `locale/pl:5459` entry carries the colon |
| `Answer` | „Odpowiedź" | §5.1 option-text column header |
| `chosen, correct` | „wybrana, poprawna" | §5.1 row label (once, column 1) |
| `chosen, incorrect` | „wybrana, niepoprawna" | §5.1 row label |
| `correct, not chosen` | „poprawna, niewybrana" | §5.1 row label |
| `correct answer: %(key)s` | „poprawna odpowiedź: %(key)s" | §5.1 empty-key caption (`%(key)s` is the reused „(brak)") |
| `%(s)s / %(m)s marks` | „%(s)s / %(m)s pkt" | §5.3 score stat |
| `Not completed` | „Nieukończone" | §4.2 empty-circle marker |
| `Pupil results` | „Wyniki ucznia" | §4.3 page name, heading, back link |

⚠️ **The score's percentage is NOT in that msgid.** „1 / 5 pkt" and „20%" are two elements —
`<span class="answers__score">` and `<span class="answers__percent">` — with the separator supplied
by CSS, not by a literal „·" inside a translated string.

⚠️ **`Breakdown` / „Szczegóły ucznia" goes OBSOLETE** in both catalogs: §4.3 replaces all three of
its consumers. `makemessages` will comment the entry out, and that obsolete block is an expected
part of PR B's diff — distinct from a fuzzy entry, which is not.

⚠️ **Three near-identical Polish words land in one question card** and want the owner's judgement
together: „Poprawnie" (the verdict badge), „Poprawna odpowiedź:" (the key label, existing) and
„Poprawna odpowiedź" (the option column header, proposed). „Klucz" is the alternative for the
column header. Flag all three in the PR body as one question.

Reused, not re-created: `Correct answer:` (`locale/pl:5459`), `(removed option)` (`:423`),
`(none)` (`:427`), `Not answered` (`:6243`), `Correct` / `Incorrect` / `Partial`, `Review`
(`:5636`), `Additional` / „Dodatkowa" (`rollups.UNIT_MARKER_LABELS`), `Progress` / `Results`
(`:2633,2628`), `Completed`, `%(k)s of %(n)s question answered` (`:6229`), and every pill word.

⚠️ `makemessages` fuzzy-prefills new msgids from similar existing ones — it did so twice in #323.
Every new entry is checked by hand and the catalogs end at 0 fuzzy.

---

## 7. Tests

Every rule below is falsified against a named mutant, run and observed red, then reverted by hand.

### 7.1 Order and names (§3)

- **T1** A class whose username order disagrees with surname order renders in surname-then-first-name
  order. Fixture: `Świątek`, `Nowak`/`Nowakowska`, two pupils sharing a surname, one login with no
  first/last name. *Mutants:* restore `order_by("username")` → red; sort by the raw `sort_name`
  string without `polish_sort_key` → red on `Świątek`.
  ⚠️ The `_RANK_SPACE` mutant belongs to `tests/test_collation.py::test_space_sorts_before_letters`
  (§2.2) — T1 keeps the prefix pair as data but does not claim that falsification.
- **T2** The same class exports in the same order, asserted on the parsed file.
  *Mutant:* order the export by username only → red.
- **T3** The matrix renders „Mateusz Adamczyk"; the checkbox label names the same string; a
  no-names login falls back to its display name; a pupil with first + last + an unrelated display
  name renders the parenthetical form in full. ⚠️ **T3 builds its own pupils with structured
  names** — `UserFactory` sets none (§2.10). *Mutant:* revert to `display_name|default:username`
  → red.
- **T4** Non-vacuity: the fixture's username order and surname order genuinely differ.
- **T5** The two drill-down headings still render `display_name|default:username` **after PR A**.
  ⚠️ **T5 is DELETED in PR B**, which rewrites both headings by design; successors are T28 and
  T28b. PR B's implementer deletes it rather than weakening it.
- ⚠️ No assertion may rest on database ids.

### 7.2 The pupil page (§4)

- **T6** `?mode=results`: quizzes present, **no lesson title**, a quiz-less chapter absent, an
  unstarted quiz present with its pill. *Mutant:* skip the prune → red.
- **T7** `?mode=results`: a rendered chapter carries **no `.rollup`** (D7). *Mutant:* keep the chip
  in both modes → red.
- **T8** `?mode=progress`: lessons and chips present. *Mutant:* prune unconditionally → red.
- **T9** No `mode`, and `?mode=nonsense`, both render Progress. *Mutant:* default to results → red.
- **T10** A quiz nested three deep keeps its part and chapter. *Mutant:* prune before `attach` → red.
- **T11** The switch links to the same pupil in the opposite mode, preserving scope, expand, subset
  and values, and marks the current view. *Mutant:* drop `subset_pks` → red.
- **T12** A non-obligatory lesson carries the „Dodatkowa" tag **between the title and the marker**;
  an obligatory one does not; **a quiz row carries no kind chip**.
  *Mutants:* tag every lesson → red; stamp the raw `unit_marker` and render it unguarded → red
  („Kwiz" appears); emit the tag after the marker → red on the order assertion.
- **T13** A quiz row carries a pill and no completion marker; a lesson row a marker and no pill;
  the unfinished marker is `.badge--todo` with its accessible name.
  *Mutant:* render the marker on every unit → red.
- **T14** The quiz title's link is **visibly** a link — underline without hover — via T33's A/B.
  `test_t37_quiz_titles_link_iff_the_pupil_has_a_submission` covers the `<a>`-presence half.
- **T15** `build_student_breakdown`'s default is `progress`: the four existing call sites still
  return an unpruned tree. *Mutant:* make `mode="results"` the default → red on the two existing
  tree-shape tests (§2.3).
- **T16** `has_math` is computed from the pruned tree: a Results page whose only maths title
  belongs to a lesson does not load KaTeX. *Mutant:* have the builder also return the unpruned
  tree and let the view scan that copy → red. (⚠️ Not "prune after the `has_math` call": with the
  prune inside the builder and the scan in the view there is no call order to invert, so that
  mutant cannot be applied.)

### 7.3 The per-question page (§5)

- **T17** Builder, one case each: picked-and-correct, picked-and-wrong, missed, untouched,
  **not answered with NO response row** (§2.6), `multiple=True`. Each asserts `Option`'s fields.
  *Mutants:* invert `picked`; drop `missed`; drop the `_answered` guard → `AttributeError` on the
  no-response case.
- **T17b** **Two** picked-but-deleted options render **two** rows, last, each `picked=True`,
  `correct=None`, `mark is None`. *Mutants:* emit a single placeholder → red; fall back to `wrong`
  for an unknown pk → red.
- **T17c** `summarise` raises `TypeError` for a choice question when `option_marks` is omitted
  **and returns normally when it is passed `{}`** (§5.1) — the two states a `None`-keyed guard
  cannot tell apart. *Mutant:* default `option_marks=None` and raise on `None` → red on the second
  half (a non-auto question 500s).
- **T18** A **non-auto** choice question: `option_marks` arrives `{}` (normalised from `None`),
  every option has `mark is None` and `correct is None`, `options_auto` is False, and no „Poprawna
  odpowiedź" column renders. *Mutants:* source `correct` from `Choice.is_correct` → red; drop the
  `or {}` normalisation → `AttributeError`.
- **T19** For a **submitted, auto-marked** question over **live** options, the per-option kinds
  equal the `choice_marks` dict the page computed, and the pupil's results page renders the same
  kinds, with "absent ≡ `mark is None`" asserted. ⚠️ Scoped deliberately: in-progress, non-auto and
  deleted-option cases break equality by design. *Mutant:* pass a doctored `option_marks` and
  assert the page follows it → red if `_choice` re-derives.
- **T20** The page lists **every** option, in author order. *Mutant:* render only picked → red.
- **T21** Teacher voice: `test_t35_teacher_voice_only` extended over the new labels.
  *Mutant:* reuse `MARK_GLYPHS`' pupil-voice labels → red.
- **T21b** Exactly **one** `sr-only` verdict label per option row, in column 1 (§5.1).
  *Mutant:* label both marker cells → red (the verdict is announced twice).
- **T22** Maths in an option text loads KaTeX. ⚠️ **Mutant in `_question_has_math`'s choice branch**
  (`courses/views.py:104-107`) — delete it → red.
- **T23** `test_t38_query_count_does_not_grow_with_questions` still passes.
  *Mutant:* re-query `question.choices.all()` outside the prefetch → red.
- **T24** Extended response with two keywords: `row["columned"]` is False, the answer part carries
  „Odpowiedź ucznia:", the keyword parts get no header row.
  *Mutant:* `columned = len(parts) > 1` → red.
- **T24b** An **all-correct** multi-part question has `columned` False; a partially-correct one
  True. *Mutant:* drop the `any(p.expected …)` term → red on the all-correct case.
- **T24c** In a columned question **every part emits three children**, including an empty
  `.answers__expected` for a correct part (§5.2). *Mutant:* keep the `{% if part.expected %}` guard
  in the columned branch → red (the count drops to two and the next row shifts).
- **T25** Badge modifier per outcome on **both** verdict templates, asserted on the rendered class.
  *Mutant:* remove it from one template → red. The card-edge class is asserted on the teacher page.
- **T26** Header, per pill kind: `scored` renders the score element and **no pill**; the other
  three render the pill and **no** score element; `in_progress` renders the answered-count phrase.
  *Mutant:* render the score unconditionally → red on three of four kinds.
- **T27** `test_t36_header_pill_matches_the_breakdown_pill` is **replaced**: for `submitted`,
  `awaiting` and `in_progress` the header pill's class list and text still equal the breakdown
  row's; for `scored` the header renders **no** pill while the breakdown row shows its score,
  now formatted by `marks`, and the header's score element carries the same numbers.
  *Mutant:* let the header keep a pill for `scored` → red.
- **T28** The per-question heading renders name and title as separate elements, with no „ — ".
  *Mutant:* restore the joined title → red.
- **T28b** The pupil page's `h1` reads „Wyniki ucznia — <name>" in **both** modes, the tab title
  matches it, the back link reads „← Wyniki ucznia", and the **switch** carries the mode words with
  the current one marked (§4.3). *Mutants:* keep the `Breakdown` msgid → red; put the mode word in
  the `h1` → red (the tab and heading disagree again).
- **T29** In Polish a half mark renders „0,5" and a 0.67 mark „0,67" in the badge, the pill **and**
  the header score; in English „0.5"/„0.67" — each inside `translation.override`. The pill's full
  string still reads „wynik 0,67/1" (the „scored" msgid survives, §5.5).
  *Mutants:* revert `marks_filter` to ASCII → red; leave `floatformat` in the pill → red on 0.67;
  drop the partial's `{% load %}` → `TemplateSyntaxError` on both consuming pages; replace the
  blocktrans with bare variable output → red on the „wynik" word.
  ⚠️ **No grouping case:** §2.9 shows `force_grouping` cannot suppress grouping, so an
  "ungrouped under `USE_THOUSAND_SEPARATOR=True`" assertion would fail against any correct
  implementation, and its mutant could never go red.
- **T30** The exported gradebook still writes a dot decimal. *Mutant:* localise the export → red.
- **T31** The options table's `<th>`s read exactly „Wybór ucznia", „Poprawna odpowiedź",
  „Odpowiedź" (and only the first and third on a non-auto question); column 1 shows ● iff `picked`;
  column 2 shows ✓ iff `correct` (§5.1). *Mutants:* mark column 1 from `correct` → red; render
  column 2 for a non-auto question → red; emit an empty third `<th>` → red.
- **T32** An AUTO question with an empty key renders the „(brak)" caption, and its **picked options
  are marked `wrong`** (§5.1 — what `choice_marks` actually returns). *Mutant:* drop the caption →
  red, since the page would then be indistinguishable from T18's non-auto rendering.
- **The shared fixture moves first.** `tests/answer_summary_fixtures.py:117-128`
  (`summarise_stored`) is a **named deliverable**, not an incidental edit (§2.6): it gains the
  `choice_marks` call that mirrors `_results_row` and passes `option_marks` for choice questions
  only. ⚠️ It is the single entry point for **all ten** question types' builder tests, so getting
  it wrong reads as ten unrelated failures.
- **The five existing `_choice` tests** (§2.6) are rewritten against `Option` records, one for one:
  correct/wrong/unanswered → T17; single-select → T17's `multiple=False` case; review mode → T18;
  removed option → T17b; no-correct-option → T32. **None is deleted without a successor.**

### 7.4 Visual

- **T33** Every CSS rule this design relies on is confirmed by comparing the computed style **with
  and without** it (repo convention). Cases: the persistent underline (T14); the breakdown pill's
  `margin-left:auto` **and** the per-question header pill's position being unchanged (§2.8);
  `.badge--todo`'s presence **and** its right alignment (§4.2); the awaiting-review row's pill+link
  pair; the „Dodatkowa" tag's position; the card edge; the columned grid with a **five-child part**
  collapsed to three (§5.2) and with a **partially-correct** question, at desktop and in the 390px
  block fallback; the back button not wrapping under a long title (§5.3).
- **T33b** The badge has a surface of its own **against both backdrops**: its computed background
  differs from the pupil page's `question__feedback-panel--*` tint **and** from the teacher page's
  `.answers__item` card (`--surface-raised`), for `correct`, `partial` and `incorrect`, in both
  themes (§5.4). ⚠️ Asserting only the pupil-page half is what let an earlier draft specify a fill
  identical to the teacher card's.
- **T33c** `.badge--todo`'s computed background and border differ from `.badge--done`'s (§4.2), so
  "not completed" cannot inherit the completed tick's green.
- **T34** Screenshots, light and dark, desktop and 390px, on mat-pp data:
  - the Results and Progress pupil pages;
  - the per-question page: a submitted quiz with a wrong choice answer (the owner's „Zbiory - quiz"
    question 1), an in-progress quiz, a quiz awaiting review;
  - **`quiz_results.html`** (§5.4's badge on a tinted panel);
  - **`course_results.html`** and **`review_submission.html`** — the two extra `.badge--muted`
    surfaces (§2.7, §5.4).
  Dark is judged on its own, not as "light but darker".

---

## 8. Delivery

Two PRs, in order.

**PR A — pupil order and names (§3).** The helper, the two views, the matrix template's two lines
and `gradebook.py`'s two name fields; T1–T5. It repairs the stale `sort_name` docstring and the
stale `test_provision.py:48-49` comment, both line-count-neutral, and runs the §2.10 inventory
(expected empty).

⚠️ **PR A must NOT touch `analytics_student.html:8-9` or `analytics_student_quiz.html:11`** (§8's
PR B). T5 pins that boundary.

**PR B — the two pages (§4, §5, §6).** The design pass (`frontend-design`) runs inside this PR,
after the markup exists and before the screenshots are judged. Ships new msgids, one obsolete
msgid (§6); no migration, no `FORMAT_VERSION` bump, no new dependency. **Deletes T5**, relying on
T28/T28b.

**Help screenshots — a manual checklist item in each PR, NOT a pytest.** The capture script runs
outside the e2e marker on a local renderer (§2.11), so no test process can observe it. Each PR:
run the capture, keep this PR's own shots — `analytics-matrix.{en,pl}.png` for PR A;
`drill-down.{en,pl}.png` **and `review-submission.{en,pl}.png`** for PR B (§2.11) — restore every
other file with `git checkout -- core/static/core/img/help/`, and confirm `git status` shows **no
file outside this PR's own set**. ⚠️ **A kept pair may itself be unchanged** — PR A's matrix shot
probably is — so the checklist asserts the absence of collateral changes, not the presence of a
diff.

**Docs.** `docs/help/teacher/drill-down.md` and `.pl.md` gain the Results/Progress distinction, the
view switch, the „Dodatkowa" tag and the option list, and follow §4.3's naming.
`docs/help/teacher/analytics.md` and `.pl.md` gain one sentence on pupil order.

**Rollout.** Nothing here is gated by `LIBLI_VENDOR_INSTANCE`: these are ordinary teacher screens
on every box, including schools' real-pupil instances. The demo kit is only why the defects were
noticed.

---

## 9. Risks

1. **The deliberate template copy (§5.4).** `quiz_results.html` and `analytics_student_quiz.html`
   must stay parallel; T25 asserts both, and both templates carry the note.
2. **The shared pill (§2.8).** Shared twice over: one template included by two pages, and one
   global `.pill` class. §4.2's rule is scoped to `.breakdown-unit`, §5.3 leaves the partial's
   logic alone, and T27 plus T33 pin both halves.
3. **`.badge--muted` is recoloured on four templates (§2.7, §5.4)** — two of them outside this
   design's own pages. Intended (an AA repair), and the reason a third help screenshot and two
   extra screenshot surfaces are listed.
4. **`marks` now reaches three templates and the pill (§5.5)**, including `course_results.html`.
   Accepted deliberately: one rule for marks across the product beats two.
5. **Screenshot regeneration side effects (§2.11).** A careless run rewrites all 58 PNGs; §8's
   checklist is per PR and asserts no collateral diff.
6. **Structural test dependencies (§2.5).** Four selectors reach into the breakdown tree by direct
   child; a wrapper element added for §4.2's column breaks them with a misleading message.
7. **Replacing a builder that five tests specify (§2.6, §7.3).** Each has a named successor.
8. **`display:contents` (§5.2).** It removes the part div from the box tree, so padding, borders
   and the old mobile rule stop applying, and a **missing** child silently shifts every later row.
   T24c and T33 exist for that pair of failure modes.
9. **The sort key now exists twice in `grouping/` (§3.1)** — the helper and five inline copies in
   `grouping/views.py`. Deliberate scope limit, recorded so the next reader does not take the
   duplication for an accident.
10. **The pupil results page links no page stylesheet (§4.2).** It loads `app.css` alone, so a rule
    written into `courses.css` — the natural home for a badge modifier, and where §5.4's modifiers
    correctly go — renders nothing there. Every §4 rule lands in `app.css`.
11. **The shared builder fixture (§2.6, §7.3).** `summarise_stored` is the single entry point for
    all ten question types' builder tests; §5.1's new argument breaks it until it is updated, and
    the failure presents as ten unrelated test failures rather than one.
