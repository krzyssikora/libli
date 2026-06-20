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

- **`<select>`-per-target is the base; drag is decoration.** Each drop target (a gap in drag-fill, a left item in match-pairs) renders as a native `<select>` whose options are a **leading empty placeholder `<option value="">` (e.g. "— choose —")** followed by the available tokens. The empty placeholder is **mandatory and is the default selected option when the target is unfilled** — it is what makes "leave this gap blank" expressible in plain HTML (without it the browser auto-selects the first real token, so `""` could never be submitted and the all-empty guard of §3.3 would be unreachable). That `<select>` is **simultaneously** the no-JS fallback, the keyboard/screen-reader path, and the source of truth. JS enhancement layers pointer drag-and-drop *on top*: dragging a token chip into a target simply **sets that target's `<select>` value** (and clearing a slot resets it to `""`). The form always submits the `<select>` values, so the server receives an identical payload whether the student dragged or used the dropdown — it cannot tell which, and `build_answer`/`mark` never branch on transport.
- **Uniform answer payload:** an ordered list parallel to the targets, each entry the **text of the chosen token** (the `<select>` option's `value` *is* the token text), or `""` for an unfilled target. The substrate's `{target → token}` shape. Token **text**, not a positional pool index, is the value **deliberately** — this resolves a class of index fragility: correctness compares the submitted text to the target's expected text, so it is **independent of pool order** and **stable against author edits that reorder the pool**. The only edit that invalidates a stored answer is *deleting the exact token a student chose* — it then matches nothing and scores wrong, the same outcome as any other non-match (no silent index-shift corruption). The value carries author token text, so it is HTML-attribute-escaped when emitted into `<option value="…">` and is only ever compared as text on submit (never rendered as HTML on the answer path). Validation against forged input is membership, not bounds: a submitted token not in the pool is treated as unfilled/wrong (mirrors `ChoiceQuestionElement.build_answer` dropping forged ids).
- **One canonical pool builder.** A single pure function **`dnd.build_pool(question)`** — a referentially-transparent function of stored data only (gap/right tokens + distractors), de-duplicated by `normalize_text`, with **no per-request randomness or session seed** — is the sole source of the pool. It returns the pool as an **ordered list** of **raw** token strings in a deterministic, non-revealing order (sorted by `normalize_text`). **Dedup tie-break is pinned:** tokens are gathered in **source order — correct tokens (gap/`right`) first, then distractors in author order** — and the **first** occurrence of each `normalize_text` key wins; later normalize-equal duplicates are dropped. So which raw form survives a collision is deterministic (it drives the displayed chip text and resume pre-selection, §5.2). **Both `render` and `mark` call the same `build_pool`** (render to emit `<option>`s in that order; mark for membership), so the two can never disagree, and because correctness is by text the order is purely presentational and never affects scoring (fixed here only so the option order isn't a giveaway and doesn't reflow between submissions/resume).
- **Reusable tokens:** a token may be assigned to more than one target; the pool never depletes; each `<select>` independently lists every pool token. This keeps the JS and no-JS experiences identical (independent selects) and is the simplest substrate.
- **Distractors:** the pool may contain extra tokens that are the correct answer for no target (they are pool members that no target expects). The `distractors` field is split by **`_lines(...)` — the existing `courses.models._accepted_lines` helper** (newline-delimited, blank lines dropped, each line **verbatim — no per-line trim**), the same splitter fill-blank already uses. `build_pool` stores the **raw token verbatim** (it does **not** trim or otherwise rewrite the stored string — `correct_token`/`right` are likewise raw) and dedups **purely by `normalize_text` key** (which internally trims + collapses whitespace + casefolds, §`marking.py`), so a distractor that normalize-equals a correct token collapses into the single first-occurrence survivor (§1.2 tie-break). Because membership, matching, **and** dedup all key off `normalize_text`, scoring is independent of leading/trailing whitespace; only the *displayed* chip is the surviving verbatim raw form. Distractors otherwise enter the pool exactly like correct tokens.

### 1.3 Marking (locked in brainstorming)

Both types mark **per target**, identically to fill-blank:

- Each target has **exactly one expected token**. A target is correct iff its assigned token equals the expected token.
- `fraction = n_correct_targets / n_targets` (partial credit). `correct = (n_correct == n and n > 0)`.
- Only the auto-markable `[A]` path is exercised here; `[N]`/`[R]` modes already exist on the base from 2c and behave for these types exactly as for every other type (recorded, no score / awaiting-review) — **no `[R]`-native UI in this slice**.

### 1.4 What this slice IS / IS NOT

**Is:** two new `QuestionElement` subclasses + their sub-row models, forms, templates, the shared DnD JS module + its no-JS select base, per-type reveal partials, marking, i18n, and tests. Works in **both** lesson units (formative, ephemeral, always-reveal) and quiz units (persisted, attempt-capped, withhold-gated) by reusing the existing dispatch.

**Is NOT (deferred):**
- **No drag-to-image** (2d-ii) and **no extended-response / `[R]`-native type** (2d-iii).
- **No new view functions, URLs, or persistence model.** `QuizSubmission`/`QuestionResponse`/`Attempt` and the `check_answer`/`quiz_answer`/`quiz_finish` views are reused unchanged; the `latest_answer` JSON simply stores this slice's payload shape. **But "no new views" does *not* mean "zero existing-code edits":** marking (`build_answer`/`mark`) and rendering (`render()`) dispatch polymorphically, yet several **per-type registration touchpoints** in `courses/views.py` and `courses/quiz.py` are hard `isinstance`/enumerated lists that the two new types must be added to (§4.4). Missing them degrades silently (no math, N+1 queries, or the question gate misfiring), so they are in scope.
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

- `stem` (inherited) stores the **token-stem** produced by `fillblank.parse()` (the `￿{n}￿`-tokenised form), exactly as fill-blank does — the `{{…}}` parser pipeline (`_mask_math` → marker extraction → token substitution) is **reused as-is**, but it is *wrapped*, not used naked: `parse()` actively splits a marker on `|` and returns a multi-element accepted list, so the drag-fill form adds a post-check that each parsed marker yielded **exactly one** piece and takes `correct_token = pieces[0]` (§4.1). "Reused" = the same function is called; the single-token rule is enforced by the wrapper, not by `parse()` (which never rejects `|`).
- Ordered **`DragBlank`** rows (mirror of `Blank`): the parser writes one per `{{token}}` marker, in order.

```
class DragBlank(models.Model):
    question       FK(DragFillBlankQuestionElement, on_delete=CASCADE, related_name="dragblanks")
    correct_token  CharField(max_length=500)   # plain text + KaTeX delimiters; never sanitised
    order          OrderField(for_fields=["question"], blank=True)
    Meta.ordering = ["order", "pk"]
```

- `related_name="dragblanks"` is deliberately **distinct** from `Blank`'s `related_name="blanks"` (Django allows the clash since they hang off different models, but the distinct name avoids conflating the two when scanning for the existing `prefetch_related_objects(fill_qs, "blanks")`; the drag-fill prefetch is `"dragblanks"`, §4.4).
- **Pool** is built by `dnd.build_pool(self)` (§1.2) from `[b.correct_token for b in self.dragblanks.all()]` + `_lines(self.distractors)`. Each gap's expected token = its `DragBlank.correct_token` (the raw stored string; marking normalizes both sides, §3.2).
- Unlike fill-blank, a marker carries **one** token, not a `|`-list of accepted strings (a gap holds one chip). The author form rejects `|` inside a drag-fill marker (§4.1/§5.1) with a clear message.

### 2.2 `MatchPairQuestionElement`

```
distractors  TextField(blank=True)   # newline-delimited extra (unmatched) right-items
REVEAL_TEMPLATE = "courses/elements/_reveal_matchpair.html"
elements = GenericRelation(Element)
```

```
class MatchPair(models.Model):
    question  FK(MatchPairQuestionElement, on_delete=CASCADE, related_name="pairs")
    left      CharField(max_length=500)   # the fixed target label; plain text + KaTeX
    right     CharField(max_length=500)   # the correct token for this left; plain text + KaTeX
    order     OrderField(for_fields=["question"], blank=True)
    Meta.ordering = ["order", "pk"]
```

- **Targets** = the `pairs`' `left` items, in order. Each target's expected token = its pair's `right`.
- **Pool** is built by `dnd.build_pool(self)` from `[p.right for p in self.pairs.all()]` + `_lines(self.distractors)` — **`left` labels never enter the pool** (they are targets, not tokens). A token text that happens to equal a `left` label is permitted and harmless: marking is by token text vs `right`, never against `left`.
- `stem` (inherited) is the optional prompt above the two columns (no markers — plain rich text).

### 2.3 Shared token convention

Token / chip text follows the **MCQ `Choice.text` convention**: plain text + KaTeX delimiters (`\(x^2\)`), **never HTML-sanitised**, `max_length=500` (matching `Choice.text`'s actual length, so the precedent is exact in both treatment and size). This keeps math chips first-class (important for this platform).

### 2.4 Persistence (reused, unchanged)

In a quiz, a submission's `QuestionResponse.latest_answer` (and each `Attempt.answer`) stores this slice's payload: the ordered list of **chosen token-text strings**, one per target, `""` for an unfilled target (exactly what `build_answer` returns, §3.2). No schema change — the 2c JSONField already accepts any type-specific shape.

- **Resume rehydration.** `quiz.rehydrate(question, latest_answer)` already returns `(selected_ids=set(), submitted_values=latest_answer)` for every non-choice type via its default branch (`courses/quiz.py`); the two new types fall into that default **unchanged** — `submitted_values` is the stored token-text list. The drag-fill / match-pairs templates consume it through a **new** `render_selects(token_stem, pool, chosen)` helper whose semantics differ from fill-blank's `render_inputs`: `render_inputs` echoes `submitted_values[n]` as literal `<input value="…">` text, whereas `render_selects` **pre-selects the `<option>` whose value equals `chosen[i]`** (a token text). Same context channel, type-appropriate consumer. The new types must be added to `answer_from_json`'s default-passthrough as well (they already fall through, but §4.4 pins this).
- **Edit-during-resume safety.** Because the stored values are token *text* (§1.2), a mid-quiz author edit that reorders or adds/removes distractors leaves every still-valid placement correct on resume; only deleting the exact chosen token drops that target to unfilled. This is strictly better than a positional-index payload (which would silently mis-map on any reorder) and is consistent with 2c §5.2's documented "edits not re-marked, all moot once submitted" boundary. A regression test pins it (§5.4).

---

## 3. The substrate: rendering, transport & marking

### 3.1 Rendering (`render()` per type + a shared partial)

Each type implements `render(...)` (mirroring `ChoiceQuestionElement.render`), passing the **mode** (`lesson`|`quiz`), `action_url`, `feedback_partial`, `quiz_submitted`, `locked`, `attempts_left`, and the repopulation channel. Both per-type templates include one shared partial, **`courses/elements/_dnd_pool.html`**, that renders the chip pool + the drag JS hook; the per-type body differs only in target layout:

- **drag-fill** (`dragfillblankquestion.html`): the token-stem is rendered with a `render_selects(token_stem, pool, chosen)` helper (a sibling of `fillblank.render_inputs`) that splits on the opaque tokens and emits, per gap, a `<select name="slot">` — a **leading empty `<option value="">`** then one `<option value>` per pool token's **text** (`build_pool` order, §1.2). **Pre-selection on resume:** the option whose value equals `chosen[i]` is selected; **if `chosen[i]` is empty or no longer a pool member (deleted token), the empty placeholder is selected** — so a deleted-token resume genuinely shows unfilled rather than the browser silently defaulting to the first token (§5.2). Text segments are trusted sanitized HTML; only the server-built `<select>`s are inserted, with every `<option>` value **and** label HTML-escaped (`format_html`) — same safe-join discipline as `render_inputs`.
- **match-pairs** (`matchpairquestion.html`): a two-column layout — each `left` label (in the authored `["order","pk"]` order) beside its `<select name="slot">` (same empty-placeholder-then-tokens structure). **Target (left/gap) order is the authored order by design** — it is not shuffled; this is not a giveaway because the tokens are pooled and ordered independently (§1.2), so position never aligns answer-to-target.

`name="slot"` is uniform across both, so `build_answer` is `post.getlist("slot")` for both (parallel to fill-blank's `getlist("blank")`).

**Positional invariant (load-bearing).** Marking pairs `getlist("slot")[i]` with `expected[i]` purely by **position**, so the template MUST emit exactly one `<select name="slot">` per target in `self.dragblanks`/`self.pairs` order (the same `["order","pk"]` relation order `expected` is built from); browsers submit same-named controls in document order, so `getlist` preserves it. The JS enhancement **must not reorder, add, or remove the `<select>` nodes** (it hides them and overlays chips/slots in place) — a reordering would silently mis-align the payload and, because marking is by text not position-of-token, **mis-score without erroring**. Asserted by a test that submits after JS enhancement and checks the recorded answer matches the targets (§5.4).

**Progressive enhancement.** With JS off, the `<select>`s + a normal submit button are a complete, working question — **no orphaned UI**: the drag chips and drop-slots are **JS-injected** (`static/courses/dnd.js`), so with JS off they are absent entirely and only the native `<select>`s show (no empty styled boxes). With JS on, the script finds each target's `<select>`, hides it, injects draggable chips + drop-slots, and on drop/keyboard-activate **writes the chosen token's text into the `<select>` value and dispatches `change`** — so the existing submit path (and any per-question `fetch`) sees identical form data. The JS is pure decoration: if it throws or never loads, the selects remain fully usable.

### 3.2 Marking (`build_answer` + `mark`)

Both types share the **same per-target algorithm**, factored into a helper **`mark_slots(expected, pool, chosen)` in a new `courses/dnd.py`** (so drag-fill and match-pairs cannot diverge and 2d-ii reuses it). Its contract is pinned:

- **`expected`**: the ordered list of raw expected-token strings, length `n_targets` (drag-fill: each `DragBlank.correct_token`; match-pairs: each pair's `right`). `n_targets = len(expected)` is **authoritative** — sourced from the question's target relation (`self.dragblanks` / `self.pairs`, the same prefetched relation as §4.4), never from the submitted list length.
- **`pool`**: the raw-token list from `dnd.build_pool(question)` (§1.2) — used **only for membership**, tested on the **normalized** form (see flow), not for index math.
- **`chosen`**: the per-target submitted token-text list; `mark_slots` reads `chosen[i]` for `i in range(n_targets)`, treating any **missing (list shorter than `n_targets`), out-of-range, or `""`** entry as **unfilled** — so a stored answer whose length no longer matches the current `n_targets` (e.g. the author *added* a target after submission) marks safely instead of raising `IndexError`.
- Returns `(n_correct, reveal)`.

The flow:

- `build_answer(self, post)` → `post.getlist("slot")` — a list of submitted **token-text strings**, padded with `""` / truncated to exactly `n_targets` (mirrors fill-blank's pad/truncate), where `n_targets` is the question's target count (`self.dragblanks`/`self.pairs`). **Unfilled targets serialize as `""`** (never `None`/`0`), so the existing `quiz.answer_is_empty` list-branch (`not any(str(v).strip() …)`) treats an all-`""` answer as empty and **any** non-blank token text as non-empty. `build_answer` returns a **`list`** (not a tuple) so `quiz.answer_to_json` passes it through unchanged (§2.4).
- `mark(self, answer)` reconstructs `expected` and `pool` from `self` via `dnd.build_pool(self)` — the **same** function `render` uses (so membership can never disagree with what was rendered) — then calls `mark_slots`. `answer` may arrive fresh from `build_answer` **or** from `quiz.answer_from_json` (the stored list, possibly length-mismatched after an edit); the defensive `chosen[i]` reading above handles both.
  - For each target `i`: `got = chosen[i]` (or `""` if absent). `got` counts as **unfilled → wrong** when it is `""` **or** `normalize_text(got)` is **not** in `{normalize_text(p) for p in pool}` (forged / edited-away). **Membership is tested on the normalized form**, consistent with matching, so a legitimately-chosen chip whose raw form differs from the deduped survivor (§1.2 tie-break) is never falsely rejected. Otherwise `ok = normalize_text(got) == normalize_text(expected[i])`.
  - `n_correct = Σ ok`; `fraction = n_correct / n_targets` (or `0.0` if `n_targets == 0`); `correct = (n_correct == n_targets and n_targets > 0)`.
  - **`mark_slots` returns `(n_correct, reveal)`** where `reveal` is a tuple of per-target dicts **keyed `{index, correct, accepted}`** — the **exact shape and key names** `FillBlankQuestionElement.mark` produces (verified: `models.py` builds `reveal.append({"index", "correct", "accepted"})` then `reveal=tuple(reveal)`, stored in `MarkResult.reveal`, whose dataclass default is `frozenset` but already carries a tuple for fill-blank — so a tuple is an established precedent, not a type violation). `accepted` = the expected token text. The new `_reveal_dragfill.html` mirrors `_reveal_fillblank.html` directly.
  - **Match-pairs needs the `left` label per row** for its two-column reveal. `mark_slots` does **not** receive `left` (it only knows `expected`/`pool`/`chosen`), so `MatchPairQuestionElement.mark` **augments** each reveal dict after `mark_slots` returns — zipping in `left` to yield `{index, correct, accepted, left}` (consumed by `_reveal_matchpair.html`). Drag-fill leaves the 3-key dict as-is (indexed by gap order). This keeps the shared helper type-agnostic while each `mark` supplies its own presentation field.

`fraction` is a `float` (`0.0`–`1.0`); the quiz path's 2c boundary converts to `Decimal` and quantizes (`fraction × max_marks`), unchanged. Because `mark` reconstructs the pool from `self` (touching `self.dragblanks`/`self.pairs`), the quiz scoring/render paths must prefetch those relations — see §4.4. Forged or edited-away tokens score wrong, never error — the same "drop forged input silently" rule as `ChoiceQuestionElement.build_answer`.

### 3.3 Feedback & the withhold rule (reused)

In a **lesson** (formative) these types use the always-reveal `_question_feedback.html` + their `REVEAL_TEMPLATE`, like every 2a/2b type. In a **quiz**, they obey the 2c withhold state machine unchanged: pre-reveal (wrong, attempts remain) shows only "Incorrect — try again (N left)" with **no** `reveal`/`reveal_template`; reveal (correct, or wrong-on-last-attempt) renders the per-type reveal partial showing each target's expected token. The reveal partials (`_reveal_dragfill.html`, `_reveal_matchpair.html`) are new but follow `_reveal_fillblank.html` exactly (iterate the `reveal` tuple, mark each target correct/incorrect, show the expected token). The no-leak invariant therefore holds **by reusing 2c's reveal-gated context construction** — these types add no new path that could leak.

**Empty-answer guard (quiz path, 2c §3.1 step 3):** "empty" = **every** target unset (all `slot` values `""`). A fully-empty submit is rejected without burning an attempt; a partially-filled submit is a real attempt (consistent with fill-blank, where some-but-not-all blanks filled counts).

**`[N]`/`[R]` behavior (unchanged from 2c).** An `[N]` drag-fill/match submission records the answer (the same token-text payload) and shows the standard non-scored "Answer recorded" acknowledgement with **no per-target reveal** and no score; `[R]` records and sits "awaiting review" — exactly as for every other type. No per-type reveal partial runs in `[N]`/`[R]`; these types add no `[R]`-native UI (that is 2d-iii).

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

### 4.4 Existing-code touchpoints (the per-type registration points)

Marking and rendering dispatch polymorphically, but several spots in `courses/views.py` and `courses/quiz.py` are **hard `isinstance` branches or enumerated lists** that do *not* pick up new `QuestionElement` subclasses automatically. Each new type must be wired into all of them (confirmed against the post-2c tree); a missed one fails silently. To keep this from being an open-ended edit list (and to make 2d-ii/2d-iii cheap), the **preferred** approach is to push each branch behind a small hook on the `QuestionElement` base and have the new types (and ideally the existing ones) implement it; enumerated edits are the fallback where a hook is overkill.

- **Prefetch (perf).** `lesson_unit` and `quiz_unit` build `choice_qs`/`fill_qs` and call `prefetch_related_objects(fill_qs, "blanks")` **guarded by `if fill_qs:`** (`views.py`). Add `dragfill_qs`/`matchpair_qs` prefetching `"dragblanks"`/`"pairs"`, **keeping the per-type `if <qs>:` empty-list guard**. If this is folded behind a base `prefetch_fields()` hook, the hook must still **group instances by type** so each relation is prefetched only against instances that have it (`prefetch_related_objects` of `"pairs"` against a drag-fill instance errors) — i.e. the hook returns this type's relation name(s) and the caller groups, it does not prefetch across mixed types. Without the prefetch, `mark`/`render` rebuilding the pool from `self` triggers N+1 queries.
- **KaTeX detection.** `_question_has_math(q)` switches on `ChoiceQuestionElement`/`FillBlankQuestionElement` to decide whether to load KaTeX (`views.py`). KaTeX can appear in **tokens *and* labels** (§2.3), so the new types' `has_math()` must scan **all** math-bearing fields: drag-fill → the `stem` + every `DragBlank.correct_token` + distractors; match-pairs → the `stem` + every pair's `left` **and** `right` + distractors. (Scanning only the pool would miss `left`-column math, which fill-blank has no analogue for.) Missing this means that math doesn't render.
- **Question-CT gate.** `question_models` / `question_ct_ids` is a hard-coded model list backing `has_questions` (`views.py`). Add both new models, or derive the list from `QuestionElement.__subclasses__()`.
- **Resume / JSON round-trip.** `quiz.rehydrate`, `quiz.answer_from_json` (read paths) **and `quiz.answer_to_json` (write path)** all branch on `ChoiceQuestionElement` and **fall through to a default** that passes `latest_answer` / the `build_answer` payload through unchanged (`quiz.py`). The new types correctly use that default on **all three** — the token-text list is a plain `list`, which `answer_to_json` passes through (it only sorts sets and lists tuples), and `answer_from_json`/`rehydrate` return it untouched. The spec **requires a test** pinning that they stay on the default path of all three (a future refactor mustn't accidentally route them through the choice branch).
- **Results-page reveal (`quiz_results` / `_results_row`).** A **distinct render path** (`views.py`): the results summary does **not** re-run the live feedback flow — `_results_row(q, r)` reconstructs each `[A]` row's reveal by **re-calling `q.mark(answer_from_json(q, r.latest_answer))`** (or `q.mark(q.build_answer(QueryDict()))` for an unanswered question) and reading `q.REVEAL_TEMPLATE`. The two new types **work here generically**: they implement `mark` (which rebuilds the pool from `self` and returns the `{index, correct, accepted[, left]}` reveal tuple) and set `REVEAL_TEMPLATE`, so `_results_row` needs **no new per-type branch** — unlike `ChoiceQuestionElement`, whose reveal partial needs an extra `choices` context the new self-contained reveal tuples do not. The existing **"accepted N+1" stance** of `_results_row` (its docstring/comment notes choices/blanks access is an accepted N+1 for 2c, no prefetch) **extends unchanged** to the new types' per-row pool rebuild; no prefetch is added on the results path. The only requirement: the new `_reveal_dragfill.html` / `_reveal_matchpair.html` partials consume the reveal tuple (and `left` for match-pairs) — no `choices`-style augmentation needed.

---

## 5. Invariants, edge cases & testing

### 5.1 Invariants

- **No-JS parity:** with JS disabled, both types are fully answerable via `<select>`s and submit (lesson and quiz). Asserted by no-JS e2e.
- **No-leak (reused):** accepted tokens reach the client only in a revealing state; the quiz withhold path is 2c's, untouched. Regression test on the JS-fragment feedback (pre-reveal contains no expected-token text) **and** the resume render (an answered-not-correct `[A]` gap rehydrates without its expected token), scoped to the answered question's wrapper — same form as 2c §5.1.
- **Server-authoritative marking:** submitted token texts are validated server-side for pool membership; forged or non-member tokens score wrong, never error. The client cannot self-report correctness.
- **Transport-agnostic:** dragged vs dropdown submissions are byte-identical to the server (asserted by submitting the same answer both ways and comparing the recorded `Attempt`).

### 5.2 Edge cases (handled explicitly)

- **Distractor-only pool entry never matches** any target (it's the correct token for none).
- **Reusable token** correctly satisfies two targets that share an expected token (independent selects; both can pick it).
- **Partially-filled quiz submit** = a real attempt with partial credit; **all-empty** = rejected without burning an attempt (§3.3).
- **Pool order** comes from the single `build_pool` (§1.2), so `render` and `mark` never disagree; order is non-revealing and stable across re-renders/resume, and — because correctness is by token text — never affects marking.
- **Normalize-equal tokens:** two raw-distinct tokens that `normalize_text` to the same string de-duplicate to one pool entry; a target expecting either raw form still matches (both sides normalized at mark, §3.2).
- **Author edits mid-quiz:** because the payload is token *text*, a reorder or distractor add/remove leaves valid placements intact on resume; only deleting the exact chosen token drops a target to unfilled (scores wrong). Stored `fraction` is still not re-marked against edited *expected* answers (the 2c §5.2 limitation); all moot once `submitted`.
- **Marker with `|`** in drag-fill → form validation error (§4.1), not a silently-split multi-answer gap.
- **KaTeX in a token** renders in chip, select option, and reveal (plain text + delimiters; never sanitised — §2.3).

### 5.3 i18n

All new strings (validation messages, "Drag a token here" / drop-slot placeholder, reveal labels) wrapped for EN/PL, matching the 2b/2c i18n passes.

### 5.4 Testing

- **Unit/integration (pytest + factory_boy, real PostgreSQL):** parser → `DragBlank` creation (incl. the `|`-rejection wrapper, §4.1); `build_pool` determinism (dedup, distractors, deterministic order; **render and mark produce the identical pool for the same question** — the C1 property); `mark` per-target fraction (full / partial / zero / reusable-token / distractor-picked / forged-non-member token / **two raw-distinct-but-normalize-equal tokens**) for both types; the shared `mark_slots` helper contract; empty-answer guard (all-`""` empty, any token non-empty, incl. a token whose text is `"0"`); quiz scoring of a partial drag-fill via the 2c `Decimal` boundary; `[N]` recorded-no-score (no reveal). **Re-mark stability:** a stored answer re-marked after a fresh render yields the same `fraction`. **Edit-then-resume:** after an author reorders the pool / adds a distractor, a stored answer's placements rehydrate unchanged and re-mark identically; after the chosen token is *deleted*, that target rehydrates unfilled. **Resume routing:** `rehydrate`/`answer_from_json`/`answer_to_json` keep both new types on the default (non-choice) branch (§4.4). **Results-page reveal (§4.4):** `_results_row` re-marks via `mark(answer_from_json(...))` and produces the correct per-target reveal for an answered, a partially-answered, and an **unanswered** drag-fill/match row (the last via `mark(build_answer(empty))`), and match-pairs rows carry the `left` key. New `factory_boy` factories for both types + their sub-rows.
- **e2e (Playwright, JS + no-JS):** author each type (with distractors + marking fields) → student answers via **drag** (JS) and via **`<select>`** (no-JS), submits, sees correct/partial feedback; in a quiz, exhausts attempts and sees reveal, asserts no token leak pre-reveal, asserts resume rehydrates placements after reload. **Slot-order integrity:** after JS enhancement, submitting yields a recorded answer whose per-target values match the targets in document order (guards the §3.1 positional invariant against any JS DOM reordering).

### 5.5 Migration

One migration adds `DragFillBlankQuestionElement` + `DragBlank` + `MatchPairQuestionElement` + `MatchPair`. No alteration to existing tables (the marking fields are already on the base from 2c's 0015). Passes the existing migration-consistency gate.
