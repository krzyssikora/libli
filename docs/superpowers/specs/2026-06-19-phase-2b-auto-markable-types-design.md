# Phase 2b — Auto-markable type expansion (short text, short numeric, fill-blanks) — Design

**Status:** spec (brainstormed 2026-06-19)
**Slice:** Phase 2b — adds three keyboard-input, auto-markable question types on top of the 2a foundations. Each subclasses the abstract `QuestionElement`, implements the `mark() → MarkResult` contract, is authored through the existing per-unit editor, and renders formatively inside lesson units (no persistence). Proves the question abstraction is genuinely extensible beyond MCQ.
**Predecessors:** 2a (the `QuestionElement` abstract base, `MarkResult`, the `check_answer` answer→submit→feedback round-trip with JS-fragment + no-JS transports, the `_question_feedback.html` partial, the add-menu/`FORM_FOR_TYPE`/allowlist authoring dispatch, `build_lesson_context`, the no-leak/IDOR/CSRF invariants). All file references below are to the post-2a (PR #20) tree.

---

## 1. Purpose & scope

### 1.1 Phase 2 decomposition (updated)

Phase 2 (quiz engine & results) is decomposed into five slices, each its own spec → plan → build cycle. **This slice narrows the original 2b/2d split:** drag-fill-blanks moves from 2b to 2d, joining the other pointer drag-and-drop types so all DnD (with its accessibility + no-JS fallback burden) is solved once.

- **2a (shipped, PR #20):** Question foundations — `QuestionElement` base + `ChoiceQuestionElement` + `mark()` interface + answer→feedback loop, formative in lessons, no persistence.
- **2b — Auto-markable type expansion (this slice):** **short text** (normalized match), **short numeric** (value + absolute tolerance), **fill-blanks** (multi-gap, per-blank accepted answers). Three new element types plugging into 2a's marking interface. Still formative, still no persistence.
- **2c — Quiz units:** `unit_type=quiz` live — quiz-unit rendering (+ optional slideshow), quiz-level submission, the **Response/Attempt persistence model**, max attempts, max marks, **[N] not-marked / [R] requires-review** marking modes, attempt recording.
- **2d — Rich interactive + review types:** **drag-fill-blanks** (moved here from 2b), match pairs, drag-to-image (pointer DnD), extended response (required/forbidden keywords); the [R] human-review path.
- **2e — Results & metrics:** scores per question/unit/course, the [R] flag surfaced, student quiz summary.

### 1.2 What this slice is

Three new concrete question element types, authored through the existing per-unit editor and rendered into lesson units:

- **`ShortTextQuestionElement`** — the student types a short string; marked by normalized comparison against one or more author-supplied accepted answers (synonyms / spelling variants).
- **`ShortNumericQuestionElement`** — the student types a number; marked correct iff it lies within an author-set absolute tolerance of the expected value. Accepts both `,` and `.` decimal separators (bilingual PL/EN).
- **`FillBlankQuestionElement`** — the author writes a stem containing inline blank markers (`{{…}}`); the student fills each gap; each gap is marked individually against its own accepted-answer set, with per-blank feedback.

A student answers and receives **server-marked feedback** — correct/incorrect, the revealed accepted answer(s), per-blank highlighting for fill-blanks, and an optional author explanation — and may retry freely. Nothing is persisted (formative practice).

### 1.3 What this slice is NOT (scope boundaries — deferred)

- **No drag-fill-blanks.** Moved to 2d (§1.1).
- **No response persistence / quiz behavior / marking modes / max-marks / max-attempts.** All → 2c, exactly as deferred in 2a §1.4. A 2b answer is ephemeral practice.
- **No acted-on partial credit.** Fill-blanks *computes* a proportional `fraction` (and stores it in `MarkResult`) so 2c inherits the signal, but the formative **verdict is all-or-nothing** (`correct` iff every blank right), matching 2a. Short-text/numeric are single-answer → `fraction ∈ {0.0, 1.0}`.
- **No regex / pattern matching, no per-blank numeric blanks, no units.** Short-text blanks are normalized-string only; numeric is its own single-input type. (A fill-blank gap is always a text-match gap in 2b.)
- **No relative/percent numeric tolerance.** Absolute only in 2b; relative can be added later without interface change (it is another `mark()` internal).
- **No author-editable choice-style ordering UI.** Blank order is the marker order in the stem.
- **No results/metrics surfaces.** → 2e.

### 1.4 Non-goals

- No new dependency. Reuses Django, the bespoke RTE / `sanitize_html`, vendored KaTeX, the `fetch`+`X-CSRFToken` transport, and every 2a invariant.
- No change to the `UnitProgress` completion contract (answering is not required for completion; questions count as "seen" like any element).
- No change to `question.js` per type (it already serializes the whole form and swaps the feedback partial — see §4.2).

---

## 2. Data model

### 2.1 Shared marking primitives (`courses/marking.py`)

`MarkResult` (the frozen dataclass from 2a: `correct: bool`, `fraction: float`, `reveal`) is **unchanged**. `reveal` stays type-opaque to the marking core; each new type documents its own shape (§3). Two small pure helpers are added to `courses/marking.py` and reused by every type:

- **`normalize_text(s, *, case_sensitive=False) -> str`** — strip leading/trailing whitespace, collapse internal whitespace runs to a single space, and (unless `case_sensitive`) casefold. Used by short-text and fill-blank marking and (the same function) by the no-leak-safe accepted-answer comparison.
- **`parse_number(s) -> Decimal | None`** — parse a single number, returning a `Decimal` or `None` (malformed → `None` → marked incorrect). **Exact grammar** (no thousands separators — they are the source of comma/period ambiguity and are rejected): strip *outer* whitespace only; the trimmed string must match `^[+-]?\d+([.,]\d+)?$` — i.e. optional leading `+`/`-`, one or more digits, then at most **one** decimal separator which may be `.` **or** `,` followed by ≥1 digit. Normalize `,`→`.` before `Decimal(...)`. Anything else → `None`. Worked boundary cases (the test table of §5): `"3,14"`→`Decimal("3.14")`; `"3.14"`→`Decimal("3.14")`; `"-3,14"`→`Decimal("-3.14")`; `"+5"`→`Decimal("5")`; `"1,234"`→`Decimal("1.234")` (comma is **always** the decimal sep, never a thousands group); `"1 234"`→`None` (internal space rejected); `"1,2,3"`→`None`; `"1."`→`None`; `""`→`None`; `"abc"`→`None`. Uses `Decimal` to avoid binary-float tolerance drift. (Authors who need grouped large numbers simply enter them ungrouped; trade-off documented.)

### 2.2 The three concrete types

All extend the existing abstract `QuestionElement(ElementBase)` (which provides `stem`, `explanation`, sanitized on save, and the abstract `mark()`), so each owns its own table + GFK content-type, per the established element pattern.

```
ShortTextQuestionElement(QuestionElement)
  accepted        TextField                       # newline-delimited accepted answers (≥1 non-blank line)
  case_sensitive  BooleanField(default=False)
  elements        GenericRelation(Element)        # join-row back-ref (cascade delete)
  def mark(self, answer: str) -> MarkResult

ShortNumericQuestionElement(QuestionElement)
  value           DecimalField(max_digits=20, decimal_places=8)
  tolerance       DecimalField(max_digits=20, decimal_places=8, default=0, validators=[MinValueValidator(0)])
  elements        GenericRelation(Element)
  def mark(self, answer: str) -> MarkResult

FillBlankQuestionElement(QuestionElement)
  # stem (inherited) stores the rendered text with ordered placeholder tokens (§3.3)
  blanks          -> Blank rows (related_name="blanks")
  elements        GenericRelation(Element)
  def mark(self, answer: list[str]) -> MarkResult

Blank(models.Model)
  question        FK -> FillBlankQuestionElement (CASCADE, related_name="blanks")
  accepted        TextField                       # newline-delimited accepted answers (≥1) — parsed from {{a|b|c}}
  case_sensitive  BooleanField(default=False)     # per-blank (UI-default False in 2b; field present for future per-blank control)
  order           OrderField(for_fields=["question"], blank=True)

  class Meta:
      ordering = ["order", "pk"]
```

**Decision (locked in brainstorming): accepted answers are an encoded list field, not a `Choice`-style child table.** Unlike 2a's `Choice` (which carries a per-row `is_correct` widget and therefore needs a row UI), an accepted answer is a bare string with no per-row affordance — synonyms are a flat list. Short-text stores them as a newline-delimited `TextField` (authored via a textarea, "one accepted answer per line"); fill-blank blanks get their list by parsing `{{a|b|c}}`. This keeps the text-match primitive identical between the two types and avoids extra child tables. `Blank` **is** a child table (it needs `order` and a 1-question→N-gaps relation), but its `accepted` is itself an encoded list — `Blank` is parsed from the stem, never hand-edited as a formset.

- **`accepted` storage detail:** stored verbatim (newline-delimited, never sanitized — it is compared, not rendered as HTML; if shown in `reveal` it is auto-escaped). At mark time the field is split on newlines, blank lines dropped, each line `normalize_text`'d. The model is the source of truth; the split/normalize happens in `mark()` (and, for the accepted-answer count validation, in the form `clean()` — §3.1).
- **`ELEMENT_MODELS`** (the `Element.content_type.limit_choices_to` allowlist, `courses/models.py`) gains `"shorttextquestionelement"`, `"shortnumericquestionelement"`, `"fillblankquestionelement"`.

### 2.3 Migration

One new migration creating the three element tables + `Blank`, plus the validation-only **`AlterField` on `Element.content_type`** (no DDL/data change — exactly as 0010 did for `htmlelement` and 0013 for `choicequestionelement`; `makemigrations --check` expects it). All new fields blank-friendly or defaulted; no data migration.

---

## 3. Authoring & consumption

### 3.1 Authoring forms (`element_forms.py`) + dispatch

Three new `FORM_FOR_TYPE` keys and three add-menu cards. The type keys follow the 2a model-name→key derivation (`__class__.__name__.lower().replace("element","")`):

| Add card | add-key | type_key | Form |
|---|---|---|---|
| Short text | `shorttext` | `shorttext` | `ShortTextQuestionElementForm` |
| Short numeric | `shortnumeric` | `shortnumeric` | `ShortNumericQuestionElementForm` |
| Fill blanks | `fillblank` | `fillblank` | `FillBlankQuestionElementForm` |

Unlike 2a's choice cards (two cards → one `choicequestion` key), here each card maps **1:1** to its own type_key and model — no add-key→type_key translation layer is needed (the 2a translation existed only because single/multi shared one model). The three keys are added to the `element_add` / `element_save` allowlist tuples and to `FORM_FOR_TYPE`.

- **`ShortTextQuestionElementForm`** (ModelForm: `stem`, `explanation`, `accepted`, `case_sensitive`). `stem`/`explanation` use the RTE widget; `accepted` is a `Textarea` ("one accepted answer per line"). `clean_accepted` rejects a value with **zero** non-blank lines.
- **`ShortNumericQuestionElementForm`** (ModelForm: `stem`, `explanation`, `value`, `tolerance`). `value` required; `tolerance` defaults 0, validated `≥ 0`. Both are `DecimalField` form fields (server parses the canonical decimal; the *student-facing* `,`/`.` leniency of §2.1 applies only to **answers**, not to authoring — authors enter a canonical decimal).
- **`FillBlankQuestionElementForm`** (ModelForm: `stem`, `explanation`). No inline formset — the blanks come from the stem (§3.3). `clean()` parses the stem markers and validates: ≥ 1 well-formed `{{…}}` marker, every marker non-empty, each marker yields ≥ 1 non-blank accepted answer after splitting on `|`. Parse/validation errors surface on the `stem` field.

Standard 2a editor mechanics are reused unchanged: `element_add` is render-only (unbound form, no row created); `element_save` validates + saves inside the existing `@transaction.atomic` + optimistic-token lock; `builder.save_element` builds the form from `FORM_FOR_TYPE` and runs the save sequence.

### 3.2 Fill-blank marker parsing (the one new authoring mechanism)

- **Delimiter:** `{{ ... }}`, with `|` separating alternate accepted answers inside one gap: `The capital of France is {{Paris|paris}}.` This delimiter **does not collide with KaTeX**, which uses `\( … \)` and `\[ … \]`.
- **Math spans are skipped (decided here, not deferred).** Because fill-blank stems may carry KaTeX *and* double braces appear in legitimate LaTeX (`x^{{2}}`, `\frac{{a}}{{b}}`), the parser **first masks out `\(…\)` and `\[…\]` spans**, scans for `{{…}}` markers only in the unmasked (prose) text, then restores the math spans verbatim. So `{{` inside math is **never** a marker, and a blank can sit immediately beside math. The plan encodes the exact two-pass regex (mask math → match `\{\{(.+?)\}\}` non-greedily on the remainder); the *semantics* are fixed by this spec.
- **Marker edge cases (authoring validation, §3.1):** the marker regex is non-greedy `\{\{(.+?)\}\}`. After matching, the interior is split on `|` and each piece is stripped; **non-blank pieces** become accepted answers. Enumerated outcomes (all surface as a `stem` field error when rejected): `{{Paris}}` → accept (1 answer); `{{Paris|paris}}` → accept (2); `{{a|}}` → accept (1 answer, empty piece dropped); `{{}}` → **reject** (zero non-blank pieces); `{{|}}` → **reject** (zero non-blank pieces); a `{{` with no closing `}}` → **reject** as a malformed/unterminated marker (the regex leaves a literal `{{` in the prose, which validation detects and errors on — it is never silently rendered). Adjacent markers `{{a}}{{b}}` with no separating prose → accept (two consecutive inputs).
- **Parse → persist:** on save, `FillBlankQuestionElementForm.clean()`/save parses markers left-to-right. Each marker becomes a `Blank` row in marker order; the marker's interior is split on `|` (blank pieces dropped) and the remaining pieces stored as the blank's newline-delimited `accepted`. The **stored `stem`** has each `{{…}}` replaced by an ordered placeholder token (§3.3 pins the token format + render-time substitution) so rendering knows where to inject inputs and the accepted answers never reach the client in the stem.
- **Re-author on edit:** editing re-parses the stem and **rebuilds** the `Blank` set (delete-all-then-recreate within the atomic save), so the blanks always match the current stem. (No stable per-blank identity is needed in 2b — nothing references a blank across edits since there is no persistence.) **`Blank.order`:** because every existing `Blank` is deleted *before* the recreate, `OrderField`'s per-question scope is empty when the new rows are written, so it restarts from its empty-scope base and numbers them `base, base+1, …` in marker order — `(order, pk)` sort therefore equals marker order. (Same `OrderField` as 2a's `Choice.order`; the plan verifies the empty-scope base against `courses/fields.py` and that the delete+recreate occur in one transaction so no stale row is observed mid-scope.)
- **Escaping a literal `{{`:** out of scope for 2b (no known author need); the plan may add a `\{{` escape, but the default is that `{{` always starts a marker. Documented as a known limitation.

### 3.3 Initial render (security-critical)

`render_element` dispatches each type to its own template under `templates/courses/elements/`. **Each template wraps its inputs in its own isolated `<form method="post">`** (exactly as 2a's `choicequestion.html` does), so each question POSTs only its own fields — `name="answer"` / `name="blank"` are scoped to one form and **never collide** across multiple questions on a page, and a no-JS submit carries only the submitting form's values:

- **`shorttext.html`** — stem (sanitized HTML, KaTeX) + a single `<input type="text" name="answer">`.
- **`shortnumeric.html`** — stem + `<input type="text" inputmode="decimal" name="answer">` (text, not `number`, so `,` is accepted and locale quirks don't strip it).
- **`fillblank.html`** — the stem rendered with each placeholder token replaced by an `<input type="text" name="blank">` in document order (so the server reads `getlist("blank")` positionally).

**Placeholder token format + render-time substitution (security-critical — the stem is `|safe` HTML).** The stored stem is sanitized HTML containing opaque tokens; the token format is **`￿{n}￿`** — a sentinel wrapping the 1-based blank index in `U+FFFF` (the Unicode non-character, which `sanitize_html` strips from author input, so an author can never type it and it is collision-proof against prose, HTML, and LaTeX). Rendering is **not** naive string replacement into a safe string: a template filter (`render_fill_blanks`) **splits** the sanitized stem on the token regex, marks each surrounding HTML segment safe individually, and **joins** with server-built `<input>` markup — so the inputs are the only unescaped insertions and no author text can forge one. The substitution emits one input per token, in order, each pulling its repopulation value (no-JS path) from `submitted_values[n-1]`.
- **Token/`Blank` count invariant:** the atomic re-parse (§3.2) guarantees `stem token count == blanks.count() == n` for every stored fill-blank. The render asserts/relies on this; if they ever disagree (only possible via direct DB tampering, never via the editor), the filter renders inputs for the tokens actually present and the marking pads/truncates to `blanks.count()` (§3.4) — degraded but safe, never an exception. Adjacent tokens (from `{{a}}{{b}}`) render as two consecutive inputs with no prose between.

**No-leak invariant (carried from 2a §3.4):** `accepted`, `value`, and `tolerance` are **never** serialized into the initial render, and never for any *other* question on a post-submit no-JS page. Correctness exists only server-side; reveal data appears **only** for the single element matching `feedback_for_pk`.

### 3.4 Marking rules (2b)

`answer` reaches `mark()` already parsed from POST by the per-type `build_answer` (§3.5); `mark()` does no request handling. **`build_answer` is a thin POST reader; all padding/truncation and normalization happen inside `mark()`** (so the positional binding has exactly one owner — see I3 below). Every `mark()` returns a fully-populated `MarkResult` on **both** verdicts: a wrong answer is `MarkResult(correct=False, fraction=0.0, reveal=…)` with the `reveal` still populated, so feedback can always show the accepted answer.

- **`ShortTextQuestionElement.mark(answer: str)`** — split `accepted` on newlines, drop blank lines, `normalize_text` each (with this question's `case_sensitive`). `correct = True, fraction = 1.0` iff `normalize_text(answer, case_sensitive=…)` equals **any** normalized accepted line; otherwise `correct = False, fraction = 0.0`. Empty answer → incorrect (normalizes to `""`, which the ≥1-non-blank-line validation guarantees is not accepted). `reveal` = a representative accepted answer (the first non-blank line) — populated on both verdicts.
- **`ShortNumericQuestionElement.mark(answer: str)`** — `n = parse_number(answer)`; if `n is None` → `correct=False, fraction=0.0`. Else `correct = True, fraction = 1.0` iff `abs(n - value) <= tolerance`, else `correct=False, fraction=0.0`. Comparison is **exact `Decimal` arithmetic**: `parse_number` may return more decimal places than the field's `decimal_places=8`; `mark()` compares the parsed `Decimal` against the stored `value` directly (no quantize/round), so stored-field precision bounds only what an *author* can save, never marking. `reveal` = `{value, tolerance}` — populated on both verdicts.
- **`FillBlankQuestionElement.mark(answer: list[str])`** — `mark()` first normalizes the list to exactly `n_blanks` entries (pad short lists with `""`, **truncate** long ones), pairing each positionally with its `Blank` in `order`. Each entry is text-matched against that blank's `accepted` via `normalize_text` (per-blank `case_sensitive`). `n_correct = count of matching blanks`; `fraction = n_correct / n_blanks`; `correct = (n_correct == n_blanks)`. `reveal` = an ordered list of `{index, correct: bool, accepted: <representative answer>}`, one per blank — a **per-blank summary** (✓/✗ + the accepted answer for missed gaps). It deliberately does **not** carry the student's typed entries: those stay visible in the question's own retained/repopulated `<form>` (§3.6, §3.7), so the same `reveal` drives identical feedback on both transports.

**Numeric `reveal` rendering (display, §3.7):** suppress the `± tolerance` suffix entirely when `tolerance == 0` (show just the value); display `value`/`tolerance` via Django's active-locale number format (so a PL student who typed `3,14` sees `3,14`, an EN student sees `3.14`) rather than the raw `Decimal` repr.

All three are consistent with 2a's empty-answer-is-incorrect and server-is-authority rules.

### 3.5 The marking round-trip — generalizing `check_answer` (touches 2a code)

2a's `check_answer` (`courses/views.py`) hard-codes the choice wire format: `request.POST.getlist("choice")` → coerce ints → validate against `question.choices` → `set[int]`. 2b generalizes this so `check_answer` is **type-agnostic**:

- **A per-type `build_answer(self, post) -> answer` method** is added to each `QuestionElement` subclass, owning the POST→answer parsing and any per-type validation that 2a did inline:
  - `ChoiceQuestionElement.build_answer` = the existing logic (getlist `choice`, int-coerce, **validate against own `choices`**, return `set[int]`) — moved out of the view, behavior unchanged.
  - `ShortTextQuestionElement.build_answer` / `ShortNumericQuestionElement.build_answer` = `post.get("answer", "")` (a raw string; parsing/normalization happens in `mark()`).
  - `FillBlankQuestionElement.build_answer` = `post.getlist("blank")` (positional list of raw strings).
- **`check_answer` becomes:** resolve unit + access + element scoped to unit (unchanged IDOR/`require_lesson` discipline); `question = element.content_object`; `answer = question.build_answer(request.POST)`; `result = question.mark(answer)`; render feedback. **Nothing persisted.** The view no longer knows any per-type wire shape. The 2a `check_answer` tests are preserved (choice behavior is identical); the foreign/forged-id drop now lives in `ChoiceQuestionElement.build_answer` and its test moves with it.
- **`content_object` type gate** broadens from "is a `ChoiceQuestionElement`" to "is a `QuestionElement` subclass" (e.g. `isinstance(question, QuestionElement)` / membership in the question content-type set), so all four (2a + 2b ×3) types are answerable and any non-question element still 404s.

### 3.6 Two transports (progressive enhancement) — reused, plus value repopulation

Both 2a transports are reused with **no change to `question.js`** (it serializes the whole form and swaps the `_question_feedback.html` partial — independent of field types):

- **JS path:** intercept submit → `fetch` POST with `X-CSRFToken` → swap the feedback fragment into the question container, re-run KaTeX. Per-question, no reload.
- **No-JS path:** full POST to `check_answer`, which re-renders the **whole lesson unit** via `build_lesson_context`. 2a threads `selected_ids` to repopulate choice inputs; 2b adds a parallel **`submitted_values`** payload (the raw typed strings — a scalar for short-text/numeric, the positional list for fill-blanks) so the answered question's inputs repopulate on the re-render.

  **Three concrete edits are required (this is not a no-op beyond "forwarding") — the plan must do all three or a `render()` call raises `TypeError`:**
  1. **`render_element` gains the kwarg and forwards it unconditionally.** Its current signature is `render_element(element, feedback_for_pk=None, selected_ids=frozenset(), mark_result=None)`; it becomes `render_element(element, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)` and forwards **all** of `feedback_for_pk`, `selected_ids`, `submitted_values`, `mark_result` to `obj.render()` on every `QuestionElement` (the established `HtmlElement.render` forwarding precedent).
  2. **The `lesson_unit.html` tag call gains the argument:** `{% render_element el feedback_for_pk=… selected_ids=… submitted_values=… mark_result=… %}`. (Other call sites — e.g. the editor preview — keep the bare call; the kwarg defaults to `None`.)
  3. **`build_lesson_context` / `check_answer` add the `submitted_values` context key** (alongside 2a's `selected_ids`/`feedback_for_pk`/`mark_result`), populated only on the post-submit path.

  **One shared `render()` signature for all four question types (the cross-type contract).** Because `render_element` forwards a *fixed* kwarg set to every `QuestionElement`, all four overrides MUST accept the same signature or the call `TypeError`s: `render(self, *, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)`. `ChoiceQuestionElement.render` **gains `submitted_values`** (and ignores it — choices repopulate from `selected_ids`); the three new types **accept `selected_ids`** (and ignore it — they repopulate from `submitted_values`). Each injects its repopulation payload + (for the answered question) the `mark_result` into the `{"el": self, …}` context. Every other question re-renders fresh and feedback-free (identity gate on `element.pk == feedback_for_pk`).

### 3.7 Feedback partial — generalizing 2a's choice-specific partial (touches 2a code)

The shipped 2a `_question_feedback.html` is **choice-specific**: it iterates `{% for c in choices %}` and the JS-path `check_answer` renders it with the hardcoded context `{"el": question, "mark_result": result, "choices": choices}`. 2b must remove that hardcoding so the one partial serves all four types without forking the JS/no-JS surfaces.

- **The partial branches on element type and delegates to a per-type reveal include.** `_question_feedback.html` keeps the shared chrome — the verdict ("Correct"/"Incorrect", i18n; ✓/✗ glyphs are decorative CSS, not load-bearing strings) and the explanation — then `{% include %}`s a small per-type reveal partial chosen by the element's type key (the same `__class__.__name__.lower().replace("element","")` discriminator used elsewhere): `_reveal_choice.html` (the existing choice loop, extracted), `_reveal_shorttext.html` ("Correct answer: `<accepted>`"), `_reveal_shortnumeric.html` ("Expected: `<value>`", with `± <tolerance>` suppressed when `tolerance==0`, locale-formatted per §3.4), `_reveal_fillblank.html` (the ordered per-blank ✓/✗ + accepted-for-missed list). The `reveal` payload shape is the contract each include consumes (§3.4).
- **`check_answer` builds the feedback context generically — no `choices` key.** Both the JS-fragment branch and the no-JS full-page branch obtain the per-type context from the answered question's own `render()` (which already injects `mark_result`, the type's `reveal`, and any repopulation payload), rather than the view assembling a choice-shaped dict. So `check_answer` passes the same `{el, feedback_for_pk, mark_result, submitted_values|selected_ids}` it would for any type; the choice `choices` queryset is supplied by `ChoiceQuestionElement.render`, not by the view. (The 2a choice feedback output is unchanged — its loop simply moved into `_reveal_choice.html` and its context into `ChoiceQuestionElement.render`.)
- **No student-entry data in the fragment (the I5 symmetry).** The per-blank reveal is a *summary* from `reveal`; it never recolors the form inputs and never needs the student's typed values. The student's entries stay visible because each transport keeps the question's own `<form>` populated — retained in-DOM on the JS path (the fragment swaps into the feedback slot, not over the form), repopulated from `submitted_values` on the no-JS path. Both transports render the **same** partial from the **same** `reveal`, so JS and no-JS feedback cannot drift (the 2a guarantee).

### 3.8 Lesson view wiring & progress (auto-covered by 2a)

- **`has_questions`** is a content-type identity check over the question content-type set; 2a wrote it to "extend automatically" — adding the three new content-types to that set is all that's needed to gate `question.js`.
- **KaTeX gate:** 2a's per-element stem/choice text scan (`has_math_delimiters` over question text) extends to the new stems (short-text/numeric/fill-blank stems) and to fill-blank `accepted`/stem; the plan ORs the new types' text into the existing scan.
- **Progress:** each new question counts toward `seen_element_ids` like any element. Answering is **not** required for completion. `UnitProgress` contract unchanged.

---

## 4. Security & validation invariants (carried from 2a, extended)

- **No answer leakage:** `accepted` / `value` / `tolerance` never reach a render except via `reveal` for the single `feedback_for_pk` element. Tested two ways, mirroring 2a: (a) the **initial** lesson render contains no accepted-answer/value signal for any question; (b) on a post-submit page, reveal appears for the answered question **only** — every other question (of any type) is still clean.
- **Server is the marking authority:** `mark()` runs only server-side; the client submits raw input, never scores or correctness.
- **Forged / malformed input is inert:** a non-numeric short-numeric answer, an over-long string, extra/missing `blank` entries — all parse to "incorrect", never error-leak. `build_answer` is a thin POST reader (fill-blanks returns the raw `getlist("blank")`, possibly `[]` when the key is absent); **`mark()` normalizes that list to `n_blanks` by padding with `""` / truncating** (§3.4) — exactly one owner of the positional alignment. Foreign choice ids stay dropped in `ChoiceQuestionElement.build_answer`.
- **IDOR scoping & `require_lesson`:** `check_answer` reuses 2a's `get_node_or_404` + `can_access_course` + unit-scoped element fetch + lesson-only gate (a submit to a quiz unit 404s). Unchanged.
- **CSRF:** fetch path sends `X-CSRFToken`; no-JS path uses `{% csrf_token %}`. No `csrf_exempt`.
- **Authoring validation:** short-text ≥ 1 accepted answer; numeric `value` required + `tolerance ≥ 0`; fill-blank ≥ 1 well-formed marker each yielding ≥ 1 accepted answer. Enforced in form/`clean()` and consistent with `mark()`'s assumptions.
- **i18n:** all new strings wrapped (`gettext` / `{% trans %}`) + Polish translations, per the established gate (`compilemessages -l pl` is a DoD gate, so every new string needs a `.po` entry). The new author- and student-facing strings to translate include, at minimum: the three add-card titles ("Short text", "Short numeric", "Fill in the blanks"); the `accepted` textarea help ("One accepted answer per line") and label; the fill-blank stem help describing the `{{answer|alternate}}` marker syntax; `value`/`tolerance` field labels; the `case_sensitive` label; the marker/validation error messages (empty marker, unterminated marker, no accepted answers, <2-blank, etc.); and the feedback strings ("Correct answer:", "Expected:"). The plan enumerates the full list against the final templates/forms.

---

## 5. Testing & Definition of Done

- **Unit (`marking.py` + `mark()`):**
  - `normalize_text` (trim, internal-whitespace collapse, casefold on/off) and `parse_number` — the full §2.1 boundary table (`3,14`==`3.14`, `-3,14`, `+5`, `1,234`→`1.234`, `1 234`→`None`, `1,2,3`→`None`, `1.`→`None`, ``→`None`, `abc`→`None`).
  - Short-text `mark()`: match any accepted line; case-sensitive on/off; empty → incorrect; whitespace tolerance.
  - Short-numeric `mark()`: within/at/outside tolerance (Decimal, no float drift); decimal-comma; non-numeric/empty → incorrect; tolerance 0 = exact.
  - Fill-blank `mark()`: all-right (`fraction 1.0`, `correct`), some-right (proportional `fraction`, `correct=False`), short/long answer list (pad/truncate), per-blank case-sensitivity; `reveal` per-blank shape.
- **`build_answer` / `check_answer` view:** each type's correct/incorrect/empty path; fill-blank positional binding; **IDOR 404**; **quiz-unit submit 404** (`require_lesson`); choice foreign-id drop preserved; CSRF present; nothing persisted.
- **Authoring:** add + edit + delete each type via the editor; short-text accepted-answers textarea validation; numeric `value`/`tolerance` validation; fill-blank marker parse (well-formed, empty marker rejected, blank rebuilt on edit, blank order follows marker order).
- **No-leakage:** (a) initial render — no accepted/value signal for any question; (b) post-submit render — reveal only for the answered question, others (all types) clean.
- **Playwright e2e (`-m e2e`):** for **each** of the three types — author it in a lesson → as a student submit wrong (✗ + reveal + explanation), retry correct (✓) — in **both** the JS fragment-swap and no-JS full-POST paths (fill-blank e2e exercises a multi-gap question and asserts per-blank highlighting + input repopulation on the no-JS path).
- **DoD gate:** default `pytest -q` (e2e excluded) + e2e green; `ruff check .` + `ruff format --check .`; `makemigrations --check` (one new migration); `manage.py check`; collectstatic; `compilemessages -l pl`.

---

## 6. Files (anticipated; the plan will finalize)

- `courses/models.py` — `ShortTextQuestionElement`, `ShortNumericQuestionElement`, `FillBlankQuestionElement`, `Blank`; each with `mark()`, `build_answer()`, and the **shared** `render(self, *, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)` override (§3.6); `ChoiceQuestionElement.build_answer()` (logic moved from the view) and its `render()` widened to the shared signature (gains `submitted_values`, still injects `choices` into context); `ELEMENT_MODELS += [3 new]`.
- `courses/marking.py` — `normalize_text`, `parse_number` (helpers); `MarkResult` unchanged.
- `courses/migrations/00XX_*` — one new migration (3 tables + `Blank` + `Element.content_type` `AlterField`).
- `courses/element_forms.py` — `ShortTextQuestionElementForm`, `ShortNumericQuestionElementForm`, `FillBlankQuestionElementForm` (incl. marker parse/validate + `Blank` rebuild); `FORM_FOR_TYPE += {shorttext, shortnumeric, fillblank}`.
- `courses/views_manage.py` — three keys added to the `element_add`/`element_save` allowlist tuples (no add-key→type_key translation needed — 1:1 mapping).
- `courses/views.py` — `check_answer` generalized to `question.build_answer(...)`, broadened `QuestionElement` type gate, and feedback context built generically (no hardcoded `choices` — §3.7); `build_lesson_context` adds `submitted_values`; `lesson_unit.html` `render_element` call gains `submitted_values=`; `has_questions` + KaTeX scan extended to the new content-types.
- `courses/templatetags/courses_extras.py` — `render_element` signature gains `submitted_values` and forwards the full `{feedback_for_pk, selected_ids, submitted_values, mark_result}` set (§3.6); a `render_fill_blanks` filter that splits the sanitized stem on the `￿{n}￿` token and safe-joins server-built `<input>`s (§3.3).
- `templates/courses/elements/shorttext.html`, `shortnumeric.html`, `fillblank.html` — the three question forms, each its own isolated `<form>` (no leak).
- `templates/courses/elements/_question_feedback.html` — shared chrome (verdict + explanation) + per-type reveal `{% include %}`; new `_reveal_choice.html` (extracted 2a loop), `_reveal_shorttext.html`, `_reveal_shortnumeric.html`, `_reveal_fillblank.html`.
- `templates/courses/manage/_edit_shorttext.html`, `_edit_shortnumeric.html`, `_edit_fillblank.html` — editor partials; three add-menu cards.
- `courses/static/courses/js/question.js` — **unchanged** (whole-form serialize + partial swap already type-agnostic).
- `courses/static/courses/css/...` — minimal styles for text/numeric inputs + inline blank inputs + per-blank feedback (token-driven).
- `locale/pl/LC_MESSAGES/django.po` — Polish strings.
- `tests/...` — unit + authoring + no-leak + e2e per §5.
