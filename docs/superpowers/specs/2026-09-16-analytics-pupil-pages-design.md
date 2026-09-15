# Analytics pupil pages — order, breakdown, per-question — design

**Status:** approved in brainstorming 2026-09-16 (three sections, each approved in turn). Not yet
spec-reviewed, not planned, not built.
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
   colours applied to the pupil's own results page too.

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
- **D4 — Outcome colours go on BOTH the teacher page and the pupil's own results page.** The badge
  markup on the two pages is a deliberate copy (PR 5 spec §5.1), and a demo rep sees the pupil page
  through the Student login.
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
notice if it silently reverted. §5.1's tests must therefore create the pinning that does not exist.

⚠️ For a demo kit this is why the matrix looks unordered: kit usernames are
`<label>-p01 … -p20` in generation order and the rep's own Student sorts last (demo spec §4.4).

### 2.2 The pieces of the wanted order already exist

- `accounts/models.py:45-55` — `User.sort_name` is `"Last First"` when both structured names
  exist, else `display_name or username`.
- `accounts/models.py:57-72` — `User.list_display_name` is `"First Last"` with the same fallback,
  appending a display name in parentheses only when it adds information not already shown.
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
- **Callers of `build_student_breakdown`:** exactly one production caller
  (`courses/views_analytics.py:268`) plus three test call sites
  (`tests/test_analytics_rollups.py:537,574,775`, `tests/test_publish_analytics.py:263`). A new
  keyword argument with a default is therefore cheap, but the tests must still be read: two of them
  assert tree shape.

### 2.4 The mode already reaches both drill-down pages

`_drill_params` (`courses/views_analytics.py:214-222`) parses `scope, mode, expand_pks,
subset_pks, values` from the querystring, and both the pupil page (`:271`) and the per-question
page (`:384`) already call it — to rebuild the *back* link only. The mode is then thrown away.
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

⚠️ `tests/test_title_math_css.py`, `tests/test_title_math_markers.py` and
`tests/test_title_math_assets.py` reach into this tree's title classes, and
`app.css:2092` names `.breakdown-unit__title` in a contrast comment. Renaming those classes is out
of scope; restyling them is in scope. Any edit that shifts line numbers must re-point the citations
that name them ([[courses-css-line-citations-are-stale]] in the owner's memory; the repo convention
is line-count-neutral comment repair).

### 2.6 The per-question page and its answer builder

- `courses/answer_summary.py` is teacher-voice by construction (PR 5 spec §4). `Part` (`:32-48`) is
  a frozen dataclass of `kind, label_is_content, label, given, expected, ok`, with a `mark`
  property deriving the ✓/✗ glyph. `_choice` (`:87-104`) joins the picked option texts into one
  string and the correct ones into another, then calls `_single` — which is precisely why the page
  shows two bare runs and never the options.
- `question.choices.all()` is already prefetched for this page
  (`courses/views.py:354`, `prefetch_related_objects(choice_qs, "choices")`), so D2 adds **no
  queries**. `tests/test_analytics_student_quiz.py:857`
  (`test_t38_query_count_does_not_grow_with_questions`) is the guard that must stay green.
- `Choice` (`courses/models.py:2447-2459`) has `text` (plain text plus KaTeX delimiters, never
  sanitised), `feedback`, `is_correct`, `order`, ordered by `("order", "pk")`.
  `ChoiceQuestionElement.multiple` (`:2279`) distinguishes single from multi-select.
- **The pupil's own results page already has the vocabulary** D2 needs:
  `ChoiceQuestionElement.MARK_GLYPHS` (`courses/models.py:2309-2313`) maps
  `correct → ("✓", "your answer, correct")`, `wrong → ("✗", "your answer, incorrect")`,
  `missed → ("＋", "correct answer, not chosen")`, and `choice_marks` (`:2315-2356`) computes them
  per option. ⚠️ **Those labels are written in the PUPIL's voice**, so the teacher page reuses the
  three *kinds* and *glyphs* but needs its own labels (§4.3). `tests/test_analytics_student_quiz.py
  ::test_t35_teacher_voice_only` is the guard.
  The matching colours already exist: `courses/static/courses/css/courses.css:377,382-386`
  (`answer-wrong` danger, mark `correct` success, `wrong` danger, `missed` warning).
- **`_answers_have_math` (`courses/views_analytics.py:346-360`) scans the unit title, each
  question, review feedback and `part.given/expected/label` — NOT option texts.** Option texts may
  carry KaTeX (`Choice.text`'s own comment says so), so D2 must extend this scan or a maths option
  renders as raw source. This is the one place where D2 can silently half-work.

### 2.7 Marks are formatted two different ways on one page

`marks_filter` (`courses/templatetags/courses_extras.py:577-589`) formats a Decimal to at most 2dp
with an ASCII dot and trims trailing zeros; the status pill instead uses `floatformat`
(`templates/courses/manage/_quiz_pill.html:7`), which localises. In Polish the same page therefore
prints a badge `0.5/1` next to a pill „0,5" — observed in the PR 5 implementation log as a
"cosmetic, inherited" note and never fixed.

- The filter is used **15 times across three templates**: `quiz_results.html`,
  `analytics_student_quiz.html`, `course_results.html` (the pupil's course-level results).
- **Four tests pin its current output**: `tests/test_quiz_scoring.py:33-45` expect `"2"`, `"1.5"`,
  `"0.67"`, `"10"`.
- ⚠️ **The CSV/XLSX export does NOT use this filter** — `courses/gradebook.py` builds cells as
  Decimals in Python (`:80-140`) — so localising the filter cannot put a decimal comma into an
  exported file, where it would break parsing. This is what makes D9's decimal comma safe.

### 2.8 The help screenshot of this page

`tests/capture_help_screenshots.py:181-187` captures the `drill-down` shot from
`manage_analytics_student` for `demo_s1`, clipped to `.breakdown__tree`; `:322` maps it to the
`drill-down` help page. Sections 5.2's visual changes therefore invalidate
`core/static/core/img/help/drill-down.{en,pl}.png`.

⚠️ **That script rewrites 26 PNGs on a local renderer and is NOT `@pytest.mark.e2e`** (demo spec
findings; the owner's memory records both). Regenerate deliberately, keep only the two drill-down
shots, and restore the rest with `git checkout -- core/static/core/img/help/`.

---

## 3. Pupil order and names

### 3.1 One ordering helper

A single function — `scoping.ordered_students(queryset)` in `courses/scoping.py`, beside the
existing pool helpers — returns a **list**:

```python
sorted(queryset, key=lambda u: (polish_sort_key(u.sort_name), u.username))
```

Both matrix builders already call `list(students)` internally
(`courses/rollups.py:753,811`), and both gradebook builders preserve the order they are handed
(`courses/gradebook.py:76,105` iterate the list; `build_matrix_table:40-48` maps matrix rows in
order), so a list is a safe substitute for the queryset at every call site.

**Call sites changed:** `views_analytics.py:107-110` (both branches) and
`views_export.py:50-54` (both branches). No other surface sorts pupils.

**Why a helper rather than four inline `sorted(...)` calls:** the matrix and the export must not be
able to drift apart — a teacher comparing the screen with the file is the case that catches a
divergence, and it is the one case nobody tests by hand.

### 3.2 One display label

`list_display_name` replaces `display_name|default:username` in:

- `templates/courses/manage/analytics_matrix.html:144` (the checkbox's `aria-label`) and `:145`
  (the row's name cell, linked and unlinked branches);
- `templates/courses/manage/analytics_student.html:9` (the breakdown heading);
- `templates/courses/manage/analytics_student_quiz.html:11` (the per-question heading, which §5.3
  restructures anyway);
- `courses/gradebook.py:42,133` (the exported `name` column, both shapes).

Unchanged by decision: the review queue and review submission screens (N2), and everything under
`grouping/`, which already uses `list_display_name`.

### 3.3 What this does not do

No index, no `db_collation`, no `Func`-based ordering in SQL. The sort is in Python over a pool
that is already fully materialised for rendering; a class is tens of pupils, and the matrix builder
lists it regardless. If a future box ever needs thousands of rows on one screen, that is a
different design.

---

## 4. The pupil results page

### 4.1 Mode reaches the tree

`build_student_breakdown(course, student, *, drafts, with_data=None, mode="progress")` gains a
keyword argument, defaulted so the four existing call sites (§2.3) keep their behaviour. The view
passes the mode it already parses (`views_analytics.py:271`).

**In `results` mode the tree is pruned** after the pill pass:

- keep every quiz unit, with its pill;
- keep a container iff it has a kept descendant;
- drop every lesson unit;
- drop `required_total` / `required_done` / `additional_done` from the kept containers' rendering
  (D7) — the values stay on the dict, the template stops reading them in this mode.

**In `progress` mode the tree is unchanged**, lessons included.

⚠️ **Pruning runs after `attach`, never before**: `_quiz_pill` is keyed off
`build_course_results`' rows, and a container dropped early would take its quiz with it.

⚠️ **A quiz with no submission keeps its `not_started` pill and stays on the page** — the gaps are
the point of the view. `_quiz_pill`'s fallback branch (`rollups.py:519`) already returns that kind
with no `submission_pk`, and `_breakdown_node.html:6` already renders an unlinked title for it.

### 4.2 What each row shows

**Both modes**
- A quiz title is a **visible link** when it has a submission: link colour plus underline, not
  `color:inherit` with a hover-only underline (§2.5). An unstarted quiz stays plain text.
- The status pill and the completion marker share **one right-hand column**, so the markers line up
  down the page instead of sitting at two different indents.
- The `Review` link for a quiz awaiting review is unchanged (`_breakdown_node.html:9-11`).

**Progress mode only**
- Every unit title uses the **normal text colour**; `is-done` no longer greys it (§2.5). A finished
  lesson is marked by its ✓ in the marker column, an unfinished one by an **empty circle** with an
  accessible name — colour is not the signal, and the marker column is never empty, so "no mark"
  cannot be confused with "not rendered".
- An **optional lesson** carries a quiet „Opcjonalne" tag (D8, §2.3), so an unfinished lesson that
  does not count toward `x/y wymagane` says so.

**Results mode only**
- Lessons are absent; chapters with no quiz are absent; chapter chips are absent (D7).

### 4.3 The heading and the view switch

- The heading names the view, reusing the matrix's own msgids: „Wyniki — Mateusz Adamczyk" or
  „Postęp — Mateusz Adamczyk" (`Results` / `Progress`, `locale/pl:2628,2633`).
- Beside it, a link to the **other** view of the same pupil: `f"{student_path}?{_expand_qs(scope,
  other_mode, expand_pks, subset_pks, values)}"`, built exactly as the matrix builds its own pair
  (§2.4). It preserves scope, expanded columns, subset and values — the same guarantee the
  „← Analityka" link already gives.
- „← Analityka" is unchanged, and the per-question page's back link already carries the mode.

---

## 5. The per-question page

### 5.1 A choice question shows every option

`_choice` (§2.6) returns, in addition to nothing else it returns today, **one part of a new kind**:

```python
Part(kind="options", label=None, label_is_content=False, given=None, expected=None, ok=None)
```

with a new field `options`: a tuple of frozen `Option(text, picked, correct, mark)` records, in
`Choice.Meta.ordering` order, where

- `picked` — the option is in `response.latest_answer`;
- `correct` — the option is in `mark_result.reveal`, and **`None` when the question is not
  auto-marked** (a REVIEW or NOT_MARKED question has no key to show);
- `mark` — `"correct"` / `"wrong"` / `"missed"` / `None`, derived by the same rule as
  `choice_marks` (§2.6) so the two pages cannot disagree: picked and in the key → correct; picked
  and not → wrong; not picked and in the key → missed; otherwise none.

`Part` gains `options` with a default of `None`, so every other builder is untouched and the
existing `mark` property is unaffected.

**Rules**
- **A picked option that no longer exists** renders as an extra row reading „(usunięta opcja)",
  reusing the existing msgid (`locale/pl:423`) that `_choice` already emits today.
- **Not answered** — every option is listed, none picked, the key still marked. The row badge stays
  „Bez odpowiedzi".
- **Not auto-marked** — options listed with picks only, no key column.
- **In progress** — the key is shown, exactly as PR 5 decided for the rest of the page (that spec's
  D5: a teacher sees the key even with attempts left).
- The old joined `given` / `expected` strings are **replaced**, not kept alongside — two renderings
  of one answer is what the page already does wrong.

### 5.2 Every other type keeps its parts, and gains labels

- A single-part type renders „Odpowiedź ucznia: …" and, only where the part is not right,
  „Poprawna odpowiedź: …" (the latter msgid exists, `locale/pl:5459`).
- A multi-part type (fill-in-the-blank, matching pairs, both grids, drag-to-image) keeps its
  per-part content label and gains **one header row per question**: „Odpowiedź ucznia" |
  „Poprawna odpowiedź" (D9).
- `Part.label_is_content` still decides `lang` tagging (PR 5 spec §5.1) — the new header row is
  interface text and carries no `lang`.

### 5.3 The header

- **Two lines, not one dash-joined title:** the pupil's `list_display_name` on a small line above,
  the quiz title as the `h1` below. Today's `"{{ unit.title }} — {{ student… }}"`
  (`analytics_student_quiz.html:11`) produced „Zbiory - quiz — Mateusz Adamczyk", two dashes of
  different meaning in one line.
- The back button sits beside the heading and does not wrap beneath a long title (the PR 5
  implementation log records the wrap).
- **The score is the page's most prominent figure** — „1 / 5 pkt · 20%" — built from the existing
  pill data (`score`, `max_score`, `percent`). The pill keeps the *state* words („przesłano",
  „w toku", „oczekuje na ocenę") and loses its duplicated score.
- An in-progress quiz keeps „Odpowiedzi: 3 z 6" (existing plural msgid, `locale/pl:6229`); an
  awaiting-review quiz keeps its „Sprawdź" link.

### 5.4 Outcome colour, on both pages

New badge modifiers, defined once in `core/static/core/css/app.css` beside `.badge--open`
(`:157`), using existing tokens (`--success`, `--warning`, `--danger` and their `-subtle` pairs,
`tokens.css:68-70,116-118`):

| outcome | badge | applies to |
|---|---|---|
| `correct` | success | both pages |
| `partial` | warning | both pages |
| `incorrect` | danger | both pages |
| `not_answered` | unchanged (muted) | both pages |
| `recorded`, `reviewed` | unchanged (neutral) | both pages |
| `review` | unchanged `.badge--review` (`courses.css:712`) | both pages |

Applied in `templates/courses/manage/analytics_student_quiz.html:46-52` and
`templates/courses/quiz_results.html:31-37` — which stay deliberate copies of one another (PR 5
spec §5.1); the modifier is added to both, and the drift note in both templates is updated to say
so.

**The question card's left edge takes the same colour** on the teacher page
(`.answers__item.is-correct` / `.is-partial` / `.is-incorrect`, classes the template already
emits at `:28` and which today have no rules at all — the PR 5 log flagged them as unstyled).
Colour is never the only signal: the badge word and the ✓/✗ glyph stay.

⚠️ **Dark mode is not free here.** `.pill--scored` hardcodes `color:#fff` on `--primary`, and
`.pill--awaiting` hardcodes `#f5b942`/`#3a2a00` (`app.css:1044-1049`) — neither follows the theme.
Both are re-expressed in tokens as part of this section, and judged in the dark screenshots.

### 5.5 Marks read the same everywhere

`marks_filter` localises its decimal separator (via `django.utils.formats.number_format`), keeping
its existing 2dp-and-trim rule. In Polish a half mark then reads „0,5" in the badge, matching the
pill's „0,5"; in English it is unchanged.

- `tests/test_quiz_scoring.py:33-45` are updated to assert per-locale output rather than the ASCII
  form (the pinned values are the specification of the old behaviour, so they must move
  deliberately, not be deleted).
- The exported file is unaffected (§2.7) and a test says so explicitly.

---

## 6. Interface text

New msgids, with the Polish for the owner to approve on the PR. Existing msgids are reused wherever
one exists — the right-hand column names them rather than re-inventing them.

| English (new) | Polski (proposed) | where |
|---|---|---|
| `Pupil's answer:` | „Odpowiedź ucznia:" | §5.2 single-part label |
| `Pupil's answer` | „Odpowiedź ucznia" | §5.2 multi-part header |
| `Pupil's choice` | „Wybór ucznia" | §5.1 option column header |
| `Correct option` | „Poprawna" | §5.1 option column header |
| `chosen, correct` | „wybrana, poprawna" | §5.1 screen-reader label |
| `chosen, incorrect` | „wybrana, niepoprawna" | §5.1 screen-reader label |
| `correct, not chosen` | „poprawna, niewybrana" | §5.1 screen-reader label |
| `%(s)s / %(m)s marks` | „%(s)s / %(m)s pkt" | §5.3 score stat |
| `Not completed` | „Nieukończone" | §4.2 empty-circle marker |

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

- **T1** Three pupils whose username order disagrees with surname order — including `Świątek`
  (after `S`, before `T`), two pupils sharing a surname with different first names, and one login
  with no first/last name — appear in the matrix in surname-then-first-name order.
  *Mutant:* restore `order_by("username")` → red.
- **T2** The same class exports in the same order, asserted on the parsed file, not the HTML.
  *Mutant:* order the export by username only → red. This is the pair T1 cannot catch alone.
- **T3** The matrix renders „Mateusz Adamczyk" (and the checkbox label names the same string);
  a no-names login falls back to its display name. *Mutant:* revert to
  `display_name|default:username` → red for the structured-name pupil.
- **T4** Non-vacuity: the fixture's username order and surname order genuinely differ, asserted
  directly, so T1/T2 cannot pass by coincidence.
- ⚠️ No assertion may rest on database ids — a pk-order coincidence is a known flake source in this
  repo (four occurrences).

### 7.2 The pupil page (§4)

- **T5** `?mode=results`: quiz titles present, **no lesson title present**, a chapter holding no
  quiz absent, an unstarted quiz present with its „nie rozpoczęto" pill.
  *Mutant:* skip the prune → red on the lesson assertion.
- **T6** `?mode=progress`: lessons present, chapter chips present — today's behaviour.
  *Mutant:* prune unconditionally → red.
- **T7** No `mode`, and `?mode=nonsense`, both render Progress. *Mutant:* default to results → red.
- **T8** Pruning keeps an ancestor chain: a quiz nested three deep still renders with its part and
  chapter above it. *Mutant:* prune containers before `attach` → red (the quiz disappears).
- **T9** The view switch link points at the same pupil with the opposite mode and preserves scope,
  expand, subset and values. *Mutant:* drop `subset_pks` from its querystring → red.
- **T10** An optional lesson carries the „Opcjonalne" tag and an obligatory one does not.
  *Mutant:* tag every lesson → red.
- **T11** A quiz with a submission renders an `<a>`; one without renders no link.
  *Mutant:* link unconditionally → red (a `not_started` pill has no `submission_pk`).
- **T12** The four existing `build_student_breakdown` call sites still pass with the default
  argument — i.e. the default really is `progress`.

### 7.3 The per-question page (§5)

- **T13** Builder, one case each: picked-and-correct, picked-and-wrong, missed, untouched,
  deleted-but-picked, not answered, not auto-marked, `multiple=True`.
  *Mutants:* invert `picked`; drop `missed`; leak the key on a non-auto question — each red on its
  own case.
- **T14** The rendered page lists **every** option of a choice question, in author order, not only
  the picked ones. *Mutant:* render only picked options → red.
- **T15** Teacher voice: the existing `test_t35_teacher_voice_only` is extended over the new
  labels — no „twoja"/"your" anywhere in the options block.
  *Mutant:* reuse `MARK_GLYPHS`' pupil-voice labels → red. (§2.6 makes this a live risk, not a
  hypothetical one.)
- **T16** A maths delimiter **in an option text** loads KaTeX. *Mutant:* leave
  `_answers_have_math` unextended → red. Without this, §5.1 ships a page that renders raw LaTeX to
  a school rep.
- **T17** `test_t38_query_count_does_not_grow_with_questions` still passes with options rendered —
  the prefetch covers them. *Mutant:* re-query `question.choices.all()` per row outside the
  prefetch → red.
- **T18** Badge modifier per outcome on **both** templates, asserted on the rendered class.
  *Mutant:* remove the modifier from one template → red (this is what stops the deliberate copy
  drifting).
- **T19** The card edge class is present per outcome. *Mutant:* drop `is-{{ row.outcome }}` → red.
- **T20** Header: the pupil's name and the quiz title are separate elements, and the rendered
  heading does not contain „ — ". *Mutant:* restore the joined title → red.
- **T21** The score stat renders „1 / 5" with its percentage; an in-progress quiz renders the
  answered-count phrase instead. *Mutant:* always render the score → red on the in-progress case.
- **T22** In Polish, a half mark renders „0,5" in the badge **and** in the score; in English,
  „0.5". *Mutant:* revert `marks_filter` to the ASCII form → red.
- **T23** The exported gradebook still writes a dot decimal (§2.7). *Mutant:* localise the export's
  numbers → red. T22 and T23 are a deliberate pair: one demands the comma, the other forbids it
  where it would corrupt a file.

### 7.4 Visual

- **T24** Screenshots, light and dark, desktop and 390px, on mat-pp data: the Results and Progress
  pupil pages, and the per-question page for a submitted quiz with a wrong choice answer (the
  owner's „Zbiory - quiz" question 1 is the reference case), an in-progress quiz, and a quiz with a
  question awaiting review. Dark is judged on its own, not as "light but darker".
- **T25** Any CSS rule this design relies on is confirmed by comparing the computed style **with
  and without** the rule, never by asserting the rule exists (repo convention: a CSS existence
  check proves nothing).
- **T26** The two help screenshots are regenerated (§2.8) and the 24 others are restored unchanged,
  asserted by `git status` being clean apart from those two files.

---

## 8. Delivery

Two PRs, in order. They are separable because §3 touches no template this design restyles.

**PR A — pupil order and names (§3).** Small, no design pass, independently useful: one helper, two
views, four templates/builders, T1–T4. It can merge while PR B is still in review.

**PR B — the two pages (§4, §5, §6).** The design pass (`frontend-design`) runs inside this PR,
after the markup exists and before the screenshots are judged. Ships new msgids; no migration, no
`FORMAT_VERSION` bump, no new dependency.

**Docs.** `docs/help/teacher/drill-down.md` and `.pl.md` describe both pages and gain: the
Results/Progress distinction, the view switch, the optional tag, and the option list. Their
„wyniki ucznia" wording (settled with #323) is kept. `docs/help/teacher/analytics.md` and `.pl.md`
gain one sentence on pupil order. The two drill-down help screenshots are regenerated (§2.8).

**Rollout.** Nothing here is gated by `LIBLI_VENDOR_INSTANCE`: these are ordinary teacher screens
on every box, including schools' real-pupil instances. The demo kit is only the reason the defects
were noticed.

---

## 9. Risks

1. **The maths-scan miss (§2.6).** The one defect that would ship silently and be seen first by a
   school rep. T16 is not optional.
2. **The deliberate template copy (§5.4).** `quiz_results.html` and `analytics_student_quiz.html`
   must stay parallel; T18 asserts both, and both templates carry the note.
3. **Decimal comma reaches a third page** — `course_results.html` (§2.7), which nothing in this
   design otherwise touches. Accepted deliberately: one rule for marks across the product beats two.
4. **Screenshot regeneration side effects (§2.8).** A careless run rewrites 26 committed PNGs on
   the local renderer. T26 pins the outcome.
5. **Line-citation rot (§2.5).** Restyling shifts `app.css` lines that three test files and one
   in-file comment name. The repair is line-count-neutral or the citations are re-pointed in the
   same commit.
