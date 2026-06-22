# Phase 2d-iii — Extended-response + the `[R]` human-review path — Design

**Status:** spec (brainstormed 2026-06-22)
**Slice:** Phase 2d-iii — the final slice of the Phase 2d split and the **9th (last) question type**. Ships two coupled things: (A) the **`ExtendedResponseQuestionElement`** type — long free text auto-marked by **required/forbidden keywords** — and (B) the generic **`[R]` "awaiting review" student substrate** — the student-facing states for the already-existing `[R]` (requires-review) and `[N]` (not-marked) modes, plus a thin **persistence seam** so Phase 3's teacher review *queue* drops in without a schema rewrite. No new view functions; reuses the 2c quiz machinery and the 2a/2b formative machinery wholesale.
**Predecessors:** 2a (the `QuestionElement` abstract base, `MarkResult`, `mark()`/`build_answer()`, the answer→submit→feedback round-trip with JS-fragment + no-JS transports, `render()` per-type dispatch, `REVEAL_TEMPLATE`, the no-leak/IDOR/CSRF invariants). 2b (`normalize_text`, the `_accepted_lines` newline splitter, `ShortTextQuestionElement` as the single-row free-text precedent). 2c (`marking_mode`/`max_attempts`/`max_marks` on the base; `QuizSubmission`/`QuestionResponse`/`Attempt`; the withhold-until-exhausted/correct feedback state machine; `quiz_feedback_context` already emitting `neutral="review"|"recorded"`; `_score_submission` already skipping non-`[A]` questions; the `mode` flag threaded through `render()`). 2d-i/2d-ii (the per-type registration-touchpoint discipline reused here). All file references are to the post-2d-ii (PR #26, merge `e5f6525`) tree.

---

## 1. Purpose & scope

### 1.1 Phase 2d decomposition (context)

Phase 2d was sub-split (in the 2d-i spec §1.1) into three slices, each its own spec → plan → build cycle:

- **2d-i — DnD substrate + drag-fill-blanks + match-pairs** — DONE & MERGED (PR #24).
- **2d-ii — drag-to-image** — DONE & MERGED (PR #26).
- **2d-iii — extended-response + the `[R]` human-review path (this slice).**

After 2d-iii all **9 question types** from the roadmap exist (single/multi MCQ, fill-blanks, drag-fill-blanks, short text, short numeric, match-pairs, drag-to-image, **extended response**). "2e — Results & metrics" follows unchanged.

### 1.2 The two deliverables (locked in brainstorming 2026-06-22)

This slice deliberately bundles a **type** and a **mode substrate**, the same shape as 2d-i (substrate proven by a type):

- **(A) Extended-response type.** A single-row free-text question (`<textarea>`), authored with two newline-delimited keyword lists. Mechanically the *simplest* type in the codebase: **no sub-row model** (keywords are stored as text on the element, parsed with the existing `_accepted_lines` splitter, exactly like `ShortTextQuestionElement.accepted`), and its answer is a **plain string** (so the quiz resume/JSON round-trip rides the existing default passthrough — §4.2).
- **(B) The `[R]`/`[N]` student substrate.** The `[R]` (requires-review) and `[N]` (not-marked) modes already exist on the base (`MarkingMode.REVIEW = "R"`, `MarkingMode.NOT_MARKED = "N"`) and the quiz path already records such a submission, locks it, computes no score, and excludes it from the total — but the **only** thing the student currently sees is the bare context string `neutral="review"|"recorded"` (set in `quiz.quiz_feedback_context`) with **no rendered UI**. This slice turns those strings into real student-facing states and adds the **persistence seam** for Phase 3. Because `[R]`/`[N]` are generic to *every* question type, this substrate is **type-agnostic** — extended-response is merely the first type for which `[R]` is the natural mode (a human reads an essay).

### 1.3 Marking — extended-response keyword scoring (locked in brainstorming)

When an extended-response question is in `[A]` (auto) mode, it is scored from its required/forbidden keyword lists with a **symmetric multiplicative** formula:

```
req_factor  = R_found / R_total            if R_total > 0 else 1.0
forb_factor = 1 - (F_found / F_total)      if F_total > 0 else 1.0
fraction    = req_factor * forb_factor     # always in [0.0, 1.0]
correct     = (fraction == 1.0)            # i.e. all required present AND no forbidden present
```

- `R_total`/`F_total` = number of distinct keywords in the required/forbidden lists. `R_found`/`F_found` = number of those keywords **present at least once** in the student's answer (present/absent — multiple occurrences of one keyword still count once).
- **Both zero-guards are load-bearing.** An author routinely fills only one list. With no required keywords the required factor is `1.0`; with no forbidden keywords the forbidden factor is `1.0`. So an only-forbidden question scores `1 * (1 - F_found/F_total)` and an only-required question scores `(R_found/R_total) * 1`. (Both lists empty is rejected at author time for `[A]` mode — §4.1 — so the degenerate `1.0 * 1.0 = 1.0` is unreachable in `[A]`.)
- **Forbidden is a graduated penalty, not a hard fail** (deliberate, symmetric with required). One forbidden term among four costs −25%, not the whole mark. An author who wants "any banned term = instant zero" lists exactly **one** forbidden keyword (then `forb_factor` is `0` the moment it appears). No special-casing.
- `correct` (which drives the green-check and the 2c withhold "try again" gate) is exactly `fraction == 1.0`.

### 1.4 Matching — whole-word / phrase (locked in brainstorming)

A keyword matches **only as a complete word, or a complete phrase for multi-word keywords** — never as a substring inside a larger word. Both the answer and each keyword are `normalize_text`'d (casefold + collapse whitespace + trim — Unicode-aware, so EN/PL diacritics fold), then a keyword is "found" iff it occurs bounded by word boundaries:

- Implemented as a Unicode word-boundary regex per normalized keyword: `(?<!\w)<re.escape(kw)>(?!\w)` searched against the normalized answer. (`\w`/`\b` in Python `re` over a `str` are Unicode-aware by default.) This makes `"ion"` **not** match `"question"`, `"cat"` **not** match `"category"`, while `"French Revolution"` matches the phrase and `"révolté"` matches case-insensitively.
- **No stemming / inflection** (explicit non-goal — would need a language-specific dependency; rejected per §1.6). `"revolt"` does not match `"revolts"`.
- A keyword that normalizes to empty (blank line) is dropped by `_accepted_lines` and never enters the lists.

### 1.5 The `[R]`/`[N]` student substrate & pending-score model (locked in brainstorming)

- **Score presentation = auto-total + pending tally.** The frozen `QuizSubmission.score`/`max_score` stay **`[A]`-only** (unchanged from 2c — `_score_submission` already `continue`s past non-`[A]` questions). The student sees the honest auto-marked total (`X / Y`) **plus a separate, derived footer**: *"N questions awaiting review (up to M more marks)"*, where `N` = count of `[R]` questions in the quiz and `M` = Σ their `max_marks`. The tally is **computed live** from the quiz's elements at render time — **no new stored field**. When Phase 3 reviews a `[R]` response (filling its `fraction`/`earned_marks` + `reviewed_at`), the reviewed mark folds into the total; that recompute is **Phase 3's** job, out of scope here.
- **Persistence seam = 2 nullable columns on `QuestionResponse`:** `reviewed_at DateTimeField(null=True, blank=True)` and `reviewed_by FK(accounts.User, null=True, on_delete=SET_NULL, related_name="+")`. The teacher's awarded mark **reuses the existing `fraction`/`earned_marks`** (null until reviewed). "Pending review" ⇔ `marking_mode == REVIEW and reviewed_at is None`. **No 2d-iii code writes these columns** — they are the reserved hook (roadmap principle: "reserve hooks for deferred features so adding them later doesn't force a schema rewrite"). Reusing `fraction`/`earned_marks` (rather than dedicated `review_fraction`/`review_marks`) is deliberate: when Phase 3 turns review on, the existing score-summation and results-reveal paths need **no "which field holds the mark" branch**.
- **`[N]` polished in parallel** (near-free): the `recorded` state gets a real "Answer recorded (not graded)" card alongside the `[R]` "awaiting review" card, in the same partial.

### 1.6 What this slice IS / IS NOT

**Is:** one new `QuestionElement` subclass (single-row, no sub-tables) + its form + template + reveal partial; a pure `mark_keywords` helper; the `[R]`/`[N]` student-facing feedback + results UI; the 2-column persistence seam; i18n; tests. Works in **both** lesson units (formative, ephemeral, always-reveal keyword self-check) and quiz units (persisted, attempt-capped, withhold-gated) by reusing existing dispatch.

**Is NOT (deferred):**
- **No teacher-facing review UI of any kind.** No review form, no queue, no Django-admin marking flow. The seam columns are written by **Phase 3**. 2d-iii ships only the *student* side + the reserved columns.
- **No new view functions, URLs, or persistence model** beyond the 2 nullable columns. `check_answer`/`quiz_answer`/`quiz_finish`/`quiz_results` and `QuizSubmission`/`QuestionResponse`/`Attempt` are reused; the new type rides the existing per-type dispatch + the per-type registration touchpoints (§4.3).
- **No recompute of a frozen quiz score** when a `[R]` is (later) reviewed — Phase 3.
- **No outline badge** for "review pending" — that edges into Phase 3 analytics; the quiz unit simply marks `UnitProgress.completed` at finish as today (a pending-review quiz is "completed, provisional").
- **No stemming/inflection, no fuzzy/semantic keyword matching, no regex-in-keyword** (§1.4).
- **No min/max answer-length authoring control.** A single module-level **char cap** (`EXTENDED_RESPONSE_MAX_CHARS = 10_000`) is enforced server-side in `build_answer`/`clean` to bound the stored `Attempt.answer` JSON — not an author-tunable field.

### 1.7 Non-goals

No new dependency (the keyword matcher is stdlib `re` + the existing `normalize_text`). No change to `MarkResult` (still `correct`/`fraction`/`reveal`). No change to the 2c withhold machinery, scoring `Decimal` boundary, or the lesson formative path. Extended-response is **plain prose** — no `{{…}}` markers, no token pool, no KaTeX in keywords (math may still appear in the `stem`, scanned for `has_math` like every other type).

---

## 2. Data model

### 2.1 `ExtendedResponseQuestionElement`

A `QuestionElement` subclass in `courses/models.py` (inherits `stem`/`explanation`/`marking_mode`/`max_attempts`/`max_marks`), **no sub-row model** — the closest precedent is `ShortTextQuestionElement` (single-row, newline-delimited `accepted`).

```
class ExtendedResponseQuestionElement(QuestionElement):
    required_keywords   = models.TextField(blank=True)   # newline-delimited; whole-word/phrase
    forbidden_keywords  = models.TextField(blank=True)   # newline-delimited; whole-word/phrase
    REVEAL_TEMPLATE = "courses/elements/_reveal_extendedresponse.html"
    elements = GenericRelation(Element)
```

- Keyword lists are parsed with the **existing `courses.models._accepted_lines`** helper (newline-delimited, blank lines dropped, each line trimmed) — the same splitter `ShortTextQuestionElement` and the DnD distractors use. Keyword **text** is plain prose + nothing else (no KaTeX delimiters expected); it is only ever compared as `normalize_text`'d text on the server and HTML-escaped if echoed into the reveal.
- `build_answer(self, post)` → `post.get("answer", "")[:EXTENDED_RESPONSE_MAX_CHARS]` (a plain `str`; `quiz.answer_to_json` passes a `str` through unchanged — §4.2). The cap also lives in the form's `clean_*`/template so an over-cap answer is a friendly bound, not silent truncation surprise. (`ShortTextQuestionElement.build_answer` is the precedent: `return post.get("answer", "")`.)
- `mark(self, answer)` → calls `keywords.mark_keywords(answer, _accepted_lines(self.required_keywords), _accepted_lines(self.forbidden_keywords))` and returns a `MarkResult` (§3.2).

### 2.2 `QuestionResponse` — the persistence seam (2 nullable columns)

In `courses/models.py`, add to the existing `QuestionResponse`:

```
reviewed_at  = models.DateTimeField(null=True, blank=True)
reviewed_by  = models.ForeignKey(
                   settings.AUTH_USER_MODEL, null=True, blank=True,
                   on_delete=models.SET_NULL, related_name="+")
```

- **Both nullable, no default change to existing rows** (an `AddField(null=True)` is a metadata-only migration). No existing 2c behaviour reads them; `_score_submission` is untouched in this slice.
- The teacher's eventual verdict reuses `fraction`/`earned_marks` (already nullable on `QuestionResponse`). **Invariant for Phase 3 (documented, not enforced here):** a `[R]` response is "reviewed" iff `reviewed_at is not None`, at which point `fraction`/`earned_marks` carry the human mark. Until then both stay `None` and the response is "pending".
- `related_name="+"` (no reverse accessor) — Phase 3 can widen it; 2d-iii needs no `user.reviewed_responses` query.

### 2.3 Persistence (reused, unchanged)

A quiz `[A]` extended-response stores its plain-string answer in `QuestionResponse.latest_answer` and each `Attempt.answer` exactly as `ShortTextQuestionElement` does; `[R]`/`[N]` store the same string with `fraction`/`earned_marks` `None` and `locked=True` after the single submission (2c behaviour, unchanged). The 2c JSONField already accepts a bare string.

### 2.4 Migration (0019)

One migration: `CreateModel ExtendedResponseQuestionElement` + `AddField QuestionResponse.reviewed_at` + `AddField QuestionResponse.reviewed_by`. No alteration to existing tables' data. Passes the migration-consistency gate.

---

## 3. Marking & rendering

### 3.1 `mark_keywords` — a pure helper (`courses/keywords.py`)

A new small module (sibling of `courses/dnd.py`/`fillblank.py`), pure and referentially transparent:

```
def mark_keywords(answer: str, required: list[str], forbidden: list[str]) -> tuple[float, tuple, bool]:
    # returns (fraction, reveal, correct)
```

- Normalize the answer once via `normalize_text(answer)` (default, case-insensitive). For each keyword, `present = bool(re.search(r"(?<!\w)" + re.escape(normalize_text(kw)) + r"(?!\w)", norm_answer))`.
- `R_total = len(required)`, `R_found = Σ present(req)`, likewise forbidden.
- Apply the §1.3 formula (with both zero-guards), clamp to `[0.0, 1.0]`.
- `reveal` = a tuple of per-keyword dicts `{keyword, kind, found}` (`kind ∈ {"required","forbidden"}`, `keyword` the **raw** authored line for display, `found` the bool) — required entries first (author order), then forbidden (author order). Mirrors fill-blank's "tuple of per-target dicts in `MarkResult.reveal`" precedent (a tuple is an established `reveal` payload there).
- `correct = (fraction == 1.0)`.

Pinned property (tested): `mark_keywords` is a pure function of `(answer, required, forbidden)` — no randomness, no DB. `ExtendedResponseQuestionElement.mark` is the only caller in the consumption path and rebuilds the lists from `self` (no sub-row prefetch needed — they are text columns on the element row already loaded).

### 3.2 `MarkResult` mapping

`ExtendedResponseQuestionElement.mark(answer)` returns `MarkResult(correct=correct, fraction=fraction, reveal=reveal)` where `reveal` is the §3.1 tuple. The `fraction` is a `float`; the quiz path's 2c `Decimal` boundary (`scoring.py`) quantizes `fraction × max_marks` unchanged. Forged/over-cap input cannot error — `build_answer` caps and `mark_keywords` only searches text.

### 3.3 Rendering (`render()` + templates)

- **Student template `extendedresponsequestionelement.html`** (named by `_meta.model_name` convention, like every element): a `<textarea name="answer" maxlength="10000">` + the mode-aware feedback container (the single 2c per-question container threaded by `render()`), and the submit/`fetch` path identical to `ShortTextQuestionElement`. **No JS enhancement at all** — the plain textarea + submit is the complete experience (the simplest no-JS parity in the codebase).
- **Reveal partial `_reveal_extendedresponse.html`** (new): iterates `mark_result.reveal`, listing required keywords as found ✓ / missing ✗ and forbidden keywords as present ✗ / absent ✓, each keyword HTML-escaped. Consumed **only** in a revealing state (lesson always-reveal, or quiz reveal-gated), so it never leaks the keyword lists pre-reveal (§5.1). In a lesson (formative) this is the keyword self-check; in a quiz `[A]` it is the reveal after correct/last-attempt.
- **Lesson vs quiz.** `marking_mode` is a quiz-only concept (the `_MarkingFieldsMixin` shows the marking fields only for quiz units). In a **lesson**, `check_answer` always calls `mark()`, so extended-response always renders the keyword self-check reveal — `[R]`/`[N]` have no meaning in a formative lesson and never reach the lesson path. In a **quiz**, `[A]` scores + reveals via the 2c withhold gate; `[R]`/`[N]` skip `mark()` and render the §3.4 substrate.

### 3.4 The `[R]`/`[N]` feedback & results UI (type-agnostic)

The plumbing already exists; 2d-iii renders it:

- **Per-question quiz feedback.** `quiz.quiz_feedback_context` already returns `neutral="review"` (for `[R]`) or `neutral="recorded"` (for `[N]`) with `mark_result=None`, `reveal_template=None`. The mode-aware per-question feedback partial gains two branches rendering, respectively, an **"✓ Submitted — your teacher will mark this"** card (`review`) and an **"Answer recorded (not graded)"** card (`recorded`). No score, no reveal, no keyword leak — these add no new context channel.
- **Results page.** `quiz_results` / `_results_row` already dispatches on `marking_mode` with outcome-only branches for `[N]`/`[R]` (no per-type `mark()`). 2d-iii fills those branches' presentation: a `[R]` row shows **"Awaiting review"** (+ "up to `{max_marks}` marks"); an `[N]` row shows **"Recorded — not graded"**. No `mark()` call, no reveal partial, so no per-type work and no leak.
- **Quiz total footer.** `quiz_results` computes, from the quiz's question elements, `pending_count = #[R]` and `pending_marks = Σ [R].max_marks` and passes them in the context; the template renders **"N questions awaiting review (up to M more marks)"** under the `[A]`-only `score / max_score` when `pending_count > 0`. Live-derived in the view, no stored field. (`[N]` questions are **not** counted as pending — they are intentionally ungraded, not deferred.)

---

## 4. Authoring & registration touchpoints

### 4.1 `ExtendedResponseQuestionElementForm`

A `ModelForm` in `courses/element_forms.py` using `_MarkingFieldsMixin` (so `marking_mode`/`max_attempts`/`max_marks` appear quiz-gated, exactly as for every 2c type), registered in `FORM_FOR_TYPE` as `"extendedresponsequestion"`:

```
fields = ["stem", "explanation", "required_keywords", "forbidden_keywords",
          "marking_mode", "max_attempts", "max_marks"]
```

- **Validation (cross-field `clean`): when `marking_mode == "A"`, require ≥1 keyword across the two lists** (an `[A]` extended-response with no keywords is meaningless — it would trivially score `1.0`). In `[R]`/`[N]`, keywords are **optional** (the teacher marks by hand; keywords may still be authored as a Phase-3 rubric hint). Message i18n-wrapped: *"Auto-marked extended response needs at least one required or forbidden keyword."*
- Each keyword line ≤ a sane length (reuse the textarea; no DB cap since the columns are `TextField`); blank lines dropped by `_accepted_lines` at mark time. The `stem` is sanitized rich text exactly as other stems.
- **Editor partial `_edit_extendedresponsequestion.html`** (new): two labelled textareas (required / forbidden, with one-line help on whole-word/phrase + newline-delimited) + `_marking_fields.html` (the quiz-gated marking block) + `_rte_toolbar.html` for the `stem` if other stems use it. **No formset** (single-row).

### 4.2 Resume / JSON round-trip (rides the default)

`quiz.rehydrate`, `quiz.answer_from_json`, `quiz.answer_to_json` all branch on `ChoiceQuestionElement` and fall through to a default that passes the value through unchanged. Extended-response's answer is a **plain `str`** → all three use the default path unchanged (`answer_to_json` only sorts sets / lists tuples; a `str` passes through). **A test pins** that the new type stays on the default branch of all three (a future refactor must not route it through the choice branch). No prefetch and no `rehydrate` special-casing.

### 4.3 Existing-code touchpoints (per-type registration)

Mechanically the **lightest** new type to date — single-row, plain-string answer, no formset, no sub-row prefetch — but it still must be wired into every hard `isinstance`/`type_key` list (confirmed against the post-2d-ii tree; a missed one fails silently or 400s):

**Consumption (`views.py` / `quiz.py`):**
- **Prefetch:** **none needed** — no sub-rows. (Do **not** add it to any `prefetch_related_objects` group.)
- **KaTeX detection (lesson path only).** Add an `isinstance(q, ExtendedResponseQuestionElement)` branch to `build_lesson_context`'s `_question_has_math` closure scanning **only the `stem`** (keywords are prose, never math). Quiz path already sets `has_math = bool(questions)`, no change.
- **Question-CT gate (lesson path only).** Add the model to `build_lesson_context`'s `question_models` list (backs `has_questions`/`question_ct_ids`). Quiz path hardcodes `has_questions=True`, no change.
- **Resume/JSON:** rides the default on all three functions (§4.2) — pinned by test, no code branch.
- **Results-page reveal (`_results_row`).** The `[A]` branch calls `q.mark(...)` + reads `q.REVEAL_TEMPLATE` generically — works with no new per-type branch (extended-response implements `mark` and sets `REVEAL_TEMPLATE`). The `[R]`/`[N]` outcome-only branches get the §3.4 presentation (type-agnostic). The existing "accepted N+1" stance extends unchanged (no prefetch on the results path; keyword columns are already on the loaded row).

**Authoring (`views_manage.py` / `builder.py` / templates):**
- **Add-element menu** `_add_menu.html`: add one `data-add-type="extendedresponsequestion"` button (icon + i18n label).
- **`type_key` allowlists:** add `"extendedresponsequestion"` to **both** `views_manage.element_add` and `views_manage.element_save` allowlists.
- **Host-form / formset render:** **none** — single-row, no formset, so `_render_open_form` needs no `course=`/formset special-case (it flows through the generic non-choice path, like `shorttextquestion`).
- **`builder.save_element` persist branch:** the **`else` plain `form.save()`** branch already handles single-row types (`shorttextquestion`/`shortnumericquestion`) — extended-response needs **no new branch** (no sub-rows to create). Confirm it is **not** caught by an earlier `elif type_key ==` so it reaches the `else`.

### 4.4 Editor display

The three marking fields show only for quiz units and hide `max_marks`/`max_attempts` for `[N]`/`[R]` — inherited verbatim from `_MarkingFieldsMixin`; no new logic. (So an author setting `[R]` on an extended-response sees only `marking_mode`, consistent with every other type.)

---

## 5. Invariants, edge cases & testing

### 5.1 Invariants

- **No-leak:** the required/forbidden keyword lists reach the client **only** in a revealing state (the reveal partial), gated by the 2c withhold machinery untouched. A quiz `[A]` extended-response with attempts remaining shows only "Incorrect — try again (N left)" with **no** `reveal_template` and **no** keyword text. Regression test on the JS-fragment feedback (pre-reveal contains no keyword) **and** the resume render (an answered-not-correct `[A]` rehydrates without its keywords). `[R]`/`[N]` cards carry no keyword text at all.
- **No-JS parity:** the `<textarea>` + submit is fully functional with JS disabled (lesson and quiz). No JS enhancement layer exists for this type. *(Carries the platform-wide no-JS `csrf_token` ticket — empty token in `render_to_string` without a request — at exact parity with every other type; flagged for 2e, not fixed here.)*
- **Server-authoritative marking:** keyword scoring is server-side; the client cannot self-report correctness; the answer is capped server-side in `build_answer`.
- **Seam is inert in 2d-iii:** `reviewed_at`/`reviewed_by` are never written by this slice; `_score_submission` is unchanged; the frozen `[A]`-only total is byte-identical to 2c for a quiz with no `[R]` questions. A test asserts a `[R]`-containing quiz finishes with `[A]`-only `score`/`max_score` and the response's `reviewed_at is None`.

### 5.2 Edge cases (handled explicitly)

- **Empty required list** → `req_factor = 1.0` (zero-guard); **empty forbidden list** → `forb_factor = 1.0`. Both empty → rejected at author time for `[A]` (§4.1), so unreachable in scoring.
- **Whole-word, not substring:** `"ion"` does not match `"question"`; `"cat"` does not match `"category"` (test).
- **Phrase keyword:** `"French Revolution"` matches the contiguous normalized phrase; not matched if the two words are non-adjacent (test).
- **PL diacritics / case:** `normalize_text` casefolds, so `"Révolté"` keyword matches `"révolté"` in the answer (test with a PL pair).
- **Duplicate occurrence counts once:** a required keyword appearing 3× contributes `1` to `R_found` (test).
- **Forbidden graduated:** all required + 1 of 4 forbidden → `1 * (1 - 0.25) = 0.75` (test); all required + the single forbidden of a one-item list → `0.0` (the "hard fail via one keyword" path).
- **Over-cap answer:** truncated to `EXTENDED_RESPONSE_MAX_CHARS` in `build_answer` (test).
- **`[R]` in a lesson:** unreachable — lessons hide `marking_mode` and always `mark()`; extended-response in a lesson always self-checks (documented, test asserts the lesson path reveals the keyword breakdown regardless of the stored `marking_mode`).
- **`[N]` not counted as pending:** the results footer counts only `[R]` toward "awaiting review"; `[N]` shows "recorded" and is excluded from the pending tally (test).

### 5.3 i18n

All new strings — the two validation messages, the textarea help text, the reveal labels ("Required keyword found/missing", "Forbidden keyword present/absent"), the "Submitted — your teacher will mark this" / "Answer recorded (not graded)" / "Awaiting review" / "N questions awaiting review (up to M more marks)" cards — wrapped for EN/PL with real Polish, matching the 2b/2c/2d i18n passes.

### 5.4 Testing

- **Unit/integration (pytest + factory_boy, real PostgreSQL):**
  - `mark_keywords` purity + the full formula matrix: all-required/none, partial required, only-forbidden (zero-guard), only-required (zero-guard), graduated forbidden, one-item-forbidden hard fail, `correct == (fraction==1.0)`; whole-word-not-substring; phrase; PL-diacritic case-fold; duplicate-counts-once; over-cap truncation.
  - `ExtendedResponseQuestionElement.mark` → `MarkResult` shape (reveal tuple of `{keyword,kind,found}`, required-then-forbidden order).
  - Quiz: `[A]` partial scored via the 2c `Decimal` boundary; `[R]` records answer, `locked=True`, `fraction`/`earned_marks`/`reviewed_at` all `None`, **excluded** from frozen `score`/`max_score`; `[N]` records, "recorded", excluded. Pending tally (`pending_count`/`pending_marks`) computed correctly with mixed `[A]`/`[R]`/`[N]`.
  - Resume routing: `rehydrate`/`answer_from_json`/`answer_to_json` keep the type on the default (non-choice) branch.
  - Results page: `[A]` row reveals keyword breakdown; `[R]` row shows "Awaiting review (up to M)"; `[N]` row shows "Recorded — not graded"; the footer renders the pending tally only when `pending_count > 0`.
  - Authoring: `[A]`-with-no-keywords rejected; `[R]`/`[N]`-with-no-keywords accepted; `save_element` reaches the `else` plain-`form.save()` (no sub-rows created). New `factory_boy` factory for the type.
  - Seam: migration adds the 2 columns nullable; a 2c-shaped quiz with no `[R]` finishes identically.
- **e2e (Playwright, JS + no-JS):** author an extended-response (keywords + marking fields) → student answers via the plain `<textarea>` (works identically JS on/off) → in a **lesson** sees the keyword self-check; in a **quiz `[A]`** exhausts attempts and sees the reveal, asserts **no keyword leak pre-reveal**, asserts resume rehydrates the typed text after reload; in a **quiz `[R]`** sees the "Submitted — awaiting review" card on submit and "Awaiting review" + the pending-tally footer on the results page.

### 5.5 Migration

One migration (`0019`) — `ExtendedResponseQuestionElement` table + `QuestionResponse.reviewed_at`/`reviewed_by` (both nullable, metadata-only AddField). No alteration to existing tables' data. Passes the migration-consistency gate.
