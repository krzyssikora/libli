# Per-question drill-down (demo access PR 5) — design

**Status:** approved in brainstorming 2026-09-14; spec-review 10 rounds, 72 applied, 0 disputed
(no clean verdict). Not yet planned, not yet built.
**Parent:** `docs/superpowers/specs/2026-09-12-demo-access-for-schools-design.md` (below: "the
parent"), §6 "PR 5" and §8 T30. PR 1–3 are merged (#318, #320); master `d432245a`.

**Scope:** a teacher-facing page showing one pupil's answers to one quiz — every question's
stem, what the pupil answered, the correct answer, the mark and the attempt count — reached from
the existing per-pupil breakdown, behind the same gate as the rest of analytics.

**Why it exists:** `docs/public/for-schools.md:15-16` (and `for-schools.pl.md:16-17`) claim
teacher analytics are "drillable down to one pupil and one question". No such view exists. The
page is dark today (`LIBLI_VENDOR_INSTANCE` unset on prod, measured 2026-09-12), and the flag
stays unset until this PR and then PR 4 make the claim true (parent §5 step 1, §6).

⚠️ **This is a product feature, not demo machinery.** It ships on every box, including schools'
real-pupil instances, and renders one person's answers to another. Nothing in it imports or
mentions the `demo` app.

---

## 1. Decisions

| # | Decision | Why, and what was rejected |
|---|----------|----------------------------|
| D1 | **Opens a SUBMITTED or an IN_PROGRESS submission.** No submission → 404. | A teacher watching a quiz mid-lesson is a real use, and demo kits deliberately contain in-progress quizzes (parent §4.5). Rejected: submitted only, which mirrors `_resolve_for_review` (`courses/views_review.py:39-45`) but leaves the breakdown's "in progress" pill a dead end. |
| D2 | **Lists every top-level question in the quiz**, the same row set as the pupil's results page. | The page reads as the quiz; numbering matches what the pupil saw. Review-marked rows show the answer and the review state; not-marked rows show the answer as recorded. Rejected: auto-marked only (the parent's literal wording), which leaves numbering gaps. |
| D3 | **Latest answer plus an attempt count**, not attempt history. | `QuestionResponse.latest_answer` is what was marked (`courses/models.py:3108-3143`). `Attempt` rows exist (`:3146-3166`) but no screen reads them. History is a later PR if wanted. |
| D4 | **A teacher-side answer summary** (§4): a new side-effect-free module turns `(question, response, mark_result)` into display parts; one new teacher template renders them. | §2.2: six of the ten reveal partials never show what the pupil entered, and the rest speak in the pupil's voice. Rejected: (A) re-rendering the quiz read-only through `render_element` — ten live `<form>`s posting to the pupil's `quiz_answer`, enabled inputs on an in-progress quiz, pupil-voice feedback, and a teacher flag threaded through all ten shared student templates; (C) adding the pupil's value to every `mark()` reveal payload and a voice flag to the ten `_reveal_*.html` partials — the widest blast radius, since `reveal` feeds live lesson feedback, locked quiz feedback and the results page. |
| D5 | **The correct answer is shown to the teacher even while the pupil still has attempts left.** | The withhold rule (`courses/quiz.py:12-58`) protects the pupil, not the teacher, who can read the key in the editor anyway. |
| D6 | **No catch-all fail-open.** Known content drift (§4.3) is handled explicitly and tested; anything else raises. | A blanket `except` would hide the next real bug behind "answer could not be displayed". |
| D7 | **Every failure is 404, never 403.** | The manage convention the breakdown already follows (`courses/views_analytics.py:240-242`). Satisfies the parent's T30 ("403/404"). |
| D8 | **The breakdown's quiz pill markup moves into a shared partial** used by both the breakdown and the new page's header. | The header must say exactly what the pill says (scored / submitted / awaiting review / in progress); one partial makes that structural rather than two copies kept in step by a test alone. |
| D9 | **Fix `rollups._QUESTION_MODELS`, which omits both grid types, in this PR** — replace it with `richtext.CONCRETE_QUESTION_MODELS` (§2.5). | The new page puts the header pill (from `_quiz_review_maps`) next to per-row badges (from `_results_row`, which sees every type), so a grid-only AUTO quiz would read "submitted" above scored rows and an unreviewed REVIEW choicegrid would badge "Awaiting review" under a header with no Review link. Rejected: documenting the split — it is a live bug in the matrix, breakdown, course results and gradebook maximum, not a design trade-off. ⚠️ **It changes prod analytics** for quizzes containing grids (mat-pp's published quizzes hold 2 choicegrids): see §7. Kept as its own task and commit so it can be split out if wanted. The swap also **deletes** the now-unused concrete-model imports (`rollups.py:10-22` — keep `ContentNode`, `Element`, `QuestionElement`, `QuestionResponse`, `QuizSubmission`, `UnitProgress` and any other name still used) and the stale "The 8 concrete … Mirrors courses/views.py:91-100" comment (`:25-26`); `ruff check --no-cache` confirms no F401. |

## 2. Findings that constrain the design

Each was read on 2026-09-14 at the cited line, on master `d432245a`.

### 2.1 No teacher surface shows an auto-marked answer

- `quiz_results` shows only the logged-in user's own submission
  (`courses/views.py:1728-1730`).
- The review page lists REVIEW questions only (`courses/views_review.py:76-77`).
- The breakdown shows one status pill per quiz (`templates/courses/manage/_breakdown_node.html:7-20`);
  its only link is "Review" on an awaiting-review pill (`:13-14`), built from
  `_quiz_pill`, which carries `submission_pk` for that kind alone (`courses/rollups.py:514-532`).

### 2.2 The pupil's results page is half the answer

- `_results_row(question, response)` (`courses/views.py:1772-1854`) is side-effect free and
  classifies each row: `outcome` ∈ correct / partial / incorrect / not_answered / recorded /
  reviewed / review, `earned`, `possible`, `answered`. For AUTO it also computes
  `reveal_result` — the question's own `mark()` over the stored answer, or over an empty
  `build_answer(QueryDict())` when unanswered (`:1819-1824`). §4 consumes that `reveal_result`,
  so the page marks each answer exactly once, with the same result the pupil's page uses.
- It does **not** filter status, so it runs on an IN_PROGRESS submission without error — but its
  `outcome` vocabulary is post-submit and misreports two in-progress/empty cases (§3.3's outcome
  override): an unanswered REVIEW question gets `"review"` (`:1800`), and a NOT_MARKED question
  gets `"recorded"` whenever a response row exists (`:1794`). A response row can exist with
  nothing in it: `quiz_answer` creates the `QuestionResponse` before its empty-answer check
  (`views.py:1636-1652`), leaving `attempt_count=0, latest_answer=None`.
- ⚠️ **The badge and the reveal read different sources.** `outcome`/`earned` come from the
  STORED `response.fraction` (`:1802-1813`); `reveal_result` is a FRESH `mark()` against the
  CURRENT key (`:1819-1822`). If an author edits the key after the pupil answered, the two can
  disagree — the pupil's own results page already shows that split. §4.3 accepts it.
- **The review page already has a teacher-side answer display**, `views_review._answer_display`
  (`courses/views_review.py:48-64`), for REVIEW rows only: choice → picked texts; a list →
  non-empty entries `", "`-joined; a string → stripped. The same REVIEW question therefore reads
  differently there (one flattened line) and here (per-gap parts with "Not answered", line breaks
  kept). **Accepted**: this page's parts carry labels the flat line cannot. Moving the review page
  onto `summarise` is a later PR (§3.6).
- `quiz_results.html:31-37` holds the outcome badge vocabulary and its msgids.
- ⚠️ **The reveal partials mostly show the key, not the pupil's answer:**

  | partial | shows the pupil's value? |
  |---|---|
  | `_reveal_shortnumeric.html` | no — "Expected: value ± tolerance" |
  | `_reveal_shorttext.html` | no — "Correct answer:" |
  | `_reveal_fillblank.html` | no — ✓, or ✗ + the accepted line |
  | `_reveal_dragfill.html`, `_reveal_dragimage.html`, `_reveal_matchpair.html` | no — ✓, or ✗ + the correct token; `dnd.mark_slots` stores only `accepted` (`courses/dnd.py:35-53`) |
  | `_reveal_choicegrid.html`, `_reveal_multigrid.html` | yes, as "(you chose …)" — pupil voice |
  | `_reveal_choice.html` | yes, via `choice_marks`, whose labels read "your answer, correct" (`courses/models.py:2309-2313`) |
  | `_reveal_extendedresponse.html` | keywords found, not the text |

  So the parent's "a thin template over data the drill-down already loads" does not hold, and
  its own clause applies: PR 5 gets its own design (this document).

### 2.3 A quiz cannot hold a nested question

- Turning a unit into a quiz is refused while it holds a question inside a container
  (`courses/builder.py:736-751`, `:779-789`), and pasting a question into a container in a quiz
  is refused (`question_in_quiz`, `:520-522`).
- Scoring counts top-level questions only (`courses/quiz.py:213`). The page lists top-level
  questions only, matching scoring. (`quiz_results` iterates *all* elements, `views.py:1740`;
  the difference is unreachable through the UI and deliberately not copied.)

### 2.4 Access is already built

- `scoping.can_review_course` (`grouping/scoping.py:96-102`): Platform Admin, the course owner,
  or a teacher of any non-archived group on the course. Not `is_staff`.
- `scoping.reviewable_students` (`:76-93`): PA/owner → every enrolled student; a group teacher →
  members of the non-archived groups they teach on that course.
- `analytics_student` applies both, 404 on either (`courses/views_analytics.py:232-242`).
- ⚠️ `tests/factories.py` `make_teacher` (`:266-268`) adds the Teacher permission group only —
  it does **not** set `is_staff`. A "staff user who reviews nothing" must be built explicitly.
- `get_node_or_404` with no `viewer` skips the publish check (`courses/access.py:104-142`).
  `courses/views_analytics.py` is in `AUTHOR_FACING` (`tests/test_publish_viewer_scan.py:10-17`),
  so omitting `viewer=` there is the sanctioned pattern. Drafts follow analytics' keep-with-data
  rule (`views_analytics.py:28-54`); here a submission must exist, and a submission *is* data.

### 2.5 Other facts the design leans on

- `build_quiz_context` prefetches each type's children in one query per type present
  (`courses/views.py:1327-1356`): choices, blanks, dragblanks, pairs, zones, grid
  columns/rows, multigrid `rows__correct_columns`. Every `mark()` reads only those.
  ⚠️ `build_lesson_context` holds a **line-for-line identical copy** of the same seven blocks
  (`courses/views.py:355-382`); `build_quiz_context`'s comment at `:1327` says "Mirror
  build_lesson_context". So there are already TWO copies.
- `_question_has_math` (`courses/views.py:98-130`) decides KaTeX per question.
- `answer_from_json` (`courses/quiz.py:192-198`): choice → set of pks; everything else unchanged.
  Stored shapes: choice = sorted pk list; shorttext/shortnumeric/extendedresponse = str;
  fillblank = list of str; dragfill/matchpair/dragimage = list of token str; choicegrid = list
  of column pk or `""` per row (`models.py:2760-2771`); multigrid = list of sorted pk lists
  (`:2842-2856`).
- `CONCRETE_QUESTION_MODELS` (`courses/richtext.py:26-28`) is introspected from
  `QuestionElement.__subclasses__()`, and its size is pinned by `len(...) == 10` in
  `tests/test_richtext.py:273` and `tests/test_richtext_drift.py:167`. §4.4's guard must not
  become a third count pin.
- Maths in a `[data-question]` subtree is typeset only by `question.js`'s initial pass
  (`courses/static/courses/js/question.js:40-41`); `math.js` covers `[data-katex]` and a fixed
  selector list (`math.js:39,52`), and `_katex_js.html:14-15` says `question.js` is deliberately
  NOT in that include and must follow it. `analytics_student.html` does not load it.
- `_quiz_pill` takes a `build_course_results` **row dict** (`rollups.py:514-532`); that row —
  the in_progress / awaiting_review / submitted branching and `graded = has_auto.get(...)` — is
  built inline in `build_course_results` (`rollups.py:450-493`), not by a callable helper.
- `tests/test_analytics_rollups.py` compares whole pill dicts: `{"kind": "scored", ...}`
  (`:547-552`) and `{"kind": "submitted"}` (`:576`); `:555` asserts `not_started`.
- `mark_keywords` returns keyword entries only (`courses/keywords.py:29-35`) — there is no
  model answer — and `mark_keywords("", [], [])` is `correct=True`.
- ⚠️ **`rollups._QUESTION_MODELS` (`courses/rollups.py:25-36`) lists 8 models and omits
  `ChoiceGridQuestionElement` and `MultiGridQuestionElement`** (its comment predates the grids).
  It feeds `_quiz_review_maps` (`:344-346`: `has_auto`, `total_review`, `reviewed_counts`) and
  `quiz_gradeable_max` (`:383-385`). Both grid editor forms offer every marking mode, REVIEW
  included (`element_forms.py:1009-1012`, `:1141-1144`), while `compute_scores`
  (`courses/quiz.py:201-229`) counts grids. So today a grid-only AUTO quiz pills `submitted`
  despite `max_score > 0`, an unreviewed REVIEW grid never arms the awaiting gate, and the
  gradebook maximum omits grid marks. `builder.py:744-748` already uses
  `CONCRETE_QUESTION_MODELS` for the same purpose. D9 fixes it.
- `views.py` does not import `views_analytics`, so `views_analytics` importing `_results_row`
  from `views` is cycle-free; `views_review.py:19` and `views_export.py:14-15` already import
  private helpers across view modules.
- The analytics/review templates render a person as `display_name|default:username` and
  nothing else (parent, findings); the new page does the same.

## 3. Route, access, data flow

### 3.1 URL

`manage/courses/<slug:slug>/analytics/student/<int:student_pk>/quiz/<int:node_pk>/`, name
`courses:manage_analytics_student_quiz`, view `analytics_student_quiz` in
`courses/views_analytics.py`, registered beside `manage_analytics_student`
(`courses/urls.py:339-344`).

### 3.2 Resolution order

Each step 404s on failure (D7):

1. `@login_required` — anonymous → the login redirect.
2. `course = get_object_or_404(Course, slug=slug)`; `scoping.can_review_course(user, course)`.
3. `student = scoping.reviewable_students(user, course).filter(pk=student_pk).first()` — a
   pupil out of reach and a non-existent pk are indistinguishable.
4. `unit = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)` — a node of
   another course, a lesson, or a container 404s. No `viewer=` (§2.4).
5. `submission = QuizSubmission.objects.filter(student=student, unit=unit).first()` — none → 404.
   Either status is accepted (D1).

### 3.3 Data

- `elements`: `unit.elements.filter(parent__isnull=True).order_by("order", "pk")` with
  `prefetch_related("content_object")`, keeping `QuestionElement` rows only.
- The same per-type prefetch as `build_quiz_context` (§2.5). ⚠️ **Extract it** into one helper,
  `prefetch_question_children(questions)` in `courses/views.py`, called by **all three**:
  `build_lesson_context`, `build_quiz_context` and the new view — prefetching exactly what both
  copies do **plus `media` for dragimage** (§5.1; the new page's stage reads it, and the lesson
  and quiz element templates already dereference `el.media.file.url`, so for them this turns N
  queries into 1 — the plan re-checks any pinned query budget for those pages) — replacing both existing copies
  rather than adding a third. Copies drift exactly the way the lock rule did
  (`courses/quiz.py:94-116`). The lesson and quiz context tests are the regression guard for the
  two replaced copies.
- `responses = {r.element_id: r for r in submission.responses.all()}`.
- Per question: `row = _results_row(q, responses.get(el.pk))`, then
  `row["parts"] = summarise(q, row["response"], row["reveal_result"])` (§4),
  `row["qnum"]` (1-based over listed questions), and for **every** question (any marking mode)
  with `response.attempt_count > 0`, `attempt_count` and `max_attempts` — `quiz_answer` counts and
  enforces attempts for every mode (`views.py:1639-1643`, `:1667`), so a REVIEW essay locked after
  its one attempt says so too.
- **Outcome override** (§2.2), applied by the new view to `row["outcome"]` after `_results_row`,
  never inside it (the pupil's page is out of scope, §3.6):
  - NOT_MARKED with `row["answered"]` false → `"not_answered"` (any status);
  - REVIEW with `row["answered"]` false on an **IN_PROGRESS** submission → `"not_answered"`.
    On a SUBMITTED one it stays `"review"`: an unanswered REVIEW question genuinely blocks the
    score (`rollups.py:402-409`) and appears in the review page.
  - REVIEW with `row["answered"]` true on an **IN_PROGRESS** submission → `"recorded"` ("Answer
    recorded"): nobody can review it until the submission is finished (by the pupil, or by a
    teacher's force-submit from the review queue), because the review page opens
    SUBMITTED work only (`views_review.py:39-45`), so "Awaiting review" would promise an action
    that does not exist yet.
  - AUTO with `row["answered"]` true **and `response.fraction is None`** → `"recorded"`. This is a
    question answered while REVIEW/NOT_MARKED, **never reviewed**, and switched to AUTO
    afterwards (§4.3; a reviewed one has a `fraction`, set by `review.review_response`):
    `_results_row` badges it `"not_answered"` (`views.py:1802-1804`) while its parts show the
    pupil's answer freshly marked, and *k* counts it answered. "Answer recorded" is true of both.
  - Otherwise AUTO is unaffected (`_results_row` keys it on `fraction`).

### 3.4 The header

- Title: `{{ unit.title }} — {{ student.display_name|default:student.username }}`.
- **Status:** the pill (D8), computed by the breakdown's own code, not a re-derivation. The
  per-unit row construction inside `build_course_results` (`rollups.py:450-493`) is **extracted**
  into `_course_results_row(unit, sub, has_auto, total_review, reviewed_counts)`, which
  `build_course_results` then calls in its loop (behaviour unchanged). ⚠️ `course_results`'s
  comment (`courses/views.py:704-708`) justifies a double iteration by "build_course_results
  builds "rows" with three rows.append calls", which stops being true: reword it in the same
  commit. (Keeping that one edit line-neutral does **not** protect other citations: the prefetch
  extraction and D9 shift `views.py`/`rollups.py` lines anyway — §7's citation sweep.) The new view calls
  `_quiz_review_maps([unit.pk], [submission])`, then `_course_results_row(...)`, then
  `_quiz_pill(row)` (§2.5). Kinds and what each shows:
  - `scored` — "scored s/m (p%)", as in the breakdown;
  - `submitted` — submitted, and either the quiz has no AUTO question (of **any** of the ten
    types, after D9) or `max_score` is falsy (`rollups.py:518`) — e.g. a fully reviewed
    REVIEW-only quiz;
  - `awaiting` — "awaiting review" **plus the existing "Review" link** to
    `courses:manage_review_submission`;
  - `in_progress` — "in progress" plus "*k* of *n* questions answered", where *n* is the
    number of listed questions and *k* counts rows with `answered` true. No score: nothing is
    cached before finish (`courses/quiz.py:232-246`).
- **A quiz with no questions** (`n == 0`) is reachable: `build_quiz_context` creates an
  IN_PROGRESS submission as soon as an enrolled pupil opens any quiz (`views.py:1364`). The page
  then omits the "*k* of *n*" count and renders one muted line, "This quiz has no questions."
  (new msgid), in place of the empty list.
- **Back link:** "← Breakdown" to `courses:manage_analytics_student` for this pupil, carrying the
  incoming `scope`/`mode`/`expand`/`student`/`values` querystring through `_expand_qs`
  (`courses/views_analytics.py:184-198`) — so the breakdown's own "← Analytics" still restores
  the matrix. The **parse** half (the `mode`/`values` whitelisting plus `_clean_expand` on
  `expand` and `student`) lives inline in `analytics_student` (`views_analytics.py:247-251`);
  extract it into `_drill_params(request) -> (scope, mode, expand_pks, subset_pks, values)` and
  call it from `analytics_student` and the new view, rather than adding a third inline copy.
  (`analytics_matrix`'s parse differs — it has `scope_rendered` — and is left alone.)

### 3.5 Entry points from the breakdown

- `_quiz_pill` returns `submission_pk` for **every** kind that has a submission (scored,
  submitted, awaiting, in_progress); `not_started` stays without one.
- `_breakdown_node.html` renders the quiz title as a link to the new page whenever the pill has
  a `submission_pk`, carrying the breakdown's querystring; `not_started` stays plain text.
  **Markup is pinned:** the existing `<span class="breakdown-unit__title" lang="…"
  data-math-title>` stays the direct child of `div.breakdown-unit` on **both** branches and keeps
  both attributes; on the link branch the title text sits in an
  `<a class="breakdown-unit__link" href="…">` **inside** that span. So
  `tests/test_title_math_markers.py:441-443`'s selector
  (`div.breakdown-unit:has(.pill) > span.breakdown-unit__title`), the `.breakdown-unit__title`
  CSS (`app.css:1012`) and `tests/capture_title_math_screenshots.py:631` keep matching. The
  pill itself renders from the shared partial (D8). The existing "Review" link stays.
- **The shared partial** is `templates/courses/manage/_quiz_pill.html`, taking `p` (the pill
  dict). It contains exactly the five pill `<span>`s of `_breakdown_node.html:8-19` (scored,
  submitted, awaiting, in_progress, not_started) and **not** the "Review" link: each caller
  renders the link itself after the include when `p.kind == "awaiting"`, so neither page shows
  it twice.
- `analytics_student` passes its querystring to the template so the link can carry it (it
  already builds `back_qs`, `views_analytics.py:247-253`).

### 3.6 Out of scope

Attempt history (D3); a per-question view across all pupils (item analysis); any change to the
review page or the pupil's results page; the author's explanation (pupil-facing); anything in
the `demo` app; the `/for-schools/` copy (PR 4); a force-submit action on this page (force-submit
stays in the review queue); replacing the review page's `_answer_display` with `summarise` (§2.2).

## 4. The answer summary — `courses/answer_summary.py`

### 4.1 Contract

```python
@dataclass(frozen=True)
class Part:
    kind: str              # "answer" | "keyword"
    label: str | None      # None for single-part types
    given: str | None      # "answer" parts: the pupil's value; None = left empty
    expected: str | None   # the correct answer as display text
    ok: bool | None        # None = not judged

def summarise(question, response, mark_result) -> list[Part]
```

- Side-effect free: no writes, no RNG. Reads only rows `build_quiz_context`'s prefetch loads.
- `mark_result` is `_results_row`'s `reveal_result`: the `MarkResult` for AUTO questions, `None`
  otherwise. **`ok` is always read from it, never re-derived.**
- Dispatch: a module-level registry dict keyed on the model **class**, one adapter per concrete
  question type. A type missing from the registry raises `KeyError` (D6; §4.4 keeps it
  unreachable).
- Display strings (`"Gap 2"`, `"(removed option)"`) are translated at call time with `gettext`
  — `summarise` runs inside the request.

### 4.2 Shared rules

1. **`expected` and `ok` exist only for AUTO questions.** For REVIEW and NOT_MARKED every part has
   `expected=None, ok=None`; only `given` is filled.
2. **`expected` is emitted only on a part whose `ok` is not `True`.** A correct part shows the
   pupil's value and a ✓ only.
3. **Unanswered** (`response is None` or `latest_answer is None`): every `"answer"` part has
   `given=None`; for AUTO, `ok=False` and `expected` filled from the empty-answer `mark_result` —
   **`ok=False` wins even when that `mark_result.correct` is `True`** (an unanswered question is
   never shown ✓; `mark_keywords("", [], [])` is the reachable case, §2.5). `"keyword"` parts
   follow the per-type table instead (`ok=None` when unanswered).
4. On an `"answer"` part, `given=None` also means "this part left empty" inside an answered
   question (an empty gap, an unselected grid row, an empty drop slot). **A string part is empty
   iff `not (v or "").strip()`** — a gap stored as `"  "` is `None`, not an invisible value.
5. **`"keyword"` parts never carry a pupil value.** `given` and `expected` are always `None`; the
   template renders only the label and the ✓/✗ glyph for them, and never "Not answered" (§5.1).

### 4.3 Per type

| type | parts | `given` | `expected` | `ok` source |
|---|---|---|---|---|
| choice (single or multiple) | 1, no label | picked option texts in option `(order, pk)` order, `", "`-joined; one `"(removed option)"` per stored pk no longer among the choices, **appended after** the live option texts | correct option texts, same order; **`"(none)"`** (new msgid) when the correct set is empty | `mark_result.correct` |
| shorttext | 1 | the stored string | `mark_result.reveal` (first accepted line) | `.correct` |
| shortnumeric | 1 | the stored string | `reveal["value"]`, plus `" ± " + reveal["tolerance"]` when tolerance is non-empty | `.correct` |
| extendedresponse | 1 `"answer"` part for the text (`label=None`, `expected=None` **always** — there is no model answer, §2.5), then one `"keyword"` part per keyword in `reveal` order | the text, line breaks preserved | `None` on every part. Keyword label = `gettext("Required") + ": " + kw` / `gettext("Avoid") + ": " + kw`, reusing the existing bare msgids exactly as `_reveal_extendedresponse.html:8,13` joins them | text part: `.correct` when answered, `False` when unanswered (rule 3); keyword part: `found` for Required, `not found` for Avoid — **`None` on every keyword part when unanswered**, as `_reveal_extendedresponse.html:18-28` does |
| fillblank | one per blank, `"Gap i"` | the typed value, or `None` if empty | `reveal[i]["accepted"]` | `reveal[i]["correct"]` |
| dragfill | one per gap, `"Gap i"` | the chosen token, or `None` | `reveal[i]["accepted"]` | `reveal[i]["correct"]` |
| dragimage | one per zone, `"Zone i"` | the chosen label, or `None` | `reveal[i]["accepted"]` | `reveal[i]["correct"]` |
| matchpair | one per pair, label = `pairs[i].left` | the chosen token, or `None` | the pair's `right` (`reveal[i]["accepted"]`) | `reveal[i]["correct"]` |
| choicegrid | one per row, label = statement | the chosen column's label; `None` for `""`; `"(removed option)"` for a pk not among the columns | `reveal[i]["correct_label"]` | `reveal[i]["is_correct"]` |
| multigrid | one per row, label = statement | chosen column labels, `", "`-joined; `"(removed option)"` appended once per stored pk not among the columns; `None` for an empty set | `reveal[i]["correct_labels"]` joined; **`"(none)"`** when that row's correct set is empty | `reveal[i]["is_correct"]` |

`i` in a label is 1-based. For REVIEW/NOT_MARKED questions the same `"answer"` parts are built
from the stored answer and the current rows alone (no `mark_result`), so rule 1 holds.
⚠️ **Labels and part counts always come from the question's current CHILD ROWS, in every mode** —
`blanks`, `dragblanks`, `zones`, `pairs[i].left`, `rows[i].statement` — never from `reveal`, which
a REVIEW/NOT_MARKED question does not have (`mark_result is None`; `reveal[i]["left"]` would raise
`TypeError`). `reveal[i]` is read **only** for `expected` and `ok`, on AUTO questions. The table's
`reveal[i]["statement"]`-style cells above name the same values the child rows hold.
⚠️ **`"keyword"` parts are emitted for AUTO only.** The editor form checks keywords only for AUTO
(`element_forms.py:1367-1391`), so a question switched to REVIEW keeps stale
`required_keywords`/`forbidden_keywords` in the database; a REVIEW or NOT_MARKED extendedresponse
yields exactly one `"answer"` part and never bare keyword labels implying marking that never ran.

⚠️ **Content edited after the answer** (the known drift, handled explicitly — D6):

- **Part count follows the question's current rows.** The stored list is padded with "empty" or
  truncated to that count, exactly as each `mark()` pads (`models.py:2600`, `:2776`, `:2861`;
  `dnd.py:45`), so parts and `reveal` entries always align by index. ⚠️ Index alignment is not
  semantic correctness: stored answers are positional, so deleting a **middle** row, blank, gap
  or pair shifts every later stored value onto the next label, and the page shows it under a
  statement the pupil never answered. `mark()` and the pupil's page misattribute identically;
  **accepted, not reconciled**.
- **`max_attempts` lowered after the answer** (e.g. 3 attempts used, now `max_attempts=1`): the
  attempt line shows "attempt *n*" without "of *max*" whenever `n > max_attempts`, never
  "attempt 3 of 1" (§5.1).
- **Marking mode changed after the answer.**
  - → AUTO, **never reviewed**: `fraction` is `None`, handled by §3.3's override (`"recorded"`),
    parts marked fresh.
  - → AUTO, **after a review**: `review.review_response` (`courses/review.py:43-53`) set `fraction`
    and `earned_marks` — and creates the row even for an unanswered REVIEW question
    (`latest_answer=None`). The override does not fire; the badge comes from the teacher's review
    mark (e.g. "Correct (1/1)") while the parts show a fresh `mark()` — or "Not answered" ✗ when
    it was never answered. **Accepted**, the same split the pupil's page shows.
  - AUTO → REVIEW/NOT_MARKED: `_results_row` keys on the CURRENT mode and ignores the stale
    `fraction`; parts are `given`-only by rule 1.
- **Header pill vs a row, after a mode switch.** `reviewed_counts` counts every reviewed response
  on a question element whatever its CURRENT mode (`rollups.py:361-369`), so a quiz with REVIEW
  Q1 reviewed then switched to AUTO and REVIEW Q2 still unreviewed pills `scored` (1 of 1
  "reviewed") with no header Review link, while Q2's row badges "Awaiting review" with its own
  link. **Accepted** — the mismatch predates PR 5 in the breakdown, and the per-row link keeps Q2
  reviewable; scoping `reviewed_counts` to current-REVIEW elements is a rollup change for another
  PR.
- **An answered question whose every row/blank/pair/zone was deleted** yields **zero** parts. The
  template then renders one muted line, "(this question no longer has any parts)" (new msgid,
  §5.4), so the pupil's answer is never silently absent.
- **A removed choice or column pk** displays as `"(removed option)"` — never silently dropped.
  ⚠️ For choicegrid, `reveal[i]["chosen_label"]` is `None` both for `""` and for a removed pk
  (`models.py:2789`), so `given` must be computed from the **stored** value, not from `reveal`.
  For multigrid, `reveal[i]["chosen_labels"]` silently omits removed pks (`:2876`) — same rule.
- **The answer KEY edited after the answer** (an accepted line, a numeric value, a choice's
  `is_correct`, a grid's correct column) is **accepted and not reconciled**: the badge keeps the
  stored-fraction outcome while the parts show the fresh `mark()` against the current key, so a
  row can read "Correct (1/1)" beside a ✗ part. This is exactly the split the pupil's own
  results page already shows (§2.2); making the teacher page disagree with the pupil's page
  would be worse. T33 pins it so a later change is deliberate.
- **A stored value of the wrong JSON shape for its type** (a hand-edited row) is **not** handled.
  `mark()` itself misreads it on the pupil's results page too; this page inherits that and raises
  or misdisplays rather than masking it.

### 4.4 Drift guard

A test derives the set of concrete question models —
`{m for m in apps.get_models() if issubclass(m, QuestionElement)}` (`get_models()` returns no
abstract model) — and asserts it **equals** the registry's key set. No count is pinned. An
eleventh question type fails the test until its adapter exists.

## 5. The page

### 5.1 Template

`templates/courses/manage/analytics_student_quiz.html`, extending `base.html`, inside
`<section class="manage answers">` (the breakdown's shell, `analytics_student.html:6-17`).

- `head_title`: "Answers · *course title* · libli" (new msgid "Answers").
- `manage__head`: the §3.4 title (`data-math-title`, `lang="{{ course.language }}"` on the unit
  title) and the "← Breakdown" ghost button (existing msgid "Breakdown").
- The status line: the shared pill partial (D8), plus the in-progress count or the Review link.
- `<ol class="answers__list">`, one `<li class="answers__item is-{{ row.outcome }}" data-question>`
  per row:
  - the question number, and the stem with `|safe` (sanitised on save,
    `courses/models.py:2198-2201`), inside `lang="{{ course.language }}"`.
    ⚠️ **fillblank and dragfill store a TOKEN stem**, not prose: `fillblank.parse` replaces each
    `{{…}}` marker with `U+FFFF n U+FFFF`, `n` 0-based (`courses/fillblank.py:17-19,65`), and
    dragfill reuses it. Rendered raw, the teacher sees replacement glyphs and bare 0-based digits
    beside "Gap 1" labels. So for those two types the stem goes through
    `answer_summary.gap_marked_stem(question)`, which substitutes each token (with the module's
    own token regex, the one `fillblank.py` defines) for `<span class="answers__gap">[n+1]</span>`
    — numbered exactly like the part labels — and returns a `SafeString`; the inserted markup is
    digits only. A template cannot call a function with an argument, so **the view sets one row
    key, `row["stem_html"]`**: `gap_marked_stem(q)` for fillblank/dragfill, `mark_safe(q.stem)` for
    every other type. The template renders only `{{ row.stem_html }}` — no per-type branch in the
    template;
  - **for a dragimage question, its image with static numbered zone badges**, after the stem (which
    is optional for this type, so without the image a prompt-less question shows nothing of what
    was asked). Markup — a **reduced** version of the static stage in
    `dragtoimagequestionelement.html:31-38`, not a verbatim copy:
    `<div class="dragimage__stage">` holding `<img class="dragimage__img"
    src="{{ row.question.media.file.url }}" alt="{{ row.question.alt }}">` and, per zone,
    `<span class="dragimage__badge" style="left:{% widthratio z.x 1 100 %}%; top:{% widthratio z.y 1 100 %}%;">{{ forloop.counter }}</span>`.
    **Dropped** from the source: `data-dnd`, `data-dragimage-stage`, `data-zone`, the
    `data-x/y/w/h="{{ …|unlocalize }}"` attributes (they exist for `dnd.js`, and `|unlocalize` would
    need `{% load l10n %}`) and the `{# unlocalize … (see above) #}` comment, which points at text not
    in the new file; also the select lists, pool and form. Nothing is interactive and no JS runs.
    Badge numbers equal the "Zone i" part labels. A deliberate reduced copy (the element template is
    a student surface, §3.6). `zones` is already
    prefetched, but ⚠️ **`media` is a foreign key** (`models.py:2930-2932`) that neither existing
    prefetch copy loads (`views.py:1349-1350` prefetches `"zones"` only), so
    `prefetch_question_children` prefetches `"zones", "media"` for dragimage questions (§3.3);
  - the outcome badge, **a deliberate copy of `quiz_results.html:31-37`'s markup and msgids**
    (Correct, Partial, Incorrect, Not answered, Answer recorded, Reviewed, Awaiting review).
    Accepted as a copy: extracting a partial would change the pupil's results page, which §3.6
    keeps out of scope. It uses the `marks` filter, so the template loads `courses_extras`;
  - a per-row "Review" link to the review page **iff `row.outcome == "review"`** (after the §3.3
    override, that is only on a SUBMITTED submission); an already-reviewed row gets no link.
    Several rows can link to the same URL, so each per-row link carries sr-only
    "question %(n)s" (new msgid) in its accessible name, telling screen-reader link lists apart;
  - the teacher's `review_feedback` on **any** row where it is non-empty, whatever the outcome —
    the pupil's page's own condition (`quiz_results.html:38-42`), so feedback on a question later
    switched out of REVIEW still shows — autoescaped;
  - the parts: one `<div class="answers__part answers__part--{{ part.kind }}">` each — the label
    if any; for an `"answer"` part, `given`, or muted "Not answered" (existing msgid) when `None`
    (a `"keyword"` part renders no given/not-answered text at all, §4.2 rule 5); a ✓/✗ glyph when
    `ok` is not `None` — **except that an `"answer"` part with `given is None` never shows ✓**
    (it shows "Not answered", and ✗ when `ok` is `False`), so an empty part scoring `ok=True`
    (e.g. a multigrid row with an empty correct set left empty) never reads "Not answered ✓" —
    `aria-hidden`, followed by sr-only "Correct" / "Incorrect" — **the glyph and its sr-only label
    are ONE unit, rendered or suppressed together**, so a screen reader never hears "Correct" where
    no ✓ is shown (existing msgids, **teacher voice
    — never "your answer"**); then "Correct answer:" (existing msgid) + `expected` **iff
    `expected` is truthy** (an empty-string reveal, e.g. shorttext with no accepted lines,
    `models.py:2492`, renders no hint rather than a dangling label).
    `given` for extendedresponse keeps line breaks (`white-space: pre-wrap`); an empty part list
    renders the muted "(this question no longer has any parts)" line instead (§4.3);
  - for every row with `attempt_count > 0` (any marking mode, §3.3), "attempt *n* of *max*", or
    "attempt *n*" when `max_attempts` is null (unlimited) **or `n > max_attempts`** (§4.3).
- All pupil-entered and author-entered text is autoescaped (`given`, labels, `expected`); only the
  stem is `|safe`, as on the pupil's page.

### 5.2 Maths

`has_math` = `titles_have_math([unit.title])` or any `_question_has_math(q)` or any
`has_math_delimiters(row["review_feedback"])` (rendered inside the typeset `li[data-question]`,
§5.1) or any
`has_math_delimiters` over each part's `given`, `expected` and `label` (a pupil can type
`\(x\)` into a short-text answer). When true, include `courses/_katex_css.html` and
`courses/_katex_js.html`, as `analytics_student.html:4,19` does, **then
`<script src="{% static 'courses/js/question.js' %}" defer></script>` after that include**, and
mark each item `data-question` — exactly `quiz_results.html:28,62-69`. Without `question.js` the
`data-question` subtrees are never typeset (§2.5) and stems/answers show raw `\(x\)`. Its form
wiring is a no-op here: the page has no `<form>`. ⚠️ `_katex_js.html:14-15`'s comment says
"question.js is deliberately NOT here: only two pages need it" — already stale: three templates
load it today (`lesson_unit.html:75`, `quiz_results.html:69`, `manage/review_submission.html:138`),
and this page is the **fourth**. Reword it in the same commit, **line-count neutral**, to something
true of all four — `lesson_unit.html` has live forms, so not "form-less" — e.g. "only pages with
`[data-question]` subtrees need it, and it must come AFTER this include".

### 5.3 Styling

- Load `courses/css/courses.css` for the stem's rich-text prose (as `quiz_results.html:5`).
- ⚠️ **Code never cites a stylesheet by line.** `tests/test_css_citations_are_durable.py:49-73`
  fails on any `<name>.css:<digits>` in a `.css`, `.py`, `.js` or `.html` file. This spec's
  `courses.css:N`/`app.css:N` references are for the reader only; a rule comment, template comment
  or test docstring cites by **selector** ("as `.quiz-results__list` does in courses.css").
- **`.breakdown-unit__link`** gets its own rule: `color: inherit; text-decoration: none`, underline
  on `:hover`/`:focus-visible` — the title keeps its current look and still reads as a link on
  interaction, rather than silently taking default link styling.
- **Muted texts** — "Not answered", "(this question no longer has any parts)", "This quiz has no
  questions." — use `--text-secondary`, **never** `--text-tertiary`, which fails AA at body size
  (memory: text-tertiary-fails-aa-at-body-size) and is what the copied `.badge--muted`
  (`courses.css:716`) uses. The badge itself stays as copied.
- **The question number is the visible `row.qnum`, not the list marker:** `.answers__list` sets
  `list-style: none` (as `.quiz-results__list` does, `courses.css:724`), so no item reads "1. 1".
- New `answers__*` rules in `core/static/core/css/app.css`, next to the breakdown block
  (`:1007-1013`), tokens only. Parts stack to one column below 640px; a long grid statement
  wraps rather than scrolling.
- ⚠️ A CSS comment naming class stems gets the `*/`-early-terminator check (memory:
  css-comment-early-terminator-eats-next-rule).

### 5.4 i18n

New msgids, each filled in Polish by hand (expected set; the plan confirms each is new by grep):
"Answers", "Gap %(n)s", "Zone %(n)s", "question %(n)s", "(removed option)",
"(this question no longer has any parts)", "(none)", "This quiz has no questions.",
"attempt %(n)s of %(max)s",
"attempt %(n)s", and an `ngettext` pair "%(k)s of %(n)s question answered" /
"%(k)s of %(n)s questions answered" — **the plural count argument is `n`** (the noun agrees with
the total: "1 of 3 questions", "1 z 5 pytań"), never `k`; the Polish three forms follow `n`. After `makemessages`, check
for fuzzy pre-fills (memory: makemessages-fuzzy-prefills-wrong-translation) and recompile the
`.mo`.

### 5.5 Help and docs

- `docs/help/teacher/drill-down.md` + `.pl.md`: a "Per-question answers" section after
  "Per-student breakdown" — click a quiz title in the breakdown to see each question, what the
  pupil answered, the correct answer and the marks; an in-progress quiz shows the answers so far;
  "← Breakdown" returns. **No new screenshot**: `tests/capture_help_screenshots.py` rewrites 26
  committed PNGs on this machine's renderer. ⚠️ The existing `drill-down.en.png`/`.pl.png`
  (`drill-down.md:11`) show the breakdown before quiz titles became links; that staleness is
  **accepted** — the difference is link styling on titles, and the next deliberate screenshot
  regeneration picks it up.
- The parent's §6 "PR 5" paragraph gains a one-line pointer to this spec. `/for-schools/` is
  untouched (PR 4).

## 6. Tests

Every rule-bearing test names the mutant that must turn it red; the plan's Falsify steps run each
mutant and observe the failure before reverting by hand.

⚠️ Fixtures create rows in several models with independent pk sequences. Assert on the element's
`data-question`/`qnum` position or on `Element.pk`, **never** on another model's pk or on a pk
substring (memory: independent-pk-sequences-make-substring-assertions-flaky).

⚠️ **Every pupil viewed by a Platform Admin or course owner needs an `Enrollment` row** for the
course, in addition to any group membership: `reviewable_students` serves PA/owner from
`Enrollment` alone (`grouping/scoping.py:84-86`), and `GroupMembershipFactory`
(`tests/factories.py:495-500`) creates none — no signal does either. Without it a correct build
404s every PA/owner fixture (T30, T35–T39, T41), and the red invites weakening the assertion.

Scope content
assertions to the item or header element, not the whole page: the `manage__head` title holds
both the quiz title and the pupil's name, and question stems or answers can repeat those
strings. (`head_title` is "Answers · *course title* · libli" and carries neither.)

- **T30 Access (parent §8 — PR 5 does not merge without it).** One fixture: a course with two
  non-archived groups, each with one pupil holding a SUBMITTED submission on the same published
  quiz. Each viewer gets its own request for pupil A's page:

  | viewer | expected |
  |---|---|
  | Platform Admin | 200 |
  | course owner (**non-staff**, asserted up front) | 200 |
  | teacher of pupil A's group (`make_teacher`, **non-staff**) | 200 |
  | teacher of pupil B's group only | 404 |
  | teacher of pupil B's (active) group **and** of an **archived** group that contains pupil A | 404 |
  | a user with `is_staff=True` **and** the Teacher group who teaches no group on the course (assert `is_staff` up front — `make_teacher` does not set it, §2.4) | 404 |
  | pupil A themself | 404 |
  | anonymous | 302 to login |

  The test asserts every row's expected status on the **unmutated** build first — in particular
  the PA and owner rows are 200, which needs both pupils enrolled (§6 preamble) — so a mutant's
  200 → 404 is a real flip and not a fixture that was 404 all along.
  Mutants, each with the rows it turns red:
  - gate step 2 on `request.user.is_staff` instead of `can_review_course` → the **non-staff group
    teacher**, **owner** and **Platform Admin** rows go 200 → 404 (`make_pa` adds the permission
    group only and never sets `is_staff`, `tests/factories.py:256-258`) (the staff row stays 404: step 3 still finds no
    reviewable pupil for it);
  - replace step 3's `reviewable_students(...)` with an unscoped `User` lookup → the
    **other-group teacher** row **and** the **archived-group teacher** row go 404 → 200 (the latter
    also teaches an active group, so step 2 passes and the unscoped lookup finds pupil A);
  - resolve step 3 through `GroupMembership` of the teacher's groups **without the archived
    filter** → the **archived-group** row goes 404 → 200. (That teacher also teaches an active
    group on the course, so step 2 passes and only step 3's archived filter decides it.)
  - `can_review_course(...) or user.is_staff` at step 2 **combined with** the unscoped step 3 →
    the **staff** row goes 404 → 200. This is the only mutant the staff row catches on its own;
    alone it guards the resolution as a whole, not step 2.
- **T31 Resolution.** Against the owner, each case changes exactly one path segment of a URL
  asserted 200 in the same test. ⚠️ Step 5 404s any node the pupil has no submission on, which
  would hide step 4's checks — so the fixture **creates a `QuizSubmission` for the same pupil on
  the lesson unit and on the other course's quiz** directly (`QuizSubmission.unit` is limited
  only to `kind="unit"`, `models.py:3067-3071`; no enrolment is needed to create the row), making
  `require_quiz` and `get_node_or_404`'s slug check the only things that 404 them:
  - a quiz node of another course (pupil has a submission on it) → 404;
  - a lesson node of the same course (pupil has a submission on it) → 404;
  - a non-existent pupil pk → 404;
  - a pupil enrolled with no submission on this quiz → 404.

  Mutants: drop `require_quiz=True` (the lesson case goes red); in the view, resolve the node
  with `ContentNode.objects.filter(pk=node_pk, kind="unit", unit_type="quiz")` instead of
  `get_node_or_404(node_pk, slug, ...)`, bypassing the slug check (the other-course case goes
  red); treat a missing submission as an empty page (the no-submission case goes red).
- **T31b Draft quiz, group teacher.** A separate sub-case with its own viewer: the pupil's
  **group teacher** opens a **draft** quiz the pupil has a submission on → 200. Mutant: add
  `viewer=request.user` to `get_node_or_404` (a group teacher cannot see drafts → 404).
- **T32 Answer summary, per type.** For each of the ten types, pure calls to `summarise` asserting
  the exact `Part` list for: correct; wrong; partial where the type has one (fillblank, dragfill,
  dragimage, matchpair, choicegrid, multigrid, **extendedresponse** — two required keywords, one
  found: `fraction` 0.5, text part `ok is False` beside one ✓ and one ✗ keyword part; mutant:
  read the text part's `ok` as `fraction > 0`); unanswered (AUTO); and the same answer on a
  REVIEW-mode copy (all `expected`/`ok` `None`), **including a REVIEW matchpair and a REVIEW
  choicegrid**, whose labels must come from the child rows (mutant: read labels from `reveal`,
  which raises on the REVIEW path). Choice covers single and multiple. A choice with
  **no correct option** answered with a pick, and a multigrid row with an **empty correct set**
  answered with a column, have `ok is False` and `expected == "(none)"` (mutant: leave `expected`
  as the empty join, which then renders a bare ✗).
  extendedresponse covers: its REVIEW-mode copy **keeps non-empty keywords on the question** and
  yields exactly one `"answer"` part (mutant: emit keyword parts regardless of mode);
  `"keyword"` parts with `given`/`expected` `None`; unanswered keyword
  parts `ok is None`; an unanswered AUTO extendedresponse with **no keywords** has text-part
  `ok is False` (rule 3 over `mark_keywords("", [], [])`'s `correct=True`); and, through the
  view, the rendered keyword part of an **answered** extendedresponse does **not** contain
  "Not answered" (mutant: render keyword parts through the `"answer"` branch).
  Mutants: emit `expected` on a correct part; compute `ok` by comparing `given` to `expected`
  instead of reading `mark_result` (goes red on a numeric answer `"0,5"` against `"1/2"`, which
  `mark()` accepts); fill `expected` on a REVIEW row.
- **T33 Content drift.** fillblank with fewer and with more stored values than current blanks;
  a choice answer holding a deleted choice's pk; a choicegrid row holding a deleted column's pk
  (`given == "(removed option)"`, not `None`); a multigrid row holding one live and one deleted
  pk. Plus **key edited after answering** (§4.3): a shortnumeric response stored at
  `fraction=1` whose `value` is then changed renders the "Correct" badge **and** a ✗ part with the
  new expected value — pinning the accepted split. Plus **mode switched to AUTO after
  answering**: a shorttext response with `latest_answer` set and `fraction=None` on a question
  now AUTO badges "Answer recorded" (not "Not answered") and its part shows `given` with ✓/✗ from
  the fresh mark; on an IN_PROGRESS submission it counts toward *k*. Plus **reviewed, then
  switched to AUTO**: an answered REVIEW shorttext reviewed at full marks then made AUTO badges
  "Correct" (from the stored review `fraction`) with parts from the fresh mark; and an
  **unanswered** REVIEW question reviewed at 0 then made AUTO (`latest_answer=None`, `fraction`
  0) badges "Incorrect" with a "Not answered" ✗ part — both pinning the accepted split. Plus
  **whitespace gap**: an answered fillblank whose second gap is stored as `"  "` has that part's
  `given is None` (mutant: test `v == ""` instead of stripping). Plus
  **zero parts**: an answered fillblank whose blanks were all deleted renders the
  "(this question no longer has any parts)" line (mutant: render nothing for an empty part
  list). Mutants: drop the
  AUTO-`fraction is None` override arm (the badge reads "Not answered" and goes red); skip the padding (IndexError or
  misaligned parts); read choicegrid `given` from `reveal["chosen_label"]` (the removed pk shows
  as not answered); read part `ok` from the stored fraction (the key-edit case goes red).
- **T34 Drift guard** (§4.4). Falsified twice: delete one registry entry; and, separately, grow the
  derived set with `mock.patch.object(apps, "get_models", ...)` returning the real models plus a
  stub subclass. **The stub is ABSTRACT** — declared inside the test function body with
  `class Meta: abstract = True` (an abstract model needs no `app_label` and never registers).
  `get_models()` would never return it, so the patch is the only place it appears, and
  `CONCRETE_QUESTION_MODELS` was already built at import time with an abstract filter. The
  guard's derivation must therefore keep `issubclass` and **not** also filter on
  `_meta.abstract`, or the stub would be filtered and the growth case could not go red.
  ⚠️ **Never define a throwaway concrete model class**: it registers permanently in
  `apps.all_models` and `QuestionElement.__subclasses__()` for the whole process/xdist worker
  (poisoning `CONCRETE_QUESTION_MODELS` and every later test that derives the model set), and a
  test-only app would also need an `INSTALLED_APPS` entry.
- **T35 The page.** Owner views: a SUBMITTED graded quiz shows the scored pill and each row's
  badge; an IN_PROGRESS quiz shows the in-progress pill, "*k* of *n* questions answered", no
  score, and the correct answer for a wrong answer on a question with attempts left (D5); an
  AUTO row shows "attempt 1 of 2"; an unlimited-attempts row shows "attempt 1"; an answered
  REVIEW row shows "attempt 1 of 1" (mutant: restrict the attempt line to AUTO). A part with
  `given is None` and `ok is True` renders no ✓ **and no sr-only "Correct"** (mutant: key the
  sr-only span on `ok` alone), and a shorttext row whose `expected` is `""`
  renders no "Correct answer:" (mutant: test `expected is not None` instead of truthiness).
  A fillblank item's rendered stem contains no `U+FFFF` and shows `[1]`, `[2]` in the order of its
  "Gap 1", "Gap 2" parts; a dragfill item likewise (mutant: set `stem_html` from the raw stem for
  token types). A quiz with no questions renders "This quiz has no questions." and no "of 0" count
  (mutant: render the empty list). A prompt-less dragimage item renders its `img.dragimage__img`
  with one `span.dragimage__badge` per zone, numbered like its "Zone i" parts, and contains no
  `select`, `form` or `data-dnd` (mutants: omit the stage; copy the interactive template instead).
  A reviewed row whose `review_feedback` alone carries `\(x\)` sets `has_math` (mutant: leave
  feedback out of `has_math`).
  On a SUBMITTED quiz with two unreviewed REVIEW questions, the two per-row Review links have
  distinct accessible names (mutant: drop the sr-only question number).
  ⚠️ The in-progress fixture **must include a `QuestionResponse` with `attempt_count=0,
  latest_answer=None`** on a listed question (the empty-submit row, §2.2), and `k` must exclude it
  — otherwise the count mutant below cannot go red. The same fixture holds an unanswered REVIEW
  question and an empty-row NOT_MARKED question: both badge "Not answered", not "Awaiting review" /
  "Answer recorded" (§3.3's override); an **answered** REVIEW question on it badges "Answer
  recorded" with no Review link; and on a **SUBMITTED** quiz the unanswered REVIEW question
  still badges "Awaiting review".
  Mutants: withhold `expected` while `response.locked` is false; count `k` over all responses
  instead of `answered` listed rows; drop the outcome override (either empty-row badge goes red);
  apply the REVIEW override on SUBMITTED too (the submitted case goes red); drop the
  answered-REVIEW-in-progress arm (that row badges "Awaiting review" and goes red).
- **T36 Header parity with the breakdown.** For each of the four submission states, the new
  page's pill equals the breakdown's pill for the same pupil and quiz — compared as **rendered
  markup** (the `pill--*` class and its text), scoped to the new page's header and to that quiz's
  `div.breakdown-unit` row, never as `response.context` dicts (which would pass a header that
  bypasses the shared partial; mutant: inline a copy of the pill spans in the header with one
  class changed) — including a
  SUBMITTED quiz with an unreviewed REVIEW question (`awaiting`, with exactly one Review link in
  the header and the score text absent), a SUBMITTED ungraded one (`submitted`), and a fully
  reviewed REVIEW-only quiz (`submitted`, although `max_score > 0`). ⚠️ The kind is decided
  inside the SHARED helpers (`_course_results_row`, `_quiz_pill`, §3.4), so a mutant there changes
  both pages at once and parity stays green. The only view-local code is the **arguments** the
  new view passes, so the mutants go there:
  - call `_quiz_review_maps([unit.pk], [])` (no submissions → empty `reviewed_counts`) → the fully
    reviewed REVIEW-only quiz reads `awaiting` on the new page but `submitted` in the breakdown;
  - call `_quiz_review_maps([], [submission])` (no unit pks → empty `has_auto`) → the scored quiz
    reads `submitted` on the new page but `scored` in the breakdown.
- **T37 Breakdown links.** The quiz title is a link to the new page for scored, submitted,
  awaiting and in_progress; not_started renders no link; the link carries the breakdown's
  querystring; the page's "← Breakdown" link round-trips `scope`, `mode`, `expand`, `student` and
  `values`. ⚠️ The incoming querystring carries **`values=raw`** and a **non-empty `student`
  subset**: `_expand_qs` emits `values` only when it is `"raw"` and `student` only when non-empty
  (`views_analytics.py:190-197`), so defaults would make both drops invisible. Mutants: link
  not_started; drop `values` from the back link; drop the subset from the back link.
- **T38 Query budget.** The page for a quiz with **one** question of each of the ten types and
  for one with **two** of each (every answered, a submission per fixture) issues the **same**
  number of queries, measured after a warm-up request (ContentType cache). Mutants: remove one
  type's prefetch from the extracted helper; drop `"media"` from the dragimage prefetch — in
  each, the two-of-each count exceeds the one-of-each count.
- **T39 Maths.** A pupil's short-text `given` containing `\(x\)` in a quiz with no other maths
  sets `has_math`, and the rendered page then includes **both** the KaTeX include and the
  `courses/js/question.js` script tag (after it); a quiz with no maths anywhere includes neither.
  Mutants: compute `has_math` from stems only; drop the `question.js` tag (§5.2 — maths would stay
  raw while the flag test passed).
- **T41 Grids reach the rollups (D9).** Pill kinds are read from `build_student_breakdown`'s tree
  (`rollups.py:535-555`, which applies `_quiz_pill` to each `build_course_results` row — the
  row itself carries only `status`/`graded`) (so the breakdown and the
  new header both inherit it): a SUBMITTED **grid-only AUTO** quiz (one choicegrid) pills
  `scored`; a SUBMITTED quiz whose only REVIEW question is an **unreviewed multigrid** pills
  `awaiting`, and after that response gets `reviewed_at` it pills **`submitted`** (no AUTO
  question, so `graded` is false); `quiz_gradeable_max` for a unit with one AUTO choicegrid
  (`max_marks` 2) and one AUTO shorttext (`max_marks` 1) is 3. The same fixtures through the new
  page show a header Review link iff the row has one. Mutant: restore the 8-model list — the
  grid-only AUTO pill, the unreviewed-multigrid `awaiting` pill, its header Review link and the
  gradeable maximum go red. ⚠️ The **post-review** case does **not**: under the 8-model list the
  multigrid drops out of both `total_review` and `reviewed_counts`, `0 > 0` is false, and it pills
  `submitted` either way. It stays as a behaviour check that the fix does not leave a reviewed
  grid pending, not as a guard on D9. The swap
  itself must not pin a count (memory: guards-that-assert-the-adjacent-thing, pattern #9).
- **T40 e2e (real gestures, `-m e2e`).** A non-staff group teacher logs in, opens the matrix,
  clicks the pupil's name, clicks the quiz title in the breakdown, and sees — inside that
  question's item — the pupil's wrong numeric answer and "Correct answer:" with the expected
  value; clicks "← Breakdown" and lands on the breakdown. The quiz is **published** (the normal
  case; T31 owns the draft case).
- **Existing tests that move:**
  - `tests/test_analytics_rollups.py:547-552` (`scored`) and `:576` (`submitted`) compare whole
    pill dicts and **must gain `submission_pk`** with the fixture submission's pk (§3.5). Those fixtures create the
    submissions as bare `QuizSubmission.objects.create(...)` (`:522`, and `:576`'s own fixture),
    unlike `sub_pending` (`:529`): **bind each to a name** (e.g. `sub_scored = …`) and assert
    `sub_scored.pk` — never `QuizSubmission.objects.last()`, which can pick the other row. `:555`
    (`not_started` has no `submission_pk`) stays unchanged and is the guard that `not_started`
    never gets one.
  - `tests/test_analytics_views.py`'s breakdown tests (`:199-291`) keep passing unchanged — the
    pill partial extraction must not change their asserted text (`90%`, the `/review/<pk>/`
    link).
  - `tests/test_title_math_markers.py:431-450` (the breakdown title's maths marker) is
    **extended** to assert the marker separately on the link branch (a quiz with a submission)
    and the plain branch (`not_started`), so neither passes on the other's marker. ⚠️ Its docstring
    and messages cite template lines — `:434` ("The quiz branch (:6) and the lesson branch
    (:24)"), `:448` (`_breakdown_node.html:6`), `:449` (`(:24)`); moving the pill spans into
    `_quiz_pill.html` and adding the link branch shifts both, so re-point all three to the
    post-change lines in the same commit. Mutant: put
    `data-math-title` on the `<a>` instead of the span (the link-branch assertion goes red).
  - Tests covering `build_course_results` keep passing after `_course_results_row` is extracted
    (behaviour-preserving), and the tests covering `build_lesson_context` **and**
    `build_quiz_context` (e.g. `courses/tests/test_callout_has_math.py`,
    `test_nested_question_nojs_feedback.py`) keep passing after both prefetch copies are replaced
    by `prefetch_question_children`.

**Manual pass before the PR:** provision a local `mat-pp` demo kit, log in as its Teacher, open
several pupils' quizzes, in light and dark; confirm wrong answers vary between pupils (parent T28
is what makes that true) and that no text reads in the pupil's voice. Screenshots, not a green
suite, decide it (memory: verify-ui-with-screenshots).

Scoped test runs per task; the whole-suite sweep, in chunks, is a branch gate only.

## 7. Delivery

One PR, off master. **No migration, no FORMAT_VERSION bump.** New pl msgids (§5.4). Merge
order stays parent §6: 1 → 2 → 3 → **5** → 4, then the vendor flag.

⚠️ **D9 changes live numbers on deploy**, with no data migration (everything is computed on
read): on any quiz containing a grid, `has_auto`/the review gate/`quiz_gradeable_max` start
counting it. Every surface fed by `_quiz_review_maps` or `quiz_gradeable_max` moves:

- **Breakdown pill and the pupil's own course results page** (`build_course_results` also serves
  `course_results`, `views.py:696-703`):
  - a grid-only AUTO quiz's pill moves `submitted` → `scored`, and its course-results row switches
    from "submitted — not graded" to its score (`course_results.html:23-24`). **The headline is
    unchanged**: `build_course_results` already sums `sub.score`/`sub.max_score` for every
    non-pending SUBMITTED row regardless of `graded` (`rollups.py:494-497`);
  - a SUBMITTED quiz with an **unreviewed REVIEW grid** becomes `awaiting_review` (pending) and
    **drops out** of the pupil's headline score and maximum.
- **Results matrix cells and averages** (`build_results_matrix`, `rollups.py:833`) and
  **gradebook cells** (`build_quiz_gradebook`, `gradebook.py:95,118`): a SUBMITTED quiz with an
  **unreviewed REVIEW grid** stops being counted — its matrix cell and averages drop it and its
  gradebook cell shows "R" instead of a score.
- **Gradebook columns**: a grid-only quiz's maximum was 0, which blanks the whole column
  (`gradebook.py:110`); after D9 the column fills with scores. A mixed quiz's maximum rises by its
  grid marks.

Cached `QuizSubmission.score`/`max_score` are unaffected (`compute_scores` already counted grids).
The REVIEW-grid effects have **no known prod instance**: every question in mat-pp's published
quizzes was AUTO in the parent's local audit (§3.1, 260/260), though prod has moved since. The PR
description lists all of the above; the manual pass (§6) opens a mat-pp quiz holding a choicegrid
in the breakdown, the matrix, the pupil's course results and the gradebook export, before and
after the change — checking the grid-only quiz's course-results **row** (not the headline, which
does not move for it); the pending-headline effect has no known prod instance and is pinned by T41
instead.

⚠️ **Citation sweep (a delivery step, not optional).** Extracting `prefetch_question_children`
removes roughly 20 lines from `build_lesson_context` (`views.py:360-382`) and 25 from
`build_quiz_context` (`:1334-1356`); D9 deletes the model list and imports near the top of
`rollups.py`. Every later line in both files shifts (memory:
line-inserting-diffs-rot-citations-in-untouched-files). After both edits land, grep for
`views\.py:\d`, `rollups\.py:\d` and `_breakdown_node\.html:\d` **outside `docs/` and `.po` files** and re-point every stale
citation. Known at `d432245a`:

- `demo/generator.py:177` (→ `views.py:1654-1664`) and `:205` (→ `:1674`);
- `courses/templatetags/courses_extras.py:71` (→ `views.py:1394`);
- `tests/test_publish_banners.py:209` (→ `:1372`) and `:231` (→ `:1405`);
- `tests/capture_title_math_screenshots.py:174` (→ `:1411-1417`);
- `tests/test_title_math_assets.py:269` (→ `:1318`);
- `courses/rollups.py:1085` (→ `rollups.py:244-250, :265`).

Some of these guards read the cited file (the css-citation tests did), so a missed one can go red
in CI rather than only rot (memory: courses-css-line-citations-are-stale). This spec's own
`views.py`/`rollups.py` line numbers describe master `d432245a` and are not re-pointed.

## 8. Parent amendments

- Parent §6 "PR 5": **applied in this spec's commit** — a pointer to this document, noting that
  the drill-down lists every question (not AUTO only) and opens in-progress submissions too.
- Parent §8 T30: unchanged in substance; this spec's T30 implements it with 404 throughout (D7).
