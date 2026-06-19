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
- **`parse_number(s) -> Decimal | None`** — strip whitespace (including internal spaces used as thousands separators), accept a single `,` **or** `.` as the decimal separator (normalize `,`→`.`), return a `Decimal`, or `None` if the string is not a single well-formed number. Empty / malformed → `None` (marked incorrect). Uses `Decimal` to avoid binary-float tolerance drift.

### 2.2 The three concrete types

All extend the existing abstract `QuestionElement(ElementBase)` (which provides `stem`, `explanation`, sanitized on save, and the abstract `mark()`), so each owns its own table + GFK content-type, per the established element pattern.

```
ShortTextQuestionElement(QuestionElement)
  accepted        TextField                       # newline-delimited accepted answers (≥1 non-blank line)
  case_sensitive  BooleanField(default=False)
  elements        GenericRelation(Element)        # join-row back-ref (cascade delete)
  def mark(self, answer: str) -> MarkResult

ShortNumericQuestionElement(QuestionElement)
  value           DecimalField(max_digits=…, decimal_places=…)
  tolerance       DecimalField(default=0)         # absolute, ≥ 0 (validators)
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

- **Delimiter:** `{{ ... }}`, with `|` separating alternate accepted answers inside one gap: `The capital of France is {{Paris|paris}}.` This delimiter **does not collide with KaTeX**, which uses `\( … \)` and `\[ … \]`; the parser matches `{{`…`}}` literally. (A literal double-brace inside LaTeX such as `x^{{2}}` is theoretically ambiguous; the spec accepts this as a known edge — authors writing math put it inside `\( … \)`, and the plan's parser may optionally skip `\(…\)`/`\[…\]` spans. The plan pins the exact regex and whether math spans are skipped.)
- **Parse → persist:** on save, `FillBlankQuestionElementForm.clean()`/save parses markers left-to-right. Each marker becomes a `Blank` row in marker order (`order` autonumbered by `OrderField`, scoped per question — same mechanism as 2a's `Choice.order`); the marker's interior is split on `|`, blank pieces dropped, and the remaining pieces stored as the blank's newline-delimited `accepted`. The **stored `stem`** has each `{{…}}` replaced by an ordered placeholder token (e.g. `[[blank:1]]`) so rendering knows where to inject inputs and the accepted answers never reach the client in the stem.
- **Re-author on edit:** editing re-parses the stem and **rebuilds** the `Blank` set (delete-and-recreate within the atomic save), so the blanks always match the current stem. (No stable per-blank identity is needed in 2b — nothing references a blank across edits since there is no persistence.)
- **Escaping a literal `{{`:** out of scope for 2b (no known author need); the plan may add a `\{{` escape, but the default is that `{{` always starts a marker. Documented as a known limitation.

### 3.3 Initial render (security-critical)

`render_element` dispatches each type to its own template under `templates/courses/elements/`:

- **`shorttext.html`** — stem (sanitized HTML, KaTeX) + a single `<input type="text" name="answer">`.
- **`shortnumeric.html`** — stem + `<input type="text" inputmode="decimal" name="answer">` (text, not `number`, so `,` is accepted and locale quirks don't strip it).
- **`fillblank.html`** — the stem rendered with each `[[blank:n]]` placeholder replaced by `<input type="text" name="blank" >` in order (so the server reads `getlist("blank")` positionally). Stem text around placeholders is the sanitized HTML / KaTeX.

**No-leak invariant (carried from 2a §3.4):** `accepted`, `value`, and `tolerance` are **never** serialized into the initial render, and never for any *other* question on a post-submit no-JS page. Correctness exists only server-side; reveal data appears **only** for the single element matching `feedback_for_pk`.

### 3.4 Marking rules (2b)

`answer` reaches `mark()` already parsed from POST by the per-type `build_answer` (§4.1); `mark()` does no request handling.

- **`ShortTextQuestionElement.mark(answer: str)`** — `correct`/`fraction=1.0` iff `normalize_text(answer, case_sensitive=…)` equals the normalized form of **any** accepted line; else `0.0`. Empty answer → incorrect (normalizes to `""`, which the ≥1-non-blank-line validation guarantees is not an accepted value). `reveal` = a representative accepted answer (the first non-blank line) to display.
- **`ShortNumericQuestionElement.mark(answer: str)`** — `n = parse_number(answer)`; if `n is None` → incorrect. Else `correct`/`fraction=1.0` iff `abs(n - value) <= tolerance` (Decimal arithmetic); else `0.0`. `reveal` = `{value, tolerance}` for display ("expected 3.14 ± 0.01").
- **`FillBlankQuestionElement.mark(answer: list[str])`** — `answer` is positional, one entry per blank in `order` (missing/short list padded with `""`). Each entry is text-matched against its blank's `accepted` via `normalize_text` (per-blank `case_sensitive`). `n_correct = count of matching blanks`; `fraction = n_correct / n_blanks`; `correct = (n_correct == n_blanks)`. `reveal` = an ordered list of `{index, correct: bool, accepted: <representative answer>}` so the feedback template highlights each input and reveals missed gaps.

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
- **No-JS path:** full POST to `check_answer`, which re-renders the **whole lesson unit** via `build_lesson_context`. 2a threads `selected_ids` to repopulate choice inputs; 2b adds a parallel **`submitted_values`** payload (the raw typed strings — a scalar for short-text/numeric, the positional list for fill-blanks) so the answered question's inputs repopulate on the re-render. Like 2a's `selected_ids`/`feedback_for_pk`/`mark_result`, these are injected only for the answered question via its `render(self, *, feedback_for_pk=None, submitted_values=None, mark_result=None)` override (mirroring 2a's `ChoiceQuestionElement.render`), and `render_element` forwards the kwarg (the established `HtmlElement.render` forwarding precedent). Every other question re-renders fresh and feedback-free (identity gate on `element.pk == feedback_for_pk`).

### 3.7 Feedback partial

`_question_feedback.html` is extended (not forked) to render each type's `reveal`:

- short-text → "Correct answer: `<accepted>`"; short-numeric → "Expected: `<value> ± <tolerance>`"; fill-blank → the per-blank list (each gap ✓/✗ with the accepted answer for missed gaps).
- The verdict ("Correct"/"Incorrect", i18n) and explanation rendering are shared with 2a. The ✓/✗ glyphs remain decorative CSS, not load-bearing strings. Both transports render this **same** partial, so JS and no-JS feedback cannot drift (the 2a guarantee).

### 3.8 Lesson view wiring & progress (auto-covered by 2a)

- **`has_questions`** is a content-type identity check over the question content-type set; 2a wrote it to "extend automatically" — adding the three new content-types to that set is all that's needed to gate `question.js`.
- **KaTeX gate:** 2a's per-element stem/choice text scan (`has_math_delimiters` over question text) extends to the new stems (short-text/numeric/fill-blank stems) and to fill-blank `accepted`/stem; the plan ORs the new types' text into the existing scan.
- **Progress:** each new question counts toward `seen_element_ids` like any element. Answering is **not** required for completion. `UnitProgress` contract unchanged.

---

## 4. Security & validation invariants (carried from 2a, extended)

- **No answer leakage:** `accepted` / `value` / `tolerance` never reach a render except via `reveal` for the single `feedback_for_pk` element. Tested two ways, mirroring 2a: (a) the **initial** lesson render contains no accepted-answer/value signal for any question; (b) on a post-submit page, reveal appears for the answered question **only** — every other question (of any type) is still clean.
- **Server is the marking authority:** `mark()` runs only server-side; the client submits raw input, never scores or correctness.
- **Forged / malformed input is inert:** a non-numeric short-numeric answer, an over-long string, extra/missing `blank` entries — all parse to "incorrect", never error-leak. `build_answer` for fill-blanks pads/truncates to the blank count; foreign choice ids stay dropped in `ChoiceQuestionElement.build_answer`.
- **IDOR scoping & `require_lesson`:** `check_answer` reuses 2a's `get_node_or_404` + `can_access_course` + unit-scoped element fetch + lesson-only gate (a submit to a quiz unit 404s). Unchanged.
- **CSRF:** fetch path sends `X-CSRFToken`; no-JS path uses `{% csrf_token %}`. No `csrf_exempt`.
- **Authoring validation:** short-text ≥ 1 accepted answer; numeric `value` required + `tolerance ≥ 0`; fill-blank ≥ 1 well-formed marker each yielding ≥ 1 accepted answer. Enforced in form/`clean()` and consistent with `mark()`'s assumptions.
- **i18n:** all new strings wrapped (`gettext` / `{% trans %}`) + Polish translations, per the established gate.

---

## 5. Testing & Definition of Done

- **Unit (`marking.py` + `mark()`):**
  - `normalize_text` (trim, internal-whitespace collapse, casefold on/off) and `parse_number` (`3,14` == `3.14`; spaces; empty/malformed → `None`).
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

- `courses/models.py` — `ShortTextQuestionElement`, `ShortNumericQuestionElement`, `FillBlankQuestionElement`, `Blank`; each with `mark()`, `build_answer()`, and a `render(self, *, feedback_for_pk=None, submitted_values=None, mark_result=None)` override; `ChoiceQuestionElement.build_answer()` (logic moved from the view); `ELEMENT_MODELS += [3 new]`.
- `courses/marking.py` — `normalize_text`, `parse_number` (helpers); `MarkResult` unchanged.
- `courses/migrations/00XX_*` — one new migration (3 tables + `Blank` + `Element.content_type` `AlterField`).
- `courses/element_forms.py` — `ShortTextQuestionElementForm`, `ShortNumericQuestionElementForm`, `FillBlankQuestionElementForm` (incl. marker parse/validate + `Blank` rebuild); `FORM_FOR_TYPE += {shorttext, shortnumeric, fillblank}`.
- `courses/views_manage.py` — three keys added to the `element_add`/`element_save` allowlist tuples (no add-key→type_key translation needed — 1:1 mapping).
- `courses/views.py` — `check_answer` generalized to `question.build_answer(...)` + broadened `QuestionElement` type gate; `build_lesson_context` adds `submitted_values`; `has_questions` + KaTeX scan extended to the new content-types.
- `courses/templatetags/courses_extras.py` — `render_element` forwards `submitted_values` (alongside 2a's `feedback_for_pk`/`mark_result`).
- `templates/courses/elements/shorttext.html`, `shortnumeric.html`, `fillblank.html` — the three question forms (no leak).
- `templates/courses/elements/_question_feedback.html` — extended for the three `reveal` shapes.
- `templates/courses/manage/_edit_shorttext.html`, `_edit_shortnumeric.html`, `_edit_fillblank.html` — editor partials; three add-menu cards.
- `courses/static/courses/js/question.js` — **unchanged** (whole-form serialize + partial swap already type-agnostic).
- `courses/static/courses/css/...` — minimal styles for text/numeric inputs + inline blank inputs + per-blank feedback (token-driven).
- `locale/pl/LC_MESSAGES/django.po` — Polish strings.
- `tests/...` — unit + authoring + no-leak + e2e per §5.
