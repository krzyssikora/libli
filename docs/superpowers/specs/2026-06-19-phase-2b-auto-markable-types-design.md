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
- **`parse_number(s) -> Decimal | None`** — parse a single number, returning a `Decimal` or `None` (malformed → `None` → marked incorrect). **Exact grammar** (no thousands separators — they are the source of comma/period ambiguity and are rejected): strip *outer* whitespace only; the trimmed string must match `^[+-]?(\d+([.,]\d+)?|[.,]\d+)$` — i.e. optional leading `+`/`-`, then **either** ≥1 integer digit with an optional single decimal separator (`.` or `,`) + ≥1 fraction digit, **or** a leading-bare decimal (`.5` / `,5`). Normalize `,`→`.` before `Decimal(...)`. Anything else → `None`. **Deliberate trade-offs (documented):** a *leading*-bare decimal is accepted (`.5`→`0.5`, student-friendly), but a *trailing*-bare decimal (`5.`, `5,`) and a bare separator (`.`) are **rejected** as malformed. Worked boundary cases (the §5 test table): `"3,14"`→`Decimal("3.14")`; `"3.14"`→`Decimal("3.14")`; `"-3,14"`→`Decimal("-3.14")`; `"+5"`→`Decimal("5")`; `".5"`→`Decimal("0.5")`; `",5"`→`Decimal("0.5")`; `"-.5"`→`Decimal("-0.5")`; `"1,234"`→`Decimal("1.234")` (comma is **always** the decimal sep, never a thousands group); `"5,"`→`None`; `"5."`→`None`; `"."`→`None`; `"1 234"`→`None` (internal space rejected); `"- 5"`→`None` and `"3 ,14"`→`None` (no whitespace permitted mid-string, around the sign or the separator); `"1,2,3"`→`None`; `""`→`None`; `"abc"`→`None`. Uses `Decimal` to avoid binary-float tolerance drift. (Authors who need grouped large numbers simply enter them ungrouped.)

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
  case_sensitive  BooleanField(default=False)     # reserved: ALWAYS False in 2b (no authoring path); see §3.4
  order           OrderField(for_fields=["question"], blank=True)

  class Meta:
      ordering = ["order", "pk"]
```

**Decision (locked in brainstorming): accepted answers are an encoded list field, not a `Choice`-style child table.** Unlike 2a's `Choice` (which carries a per-row `is_correct` widget and therefore needs a row UI), an accepted answer is a bare string with no per-row affordance — synonyms are a flat list. Short-text stores them as a newline-delimited `TextField` (authored via a textarea, "one accepted answer per line"); fill-blank blanks get their list by parsing `{{a|b|c}}`. This keeps the text-match primitive identical between the two types and avoids extra child tables. `Blank` **is** a child table (it needs `order` and a 1-question→N-gaps relation), but its `accepted` is itself an encoded list — `Blank` is parsed from the stem, never hand-edited as a formset.

- **`accepted` storage detail:** stored verbatim (newline-delimited, never sanitized — it is compared, not rendered as HTML; if shown in `reveal` it is auto-escaped). At mark time the field is split on newlines, blank lines dropped, each line `normalize_text`'d. The model is the source of truth; the split/normalize happens in `mark()` (and, for the accepted-answer count validation, in the form `clean()` — §3.1). The newline-delimited encoding is unambiguous because **a marker interior is single-line**: `{{…}}` markers are parsed out of the (single-line-per-marker) stem and a newline can never appear *inside* a `{{…}}`, so a `|`-separated piece can never itself contain a newline (§3.2).
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
- **`ShortNumericQuestionElementForm`** (ModelForm: `stem`, `explanation`, `value`, `tolerance`). `value` required; `tolerance` defaults 0, validated `≥ 0`. **Author input uses the same `,`/`.` leniency as students** (the type exists to be PL/EN bilingual, so a PL author typing `3,14` must not get a validation error): `clean_value`/`clean_tolerance` run the field through **`parse_number`** rather than relying on `DecimalField`'s locale-dependent form parsing, so authoring accepts exactly what §2.1 accepts. The resulting `Decimal` must fit the model field bound (`max_digits=20, decimal_places=8`); a value exceeding the precision is a **validation error** (surfaced on the field), not a silent quantize, so what the author sees saved is what marking compares against.
- **`FillBlankQuestionElementForm`** (ModelForm: `stem`, `explanation`). No inline formset — the blanks come from the stem (§3.3). `clean()` parses the stem markers and validates: ≥ 1 well-formed `{{…}}` marker, every marker non-empty, each marker yields ≥ 1 non-blank accepted answer after splitting on `|`. Parse/validation errors surface on the `stem` field.

Standard 2a editor mechanics are reused unchanged: `element_add` is render-only (unbound form, no row created); `element_save` validates + saves inside the existing `@transaction.atomic` + optimistic-token lock; `builder.save_element` builds the form from `FORM_FOR_TYPE` and runs the save sequence.

### 3.2 Fill-blank marker parsing (the one new authoring mechanism)

- **Delimiter:** `{{ ... }}`, with `|` separating alternate accepted answers inside one gap: `The capital of France is {{Paris|paris}}.` This delimiter **does not collide with KaTeX**, which uses `\( … \)` and `\[ … \]`.
- **Math spans are skipped (decided here, not deferred).** Because fill-blank stems may carry KaTeX *and* double braces appear in legitimate LaTeX (`x^{{2}}`, `\frac{{a}}{{b}}`), the parser **first masks out `\(…\)` and `\[…\]` spans** (matching only **balanced** delimiter pairs, non-greedily), scans for `{{…}}` markers only in the unmasked (prose) text, then restores the math spans verbatim. So `{{` inside *balanced* math is **never** a marker, and a blank can sit immediately beside math. **Unbalanced math:** an opening `\(`/`\[` with no matching close matches no balanced span, so it stays in the prose text as literal characters — markers *after* it are still scanned normally (the mask never swallows the stem tail). An author who genuinely wants `{{…}}` treated as math must enclose it in a properly-closed `\(…\)`. The plan encodes the exact two-pass regex (mask balanced math → match `\{\{(.+?)\}\}` non-greedily on the remainder); the *semantics*, including the unbalanced-delimiter rule, are fixed by this spec.
  - **Mask placeholders are parse-time only and cannot be forged by author text.** The masking step is an **in-memory, parse-time** operation that never persists its intermediate tokens. To make restore collision-proof, masking is **positional** — the parser extracts the matched math spans into a list and replaces each with a sentinel built from the already-stripped `U+FFFF` class (the same code point the save path strips from the stem before parsing, §3.3), so no surviving author character can resemble a mask placeholder. Restore re-inserts the captured spans by position. (Either a positional span list or a `U+FFFF`-sentinel placeholder satisfies this; the plan picks one — both are author-unforgeable.)
- **Markers are single-line.** A `{{…}}` marker interior may not contain a newline; the matching regex does not span lines (no `DOTALL`). A `{{` not closed by `}}` on the same logical line is an unterminated marker (rejected below). This is what guarantees the `|`-pieces are newline-free and so safely stored newline-delimited in `Blank.accepted` (§2.2).
- **Marker edge cases (authoring validation, §3.1):** the marker regex is non-greedy `\{\{(.+?)\}\}` (no `DOTALL`). After matching, the interior is split on `|` and each piece is stripped; **non-blank pieces** become accepted answers. Enumerated outcomes (all surface as a `stem` field error when rejected): `{{Paris}}` → accept (1 answer); `{{Paris|paris}}` → accept (2); `{{a|}}` → accept (1 answer, empty piece dropped); `{{}}` → **reject** (zero non-blank pieces); `{{|}}` → **reject** (zero non-blank pieces); a `{{` with no closing `}}` → **reject** as a malformed/unterminated marker (the regex leaves a literal `{{` in the prose, which validation detects and errors on — it is never silently rendered). Adjacent markers `{{a}}{{b}}` with no separating prose → accept (two consecutive inputs).
- **Parse → persist:** on save, `FillBlankQuestionElementForm.clean()`/save parses markers left-to-right. Each marker becomes a `Blank` row in marker order; the marker's interior is split on `|` (blank pieces dropped) and the remaining pieces stored as the blank's newline-delimited `accepted`. The **stored `stem`** has each `{{…}}` replaced by an ordered placeholder token (§3.3 pins the token format + render-time substitution) so rendering knows where to inject inputs and the accepted answers never reach the client in the stem.
- **Re-author on edit:** editing re-parses the stem and **rebuilds** the `Blank` set (delete-all-then-recreate within the atomic save), so the blanks always match the current stem. (No stable per-blank identity is needed in 2b — nothing references a blank across edits since there is no persistence.) **`Blank.order`:** because every existing `Blank` is deleted *before* the recreate, `OrderField`'s per-question scope is empty when the new rows are written, so it restarts from its empty-scope base and numbers them `base, base+1, …` in marker order — `(order, pk)` sort therefore equals marker order. (Same `OrderField` as 2a's `Choice.order`; the plan verifies the empty-scope base against `courses/fields.py` and that the delete+recreate occur in one transaction so no stale row is observed mid-scope.)
- **Escaping a literal `{{`:** out of scope for 2b (no known author need); the plan may add a `\{{` escape, but the default is that `{{` always starts a marker. Documented as a known limitation.

### 3.3 Initial render (security-critical)

`render_element` dispatches each type to its own template under `templates/courses/elements/`. **Each template wraps its inputs in its own isolated `<form method="post">`** (exactly as 2a's `choicequestion.html` does), so each question POSTs only its own fields — `name="answer"` / `name="blank"` are scoped to one form and **never collide** across multiple questions on a page, and a no-JS submit carries only the submitting form's values. **The form `action` is the `check_answer(slug, node_pk, element_pk)` URL**, and like 2a's `ChoiceQuestionElement.render`, each new type's `render()` injects the `element` (and the `slug`/`node_pk` it derives from `element.unit`) into the template context so `{% url %}` can build that action (see the shared `render()` signature in §3.6, which carries `element`):

- **`shorttext.html`** — stem (sanitized HTML, KaTeX) + a single `<input type="text" name="answer">`.
- **`shortnumeric.html`** — stem + `<input type="text" inputmode="decimal" name="answer">` (text, not `number`, so `,` is accepted and locale quirks don't strip it).
- **`fillblank.html`** — the stem rendered with each placeholder token replaced by an `<input type="text" name="blank">` in document order (so the server reads `getlist("blank")` positionally).

**Placeholder token format + render-time substitution (security-critical — the stem is `|safe` HTML).** The stored stem is sanitized HTML containing opaque tokens; the token format is **`￿{n}￿`** — a sentinel wrapping the 1-based blank index in `U+FFFF` (a Unicode non-character). **The collision-proofness is enforced explicitly, NOT assumed from the sanitizer:** `nh3`/`sanitize_html` strips disallowed *markup*, not arbitrary non-character code points in text, so the save path must **explicitly strip all `U+FFFF` from the author's (already-sanitized) stem before inserting tokens** — a dedicated step in `clean()`/save, covered by a test (author pastes a literal `U+FFFF`, save strips it, no forged token survives). After that strip, every `￿{n}￿` in the stored stem is one the parser inserted. Rendering is **not** naive string replacement into a safe string: a template filter (`render_fill_blanks`) **splits** the sanitized stem on the token regex, marks each surrounding HTML segment safe individually, and **joins** with server-built `<input>` markup — so the inputs are the only unescaped insertions and no author text can forge one. The substitution emits one input per token, in document order; each input's no-JS repopulation value is read **defensively** from `submitted_values` — `submitted_values[n-1]` if present, else the empty string (so a `submitted_values` list shorter/longer than the token count never raises `IndexError`; it mirrors the pad/truncate `mark()` applies — §3.4).
- **Token/`Blank` count invariant:** the atomic re-parse (§3.2) guarantees `stem token count == blanks.count() == n` for every stored fill-blank. The render asserts/relies on this; if they ever disagree (only possible via direct DB tampering, never via the editor), the filter renders inputs for the tokens actually present and the marking pads/truncates to `blanks.count()` (§3.4) — degraded but safe, never an exception. Adjacent tokens (from `{{a}}{{b}}`) render as two consecutive inputs with no prose between.

**No-leak invariant (carried from 2a §3.4):** `accepted`, `value`, and `tolerance` are **never** serialized into the initial render, and never for any *other* question on a post-submit no-JS page. Correctness exists only server-side; reveal data appears **only** for the single element matching `feedback_for_pk`.

**Inputs stay editable after feedback (free retry).** On the post-submit re-render the text/numeric/blank inputs remain enabled (no `disabled`/`readonly`) — repopulated with the student's entry and shown beside the ✓/✗ reveal — so the student can edit and resubmit freely, matching 2a's still-active choice radios (formative practice, §1.2).

### 3.4 Marking rules (2b)

`answer` reaches `mark()` already parsed from POST by the per-type `build_answer` (§3.5); `mark()` does no request handling. **`build_answer` is a thin POST reader; all padding/truncation and normalization happen inside `mark()`** (so the positional binding has exactly one owner). Every `mark()` returns a fully-populated `MarkResult` on **both** verdicts: a wrong answer is `MarkResult(correct=False, fraction=0.0, reveal=…)` with the `reveal` still populated, so feedback can always show the accepted answer.

- **`ShortTextQuestionElement.mark(answer: str)`** — split `accepted` on newlines, drop blank lines, `normalize_text` each (with this question's `case_sensitive`). `correct = True, fraction = 1.0` iff `normalize_text(answer, case_sensitive=…)` equals **any** normalized accepted line; otherwise `correct = False, fraction = 0.0`. Empty answer → incorrect (normalizes to `""`, which for an **editor-authored** question the ≥1-non-blank-line validation guarantees is not accepted). `mark()` does not *rely* on that validation for safety: a malformed row with an empty `accepted` (only reachable via direct DB/shell, not the editor) yields an empty accepted set, so **every** answer — including `""` — is simply marked incorrect (benign, never an error). `reveal` = a representative accepted answer (the first non-blank line, or `""` if none) — populated on both verdicts.
- **`ShortNumericQuestionElement.mark(answer: str)`** — `n = parse_number(answer)`; if `n is None` → `correct=False, fraction=0.0`. Else `correct = True, fraction = 1.0` iff `abs(n - value) <= tolerance`, else `correct=False, fraction=0.0`. Comparison is **exact `Decimal` arithmetic**: `parse_number` may return more decimal places than the field's `decimal_places=8`; `mark()` compares the parsed `Decimal` against the stored `value` directly (no quantize/round), so stored-field precision bounds only what an *author* can save, never marking. `reveal` = `{value, tolerance}` — populated on both verdicts.
- **`FillBlankQuestionElement.mark(answer: list[str])`** — `mark()` first normalizes the list to exactly `n_blanks` entries (pad short lists with `""`, **truncate** long ones), pairing each positionally with its `Blank` in `order`. Each entry is text-matched against that blank's `accepted` via `normalize_text`, passing the blank's `case_sensitive` — which in 2b is **always `False`** (the field is reserved; there is no marker syntax or form control to set it — §2.2). `mark()` reads it generically so a future slice can populate it without touching the marking code, but an implementer should not build any per-blank case toggle in 2b. `n_correct = count of matching blanks`; `fraction = n_correct / n_blanks` (a **float**); `correct = (n_correct == n_blanks)`. `reveal` = an ordered list of `{index, correct: bool, accepted: <representative answer>}`, one per blank — a **per-blank summary** (✓/✗ + the accepted answer for missed gaps). The representative `accepted` shown is the blank's **first non-blank accepted piece** (consistent with short-text's "first non-blank line"), not all `|`-alternatives. It deliberately does **not** carry the student's typed entries: those stay visible in the question's own retained/repopulated `<form>` (§3.6, §3.7), so the same `reveal` drives identical feedback on both transports.
- **`fraction` is an inexact float signal.** `n_correct / n_blanks` is ordinary binary float division (`1/3 → 0.333…`); `MarkResult.fraction` stays `float` (the 2a contract). `correct` — never `fraction` — is the formative verdict, so float imprecision never affects 2b behavior. Tests assert `fraction` with `pytest.approx`, never `==`. 2c, which multiplies `fraction × max_marks`, must tolerate a non-terminating float (it is documented here as an approximate score signal, not an exact rational).

**Numeric `reveal` rendering (display, §3.7):** suppress the `± tolerance` suffix entirely when `tolerance == 0` (show just the value); display `value`/`tolerance` via Django's active-locale **decimal-separator** format (so a PL student who typed `3,14` sees `3,14`, an EN student sees `3.14`) rather than the raw `Decimal` repr — but with **digit grouping disabled** (`use_grouping=False` / no thousands separators), so the revealed number is in exactly the form `parse_number` accepts and a student can copy it back verbatim (avoids showing `1 234,5`, which §2.1 would reject as input).

All three are consistent with 2a's empty-answer-is-incorrect and server-is-authority rules.

### 3.5 The marking round-trip — generalizing `check_answer` (touches 2a code)

2a's `check_answer` (`courses/views.py`) hard-codes the choice wire format: `request.POST.getlist("choice")` → coerce ints → validate against `question.choices` → `set[int]`. 2b generalizes this so `check_answer` is **type-agnostic**:

- **A per-type `build_answer(self, post) -> answer` method** is added to each `QuestionElement` subclass, owning the POST→answer parsing and any per-type validation that 2a did inline:
  - `ChoiceQuestionElement.build_answer` = the existing logic (getlist `choice`, int-coerce, **validate against own `choices`**, return `set[int]`) — moved out of the view, behavior unchanged.
  - `ShortTextQuestionElement.build_answer` / `ShortNumericQuestionElement.build_answer` = `post.get("answer", "")` (a raw string; parsing/normalization happens in `mark()`).
  - `FillBlankQuestionElement.build_answer` = `post.getlist("blank")` (positional list of raw strings).
- **`check_answer` becomes:** resolve unit + access + element scoped to unit (unchanged IDOR/`require_lesson` discipline); `question = element.content_object`; `answer = question.build_answer(request.POST)`; `result = question.mark(answer)`; render feedback. **Nothing persisted.** The view no longer knows any per-type wire shape. The 2a `check_answer` tests are preserved (choice behavior is identical); the foreign/forged-id drop now lives in `ChoiceQuestionElement.build_answer` and its test moves with it.
- **`content_object` type gate is already broad in 2a — no edit needed.** 2a's `check_answer` already gates on `isinstance(question, QuestionElement)` (the abstract base), not on `ChoiceQuestionElement`, so all four (2a + 2b ×3) types are **already** answerable through the existing gate; the only new wiring is the per-type `build_answer` dispatch above (and `mark()`, which is abstract on the base). The plan verifies the shipped gate is the `QuestionElement` form and keeps it; it must **not** be narrowed. A non-question element still 404s.

### 3.6 Two transports (progressive enhancement) — reused, plus value repopulation

Both 2a transports are reused with **no change to `question.js`** (it serializes the whole form and swaps the `_question_feedback.html` partial — independent of field types):

- **JS path:** intercept submit → `fetch` POST with `X-CSRFToken` → swap the feedback fragment into the question container, re-run KaTeX. Per-question, no reload.
- **No-JS path:** full POST to `check_answer`, which re-renders the **whole lesson unit** via `build_lesson_context`. 2a threads `selected_ids` to repopulate choice inputs; 2b adds a parallel **`submitted_values`** payload (the raw typed strings — a scalar for short-text/numeric, the positional list for fill-blanks) so the answered question's inputs repopulate on the re-render.

  **Three concrete edits are required (this is not a no-op beyond "forwarding") — the plan must do all three or a `render()` call raises `TypeError`:**
  1. **`render_element` gains the `submitted_values` kwarg and forwards it.** The shipped signature is `render_element(element, feedback_for_pk=None, selected_ids=frozenset(), mark_result=None)` and it already forwards `element=element` plus those three to `obj.render()`. 2b **adds** `submitted_values` to that set: `render_element(element, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)`, forwarding **all** of `element`, `feedback_for_pk`, `selected_ids`, `submitted_values`, `mark_result` to `obj.render()` on every `QuestionElement` (the `HtmlElement.render` forwarding precedent). `submitted_values` is **added to**, never replaces, the existing forwarded kwargs.
  2. **The `lesson_unit.html` tag call gains the argument:** `{% render_element el feedback_for_pk=… selected_ids=… submitted_values=… mark_result=… %}`. (Other call sites — e.g. the editor preview — keep the bare call; the kwarg defaults to `None`.)
  3. **`build_lesson_context` seeds the default; `check_answer` overrides it.** Mirroring 2a's existing pattern (`build_lesson_context` sets `feedback_for_pk=None, selected_ids=frozenset(), mark_result=None` in the base context, and `check_answer` overrides them on submit), `build_lesson_context` **also seeds `submitted_values=None`** so every question in the no-JS re-render has the key defined (no template lookup miss for the non-answered questions); `check_answer` overrides `submitted_values` only for the answered question on the post-submit path.

  **One shared `render()` signature for all four question types (the cross-type contract).** Because `render_element` forwards a *fixed* kwarg set — which **already includes `element`** — to every `QuestionElement`, all four overrides MUST accept the same signature or the call `TypeError`s. The shipped 2a `ChoiceQuestionElement.render` is `render(self, *, element=None, feedback_for_pk=None, selected_ids=frozenset(), mark_result=None)`; the unified 2b signature simply **adds `submitted_values`**: `render(self, *, element=None, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)`. `ChoiceQuestionElement.render` **gains `submitted_values`** (and ignores it — choices repopulate from `selected_ids`; it keeps injecting its `choices` queryset + `element`/`slug`/`node_pk` into context); the three new types **accept `selected_ids`** (and ignore it — they repopulate from `submitted_values`) and **must inject the same `element`/`slug`/`node_pk` form-action context** (§3.3).

  **Repopulation is gated on identity (critical — the payload is forwarded to *every* question).** `build_lesson_context` puts a **single** `submitted_values`/`selected_ids`/`mark_result` in the lesson context, and the template forwards that same value to **every** element's `render()`. So each `render()` (and its template) must apply `submitted_values`/`selected_ids`/`mark_result`/feedback **only when `self.pk == feedback_for_pk`** — exactly as 2a already gates `selected_ids`/feedback. Otherwise the one answered question's typed values would bleed into every other question's inputs. Every non-answered question re-renders fresh and feedback-free; only the `feedback_for_pk` match repopulates + shows feedback.

### 3.7 Feedback partial — generalizing 2a's choice-specific partial (touches 2a code)

The shipped 2a `_question_feedback.html` is **choice-specific**: it iterates `{% for c in choices %}` and the JS-path `check_answer` renders it with the hardcoded context `{"el": question, "mark_result": result, "choices": choices}`. 2b must remove that hardcoding so the one partial serves all four types without forking the JS/no-JS surfaces.

- **A per-type `feedback_context(self, mark_result) -> dict` method is the single source of the partial's context (replaces the choice-hardcoded dict).** The shipped 2a JS-fragment branch of `check_answer` renders `_question_feedback.html` **directly** with a hardcoded `{"el": question, "mark_result": result, "choices": choices}` dict — it does **not** call `question.render()` (which renders the whole *question-form* template `choicequestion.html`, not the feedback partial). So "get the context from `render()`" is wrong: 2b adds a dedicated **`feedback_context(self, mark_result)`** method on each `QuestionElement` subclass that returns exactly the dict the partial needs — at minimum `{"el": self, "mark_result": mark_result, "reveal_template": <this type's include path>}` plus any per-type extras (`ChoiceQuestionElement.feedback_context` adds its `choices` queryset; the new types add nothing beyond `reveal`, which already rides on `mark_result`). The `check_answer` JS branch becomes `render_to_string("…/_question_feedback.html", question.feedback_context(result), request)` — generic, no hardcoded `choices`.
- **The partial delegates to a per-type reveal include selected by `reveal_template` (not template-side string munging).** Django templates cannot call `__class__.__name__.lower().replace(...)` (no arg-taking method calls in DTL), so `feedback_context` supplies a **`reveal_template`** string (e.g. choice → `"courses/elements/_reveal_choice.html"`, short-text → `_reveal_shorttext.html`, etc.). `_question_feedback.html` keeps the shared chrome — the verdict ("Correct"/"Incorrect", i18n; ✓/✗ glyphs are decorative CSS, not load-bearing strings) and the explanation — then does **`{% include reveal_template %}`**. The four includes: `_reveal_choice.html` (the existing choice loop, extracted), `_reveal_shorttext.html` ("Correct answer: `<accepted>`"), `_reveal_shortnumeric.html` ("Expected: `<value>`", with `± <tolerance>` suppressed when `tolerance==0`, no-grouping locale format per §3.4), `_reveal_fillblank.html` (the ordered per-blank ✓/✗ + accepted-for-missed list). The `reveal` payload shape is the contract each include consumes (§3.4).
- **Both transports feed the *same* `feedback_context`, so they cannot drift.** No-JS path: the answered question's `render()` (the form template) `{% include %}`s `_question_feedback.html` with the **same** `feedback_context(mark_result)` dict (its `render()` calls `feedback_context` when `feedback_for_pk == self.pk`). JS path: the view renders the partial standalone with `feedback_context(result)`. One method → one dict → one partial on both paths. (The 2a choice feedback output is unchanged — its loop moves into `_reveal_choice.html` and its context into `ChoiceQuestionElement.feedback_context`.)
- **No student-entry data in the fragment (transport symmetry).** The per-blank reveal is a *summary* from `reveal`; it never recolors the form inputs and never needs the student's typed values. The student's entries stay visible because each transport keeps the question's own `<form>` populated — retained in-DOM on the JS path (the fragment swaps into the feedback slot, not over the form), repopulated from `submitted_values` on the no-JS path. Both transports render the **same** partial from the **same** `reveal`, so JS and no-JS feedback cannot drift (the 2a guarantee).

### 3.8 Lesson view wiring & progress (auto-covered by 2a)

- **Shared `question_ct_ids` (introduced here, not "extend a set").** In 2a there is **no** named set — `build_lesson_context` builds `question_ct_ids` inline as a literal `{get_for_model(ChoiceQuestionElement).id}`. 2b replaces that inline literal with a **union over all four question content-types** (derived from an explicit 4-model list, or `QuestionElement.__subclasses__()`), defined once and reused by **`has_questions`** (the `question.js` gate). The plan picks the single construction site and the explicit-list-vs-`__subclasses__` choice.
- **KaTeX gate — the prefetch and scan must branch by type (not a literal "OR in the text").** The shipped `build_lesson_context` does two **choice-specific** things 2b must generalize: (1) it collects `questions = [el … if isinstance(el.content_object, ChoiceQuestionElement)]` and `prefetch_related_objects(questions, "choices")`; (2) the math scan reads each question's `stem` **and** `q.choices.all()` text. For 2b: **prefetch per type** — fill-blank questions need **`"blanks"`** prefetched (a *different* relation), while short-text/numeric have **no** child relation (prefetch nothing). The math scan reads `stem` for all three new types, **plus `accepted` from `blanks`** for fill-blank only (never `.choices`, which the new types don't have). A literal "OR the new text into the existing `q.choices` scan" would `AttributeError`/N+1 on the new types — so the plan generalizes the collect+prefetch+scan to dispatch on type (e.g. a per-type "math source text" helper).
- **Progress:** each new question counts toward `seen_element_ids` like any element. Answering is **not** required for completion. `UnitProgress` contract unchanged.

---

## 4. Security & validation invariants (carried from 2a, extended)

- **No answer leakage:** `accepted` / `value` / `tolerance` never reach a render except via `reveal` for the single `feedback_for_pk` element. Tested two ways, mirroring 2a: (a) the **initial** lesson render contains no accepted-answer/value signal for any question; (b) on a post-submit page, reveal appears for the answered question **only** — every other question (of any type) is still clean.
- **Server is the marking authority:** `mark()` runs only server-side; the client submits raw input, never scores or correctness.
- **Forged / malformed input is inert:** a non-numeric short-numeric answer, an over-long string, extra/missing `blank` entries — all parse to "incorrect", never error-leak. `build_answer` is a thin POST reader (fill-blanks returns the raw `getlist("blank")`, possibly `[]` when the key is absent); **`mark()` normalizes that list to `n_blanks` by padding with `""` / truncating** (§3.4) — exactly one owner of the positional alignment. Foreign choice ids stay dropped in `ChoiceQuestionElement.build_answer`.
- **IDOR scoping & `require_lesson`:** `check_answer` reuses 2a's `get_node_or_404` + `can_access_course` + unit-scoped element fetch + lesson-only gate (a submit to a quiz unit 404s). Unchanged.
- **CSRF:** fetch path sends `X-CSRFToken`; no-JS path uses `{% csrf_token %}`. No `csrf_exempt`.
- **Authoring validation:** short-text ≥ 1 accepted answer; numeric `value` required + `tolerance ≥ 0`; fill-blank ≥ 1 well-formed marker each yielding ≥ 1 accepted answer. Enforced in form/`clean()` and consistent with `mark()`'s assumptions.
- **i18n:** all new strings wrapped (`gettext` / `{% trans %}`) + Polish translations, per the established gate (`compilemessages -l pl` is a DoD gate, so every new string needs a `.po` entry). The new author- and student-facing strings to translate include, at minimum: the three add-card titles ("Short text", "Short numeric", "Fill in the blanks"); the `accepted` textarea help ("One accepted answer per line") and label; the fill-blank stem help describing the `{{answer|alternate}}` marker syntax; `value`/`tolerance` field labels; the `case_sensitive` label; the marker/validation error messages (empty marker `{{}}`, unterminated `{{`, no accepted answers, and **no markers at all** — the minimum is **≥ 1** blank, so a single-blank fill-blank is valid; there is deliberately no ≥2-blank rule, unlike 2a's ≥2-choice); and the feedback strings ("Correct answer:", "Expected:"). The plan enumerates the full list against the final templates/forms.

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
- **Fill-blank token security:** authoring a stem containing a literal `U+FFFF` (and/or a literal `￿{1}￿`-shaped string) — the save strips `U+FFFF` so no forged placeholder survives, and the rendered fill-blank emits exactly `blanks.count()` inputs with no injected/unescaped markup from author text (the `render_fill_blanks` split/safe-join is the only `<input>` source).
- **Playwright e2e (`-m e2e`):** for **each** of the three types — author it in a lesson → as a student submit wrong (✗ + reveal + explanation), retry correct (✓) — in **both** the JS fragment-swap and no-JS full-POST paths (fill-blank e2e exercises a multi-gap question and asserts per-blank highlighting + input repopulation on the no-JS path).
- **DoD gate:** default `pytest -q` (e2e excluded) + e2e green; `ruff check .` + `ruff format --check .`; `makemigrations --check` (one new migration); `manage.py check`; collectstatic; `compilemessages -l pl`.

---

## 6. Files (anticipated; the plan will finalize)

- `courses/models.py` — `ShortTextQuestionElement`, `ShortNumericQuestionElement`, `FillBlankQuestionElement`, `Blank`; each with `mark()`, `build_answer()`, `feedback_context(self, mark_result)` (the per-type feedback-partial dict incl. `reveal_template`, §3.7), and the **shared** `render(self, *, element=None, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)` override (gated on `self.pk == feedback_for_pk` for repopulation/feedback, §3.6) that injects the type's repopulation payload + `element`/`slug`/`node_pk` form-action context (§3.3); `ChoiceQuestionElement.build_answer()` + `feedback_context()` (logic/`choices` moved from the view) and its `render()` widened to the shared signature; `ELEMENT_MODELS += [3 new]`.
- `courses/marking.py` — `normalize_text`, `parse_number` (helpers); `MarkResult` unchanged.
- `courses/migrations/00XX_*` — one new migration (3 tables + `Blank` + `Element.content_type` `AlterField`).
- `courses/element_forms.py` — `ShortTextQuestionElementForm`, `ShortNumericQuestionElementForm`, `FillBlankQuestionElementForm` (incl. marker parse/validate + `Blank` rebuild); `FORM_FOR_TYPE += {shorttext, shortnumeric, fillblank}`.
- `courses/views_manage.py` — three keys added to the `element_add`/`element_save` allowlist tuples (no add-key→type_key translation needed — 1:1 mapping).
- `courses/views.py` — `check_answer` generalized to `question.build_answer(...)` + `question.feedback_context(result)` for the JS-fragment render (no hardcoded `choices`, §3.7); the `isinstance(question, QuestionElement)` gate is **already** broad in 2a — keep, don't narrow (§3.5); `build_lesson_context` gains the `submitted_values=None` default seed, the union `question_ct_ids` for `has_questions`, and a **per-type prefetch + math-scan** (fill-blank → prefetch `blanks` and scan `stem`+`accepted`; short-text/numeric → no child prefetch, scan `stem`; never `.choices` on the new types — §3.8); `lesson_unit.html` `render_element` call gains `submitted_values=`.
- `courses/templatetags/courses_extras.py` — `render_element` signature gains `submitted_values` and forwards the full `{feedback_for_pk, selected_ids, submitted_values, mark_result}` set (§3.6); a `render_fill_blanks` filter that splits the sanitized stem on the `￿{n}￿` token and safe-joins server-built `<input>`s (§3.3).
- `templates/courses/elements/shorttext.html`, `shortnumeric.html`, `fillblank.html` — the three question forms, each its own isolated `<form>` (no leak).
- `templates/courses/elements/_question_feedback.html` — shared chrome (verdict + explanation) + per-type reveal `{% include %}`; new `_reveal_choice.html` (extracted 2a loop), `_reveal_shorttext.html`, `_reveal_shortnumeric.html`, `_reveal_fillblank.html`.
- `templates/courses/manage/_edit_shorttext.html`, `_edit_shortnumeric.html`, `_edit_fillblank.html` — editor partials; three add-menu cards.
- `courses/static/courses/js/question.js` — **unchanged** (whole-form serialize + partial swap already type-agnostic).
- `courses/static/courses/css/...` — minimal styles for text/numeric inputs + inline blank inputs + per-blank feedback (token-driven).
- `locale/pl/LC_MESSAGES/django.po` — Polish strings.
- `tests/...` — unit + authoring + no-leak + e2e per §5.
