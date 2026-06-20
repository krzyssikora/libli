# Phase 2d-i — Drag-and-drop substrate + drag-fill-blanks & match-pairs — Design

**Status:** spec (brainstormed 2026-06-20)
**Slice:** Phase 2d-i — the first slice of the Phase 2d split. Builds a **shared drag-and-drop substrate** (progressive-enhancement model + a uniform `{target → token}` answer payload + per-target marking) and proves it with the **two "tokens → slots" question types: drag-fill-blanks and match-pairs**. Both plug into the existing 2a/2b/2c marking & quiz machinery with **no new views** — they are new `QuestionElement` subclasses that the existing `check_answer` (lesson, formative) and `quiz_answer`/`quiz_finish` (quiz, persisted) paths dispatch to generically.
**Predecessors:** 2a (the `QuestionElement` abstract base, `MarkResult`, `mark()`, `build_answer()`, the answer→submit→feedback round-trip with JS-fragment + no-JS transports, `render()` per-type dispatch, `REVEAL_TEMPLATE`, the no-leak/IDOR/CSRF invariants). 2b (the `{{a|b}}` fill-blank stem parser `fillblank.py`, per-gap fractional marking, `normalize_text`). 2c (the `marking_mode`/`max_attempts`/`max_marks` fields already on `QuestionElement`; the quiz persistence model `QuizSubmission`/`QuestionResponse`/`Attempt`; the withhold-until-exhausted/correct feedback state machine; the quiz vs lesson render `mode`). All file references are to the post-2c (PR #22) tree.

---

## 1. Purpose & scope

### 1.1 Phase 2d decomposition (context)

Phase 2d (the "rich interactive + review types" bucket from the 2c spec §1.1) is **sub-split** into three focused slices, each its own spec → plan → build cycle:

- **2d-i — DnD substrate + drag-fill-blanks + match-pairs (this slice):** the shared progressive-enhancement substrate, proven by the two types whose answer is "assign tokens to slots."
- **2d-ii — drag-to-image:** the third DnD type (drag labels onto author-defined zones over an image), built on the now-proven substrate; adds the image + drop-zone authoring UI (the heaviest single authoring piece).
- **2d-iii — extended-response + the `[R]` human-review path:** long free text marked by required/forbidden keywords, plus the first `[R]`-native type and its student-facing "awaiting review" states. (The teacher review *queue* remains Phase 3 — it needs groups.)

This split replaces the single "2d" bullet in the 2c spec; "2e — Results & metrics" is unchanged and still follows.

### 1.2 The substrate (locked in brainstorming)

Three of the four Phase 2d types are pointer drag-and-drop, and the codebase requires **no-JS parity** (every action works without JavaScript). The unifying decision:

- **`<select>`-per-target is the base; drag is decoration.** Each drop target (a gap in drag-fill, a left item in match-pairs) renders as a native `<select>` whose options are the available tokens. That `<select>` is **simultaneously** the no-JS fallback, the keyboard/screen-reader path, and the source of truth. JS enhancement layers pointer drag-and-drop *on top*: dragging a token chip into a target simply **sets that target's `<select>` value**. The form always submits the `<select>` values, so the server receives an identical payload whether the student dragged or used the dropdown — it cannot tell which, and `build_answer`/`mark` never branch on transport.
- **Uniform answer payload:** an ordered list parallel to the targets, each entry the chosen token's **pool index** (or empty). The substrate's `{target → token}` shape. (Pool *index*, not free text, so the value is a small integer that can't carry markup and is trivial to validate against the pool.)
- **Reusable tokens:** a token may be assigned to more than one target; the pool never depletes; each `<select>` independently lists every pool token. This keeps the JS and no-JS experiences identical (independent selects) and is the simplest substrate.
- **Distractors:** the pool may contain extra tokens that are the correct answer for no target. The pool is rendered in a **stable, non-revealing order** (a deterministic shuffle — e.g. sorted by normalized text, or a fixed seed) so the option order is never a giveaway and never reflows between submissions. Marking is order-independent, so pool order never affects correctness.

### 1.3 Marking (locked in brainstorming)

Both types mark **per target**, identically to fill-blank:

- Each target has **exactly one expected token**. A target is correct iff its assigned token equals the expected token.
- `fraction = n_correct_targets / n_targets` (partial credit). `correct = (n_correct == n and n > 0)`.
- Only the auto-markable `[A]` path is exercised here; `[N]`/`[R]` modes already exist on the base from 2c and behave for these types exactly as for every other type (recorded, no score / awaiting-review) — **no `[R]`-native UI in this slice**.

### 1.4 What this slice IS / IS NOT

**Is:** two new `QuestionElement` subclasses + their sub-row models, forms, templates, the shared DnD JS module + its no-JS select base, per-type reveal partials, marking, i18n, and tests. Works in **both** lesson units (formative, ephemeral, always-reveal) and quiz units (persisted, attempt-capped, withhold-gated) by reusing the existing dispatch.

**Is NOT (deferred):**
- **No drag-to-image** (2d-ii) and **no extended-response / `[R]`-native type** (2d-iii).
- **No new views, URLs, or persistence model.** `QuizSubmission`/`QuestionResponse`/`Attempt` and the `check_answer`/`quiz_answer`/`quiz_finish` views are reused unchanged; the `latest_answer` JSON simply stores this slice's payload shape.
- **No "consume-once" token semantics** (tokens are reusable, §1.2) — the consumed/depleting-pool feel is explicitly rejected because plain-HTML dropdowns can't enforce single-use without JS.
- **No line-drawing match UI** — the two-column select/slot layout is the chosen presentation (line-drawing has no no-JS equivalent).
- **No change to existing types** or to the quiz scoring/withhold machinery.

### 1.5 Non-goals

No new dependency. The drag JS is a small vanilla-JS enhancement (no DnD library), consistent with the existing `fetch` + `X-CSRFToken` transport and the project's bespoke (no-framework) front end. No change to `MarkResult` (still `correct`/`fraction`/`reveal`).

---

## 2. Data model

Two new concrete question types in `courses/models.py`, each a `QuestionElement` subclass (so each inherits `stem`/`explanation`/`marking_mode`/`max_attempts`/`max_marks` and owns its own table → **one migration adding both tables + their sub-row tables**). Each declares `elements = GenericRelation(Element)` (the 1a GFK join-row, as every other element type does) and a `REVEAL_TEMPLATE`.

### 2.1 `DragFillBlankQuestionElement`

```
distractors  TextField(blank=True)   # newline-delimited extra (wrong) tokens
REVEAL_TEMPLATE = "courses/elements/_reveal_dragfill.html"
elements = GenericRelation(Element)
```

- `stem` (inherited) stores the **token-stem** produced by `fillblank.parse()` (the `￿{n}￿`-tokenised form), exactly as fill-blank does — the `{{…}}` parser is reused verbatim.
- Ordered **`DragBlank`** rows (mirror of `Blank`): the parser writes one per `{{token}}` marker, in order.

```
class DragBlank(models.Model):
    question       FK(DragFillBlankQuestionElement, on_delete=CASCADE, related_name="blanks")
    correct_token  CharField(max_length=200)   # plain text + KaTeX delimiters; never sanitised
    order          OrderField(for_fields=["question"], blank=True)
    Meta.ordering = ["order", "pk"]
```

- **Pool** = `[b.correct_token for b in blanks]` + `_lines(distractors)`, de-duplicated by normalized text, then rendered in the stable non-revealing order (§1.2). Each gap's expected token = its `DragBlank.correct_token`.
- Unlike fill-blank, a marker carries **one** token, not a `|`-list of accepted strings (a gap holds one chip). The author form rejects `|` inside a drag-fill marker (§5.1) with a clear message.

### 2.2 `MatchPairQuestionElement`

```
distractors  TextField(blank=True)   # newline-delimited extra (unmatched) right-items
REVEAL_TEMPLATE = "courses/elements/_reveal_matchpair.html"
elements = GenericRelation(Element)
```

```
class MatchPair(models.Model):
    question  FK(MatchPairQuestionElement, on_delete=CASCADE, related_name="pairs")
    left      CharField(max_length=200)   # the fixed target label; plain text + KaTeX
    right     CharField(max_length=200)   # the correct token for this left; plain text + KaTeX
    order     OrderField(for_fields=["question"], blank=True)
    Meta.ordering = ["order", "pk"]
```

- **Targets** = the `pairs`' `left` items, in order. Each target's expected token = its pair's `right`.
- **Pool** = `[p.right for p in pairs]` + `_lines(distractors)`, de-duplicated, stable non-revealing order (§1.2).
- `stem` (inherited) is the optional prompt above the two columns (no markers — plain rich text).

### 2.3 Shared token convention

Token / chip text follows the **MCQ `Choice.text` convention**: plain text + KaTeX delimiters (`\(x^2\)`), **never HTML-sanitised**, `max_length=200`. This keeps math chips first-class (important for this platform) and matches an existing, reviewed precedent.

### 2.4 Persistence (reused, unchanged)

In a quiz, a submission's `QuestionResponse.latest_answer` (and each `Attempt.answer`) stores this slice's payload: the ordered list of chosen pool-index strings, one per target, `""` for an unfilled target (exactly what `build_answer` returns, §3.2). No schema change — the 2c JSONField already accepts any type-specific shape. Resume (`quiz_unit` GET) rehydrates the `<select>` values / chip placements from `latest_answer` via the same `submitted_values` context channel the templates already consume.

---

## 3. The substrate: rendering, transport & marking

### 3.1 Rendering (`render()` per type + a shared partial)

Each type implements `render(...)` (mirroring `ChoiceQuestionElement.render`), passing the **mode** (`lesson`|`quiz`), `action_url`, `feedback_partial`, `quiz_submitted`, `locked`, `attempts_left`, and the repopulation channel. Both per-type templates include one shared partial, **`courses/elements/_dnd_pool.html`**, that renders the chip pool + the drag JS hook; the per-type body differs only in target layout:

- **drag-fill** (`dragfillblankquestion.html`): the token-stem is rendered with a `render_selects(token_stem, pool, chosen)` helper (a sibling of `fillblank.render_inputs`) that splits on the opaque tokens and emits, per gap, a `<select name="slot">` of the pool (plus a styled drop-slot the JS reveals). Text segments are trusted sanitized HTML; only the server-built `<select>`s are inserted (option labels escaped) — same safe-join discipline as `render_inputs`.
- **match-pairs** (`matchpairquestion.html`): a two-column layout — each `left` label beside its `<select name="slot">`/drop-slot.

`name="slot"` is uniform across both, so `build_answer` is `post.getlist("slot")` for both (parallel to fill-blank's `getlist("blank")`).

**Progressive enhancement.** With JS off, the `<select>`s + a normal submit button are a complete, working question. The DnD JS (`static/courses/dnd.js`, loaded by the partial) finds each target's `<select>`, hides it, renders draggable chips + drop-slots, and on drop/keyboard-activate **writes the chosen pool index back into the `<select>` and dispatches `change`** — so the existing submit path (and any existing per-question `fetch`) sees identical form data. The JS is pure decoration: if it throws or never loads, the selects remain.

### 3.2 Marking (`build_answer` + `mark`)

Both types share the **same per-target algorithm** (factored into a small helper, e.g. `mark_slots(expected, pool, chosen_indices)` in a new `courses/dnd.py`, so drag-fill and match-pairs cannot diverge and 2d-ii can reuse it):

- `build_answer(self, post)` → `post.getlist("slot")` — a list of pool-index strings (or `""`), one per target, padded/truncated to exactly `n_targets` (mirrors fill-blank's pad/truncate).
- `mark(self, answer)`:
  - For each target `i`: map `answer[i]` (pool index) → token text via the pool; `got` = that text or `""`; `expected` = target's expected token. `ok = got != "" and normalize_text(got) == normalize_text(expected)`.
  - `n_correct = Σ ok`; `fraction = n_correct / n` (or `0.0` if `n == 0`); `correct = (n_correct == n and n > 0)`.
  - `reveal` = a tuple of per-target `{index, correct, expected}` (drag-fill keyed by gap order; match-pairs by `left`), consumed by the per-type reveal partial.

`fraction` is a `float` (`0.0`–`1.0`); the quiz path's 2c boundary converts to `Decimal` and quantizes (`fraction × max_marks`), unchanged. Foreign/out-of-range indices map to `""` (wrong), never error — the same "drop forged input silently" rule as `ChoiceQuestionElement.build_answer`.

### 3.3 Feedback & the withhold rule (reused)

In a **lesson** (formative) these types use the always-reveal `_question_feedback.html` + their `REVEAL_TEMPLATE`, like every 2a/2b type. In a **quiz**, they obey the 2c withhold state machine unchanged: pre-reveal (wrong, attempts remain) shows only "Incorrect — try again (N left)" with **no** `reveal`/`reveal_template`; reveal (correct, or wrong-on-last-attempt) renders the per-type reveal partial showing each target's expected token. The reveal partials (`_reveal_dragfill.html`, `_reveal_matchpair.html`) are new but follow `_reveal_fillblank.html` exactly (iterate the `reveal` tuple, mark each target correct/incorrect, show the expected token). The no-leak invariant therefore holds **by reusing 2c's reveal-gated context construction** — these types add no new path that could leak.

**Empty-answer guard (quiz path, 2c §3.1 step 3):** "empty" = **every** target unset (all `slot` values `""`). A fully-empty submit is rejected without burning an attempt; a partially-filled submit is a real attempt (consistent with fill-blank, where some-but-not-all blanks filled counts).

---

## 4. Authoring

Two new `ModelForm`s in `courses/element_forms.py`, registered in `FORM_FOR_TYPE` as `"dragfillblankquestion"` and `"matchpairquestion"`, and surfaced in the builder's add-element menu (`builder.py`) alongside the other question types. Both use the existing `_MarkingFieldsMixin` (so `marking_mode`/`max_attempts`/`max_marks` appear, quiz-gated, exactly as 2c wired for fill-blank).

### 4.1 drag-fill-blanks form

- A `stem` textarea using the **`{{token}}` syntax**, parsed by the **reused `fillblank` pipeline**: `sanitize_html(raw)` → `strip_sentinel` → `parse()`. On success, store the token-stem in `stem` and create one `DragBlank(correct_token=…)` per marker, in order.
- Validation (raising the form error, mirroring `FillBlankQuestionElementForm`): at least one marker (`FillBlankError("no blanks")`), no unterminated marker, and — **drag-fill-specific** — **no `|` inside a marker** (a gap has one token, not alternatives): *"Each gap holds one token — use a single answer per {{…}}, not alternatives."*
- A `distractors` textarea (newline-delimited extra tokens), `blank=True`.

### 4.2 match-pairs form

- An **inline formset** of `MatchPair` rows (`left`, `right`, `order`), mirroring how `Choice` rows are authored for MCQ (add/reorder/delete, ≥1 pair required).
- An optional `stem` (plain prompt) and a `distractors` textarea (newline-delimited extra right-items).
- Validation: ≥1 pair; both `left` and `right` non-blank per row.

### 4.3 Editor display

The three marking fields show only for quiz units and hide `max_marks`/`max_attempts` for `[N]`/`[R]` — **inherited verbatim** from the 2c `_MarkingFieldsMixin` behaviour; no new logic.

---

## 5. Invariants, edge cases & testing

### 5.1 Invariants

- **No-JS parity:** with JS disabled, both types are fully answerable via `<select>`s and submit (lesson and quiz). Asserted by no-JS e2e.
- **No-leak (reused):** accepted tokens reach the client only in a revealing state; the quiz withhold path is 2c's, untouched. Regression test on the JS-fragment feedback (pre-reveal contains no expected-token text) **and** the resume render (an answered-not-correct `[A]` gap rehydrates without its expected token), scoped to the answered question's wrapper — same form as 2c §5.1.
- **Server-authoritative marking:** the chosen pool indices are validated server-side against the pool; forged/out-of-range indices score wrong, never error. The client cannot self-report correctness.
- **Transport-agnostic:** dragged vs dropdown submissions are byte-identical to the server (asserted by submitting the same answer both ways and comparing the recorded `Attempt`).

### 5.2 Edge cases (handled explicitly)

- **Distractor-only pool entry never matches** any target (it's the correct token for none).
- **Reusable token** correctly satisfies two targets that share an expected token (independent selects; both can pick it).
- **Partially-filled quiz submit** = a real attempt with partial credit; **all-empty** = rejected without burning an attempt (§3.3).
- **Pool order** is stable across re-renders/resume and never reveals the answer (§1.2); marking is order-independent.
- **Author edits mid-quiz** are governed by the existing 2c §5.2 limitation (stored `fraction` not re-marked against edited tokens; all moot once `submitted`). No new reconciliation here.
- **Marker with `|`** in drag-fill → form validation error (§4.1), not a silently-split multi-answer gap.
- **KaTeX in a token** renders in chip, select option, and reveal (plain text + delimiters; never sanitised — §2.3).

### 5.3 i18n

All new strings (validation messages, "Drag a token here" / drop-slot placeholder, reveal labels) wrapped for EN/PL, matching the 2b/2c i18n passes.

### 5.4 Testing

- **Unit/integration (pytest + factory_boy, real PostgreSQL):** parser → `DragBlank` creation; pool construction (dedup, distractors, stable order); `mark` per-target fraction (full / partial / zero / reusable-token / distractor-picked / forged-index) for both types; the shared `mark_slots` helper; empty-answer guard; quiz scoring of a partial drag-fill via the 2c `Decimal` boundary; `[N]` recorded-no-score. New `factory_boy` factories for both types + their sub-rows.
- **e2e (Playwright, JS + no-JS):** author each type (with distractors + marking fields) → student answers via **drag** (JS) and via **`<select>`** (no-JS), submits, sees correct/partial feedback; in a quiz, exhausts attempts and sees reveal, asserts no token leak pre-reveal, asserts resume rehydrates placements after reload.

### 5.5 Migration

One migration adds `DragFillBlankQuestionElement` + `DragBlank` + `MatchPairQuestionElement` + `MatchPair`. No alteration to existing tables (the marking fields are already on the base from 2c's 0015). Passes the existing migration-consistency gate.
