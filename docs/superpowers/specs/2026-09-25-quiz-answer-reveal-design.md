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

1. **Before any Check** — unchanged. **No Show answer button** is rendered yet.
2. **After a Check with attempts remaining** (not locked):
   - every part is coloured green/red (D6) — blank, box, slot, zone, pair, grid row;
     for multiple choice the **ticked** options get ✓/✗, but the ＋ (a missed correct
     option) is **not** shown, because it would reveal the key;
   - result line: "✓ Correct · 1 / 1", "◐ Partly correct · 0.25 / 1 · 2 attempts
     left", "✗ Incorrect · 0 / 1 · 2 attempts left" (D4). The marks are
     `earned_marks(fraction, max_marks)` of this attempt;
   - a **Show answer** button after Check (§3.1 fixes its position);
   - explanation still hidden (unchanged).

   The same state is drawn on a page reload (resume) and on the no-JS re-render (§2.4).
3. **Show answer**: `confirm()` — "Show the answer? This ends the question: you won't
   be able to try again, and you keep the marks you have now (0.25 of 1)." (text and
   marks come from the server, §3.4). Confirm → locked at the latest attempt's marks
   (D5), `revealed_at` set (§3). Cancel → nothing.
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

Each converted type's template/tag paints its controls from a **`verdicts`** render
argument — the `fillblank.render_inputs(verdicts=...)` pattern from PR #346, extended.
`verdicts` is passed **whenever an auto-marked answer exists**, locked or not;
`mark_result` (which carries key material in `reveal`) is still passed to the template
**only when locked**, as today. Because only booleans reach the page before the lock,
D6 leaks no key.

Multiple choice: `choice_marks` gains the unlocked-quiz case — ✓/✗ on **picked**
options only, never ＋ until locked.

### 2.2 The correct-answer copy

`QuestionElement.key_answer()` returns the correct answer **in exactly the shape that
type's `build_answer()` returns** — the same identifiers, not display text (for drag the
words, match pairs and drag onto image: the `slot` values `build_answer` reads with
`post.getlist("slot")`; for grids: the per-row column pks) — so the existing
render/rehydrate path draws both copies identically:

| Type | `key_answer()` |
|---|---|
| Fill in the blanks | first accepted line per blank (list) |
| Short text | first accepted line |
| Short number | the value (the copy renders "± tolerance" beside it when tolerance > 0) |
| Drag the words | the correct `slot` value per gap |
| Match pairs | the correct `slot` value per left item |
| Choice grid / multi grid | the correct column pk(s) per row |
| Drag onto image | the correct `slot` value per zone |
| Multiple choice, extended response | `None` (own view, D8 / D7) |

When a question is **locked and not fully correct** (§2.6 defines the source of "fully
correct"), the renderer draws a second copy from `key_answer()`.

**What the copy contains — the controls region only.** Each converted template factors
its answer controls (the stem with its inputs / slots / grid, i.e. today's
`<fieldset class="question__stem">` content) into a per-type include, e.g.
`_fillblank_controls.html`, rendered once for "Your answer" and once with `copy="key"`
for the correct answer. The form wrapper, the Check and Show answer buttons, the
`[data-question-feedback]` box and `data-quiz-locked` are rendered **exactly once** per
question — never inside the copy. Test: exactly one `[data-question-feedback]`, one
Check button and at most one Show answer button per rendered question.

The key copy's controls:

- all parts painted correct;
- every control **`disabled`** (not `readonly`, which has no effect on radios,
  checkboxes, selects or draggables) and **without a `name` attribute** — disabled
  controls are never serialised by `FormData`, and the missing `name` is defence in
  depth, so no re-post can ever send the key as the student's answer. Drag types'
  nameless `<select>`s carry **`data-slot`** instead, and dnd.js's selector widens from
  `select[name="slot"]` to `select[name="slot"], select[data-slot]` so it still builds
  the drag UI for the key copy (PR 2);
- **every `id` in the copy gets a `-key` suffix**, and every `for=` / `aria-*` reference
  in the copy is rewritten to match, so ids stay unique and labels point at their own
  copy's controls.

**The copy is rendered only when locked**; it never appears in the page, the Check
response, or the resume render before that.

### 2.3 The switch

`templates/courses/elements/_answer_switch.html` — a two-option segmented control
("Your answer" / "Correct answer") built from two radio inputs named
`answer_view_<element.pk>`, placed **inside the question `<form>`** (so the fetch path's
form-body swap carries it, §2.4) but **outside every `<fieldset>`** — a direct child of
the form next to the feedback box. A locked question's templates render their
controls fieldset `disabled` and both freeze scripts disable `fieldset`s, and a disabled
fieldset disables every control inside it regardless of any selector exclusion. The
switch is wrapped in `[data-answer-switch]`, and the CSS rule that shows the copy
matching the checked radio is scoped to **the form** (`form:has(...)`), not to
`[data-question]`, so it works on every render path including the results page (§4),
which renders each question inside the same form markup. "Your answer" is checked by
default (D3). Keyboard-operable, no JS. Test: no switch radio has a `disabled`
ancestor `fieldset`, in the server render and after each script's freeze.

- `answer_view_*` joins the reserved POST names documented on
  `courses.quiz.parse_attempt`: no `build_answer` may read it. It only exists on a
  locked question, whose form is never posted again (its Check is disabled, and
  Finish re-posts only open questions).
- **Freeze exclusion, both scripts.** quiz.js freezes
  `form.querySelectorAll("input, button, select, textarea, fieldset")` (root: the
  form); editor.js freezes `qEl.querySelectorAll(...)` (root: the whole
  `[data-question]`). Both roots now contain the switch, so **both** selectors must
  skip `[data-answer-switch]` and its descendants. One e2e test per script.

### 2.4 Which response carries what

Today only `INLINE_QUIZ_REVEAL` types (choice) get the whole element back on the fetch
path, and only with `mark_result` when locked (`views._quiz_render_feedback`); every
other type gets just the feedback box. After this change, **every converted type
answers every fetch-path Check and Show answer with the whole re-rendered element**
(`verdicts` always, `mark_result` + key copy + switch only when locked, the Show answer
button when eligible), swapped in via the existing `data-question-inline` form-body swap.
The converted type's form gains `data-question-inline` in quiz mode. Unconverted types
keep today's fragment until their PR.

**Per-type enhancers after a swap.** `form.innerHTML = …` replaces controls that
per-type scripts enhanced at DOMContentLoaded: dnd.js (`init(root)`, drag UI) and
blank_autosize.js (initial fit). quiz.js and editor.js must re-run both on the swapped
form, through a small global each script exposes (e.g. `window.libliDnd.init(form)`,
`window.libliBlankAutosize(form)`), and both must be idempotent. PR 1 needs the
autosize re-run; PR 2 the dnd one. Test (PR 2 e2e): after a Check and after a reveal,
the drag UI is present in both copies.

The other render paths must draw §1 state 2 or 4 identically:

- **resume** (`build_quiz_context`, page load mid-quiz) and the **no-JS** re-render
  compute `verdicts = part_verdicts(mark(answer_from_json(question, latest_answer)))`
  for an answered question, locked or not (today they pass nothing until locked).
  `latest_answer` is the stored JSON form; `mark()` takes the `build_answer` shape,
  which `courses.quiz.answer_from_json` reconstructs;
- **editor try-it** (`views_manage.element_try`, quiz branch, §3.3);
- **previewer** (`quiz_answer`'s non-enrolled branch).

### 2.5 Result line

`_quiz_question_feedback.html` gains the **partial** state (0 < fraction < 1) and the
marks, per §1. One template for all types. The "· N attempts left" segment is
**omitted** when `max_attempts` is None (unlimited); result-line tests cover both.

### 2.6 One source per value — every render path

Any render of an **already-stored** answer (the enrolled reveal response, resume, no-JS,
the results page) re-marks it to get verdicts, and re-marking can disagree with what
was awarded if the author has since edited the key. So on every path:

- the **result line, the marks, the `data-confirm` marks and whether the switch is
  shown** ("fully correct" or not) come from the **stored** `response.fraction` /
  `earned_marks`;
- the **part colours and `mark_result`** (hence the key copy) come from a **fresh**
  `mark(answer_from_json(question, latest_answer))`.

The disagreement after a key edit is accepted — the marks are what was awarded; the
colours and key show the key as it is now — and is written down so nobody "fixes" one to
match the other. A fresh Check (live or ephemeral) has only one result, so the question
does not arise there. Test: edit the key after an attempt, then reveal; the line keeps
the stored marks.

## 3. Show answer — server

### 3.1 Transport

A second submit button `<button type="submit" name="reveal" value="1">` in the
question's form, posting to the form's existing action (`courses:quiz_answer` for the
student and previewer; `courses:manage_element_try` in the editor). No new URL.

- **Check must be the first submit button in the form's tree order.** Implicit
  submission (Enter in a text input) uses the first submit button; if Show answer came
  first, Enter would end the question — without a prompt on the no-JS path. Test: Enter
  in a short-text / blank input performs a Check, not a reveal.
- **quiz.js must send the submitter.** Today it builds `new FormData(form)`, which drops
  the clicked button, so Show answer would silently post a Check and use an attempt.
  It must use `new FormData(form, e.submitter)` (editor.js already appends
  `e.submitter`'s name/value). When the submitter is the reveal button, quiz.js and
  editor.js run the `confirm()` first, **do not** increment `data-attempts-made`, and
  send `attempt` = the current `made` count (not `made + 1`) so the ephemeral path
  sees no new attempt. Mutant: drop the submitter → a test must go RED.

### 3.2 Enrolled student (`quiz_answer`)

Inside the existing transaction + `select_for_update`, after the existing
SUBMITTED / locked / exhausted gates (which already return 409 on fetch and redirect
to results otherwise, via `_quiz_locked_response`):

- eligible iff `can_reveal(question, attempts_made=response.attempt_count,
  locked=response.locked)` (§3.5);
- then `locked = True`, `revealed_at = now()`. It **ignores the posted answer** —
  "Your answer", the verdicts and the marks come from the stored latest attempt, so a
  student cannot slip in an unchecked answer. It does **not** increment
  `attempt_count` and creates **no** `Attempt` row;
- ineligible (no attempt yet, or N/R) → fetch: 409 (quiz.js reloads); no-JS: redirect
  back to the quiz unit page (the question renders its current state).

### 3.3 Previewer and editor try-it (ephemeral)

Stateless, persists nothing, as today. When the POST carries `reveal`,
`attempts_made = parse_attempt(POST)` (the client sent its `made` count, §3.1 — note
`parse_attempt` floors at 1, so a reveal sent with `made = 0` reads as 1; the client
never offers the button before a Check, and the server-side check is advisory on this
path), and `locked = False` — a previously locked state is **not** modelled server-side
(the client has already frozen the question, so its reveal button no longer exists).
`can_reveal` decides; ineligible → the same response as an ephemeral Check with no
attempt (the unlocked element, no reveal).

- Previewer: `quiz_answer`'s non-enrolled branch → `ephemeral_quiz_feedback(...,
  reveal=True)` → a locked stand-in → the same whole-element render.
- Editor: `views_manage.element_try`'s quiz branch does the same with its own context
  builder, and returns the whole element for converted types (§2.4).
- **Accepted divergence (pinned by a test):** the ephemeral reveal marks **whatever the
  form holds** at the moment of the reveal, which may differ from the last Checked
  answer. The enrolled path uses the stored answer. This is acceptable because nothing
  is persisted and only authors/previewers reach this path.
- **Edge cases of that divergence, defined:** a reveal **bypasses the empty-answer
  validation branch** — an emptied form is marked as-is (every part wrong, 0 marks),
  locked, with an empty "Your answer" and the switch. A form that happens to be fully
  correct locks as "✓ Correct · 1 / 1 · answer shown" with no switch. Both are in the
  ephemeral-divergence tests.

### 3.4 Confirmation text

The reveal button carries a server-rendered `data-confirm`, built with the latest
attempt's marks, e.g. msgid `"Show the answer? This ends the question: you won't be
able to try again, and you keep the marks you have now (%(earned)s of %(max)s)."`. It is
re-rendered with every whole-element response, so it always matches the latest Check.
quiz.js / editor.js pass it to `confirm()`. No-JS proceeds without a prompt, like Finish.
e2e must register a dialog handler (Playwright auto-dismisses `confirm` → the reveal
would silently not happen).

### 3.5 Reveal-rule parity

`courses.quiz.can_reveal(question, *, attempts_made, locked) -> bool`:
AUTO marking mode, `attempts_made >= 1`, not `locked`. The SUBMITTED check stays in
`quiz_answer`'s existing gate (the ephemeral path has no submission). Both the saved
path (§3.2) and both ephemeral paths (§3.3) call it; `tests/test_quiz_lock_rule_parity.py`
gains a case per condition.

### 3.6 Migration

`courses/migrations/0067_questionresponse_revealed_at.py` — nullable
`DateTimeField`, reversible (plain AddField). Its dependency must be the graph head at
the time it is written (currently `0066_blank_answers_unescape`).

## 4. Results page (D10)

`views._results_row` / `quiz_results.html` render each question **read-only through
the same renderer**, from the stored `latest_answer`, locked.

Values follow §2.6 (stored marks / fresh colours). **Unanswered** rows (no
`QuestionResponse`, or `latest_answer` None) get `verdicts = None` — neutral controls —
and `mark()` is **not** called for them; only the key copy is drawn.

Rows:

- **auto-marked, answered**: result line ("· answer shown" if `revealed_at`), the switch
  (or ✓ ✗ ＋ for choice), the explanation;
- **auto-marked, unanswered**: empty controls, "Not answered · 0 / 1", and the switch so
  the answer is still viewable;
- **N / R, answered**: the student's answer read-only + "Answer recorded" / "Submitted
  for review" / the teacher's `review_feedback`; never a key (as today);
- **N / R, unanswered**: empty controls + "Not answered"; no marks, no switch, no key;
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

- **No leak before lock**: no correct-answer copy and no key text in the page, the
  Check response, or the resume render. The existing no-leak tests
  (`test_quiz_noleak.py`, `test_questions_2d_quiz_noleak.py`, `test_quiz_resume.py`)
  **keep every assertion about key text**; the only assertions that change are those
  forbidding correctness markers on controls before the lock, which D6 now requires
  (each such rewrite names the assertion it replaces).
- **Verdicts on every path**: fetch Check, resume, no-JS, previewer, editor try-it all
  paint the same parts for the same answer.
- **Key copy**: correct values; every control `disabled` and nameless; **no `id` occurs
  twice** in a rendered question; the Finish re-post cannot carry it.
- **Show answer state machine**: 409/redirect when no attempt yet / locked / submitted
  / N or R; no attempt consumed; posted answer ignored (enrolled); ephemeral divergence
  pinned (§3.3); `revealed_at` set; `can_reveal` parity.
- **Transport**: Enter in a text input does a Check, not a reveal; quiz.js sends the
  submitter (mutant); the client counter does not move on a reveal.
- **Results rows**: correct, partial, incorrect, unanswered, revealed, N, R, N/R
  unanswered; stored-vs-fresh sources (§4).
- **e2e**: the flow incl. the confirm handler; the switch arrives without a reload and
  still works after the freeze (quiz.js and editor.js); per-part colours measured as
  computed styles; light + dark screenshots.
- **Mutants**: leak the copy before lock, drop `name` stripping / `disabled`, freeze the
  switch, drop the submitter, count the reveal as an attempt → each must go RED.
- Rewritten existing tests say which old assertion each replaces; none is loosened.

## 8. Delivery — three PRs (D7)

Every PR: new strings extracted (`makemessages`), Polish translations written (clear any
fuzzy pre-fill — `makemessages` can pre-fill a wrong translation), `.mo` compiled.
Strings include "Show answer", "Your answer", "Correct answer", "Partly correct",
"answer shown", "Not answered" and the confirm text. There is no student-facing help
section; author help is below.

1. **Shared + fill in the blanks, short text, number.** Migration; reveal branch in
   `quiz_answer` (saved + previewer) and `element_try`; `can_reveal`; Show answer button,
   `data-confirm`, submitter handling in quiz.js/editor.js; result line;
   `_answer_switch.html` + freeze exclusion; `verdicts` / `part_verdicts` / `key_answer`
   hooks with base-class `None`; whole-element responses for converted types; resume and
   no-JS verdicts; results page through the renderer; analytics tag. **Unconverted types
   keep today's lists** live and on results. Help (`docs/help/course-admin/quiz-editors.md`
   + `.pl.md`) updated.
2. **Drag the words, match pairs, drag onto image, choice grid, multi grid.**
3. **Multiple choice + extended response.** Choice: ✓/✗ on picks from the first Check
   (＋ only when locked), Show answer, results. Extended response: Show answer reveals
   its keyword list. Delete the now-unused `_reveal_*.html` and their unused msgids.
   Help updated again.
