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
original quiz feature. It is also **not slideshow-related** — two non-slideshow `mat-pp` quizzes
(362, 841) render identically inert; the bug was first reported against a slide-split quiz only by
coincidence.

### Prose that documents the opposite behaviour

`views.py:1204` does not stand alone. **Five** prose sites assert the behaviour this change reverses,
and **all five are required edits** — leaving them is worse than the original bug, because the next
reader trusts them:

- `courses/views.py:1201-1203` — "Inputs are disabled + Finish hidden when the quiz is submitted OR
  the accessor is a non-enrolled previewer … a previewer gets a READ-ONLY quiz, never live forms that
  403 on submit."

  **Only the previewer half becomes false** — "READ-ONLY" and "never live forms". The submitted half
  stays true, and so does "Finish hidden" *for previewers*, which is exactly what Component 2
  requires the replacement comment to keep documenting (`read_only`'s sole remaining job). Do not
  delete the whole block; rewrite it around Component 2's required one-line `read_only` comment.
- `courses/views.py:860-866` — `check_answer`'s "This deliberately diverges from seen/quiz, which
  ignore previewers so authors don't pollute their own SCROLL-tracking and quiz analytics. It is
  those two specifically, NOT progress writes in general".

  **Add a clarifying clause; do NOT narrow `seen/quiz` to `seen`, and do not touch "those two".**
  An earlier draft of this spec called for that narrowing. It was wrong, and the comment's own gloss
  is why: its sense of *ignore* is **persistence** — "so authors don't pollute their own
  SCROLL-tracking and quiz analytics". Under that sense the sentence stays **true** after this
  change, because the entire design is a live gradeable quiz that *persists nothing*, so previewer
  quiz data still never reaches analytics. Narrowing it would delete an accurate statement and
  weaken the very guarantee this change is built on. Only under the *other* reading — "quiz rejects
  previewers' requests" — does it become false.

  What genuinely changed is that quiz now **serves** previewers live forms. So append a clause to
  that effect (e.g. "— quiz now serves previewers live forms, but still records nothing for them")
  and leave the persistence contrast, the "those two specifically" clause, and the `seen` rationale
  intact. The `seen` half remains load-bearing for
  `tests/test_courses_progress.py::test_previewer_seen_no_write_and_ignores_stored_completion`.
- `tests/test_unit_edit_link.py:328` — docstring justifying why the actor is enrolled, stating that
  `quiz_answer` raises `PermissionDenied` for previewers.
- `tests/test_unit_nav_render.py:800` — the same claim, in the same shape.
- `tests/test_quiz_views.py:61` — the inline comment
  `# Read-only preview: no Finish button, inputs disabled (no live forms that 403).`, which must be
  rewritten alongside the assertion beneath it.

So the claim "one test pins the old behaviour" is true only of *assertions*; five prose sites also
describe it.

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
- **The enrolled student path's *server-side* behaviour does not change.** Not its grading, attempt
  enforcement, lock-state machine, reveal gating, `[N]`/`[R]` neutral handling, or 409-on-submitted
  behaviour.

  **One deliberate carve-out:** the client-side `[data-quiz-locked]` freeze selector is widened, and
  that *is* observable to an enrolled student — it fixes an existing defect where a locked
  extended-response question stays editable until reload (Component 5). It is in scope as a defect
  fix, and this Non-goal must not be cited to skip it.

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
    """Grade `answer` without persisting anything.

    Returns the triple (stand_in, result, validation) — NOT a finished context —
    so callers can feed it to whichever renderer they need.
    Persists NOTHING: no QuizSubmission, no QuestionResponse, no Attempt.
    Mirrors quiz_answer's state machine exactly:
      - empty answer            -> (stand_in, None, True); mark() is NOT called
      - AUTO                    -> mark(); locked iff correct, or
                                   (max_attempts is not None and attempt >= max_attempts)
      - NOT_MARKED / REVIEW     -> result None, locked True (single submission)
    """
```

**The `max_attempts is not None` guard is mandatory, not defensive noise.** `max_attempts` is
nullable and `null` means *unlimited* — `courses/models.py:1591-1592` reads
`# null = unlimited attempts; consumed only in quiz units (dormant in lessons).` Every existing
implementation guards it (`views.py:1299`, `views.py:1331`, `views_manage.py:1755`, `quiz.py:49`).
Writing the rule without the guard raises
`TypeError: '>=' not supported between instances of 'int' and 'NoneType'` on the first AUTO question
authored with unlimited attempts.

**The return type is a triple, not a context dict, and that is load-bearing.** The no-JS path
(below) reuses `_quiz_render_feedback(request, node, element, question, response, *, result,
validation)`, which builds the feedback context *itself* from a `response` object and then reads
`response.latest_answer` for rehydration (`views.py:1248-1268`). A helper returning a finished
context could not be passed to it, and the implementer would be forced either to duplicate the whole
re-render body or to silently change the helper's contract.

`stand_in` is therefore a duck-typed `QuestionResponse` substitute carrying exactly the three
attributes its consumers touch:

| Attribute | Value | Read by |
|---|---|---|
| `.locked` | the ephemeral lock decision; **`False` unconditionally on the validation branch** | `quiz_feedback_context`, and `_quiz_render_feedback`'s new `st["locked"]` write |
| `.attempt_count` | `attempt`, or `attempt - 1` on the validation branch | `quiz_feedback_context` (for `attempts_left`) |
| `.latest_answer` | `answer_to_json(answer)` | `_quiz_render_feedback`'s `rehydrate` call |

**`.locked = False` on the validation branch is load-bearing, not a default.** `quiz_feedback_context`
copies `response.locked` into the context at `quiz.py:25` — *before* the `if validation: return ctx`
early exit at `quiz.py:28-29` — so a locked stand-in reaches
`_quiz_question_feedback.html:5`, which emits `{% if locked %}<span data-quiz-locked hidden>{% endif %}`
inside the **validation** panel. An implementer who reads "`[N]`/`[R]` → locked True" and hoists the
lock decision above the empty-answer guard makes an empty submit freeze the question: `quiz.js`
disables the controls on `[data-quiz-locked]`, and the no-JS path freezes it permanently through
`st["locked"]`. Use `locked=False, attempt_count=attempt - 1`, exactly as `views_manage.py:1747` does.
The enrolled path cannot reach the validation branch with a locked response at all
(`views.py:1298-1302` returns `_quiz_locked_response` first), so `False` is also the faithful mirror.

**But do not copy `views_manage.py:1747` wholesale.** That call site builds
`SimpleNamespace(locked=False, attempt_count=attempt - 1)` with **no `latest_answer`**, because
`element_try` renders the fragment directly and never calls `_quiz_render_feedback`. The previewer
branch routes *every* response through `_quiz_render_feedback`, validation included, and its no-JS
branch runs `rehydrate(question, response.latest_answer)` at `views.py:1265`. A stand-in missing that
attribute raises
`AttributeError: 'types.SimpleNamespace' object has no attribute 'latest_answer'` — a 500 on a path
the error table declares supported.

**So `ephemeral_quiz_feedback` builds one three-attribute stand-in on every branch.** All three
attributes are always present; only `.locked` and `.attempt_count` vary by branch, and
`.latest_answer` is always `answer_to_json(answer)`.

`.latest_answer` **must** be `answer_to_json(answer)`, not the raw `build_answer` output.
`rehydrate` (`courses/quiz.py:85-91`) is specified against a *stored* `latest_answer` — the output of
`answer_to_json` — and `answer_to_json` is what normalises a set to a sorted list and a tuple to a
list. A choice question's raw `set` happens to survive `set(…)` unchanged, which is exactly the kind
of accident that hides the bug until a tuple payload reaches it.

Because grading routes through the same `quiz_feedback_context` the student path uses, the
**no-leak guarantee is inherited rather than reimplemented**: the correct answer is withheld until
the question locks, exactly as for a student.

`views_manage.element_try`'s quiz branch collapses to `parse_attempt` + `ephemeral_quiz_feedback` +
its own `quiz_feedback_context(question, stand_in, result=…, validation=…)` call. Its observable
behaviour must not change.

### Component 2 — `courses/views.py`: unconflate the two flags

`build_quiz_context` gains a distinct `previewing` flag and stops overloading `read_only`:

| Context key | Meaning | Consumers |
|---|---|---|
| `quiz_submitted` | The submission is `SUBMITTED`; inputs frozen. | question templates (via `_quiz_article.html`) |
| `previewing` | `not enrolled` — see the derivation rule below. | preview banner |
| `read_only` | `quiz_submitted or previewing`; gates the Finish form only. | `_quiz_article.html` Finish block |

`read_only` is retained with its current value so the Finish form's condition is untouched — Finish
stays hidden for previewers, per the decided non-goal. The change is that `_quiz_article.html:12`
passes `quiz_submitted=quiz_submitted` rather than `quiz_submitted=read_only`, so a previewer's inputs
render **live**.

**Derivation rule — `previewing` must not cost a query.** `build_quiz_context` already calls
`is_enrolled(user, node.course)` at `views.py:1134` and **discards the result** (it is the condition of
an `if` whose only effect is creating the submission). Hoist it into a local —
`enrolled = is_enrolled(user, node.course)`, then `previewing = not enrolled` — rather than calling
`is_enrolled` a second time. This builder is otherwise carefully prefetched (`views.py:1113-1131`);
adding a second `Enrollment.objects.filter(...).exists()` round trip to every quiz render would be a
silent regression. (`not enrolled` is also exactly `submission is None`, the value `read_only` uses
today.)

`read_only` keeps its name but no longer means what the name says: after this change its sole job is
"the Finish form is unavailable", *not* "the page is inert". `build_quiz_context` must carry a
one-line comment saying so, or the next reader will helpfully reintroduce the conflation this change
exists to remove.

**The submitted-quiz freeze is defence-in-depth, not a live path.** `quiz_unit` redirects to
`quiz_results` before rendering whenever the submission is SUBMITTED (`views.py:1224`), and the only
other renderer of `quiz_unit.html` — `_quiz_render_feedback` — is reachable only after `quiz_answer`
has already returned `_quiz_locked_response` for a submitted submission (`views.py:1292-1293`). So
`_quiz_article.html` is never rendered with `quiz_submitted=True` today; `ctx["quiz_submitted"]`
(set at `views.py:1200`) currently has **zero consumers**, because the template reads `read_only`.
Wiring the template to `quiz_submitted` is therefore correct-by-construction rather than
behaviour-changing, and any test for it must target the renderer directly (see Testing).

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

Moving resolution ahead of the enrollment branch is a real, deliberate behaviour change: a previewer
targeting an element in another unit gets **404 instead of today's 403**. That is the point — the
previewer should get the student's 404 rules, not a coarser 403.

`quiz_finish` keeps `raise PermissionDenied` for non-enrolled users, unchanged.

**Why a client-supplied `attempt` is safe here — the invariant that must be stated, and tested.**
A client-controlled attempt counter makes this endpoint an on-demand answer oracle *for anyone who
reaches the previewer branch*. It is acceptable only because of a fact outside this file:
`courses/access.py:16-29` defines `accessible_courses` as **staff/superuser ⇒ all; else owned ∪
enrolled ∪ taught (non-archived groups)**. Therefore

> `can_access_course(u, c) and not is_enrolled(u, c)` ⟹ `u` is staff, the course owner, or a teacher
> of one of its groups.

A plain student can never reach the branch — they are either enrolled (and take the persisted path)
or denied outright. This invariant is load-bearing and invisible from `views.py`, and the repository
already carries an "access-widening reachability" lesson: a future widening of `accessible_courses`
would silently convert this into a student-reachable reveal endpoint. State it in a comment at the
branch, and pin it with the test named in Testing.

**Tripwire when writing those comments.** `tests/test_element_state_write_routes.py` regexes **raw
source, comments included**, across first-party files and asserts `EXPECTED_WRITE_COUNT = 3` for
`courses/views.py`. Its patterns include `\.element_state\s*=(?!=)` and `element_state\[…\]\s*=`. New
prose in `courses/views.py` must avoid those shapes or it reddens an unrelated suite — this has bitten
the repository before.

### Component 4 — `templates/courses/_quiz_article.html`: the preview banner

A previewer gets a visible, styled banner above the questions explaining the state — the missing
piece that made the current behaviour read as breakage:

> **Preview** — you are not enrolled in this course, so your answers are not recorded and the quiz
> cannot be finished.

The second clause is deliberate: the Finish button and the score summary are also absent for a
previewer, and the whole point of this change is that the page stops having unexplained gaps.

**Markup is pinned**, so the render test and the e2e locator have something durable to target:

```html
{% get_current_language as LANGUAGE_CODE %}
<aside class="alert alert--info" data-quiz-preview-notice
       lang="{{ LANGUAGE_CODE }}" aria-label="{% trans 'Preview notice' %}">
  <strong>{% trans "Preview" %}</strong> — {% trans "you are not enrolled …" %}
</aside>
```

- `<aside>` keeps the banner in landmark navigation as complementary content, with an `aria-label` to
  name it.
- **No `role="status"`.** Two reasons, both disqualifying: a live region only announces mutations
  that occur *after* it is in the accessibility tree, and this banner is server-rendered and present
  at first paint on every render path — so it would never announce anything. Worse, `role="status"`
  **overrides** `<aside>`'s implicit `complementary` role, removing the banner from landmark
  navigation — the exact opposite of why `<aside>` was chosen.
- `lang="{{ LANGUAGE_CODE }}"` is required because the banner sits inside
  `<article class="quiz" lang="{{ course.language }}">` (`_quiz_article.html:2`), so without it a
  Polish-UI string is announced as English inside an English course. `_unit_crumbs.html:11-15`
  documents this exact trap. **`LANGUAGE_CODE` must be fetched with `{% get_current_language %}`** —
  `django.template.context_processors.i18n` is *not* enabled (`config/settings/base.py:66-74`), so it
  is not otherwise in the context.
- `<strong>`, not a heading — the banner must not enter the document outline.

Rendered only when `previewing` is true.

**Placement is specified, not left to taste:** the banner renders **once, outside the
`{% for slide in slides %}` loop** — immediately after the `<h1 class="lesson-unit__title">`. Inside
the loop it would render once per slide; inside the *first* slide it would vanish the moment the
previewer advances, since `slideshow.js` shows one slide at a time. The original bug report was
against a slide-split quiz, so this is the case most likely to be got wrong.

**Class:** reuse `.alert .alert--info` (`core/static/core/css/app.css:211-216`), the existing
page-level notice pattern. Explicitly **not** `.callout` (`courses/static/courses/css/courses.css:1414-1459`)
— that is the *content-element* callout; it expects `.callout__header` / `__icon` / `__heading` /
`__body` children and a `--callout-accent` modifier, and reusing it would make a system message look
like authored content. `.alert` lives in the global `app.css`, which every page already loads, so no
new stylesheet link is needed.

**i18n:** new user-visible strings go into both the `pl` and `en` catalogues via
`uv run python manage.py makemessages -l pl -l en --no-obsolete`, then
`uv run python manage.py compilemessages`. Before committing, check for `#, fuzzy` entries —
`makemessages` pre-fills them from unrelated msgids, and clearing one means deleting **both** the
`#, fuzzy` line and the `#| msgid` line. `.mo` files are tracked binaries with no 3-way merge, so
regenerate them on a branch that is up to date with master. `tests/test_i18n_po_health.py` guards the
whole catalogue.

### Component 5 — `courses/static/courses/js/quiz.js`: client-side attempt tracking

The ephemeral endpoint is stateless, so the client owns the attempt counter. `quiz.js` mirrors the
already-shipped logic at `editor.js:220-258`:

- read `data-attempts-made` (default `0`) from `form.closest("[data-question]")`;
- append `attempt` = made + 1 to the POST body;
- on response, increment `data-attempts-made` **unless** the feedback carries `.is-validation` (an
  empty answer does not consume an attempt);
- the existing `[data-quiz-locked]` handling disables inputs on terminal states (see the caveat
  below).

Three facts an implementer needs that are easy to get wrong:

- **No server template ever emits `data-attempts-made`.** It appears only in
  `courses/static/courses/js/editor.js:220,256`. The attribute is created client-side on the first
  response; the "default `0`" is therefore the only initial value, not a server-seeded one.
- **The counter lives on an ancestor, not the form.** `[data-question]` is the outer
  `<div class="el el--question" data-question>` (e.g. `choicequestion.html:2`), while the existing
  `quiz.js` handler holds only `form`. A `form.closest("[data-question]")` lookup must be added; it
  has no counterpart in the current file.
- **Null-guard it.** `editor.js` guards the lookup twice (`var made = qEl ? … : 0`, then
  `if (!qEl) return;`). The quiz mirror must degrade to attempt 1 rather than throw when
  `[data-question]` is absent.

The counter is gated so the enrolled path is behaviourally unaffected: the server ignores `attempt`
entirely on the enrolled path, where attempt state comes from the persisted
`QuestionResponse.attempt_count`.

**`attempt` is a reserved answer-POST field name.** `quiz.js` now adds it to every POST **from the
per-question submit handler**, enrolled path included. The Finish flush at `quiz.js:61-73` builds its
own `new FormData(f)` per open form and hits the same endpoint; it deliberately does **not** append
`attempt` — the server ignores the field on the enrolled path, and Finish is hidden for previewers,
so the flush has no attempt semantics to carry. Leave that block unedited. The body is fed straight to
`question.build_answer(request.POST)`. This is safe because all ten `build_answer` implementations
read only `choice`, `answer`, `blank`, `slot`, and `row_<pk>` (`courses/models.py:1693, 1820, 1849,
1883, 1905, 1965, 2017, 2076, 2159, 2254`) — verified, not assumed. Recorded so a future question
type does not quietly claim the name: **no `build_answer` may read `attempt`**; it is consumed only
by `parse_attempt`.

**Caveat on the `[data-quiz-locked]` freeze, unchanged from today.** `quiz.js:45-47` disables only
`form.querySelectorAll("input, button")`, which misses **two** control families:

| Family | Control | Example |
|---|---|---|
| 2D / grid | wrapping `<fieldset>` — which also covers every `<select name="slot">`, since those render *inside* it (`dnd.py:85, 107, 126`) | `dragtoimagequestionelement.html:7`, `multigridquestionelement.html:7`, `matchpairquestionelement.html:7` |
| extended response | bare `<textarea>`, **no fieldset at all** | `extendedresponsequestionelement.html:7-9` |

Two residual families, not three: `select` appears in the widened selector defensively only, because
disabling the fieldset already disables the selects inside it.

For an enrolled student the next page load repairs this; a JS previewer never gets a server render
carrying `locked`, so those controls stay interactive after locking. Harmless today only because the
Check button *is* disabled, so nothing can actually be resubmitted.

**Accepted residual — the widening freezes form *controls*, not the JS-built drag-and-drop targets.**
For drag-fill / match-pair / drag-to-image, the `<select name="slot">` is not the interaction surface
once JS runs: `dnd.js:171,188` sets `sel.style.display = "none"` and builds
`<span class="dnd__slot">` / `<span class="dragimage__target">` drop targets with `click` handlers
(`dnd.js:156,198`). **`fieldset[disabled]` does not disable spans** — `disabled` propagates only to
form controls — and `tapTarget`'s "unarmed + filled → clear" branch (`dnd.js:95-105`) calls
`setSelect(sel, "")`, which works fine on a hidden, disabled select. So after `[data-quiz-locked]` a
JS previewer can still tap a filled slot and wipe their own answer out from under the
"Answer recorded" panel, with no subsequent server render to repair the display.

This is **accepted, not fixed**, and the reason is the same as above: the Check button is disabled, so
nothing can be resubmitted and no state is corrupted — only the previewer's own display. Closing it
properly means teaching `dnd.js` to no-op when its select is `disabled`, which changes drag-and-drop
behaviour on the enrolled path too and is out of scope here.

**Consequence for tests:** do **not** write a "locked DnD question is inert for a previewer" test — it
would fail correctly. Scope any DnD freeze assertion to the form controls.

Fix it for both paths by widening the selector to
`"input, button, select, textarea, fieldset"`. Note that `fieldset` alone is **not** sufficient — the
extended-response `<textarea>` has no wrapping fieldset, so on the *enrolled* path a student who
submits an extended-response question currently sees "Submitted for review" beside a still-editable
answer box until the next page load. The full selector is a strict improvement to both paths, not a
scope expansion.

**Widen `editor.js` in the same commit.** `courses/static/courses/js/editor.js:261` freezes the
authoring "try it" preview with a similarly-too-narrow selector and misses the same families. The two
are **not** identical today and the post-change form of each is specified here so they do not diverge
silently:

| Site | Before | After |
|---|---|---|
| `quiz.js:46` | `form.querySelectorAll("input, button")` | `form.querySelectorAll("input, button, select, textarea, fieldset")` |
| `editor.js:261` | `qEl.querySelectorAll("input, button[type=submit]")` | `qEl.querySelectorAll("input, button[type=submit], select, textarea, fieldset")` |

`editor.js` **keeps** its `[type=submit]` qualifier: its root is the whole `[data-question]` element
rather than the form, so bare `button` there could reach controls the quiz freeze never touches. (No
non-submit `<button>` exists inside a question form today, so the choice is currently unobservable —
which is exactly why it must be written down rather than decided silently.) Leaving it
would let the two client-side freezes diverge immediately after a change whose stated rationale is
that code-identical duplicates rot apart (issue #169) — and it would be a strange look to extract the
Python half to stop twin drift while creating fresh drift in the JS half. Widen both.

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
    -> stand_in, result, validation = ephemeral_quiz_feedback(
           question, question.build_answer(POST), attempt)
    -> _quiz_render_feedback(request, node, element, question, stand_in,
                             result=result, validation=validation)
                                                     [NO transaction, NO writes]
quiz.js  -> swap [data-question-feedback]; bump data-attempts-made unless .is-validation;
            disable inputs iff [data-quiz-locked]
```

**Both previewer response shapes go through the one existing renderer.**
`_quiz_render_feedback` already branches on `_wants_fragment(request)`, so passing the ephemeral
stand-in in place of a `QuestionResponse` serves the JS fragment *and* the no-JS full page with a
single call and no duplicated re-render body. This is the whole reason `ephemeral_quiz_feedback`
returns a triple rather than a context.

### Previewer, POST an answer (no JS)

`_wants_fragment(request)` is false, so `_quiz_render_feedback` takes its full-re-render branch:
rebuild the quiz context, inject this question's rendered fragment into
`render_states[element.pk]["feedback_html"]`, and rehydrate from `stand_in.latest_answer` — which is
why that attribute exists and why it must hold `answer_to_json(answer)`.

**`_quiz_render_feedback` needs exactly ONE added line: `st["locked"] = response.locked`.**
It currently sets `feedback_html`, `selected_ids`, and `submitted_values` on the render state, but
not `locked`. On the enrolled path that is fine: `build_quiz_context` re-reads the just-saved
`QuestionResponse` and derives it (`views.py:1162`). A previewer has `responses == {}`, so
`st["locked"]` is `False` for every question.

**Do NOT also write `st["attempts_left"]`** — that was considered and rejected for two independent
reasons, either of which is sufficient:

1. **It is not a no-op on the enrolled path; it is a regression.** `quiz_feedback_context` returns
   early on the validation branch (`quiz.py:28-29`, `if validation: return ctx`) with
   `"attempts_left": None`, before the computation at `quiz.py:49-50` is ever reached. Meanwhile
   `build_quiz_context` has already derived a real number from a *non-validation* context
   (`views.py:1176`). Concretely: enrolled student, AUTO, `max_attempts=3`, one wrong attempt
   recorded, then a no-JS POST with an empty answer → `build_quiz_context` sets
   `st["attempts_left"] = 2` and the write would clobber it with `None`.
2. **It is dead in quiz mode anyway.** `st["attempts_left"]` flows through `_quiz_article.html:12` →
   `render_element` → the per-type template context, and the only template reading `attempts_left`
   is `_quiz_question_feedback.html:33` — which quiz mode never includes, because every question
   template renders `{% if mode == "quiz" %}{{ feedback_html|safe }}` and the fragment bakes its own
   `attempts_left` at render time.

Only `locked` is load-bearing, and only `locked` gets written.

Left unfixed, that is a real defect, not a cosmetic one: the injected fragment still emits
`<span data-quiz-locked hidden>` — it does so for **every** `NOT_MARKED`/`REVIEW` question on first
submit, and for any AUTO question that is correct or at `max_attempts` — while
`choicequestion.html:15`/`:29` and its siblings gate `disabled` on `{% if quiz_submitted or locked %}`,
both now false. The previewer would see "Answer recorded", or the revealed answer, sitting next to an
enabled Check button, and could resubmit a single-submission `[N]`/`[R]` question forever.

`st["locked"] = response.locked` **is** a true no-op on the enrolled path — it writes the value
`build_quiz_context` already derived from the just-saved response — so this stays behaviour-preserving
for students while making the previewer path correct.

Because the previewer has no server-side attempt state, a no-JS previewer is pinned at attempt 1.
Consequence, accepted: for `max_attempts >= 2` they always see the withhold branch and never the
wrong-on-last-attempt reveal. At `max_attempts = 1` — the model default — attempt 1 *is* the last
attempt, so the first wrong submit locks and reveals, identically to a student. Either way this is a
view no wider than a student's — it leaks nothing — and it is the direct, stated cost of the "no
server-side attempt state for previewers" decision.

**Accepted consequence: no-JS previewer feedback is single-question and non-cumulative.** On the
enrolled path the rebuilt context restores every *other* question's `feedback_html`, `locked`,
`selected_ids`, and `submitted_values` from the persisted rows (`views.py:1170-1181`). A previewer has
`responses == {}`, so every question except the one just answered comes back blank and unlocked: a
no-JS previewer who answers Q1 then Q2 sees Q1's feedback vanish, its answer cleared, and its Check
button live again. This follows directly and unavoidably from "persists nothing" — there is nowhere
to restore Q1's state from. It is stated here so it is a recorded consequence rather than a surprise,
and it narrows the general "sees exactly the feedback a student would see" claim: that holds
per-question for the JS path, not across questions for the no-JS path.

Routing through `_quiz_render_feedback` also inherits `unit_nav`, which the page genuinely requires:
`quiz_unit.html` renders through `_unit_shell.html` (iterates `unit_nav.tree`) and `_unit_footer.html`
(reads `unit_nav.course_progress` / `.prev` / `.part_progress`). `build_quiz_context` does **not** set
it — `quiz_unit` (`views.py:1231`) and `_quiz_render_feedback` (`views.py:1260`) each add it
separately. A hand-rolled previewer branch that forgot `build_unit_nav` would ship a nav-less page
green, which is precisely why the previewer must not get its own re-render body.

### Enrolled student — unchanged

`is_enrolled` is true, so the previewer branch is never entered and the existing
`transaction.atomic()` path runs byte-for-byte as before.

## Error handling

| Condition | Behaviour |
|---|---|
| Previewer POSTs an empty answer | Validation context via `ephemeral_quiz_feedback`; attempt not consumed; matches the student path. |
| Previewer POSTs a malformed / absent `attempt` | `parse_attempt` floors to 1. Never raises. |
| Previewer POSTs an `attempt` beyond `max_attempts` | Question locks and reveals — same as a student on their final attempt. A previewer cannot use this to see a reveal a student could not: reaching the reveal *is* the normal terminal state of a question. |
| `max_attempts is None` (unlimited) | Never locks on a wrong answer; `attempts_left` stays `None`; the previewer may retry indefinitely — identical to the student. Requires the `is not None` guard in `ephemeral_quiz_feedback`. |
| Previewer POSTs to an already-locked question | **Re-grades and returns a fresh 200 fragment**, where an enrolled student gets 409 / redirect via `_quiz_locked_response` (`views.py:1297-1302`). Accepted: the previewer branch is stateless by design, so there is no server-side "already locked" to detect. Nothing leaks — a locked question's reveal is content the previewer had already earned. |
| Viewer was enrolled, submitted, then unenrolled | Keyed on `is_enrolled`, so they are treated as a previewer: live gradeable quiz, answers discarded, their frozen `SUBMITTED` row untouched and not shown. Accepted rather than special-cased — the banner states plainly that answers are not recorded, and defining `previewing` as "not enrolled **and** no submission exists" would add a query plus a fourth page state for a rare transition. |
| Previewer targets an element in another unit / a non-question element | **Changed for previewers: 403 → 404.** Resolution now precedes the enrollment branch, so a previewer gets the student's `get_object_or_404` / `Http404("not a question element")` rules instead of today's blanket `PermissionDenied`. Deliberate. |
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

- Previewer GET: inputs are **live**, the preview banner is present, the Finish form is absent, and
  `QuizSubmission` is still not created.

  "Live" must be asserted **per markup family**, or the test is vacuous for most question types.
  There are three families, and the test must name at least one of each:

  1. **control-level** — `disabled` on the `<input>`/`<button>` itself (choice, short text, short
     numeric);
  2. **fieldset-wrapped** — `disabled` on a wrapping `<fieldset>`
     (`dragtoimagequestionelement.html:7`, `multigridquestionelement.html:7`, and likewise
     choicegrid / matchpair / dragfill);
  3. **bare textarea** — `extendedresponsequestionelement.html:7-9`, which has no wrapping fieldset
     and so is missed by both of the other checks.

- Multi-slide previewer GET: the banner appears exactly once and outside every `.slide`.

- Submitted quiz — **do not test this through `quiz_unit`**. That view redirects to `quiz_results`
  before rendering (`views.py:1224`), so a GET returns 302 and the assertion would be vacuous. Test
  the renderer directly:

  ```python
  render_to_string("courses/_quiz_article.html", build_quiz_context(node, user))
  ```

  with a SUBMITTED submission, and assert the inputs are frozen. The context **must** come from
  `build_quiz_context`, not be hand-built.

  **Be honest about what this test can and cannot falsify.** Because
  `read_only = quiz_submitted or previewing`, `read_only ⊇ quiz_submitted` — there is no
  `build_quiz_context` state with `quiz_submitted=True` and `read_only=False`. A SUBMITTED enrolled
  submission yields both true, so `quiz_submitted=read_only` and `quiz_submitted=quiz_submitted`
  render byte-identical HTML and this test passes either way. It guards "a SUBMITTED quiz still
  freezes its inputs" — the mutation it catches is `quiz_submitted` being dropped from line 12
  altogether, **not** a revert to `read_only`. The test that actually falsifies the argument-source
  change is the **previewer-GET liveness** test above, since `previewing=True` is the only state that
  discriminates the two spellings.

  **Do not use `render_element(..., quiz_submitted=True)` for this.** The change under test is the
  argument *source* on `_quiz_article.html:12` (`quiz_submitted=read_only` →
  `quiz_submitted=quiz_submitted`); passing `quiz_submitted=True` straight in bypasses that line
  entirely and stays green no matter what line 12 says. The same vacuity applies to the existing
  `q.render(element=el, mode="quiz", quiz_submitted=False, …)` precedent at
  `tests/test_quiz_render.py:14-20`. (`render_element` is also
  `@register.simple_tag(takes_context=True)` at `courses_extras.py:25-27`, so a direct Python call
  would need a context dict as its first positional argument.)

- Enrolled, fresh quiz: unchanged — Finish present, no banner.

### Grading parity

Drive a previewer and an enrolled student through the same question with the same answers and assert
the rendered feedback fragments agree on verdict, `attempts_left`, and lock state — for AUTO,
`NOT_MARKED`, and `REVIEW` marking modes.

**Both sides must POST with `HTTP_X_REQUESTED_WITH="fetch"`.** `_quiz_render_feedback` branches on
`_wants_fragment(request)` (`views.py:87`), and the Django test client does not send that header by
default — so without it the test compares two *full pages*, which this spec elsewhere states
provably differ (banner present, Finish absent, every other question blank and unlocked). Parity is a
**fragment-mode claim only**; it does not contradict the "no-JS previewer feedback is single-question
and non-cumulative" consequence recorded above, because that describes the other branch. The existing
suite convention for this header is at `tests/test_unit_edit_link.py:323-326`.

**The previewer side must POST `attempt=N` explicitly.** The Django test client runs no JS, so nothing
supplies the counter; `parse_attempt` floors to 1, and a previewer's second POST would still be
attempt 1 while the student's is attempt 2 — the fragments then diverge on `attempts_left` and lock
state for every multi-attempt question. Posting `attempt=N` is the test-level stand-in for
`data-attempts-made`. An implementer who hits this divergence and "fixes" it with server-side attempt
state has implemented the explicit non-goal.

**Stopping condition — parity is asserted only for POSTs the student path accepts**, i.e. up to and
including the locking submission. Past that point the two paths *provably* diverge and are meant to:
a further student POST returns 409 / redirect via `_quiz_locked_response` (`views.py:1297-1302`),
while the stateless previewer branch returns a fresh 200 fragment. State the boundary **ordinally-free
for both modes**: it is the POST *after the locking submission*, where **the locking submission** is
the single first real submit for `[N]`/`[R]` and the correct-or-exhausted one for AUTO. Empty POSTs
never advance toward it (they
lock nothing), so an inserted empty POST shifts the boundary by one position and any rule pinned to
"the second POST" would stop a POST early. A test that keeps driving past the boundary compares a 409
body against a feedback fragment and fails for the wrong reason.

**How `N` advances is also part of the rule.** `N` increments only after a POST whose response is
*not* the validation panel — the server-side analogue of `quiz.js`'s "increment unless
`.is-validation`" guard, and a faithful mirror of the enrolled path, where an empty answer takes the
`answer_is_empty` branch (`views.py:1305-1311`) and never increments `attempt_count`. A driver that
increments `N` once per POST desynchronises the two sides the moment the sequence contains an empty
submit, and the fragments then diverge on `attempts_left` for the wrong reason. **Include at least
one empty POST in the parity sequence** so this rule is actually exercised rather than merely
written down.

### The enrolled path must keep ignoring `attempt`

`quiz.js` will now send a client-controlled `attempt` on **every** quiz answer POST, students
included. Today `quiz_answer` never reads it (`views.py:1288-1347`), and the reserved-name rule above
says no `build_answer` may. Neither fact is currently pinned by a test, and the consequence of losing
it is severe: once `parse_attempt` lives in `courses/quiz.py`, plumbing it into the shared answer path
is an obvious-looking tidy-up, and it would let a real student POST `attempt=99` to force
`response.locked = True` and the reveal via `views.py:1330-1333` — an answer oracle on the *persisted*
path, with the suite still green.

Required test: an enrolled student POSTs a **wrong** answer with `attempt=99` to an AUTO question with
`max_attempts=3`; the response must still show `attempts_left = 2`, must not contain the reveal, and
`QuestionResponse.attempt_count` must be `1`.

### Access invariant — both bounds

**Lower bound.** A plain authenticated user who is **not** enrolled, not staff, not the owner, and
not a group teacher must still get `PermissionDenied` from `quiz_answer` — i.e. must never reach the
ephemeral branch. This pins the `accessible_courses` invariant that makes the client-supplied
`attempt` safe.

**Upper bound — the one a mis-keyed branch would break silently.** An `is_staff` user (or the course
owner) who **is** enrolled must still take the persisted path: POSTing an answer creates a
`QuizSubmission`, a `QuestionResponse`, and an `Attempt`. **No existing enrolled-path quiz test
asserts that a row was written for a privileged actor** — the two that drive `quiz_answer` as an
enrolled course *owner* (`tests/test_unit_edit_link.py:331-333` and `tests/test_e2e_quiz.py::_seed_quiz`,
which enrols the owner) assert nothing about persistence. So a branch mistakenly keyed on
`request.user.is_staff` or `can_manage_course` instead of `not is_enrolled(...)` would pass the entire
suite while silently stopping grade capture for every enrolled teacher. The branch condition is
`not is_enrolled(request.user, course)` and nothing else.

### No-leak

Extend the existing guarantee (`tests/test_quiz_noleak.py`,
`tests/test_questions_2d_quiz_noleak.py`) to the previewer: while attempts remain, the response must
not contain the correct answer or the reveal template's output.

**Construct the question with `max_attempts >= 2` and POST `attempt=1`.**
`QuestionElement.max_attempts` defaults to `1` (`courses/models.py:1592`), so with the default the
first wrong answer immediately satisfies `attempt >= max_attempts`, locks, and reveals — there is no
"while attempts remain" state to test, and the test would be vacuous. The existing fixtures already
do this (`tests/test_quiz_noleak.py:16` uses `max_attempts=3`;
`tests/test_questions_2d_quiz_noleak.py:25` and `:49` use `2`). Stated here so nobody "fixes" a red
test by weakening the withhold gate.

### No-JS previewer

- An `[N]`/`[R]` question renders `disabled` inputs after one no-JS submit — the direct regression
  test for the `st["locked"]` fix.
- An **empty** previewer POST emits no `data-quiz-locked` and leaves the inputs live — the regression
  test for `stand_in.locked = False` on the validation branch.
- The previewer twin of `tests/test_unit_nav_render.py:799`
  `test_crumb_survives_the_no_js_quiz_answer_re_render` — proves the re-render still carries
  `unit_nav`.

### Existing test to update

`tests/test_quiz_views.py:53` `test_quiz_unit_get_no_submission_for_unenrolled_preview` is the only
test whose *assertions* pin the old behaviour. The five prose sites listed under "Prose that
documents the opposite behaviour" also describe it, and all five are required edits.

- `assert not QuizSubmission.objects.filter(unit=unit).exists()` — **load-bearing, keep unchanged.**
- `assert b"Finish quiz" not in resp.content` — still correct (Finish stays hidden); verify rather
  than assume.
- `assert b"disabled" in resp.content` — must flip to asserting the question inputs are live. Assert
  against the question inputs specifically, not a bare substring search, so an unrelated `disabled`
  elsewhere in the page cannot make the test vacuous.

### Shared-helper equivalence

The extraction must be provably behaviour-preserving at `views_manage.element_try`'s quiz branch.
"Still returns what it returned before" is not something a test can reference after the refactor, so
enumerate the branch's five distinct states (`views_manage.py:1741-1761`) as required assertions on
the rendered fragment:

1. malformed / absent `attempt` → floors to 1. **Must be exercised at `max_attempts >= 2`**, or it is
   vacuous: at the model default of `1`, `attempt=1`, `attempt=""`, and `attempt=5` all satisfy
   `attempt >= max_attempts`, all lock, and all render an identical reveal — the assertion cannot tell
   a working `parse_attempt` from one returning garbage. Use e.g. `max_attempts=3` with a wrong answer
   and assert the rendered "2 attempts left", so the floor is observable. (`tests/test_element_try.py`'s
   `_question` helper defaults to `max_attempts=1`, so this must be set explicitly.)
2. empty answer → validation panel, attempt not consumed;
3. AUTO wrong with attempts left → withhold (no reveal, `attempts_left` shown);
4. AUTO wrong at `max_attempts` → locked + reveal;
5. `[N]`/`[R]` → locked, neutral "recorded" panel, no mark result.

These belong alongside the existing coverage in `tests/test_element_try.py` and
`tests/test_choice_inline_feedback.py:123`, which already exercise parts of this branch.

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
