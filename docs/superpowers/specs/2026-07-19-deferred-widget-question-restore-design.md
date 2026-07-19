# Lesson-mode answer restore for the deferred widget question types (student practice state)

## Purpose

Slice 3 (`2026-07-18-question-answer-restore-design.md`) made a student's in-lesson question
answer survive a reload — but only for **five "simple, server-refillable" types** (ShortText,
ShortNumeric, ExtendedResponse, ChoiceQuestion, FillBlank). It **deferred five more**, stating
they *"render an interactive JS widget on top of the form; a server-rendered submitted_values
static view would half-restore into a widget the boot JS cannot reconcile."* Those five are the
last interactive lesson family that still loses a student's work on reload:

- `ChoiceGridQuestionElement` (Matrix)
- `MultiGridQuestionElement` (Multi-select grid)
- `MatchPairQuestionElement`
- `DragToImageQuestionElement`
- `DragFillBlankQuestionElement` (drag-words)

**This slice's premise is that slice 3's deferral reason is wrong, and its first job is to prove
that before building anything.** A source investigation found that these five are *not* special:
the slice-3 restore path is entirely type-agnostic, every one of the five already round-trips
through the same `rehydrate`/`answer_from_json`/`mark` helpers **on the quiz results page today**,
and the only thing gating them out of lesson restore is the class flag `RESTORABLE_IN_LESSON =
False`. If that holds, enabling restore is the *same one-flag flip* the five simple types already
use. This spec is therefore **verify-first**: it treats "the flag flip is sufficient" as a
hypothesis to falsify per type, not a fact to build on.

### Scope

**In scope — all five deferred `QuestionElement` subclasses persist AND restore**, reaching parity
with the five simple types slice 3 already handles.

The work is **verification, not new mechanism.** Concretely:

1. **Falsify the premise first** (see Architecture C1). Write a per-type restore test for all five,
   RED with `RESTORABLE_IN_LESSON = False` (renders un-restored) and GREEN after the flip. The
   minimum-confidence floor before trusting the flip is **both grid shapes (`ChoiceGrid` *and*
   `MultiGrid`) and at least one drag type** gone red→green (the authoritative floor lives in C1 — the
   two grids are different payloads, so one grid does not vouch for the other); every type is then
   individually required to pass or be carved to the Fallback.
2. **Flip `RESTORABLE_IN_LESSON = True`** on the five models. That single flip enables both the
   save side and the restore side (C2).
3. **Prove the drag widgets actually re-arm** with a real-browser e2e (C4), the image-overlay type
   mandatory — because the deferral premise was specifically about the *JS widget*, which a Django
   test client cannot observe.

**Out of scope / explicitly not built:**

- **No new client-rehydrate / `data-state` machinery.** The reveal-gate/stepper boot-rearm pattern
  is *not* introduced here; the investigation found it unnecessary (grids have no student JS; the
  drag widgets re-arm from server-rendered native `<select>` values). If a type turns out to
  genuinely need it, that type drops to the **Fallback** (below) rather than growing this slice.
- **No changes to the five simple types**, to quiz mode, to the save/restore substrate, or to any
  question template.
- **No new endpoint, model field, migration, or translatable string.**
- **No author-side widget changes.** `choicegrid.js` / `multigrid.js` are editor-only enhancers and
  are untouched.

### Non-goals

Inherited verbatim from slice 3: **no attempt history**, **no stored verdict** (re-derived every
load, so an author fixing a wrong key re-marks a restored answer correctly), **no analytics /
gradebook coupling**, **no quiz-mode change**.

## Background: what already exists (and is reused unchanged)

The slice-1/2/3 practice-state substrate is fully in place.

**Prerequisite — PR #158 is MERGED (2026-07-19) and is part of this branch's base (`master`).** The
type-agnostic restore branch and the fail-open `try/except` + `logger.exception` (which a test below
names) are the state PR #158 established. Every "existing" / "just refactored by PR #158" claim below
holds **only** on a base that includes it. This slice branches from `master` *after* that merge, so
the premise is satisfied — but if it were ever re-based onto a pre-#158 point, "no other production
edit" would be false and the fail-open would not yet exist. Verify `git merge-base` includes #158
before relying on these facts.

The load-bearing facts this slice depends on, each verified against source:

- **The restore path is type-agnostic.** `render_element`'s `QuestionElement` restore branch
  (`courses/templatetags/courses_extras.py`; just refactored by PR #158) reads the `{"answer": …}`
  blob from the int-keyed ambient `element_state` map, calls `rehydrate(obj, stored)` +
  `answer_from_json(obj, stored)` + `obj.mark(...)`, and passes `selected_ids` / `submitted_values`
  / `mark_result` into the branch's single `obj.render(...)`. It contains **no per-type code** and
  gates only on `mode=="lesson"`, `getattr(obj, "RESTORABLE_IN_LESSON", False)`, and
  `element.pk != feedback_for_pk`.
- **The save path is type-agnostic.** `check_answer` (`courses/views.py`) computes `answer =
  question.build_answer(request.POST)`, marks it, and — gated on `RESTORABLE_IN_LESSON` — calls
  `save_element_state(user, unit, pk, {"answer": answer_to_json(answer)})` (or deletes the key when
  `answer_is_empty(answer)`). Both the JS-fragment and no-JS paths persist.
- **`RESTORABLE_IN_LESSON` is the sole gate.** Base default `False` on `QuestionElement`
  (`courses/models.py`); the five deferred models inherit that default and are the *only* thing
  keeping them out. Flipping it flips **both** sides at once (single source of truth, C2 of slice 3).
- **The quiz results page already round-trips all five, server-side, on every load.** The quiz
  render loop (`courses/views.py`, the results/review render) calls `rehydrate(q, r.latest_answer)`
  for **every** `QuestionElement` with no type check, feeding the shared element templates. This is
  the proof the server can reconstruct each type's answered state from stored answer data — the
  lesson restore path reuses the identical helpers.
- **The generic helpers are type-blind for non-choice payloads.** `rehydrate` (`courses/quiz.py`):
  choice types → `(selected_ids, None)`; everything else → `(set(), latest_answer)` verbatim.
  `answer_from_json`: non-choice types pass `latest_answer` straight to `mark()`. `answer_to_json`:
  set→sorted list, tuple→list, else unchanged. `answer_is_empty` **recurses**, so an all-`""` grid
  list or a `[[],[]]` multigrid list correctly reads empty.
- **The grids are "non-choice" to `rehydrate`.** `ChoiceGridQuestionElement` /
  `MultiGridQuestionElement` are **not** `ChoiceQuestionElement` subclasses, so `rehydrate` takes the
  "everything else" branch for them: their positional list / list-of-lists arrives as
  `submitted_values` (not `selected_ids`), which is exactly what `render_choice_grid` /
  `render_multigrid` consume to emit `checked`. (If a reader wrongly assumed grids were "choice
  types," `submitted_values` would be `None` and nothing would render checked — hence stating it.)

### How each of the five reconstructs its answered state server-side

**The two grids have no student-facing JS at all.** They are pure server-rendered inputs:

- `ChoiceGridQuestionElement` (Matrix): `build_answer` returns a **positional list**, one entry per
  row, each an int col-pk or `""` (`courses/models.py`); `mark()` compares to
  `row.correct_column_id`. Rendered by `render_choice_grid` / `_grid_row_cells`
  (`courses/templatetags/courses_extras.py`) as radios `name="row_<rowpk>" value="<colpk>"`, emitting
  `checked` on the radio whose `c.pk == chosen` from `submitted_values`.
- `MultiGridQuestionElement` (Multi-select grid): `build_answer` returns a **list-of-lists** (per
  row, sorted chosen col-pks); `mark()` compares each row's set to `row.correct_columns`. Rendered
  by `render_multigrid` / `_multigrid_row_cells` as checkboxes, `checked` for each `c.pk in
  chosen_set`.

`choicegrid.js` / `multigrid.js` target `[data-choicegrid-editor]` / `[data-multigrid-editor]` —
authoring templates only, never the student element template. So for the grids the restored answer
is 100% in the server HTML; there is nothing for a widget to reconcile.

**The three drag types keep a native `<select name="slot">` as the source of truth**, one per
gap/row/zone, built by `courses/dnd.py` (`render_selects` / `render_match_rows` /
`render_zone_selects`). `build_answer` is `post.getlist("slot")` for all three; `mark()` delegates
to `dnd.mark_slots`. The answered render pre-selects the matching `<option selected>` from
`submitted_values` (`dnd.py::_render_select`). The `dnd.js` enhancement **re-arms itself from those
select values on boot**: `buildInlineSlots` seeds each visible drop-slot's text from `sel.value`
(drag-words, match-pairs), and the image overlay's `paint()` reads `sel.value` on boot to fill each
absolute-positioned target (drag-to-image). So a server-rendered pre-filled `<select>` makes the
widget paint the restored answer with no client blob.

**Positional-alignment invariant (verify, don't assume).** Correct drag restore requires the stored
`slot` list to stay **positionally aligned** to the widget's selects — one entry per slot, with a
placeholder for an unfilled slot — so `_render_select` pre-selects the right option at the right
position. A **partially-answered** drag answer is the case this can break: whether
`getlist("slot")` (and its `answer_to_json` round-trip) emits `""` for an empty select — keeping
later slots aligned — or **omits** it — shifting every later slot onto the wrong target — is the one
thing the implementation must **confirm against source**, pinned by a partial-answer restore test
(Testing).

**The grids are NOT immune to positional fragility** (a round-2 claim to the contrary was *wrong* and
is corrected here — verified against `render_choice_grid`/`render_multigrid` and the grids'
`build_answer`). Their `name="row_<rowpk>"` inputs key only the *live-POST → row* mapping; the
**stored blob is a bare positional list with no row-pk**, consumed positionally on restore (`sv[i]`
over `enumerate(el.rows.all())`), exactly as the drag render is. `build_answer` emits one entry per
row (with `""` for an unanswered row), so a *partial* grid answer stays aligned — but a row
**deleted or reordered** between save and restore shifts every later row's stored answer onto the
wrong statement. Worse than the grid column-pk case (which degrades to *unfilled*), a row-structure
change is a **silent cross-row misfill**. Grids therefore get the **same** treatment as drag: a
row-edit alignment/degradation test (Testing).

**Robustness to author edits differs and matters (see Error handling):** the grids key on **column
pk** (a deleted column → stale pk → renders unfilled), the drag types key on **token text**
(normalize-aware) which survives more edits.

## Architecture / the change

There is almost no new production code — the slice is a flag flip plus verification. The structure
below is ordered by the verify-first discipline.

### C1. Falsify the deferral premise (the gating first task)

Before flipping the flag as a feature, prove the hypothesis is true **per type**, and prove it is the
flag that does the work.

- Write a view-level restore test for **each of the five** (seed the str-keyed
  `UnitProgress.element_state`, GET `lesson_unit`, assert the answered state renders — a `checked`
  radio/checkbox for the grids, an `<option selected>` for the drag types). Structure these as the
  parametrized `IN_SCOPE` restore tests (Testing), so the same tests supply the per-type evidence.
  **Assert on the *specific* option, not bare `selected`.** A native `<select>` always has *some*
  option selected (the blank/placeholder default when nothing is chosen), so "no `<option selected>`"
  is not a valid RED signal. Pin it by value: **GREEN** asserts `selected` on the *chosen value's*
  option; **RED / empty slot** asserts `selected` sits on the *blank/placeholder* option (equivalently,
  is absent from every non-default option). The grids' `checked` on radios/checkboxes has no such
  ambiguity (an unchecked cell simply carries no `checked`).
- **Capture all five RED before any flip.** With `RESTORABLE_IN_LESSON = False` (the current tree —
  all five still deferred), run the whole parametrized set in **one** pass: every one must be **RED**
  (renders un-restored). *Then* apply C2's single collective flip and re-run: every one must turn
  **GREEN.** Because the RED evidence is captured on the current all-deferred tree, **no per-type
  toggling is needed** — each type's red-then-green falls out of the same two runs (one before, one
  after the one flip). This proves the flag is the sole gate for *each distinct payload shape* (grid
  positional list, multigrid list-of-lists, drag/match/image `slot` list). C2 is the documented
  end-state, not a per-type toggle.
- **Go/no-go gate (read from those same two runs).** **Every one of the five must individually go
  red→green, or be carved to the Fallback — that is the real bar.** The two grids are different
  payloads (positional list vs list-of-lists) and the three drag types use *distinct server render
  functions* (`render_selects` / `render_match_rows` / `render_zone_selects`), so **no type vouches
  for another.** As a **minimum-confidence sanity check** before reading the rest, *expect* both grid
  shapes and one drag type among the greens — but this is **not** a blocking gate (the authoritative
  ship rule is Fallback → Ship criteria, under which a one-grid / zero-drag ship is valid). Any type
  still RED after the flip (or whose C4 e2e later fails) routes to the Fallback and is never assumed to
  have passed.
- **Capture the evidence** where a reviewer can find it: paste the RED (flag off) and GREEN (flag on)
  run outputs into the falsification commit message **and** the PR body, so "red-then-green" is a
  discoverable artifact, not a claim.
- **`DragToImage` caveat:** its *view-level* test can only assert the server-rendered `<option
  selected>` — a Django test client cannot observe the absolute-positioned overlay. So its view test
  proves the **server half only**; the overlay re-arm guarantee rests entirely on the mandatory e2e
  (C4). Reviewers should weight that e2e accordingly.
- **Precondition — confirm drag placeholder retention at C1 (shared, not per-type).** Before flipping
  any drag type, **source-confirm** that `check_answer`'s save leg keeps a positional placeholder for
  each empty slot — i.e. `build_answer` (`getlist("slot")`) + `answer_to_json` do **not** drop empty
  selects (Save-side alignment test, Testing). This is shared `dnd.py` behavior across all three drag
  types, so it is a **gating precondition, not a per-type check**: if placeholders are *not* retained,
  do **not** flip the drag types — the fix is a production edit, hence out of this flag-flip slice
  (see Fallback).
- **Precondition — confirm the grid render bounds guard at C1.** The grids-only *no-500* floor rests
  on `render_choice_grid` / `render_multigrid` consuming the stored list as `sv[i] if i < len(sv)
  else ""`. **Source-confirm** that guard exists (parallel to the drag placeholder precondition):
  because `obj.render()` runs **outside** the fail-open `try/except` (see Error handling), a stored
  list shorter than the current row count (a row *added* after save) would otherwise `IndexError` at
  render — a real 500. The Row-structure degradation test (Testing) pins it.
- **If any of the five cannot be made to pass by the flag flip alone**, the "trivial flip" hypothesis
  is false for that family — stop and route that type to the Fallback rather than inventing mechanism
  to force it.

**What must go green to ship.** **At least one grid** red→green is the minimum to ship anything (a
grids-only slice is valid — see Fallback); both grid shapes green is the go/no-go *confidence target*,
not a joint requirement. The two grids are **independent payloads**, so — like every other type — **one
passing grid ships and a failing grid is carved**; they are not all-or-nothing. The "one drag type"
part of the floor applies **only when a drag type is in scope** after the placeholder precondition. If
**neither grid** goes red→green, the premise is falsified and **nothing ships**. Every type's evidence
comes from the same before/after pair; any individual type that stays red is carved out (Fallback),
never shipped on assumption.

### C2. Enable — flip the flag on the five models

Set `RESTORABLE_IN_LESSON = True` on `ChoiceGridQuestionElement`, `MultiGridQuestionElement`,
`MatchPairQuestionElement`, `DragToImageQuestionElement`, `DragFillBlankQuestionElement`. This
single change per model:

- **Save:** `check_answer` now persists `{"answer": answer_to_json(build_answer(POST))}` for these
  types on check (and deletes on empty). Each type's `build_answer` output is already JSON-native
  (list of strings / ints / `""` / nested lists) and lossless through `answer_to_json`.
- **Restore:** `render_element`'s restore branch now rehydrates + re-marks + renders them filled on
  a full-page render, exactly as for the five simple types.

No other production edit is required **if C1 held**.

**The collective flip is for evidence capture — not necessarily the committed end state.** The
end-to-end sequence is: (1) flip all five to `True`; (2) run the per-type view tests + C4 e2es and
observe which pass; (3) **revert `RESTORABLE_IN_LESSON = False`** for every carved type — any that
stayed red at C1, failed its C4 e2e, or tripped a precondition (see Fallback); (4) finalize the
`IN_SCOPE` / `DEFERRED` test membership to match the surviving set. So "single flip" means one flip
*to capture the red→green evidence*, never a guarantee that all five ship — an implementer must not
read it as the final committed state.

### C3. UX — parity with slice 3 (confirmed)

A restored grid/drag answer renders **filled, still editable, re-submittable** — identical to the
five simple types today, with no locked state invented and no template changes. (The templates gate
`disabled` on `quiz_submitted or locked`, both false in lesson restore, so the answer stays editable
for another attempt.) `question.js` — the generic question-**form** boot script (loaded for every
question form, grids included; it is *not* a per-type widget like `choicegrid.js`, so "grids have no
student JS" refers to the absence of a grid widget, not of the shared form script) — hides the Check
button on load for any question whose DOM already shows `.question__verdict.is-correct`. So a
correctly-restored grid hides its Check button **iff** that grid's lesson template renders the
verdict class — tying this directly to the per-type verdict observation below.

**Verdict display is verification-gated, not assumed.** Restore passes `mark_result` exactly as a
live no-JS check does, so each type shows a verdict *to the same extent its own lesson template
already renders one on a live check*. This is deliberately **not asserted as fact** for the
grid/drag types: there is a known quiz-vs-lesson consumption divergence
(`[[quiz-vs-lesson-consumption-divergence]]` — the quiz page and the lesson page render the same
element differently), and the Background proof ("quiz results already round-trips all five") only
proves the *quiz* render, not the *lesson* one. So the per-type restore tests (Testing) must
**observe** what each lesson template actually renders. If a type's lesson template shows no verdict
block, that is acceptable — the refilled answer is the primary goal — and recorded; it is **not**
grounds to add a template change under this slice, which would break the no-template-edits invariant.

### C4. Prove the drag widgets re-arm — real-browser e2e (the crux)

A Django test client sees the server-rendered `<select>` but **cannot** observe whether `dnd.js`
painted its chips/overlay. Since the deferral premise was specifically about the JS widget, the
slice must drive a **real browser**:

- **Mandatory — overlay path (`DragToImageQuestionElement`):** answer it in a real lesson, reload,
  and assert the **visible overlay targets show the restored answer** — this template-independent
  signal is the **sole hard anchor** for the correct case (the absolute-positioned overlay re-arm is
  the riskiest path in the slice). Exercise **both** outcomes: correct and **incorrect** (the wrong
  answer still painted in the overlay, widget still editable — the only browser check of C3's "still
  editable, re-submittable" claim). **Neither "Check hidden" nor "verdict shown" is a hard anchor** —
  they are the *same* contingent signal: `question.js` does **not** re-mark; its boot pass only hides
  Check when `.question__verdict.is-correct` is already in the server-rendered DOM (verified in
  `question.js`), so both appear only if this type's lesson template renders the verdict class (per
  C3). Assert either **only if** that verdict was observed; **never fail the e2e on their absence**,
  or a correctly-restored (highest-value) type is spuriously Fallback-routed.
- **Mandatory — inline path (one of `DragFillBlank` / `MatchPair`):** the inline widgets re-arm
  through `buildInlineSlots`, a **distinct code path** from the overlay's `paint()`, and a view test
  observes neither. So at least one inline drag e2e is **also mandatory** — reload and assert the
  visible drop-slots show the restored tokens — otherwise two of the three drag types ship with zero
  browser evidence their widget re-arms, exactly the risk this slice exists to retire. This e2e
  vouches for the **shared `buildInlineSlots` JS path** for *both* inline types **only if** a
  source-confirm shows `buildInlineSlots` has **no per-inline-type branch** and both inline templates
  present the **same slot DOM shape** it keys on — that confirm is a precondition of the vouch, since a
  passing e2e for one type only proves *that* type's DOM re-arms. Absent it (or if the two DOMs
  differ), the sibling inline type gets its **own** mandatory e2e rather than riding the vouch. The
  un-chosen inline type's distinct *server render* (`render_selects` vs `render_match_rows`) is
  separately covered by its C1 view test. Same rule as the overlay case: visible tokens are the hard
  anchor; Check/verdict asserted only if observed.

**These mandates are conditional on the type shipping.** An e2e is required only for a drag type that
survives C1 and is actually being enabled: if `DragToImage` is carved at C1 (e.g. its view test shows
no server-side `<option selected>` under the lesson divergence), the overlay e2e is **moot** and its
absence does not block a grids+inline ship. Choose the inline type freely — both share
`buildInlineSlots` and both server renders are already covered by their C1 view tests, so there is no
"least-covered" tie-break; pick either (or the one with the more complex widget DOM, to exercise the
harder re-arm). **A failed inline e2e disproves the shared
`buildInlineSlots` vouch**, so the sibling inline type may **not** ship on that vouch — it must get its
own passing e2e or be carved too.

Drive the actual gesture and reload (never `page.evaluate` to fake state — per
`[[e2e-must-drive-real-ui]]`). These e2es are what actually falsify *"the JS widget cannot be
re-armed."* If one fails, its type (and, for the inline vouch, its sibling) routes to the Fallback.

## Data flow

Unchanged in shape from slice 3 (this slice only widens the type set):

- **Answering (JS or no-JS lesson):** POST to `check_answer` → `build_answer` + `mark` → (now
  in-scope) `save_element_state(user, unit, pk, {"answer": …})`. JS gets a fragment; no-JS gets a
  full re-render where the just-answered element shows via the global kwargs and every other
  answered element via restore.
- **Reload / fresh GET:** `build_lesson_context` loads the fail-open-filtered `element_state`; each
  in-scope element with an `"answer"` blob is rehydrated and **re-marked server-side**, then rendered
  filled (with a verdict *iff* its lesson template renders one — C3); `dnd.js` (drag types) paints the
  widget from the server-rendered selects; `question.js` then hides Check on any question whose
  server-rendered DOM already shows the correct-verdict class (it **reads** that class, it does not
  re-mark).
- **Clearing / Start fresh:** empty re-check deletes the key; `progress_reset` wipes
  `element_state` wholesale. Both already work; both pinned by tests.

## Error handling

- **Restore-side fail-open (existing, hardened by PR #158):** the restore **data-prep** (blob access,
  `rehydrate`, `answer_from_json`, `mark`) is wrapped in `try/except` that now `logger.exception`s and
  falls through to the un-restored render. **`obj.render()` runs OUTSIDE that `try/except`** (once,
  after the block — the slice-3 design pins this). So the try/except's "a bad blob can never 500"
  guarantee covers **data-prep** errors only; a **render-time** error is a *separate* protection —
  it is prevented not by the try/except but by the render functions' own guards (e.g. the grid
  `sv[i] if i < len(sv)` bounds guard, source-confirmed at C1). The two "→ 500" falsify lines in
  Testing target *those render guards*, not the try/except: deleting a render bounds guard **does**
  500 (which is why it must be confirmed present); deleting the try/except 500s on a *bad blob*.
  Both statements hold once the boundary is pinned. This slice adds no new *marking* surface:
  restore's `obj.mark(answer_from_json(obj, stored))` is the same `mark()` `check_answer` already
  calls live, so if the live check can't error for a type/answer, neither can restore's mark.
- **Stale references self-heal or misfill — three modes, none unique to the grids.** (1) *Grid column*
  delete: a stored column-pk whose column was deleted fails to match on re-mark, so `render_choice_grid`
  / `render_multigrid` emit no `checked` for it — the cell renders **unfilled, never errors**
  (`build_answer` / `mark` validate against the current valid-pk sets). (2) *Grid row* delete/reorder:
  the stored blob is a **bare positional list** consumed by row index (`sv[i]`), so a removed/reordered
  row shifts every later row's answer — a **silent cross-row misfill** (200, no crash, but the wrong
  statement shows the answer). (3) *Drag* structural edit: `build_answer` is `post.getlist("slot")`, so
  removing a zone/gap/match row changes slot count/identity and a stored `slot` list can mismatch.
  Modes (1) and (3) degrade to *unfilled/mismatch, 200, no 500*; mode (2) is silent-wrong but
  **self-limiting** — the verdict is re-derived on load (never stored), so a misfilled cell simply marks
  wrong, never crashes, and the next student check overwrites it. **Each mode gets its own
  degradation/alignment test** (grid column-pk delete; grid row delete/reorder; drag zone/gap removal).
- **Empty answers.** `answer_is_empty` recurses, so an all-`""` grid or `[[],[]]` multigrid reads
  empty → the key is deleted → next reload shows the question blank. Pinned by a test.
- **Deferred-on-both-sides invariant preserved.** The `RESTORABLE_IN_LESSON` gate is consulted on
  **both** save and restore, so no type can ever be enabled on one side only.

## Testing

Falsification-first (per `[[falsify-tests-not-run-them]]`): every guard below names what to delete
to see RED. Extend `courses/tests/test_question_restore.py`, which already has the sibling structure
and an `IN_SCOPE` / `DEFERRED` split — **move the five types from `DEFERRED` to `IN_SCOPE`** (that
alone flips several existing parametrized assertions, e.g. `test_deferred_types_are_not_restorable`
must be updated as the types are enabled).

**When `DEFERRED` empties** (all five enabled, none carved to the Fallback), a test parametrized over
it passes **vacuously** by iterating nothing — the exact trap `[[falsify-tests-not-run-them]]` warns
against. So `test_deferred_types_are_not_restorable` must be **deleted** in that case — its intent is
then carried (in reduced form) by `test_base_default_is_false` — a **pre-existing** test in
`courses/tests/test_question_restore.py`, not new to this slice (`QuestionElement.RESTORABLE_IN_LESSON`
still defaults `False`) — or, if any type lands in the Fallback, kept parametrized over **only** that
still-deferred sentinel. Note the reduced guarantee: once all five subclasses set `True`, no shipping
type inherits the base default, so `test_base_default_is_false` guards only the **base invariant /
future subclasses**, not any currently-shipping type — do not over-read it as still covering the five.
Never leave the parametrized test iterating an empty set; whichever assertion survives must be
falsification-shown still able to go RED.

**C1 falsification (the premise proof, run first):**
- For **all five** types: seed the str-keyed `element_state` DB row, GET `lesson_unit` **through the
  view** (so `build_lesson_context` re-keys to int — never `obj.render` with a str key), assert the
  answered state renders. Run the whole set **RED on the current all-deferred tree, then GREEN after
  C2's single collective flip** (one run each side, no per-type toggling). This pair of runs is a
  **confidence target** (both grid shapes + ≥1 drag type going red→green sanity-checks the mechanism),
  **not** a hard gate — the authoritative rule for what actually ships is **Fallback → Ship criteria**
  (a one-grid, zero-drag ship is valid). Any type still RED after the flip, or later carved by its C4
  e2e, is dropped. **Paste both run outputs (flag off / flag on) into the falsification commit message
  and the PR body, annotated with the final per-type carve outcomes** — a type can be view-GREEN yet
  carved by a failing e2e, so the annotation lets a reviewer reconcile the green list against the
  actually-shipped set.

**Save (per type):**
- Checking each of the five in a lesson stores `{"answer": <json>}` under `str(element.pk)`.
  *Falsify:* the `RESTORABLE_IN_LESSON` save gate → no blob.
- Envelope/shape correctness per family: grid → positional list with `""` / list-of-lists; drag →
  list of `slot` strings. *Falsify:* store the raw answer without the `{"answer": …}` envelope →
  read-side filter drops it → the restore test goes blank.
- Empty answer (all-`""` grid / `[[],[]]` / empty slots) after a prior stored answer **deletes** the
  key. *Falsify:* skip the `answer_is_empty` branch → stale key remains.
- The no-JS `check_answer` path also persists for these types. *Falsify:* gate the save behind
  `_wants_fragment`.
- **Save-side positional alignment (drag).** Answer only *some* slots of a drag question through
  `check_answer` and assert the **stored** blob is positionally aligned — a placeholder retained for
  each empty slot, not a short/compacted list. This pins the invariant's **real** (save-leg) failure
  mode: the restore-leg partial test (below) seeds an already-aligned blob and so cannot catch a
  `build_answer`/`answer_to_json` that drops empties. *Falsify:* if the save omits empty slots, the
  stored list is shorter than the slot count → RED. **Shared POST-side leg, but confirm all three
  renders.** The placeholder *retention on save* lives in shared `dnd.py` (`getlist("slot")` /
  `answer_to_json`), so **one** representative drag type exercises that POST-side leg. **But** whether
  an empty slot contributes a blank at all depends on each *per-type render* (`render_selects` /
  `render_match_rows` / `render_zone_selects`) emitting a submittable blank/default `<option>` for an
  unfilled slot — a render that omits it would drop empties and silently misfill partial answers. So
  the C1 placeholder precondition must **source-confirm all three renders** emit that blank option;
  only then does the single representative save-side test generalize. (The restore-leg test below is
  per shipping drag type regardless.)

**Restore (per type, view-level):**
- Seed each type's `element_state` blob, GET `lesson_unit`, assert the answered state renders: grids
  → `checked` on the chosen cells; drag types → `<option selected>` on the chosen slots. Cover **all
  five**. Assert the verdict **to the extent the type's lesson template renders one** — observe it
  per type rather than assuming it (C3); a type whose lesson template shows no verdict block still
  passes on the refill alone. *Falsify:* remove the slice-3 restore block in `render_element`
(Background / C2) → inputs render blank.
- **Stale-pk degradation (grids):** seed a grid blob referencing a column pk that no longer exists,
  restore via the view, assert the lesson returns 200 and that cell renders unfilled (no `checked`,
  no 500). *Falsify:* (guards existing behavior; a change that indexed a stale pk unguarded would
  RED/500.)
- **Row-structure degradation (grids) — bounded, not crashing, and NOT misfill-free.** The stored
  blob is positional with no row-pk, so an author changing rows between save and restore degrades
  **acceptably and self-limitingly** (Error handling mode 2); the test asserts the *bounded* outcome,
  **never** "no misfill" (which the mechanism cannot provide). Two operations:
  - *Fewer stored entries than current rows* (a row **added** after save, or a hand-forged short blob):
    restore via the view, assert **200, no 500** — the render's `sv[i] if i < len(sv) else ""` bounds
    guard leaves the extra rows blank. *Falsify:* delete the `i < len(sv)` guard → `IndexError`/500.
  - *A middle row deleted or reordered* (stored list now longer than / permuted vs the rows): restore,
    assert **200, no 500** and a well-formed render; a later row **may** show a neighbour's stored
    answer — that misfill is **accepted** (the verdict is re-derived, so it marks wrong and the next
    student check overwrites it). *Falsify:* (guards the 200/no-crash floor.)
- **Structural-edit degradation (drag types):** seed a drag blob whose `slot` list references a
  since-removed zone/gap/row, restore via the view, assert 200 + the affected slot un-armed + no 500.
  *Falsify:* (guards existing behavior; an unguarded stale-slot index would RED/500.)
- **Partial-answer drag alignment (restore leg).** Seed an *already-aligned* drag blob with only
  *some* slots filled (placeholders for the empty ones), restore via the view, and assert each filled
  slot re-arms at its **correct position** (the right `<option selected>` on the right select) while
  empty slots stay empty. This is the restore-leg counterpart to the Save-side alignment test above:
  together they pin the full round-trip — the save test proves the stored list keeps placeholders, this
  proves the restore consumes them positionally. **Per shipping drag type:** unlike the shared save-side
  test, the restore-leg consumption runs through each type's *distinct* render (`render_selects` /
  `render_match_rows` / `render_zone_selects`, all feeding `_render_select`), so this test is written
  **once per shipping drag type**. *Falsify:* seed a mid-list gap and assert the trailing slot's option
  is the correct one, not the shifted neighbour.
- **Deferred→enabled parity:** the existing `test_deferred_hand_forged_blob_does_not_restore` /
  `test_deferred_type_persists_nothing` for these types must be **retargeted** to now-enabled
  behavior (they restore / persist) — and a still-genuinely-deferred sentinel kept only if any type
  lands in the Fallback. *Falsify:* the in-scope gate.
- Corrupt/non-digestible blob → 200 + un-restored + logged (the PR #158 fail-open). *Falsify:*
  remove the `try/except` → GET 500s.
- Editor-preview exclusion still holds (renders `mode="lesson"` with no `element_state` → blank).
  *Falsify:* a test asserting restore needs a non-empty `element_state`.

**Reset:**
- `progress_reset` clears an in-scope grid/drag blob. *(guards existing wholesale wipe.)*

**Widget re-arm — e2e, real UI (C4, the crux):**
- **Mandatory (overlay path):** answer a `DragToImageQuestionElement` in a real lesson, reload,
  assert the visible overlay targets show the restored answer — the **sole hard anchor** for the
  correct case. Cover **both** correct and incorrect restores. For the incorrect case, prove
  editability **by gesture, not by attribute**: after reload perform a **real** drag/tap that changes
  a slot and assert the new value paints (observing a non-`disabled` control is too weak — it is the
  only browser check of C3's editable/re-submittable claim). Assert Check-hidden and verdict-shown
  **only if** that lesson template was observed to render the verdict class (C3); do **not** fail on
  their absence. *Falsify:* set that type's `RESTORABLE_IN_LESSON = False` → the widget is empty after
  reload.
- **Mandatory (inline path) — only if an inline drag type ships:** when any inline drag type is being
  enabled, one inline e2e (`DragFillBlank` / `MatchPair`) is required — its re-arm runs through
  `buildInlineSlots`, a code path the overlay e2e does not exercise; reload and assert the visible
  drop-slots show the restored tokens. Moot in a grids-only ship where both inline types were carved
  (per C4's shipping condition).
- Drive the actual drag/tap gesture and a real reload — never `page.evaluate`.

**Regression breadth:** full non-e2e suite at every red-window boundary (a red window blinds
per-task reviewers — `[[student-practice-state-status]]`), plus the focused question/quiz/state files
and the **new widget-restore e2e file** — `courses/tests/test_question_restore_e2e.py` (marked
`@pytest.mark.e2e`, holding the overlay + inline drag re-arm e2es), the sibling of the view-level
`courses/tests/test_question_restore.py`. `manage.py check`, `ruff check`, `ruff format --check`, `makemigrations --check`
(expected: **no new migration**) all clean.

## Fallback

The Fallback triggers on **any** observed RED or failed precondition — **C1** (view-level restore),
the **C4 e2e** (widget re-arm), the **Save-side alignment test** (drag placeholder retention), the
**drag placeholder-render precondition** (all three renders emit a submittable blank option), or the
**grid bounds-guard precondition** (`sv[i]` guarded by `i < len(sv)`). If a check shows a type
genuinely does **not** round-trip from the flag flip alone (e.g. the image-overlay widget cannot
re-arm from server-rendered selects), that type is **carved back out of this slice** — left
`RESTORABLE_IN_LESSON = False`, with the observed failure documented — and the slice ships the types
that do.

**Special case — a shared save-side defect carves all three drag types at once.** If the Save-side
alignment test goes RED because `dnd.py`'s `getlist("slot")` / `answer_to_json` **drops** empty slots,
that defect is **shared** across all three drag types, not per-type, and fixing it is a **production
edit** — which this flag-flip slice explicitly excludes. In that case: carve **all three** drag types
out (leave them deferred), ship the two grids, and spin the placeholder fix into its **own follow-up
spec**. Do **not** smuggle the production edit into this slice to keep the drag types — that would
violate the "no other production edit" invariant the whole slice rests on. (This is why C1 makes the
placeholder-retention source-check a gating precondition: the decision should be reached *before* the
flip, not discovered after.)

**Special case — an absent grid render bounds guard carves the grids.** If the C1 source-confirm finds
`render_choice_grid` / `render_multigrid` do **not** guard `sv[i]` with `i < len(sv)` — so a row added
after save would 500 at render, since `obj.render()` runs *outside* the fail-open `try/except` —
adding the guard is a **production edit** this flag-flip slice excludes. Mirror the drag case exactly:
do **not** flip the grids, spin the bounds-guard fix into its **own follow-up spec**, and ship only
the drag types that pass — or, if the grids were the only in-scope survivors, **ship nothing**. The
no-production-edit invariant stays intact.

A client-rehydrate mechanism for a stubborn widget is likewise **not** forced in under this slice; it
becomes its own follow-up with its own spec. The verify-first structure exists precisely so every
carve-out is driven by observed RED, not by schedule pressure.

**Ship criteria (explicit, so no case is undefined). The two grids are independent, per-type
carveable — they are a joint *confidence target*, never a joint ship requirement:**
- **Both grids red→green, all three drag types carved** (e.g. the shared save-side placeholder defect)
  → ship a **grids-only** slice; the "one drag type" floor does not apply because no drag type is in
  scope. The drag work becomes its own follow-up.
- **Both grids + ≥1 drag type red→green** (that drag type also passing its C4 e2e) → ship those; any
  other drag type that stayed red or failed its e2e is carved.
- **Exactly one grid red→green** (the other stays red) → the premise still holds; **ship the passing
  grid, carve the failing one** like any other type. First investigate *why* one grid shape failed
  when the other passed — it is a surprising, payload-shape-specific result and may be a fixable bug —
  but a single passing grid is a valid ship, not a blocker.
- **Both grids carved by the bounds-guard *precondition*** (not by a C1 RED — the flag-flip premise
  actually holds for them, but the missing `sv[i]` guard makes shipping them a production edit), **and
  ≥1 drag type passes** → ship those drag types; the grids' bounds-guard fix becomes its own follow-up
  (see the grid-bounds-guard special case). If in this case **no** type at all survives, nothing ships.
- **Both grids flipped and genuinely stayed RED at C1** (a real restore failure, *not* a
  precondition carve) → the flag-flip premise is falsified for the lowest-risk types, so **nothing
  ships** and the slice is abandoned (the deferral was right after all), documented as such.
- A drag type may ship **only** if it clears C1 (view), the C4 e2e (widget) — satisfied for a vouched
  inline sibling **by the shared `buildInlineSlots` vouch, or by its own e2e** — and the save-side
  placeholder precondition.
- **When a type is carved, its tests go with it.** A carved drag type's widget/alignment tests
  (save-side, partial-restore, structural-degradation, C4 e2e) are **removed or converted to
  deferred-sentinel assertions** matching its still-`False` flag, so the committed suite is green and
  the carve is reflected in the tests — a RED save-side alignment test is never committed.
- A grid may ship once it clears C1. The **row-structure degradation test is not a carve gate**: an
  observed row-edit misfill is *accepted* (bounded, self-limiting), so "clears" it means the test
  **passes by documenting the bounded outcome (200, no crash)**, never "the grid exhibits no misfill"
  (impossible by design). A grid is carved only if C1 itself stays RED.

## Isolation note (execution)

A concurrent session collided with this work earlier in the same working tree (it switched/deleted
branches underneath an in-flight PR). This slice is being specced and must be executed in an
**isolated git worktree** with its **own `DATABASE_URL`** per `[[test-db-contention-across-worktrees]]`
and `[[verify-master-never-infer-it]]` — never assume the main checkout is untouched; verify with
`git status` before any controller-side edit.
