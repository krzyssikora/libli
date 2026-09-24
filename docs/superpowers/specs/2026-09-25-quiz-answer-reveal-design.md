# Quiz answer reveal: "Show answer" + an in-place Your/Correct switch — design

Date: 2026-09-25 · Branch: `feat/quiz-answer-reveal` (spec); implementation in three PRs (§8)

## Problem

After answering a quiz question, a student sees the correct answer only once the
question **locks** (a correct answer, or a wrong one on the last attempt). The answer
is then printed as a **separate list** under the question — "Correct answer: X",
"Expected: 3.14 ± 0.01", a ✓/✗ row per blank / slot / zone / pair / grid row
(`templates/courses/elements/_reveal_*.html`, included from
`_quiz_question_feedback.html`). The owner's verdict: "far from perfect".

- The list is detached from the controls: the student has to match row N to blank N
  (the same problem PR #346 removed from lessons for fill-in-blanks).
- Short text and number reveals show the correct answer but **not what the student
  typed**.
- **No way to ask for the answer.** With unlimited attempts (`max_attempts=None`) a
  student who is never right never sees it during the quiz.
- A partly-right answer (0 < fraction < 1) shows as plain "Incorrect" in the live
  panel; only the results page knows "partial".
- The results page (`quiz_results.html` via `views._results_row`) shows lists, never
  the question, and differs from the live panel (choice gets a list there; partial and
  unanswered rows reveal there but not live).

Multiple choice already marks its options in place once locked (`INLINE_QUIZ_REVEAL`,
`ChoiceQuestionElement.choice_marks`, `MARK_GLYPHS` ✓ ✗ ＋) — the one type without the
problem.

## Owner decisions (verbatim intent — do not reverse in review)

| # | Decision | Rejected alternative |
|---|----------|----------------------|
| D1 | A **Show answer** button, available after the first Check on an auto-marked quiz question; it asks for confirmation, then **locks the question at its current marks**. | Presentation-only change keeping today's timing; answers only on the results page at the end. |
| D2 | A revealed answer is shown with a **"Your answer / Correct answer" switch** on the question's own controls; no separate list. | An answer tag next to each wrong box; a red-pen correction inside the box. |
| D3 | The revealed state **opens on "Your answer"** (the coloured view). | Opening on "Correct answer". |
| D4 | The result line states the **real outcome incl. partly correct and the marks** (e.g. "◐ Partly correct · 0.25 / 1"); never "Incorrect — answer shown" for a partial answer. | Keeping "Incorrect" for partial answers. |
| D5 | The **latest attempt counts** (unchanged). Owner's reasoning: changing a right answer to a wrong one is what the student now thinks, so it is marked. | Best attempt counts. |
| D6 | **Each part is coloured green/red from the first Check**, while attempts remain. | Only "Incorrect" until the question locks. |
| D7 | Scope: **every question type, one spec, three PRs** in the order of §8. Extended response keeps its keyword view. | One PR; converting only some types. |
| D8 | **Multiple choice keeps its combined ✓ ✗ ＋ view**, no switch. | The same switch as every other type. |
| D9 | Multiple choice stays **all-or-nothing**. Partial-credit scoring is a separate later idea (owner floated 1/n per option state; its "blank answer scores 0.6" flaw was discussed). | 1/n per option; right-minus-wrong. |
| D10 | The **results page shows each question as it ended** (read-only, same renderer, switch). | Keeping the list page; a summary table with expandable questions. |
| D11 | **Lessons unchanged**: no answers in lessons (PR #346 stands; an author can add a spoiler). | Show answer in lessons; a per-question author setting. |
| D12 | **Rendering approach 1**: the server draws the question a second time from a per-type `key_answer()` through the existing renderer. | Client-side JS filling in the key; a per-type correct-answer template. |

## 1. Student experience in a quiz

Applies to **auto-marked** (`marking_mode = A`) questions. Not-marked (N) and
requires-review (R) questions are unchanged: they lock on first submission, show
"Answer recorded" / "Submitted for review", and never reveal a key.

1. **Before any Check** — unchanged.
2. **After a Check with attempts remaining** (not locked):
   - every part is coloured green/red (D6) — blank, box, slot, zone, pair, grid row;
     for multiple choice the **ticked** options get ✓/✗, but the ＋ (a missed correct
     option) is **not** shown, because it would reveal the key;
   - result line: "✓ Correct · 1 / 1", "◐ Partly correct · 0.25 / 1 · 2 attempts
     left", "✗ Incorrect · 0 / 1 · 2 attempts left" (D4). The marks are
     `earned_marks(fraction, max_marks)` of this attempt;
   - a **Show answer** button next to Check;
   - explanation still hidden (unchanged).
3. **Show answer**: `confirm()` — "Show the answer? This ends the question: you won't
   be able to try again, and you keep the marks you have now (0.25 of 1)." Confirm →
   locked at the latest attempt's marks (D5), `revealed_at` set (§3). Cancel → nothing.
4. **Locked** (correct / last attempt used / Show answer):
   - inputs frozen (as today);
   - if the answer is **not fully correct**: the **switch** appears, opening on
     **Your answer** (D3). A fully correct answer gets no switch — both sides would be
     identical;
   - multiple choice: no switch; ✓ ✗ ＋ on the options (D8, today's locked view);
   - extended response: its keyword list (as today);
   - explanation shown (as today);
   - after Show answer, the result line adds "· answer shown".
5. **Unlimited attempts**: locks only on correct or Show answer — Show answer is the
   stuck student's way out.
6. **Finish** — unchanged (it still re-posts every open question's form first).

## 2. Rendering (D12)

All server-side; no per-type JS; works without JS.

### 2.1 Per-part verdicts

`QuestionElement.part_verdicts(mark_result) -> list[bool] | None` — the right/wrong
flag per part, in the order the type's template draws its parts. Every multi-part type
already computes these in `mark()` (`reveal` items carry `correct`); `part_verdicts`
extracts **only the booleans**. Short text / number: one part. Base class: `None`
(= not converted; the type keeps today's list, §8).

Each converted type's template/tag paints its controls from the verdicts — the
`fillblank.render_inputs(verdicts=...)` pattern from PR #346, extended. Because only
booleans reach the page, D6 leaks no key.

Multiple choice: `choice_marks` gains the unlocked-quiz case — ✓/✗ on **picked**
options only, never ＋ until locked.

### 2.2 The correct-answer copy

`QuestionElement.key_answer()` returns the correct answer **in the shape that type's
`build_answer()` returns**, so the existing render/rehydrate path can draw it:

| Type | `key_answer()` |
|---|---|
| Fill in the blanks | first accepted line per blank (list) |
| Short text | first accepted line |
| Short number | the value (the copy renders "± tolerance" beside it when tolerance > 0) |
| Drag the words | the correct token per slot |
| Match pairs | the correct partner per left item |
| Choice grid / multi grid | the correct cell(s) per row |
| Drag onto image | the correct label per zone |
| Multiple choice, extended response | `None` (own view, D8 / D7) |

When a question is **locked and not fully correct**, the renderer draws a second copy
from `key_answer()`: all parts painted correct, every control read-only, and **no
control carries a `name` attribute** — so quiz.js's Finish re-post (which serialises the
question's form) can never send the key as the student's answer. **The copy is rendered
only when locked**; it never appears in the page, the Check fragment, or the resume
render before that.

### 2.3 The switch

`templates/courses/elements/_answer_switch.html` — a two-option segmented control
("Your answer" / "Correct answer") built from two radio inputs with a per-element
unique name, placed **outside the question `<form>`** (inside `[data-question]`) so
they are never serialised; a `[data-question]:has(...)` CSS rule shows the copy matching
the checked radio, "Your answer" checked by default (D3). Keyboard-operable, no JS.

- quiz.js and editor.js freeze **every** input inside `[data-question]` once
  `[data-quiz-locked]` appears; the freeze selector must exclude the switch
  (`[data-answer-switch]`). Pinned by an e2e test.
- Locked answers already come back as the whole re-rendered element on the fetch path
  (`_quiz_render_feedback`'s INLINE branch). Converted types join that branch, so the
  switch and both copies land via the existing `data-question-inline` form-body swap.

### 2.4 Result line

`_quiz_question_feedback.html` gains the **partial** state (0 < fraction < 1) and the
marks, per §1. One template for all types.

## 3. Show answer — server

- **Transport**: a second submit button `name="reveal" value="1"` in the question's
  form, posting to the existing `courses:quiz_answer`. No new URL.
- **Enrolled student** (inside the existing transaction + `select_for_update`):
  accepted only if marking_mode is AUTO, `attempt_count >= 1`, not locked, and the
  submission is not SUBMITTED. Then `locked = True`, `revealed_at = now()`. It
  **ignores the posted answer** — "Your answer" and the marks come from the stored
  latest attempt, so a student cannot slip in an unchecked answer. It does **not**
  increment `attempt_count` and creates **no** `Attempt` row. Any other state → 409
  (quiz.js already reloads on 409).
- **Non-enrolled previewer + editor try-it**: ephemeral as today. The client-supplied
  attempt count (`parse_attempt`) plus `reveal` feed `ephemeral_quiz_feedback`; the
  answer is whatever the form holds. Nothing persisted.
- **Reveal-rule parity**: one helper, `courses.quiz.can_reveal(question, attempt_count,
  locked)`, decides eligibility for BOTH the saved and the ephemeral path;
  `tests/test_quiz_lock_rule_parity.py` gains a case per condition so the paths cannot
  drift.
- **Confirmation**: `confirm()` in quiz.js / editor.js, like Finish. No-JS proceeds
  without a prompt, like Finish. e2e must register a dialog handler (Playwright
  auto-dismisses confirm → the reveal would silently not happen).

### 3.1 Migration

`courses/migrations/0067_questionresponse_revealed_at.py` — nullable
`DateTimeField`, reversible (plain AddField). Its dependency must be the graph head at
the time it is written (currently `0066_blank_answers_unescape`).

## 4. Results page (D10)

`views._results_row` / `quiz_results.html` render each question **read-only through
the same renderer**, from the stored `latest_answer`, `mark_result = mark(latest)`,
locked:

- **auto-marked**: result line (correct / partial / incorrect, marks; "· answer shown"
  if `revealed_at`), the switch (or ✓ ✗ ＋ for choice), the explanation;
- **unanswered**: empty controls, "Not answered · 0 / 1", and the switch so the answer
  is still viewable;
- **N / R**: the student's answer read-only + "Answer recorded" / "Submitted for
  review" / the teacher's `review_feedback`; never a key (as today);
- score badges and the total stay.

Unconverted types (during PR 1–2) keep today's list rows.

## 5. Teacher analytics

`templates/courses/manage/analytics_student_quiz.html` shows an **"answer shown"** tag on
rows whose `QuestionResponse.revealed_at` is set. Nothing else in analytics or the review
queue changes.

## 6. Out of scope

Lessons (D11); multiple-choice partial credit (D9); latest-vs-best (D5); the teacher
review queue; any per-quiz "allow Show answer" setting.

## 7. Testing

Per PR, for its types:

- **No leak before lock**: no correct-answer copy, no key text in the page, the Check
  fragment, or the resume render — only the booleans. Existing no-leak tests
  (`test_quiz_noleak.py`, `test_questions_2d_quiz_noleak.py`, `test_quiz_resume.py`)
  must stay at least as strict.
- **Key copy**: correct values; no `name` on any control; Finish re-post cannot carry it.
- **Show answer state machine**: 409 when no attempt yet / locked / submitted / N or R;
  no attempt consumed; posted answer ignored; `revealed_at` set; lock-rule parity.
- **Results rows**: correct, partial, incorrect, unanswered, revealed, N, R.
- **e2e**: the flow incl. confirm handler; the switch still works after the freeze;
  per-part colours measured as computed styles; light + dark screenshots.
- **Mutants**: break each key behaviour (leak the copy before lock, drop `name`
  stripping, freeze the switch, count the reveal as an attempt) and require RED.
- Rewritten existing tests say which old assertion each replaces; none is loosened.

## 8. Delivery — three PRs (D7)

1. **Shared + fill in the blanks, short text, number.** Migration; reveal branch
   (saved + ephemeral); Show answer button + confirm; result line; `_answer_switch.html`;
   `part_verdicts` / `key_answer` hooks with base-class `None`; results page through the
   renderer; analytics tag. **Unconverted types keep today's lists** live and on results.
   Help (`docs/help/course-admin/quiz-editors.md` + `.pl.md`) updated.
2. **Drag the words, match pairs, drag onto image, choice grid, multi grid.**
3. **Multiple choice + extended response.** Choice: ✓/✗ on picks from the first Check
   (＋ only when locked), Show answer, results. Extended response: Show answer reveals
   its keyword list. Delete the now-unused `_reveal_*.html` and their unused msgids.
   Help updated again.
