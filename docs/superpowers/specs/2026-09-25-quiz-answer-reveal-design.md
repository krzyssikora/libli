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
| D13 | **Lessons, the other types: treat them like fill in the blanks** — each part coloured green/red in place after a lesson Check and the answer list dropped (no answers in lessons), for short text, number, drag the words, match pairs, both grids and drag onto image; each type's lesson change ships in that type's quiz PR. Extended response keeps its keyword view (nothing to colour); multiple choice already marks in place. Chosen after the D11 premise correction. | Leaving the eight types' lesson lists as they are; Show answer in lessons (reverses D11). |

> **D11 premise correction (spec-review round 3) — RESOLVED BY D13.** D11 was chosen on
> the author's statement that lessons show no answers since #346. That was true only for
> fill in the blanks and multiple choice (`INLINE_LESSON_FEEDBACK = True`); the other
> eight types still showed their `_reveal_*` list after a wrong lesson Check. Told this,
> the owner chose D13: those types move to in-place colouring too (§5a). D11 ("no answers
> in lessons", no Show answer in lessons) stands.

## 1. Student experience in a quiz

Applies to **auto-marked** (`marking_mode = A`) questions. Not-marked (N) and
requires-review (R) questions are unchanged: they lock on first submission, show
"Answer recorded" / "Submitted for review", and never reveal a key.

1. **Before any Check** — unchanged. **No Show answer button** is rendered yet.
2. **After a Check with attempts remaining** (not locked):
   - every part is coloured green/red (D6) — blank, box, slot, zone, pair, grid row;
     for multiple choice the **ticked** options get ✓/✗, but the ＋ (a missed correct
     option) is **not** shown, because it would reveal the key;
   - result line: "◐ Partly correct · 0.25 / 1 · 2 attempts left", "✗ Incorrect · 0 / 1
     · 2 attempts left" (D4). A fully correct answer always locks (state 4). On an
     **unlocked** question the line never reads "Correct": if the §2.5 helper says
     correct only because of rounding (e.g. `max_marks = 0.01`, fraction 0.5 → earned
     0.01) while `result.correct` is False, the line reads **partial**. The marks are
     `earned_marks(to_stored_fraction(result.fraction), max_marks)` of this attempt
     (§2.5 defines the outcome from those marks);
   - a **Show answer** button after Check (§3.1 fixes its position);
   - explanation still hidden (unchanged);
   - the colours are **server-rendered and persist until the next Check** — editing a
     part does not clear its colour (no JS); test: edit a green part, the class stays
     until the next Check replaces the element.

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

`QuestionElement.part_verdicts(mark_result, answer) -> list[bool | None] | None` — the
right/wrong flag per part (a `None` **entry** means "neutral, paint nothing", and every
type's template must treat it so — never as False), in the order the type's template draws its parts. Every multi-part type
already computes these in `mark()`, under a **per-type key**: `correct` for fill in the
blanks and the dnd types (`dnd.mark_slots`), `is_correct` for choice grid and multi
grid — each type's `part_verdicts` reads its own key (no shared base implementation).
`part_verdicts` extracts **only the booleans**. Short text / number: one part, whose
verdict is the **fresh** correctness (see §2.6 — their `reveal` is a string / a
`{value, tolerance}` dict with no boolean, so it cannot come from `reveal`). Base class:
`None` (= not converted).

**Two explicit per-type switches, set PR by PR:**

1. **`SUPPORTS_REVEAL`** (class flag, base `False`). It drives: the Show answer button's
   render and `can_reveal` (§3.5) — **alone**; and the `render(mode="results")` path (§4).
   The whole-element response in `_quiz_render_feedback` / `element_try` and the
   template's `data-question-inline` in quiz mode are gated by
   **`SUPPORTS_REVEAL or INLINE_QUIZ_REVEAL`**: multiple choice already takes that path
   today via `INLINE_QUIZ_REVEAL` (views.py `_quiz_render_feedback`, views_manage
   `element_try`) and must keep it through PR 1–2 (test, PR 1: a locked choice question
   still returns the whole element with its ✓ ✗ ＋ marks). Set in PR 1 on fill in the
   blanks, short text and number; PR 2 on its five types; PR 3 on multiple choice and
   extended response. An unset type behaves exactly as it does today (its current
   response shape, no button, its old results row) **except for the result line**, and a
   reveal POST for it gets the ineligible response (test). The result line (§2.5: partly
   correct, marks, attempts-left omission) is **not** gated: it is one shared template,
   D4 is not type-specific, and it ships for **every** quiz type in PR 1.
2. **The in-place view**, which decides what a locked, not-fully-correct question shows:
   - `key_answer()` is not None → key copy + switch (every PR 1–2 type);
   - multiple choice → its inline ✓ ✗ ＋ marks (`INLINE_QUIZ_REVEAL`, D8), no switch;
   - extended response → no in-place view: its `_reveal_extendedresponse.html` keyword
     block **stays** as its view inside the feedback box, no switch (D7).

`quiz_feedback_context` sets `reveal_template = None` **iff the type has an in-place
view** (key copy or inline marks), so the old `_reveal_*` list is never printed beside
the key copy, while extended response keeps its keyword block. `part_verdicts` is
implemented by every PR 1–2 type and by choice (via its picked-option marks); extended
response returns `None` (nothing to colour). Test: a locked question of each
`SUPPORTS_REVEAL` type renders no `_reveal_*` markup except extended response's keyword
block, in the quiz and on the results page.

Elsewhere in this spec, a **"converted type"** means a type with `SUPPORTS_REVEAL` set.

Each converted type's template/tag paints its controls from a **`verdicts`** render
argument — the `fillblank.render_inputs(verdicts=...)` pattern from PR #346, extended.
`verdicts` is passed **whenever an auto-marked answer exists**, locked or not;
`mark_result` (which carries key material in `reveal`) is still passed to the template
**only when locked**, as today. Because only booleans reach the page before the lock,
D6 leaks no key — for every type except choice, where a per-option boolean **is** the key.
So **choice's `part_verdicts` is pinned as one entry per option, in option order: True /
False for a picked option, `None` for an unpicked one** — the correctness of an unpicked
option never leaves the server before the lock (after it, `choice_marks` shows ＋ as
today). No-leak test (PR 3): an unlocked, wrong choice question's HTML carries no marker,
class or attribute on any unpicked option.

**Colour is never the only cue** (WCAG 1.4.1). Removing the `_reveal_*` lists removes the
only non-colour verdict cue most types have today, so every painted part of every converted
type — in quizzes and in lessons — carries **`aria-invalid="true"` when wrong** and a
**visually-hidden "correct" / "incorrect" text** (translatable) inside or labelling the
part; a right part has no `aria-invalid`. No visible glyph is added: the look stays the
fill-in-table look the owner chose (D2 / D6). Choice keeps its existing `MARK_GLYPHS`
labels. Per-type test: a wrong part carries both cues and a right part neither `aria-invalid`
nor the "incorrect" text, in the quiz and in a lesson. (Beware the project's redefined
`.visually-hidden` in the notes / tags CSS — use the shared utility class.)

Multiple choice: `choice_marks` gains the unlocked-quiz case — ✓/✗ on **picked**
options only, never ＋ until locked. That case reads the pinned per-option **`verdicts`**,
**never `mark_result`** (whose `reveal` is the whole key); `mark_result` stays `None` in an
unlocked choice render's context, which the PR 3 no-leak test asserts.

**`answer` argument.** Choice's `MarkResult` does not carry the student's picks (`reveal`
is the correct-id set; `annotated` only the feedback-bearing wrong ones), so
`part_verdicts` takes the answer as its second argument, in `build_answer` shape. Each
path passes: the **live** answer on a fetch Check / ephemeral path; `answer_from_json(
question, latest_answer)` on stored paths (resume, no-JS, reveal response, results); and
it is **not called** for unanswered results rows (verdicts `None`, §4). Types other than
choice ignore it.

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
| Short number | **`self.value`** — a plain string, exactly `build_answer`'s shape (`post.get("answer", "")`), fed through the same `submitted_values` pairing into the key copy's `<input value=…>`. The key-copy **template** prints "± `el.tolerance`" beside the input when `el.tolerance` is non-empty, **unfiltered** — exactly as today's `_reveal_shortnumeric.html` prints `reveal.value` / `reveal.tolerance` with no filter (no display change; a pl-locale test compares the two) |
| Drag the words | the correct `slot` value per gap |
| Match pairs | the correct `slot` value per left item |
| Choice grid / multi grid | the correct column pk(s) per row |
| Drag onto image | the correct `slot` value per zone |
| Multiple choice, extended response | `None` (own view, D8 / D7) |

**One decision, made in one helper, passed as one render input.** Callers compute
`key_values = courses.quiz.key_view(question, mode=…, locked=…, fully_correct=…)`, which
returns `question.key_answer()` iff **`mode in ("quiz", "results")` AND
`marking_mode == AUTO` AND locked AND not fully correct AND `key_answer()` is not None**
(§2.6 defines "fully correct"), else `None`. The renderer receives `key_values` and draws
the second copy **and** the switch (§2.3) **iff `key_values is not None`** — it never
re-derives the decision from `locked` / `mark_result`. Every caller that renders a quiz or
results question calls `key_view`: fetch Check and reveal responses, resume, no-JS, the
previewer patch site, editor try-it, and the results helper (§4). The `marking_mode ==
AUTO` conjunct is load-bearing: a not-marked / requires-review question locks on first
submission, is never "fully correct", and has a non-None `key_answer()`, so without it
N/R questions would show the key (test: a locked N and a locked R question of each
converted type render no copy and no switch — quiz, resume, results, answered and
unanswered).
**Lesson mode never calls `key_answer()`** and never draws the copy or the switch, whatever
its own "locked on correct" notion says (D11). Test: a
wrong locked multiple-choice or extended-response question renders no switch and no copy.

**What the copy contains — the controls region only.** Each converted template factors
its answer controls into a per-type include (e.g. `_fillblank_controls.html`), rendered
once for "Your answer" and once with `copy="key"` for the correct answer. Per type:

| Type | Controls include holds | Stem |
|---|---|---|
| Fill in the blanks, drag the words | the token stem with its inputs / slots (the stem prose IS the controls) | inside the copy |
| Short text, number | the `<input name="answer">` only (+ "± tolerance" in the key copy); the key copy's input gets **`aria-label`** = the translatable "Correct answer" (its student-side label stays outside the copy) | stays outside the form, once; the key copy sits right after the student's input |
| Match pairs, both grids, drag onto image | the content of the type's controls `<fieldset>` | stays where it is today, once |

The form wrapper, the Check and Show answer buttons, the `[data-question-feedback]` box
and `data-quiz-locked` are rendered **exactly once** per question — never inside the
copy. Test (quiz and editor paths): exactly one `[data-question-feedback]`, one Check
button and at most one Show answer button per rendered question.

**Author HTML inside the copy** (fill in the blanks, drag the words: the stem prose is
author rich text). After rendering, the key copy's HTML is post-processed with
BeautifulSoup (already a dependency) using the **`html.parser`** parser and serialised
with **`decode_contents()`** (a `NavigableString` decodes entities while a `Tag`
re-escapes them — the known bs4 trap; test: a stem containing `\(a<b\)` and `&amp;`
renders identically in both copies apart from the id suffixes): **every** `id` in it — template-generated or
authored — gets the `-key` suffix and every `for=` / `aria-labelledby` /
`aria-describedby` / `aria-controls` reference inside the copy is rewritten to match
**only when its target id is itself inside the key copy** — a reference to an id outside
the copy (e.g. a hint in the stem, which stays outside for short text / match pairs /
grids) is left untouched (test case: a reference pointing outside the copy);
`<iframe>` / `<embed>` / `<object>` elements are **removed** from the key copy (the
student's copy keeps them; duplicating a GeoGebra applet is heavy and pointless). Tests
include a stem with an authored id / anchor and one with an iframe.

The key copy's controls:

- all parts painted correct;
- every control **`disabled`** (not `readonly`, which has no effect on radios,
  checkboxes, selects or draggables) and **without a `name` attribute** — disabled
  controls are never serialised by `FormData`, and the missing `name` is defence in
  depth, so no re-post can ever send the key as the student's answer. Drag types'
  nameless `<select>`s carry **`data-slot`** instead, and dnd.js's selector widens from
  `select[name="slot"]` to `select[name="slot"], select[data-slot]` so it still builds
  the drag UI for the key copy (PR 2). **Server side — one mechanism for every type:**
  the controls are built in Python with hard-coded names (`fillblank.render_inputs` →
  `name="blank"`; `dnd._render_select` via `render_selects` / `render_match_rows` /
  `render_zone_selects` → `name="slot"`; the choice-grid / multi-grid cell builders in
  `courses_extras.py` → `name="row_<pk>"`), so no builder is changed. Instead the
  **BeautifulSoup post-pass** that already rewrites the key copy's ids (below) also, on
  **every `input` / `select` / `textarea` in the key copy**: turns `name="slot"` into
  `data-slot`, **removes `name`**, and adds **`disabled`**. The names are gone before the
  HTML reaches the browser, which matters beyond leaks: a key-copy grid radio still named
  `row_<pk>` would join the student copy's radio group in the same form, and its `checked`
  would uncheck the student's pick. The student's locked copy keeps `name` and stays
  disabled **the way each type does it today**: through its controls fieldset for the
  multi-part types, and through `disabled` on the `<input>` itself for short text and
  number (they have no fieldset) — the direct `disabled` is not dropped. Test: on a locked, wrong choice-grid question
  the student copy's picked radio stays `checked` in the rendered HTML and in the DOM
  (e2e), beside the key copy; no control in any key copy has a `name`;
- **the drag UI is inert when its controls are disabled** — dnd.js's `enhance` today
  ignores `disabled` and builds live chips whose tap/drag changes the select's value
  in code. It must build a display-only UI (chips `disabled`, no drag or tap-assign)
  when the block's selects are disabled or the block is a key copy; this also covers a
  locked "Your answer" on resume and in the editor, where no script freezes the chips.
  Test: tapping / dragging a chip in either locked copy leaves every select unchanged;
- ids per the author-HTML rule above;
- **empty keys:** `key_answer()` returns `None` (no copy, no switch) when the type's whole
  key is empty — e.g. a short-text question with no accepted line. A fill-in-the-blanks
  question where only some blanks have no accepted line still gets a copy, with those
  blanks as empty green boxes (an authoring gap, not hidden); tests pin both.

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
switch is wrapped in `[data-answer-switch]` with **`role="radiogroup"`** and an
**`aria-label`** ("Answer view", translatable — §8), since it cannot sit in a fieldset with
a `<legend>`, and the CSS rule that shows the copy
matching the checked radio is scoped to a **`[data-answer-scope]`** container
(`[data-answer-scope]:has(...)`): in the quiz and the editor that attribute sits on the
question `<form>`; on the results page (§4), which has **no forms**, it sits on a plain
`<div>` wrapping the read-only question. So the results page gains no form, no buttons
and no submit target (question.js, which it loads, binds only to forms), and Enter on a
switch radio there cannot submit anything. "Your answer" is checked by default (D3). Keyboard-operable, no JS. **The key copy is hidden by default** and shown only
by the `:has()` rule, so a browser without `:has()` degrades to "Your answer" only (D3).
The radios carry **`autocomplete="off"`** so reload / back-forward form restoration can
never reopen a question on "Correct answer" (e2e covers a reload). Test: no switch radio has a `disabled`
ancestor `fieldset`, in the server render and after each script's freeze.

- `answer_view_*` **and `reveal`** (§3.1) join `attempt` in the reserved POST names
  documented on `courses.quiz.parse_attempt`: no `build_answer` may read them. It only exists on a
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

Whole-element renders pass **`submitted_values`** (from `courses.quiz.rehydrate`) and
**`feedback_for_pk=element.pk`** as well as `selected_ids` — today
`_quiz_render_feedback` and `element_try` pass only `selected_ids`, because choice was
the only whole-element type, and the fill-blank / short-text templates show values only
when `element.pk == feedback_for_pk`. The key copy uses the same pairing with
`key_answer()` as its values.

**Validation (empty answer) responses are the feedback fragment only** — no swap — on
both the enrolled and the ephemeral path, for every type: the whole-element gate
(`SUPPORTS_REVEAL or INLINE_QUIZ_REVEAL`) **excludes `validation=True`**. For converted
types that is today's behaviour; for **multiple choice it is a change** (today
`_quiz_render_feedback` checks `INLINE_QUIZ_REVEAL` before `validation` and re-renders the
whole element from the prior `latest_answer`). On the **fetch** path the student's current
(empty) inputs stay as they are. Test (fetch path, enrolled and ephemeral, incl. choice):
clear the inputs, Check → the validation message appears and the inputs stay empty. The
**no-JS** validation response is the full `quiz_unit.html` re-render, which by design
(the comment in `quiz_answer`) shows the question's prior stored answer — now with its
colours through the resume path — or empty controls on a first attempt; a no-JS test pins
that.

**Per-type enhancers after a swap (drag types, PR 2).** Today `data-dnd` sits on the
outer `<div … data-question data-dnd>`, outside the form, and `enhance()` is guarded by
`block.dataset.dndReady`. So a form-body swap leaves the outer block marked ready while
replacing its pool with an empty one — the chips vanish — and `libliEnhanceDnd(form)`
finds no `[data-dnd]` descendant at all. Both copies would also share one block and one
pool (for drag onto image, `selects[zoneIdx]` would pair the key copy's selects with the
student's badges). Therefore: **`data-dnd`, its `[data-dnd-pool]` and
`[data-dragimage-stage]` move INTO the per-type controls include**, rendered once per
copy, and are dropped from the outer div. The templates' form-less `{% else %}` branch
(e.g. matchpair's `<div>{% render_match_pairs el %}{% include "_dnd_pool.html" %}</div>`
and the drag-onto-image stage) also renders **through the same controls include**, so it
keeps a dnd root. Each copy is its own dnd root, and after a swap
those roots are new nodes with no `dndReady`, and re-enhancing them is a **new
requirement (PR 2) on all three swap sites**: quiz.js **must call**
`window.libliEnhanceDnd(form)` after its form-body swap (it has no such call today);
question.js likewise (§5a); and editor.js's **try-it** branch must call
`window.libliEnhanceDnd(tryForm)` after `tryForm.innerHTML = …` (today it calls
`libliEnhanceDnd` only after a whole editor-pane fragment swap, and re-runs only math
after a try-it). Test that fails on today's markup — on the student quiz, the lesson,
and the editor try-it in quiz and lesson mode: after a fetch Check on each drag type,
`.dnd__chip` exists in
the live copy, and each copy's selects are driven only by its own pool / targets.
blank_autosize.js needs no change: its document-wide `MutationObserver` already re-fits
after any swap, and it is a no-op where `field-sizing: content` is supported (so a
Chromium e2e cannot test it anyway). Test (PR 2 e2e): after a Check and after a reveal,
the drag UI is present in both copies.

The other render paths must draw §1 state 2 or 4 identically:

- **resume** (`build_quiz_context`, page load mid-quiz) and the **no-JS** re-render
  compute `result = _stored_result(question, response)` and
  `verdicts = question.part_verdicts(result, answer_from_json(question,
  response.latest_answer))` for an answered question, **locked or
  not**. Today `build_quiz_context` already calls `_stored_result` for **every** answered
  AUTO question (`attempt_count > 0`) and only limits `state["mark_result"]` to locked
  ones; the change is to **also derive `verdicts` from that same result on both
  branches**, keeping `mark_result` locked-only — no second `_stored_result` call. This is
  the one formula for every stored-answer path (§2.6);
  `_stored_result` already applies `answer_from_json` before `mark()`;
- **editor try-it** (`views_manage.element_try`, quiz branch, §3.3);
- **previewer** (`quiz_answer`'s non-enrolled branch). Its **no-JS** re-render has no
  stored responses (`build_quiz_context` builds no state for a previewer), so
  `_quiz_render_feedback`'s no-JS branch patches the question's `st[...]` by hand
  (`locked`, `selected_ids`, `submitted_values`, `mark_result` today). That patch site
  must also set **every new render key**: `verdicts`, the Show answer eligibility and
  its `data-confirm` marks, `revealed`, and the key-copy inputs. On **every** caller,
  when `result is None` (a validation response, or an N/R question) `verdicts = None`
  **without calling `part_verdicts`** (the per-type implementations read
  `mark_result.reveal` / `.correct` and would raise). The previewer test adds a no-JS
  validation case. Test: a no-JS previewer
  Check shows the part colours and the Show answer button.

**New render keys travel through three signatures.** `verdicts`, `revealed`, the Show
answer eligibility + its `data-confirm` marks, and the key-copy values are added as
keyword arguments to **`QuestionElement.render()`**, the **`render_element`** template tag,
and the **`{% render_element … %}` call in `_quiz_article.html`** (which today forwards
`mark_result=st.mark_result` etc. from `render_states`). A missed key fails silently (the
part is simply not painted), so a resume test asserts painted parts — it fails if
`st.verdicts` is not forwarded. (Lesson verdicts need none of this: §5a.)

**The Show answer button's render condition**, on every path:
`mode == "quiz" and can_reveal(...) and not quiz_submitted` (`can_reveal` includes the
`SUPPORTS_REVEAL` check, §3.5; the
results mode has no buttons at all; lessons never show it, D11). `can_reveal` leaves
SUBMITTED out on purpose (§3.5). The `not quiz_submitted` term is defence in depth: no
view renders the quiz page for a submitted quiz today (`quiz_unit` redirects to results,
`quiz_answer` returns `_quiz_locked_response`, and `finalize_submission` locks every
response), but the templates still take `quiz_submitted`. Test at render level:
`render(..., quiz_submitted=True)` for an unlocked answered AUTO question emits no enabled
Show answer button.

### 2.5 Result line

`_quiz_question_feedback.html` gains the **partial** state and the marks, per §1. One
template for all types. The outcome is classified **by earned marks, not by fraction**,
exactly as `views._results_row` does today — `earned == max_marks` → correct,
`earned > 0` → partial, else incorrect — via **one shared helper** (e.g.
`courses.scoring.outcome(earned, max_marks)`) used by the live line and the results page
alike, so a tiny fraction that rounds to 0.00 reads "Incorrect" in both places. Every
path gets `earned` as `earned_marks(to_stored_fraction(result.fraction), max_marks)`
(`earned_marks` needs the Decimal stored fraction; a raw float raises). The "· N attempts left" segment is
**omitted** when `max_attempts` is None (unlimited); result-line tests cover both.

### 2.6 One source per value — every render path

Any render of an **already-stored** answer (the enrolled reveal response, resume, no-JS,
the results page) re-marks it to get verdicts, and re-marking can disagree with what
was awarded if the author has since edited the key. So on every path:

- the **result line, the marks and the `data-confirm` marks** come from the **stored**
  `response.fraction`, with `earned` **always recomputed** as
  `earned_marks(stored fraction, current max_marks)` exactly as `_results_row` does — the
  stored `response.earned_marks` column is **not** read for display (it used the
  `max_marks` in force at Check time), except for a reviewed R question's
  teacher-awarded marks; the line's outcome via the §2.5 helper;
- **"fully correct"** — which alone decides whether the key copy and switch are drawn —
  is **one predicate: `_stored_result(...).correct`** (stored `fraction == 1`). Where it
  disagrees with the helper's outcome after rounding (e.g. 0.9999 → earned 1.00), the
  line still follows the helper and the switch still follows this predicate;
- the **part colours and `mark_result`** come from a **fresh**
  `mark(answer_from_json(question, latest_answer))`. The **key copy** comes from
  `key_answer()` (always the current key), not from `mark_result`.

This split **already exists**: `views._stored_result(question, response)` builds a
`MarkResult` from the stored fraction/correctness plus a fresh `reveal` / `annotated`,
and `build_quiz_context` uses it. It is the **single source** for every stored-answer
path (reveal response, resume, no-JS, results page); `part_verdicts` reads its fresh
`reveal`. No second implementation. `_stored_result` today copies only `reveal` /
`annotated` from the fresh mark and takes `correct` from the stored fraction; it gains a
**`fresh_correct`** field (the fresh `mark().correct`). `fresh_correct` is added to
`courses.marking.MarkResult` as an optional field **defaulting to None** (a live `mark()`
leaves it None), and the single-part types' `part_verdicts` read
`fresh_correct if fresh_correct is not None else correct` — so they paint correctly on a
live Check (from `correct`) and on a stored path (from the fresh mark). The key-edit test
covers a short-text question as well as a multi-part one, and a live-Check test asserts
the green / red part for short text and for number.

**The reverse case is pinned differently:** when the stored answer is fully correct
(`_stored_result(...).correct`) but a later key edit makes the fresh mark find wrong parts,
the parts are **painted all correct** (`verdicts` = all True) — a "✓ Correct" line over red
parts with no switch and no key would be unexplainable. Test: stored correct, key edited,
resume and results show every part green.

**The mirror case is accepted as-is:** a stored answer that is **not** fully correct, where
a later key edit makes the fresh mark find every part correct, renders its stored line
("◐ Partly correct" / "✗ Incorrect") over all-green parts, with the switch (whose two copies
may then look alike). It is rare, follows the stored-marks / fresh-colours rule, and shows
the student that the key has changed; test pins it so nobody "fixes" it.

Otherwise the disagreement after a key edit is accepted — the marks are what was awarded; the
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
  It must append the submitter the way editor.js already does —
  `if (e.submitter && e.submitter.name) body.append(e.submitter.name,
  e.submitter.value)` — **not** `new FormData(form, e.submitter)`, whose second
  argument older engines (pre-2023 Chrome/Firefox/Safari, common on school devices)
  silently ignore. `SubmitEvent.submitter` itself is missing before Safari 15.4, so both
  scripts also add a **fallback**: a `click` listener on `[name="reveal"]` records the
  pending submitter on its form (e.g. `form._pendingSubmitter`), and the submit handler
  uses `e.submitter || form._pendingSubmitter` (then clears it). A unit/e2e test drives the
  handler with `e.submitter` undefined and asserts `reveal` is still sent. When the submitter is the reveal button, quiz.js and
  editor.js run the `confirm()` first, **do not** increment `data-attempts-made`, and
  send `attempt` = the current `made` count (not `made + 1`) so the ephemeral path
  sees no new attempt. Mutant: drop the submitter → a test must go RED.

### 3.2 Enrolled student (`quiz_answer`)

Inside the existing transaction + `select_for_update`. **Order matters**: the reveal
branch runs **right after the SUBMITTED gate** and the `get_or_create` of the response,
and **before** today's combined locked-or-exhausted gate and before `build_answer` /
`answer_is_empty`:

1. SUBMITTED → `_quiz_locked_response` (as today);
2. `if request.POST.get("reveal")`: locked → `_quiz_locked_response`; otherwise the
   eligibility rule below. It never reaches the exhausted gate, so a response left
   **exhausted but unlocked** (an author lowered `max_attempts` after the student used
   their attempts) can still be revealed — Show answer is the way out (§1.5); and it
   never reaches the empty-answer validation, so an emptied form cannot block it
   (test: an enrolled reveal with emptied inputs locks the question and shows the
   stored answer);
3. otherwise today's locked / exhausted gate, `build_answer`, validation, marking.

Within step 2:

- eligible iff `can_reveal(question, attempts_made=response.attempt_count,
  locked=response.locked)` (§3.5);
- then `locked = True`, `revealed_at = now()`, and **both** the fetch and the no-JS
  response call `_quiz_render_feedback(..., result=_stored_result(question, response))`
  — never with `result=None`, which `quiz_feedback_context` reads as an N/R question and
  renders "Answer recorded" (test: an enrolled reveal response has the marks line, not
  "Answer recorded"). It **ignores the posted answer** —
  "Your answer", the verdicts and the marks come from the stored latest attempt, so a
  student cannot slip in an unchecked answer. It does **not** increment
  `attempt_count` and creates **no** `Attempt` row;
- eligible, no-JS → the same full `quiz_unit.html` re-render the no-JS Check already
  does (`_quiz_render_feedback`'s non-fetch branch), now showing the locked state through
  the stored-answer path (§2.4);
- ineligible (no attempt yet, or N/R, or not `SUPPORTS_REVEAL`) → fetch: 409 (quiz.js
  reloads); no-JS: redirect back to the quiz unit page (the question renders its
  current state).

### 3.3 Previewer and editor try-it (ephemeral)

Stateless, persists nothing, as today. When the POST carries `reveal`,
`attempts_made = parse_attempt(POST)` (the client sent its `made` count, §3.1 — note
`parse_attempt` floors at 1, so a reveal sent with `made = 0` reads as 1; the client
never offers the button before a Check, and the server-side check is advisory on this
path), and `locked = False` — a previously locked state is **not** modelled server-side
(the client has already frozen the question, so its reveal button no longer exists).
`can_reveal` decides. On this path ineligibility can only come from N/R marking or a
type without `SUPPORTS_REVEAL` (the attempt floor makes `attempts_made >= 1`), and
neither ever renders the button, so an ineligible ephemeral reveal (fetch or no-JS,
previewer or editor) simply **ignores `reveal` and is processed as a normal ephemeral
Check** of the posted answer — whatever response that type gives a Check today.

- Previewer: `quiz_answer`'s non-enrolled branch → `ephemeral_quiz_feedback(...,
  reveal=True)` → a locked stand-in → the same whole-element render.
- The stand-in (today a `SimpleNamespace(locked, attempt_count, latest_answer)`) gains
  **`revealed_at`** on **every** branch — a timestamp on a reveal, `None` otherwise,
  including the validation branch — and `quiz_feedback_context` passes a `revealed`
  flag (from `response.revealed_at`) to the result-line template, so "· answer shown"
  renders on the enrolled and both ephemeral paths alike.
- Editor: `views_manage.element_try`'s quiz branch does the same with its own context
  builder, and returns the whole element for converted types (§2.4).
- **Accepted divergence (pinned by a test):** the ephemeral reveal marks **whatever the
  form holds** at the moment of the reveal, which may differ from the last Checked
  answer. The enrolled path uses the stored answer. This is acceptable because nothing
  is persisted and only authors/previewers reach this path.
- **Edge cases of that divergence, defined:** a reveal **bypasses the empty-answer
  validation branch** — an emptied form is marked as-is (every part wrong, 0 marks),
  locked, with an empty "Your answer" and the switch. A form that happens to be fully
  correct locks as "✓ Correct · 1 / 1 · answer shown" with no switch. If the form was
  edited after the last Check, the confirm text's marks (§3.4, from the last Check)
  differ from the locked marks (from the form) — accepted on this path only; §3.4's
  "always matches" holds on the enrolled path. All three are in the ephemeral-divergence
  tests, and no test asserts confirm-vs-locked equality on the ephemeral path.

### 3.4 Confirmation text

The reveal button carries a server-rendered `data-confirm`, built with the latest
attempt's marks, e.g. msgid `"Show the answer? This ends the question: you won't be
able to try again, and you keep the marks you have now (%(earned)s of %(max)s)."`, with
`earned` and `max` formatted exactly as the result line formats them (the existing
`marks` template filter, `courses_extras.py`, incl. the Polish decimal comma); a test
compares the confirm text's marks with the result line's. It is
re-rendered with every whole-element response, so it always matches the latest Check.
quiz.js / editor.js pass it to `confirm()`. No-JS proceeds without a prompt, like Finish.
e2e must register a dialog handler (Playwright auto-dismisses `confirm` → the reveal
would silently not happen).

### 3.5 Reveal-rule parity

`courses.quiz.can_reveal(question, *, attempts_made, locked) -> bool`:
**`type(question).SUPPORTS_REVEAL`**, AUTO marking mode, `attempts_made >= 1`, not
`locked`. The flag check lives **here and only here**, so every caller — the button's
render condition (§2.4), the enrolled branch (§3.2 step 2), the ephemeral paths (§3.3)
— gets it by calling `can_reveal`. The SUBMITTED check stays in
`quiz_answer`'s existing gate (the ephemeral path has no submission). Both the saved
path (§3.2) and both ephemeral paths (§3.3) call it; `tests/test_quiz_lock_rule_parity.py`
gains a case per condition, including an unconverted AUTO type (a crafted reveal POST
for it gets the ineligible response on the enrolled path and a normal Check on the
ephemeral ones).

### 3.6 Migration

`courses/migrations/0067_questionresponse_revealed_at.py` — nullable
`DateTimeField`, reversible (plain AddField). Its dependency must be the graph head at
the time it is written (currently `0066_blank_answers_unescape`).

## 4. Results page (D10)

`views._results_row` / `quiz_results.html` render each question **read-only through
the same renderer**, from the stored `latest_answer`, locked — the results helper passes
**`locked=True` for every row**, to `key_view` and to the render, exactly as `_results_row`
hard-codes it today (`finalize_submission` locks every response on Finish, so this only
pins the invariant); only `fully_correct` varies per row — via a new render mode
**`render(mode="results")`**: each converted template gains that branch, which emits a
`<div data-answer-scope>` in place of the `<form>`, **no** Check / Show answer button,
the controls include(s) with values + verdicts, the key copy, the switch, and a
`[data-question-feedback]` box filled with a **`feedback_html`** fragment. That fragment is
a new **`_results_question_feedback.html`**, built by the results helper from today's
`quiz_results.html` row markup — the outcome badge with earned / possible, "Not answered",
"Answer recorded" / "Submitted for review" / reviewed with the teacher's marks and
`review_feedback`, "· answer shown", and the explanation. `_quiz_question_feedback.html`
(the live quiz) gains none of these results-only states. (Today's templates have
only an `{% if element %}` form branch and a bare `{% else %}` branch; neither fits.)
Each PR lists this branch in its per-type template work. **The student's copy is frozen
in results mode by the same mechanism the quiz uses for that type** — the results branch
keeps the disabled wrapping fieldset around the multi-part types' controls include, and
renders `disabled` on the short-text / number input — so its inputs are never editable and
dnd.js (which PR 2 adds to this page) builds the inert UI for it. Tests: the results page
contains no `<form>` and no submit button inside any question; every control in both
copies is disabled; dragging or tapping a chip on the results page changes no select.

Values follow §2.6 (stored marks / fresh colours). **Unanswered** rows (no
`QuestionResponse`, or `latest_answer` None) get `verdicts = None` — neutral controls —
and, **for types whose `key_answer()` is not None**, `mark()` is **not** called — only the
key copy is drawn. **Multiple choice and extended response** have no key copy; their only
view of the answer comes from a mark result, so for them the results helper keeps
today's `mark(build_answer(QueryDict()))` ("reveal all"): choice shows ＋ on every correct
option, extended response its keyword block. Test (PR 3): an unanswered choice row shows
＋ on the correct options; an unanswered extended-response row shows its keywords.

Rows:

- **auto-marked, answered**: result line ("· answer shown" if `revealed_at`), the switch
  (or ✓ ✗ ＋ for choice), the explanation;
- **auto-marked, unanswered**: empty controls, "Not answered · 0 / 1", and the answer
  still viewable — the switch for types with a key copy; ＋ on the correct options for
  choice; the keyword block for extended response. The results helper treats an
  unanswered **auto-marked** row as **locked and not fully correct without calling
  `_stored_result`** (there is no response / `latest_answer` to read) and passes that to
  `key_view` — which still returns `None` for an N/R question;
- **N / R, answered**: the student's answer read-only + "Answer recorded" / "Submitted
  for review" / the teacher's `review_feedback`; never a key (as today);
- **N / R, unanswered**: empty controls + "Not answered"; no marks, no switch, no key;
- score badges and the total stay.

Unconverted types (during PR 1–2) keep today's list rows.

The results page loads only question.js (and KaTeX when `has_math`) today. **PR 2 adds
dnd.js** to it so drag types show the (inert, §2.2) drag UI rather than the native
select fallback.

## 5. Teacher analytics

`templates/courses/manage/analytics_student_quiz.html` shows an **"answer shown"** tag on
rows whose `QuestionResponse.revealed_at` is set. Nothing else in analytics or the review
queue changes.

**`_results_row` has a second consumer:** `views_analytics._quiz_answer_rows` calls it and
feeds `row["reveal_result"]`, `row["marks"]`, `row["outcome"]`, `row["earned"]` and
`row["answered"]` to `answer_summary.summarise` and the analytics template — including a
`reveal_result` built for **unanswered** AUTO rows (`mark(build_answer(QueryDict()))`),
which the teacher's "expected answer" column relies on. Therefore `_results_row` keeps
**every existing key with its current semantics**; the results page's new render data
(`verdicts`, key copy, the `mode="results"` render) is built by a **separate helper**
used only by `quiz_results.html`, and the §4 "`mark()` is not called for unanswered rows"
rule applies to that helper only. Test: the analytics student-quiz page still shows the
expected answer for an answered and an unanswered row of each `SUPPORTS_REVEAL` type.

## 5a. Lessons (D13)

Each type converted by PR 1 / PR 2 also becomes an in-place type **in lessons**, with
exactly the #346 mechanism fill in the blanks uses:

- the type sets **`INLINE_LESSON_FEEDBACK = True`**, so `check_answer` and
  `element_try`'s lesson branch return the whole re-rendered element (lesson mode) and
  the lesson render drops `reveal_template` — **no answer list, no key copy, no switch,
  no Show answer** in lessons (D11);
- **where lesson verdicts come from:** in lesson mode `QuestionElement.render()` computes
  them **itself** — `verdicts = self.part_verdicts(mark_result, answer)` where `answer` is
  **`selected_ids` for set-answer types (multiple choice)** and **`submitted_values`
  otherwise** (`check_answer` and the restore branch pass `submitted_values=None` for a set
  answer; the picks travel only in `selected_ids`; restore's `rehydrate()` output is the
  `build_answer` shape) **iff
  `element.pk == feedback_for_pk`**, else `None`. No caller passes lesson verdicts, so
  every lesson path gets them with no new plumbing: fetch, no-JS, practice-state
  restore (`render_element`'s restore branch), editor try-it, and questions **nested in
  containers** (which receive only the container `page` dict — `feedback_for_pk`,
  `selected_ids`, `submitted_values`, `mark_result` — never a new kwarg). The
  `feedback_for_pk` guard is load-bearing: the no-JS lesson re-render hands **one**
  page-level `mark_result` to every question on the unit, so without it a question
  would paint from another question's result, and a different type's `reveal` shape can
  raise. Tests: a lesson question nested in a callout paints on no-JS and on restore; a
  no-JS lesson Check on question A leaves a converted question B of another type
  unpainted and renders without error;
- the lesson form carries `data-question-inline` in lesson mode (question.js and
  editor.js already swap the form body for it). For drag types, the per-copy `data-dnd`
  root (§2.4) applies in lessons too, and **question.js** must call
  `window.libliEnhanceDnd(form)` after its swap, like quiz.js;
- the verdict line and the explanation stay, as for fill in the blanks today — the lesson
  line is **unchanged**, so a partly right lesson answer still reads "Incorrect" above its
  green and red parts. D4's partial wording is quiz-only; the lesson line
  (`_question_feedback.html`) is shared by every lesson question, and changing it is out of
  scope here.

Extended response and multiple choice are unchanged in lessons. Tests per converted
type: a wrong lesson Check (fetch, no-JS, restore, editor try-it) paints each part and
contains no `_reveal_*` markup and no "Correct answer" text. On a correct lesson answer
the newly converted types keep **today's** behaviour: Check hidden (question.js
`finishSolved`), inputs **stay editable** — only fill in the blanks has
`data-lock-on-correct`, and D13 does not extend it.

## 6. Out of scope

Show answer / answers in lessons (D11); multiple-choice partial credit (D9); latest-vs-best (D5); the teacher
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
Strings include "Show answer", "Your answer", "Correct answer", "Answer view", "Partly correct",
"answer shown", "Not answered" and the confirm text. There is no student-facing help
section; author help is below.

1. **Shared + fill in the blanks, short text, number** (+ short text and number in
   lessons, §5a). Migration; reveal branch in
   `quiz_answer` (saved + previewer) and `element_try`; `can_reveal`; Show answer button,
   `data-confirm`, submitter handling in quiz.js/editor.js; result line;
   `_answer_switch.html` + freeze exclusion; `verdicts` / `part_verdicts` / `key_answer`
   hooks with base-class `None`; whole-element responses for converted types; resume and
   no-JS verdicts; results page through the renderer; analytics tag. **Unconverted types
   keep today's lists** live and on results. Help (`docs/help/course-admin/quiz-editors.md`
   + `.pl.md`) updated.
2. **Drag the words, match pairs, drag onto image, choice grid, multi grid** — in quizzes
   and in lessons (§5a). New strings through the "every PR" i18n step above. Help updated
   for the lesson behaviour change of these types (the PR 1 Show answer text is written
   type-agnostically, so it needs no change).
3. **Multiple choice + extended response.** Choice: ✓/✗ on picks from the first Check
   (＋ only when locked), Show answer, results. Extended response: Show answer reveals
   its keyword list. **Template clean-up**: after D13 no lesson or quiz path reaches
   the `_reveal_*.html` lists of the converted types; each may be deleted only after a
   grep of every `REVEAL_TEMPLATE` / `reveal_template` / `_reveal_` consumer (quiz,
   lesson, results, analytics, editor) comes back empty for it.
   `_reveal_extendedresponse.html` stays — it is extended response's view (D7). Test
   (PR 3): a wrong **lesson** Check and a wrong locked **quiz** Check render without error
   for every question type. Help updated again.
