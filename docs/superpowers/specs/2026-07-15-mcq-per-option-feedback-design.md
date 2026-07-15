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

`MarkResult.nudged` is choice-specific (only `ChoiceQuestionElement.mark()` sets it and only
`_reveal_choice.html` reads it). Rename the field to `annotated` to match its new, broader
meaning, updating the dataclass definition, its docstring, the single producer
(`ChoiceQuestionElement.mark()`), and the single consumer template. Grep confirms `nudged`
has no other references in non-test code; test references are updated alongside.

### 3. Lesson render — inline feedback in the choices list (`choicequestion.html`)

Extract the form's inner body (the choices `<ul>` + the Check button + the bottom feedback
slot) into a partial, `_choicequestion_body.html`, so the same markup can be produced by
both the full-element render and the lesson `check_answer` re-render:

- `choicequestion.html` renders `<form …>{% include "…/_choicequestion_body.html" %}</form>`.
- Each choice `<li>` gains, when `mark_result` is present:
  - a per-option state marker — ✓ when `c.is_correct`, ✗ when `c.pk in selected_ids and not
    c.is_correct` — so the student sees per-option status without the bottom list;
  - an inline `<p class="question__choice-feedback">{{ c.feedback }}</p>` rendered **iff**
    `c.pk in mark_result.annotated` (which already implies non-empty feedback).
- The `<form>` element itself carries a data hook (e.g. `data-question-inline`) so the JS
  knows to swap the form body rather than only the bottom slot (see §5).
- The bottom `[data-question-feedback]` slot in the lesson path keeps **only** the verdict
  (✓ Correct / ✗ Incorrect) and the author `explanation`; it no longer includes
  `_reveal_choice.html`. This is achieved by passing `reveal_template=None` in the lesson
  `check_answer` feedback context for choice (see §4), so `_question_feedback.html`'s
  existing `{% if not mark_result.correct %}{% include reveal_template %}{% endif %}` guard
  renders nothing.

Repopulation of `selected_ids` (checked state on retry) and the `disabled` handling for
`quiz_submitted`/`locked` are preserved exactly as today.

### 4. Lesson delivery — `check_answer` returns the re-rendered form body (`courses/views.py`)

Today the JS branch of `check_answer` returns only `_question_feedback.html` (verdict +
reveal) to swap into the bottom slot. For choice questions it must instead return the
re-rendered **form body** (`_choicequestion_body.html`) so the inline feedback appears in
the choices list.

- The JS branch, for a `ChoiceQuestionElement`, renders `_choicequestion_body.html` with the
  full context (`choices`, `selected_ids`, `mark_result`, `mode="lesson"`,
  `reveal_template=None`, `feedback_for_pk`, the verdict/explanation context) and returns
  that fragment.
- All **other** question types are unchanged: they keep returning
  `_question_feedback.html` into the bottom slot.
- The no-JS POST path (full-page re-render) already renders the whole element with
  `mark_result` and `selected_ids`, so inline feedback appears there for free once the
  template (§3) carries it; that path needs no behavioural change beyond `reveal_template`
  suppression for choice consistency.

### 5. Lesson JS — gated form-body swap (`courses/static/courses/js/question.js`)

`question.js` binds one `submit` listener per question form and today swaps the returned
HTML into `[data-question-feedback]`. Change:

- If the form carries the `data-question-inline` hook, swap the returned HTML into the
  **form's inner content** (`form.innerHTML = html`). The `<form>` node itself persists, so
  the bound submit listener survives and retry continues to work.
- Otherwise (all other question types) behave exactly as today: swap the bottom
  `[data-question-feedback]` slot.
- After either swap, re-run the existing `renderQ` inline-math pass over the swapped region.
- The existing "hide Check button on a fully-correct answer" logic keys off
  `.question__verdict.is-correct`; that verdict is inside the swapped body for choice, so
  the lookup still resolves. The Check button is re-emitted by the body partial and hidden
  when correct.

### 6. Quiz-feedback and quiz-results — keep the reveal list, follow the new rule

`_reveal_choice.html` remains the option display in the quiz-feedback
(`_quiz_question_feedback.html`) and quiz-results (`quiz_results.html`) views, where the
interactive form is not present. Update it to the renamed field:

- Replace `{% if c.pk in mark_result.nudged %}` with `{% if c.pk in
  mark_result.annotated %}`.
- No layout change. The practical effect is that a **missed correct option** now shows its
  feedback in the reveal list (previously only selected distractors did), consistent with the
  lesson view.

### 7. Editor — clarify the `feedback` field help text (`courses/element_forms.py`)

`Choice.feedback` is already an editable field in the `ChoiceOptionForm` inline formset. No
schema or field change. Update its help text / label so authors know the feedback now shows
for **both** a trap the student selected *and* a correct option the student missed — i.e.
authors should write "why this is wrong" on distractors and "why this should be chosen" on
correct options. EN + PL.

## Data flow

Lesson consumption (JS path):

1. Student ticks options and clicks **Check**.
2. `question.js` POSTs the form to `check_answer` with `X-Requested-With: fetch`.
3. `check_answer` validates the submission (`build_answer`), marks it
   (`ChoiceQuestionElement.mark()` → `MarkResult` with `annotated`), and — for a choice
   question — renders `_choicequestion_body.html` (choices with inline per-option markers +
   feedback, verdict-only bottom slot) and returns it.
4. `question.js` sees `data-question-inline`, sets `form.innerHTML = html`, re-typesets math.
   The student sees ✓/✗ and corrective feedback directly under each option they got wrong;
   fully-correct answers show only the ✓ verdict and hide the Check button.

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
- **Field rename safety**: `nudged` → `annotated` is a mechanical rename with exactly one
  producer and one template consumer; a repo-wide grep guards against a missed reference, and
  tests referencing `nudged` are updated in the same change.
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
  annotated options and **not** under others; shows ✓/✗ per-option markers; bottom slot shows
  the verdict but **no** `question__reveal` list.
- Fully-correct render shows no inline feedback and no reveal list.
- `_reveal_choice.html` (quiz/results context) shows feedback for a missed-correct option.

View:

- `check_answer` for a choice question over the fetch path returns the form body containing
  inline feedback (not the bare `_question_feedback.html`).
- `check_answer` for a non-choice question still returns `_question_feedback.html`
  (regression guard).

e2e (`-m e2e`, run focused/foreground):

- Lesson: answer an MCQ incorrectly, click Check, assert corrective feedback appears **inline
  beneath** the wrong option (and beneath a missed-correct option), and that no duplicate
  bottom option-list is rendered.
- Answer correctly: assert the ✓ verdict, no inline feedback, Check hidden.

Full-suite Definition-of-Done: run the whole unit suite + lint (`ruff`, `ruff format
--check`) + i18n catalog checks (EN/PL) per repo convention. No `ELEMENT_MODELS` count
assertions change (no new element).
