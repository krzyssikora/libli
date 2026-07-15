# Inline per-option feedback for multiple-choice questions

## Purpose

`ChoiceQuestionElement` (the platform's single- and multiple-choice MCQ) already lets
authors attach per-option `feedback` text to each `Choice`. Today that feedback surfaces
under two narrow rules:

1. **What shows** — only *selected distractors* (`c.pk in answer and c.feedback and not
   c.is_correct`), and only when the whole answer is wrong (the "nudge").
2. **Where it shows** — in a **duplicate list at the bottom** of the element. On a wrong
   answer, `_reveal_choice.html` re-lists every option a second time below the form, with a
   ✓ on correct options and the nudge text under selected wrong ones.

Two problems follow:

- **Omission errors get no feedback.** If the student's mistake is *missing* a correct
  option (e.g. "select all that apply", correct = {A, C}, student picks only {A}), they
  selected no wrong option, so nothing is shown — even though they were wrong.
- **In lessons the feedback is spatially divorced from the option it describes**, and the
  options are rendered twice (once as the live form, once in the bottom reveal list).

This change makes per-option feedback **symmetric** (it covers both wrong picks *and*
missed-correct options) and moves it **inline, directly beneath the option it refers to**,
in the lesson consumption view — while keeping the existing bottom reveal list in the
quiz-feedback and quiz-results views, where that list is the *only* place the options
appear and therefore is not a duplicate.

This is an **enhancement to an existing element**, not a new element type. There is **no new
model, no migration, no `ELEMENT_MODELS` entry, no transfer plumbing, no add-menu palette
card, and no new form** — `Choice.feedback` already exists and already round-trips through
course export/import.

### Non-goals

- No affirming feedback on options the student handled correctly (no "smug" text when a
  correct option was correctly selected or a distractor correctly avoided). Feedback stays
  **corrective-only**, shown exactly on the options the student got wrong.
- No change to the other question types (`shorttext`, `shortnumeric`, `fillblank`,
  `dragfill`, `matchpair`, `dragimage`, `choicegrid`, `multigrid`). Their bottom-reveal
  pattern is untouched.
- No change to marks/scoring. This is presentational feedback only; `fraction` and
  correctness are unchanged.
- No change to the on-disk transfer format (`FORMAT_VERSION` is **not** bumped).

## Definitions

Let `correct` = the set of choice pks with `is_correct=True`, and `answer` = the student's
validated set of selected choice pks (already produced by
`ChoiceQuestionElement.build_answer`).

- **annotated set** = the symmetric difference `answer △ correct`, restricted to options
  that carry non-empty `feedback` text:
  - `selected ∧ ¬correct` — a distractor the student fell for.
  - `¬selected ∧ correct` — a correct option the student missed.
- On a fully-correct answer (`answer == correct`) the symmetric difference is empty, so the
  **annotated set is empty** and no feedback is shown. This is the intended "stay quiet when
  right" behaviour.

## Architecture / components

### 1. Marking rule — `ChoiceQuestionElement.mark()` (`courses/models.py`)

Replace the `nudged` computation with the symmetric **annotated** set.

Current:

```python
nudged = (
    frozenset(
        c.pk for c in choices
        if c.pk in answer and c.feedback and not c.is_correct
    )
    if not is_correct
    else frozenset()
)
```

New (semantics: symmetric difference, restricted to options with feedback text):

```python
annotated = frozenset(
    c.pk for c in choices
    if c.feedback and ((c.pk in answer) != c.is_correct)
)
```

Notes:

- `(c.pk in answer) != c.is_correct` is exactly "selected XOR correct" = the option is in
  the symmetric difference (student got *this option* wrong).
- The outer `if not is_correct` guard is **dropped**: it is now redundant, because a
  fully-correct answer already yields an empty symmetric difference. Dropping it is
  behaviour-preserving for the correct case and is what enables the omission case (a wrong
  answer with only missed-correct options now populates `annotated`).
- `reveal` (the full correct-set, used to render ✓ marks) is **unchanged**.

### 2. `MarkResult` field rename — `nudged` → `annotated` (`courses/marking.py`)

`MarkResult.nudged` is choice-specific. Rename the field to `annotated` to match its new,
broader meaning, updating **every** producer and consumer — there are **two of each**, not
one:

- **Producers** (both construct a `MarkResult` carrying this field):
  1. `ChoiceQuestionElement.mark()` (`courses/models.py`) — the primary marker.
  2. `courses/views.py:_stored_result()` — reconstructs a `MarkResult` from a stored
     `QuestionResponse` for the quiz-feedback render (reached via `build_quiz_context`). It
     both **reads** `m.nudged` and **passes** `nudged=` to the `MarkResult` constructor. Miss
     this and the quiz-feedback render 500s (`AttributeError`/`TypeError`) for every
     submitted AUTO choice question.
- **Consumers** (read the field):
  1. `_reveal_choice.html` (template).
  2. `_stored_result()` itself (the read above).

Update the dataclass definition + docstring, both producers, and the template consumer.
Test references to `nudged` are updated in the same change. A repo-wide grep for `nudged`
(non-test) is the completeness guard.

### 3. Lesson render — inline feedback in the choices list (`choicequestion.html`)

The change is made **in place** in `choicequestion.html` — no separate body partial is needed,
because both the JS-fragment path and the no-JS path now re-render the whole element through
`render()` (§4), and the JS extracts the form body from that full-element response client-side
(§5).

- `choicequestion.html`'s `<form>` gains the `data-question-inline` hook, telling the JS to
  swap the form body rather than only the bottom slot (see §5).

**Per-option annotations render only on the options the student got wrong** — i.e. only for
`c.pk in mark_result.annotated`. Non-annotated options (correctly selected, or a distractor
correctly avoided) get **no marker and no feedback** — this keeps the feature corrective-only
(the non-goal) and means a **fully-correct answer shows nothing per-option**, only the bottom
verdict.

The inline per-option block is gated on **`mode == "lesson"` AND `c.pk in
mark_result.annotated`** (mark_result presence alone is *not* the gate). The `mode == "lesson"`
condition mirrors the bottom-slot reveal suppression (below) and makes the "inline in lessons,
reveal-list in quiz" split explicit rather than relying on the unstated invariant that the quiz
form render never passes a `mark_result`. (That invariant holds today — the quiz form render
uses `mode="quiz"` with no `mark_result` — but gating on `mode` keeps a future change that
threads `mark_result` into the quiz form from leaking inline markers that duplicate the reveal
list.)

Concretely, for each choice `<li>` when the gate holds, insert **as siblings after the
`<label>`** (not inside it — keeping the `<label>` boundary clean for accessibility):

- a **per-option marker** `<span>` distinguishing the two mistake kinds, with a stable class
  the styling pass and the rendering test both anchor on:
  - `c.pk in selected_ids` (a trap the student picked) → `class="question__choice-marker
    question__choice-marker--wrong"`, glyph ✗;
  - `c.pk not in selected_ids` (a correct option missed) → `class="question__choice-marker
    question__choice-marker--missed"`, a glyph distinct from both ✓ and ✗ (final glyph is a
    frontend-design choice; it must not read as "you got this right"). The test asserts on the
    `--missed` class, not the glyph;
- an inline `<p class="question__choice-feedback">{{ c.feedback }}</p>` (membership in
  `annotated` already implies non-empty feedback).

This removes the earlier contradiction where a fully-correct answer would have stamped ✓ on
every correct option: no per-option markers are emitted when `annotated` is empty.

**Bottom slot in lesson mode.** The `[data-question-feedback]` slot keeps **only** the verdict
(✓ Correct / ✗ Incorrect) and the author `explanation`; it no longer includes
`_reveal_choice.html`. Suppression is done at **two** load-bearing points (see §4 for the
delivery that makes both fire):

1. `ChoiceQuestionElement.render()` passes `reveal_template=None` **when `mode == "lesson"`**
   (both the JS-fragment re-render and the no-JS full-page re-render flow through `render()`),
   instead of unconditionally `self.REVEAL_TEMPLATE`. **This gate goes only in the
   `ChoiceQuestionElement.render()` override (`models.py:1222`), which is a near-verbatim copy
   of the base `QuestionElement.render()` — the base method must remain unchanged.** DRY-ing
   the `mode` gate up into the base would set `reveal_template=None` for *every* other question
   type on the no-JS lesson path, silently dropping their inline reveal.
2. `_question_feedback.html`'s reveal include is re-guarded on **truthiness**:
   `{% if not mark_result.correct and reveal_template %}{% include reveal_template %}{% endif
   %}`. Without this, a wrong-answer render with `reveal_template=None` hits `{% include None
   %}`, which raises `TemplateDoesNotExist` (a 500), because the current guard tests only
   `not mark_result.correct`. The sibling `_quiz_question_feedback.html` and `quiz_results.html`
   already guard on `{% if reveal_template %}`; this aligns `_question_feedback.html` with them.
   Quiz/results pass a real `reveal_template`, so their reveal list is unaffected.

Repopulation of `selected_ids` (checked state on retry) and the `disabled` handling for
`quiz_submitted`/`locked` are preserved exactly as today (they come free from rendering through
`render()` — see §4).

### 4. Lesson delivery — `check_answer` returns the re-rendered form body (`courses/views.py`)

Today the JS branch of `check_answer` (`views.py:524-529`) returns only
`_question_feedback.html` (verdict + reveal) built from `question.feedback_context(result)`,
swapped into the bottom slot. That context is deliberately thin — it does **not** carry
`element`, `feedback_partial`, `quiz_submitted`, `locked`, or a full `choices`/`selected_ids`
set — so it cannot render the form body. Rather than hand-assemble that context (and risk the
missing-name crashes the review flagged), the choice branch reuses the element's own
`render()`, which already assembles the complete, correct context:

- **JS branch, for a `ChoiceQuestionElement`:** call `question.render(element=element,
  mode="lesson", selected_ids=<validated answer>, mark_result=result,
  feedback_for_pk=element.pk)` and return it wrapped in an `HttpResponse` —
  `HttpResponse(question.render(...))` — since `render()` returns a `str`, not an
  `HttpResponse` (the existing branch returns `render(request, template, ctx)`, a real
  response; a bare string from a view is invalid). The response body is the **full element
  HTML**. Because §3 makes
  `render()` set `reveal_template=None` for `mode="lesson"`, the returned element has the
  inline per-option feedback in the choices list and a verdict-only bottom slot (no duplicate
  reveal). `render()` already supplies `element`, `feedback_partial`, `quiz_submitted=False`,
  `locked=False`, `choices`, and `action_url` — resolving the incomplete-context risk. The JS
  (§5) extracts the `<form>`'s inner HTML from this response and swaps it into the live form,
  so returning the whole element (outer `<div>` + `<form>`) is fine.
- All **other** question types are unchanged: the branch still returns
  `_question_feedback.html` into the bottom slot for any non-choice `QuestionElement`. The
  choice-vs-other split is a single `isinstance(question, ChoiceQuestionElement)` check in
  `check_answer`'s fragment branch.
- **No-JS POST path** (`views.py:530-540`, full-page `lesson_unit.html` re-render): this
  already re-renders the whole element through `render_element`→`render()` with `mark_result`
  and `selected_ids`. Once `render()` gates `reveal_template` on `mode` (§3 point 1) and
  `_question_feedback.html` guards on truthiness (§3 point 2), the no-JS wrong-answer render
  shows inline feedback and **no** duplicate reveal list — the mechanism the earlier draft
  asserted but did not provide. `mode` is already `"lesson"` on this path.

### 5. Lesson JS — gated form-body swap (`courses/static/courses/js/question.js`)

`question.js` binds one `submit` listener per question form and today (a) captures `slot =
q.querySelector("[data-question-feedback]")` before the fetch, then (b) after the response
sets `slot.innerHTML = html`, runs `renderQ(slot)`, and looks up
`slot.querySelector(".question__verdict.is-correct")` to hide the Check button. Change:

- **If the form carries `data-question-inline`** (choice): the response is the **full element
  HTML**. Parse it (`new DOMParser().parseFromString(html, "text/html")`), take the parsed
  `<form>`'s `innerHTML`, and assign it to the **live** form (`form.innerHTML = newInner`). The
  live `<form>` node persists, so the bound submit listener survives and retry keeps working.
  Then, operating on the **live form** (not the stale pre-fetch `slot`, which
  `form.innerHTML = …` has just detached):
  - `renderQ(form)` to typeset the swapped choices' and feedback's math;
  - `form.querySelector(".question__verdict.is-correct")` to decide whether to hide the Check
    button. The verdict and the (re-emitted) Check button are both inside the new form body,
    so both queries resolve against `form`.
- **Otherwise** (all other question types): behave exactly as today — `slot.innerHTML = html`,
  `renderQ(slot)`, verdict lookup on `slot`. A regression test asserts a non-choice question
  still swaps the bottom slot and does not touch the form body.

The key correction over the earlier draft: the choice path must **not** reuse the pre-captured
`slot` variable for the post-swap `renderQ`/verdict-hide — that node is detached by the
`form.innerHTML` assignment — it must re-query against the live `form`.

### 6. Quiz-feedback and quiz-results — keep the reveal list, follow the new rule

`_reveal_choice.html` remains the option display in the quiz-feedback
(`_quiz_question_feedback.html`) and quiz-results (`quiz_results.html`) views, where the
interactive form is not present. Update it to the renamed field:

- Replace `{% if c.pk in mark_result.nudged %}` with `{% if c.pk in
  mark_result.annotated %}`.
- No layout change. The practical effect is that a **missed correct option** now shows its
  feedback in the reveal list (previously only selected distractors did), consistent with the
  lesson view.

**Unanswered-question results (intended behavior, documented).** `_results_row`
(`views.py:1053-1058`) marks an **empty** answer for an unanswered `[A]` question
(`question.mark(question.build_answer(QueryDict()))`). Under the symmetric rule, `mark(empty)`
puts **every correct option that carries feedback** into `annotated` (each correct option
satisfies `(pk ∉ ∅) != is_correct`). So the results reveal for an unanswered choice question
now shows each correct option's "why this should be chosen" feedback. This is **intended** and
consistent with the existing "reveal all correct answers for every [A] row, including
unanswered ones" behavior already documented at `views.py:1010-1011,1048-1052` — the reveal
list already shows the ✓ correct answers for skipped questions; it now also shows their author
feedback. No suppression is added. A results-page test covers the unanswered choice-question
case (see Testing).

### 7. Editor — clarify the `feedback` field help text (`courses/element_forms.py`)

`Choice.feedback` is already an editable field in the `ChoiceOptionForm` inline formset. No
schema or field change. Update its help text / label so authors know the feedback now shows
for **both** a trap the student selected *and* a correct option the student missed — i.e.
authors should write "why this is wrong" on distractors and "why this should be chosen" on
correct options. EN + PL.

### 8. Styling — new classes (`courses/static/courses/css/courses.css`)

Today only `question__nudge` is styled. The new inline classes must ship styled (repo
convention: no undefined classes, every view ships styled, verified light + dark):

- `.question__choice-feedback` — the inline corrective text under an option, in the **lesson**
  choices list.
- `.question__choice-marker` with `--wrong` (✗) and `--missed` modifiers — the two per-option
  markers, each with a light- and dark-mode-legible treatment.

**On the two class names for author feedback text (deliberate split).** The lesson inline path
uses `question__choice-feedback`; the quiz/results reveal list keeps `question__nudge` in
`_reveal_choice.html`. This split is intentional, not an oversight: the two live in
structurally different DOM (inline within an interactive `<li>` in the choices `<ul>` vs. an
item in the standalone `question__reveal` list), so they need different layout rules. They
should nonetheless **share visual language** (color, type treatment) so the same
`Choice.feedback` string reads consistently across views; only positioning differs. Keeping
them as separate classes avoids overloading one rule with two layout contexts.

Run a `frontend-design` pass on the inline treatment and verify with light + dark screenshots
before finishing (per the repo's screenshot-verification convention). The old
`question__nudge` rule may be removed if no longer referenced after `_reveal_choice.html` stops
using it — but note `_reveal_choice.html` is retained for quiz/results, so confirm whether it
still emits `question__nudge` before deleting the rule.

## Data flow

Lesson consumption (JS path):

1. Student ticks options and clicks **Check**.
2. `question.js` POSTs the form to `check_answer` with `X-Requested-With: fetch`.
3. `check_answer` validates the submission (`build_answer`), marks it
   (`ChoiceQuestionElement.mark()` → `MarkResult` with `annotated`), and — for a choice
   question — calls `question.render(..., mode="lesson", mark_result=result,
   selected_ids=<answer>, feedback_for_pk=element.pk)`. `render()` sets `reveal_template=None`
   for lesson mode, so the returned full-element HTML carries inline per-option markers +
   feedback in the choices list and a verdict-only bottom slot (no duplicate reveal list).
4. `question.js` sees `data-question-inline`, extracts the parsed `<form>`'s inner HTML and
   assigns it to the live form, then re-typesets math and re-checks the verdict against the
   live form. The student sees, directly under each option they got **wrong**, a wrong-pick
   (✗) or missed-correct marker plus corrective feedback; correctly-handled options show
   nothing; a fully-correct answer shows only the ✓ verdict and hides the Check button.

Quiz feedback / quiz results:

1. The element is rendered (or re-rendered on results) with a `mark_result` carrying
   `annotated`.
2. `_reveal_choice.html` lists every option with ✓ on correct ones and feedback on
   `annotated` ones — now including missed-correct options.

No-JS lesson fallback: the full-page `check_answer` re-render already renders the whole
element with `mark_result` and `selected_ids`; the template change (§3) makes inline feedback
appear without any JS.

## Error handling

- **Forged / foreign choice ids**: unchanged — `build_answer` already intersects submitted
  ids with the question's own choices, dropping anything foreign without error.
- **Options with empty feedback**: excluded from `annotated` by the `c.feedback` guard, so no
  empty `<p>` is emitted.
- **Fully-correct answer**: `annotated` empty → no inline feedback, ✓ verdict only, Check
  button hidden. Matches current "suppress reveal when correct" behaviour.
- **Network error on Check** (JS path): unchanged — `question.js` leaves the form intact on a
  fetch failure, so the student can retry.
- **Field rename safety**: `nudged` → `annotated` is a mechanical rename touching **two**
  producers (`ChoiceQuestionElement.mark()` and `views.py:_stored_result`) and two consumers
  (`_reveal_choice.html` and `_stored_result`'s read); a repo-wide grep for `nudged` (non-test)
  is the completeness guard, and tests referencing `nudged` are updated in the same change.
  Missing the `_stored_result` site 500s the quiz-feedback render for submitted AUTO choice
  questions — a test over that path is the guard.
- **Cross-type regression risk**: the `question.js` swap change is gated on
  `data-question-inline`, which only the choice template emits, so other question types keep
  the bottom-slot behaviour. A test asserts the non-choice path still swaps the bottom slot.

## Testing

Unit (`courses/tests/`, `tests/`):

- `mark()` symmetric rule:
  - selected distractor with feedback → in `annotated`;
  - missed correct option with feedback → in `annotated` (the previously-uncovered case);
  - correctly-selected correct option and correctly-avoided distractor → **not** in
    `annotated`;
  - fully-correct answer → `annotated` empty;
  - option in the symmetric difference but with empty feedback → **not** in `annotated`;
  - single-choice and multiple-choice variants both covered.

Template rendering:

- Lesson render with a wrong `mark_result` shows inline `question__choice-feedback` under the
  annotated options and **not** under others; shows the wrong-pick marker on a selected
  distractor and the distinct missed-correct marker on an unselected correct option; bottom
  slot shows the verdict but **no** `question__reveal` list.
- Fully-correct render shows no inline feedback, no per-option markers, and no reveal list —
  only the ✓ verdict.
- `_reveal_choice.html` (quiz/results context) shows feedback for a missed-correct option
  (the `annotated` rename in action).
- Results page for an **unanswered** choice question (`[A]` marking): the reveal list shows
  each correct option's feedback (the documented `mark(empty)` → all-correct-`annotated`
  behavior), and does not error.

View:

- `check_answer` for a choice question over the **fetch** path returns the full element HTML
  containing inline feedback in the choices list and **no** `question__reveal` list (not the
  bare `_question_feedback.html`).
- `check_answer` for a choice question over the **no-JS full-page** path (`lesson_unit.html`
  re-render, wrong answer) shows inline feedback **and asserts the duplicate
  `question__reveal` list is absent** — the regression the `reveal_template`/`mode` suppression
  exists to prevent.
- `check_answer` for a non-choice question still returns `_question_feedback.html`
  (regression guard — the inline swap must not leak to other types).
- Quiz-feedback render for a submitted AUTO choice question returns 200 (guards the
  `_stored_result` `nudged`→`annotated` rename against a 500).
- A wrong-answer JS-fragment render does **not** raise `TemplateDoesNotExist` (guards the
  `{% include None %}` fix).

e2e (`-m e2e`, run focused/foreground):

- Lesson: answer an MCQ incorrectly, click Check, assert corrective feedback appears **inline
  beneath** the wrong option (and beneath a missed-correct option), and that no duplicate
  bottom option-list is rendered.
- Answer correctly: assert the ✓ verdict, no inline feedback, Check hidden.

Full-suite Definition-of-Done: run the whole unit suite + lint (`ruff`, `ruff format
--check`) + i18n catalog checks (EN/PL) per repo convention. No `ELEMENT_MODELS` count
assertions change (no new element).
