# Per-question drill-down (demo access PR 5) — design

**Status:** approved in brainstorming 2026-09-14. Not yet planned, not yet built.
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
- The same per-type prefetch as `build_quiz_context` (§2.5). ⚠️ **Extract it** into one helper
  both builders call, rather than copying the seven `if` blocks: two copies drift exactly the
  way the lock rule did (`courses/quiz.py:94-116`).
- `responses = {r.element_id: r for r in submission.responses.all()}`.
- Per question: `row = _results_row(q, responses.get(el.pk))`, then
  `row["parts"] = summarise(q, row["response"], row["reveal_result"])` (§4),
  `row["qnum"]` (1-based over listed questions), and for AUTO questions with
  `response.attempt_count > 0`, `attempt_count` and `max_attempts`.
- **Outcome override** (§2.2), applied by the new view to `row["outcome"]` after `_results_row`,
  never inside it (the pupil's page is out of scope, §3.6):
  - NOT_MARKED with `row["answered"]` false → `"not_answered"` (any status);
  - REVIEW with `row["answered"]` false on an **IN_PROGRESS** submission → `"not_answered"`.
    On a SUBMITTED one it stays `"review"`: an unanswered REVIEW question genuinely blocks the
    score (`rollups.py:402-409`) and appears in the review page.
  - AUTO is unaffected (`_results_row` already keys it on `fraction`).

### 3.4 The header

- Title: `{{ unit.title }} — {{ student.display_name|default:student.username }}`.
- **Status:** the pill (D8), computed by the breakdown's own code, not a re-derivation. The
  per-unit row construction inside `build_course_results` (`rollups.py:450-493`) is **extracted**
  into `_course_results_row(unit, sub, has_auto, total_review, reviewed_counts)`, which
  `build_course_results` then calls in its loop (behaviour unchanged). The new view calls
  `_quiz_review_maps([unit.pk], [submission])`, then `_course_results_row(...)`, then
  `_quiz_pill(row)` (§2.5). Kinds and what each shows:
  - `scored` — "scored s/m (p%)", as in the breakdown;
  - `submitted` — submitted, and either the quiz has no AUTO question or `max_score` is falsy
    (`rollups.py:518`) — e.g. a fully reviewed REVIEW-only quiz;
  - `awaiting` — "awaiting review" **plus the existing "Review" link** to
    `courses:manage_review_submission`;
  - `in_progress` — "in progress" plus "*k* of *n* questions answered", where *n* is the
    number of listed questions and *k* counts rows with `answered` true. No score: nothing is
    cached before finish (`courses/quiz.py:232-246`).
- **Back link:** "← Breakdown" to `courses:manage_analytics_student` for this pupil, carrying the
  incoming `scope`/`mode`/`expand`/`student`/`values` querystring through `_expand_qs`
  (`courses/views_analytics.py:184-198`) — so the breakdown's own "← Analytics" still restores
  the matrix.

### 3.5 Entry points from the breakdown

- `_quiz_pill` returns `submission_pk` for **every** kind that has a submission (scored,
  submitted, awaiting, in_progress); `not_started` stays without one.
- `_breakdown_node.html` renders the quiz title as a link to the new page whenever the pill has
  a `submission_pk`, carrying the breakdown's querystring; `not_started` stays plain text. The
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
the `demo` app; the `/for-schools/` copy (PR 4).

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
   question (an empty gap, an unselected grid row, an empty drop slot).
5. **`"keyword"` parts never carry a pupil value.** `given` and `expected` are always `None`; the
   template renders only the label and the ✓/✗ glyph for them, and never "Not answered" (§5.1).

### 4.3 Per type

| type | parts | `given` | `expected` | `ok` source |
|---|---|---|---|---|
| choice (single or multiple) | 1, no label | picked option texts in option `(order, pk)` order, `", "`-joined; one `"(removed option)"` per stored pk no longer among the choices | correct option texts, same order | `mark_result.correct` |
| shorttext | 1 | the stored string | `mark_result.reveal` (first accepted line) | `.correct` |
| shortnumeric | 1 | the stored string | `reveal["value"]`, plus `" ± " + reveal["tolerance"]` when tolerance is non-empty | `.correct` |
| extendedresponse | 1 `"answer"` part for the text (`label=None`, `expected=None` **always** — there is no model answer, §2.5), then one `"keyword"` part per keyword in `reveal` order | the text, line breaks preserved | `None` on every part. Keyword label = `gettext("Required") + ": " + kw` / `gettext("Avoid") + ": " + kw`, reusing the existing bare msgids exactly as `_reveal_extendedresponse.html:8,13` joins them | text part: `.correct` when answered, `False` when unanswered (rule 3); keyword part: `found` for Required, `not found` for Avoid — **`None` on every keyword part when unanswered**, as `_reveal_extendedresponse.html:18-28` does |
| fillblank | one per blank, `"Gap i"` | the typed value, or `None` if empty | `reveal[i]["accepted"]` | `reveal[i]["correct"]` |
| dragfill | one per gap, `"Gap i"` | the chosen token, or `None` | `reveal[i]["accepted"]` | `reveal[i]["correct"]` |
| dragimage | one per zone, `"Zone i"` | the chosen label, or `None` | `reveal[i]["accepted"]` | `reveal[i]["correct"]` |
| matchpair | one per pair, label = `reveal[i]["left"]` | the chosen token, or `None` | the pair's `right` (`reveal[i]["accepted"]`) | `reveal[i]["correct"]` |
| choicegrid | one per row, label = statement | the chosen column's label; `None` for `""`; `"(removed option)"` for a pk not among the columns | `reveal[i]["correct_label"]` | `reveal[i]["is_correct"]` |
| multigrid | one per row, label = statement | chosen column labels, `", "`-joined; `"(removed option)"` appended once per stored pk not among the columns; `None` for an empty set | `reveal[i]["correct_labels"]` joined | `reveal[i]["is_correct"]` |

`i` in a label is 1-based. For REVIEW/NOT_MARKED questions the same parts are built from the
stored answer and the current rows alone (no `mark_result`), so rule 1 holds.

⚠️ **Content edited after the answer** (the known drift, handled explicitly — D6):

- **Part count follows the question's current rows.** The stored list is padded with "empty" or
  truncated to that count, exactly as each `mark()` pads (`models.py:2600`, `:2776`, `:2861`;
  `dnd.py:45`), so parts and `reveal` entries always align by index.
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
    `courses/models.py:2198-2201`), inside `lang="{{ course.language }}"`;
  - the outcome badge, **a deliberate copy of `quiz_results.html:31-37`'s markup and msgids**
    (Correct, Partial, Incorrect, Not answered, Answer recorded, Reviewed, Awaiting review).
    Accepted as a copy: extracting a partial would change the pupil's results page, which §3.6
    keeps out of scope. It uses the `marks` filter, so the template loads `courses_extras`;
  - for REVIEW rows on an `awaiting` submission, a "Review" link to the review page;
  - the parts: one `<div class="answers__part answers__part--{{ part.kind }}">` each — the label
    if any; for an `"answer"` part, `given`, or muted "Not answered" (existing msgid) when `None`
    (a `"keyword"` part renders no given/not-answered text at all, §4.2 rule 5); a ✓/✗ glyph when `ok` is not `None`, `aria-hidden`,
    followed by sr-only "Correct" / "Incorrect" (existing msgids, **teacher voice — never
    "your answer"**); then "Correct answer:" (existing msgid) + `expected` when present.
    `given` for extendedresponse keeps line breaks (`white-space: pre-wrap`);
  - for AUTO rows with attempts, "attempt *n* of *max*", or "attempt *n*" when `max_attempts` is
    null (unlimited).
- All pupil-entered and author-entered text is autoescaped (`given`, labels, `expected`); only the
  stem is `|safe`, as on the pupil's page.

### 5.2 Maths

`has_math` = `titles_have_math([unit.title])` or any `_question_has_math(q)` or any
`has_math_delimiters` over each part's `given`, `expected` and `label` (a pupil can type
`\(x\)` into a short-text answer). When true, include `courses/_katex_css.html` and
`courses/_katex_js.html`, as `analytics_student.html:4,19` does, **then
`<script src="{% static 'courses/js/question.js' %}" defer></script>` after that include**, and
mark each item `data-question` — exactly `quiz_results.html:28,62-69`. Without `question.js` the
`data-question` subtrees are never typeset (§2.5) and stems/answers show raw `\(x\)`. Its form
wiring is a no-op here: the page has no `<form>`.

### 5.3 Styling

- Load `courses/css/courses.css` for the stem's rich-text prose (as `quiz_results.html:5`).
- New `answers__*` rules in `core/static/core/css/app.css`, next to the breakdown block
  (`:1007-1013`), tokens only. Parts stack to one column below 640px; a long grid statement
  wraps rather than scrolling.
- ⚠️ A CSS comment naming class stems gets the `*/`-early-terminator check (memory:
  css-comment-early-terminator-eats-next-rule).

### 5.4 i18n

New msgids, each filled in Polish by hand (expected set; the plan confirms each is new by grep):
"Answers", "Gap %(n)s", "Zone %(n)s", "(removed option)", "attempt %(n)s of %(max)s",
"attempt %(n)s", and an `ngettext` pair "%(k)s of %(n)s question answered" /
"%(k)s of %(n)s questions answered" (Polish needs its three forms). After `makemessages`, check
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
substring (memory: independent-pk-sequences-make-substring-assertions-flaky). Scope content
assertions to the item or header element, not the whole page: the quiz title repeats in
`head_title` and the `manage__head` title, and the pupil's name in that title.

- **T30 Access (parent §8 — PR 5 does not merge without it).** One fixture: a course with two
  non-archived groups, each with one pupil holding a SUBMITTED submission on the same published
  quiz. Each viewer gets its own request for pupil A's page:

  | viewer | expected |
  |---|---|
  | Platform Admin | 200 |
  | course owner | 200 |
  | teacher of pupil A's group (`make_teacher`, **non-staff**) | 200 |
  | teacher of pupil B's group only | 404 |
  | a user with `is_staff=True` **and** the Teacher group who teaches no group on the course (assert `is_staff` up front — `make_teacher` does not set it, §2.4) | 404 |
  | pupil A themself | 404 |
  | anonymous | 302 to login |

  Mutants, each with the rows it turns red:
  - gate step 2 on `request.user.is_staff` instead of `can_review_course` → the **non-staff group
    teacher** and **owner** rows go 200 → 404 (the staff row stays 404: step 3 still finds no
    reviewable pupil for it);
  - replace step 3's `reviewable_students(...)` with an unscoped `User` lookup → the
    **other-group teacher** row goes 404 → 200;
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
  dragimage, matchpair, choicegrid, multigrid); unanswered (AUTO); and the same answer on a
  REVIEW-mode copy (all `expected`/`ok` `None`). Choice covers single and multiple.
  extendedresponse covers: `"keyword"` parts with `given`/`expected` `None`; unanswered keyword
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
  new expected value — pinning the accepted split. Mutants: skip the padding (IndexError or
  misaligned parts); read choicegrid `given` from `reveal["chosen_label"]` (the removed pk shows
  as not answered); read part `ok` from the stored fraction (the key-edit case goes red).
- **T34 Drift guard** (§4.4). Falsified twice: delete one registry entry; and, separately, grow the
  derived set with `mock.patch.object(apps, "get_models", ...)` returning the real models plus a
  stub subclass. ⚠️ **Never define a throwaway concrete model class**: it registers permanently in
  `apps.all_models` and `QuestionElement.__subclasses__()` for the whole process/xdist worker
  (poisoning `CONCRETE_QUESTION_MODELS` and every later test that derives the model set), and a
  test-only app would also need an `INSTALLED_APPS` entry.
- **T35 The page.** Owner views: a SUBMITTED graded quiz shows the scored pill and each row's
  badge; an IN_PROGRESS quiz shows the in-progress pill, "*k* of *n* questions answered", no
  score, and the correct answer for a wrong answer on a question with attempts left (D5); an
  AUTO row shows "attempt 1 of 2"; an unlimited-attempts row shows "attempt 1".
  ⚠️ The in-progress fixture **must include a `QuestionResponse` with `attempt_count=0,
  latest_answer=None`** on a listed question (the empty-submit row, §2.2), and `k` must exclude it
  — otherwise the count mutant below cannot go red. The same fixture holds an unanswered REVIEW
  question and an empty-row NOT_MARKED question: both badge "Not answered", not "Awaiting review" /
  "Answer recorded" (§3.3's override); and on a **SUBMITTED** quiz the unanswered REVIEW question
  still badges "Awaiting review".
  Mutants: withhold `expected` while `response.locked` is false; count `k` over all responses
  instead of `answered` listed rows; drop the outcome override (either empty-row badge goes red);
  apply the REVIEW override on SUBMITTED too (the submitted case goes red).
- **T36 Header parity with the breakdown.** For each of the four submission states, the new
  page's pill kind equals the breakdown's pill kind for the same pupil and quiz, including a
  SUBMITTED quiz with an unreviewed REVIEW question (`awaiting`, with exactly one Review link in
  the header and the score text absent), a SUBMITTED ungraded one (`submitted`), and a fully
  reviewed REVIEW-only quiz (`submitted`, although `max_score > 0`). Mutants — in the **new
  view's kind computation**, not the shared partial (a partial mutant changes both pages at once
  and parity stays green): ignore `submission_is_counted` (the awaiting case goes red, score
  shown); compute `scored` from `max_score` alone (the REVIEW-only case goes red).
- **T37 Breakdown links.** The quiz title is a link to the new page for scored, submitted,
  awaiting and in_progress; not_started renders no link; the link carries the breakdown's
  querystring; the page's "← Breakdown" link round-trips `scope`, `mode`, `expand`, `student` and
  `values`. ⚠️ The incoming querystring carries **`values=raw`** and a **non-empty `student`
  subset**: `_expand_qs` emits `values` only when it is `"raw"` and `student` only when non-empty
  (`views_analytics.py:190-197`), so defaults would make both drops invisible. Mutants: link
  not_started; drop `values` from the back link; drop the subset from the back link.
- **T38 Query budget.** The page for a quiz with **one** question of each of the ten types and
  for one with **two** of each (every answered, a submission per fixture) issues the **same**
  number of queries, measured after a warm-up request (ContentType cache). Mutant: remove one
  type's prefetch from the extracted helper — the two-of-each count exceeds the one-of-each count.
- **T39 Maths.** A pupil's short-text `given` containing `\(x\)` in a quiz with no other maths
  sets `has_math`, and the rendered page then includes **both** the KaTeX include and the
  `courses/js/question.js` script tag (after it); a quiz with no maths anywhere includes neither.
  Mutants: compute `has_math` from stems only; drop the `question.js` tag (§5.2 — maths would stay
  raw while the flag test passed).
- **T40 e2e (real gestures, `-m e2e`).** A non-staff group teacher logs in, opens the matrix,
  clicks the pupil's name, clicks the quiz title in the breakdown, and sees — inside that
  question's item — the pupil's wrong numeric answer and "Correct answer:" with the expected
  value; clicks "← Breakdown" and lands on the breakdown. The quiz is **published** (the normal
  case; T31 owns the draft case).
- **Existing tests that move:**
  - `tests/test_analytics_rollups.py:547-552` (`scored`) and `:576` (`submitted`) compare whole
    pill dicts and **must gain `submission_pk`** with the fixture submission's pk (§3.5). `:555`
    (`not_started` has no `submission_pk`) stays unchanged and is the guard that `not_started`
    never gets one.
  - `tests/test_analytics_views.py`'s breakdown tests (`:199-291`) keep passing unchanged — the
    pill partial extraction must not change their asserted text (`90%`, the `/review/<pk>/`
    link).
  - Tests covering `build_course_results` keep passing after `_course_results_row` is extracted
    (behaviour-preserving), and `courses/tests/` covering `build_quiz_context` keep passing after
    the prefetch extraction.

**Manual pass before the PR:** provision a local `mat-pp` demo kit, log in as its Teacher, open
several pupils' quizzes, in light and dark; confirm wrong answers vary between pupils (parent T28
is what makes that true) and that no text reads in the pupil's voice. Screenshots, not a green
suite, decide it (memory: verify-ui-with-screenshots).

Scoped test runs per task; the whole-suite sweep, in chunks, is a branch gate only.

## 7. Delivery

One PR, off master. **No migration, no FORMAT_VERSION bump.** New pl msgids (§5.4). Merge
order stays parent §6: 1 → 2 → 3 → **5** → 4, then the vendor flag.

## 8. Parent amendments

- Parent §6 "PR 5": **applied in this spec's commit** — a pointer to this document, noting that
  the drill-down lists every question (not AUTO only) and opens in-progress submissions too.
- Parent §8 T30: unchanged in substance; this spec's T30 implements it with 404 throughout (D7).
