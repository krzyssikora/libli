# Interactive quiz preview for non-enrolled viewers

## Purpose

### The problem

A user with course access but **no enrollment** — a platform admin, a teacher, a content editor
previewing their own work — opens a quiz unit and gets a page that looks like a live quiz but is
inert. Every input renders `disabled`, there is no "Finish quiz" button, and **nothing on the page
says why**. The page reads as broken software, not as a preview.

Measured on the live dev database, rendering `/courses/mat-pp/u/150/quiz/` as a staff user through
the Django test client:

```html
<input type="checkbox" name="choice" value="127" disabled>
<input type="text" name="answer" inputmode="decimal" ... disabled>
<button type="submit" class="btn btn--small" disabled>Sprawdź</button>
```

`quiz-finish` occurs zero times in the response, and the response contains zero occurrences of any
preview/read-only notice string.

### The cause

`courses/views.py:1204`:

```python
"read_only": quiz_submitted or submission is None,
```

`submission` is `None` for anyone not enrolled, because `courses/views.py:1133-1135` only creates a
`QuizSubmission` when `is_enrolled(user, node.course)`. The single `read_only` flag therefore
conflates two unrelated states:

- **submitted** — the student finished; the quiz is genuinely frozen; and
- **previewing** — the viewer is not enrolled, so nothing *can* be persisted.

`_quiz_article.html:12` passes that conflated flag into every question template as
`quiz_submitted=read_only`, and each question template disables its inputs on
`{% if quiz_submitted or locked %}`.

This is **not a regression**. The line has been present since commit `0fbf983b` (2026-06-20), the
original quiz feature. It is also **not slideshow-related** — three non-slideshow `mat-pp` quizzes
(362, 841) render identically inert; the bug was first reported against a slide-split quiz only by
coincidence.

### Why it is worth fixing

Lessons already do the opposite. A non-enrolled previewer on a lesson unit **is** interactive: their
practice state and their explicit completion both persist. That asymmetry is deliberate and
documented at `courses/views.py:688-698`, which spells out that only *scroll tracking* is dropped for
a previewer. Quizzes are the sole unit type that gives a previewer a dead page.

### What this change does

A non-enrolled previewer gets a **live, gradeable quiz that persists nothing**. They can select
choices, type answers, press Check, and see exactly the feedback a student would see — including the
withhold-until-locked reveal gating — while no `QuizSubmission`, `QuestionResponse`, or `Attempt` row
is ever written.

### Non-goals (decided, not open)

- **"Finish quiz" stays hidden for previewers.** Nothing is persisted, so there is no submission for
  `quiz_results` to render. No client-side score summary in this slice.
- **No server-side attempt enforcement for previewers.** Attempts are client-tracked, so a previewer
  who reloads the page gets a fresh attempt budget. This is already true of the authoring "try it"
  preview; matching it is consistent, and the alternative (server-side attempt state) would require
  exactly the persistence this change exists to avoid.
- **The enrolled student path does not change.** Not its grading, attempt enforcement, locking,
  reveal gating, `[N]`/`[R]` neutral handling, or 409-on-submitted behaviour.

## Architecture

The grading machinery this feature needs **already exists and ships today**. It is the authoring
"try it" preview at `courses/views_manage.py:1732-1761`, which marks an answer with the real
`question.mark()`, synthesises per-question response state, reads a client-supplied `attempt` field,
persists nothing, and renders the same `courses/elements/_quiz_question_feedback.html` fragment the
student path uses. `courses/quiz.py:11-19` already documents `quiz_feedback_context` as accepting
such a stand-in:

> `response` only needs `.locked` and `.attempt_count` — the live student path passes a
> `QuestionResponse`; the authoring 'try it' preview passes an ephemeral stand-in (nothing
> persisted).

So this change is **wiring an existing mechanism into a second call site**, not building grading.

### Component 1 — `courses/quiz.py`: extract the ephemeral grader

Move the ephemeral logic out of `views_manage.py` into two pure helpers in `courses/quiz.py`, and
have **both** call sites use them. This is an extraction, not a copy: the repository carries a
standing twin-drift guard (issue #169) precisely because code-identical duplicates rot apart.

```python
def parse_attempt(post):
    """1-based attempt number from a client-supplied `attempt` field, floored at 1."""

def ephemeral_quiz_feedback(question, answer, attempt):
    """Grade `answer` and return the _quiz_question_feedback.html context.
    Persists NOTHING — no QuizSubmission, no QuestionResponse, no Attempt.
    Mirrors quiz_answer's state machine exactly:
      - empty answer            -> validation context, attempt NOT consumed
      - AUTO                    -> mark(); locked iff correct or attempt >= max_attempts
      - NOT_MARKED / REVIEW     -> result None, locked True (single submission)
    """
```

`ephemeral_quiz_feedback` builds a `SimpleNamespace(locked=…, attempt_count=…)` stand-in and returns
`quiz_feedback_context(question, stand_in, result=…)`. Because it routes through the same
`quiz_feedback_context`, the **no-leak guarantee is inherited rather than reimplemented**: the correct
answer is withheld until the question locks, exactly as for a student.

`views_manage.element_try`'s quiz branch collapses to a call to these two helpers. Its observable
behaviour must not change.

### Component 2 — `courses/views.py`: unconflate the two flags

`build_quiz_context` gains a distinct `previewing` flag and stops overloading `read_only`:

| Context key | Meaning | Consumers |
|---|---|---|
| `quiz_submitted` | The submission is `SUBMITTED`; inputs frozen. | question templates (via `_quiz_article.html`) |
| `previewing` | Viewer is not enrolled; answers cannot be recorded. | preview banner |
| `read_only` | `quiz_submitted or previewing`; gates the Finish form only. | `_quiz_article.html` Finish block |

`read_only` is retained with its current value so the Finish form's condition is untouched — Finish
stays hidden for previewers, per the decided non-goal. The change is that `_quiz_article.html:12`
passes `quiz_submitted=quiz_submitted` rather than `quiz_submitted=read_only`, so a previewer's inputs
render **live** while a submitted quiz's stay frozen.

### Component 3 — `courses/views.py`: the previewer answer branch

`quiz_answer` currently rejects previewers outright at line 1278:

```python
if not is_enrolled(request.user, course):
    raise PermissionDenied  # previewers cannot persist
```

That becomes a branch to the ephemeral path, taken **after** the existing `can_access_course` check
and after the element/question resolution, so a previewer is subject to exactly the same access and
404 rules as a student. The branch returns before the `transaction.atomic()` block, so no write path
is reachable for a previewer.

`quiz_finish` keeps `raise PermissionDenied` for non-enrolled users, unchanged.

### Component 4 — `templates/courses/_quiz_article.html`: the preview banner

A previewer gets a visible, styled banner above the questions explaining the state — the missing
piece that made the current behaviour read as breakage:

> **Preview** — you are not enrolled in this course, so your answers are not recorded.

Rendered only when `previewing` is true. New user-visible strings go into both the `pl` and `en`
catalogues. The banner ships styled against existing design tokens (no bare HTML), reusing the
established callout/notice look rather than inventing a new one.

### Component 5 — `courses/static/courses/js/quiz.js`: client-side attempt tracking

The ephemeral endpoint is stateless, so the client owns the attempt counter. `quiz.js` mirrors the
already-shipped logic at `editor.js:220-258`:

- read `data-attempts-made` (default `0`) from the enclosing `[data-question]`;
- append `attempt` = made + 1 to the POST body;
- on response, increment `data-attempts-made` **unless** the feedback carries `.is-validation` (an
  empty answer does not consume an attempt);
- the existing `[data-quiz-locked]` handling already disables inputs on terminal states and is
  reused as-is.

The counter is gated so the enrolled path is behaviourally unaffected: the server ignores `attempt`
entirely on the enrolled path, where attempt state comes from the persisted
`QuestionResponse.attempt_count`.

## Data flow

### Previewer, GET

```
quiz_unit
  -> build_quiz_context
       is_enrolled = False -> submission = None
       quiz_submitted = False        (inputs LIVE)
       previewing     = True         (banner shown)
       read_only      = True         (Finish hidden)
       responses = {}, render_states = per-question empty state
  -> quiz_unit.html -> _quiz_article.html
       banner + live question forms, no Finish form
```

No write occurs, exactly as today: `QuizSubmission.objects.filter(unit=unit)` stays empty.

### Previewer, POST an answer (JS)

```
quiz.js  -> POST action_url  { …answer fields…, attempt: N }  X-Requested-With: fetch
quiz_answer
  can_access_course  -> ok
  resolve element + question (404 rules identical to the student path)
  is_enrolled == False
    -> attempt = parse_attempt(POST)
    -> ctx = ephemeral_quiz_feedback(question, question.build_answer(POST), attempt)
    -> render _quiz_question_feedback.html            [NO transaction, NO writes]
quiz.js  -> swap [data-question-feedback]; bump data-attempts-made unless .is-validation;
            disable inputs iff [data-quiz-locked]
```

### Previewer, POST an answer (no JS)

`_wants_fragment(request)` is false, so returning a bare fragment would render a naked HTML snippet as
a whole page. The previewer no-JS path instead reuses the existing full-re-render shape already used
by `_quiz_render_feedback`: rebuild the quiz context and inject this question's rendered fragment into
its `render_states[element.pk]["feedback_html"]`, plus rehydrate the submitted values so the inputs
show what was typed.

Because the previewer has no server-side attempt state, a no-JS previewer is always at attempt 1.
Consequence, accepted: a no-JS previewer never reaches "wrong on the last attempt", so for a
multi-attempt AUTO question they see the withhold branch rather than the reveal. This is a strictly
narrower view than a student gets — it leaks nothing — and it is the direct, stated cost of the
"no server-side attempt state for previewers" decision.

### Enrolled student — unchanged

`is_enrolled` is true, so the previewer branch is never entered and the existing
`transaction.atomic()` path runs byte-for-byte as before.

## Error handling

| Condition | Behaviour |
|---|---|
| Previewer POSTs an empty answer | Validation context via `ephemeral_quiz_feedback`; attempt not consumed; matches the student path. |
| Previewer POSTs a malformed / absent `attempt` | `parse_attempt` floors to 1. Never raises. |
| Previewer POSTs an `attempt` beyond `max_attempts` | Question locks and reveals — same as a student on their final attempt. A previewer cannot use this to see a reveal a student could not: reaching the reveal *is* the normal terminal state of a question. |
| Previewer targets an element in another unit / a non-question element | Unchanged `get_object_or_404` / `Http404("not a question element")`, evaluated before the enrollment branch. |
| Viewer lacks course access entirely | Unchanged `PermissionDenied` from `can_access_course`, evaluated first. |
| Previewer POSTs to `quiz_finish` | Unchanged `PermissionDenied`. |
| Enrolled student, submitted quiz | Unchanged 409 / redirect via `_quiz_locked_response`. |

## Testing

Every new test must be **falsified before it is trusted**: delete or invert the behaviour it guards
and require it to go RED. This repository has shipped vacuous tests before.

### Persistence invariant — the load-bearing one

After a previewer POSTs an answer (correct, incorrect, empty, and beyond `max_attempts`), assert
**all three** of `QuizSubmission`, `QuestionResponse`, and `Attempt` have zero rows. Asserting only
`QuizSubmission` would miss a partial write.

### Render

- Previewer GET: inputs are **live** (no `disabled` on question inputs), the preview banner is
  present, the Finish form is absent, and `QuizSubmission` is still not created.
- Submitted quiz: inputs still `disabled` — proves the `quiz_submitted` / `previewing` split did not
  leak the previewer's liveness into the frozen case.
- Enrolled, fresh quiz: unchanged — Finish present, no banner.

### Grading parity

Drive a previewer and an enrolled student through the same question with the same answers and assert
the rendered feedback fragments agree on verdict, `attempts_left`, and lock state — for AUTO,
`NOT_MARKED`, and `REVIEW` marking modes.

### No-leak

Extend the existing guarantee (`tests/test_quiz_noleak.py`,
`tests/test_questions_2d_quiz_noleak.py`) to the previewer: while attempts remain, the response must
not contain the correct answer or the reveal template's output.

### Existing test to update

`tests/test_quiz_views.py:52` `test_quiz_unit_get_no_submission_for_unenrolled_preview` is the only
test pinning the old behaviour.

- `assert not QuizSubmission.objects.filter(unit=unit).exists()` — **load-bearing, keep unchanged.**
- `assert b"Finish quiz" not in resp.content` — still correct (Finish stays hidden); verify rather
  than assume.
- `assert b"disabled" in resp.content` — must flip to asserting the question inputs are live. Assert
  against the question inputs specifically, not a bare substring search, so an unrelated `disabled`
  elsewhere in the page cannot make the test vacuous.

### Shared-helper equivalence

Assert `views_manage.element_try`'s quiz branch still returns what it returned before the extraction,
so the refactor is provably behaviour-preserving at the site being refactored.

### e2e

One real-browser test: a non-enrolled staff user opens a quiz, answers a question, sees feedback, and
no submission exists afterwards. Must drive the real gesture (click/type), never `page.evaluate`.
`-m e2e` is mandatory or the test is silently deselected.

### UI verification

The preview banner is new UI: verify with Playwright screenshots in **both** light and dark mode,
judged separately — dark is never inferred from light.

### Tooling

All commands run through `uv run` (`uv run pytest`, `uv run ruff format --check`); bare `pytest` /
`ruff` / `python` are not on PATH.
