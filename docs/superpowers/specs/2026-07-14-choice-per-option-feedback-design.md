# Per-choice feedback for ChoiceQuestionElement

## Purpose

Authors of multiple-choice questions want to attach a short, targeted feedback
nudge to individual choices — e.g. "Are you sure? Re-read the exponent rule" on a
tempting distractor. Today `ChoiceQuestionElement` supports only a whole-question
`explanation`; there is no way to respond to *which* wrong option a student picked.

This ports the legacy Demo-Course `.mult_feedback_incorrect` widget (see
`C:/Users/krzys/Documents/teaching/LAL/html/_template.html`, "multiple choice, with
feedback") into libli as an **enhancement to the existing `ChoiceQuestionElement`**,
not a new element type. Both single- and multiple-choice questions gain the
capability for free.

**Scope decision (locked during brainstorming):** the only genuinely new capability
in the legacy choice-widget family is *per-choice feedback*. The other legacy
variants are already covered — True/false grid and one-choice-in-line by the new
`ChoiceGridQuestionElement` (Matrix), and plain single/multi MCQ by
`ChoiceQuestionElement` itself. So this work adds one field to the `Choice` model and
its presentation, and touches nothing else in the element catalog.

**Non-goals:**

- No new element type, palette card, form class, transfer key, or `ELEMENT_MODELS`
  entry.
- No change to marking. Scoring stays exact-set-equality; feedback is purely
  presentational and never affects `correct`/`fraction`.
- The legacy multi-line, per-line variant (`.multi_ans` / `.multi_feedback_ans`) is
  out of scope — its per-*group* feedback is a different shape and not requested.

## Display rule (locked)

A choice's feedback nudge is shown **only when the student selected that choice, that
choice is a distractor (not correct), AND the overall submission was wrong**. For
single-choice this is simply "picked a wrong option." For **multiple-choice**, a student
can be overall-wrong while having selected an annotated *correct* choice — that correct
choice does **not** nudge; only the selected distractors do. This keeps the rule and its
rationale consistent: authors annotate distractors, and correct picks stay quiet (the ✓
reveal already handles them). Matches the legacy `.mult_feedback_incorrect` "are you sure
about option 2?" nudge. (The rejected "any selected choice" option would have surfaced
correct-pick affirmations; it was declined during brainstorming.)

## Architecture / components

### 1. Data model — `courses/models.py`

Add one field to the existing `Choice` model:

```python
feedback = models.CharField(max_length=500, blank=True, default="")
```

`default=""` is **required**, not cosmetic: adding a non-nullable `CharField` to the
already-populated `Choice` table with no default makes `makemigrations` prompt
interactively for a one-off default, which breaks the non-interactive
`makemigrations --check` DoD. `default=""` also matches repo convention for fields added
to existing models (`tab_id`, `external_id`, `review_feedback` all use
`blank=True, default=""`). The migration is then additive and dependency-free (no data
migration).

Render semantics mirror `Choice.text`: plain text plus KaTeX delimiters, **never
sanitised** (stored raw, auto-escaped by the Django template on render so KaTeX
delimiters survive for client-side KaTeX). Blank by default → existing and un-annotated
choices carry an empty string. (Authoring parity is intentionally *not* full — the editor
input is a plain field without the `∑` math-insert affordance; see §4.)

### 2. Marking — unchanged, nudged pks carried on the result

`ChoiceQuestionElement.mark(answer)` (`models.py`) keeps exact set-equality for
`correct`/`fraction`. `mark()` is the single place with access to the student's
selected set (`answer`) on **every** render path (the lesson JS-fragment
`feedback_context`, the lesson no-JS re-render, and the quiz/results paths do not all
carry the selection), so the nudge signal must originate here.

Add one optional field to `MarkResult` (`courses/marking.py`):

```python
notes: frozenset = frozenset()   # choice pks to nudge; type-opaque, per-type
```

Deliberately a **`frozenset` of pks**, not a `dict` of pk→text — the same type family
as the existing `reveal`. This keeps `MarkResult` an immutable, hashable `frozen=True`
dataclass (a `dict` field would make `hash(instance)` raise `TypeError`); it needs no
`field()` / `default_factory` (a bare `frozenset()` default is safe, exactly like
`reveal`, so no new `from dataclasses import field` import); and the actual text is read
from `choice.feedback` at render time, so the template needs only a membership test plus
attribute access (see §3), never a dict-value-by-key lookup. Every other question type
leaves `notes` empty. `MarkResult.reveal` is **unchanged**, so the existing ✓ logic and
all current consumers/tests keep working. Extend the `MarkResult` docstring with a
one-line description of `notes` (a per-type choice-pk set to nudge), mirroring the
existing `reveal` sentence, so the second type-opaque payload is documented.

`ChoiceQuestionElement.mark()` populates `notes` **only when the answer is wrong**, with
the pks of the **selected distractor** choices (selected, has feedback, and *not*
correct — see the Display rule) computed from a **single** `self.choices.all()` pass
(also used to derive the correct set, so no second query is issued — choices are already
prefetched on the quiz/results builders):

```python
choices = list(self.choices.all())
correct_set = frozenset(c.pk for c in choices if c.is_correct)
is_correct = set(answer) == set(correct_set)
notes = (
    frozenset(
        c.pk for c in choices
        if c.pk in answer and c.feedback and not c.is_correct
    )
    if not is_correct else frozenset()
)
return MarkResult(correct=is_correct, fraction=..., reveal=correct_set, notes=notes)
```

The `not c.is_correct` clause is load-bearing for multiple-choice: without it, a selected
annotated *correct* choice in an overall-wrong submission would nudge, contradicting the
Display rule.

**Quiz reload / no-JS carry (load-bearing):** `_stored_result` (`courses/views.py`)
reconstructs a `MarkResult` from the persisted `QuestionResponse` and currently keeps
only `.reveal`, discarding the rest. It already calls `question.mark(...)` to recover
`reveal`, so it must carry `notes` from that same call:
`m = question.mark(...); return MarkResult(correct=..., fraction=..., reveal=m.reveal, notes=m.notes)`.
Without this, nudges would appear on the live quiz submit but vanish on page reload/
resume and on the no-JS re-render (which both route through `_stored_result` →
`build_quiz_context`). `_stored_result` is therefore an explicit touch point, pinned by
a reload test (§Testing).

### 3. Reveal template — `templates/courses/elements/_reveal_choice.html`

Currently lists each choice and ticks the ones in `mark_result.reveal`. Add, inside the
existing per-choice `<li>` and below the choice-text span: when `c.pk in
mark_result.notes`, render the choice's own feedback in a dedicated element:

```django
{% if c.pk in mark_result.notes %}
  <p class="question__nudge">{{ c.feedback }}</p>
{% endif %}
```

Only a membership test (`c.pk in mark_result.notes`) and attribute access
(`c.feedback`) are used — both native Django-template operations, so **no custom
template filter is introduced** (the repo's only `get_item`-style filter is
manage-scoped and not loadable in this student-facing template). `c.feedback` is
auto-escaped on render (KaTeX delimiters survive for the client). The correct-✓ block is
untouched. Because `notes` is non-empty only on a wrong submission and only for selected
annotated choices, the membership test is the sole guard needed.

**Styling (per repo convention "every view ships styled"):** add a `.question__nudge`
rule to the courses CSS — a muted, indented aside, visually subordinate to the choice
and distinct from the ✓ reveal. It renders on the lesson, quiz, and results reveal — all
three go through this one template, so markup/placement are identical across them. Verify
light + dark with a screenshot before shipping.

### 4. Editor — `templates/courses/manage/editor/_edit_choicequestion.html`

Add an optional per-choice feedback input to each `.choice-row`, below the choice text.
Add `"feedback"` to the `ChoiceFormSet` field list (`inlineformset_factory(...,
fields=[...])` in `courses/element_forms.py`), and give it a small **`forms.Textarea`**
widget (`widgets={"feedback": forms.Textarea(attrs={"rows": 2})}` on the factory) — the
field is `max_length=500`, so a single-line `TextInput` (the default auto widget) would be
cramped. A `Textarea` still emits `id_choices-N-feedback`, so the clone-renumber and
`id_for_label` wiring below are unaffected.

**Render the field via the auto widget `{{ f.feedback }}`** (not a hand-built
`<input name="{{ f.feedback.html_name }}">` like `is_correct`) — the auto widget emits
`id_choices-N-feedback`, which is exactly what (a) the "Add option" clone regex renumbers
and (b) a `<label for="{{ f.feedback.id_for_label }}">Feedback (optional)</label>`
associates with (use `{{ f.feedback.id_for_label }}`, **not** a hardcoded
`id_choices-N-feedback` — there is no `N` variable inside the `{% for f in formset %}`
loop, and the bound-field property tracks the widget through the clone-renumber).
Mirroring the hand-built `is_correct` pattern instead would drop the `id` and break both. The `addChoiceRow` JS (`editor.js`) renumbers every `[name]`/`[id]`/`[for]` on the
cloned row via a generic `([-_])\d+([-_])` regex, so the `{{ f.feedback }}` widget is
renumbered correctly with **no JS change** — a round-trip test (§Testing) confirms it.

The feedback input is a **plain field** — it deliberately does *not* get the `∑`
math-insert trigger / live `math-preview` affordance the choice-text cell has. KaTeX in
feedback is typed by hand (an accepted authoring limitation); render-side KaTeX still
works (§1, §6). No new form class; `ChoiceQuestionElementForm` is unchanged.

### 5. Transfer (export / import) — `courses/transfer/`

- **Export** `_ser_choice` (`export.py`): emit `"feedback": c.feedback` in each choice
  dict.
- **Validate** `_val_choice` (`payloads.py`): this function has **two** `_exact_keys`
  calls — the outer one on `data` (`Q_KEYS + ["multiple", "choices"]`, ~line 295) and the
  per-choice one inside `for c in choices:` (~line 306). The shim targets each choice, so
  it goes **inside that loop, immediately before the per-choice `_exact_keys`** (not
  before the outer check, where `c` is undefined):
  `if isinstance(c, dict): c.setdefault("feedback", "")` (identical pattern to the iframe
  `width`/`height` v2 shim and the tabs `parent`/`tab` v3 shim), then
  `_exact_keys(c, ["text", "is_correct", "feedback"], _("choice"))` and
  `check_str(c["feedback"], _("choice feedback"), max_length=500)` (optional — the
  `required=False` default of `check_str`, so blank feedback passes).
- **Import** `_build_choice` (`importer.py`): pass `feedback=c["feedback"]` when
  constructing each `Choice`.
- **Version:** bump `FORMAT_VERSION` `3 → 4` in `courses/transfer/schema.py` (the
  on-disk element shape changed). The importer's version check accepts any
  `version <= FORMAT_VERSION`, and the `setdefault` shim makes older (v3 and earlier)
  archives import unchanged.
- **Tests that break with this change (must update in the same change — currently green):**
  - *Version-pinned:* `tests/test_tabs_transfer.py` (`test_format_version_is_3` → assert
    `4`; rename or generalize it), `tests/test_transfer_schema.py` (the `FORMAT_VERSION == 3`
    assertion), and `tests/test_transfer_export.py` (the `manifest["format_version"] == 3`
    assertion, ~line 220).
  - *Choice-shape-pinned:* `tests/test_transfer_export.py::test_choice_question` (~line 115)
    asserts each exported choice dict by **exact equality** (`{"text": ..., "is_correct":
    ...}`); once `_ser_choice` emits `feedback`, update the expected dicts to include
    `"feedback": ""` (or the set value). (The validation tests in `test_transfer_validation.py`
    do **not** break — they route through the `setdefault` shim before `_exact_keys`.)
  Skipping any of these makes the DoD's green-suite requirement fail.

### 6. `has_math` — `courses/views.py`

In `_question_has_math`, the `ChoiceQuestionElement` clause additionally scans each
choice's feedback:

```python
if isinstance(q, ChoiceQuestionElement):
    return any(
        has_math_delimiters(c.text) or has_math_delimiters(c.feedback)
        for c in q.choices.all()
    )
```

so a KaTeX nudge triggers KaTeX loading on lesson, quiz, and results pages. This is
the single source of truth consulted by the lesson/quiz context builders and the tabs
recursion (`_element_has_math`), so no other site changes.

### 7. i18n — EN/PL

New translatable strings — **both** need a Polish `msgstr`:

- the editor label `"Feedback (optional)"` (§4), and
- the transfer-validation string `_("choice feedback")` (§5), analogous to the existing
  `_("choice text")` — an easy one to miss, since §5 introduces it away from this section.

Extract with `makemessages`, translate both, compile, and run the catalog-clean check in
DoD (which forbids obsolete `#~` entries; additionally confirm no empty `msgstr` for these
two new msgids — a fuzzy/empty translation would ship English in the Polish catalog).

### Deliberately untouched

`ELEMENT_MODELS`, the add-palette (`_add_menu.html`), `FORM_FOR_TYPE`,
`save_element` (builder), `NESTABLE_TYPE_KEYS`, `_EDITOR_TYPE_LABELS`,
`_ELEMENT_LABELS` / `element_summary`, and the student-render dispatch — none move,
because no new type is introduced. This is the payoff of the enhance-not-add decision.

## Data flow

**Authoring:** editor renders each choice row with a feedback input → author fills it
on distractors → `save_element` → `ChoiceFormSet` saves `Choice.feedback` alongside
`text`/`is_correct` (existing save path, now with one more field).

**Lesson (formative, JS fragment):** student selects + submits → `check_answer` view →
`ChoiceQuestionElement.mark(answer)` builds `MarkResult(..., notes={...})` for a wrong
answer → `feedback_context` (already overridden to add `choices`) passes `mark_result`
→ `_question_feedback.html` includes `_reveal_choice.html` → nudges render under the
student's wrongly-selected annotated choices.

**Quiz:** identical `mark()` output. On the live submit the full `mark()` result flows
through; on reload/resume and the no-JS re-render the result is rebuilt by
`_stored_result`, which carries `notes` (see §2). The whole feedback/reveal block is
server-rendered **only once the question is locked/marked** (existing no-leak gate), so
the nudges inherit that gate — nothing renders pre-lock, on any path.

**Results page:** `quiz_results` → `_results_row` (`courses/views.py`) already calls
`question.mark(answer_from_json(...))` directly and passes the result into
`_reveal_choice.html` as `mark_result` (gated to non-correct outcomes). Because `mark()`
now carries `notes`, the results reveal shows the nudges on the options the student
mis-picked **with no change to `_results_row`** — it is a change-free touch point, listed
here only so it is not mistaken for missing. Already locked/graded → no leak. Pinned by a
results-page nudge assertion (§Testing).

**Transfer:** export emits `feedback`; import (including legacy v≤3 archives via the
shim) reconstructs it.

## Error handling

- **Forged / foreign choice ids:** unchanged — `build_answer` already drops ids not
  belonging to the question before `mark()` runs, so `notes` can only ever key on this
  question's own choices.
- **No-leak (the load-bearing safety property):** per-choice feedback must never appear
  before a quiz question is locked/marked. Guaranteed because `notes` travels on
  `mark_result` and the reveal block is gated on lock/mark in both the quiz template and
  the results path. Pinned by an explicit test (a selected-distractor's nudge is absent
  from the withheld pre-lock quiz fragment, and present only after lock).
- **Empty feedback:** blank feedback never enters `notes` (the `and c.feedback` guard),
  so no empty nudge elements render.
- **Correct submission:** `notes` is empty, so no nudge renders even if the author
  annotated a correct choice — consistent with the locked display rule.
- **Legacy archive import:** the `setdefault("feedback", "")` shim means a v3-or-earlier
  export (no `feedback` key) imports cleanly; the strict `_exact_keys` still rejects
  unknown keys.
- **KaTeX / escaping:** feedback is auto-escaped on render like `text`; the U+FFFF /
  markup-injection concerns that apply to fill-blank token forging do not apply here
  (feedback is displayed, never parsed into inputs).

## Testing

Model / marking:

- `mark()` populates `notes` (a `frozenset` of pks) for selected annotated choices on a
  **wrong** answer; leaves it an empty `frozenset` on a **correct** answer.
- `notes` excludes selected choices with blank feedback, and excludes annotated choices
  the student did **not** select.
- **Multiple-choice:** a selected annotated **correct** choice in an overall-wrong
  submission is **absent** from `notes` (only selected distractors nudge — pins the
  `not c.is_correct` clause / the I2 rule).
- `MarkResult.notes` defaults to an empty `frozenset` for every other question type (no
  regression), and `MarkResult` stays hashable (a `frozenset` field, not a dict) — a
  `hash(MarkResult(...))` smoke assertion guards this.

Rendering:

- `_reveal_choice.html` shows the nudge (as `.question__nudge`) under a wrongly-selected
  annotated choice and not under others; correct-✓ behaviour unchanged.
- KaTeX delimiters in feedback survive to the client (auto-escaped, not mangled).
- Light + dark screenshot of the nudge verified before shipping.

Quiz no-leak (explicit):

- A selected-distractor's nudge is **absent** from the withheld pre-lock quiz fragment
  and **present** only after the question is locked/marked (negative + positive
  assertion, mirroring the existing choice withhold test).
- After locking, the nudge **survives a page reload/resume and the no-JS re-render**
  (exercises `_stored_result` carrying `notes` — pins the C1 gap: nudge present
  post-reload, not only on the live submit).
- **Results page:** a mis-picked distractor's nudge renders on the `quiz_results` reveal
  (pins the third render path — `_results_row` → `_reveal_choice.html` — alongside the
  lesson and quiz paths).

Editor / authoring:

- `GET`/`POST` `manage_element_add`-and edit for a choice question round-trips
  `Choice.feedback` (save → reload → value present).
- The "Add option" flow yields a row whose feedback input posts under the correct
  formset prefix (verifies the clone picks up the new field).

Transfer:

- Export includes `feedback`; round-trip export→import preserves it.
- A legacy archive **without** the `feedback` key imports cleanly (shim), producing
  empty feedback.
- `_val_choice` rejects a too-long (>500) feedback string.

has_math:

- `_element_has_math` is `True` for a choice question whose only math lives in a
  choice's feedback; `False` when neither text nor feedback carries math.

i18n:

- Catalog-clean check passes (no obsolete `#~` entries; Polish string present).

Definition of done: `ruff check --fix && ruff format`, `makemigrations --check`,
`manage.py check`, full `pytest -m "not e2e"`, relevant e2e (choice authoring +
consumption), and the i18n catalog test all green.
