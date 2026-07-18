# Lesson-mode question answer restore (student practice state, slice 3)

## Purpose

A student who answers a question inside a **lesson** (not a quiz) loses that answer the
moment the page reloads. `check_answer` marks the submitted answer and returns feedback, but
its own comment says it plainly: *"NOTHING is persisted."* A stray reload — a mis-tapped Enter,
a navigation, a browser restore — wipes work the student did.

Every other interactive lesson element already survives a reload through the slice-1/slice-2
**practice-state substrate** (`UnitProgress.element_state`): mark-done, the reveal gates, the
graded self-checks, the stepper. Questions are the last interactive family that does not. This
slice closes that gap for the **simple, server-refillable question types**, deferring the
drag/match/grid widgets (whose interactive JS the server cannot re-arm) to a follow-up.

### Scope

**In scope — these five `QuestionElement` subclasses persist AND restore:**

- `ShortTextQuestionElement`
- `ShortNumericQuestionElement`
- `ExtendedResponseQuestionElement`
- `ChoiceQuestionElement` (single- and multiple-choice)
- `FillBlankQuestionElement`

**Deferred (this slice must neither persist nor restore them):**
`DragFillBlankQuestionElement`, `MatchPairQuestionElement`, `DragToImageQuestionElement`,
`ChoiceGridQuestionElement`, `MultiGridQuestionElement`. These render an interactive JS widget
on top of the form; a server-rendered "submitted_values" static view would half-restore into a
widget the boot JS cannot reconcile. They are excluded on the **save** side (not merely the
restore side) so they never write a blob that a future reader might half-restore.

### Non-goals

- **No attempt history.** Only the latest answer is kept, exactly as quiz mode keeps only
  `QuestionResponse.latest_answer`.
- **No stored verdict.** The correctness is re-derived on every load (see Data flow), so an
  author who later fixes a wrong answer key re-marks a restored answer correctly.
- **No analytics / gradebook coupling.** Lesson practice is ungraded and absent from analytics;
  this slice does not touch `QuestionResponse`, `QuizSubmission`, or any rollup.
- **No quiz-mode change.** Quiz answer persistence already exists and is untouched.

## Background: what already exists (and is reused verbatim)

**Quiz mode already persists + rehydrates question answers**, and this slice reuses its pure
helpers unchanged:

- `courses/quiz.py::build_answer(POST)` — server-side, per-type parse of a real `QueryDict`
  (it mixes `.get()` and `.getlist()`; a plain dict-of-lists silently breaks the multi-value
  types, so the parse must stay server-side over the real POST).
- `courses/quiz.py::answer_to_json(answer)` — JSON-safe form of a `build_answer` payload
  (set → sorted list, tuple → list, else unchanged).
- `courses/quiz.py::answer_is_empty(answer)` — True iff the payload carries nothing markable.
- `courses/quiz.py::rehydrate(question, latest_answer)` → `(selected_ids, submitted_values)`
  for the shared element templates (choice → `selected_ids`; the rest → `submitted_values`).
- `courses/quiz.py::answer_from_json(question, latest_answer)` — inverse of `answer_to_json`,
  reconstructs a `mark()` input from stored JSON.

**The slice-1 practice-state substrate:**

- `UnitProgress.element_state` — a per-student JSON map keyed by `str(element.pk)`, values are
  dicts. `build_lesson_context` reads it into the ambient template context key `element_state`,
  applying a **read-side fail-open**: *any non-dict value is dropped* and any non-int-coercible
  key is dropped, rather than 500 the lesson from inside a template tag.
- `element_state_save` (view, route `.../u/<node_pk>/state/`) — the JSON write endpoint. It
  already contains a **stubbed `fields` branch** returning `400 "fields is not supported yet"`,
  left as an anticipated seam. **This slice supersedes that stub** (see Architecture — the save
  rides `check_answer`, not this branch); the stub stays returning 400.
- `render_element` (template tag in `courses/templatetags/courses_extras.py`) — dispatches each
  element's render. Its `QuestionElement` branch passes the **global** `feedback_for_pk`,
  `selected_ids`, `submitted_values`, `mark_result`; its non-question branch passes the
  per-element `element_state` map. **The question branch does not consult `element_state`
  today** — that is the restore seam this slice adds.
- `check_answer` (view, route `.../element/<element_pk>/check`) — the lesson question check:
  `answer = question.build_answer(request.POST)`, `result = question.mark(answer)`. Two response
  paths: a JS **fragment** path (`_wants_fragment`) returning just the re-rendered element, and a
  **no-JS** path re-rendering the whole `lesson_unit.html` with `feedback_for_pk=element.pk`.

**The single-value `feedback_for_pk` model is the thing this slice generalizes.** Every question
template gates BOTH its input refill AND its feedback block on `element.pk == feedback_for_pk`
(e.g. `shorttextquestionelement.html:9`, `choicequestion.html:14/32`). `feedback_for_pk` is one
global pk — "which element just got checked" — which is fine when exactly one question shows
feedback. On restore, *many* questions may need refilling at once, so restore must make
`element.pk == feedback_for_pk` true **per element**, driven from the `element_state` map rather
than the single global.

## Architecture / components

The design is **persist-on-check + server-side restore**, contained in four small seams. No new
endpoint, no new migration, no new model field, no question-template edits.

### C1. Blob shape — a dict envelope

Stored blob for a question element:

```json
{ "answer": <answer_to_json(build_answer(POST))> }
```

The **envelope is mandatory, not cosmetic.** The raw `answer_to_json` output is a list (choice /
fill-blank) or a string (text / numeric / extended) — never a dict. `build_lesson_context`'s
read-side fail-open drops any non-dict blob, so a bare list/string answer would be silently
discarded before it ever reached a template. Wrapping it as `{"answer": …}` keeps it dict-shaped
(consistent with every other practice-state blob) and lets it survive the read filter. The
verdict is **never** in the envelope — it is re-derived on load.

### C2. Scope gate — one class attribute, two consumers

Add a class attribute `RESTORABLE_IN_LESSON` to `QuestionElement` (base default `False`) and set
it `True` on exactly the five in-scope subclasses. Both the save side (C3) and the restore side
(C4) gate on `getattr(obj, "RESTORABLE_IN_LESSON", False)`, so the in-scope set has a **single
source of truth** and the deferred widgets can never leak in on one side only.

### C3. Save — folded into `check_answer`

`check_answer` already computes `answer` and marks it. After marking, if the question is
in-scope (C2):

- `answer_is_empty(answer)` → **delete** the element's key (the student cleared their answer).
- else → **store** `{"answer": answer_to_json(answer)}` under `str(element.pk)`.

The write reuses the slice-1 atomic pattern (`get_or_create` + `select_for_update` + `save`),
extracted into a shared helper (C5) so `check_answer` and `element_state_save` cannot drift. The
save runs on **both** `check_answer` response paths (JS fragment and no-JS), because both have the
same parsed `answer` in hand — persistence is therefore uniform across JS and no-JS. A
non-in-scope question runs `check_answer` exactly as today (mark + feedback, no write).

Rationale for riding `check_answer` rather than the `element_state_save` `fields` branch: the
answer is already server-parsed and marked at this point, so persisting inline costs no second
round-trip, needs no `QueryDict` reconstruction, requires no near-vacuous "question validator" in
`state.py`, and persists on the no-JS path for free. The `fields` stub is left returning 400.

### C4. Restore — inside `render_element`, zero template edits

In the `QuestionElement` branch of `render_element`, before falling through to today's global-kwarg
render, attempt a per-element restore. Restore applies when **all** hold:

1. the element is in-scope (C2); AND
2. `element.pk != feedback_for_pk` — the element is **not** the one being checked live (the live
   answer always wins for its own element; this is the disambiguation the single global cannot
   express); AND
3. the `element_state` map (`context.get("element_state")`) has a dict blob for `str(element.pk)`
   carrying an `"answer"` key.

When it applies, reconstruct the render inputs with the reused quiz helpers and re-mark:

```python
stored = blob["answer"]
selected, submitted = rehydrate(obj, stored)
result = obj.mark(answer_from_json(obj, stored))
# render with feedback_for_pk = element.pk, selected_ids = selected,
#            submitted_values = submitted, mark_result = result
```

Because the template gates on `element.pk == feedback_for_pk`, rendering the restored element
with `feedback_for_pk = element.pk` makes it refill its input(s) and show the re-marked feedback
— **identical** to the live-checked path. The six question templates need **no changes**.

**Invariant that bounds the risk:** restore's `obj.mark(answer_from_json(obj, stored))` is the
*same* `mark()` call `check_answer` already makes on the live path (line 757). If the live check
cannot error for a given type/answer, neither can restore. Restore introduces no new marking
surface.

The whole restore block is wrapped in `try/except` → on **any** failure it falls through to the
un-restored global-kwarg render (fail-open; see Error handling). The two data sources never
collide: the global kwargs serve the single live-checked element and the JS-fragment path (which
does not route through `render_element` at all); the map serves every previously-answered element
on a full-page render.

### C5. Shared atomic-write helper

Extract the slice-1 inline write (currently in `element_state_save`) into a module-level helper,
e.g.:

```python
def save_element_state(user, unit, element_pk, blob):
    """blob: a dict to store, or None to delete the key. Atomic; upserts the row."""
    with transaction.atomic():
        UnitProgress.objects.get_or_create(student=user, unit=unit)
        progress = UnitProgress.objects.select_for_update().get(student=user, unit=unit)
        if blob is None:
            progress.element_state.pop(str(element_pk), None)
        else:
            progress.element_state[str(element_pk)] = blob
        progress.save()
```

Both `check_answer` (new caller) and `element_state_save` (refactored to call it for its
EMPTY/store cases) use it, so the write path is single-sourced. `element_state_save`'s echo /
REJECT / previewer semantics are preserved — only the atomic block moves.

### C6. Check-button consistency — one boot pass in `question.js`

After a live correct check, `question.js` hides the Check button (a fully-correct answer needs no
re-check). On a **restore** render the button is emitted normally, so a restored-correct question
would show a stale, pointless Check button. Add a small boot pass in `question.js`: for each
question whose DOM already shows `.question__verdict.is-correct` on load, hide its Check/Submit
button — mirroring the post-fetch behavior. Still no template change. A restored **incorrect**
answer keeps its Check button (the student can retry), which is correct.

## Data flow

**Answering (JS lesson):** student fills input → `question.js` POSTs the form to `check_answer`
→ `build_answer` + `mark` → (in-scope) `save_element_state(user, unit, pk, {"answer": …})` →
fragment response swaps the feedback/element in place. One round-trip, unchanged from today except
for the added write.

**Answering (no-JS):** form POSTs to `check_answer` → same parse/mark/save → full
`lesson_unit.html` re-render with `feedback_for_pk=element.pk`. The just-answered question shows
via the global kwargs; every *other* previously-answered question shows via C4 restore.

**Reload / fresh GET (`lesson_unit`):** `build_lesson_context` loads `element_state` (fail-open
filtered). `feedback_for_pk` is unset (≠ any real pk). For each in-scope question with an
`"answer"` blob, `render_element` (C4) rehydrates, re-marks, and renders it filled + verdicted.
`question.js` boot pass (C6) hides Check on the ones that re-marked correct.

**Clearing an answer:** student empties the input and re-checks → `answer_is_empty` → key deleted
→ next reload shows the question blank.

**Start fresh (`progress_reset`):** already wipes `element_state` wholesale, so question answers
reset with everything else. No new code — but a test pins it (Testing).

## Error handling

- **Read-side fail-open (existing):** `build_lesson_context` drops non-dict blobs and
  non-int-coercible keys. The C1 envelope is a dict, so it survives; a corrupted non-dict value
  is dropped and the question renders blank rather than 500ing.
- **Restore-side fail-open (new, C4):** the rehydrate/re-mark block is wrapped in `try/except`.
  Any exception (a malformed `"answer"`, a shape `rehydrate`/`mark` cannot digest) → fall through
  to the un-restored render. A single bad blob can never take down the lesson page or any sibling
  question.
- **Stale references self-heal:** a stored choice pk whose choice the author later deleted simply
  fails to match on re-mark, and its checkbox is absent from the rendered choices — it drops
  silently. Because the verdict is re-derived (never stored), an author who fixes a wrong answer
  key re-marks every restored answer correctly on the next load.
- **Previewer parity (existing slice-1 policy):** practice state persists for **any** viewer who
  can access the lesson (author/teacher included), not only enrolled students; `check_answer`
  already gates on `can_access_course`. The save adds no new authorization surface.
- **Deferred types:** excluded on the save side (C2/C3), so no blob is ever written for them; even
  if a hand-forged blob appeared, C4's in-scope gate refuses to restore it.

## Testing

Falsification-first (per the project's hard-won rule: a passing test proves nothing until you
delete the guard and watch it go red). Each guard below names what to delete to see RED.

**Save (C3):**
- Checking an in-scope question stores `{"answer": <json>}` under `str(element.pk)` in
  `element_state`. *Falsify:* remove the `save_element_state` call → key absent.
- Per-type envelope correctness: `ShortText` → string; `ChoiceQuestion` (multi) → sorted pk list;
  `FillBlank` → list of strings. *Falsify:* store the raw answer without the `{"answer": …}`
  envelope → read-side filter drops it → restore test (below) goes blank.
- Empty answer after a prior stored answer **deletes** the key. *Falsify:* skip the
  `answer_is_empty` branch → stale key remains.
- A **deferred** type (e.g. `MatchPairQuestionElement`) checked in a lesson stores **nothing**.
  *Falsify:* remove the `RESTORABLE_IN_LESSON` gate on the save side → a blob appears.
- The no-JS `check_answer` path also persists. *Falsify:* gate the save behind `_wants_fragment`
  → no-JS POST leaves no blob.

**Restore (C4):**
- Seed `element_state` **through the lesson view** (str-keyed `UnitProgress`, never `obj.render`
  with a str key — the int/str-key seam), GET `lesson_unit`, assert the input is pre-filled and
  the re-marked verdict is shown. Cover at least `ShortText` (value attribute), `ChoiceQuestion`
  (checked inputs), `FillBlank` (per-blank values). *Falsify:* remove the C4 restore block →
  inputs render blank, no verdict.
- The live-checked element uses the **live** answer, not a stale blob: with both a stored blob and
  a differing live POST for the same element (no-JS path), the rendered value is the live one.
  *Falsify:* drop the `element.pk != feedback_for_pk` guard → the stale blob overrides the live
  answer.
- A **deferred** type with a hand-forged blob does **not** restore. *Falsify:* remove the
  restore-side in-scope gate → it restores.
- A corrupt/non-digestible `"answer"` blob → lesson still returns 200 and that question renders
  un-restored (fail-open). *Falsify:* remove the `try/except` → the GET 500s.

**Reset:**
- `progress_reset` clears an in-scope question's blob. *Falsify:* (guards existing behavior)
  assert the blob is gone after reset; a regression that special-cased question blobs would fail.

**Check button (C6) — e2e, real UI (drive the actual gesture, never `page.evaluate`):**
- Answer an in-scope question **correctly** in a real lesson, reload the page, assert: the answer
  is shown, the correct verdict is shown, and the Check button is hidden. *Falsify:* remove the
  boot pass → the button is visible after reload.
- Answer **incorrectly**, reload, assert the answer + wrong verdict show and Check is **still
  visible**.

**Regression breadth:** run the full non-e2e suite at every red-window boundary (a red window
blinds per-task reviewers), plus the focused question/quiz/state e2e files. `manage.py check`,
`ruff`, `ruff format --check`, and `makemigrations --check` (expected: no new migration) all clean.
