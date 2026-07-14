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

A choice's feedback nudge is shown **only when the student selected that choice AND
the overall submission was wrong** ("selected + wrong only"). Rationale: authors
annotate distractors; a correct submission stays quiet (the existing ✓ reveal already
handles it), and a correct pick the author happened to annotate is not surfaced. This
matches the legacy `.mult_feedback_incorrect` "are you sure about option 2?" nudge.

## Architecture / components

### 1. Data model — `courses/models.py`

Add one field to the existing `Choice` model:

```python
feedback = models.CharField(max_length=500, blank=True)
```

Semantics mirror `Choice.text` exactly: plain text plus KaTeX delimiters, **never
sanitised** (stored raw, auto-escaped by the Django template on render so KaTeX
delimiters survive for client-side KaTeX). Blank by default → existing choices and
un-annotated choices carry an empty string. One migration (additive, nullable-free
with a blank default, no data migration needed).

### 2. Marking — unchanged, nudges carried on the result

`ChoiceQuestionElement.mark(answer)` (`models.py`) keeps exact set-equality for
`correct`/`fraction`. It is the single place with access to the student's selected
set (`answer`) on **both** render paths — the lesson JS-fragment path
(`feedback_context`) does not carry the selection, so the nudge map must originate in
`mark()`.

Add one optional field to `MarkResult` (`courses/marking.py`):

```python
notes: dict = field(default_factory=dict)   # pk -> feedback text; type-opaque, per-type
```

`MarkResult.reveal` (the correct-id frozenset) is **unchanged**, so the existing ✓
logic and every current consumer/test keep working. `notes` is a separate, optional,
type-opaque presentation payload — consistent with the existing docstring describing
`reveal` as "a per-type, type-opaque presentation payload consumed by the reveal
template." Every other question type leaves `notes` empty.

`ChoiceQuestionElement.mark()` populates `notes` **only when the answer is wrong**,
with `{pk: choice.feedback}` for each **selected** choice that has non-empty
feedback:

```python
is_correct = set(answer) == set(correct_set)
notes = {}
if not is_correct:
    for c in self.choices.all():
        if c.pk in answer and c.feedback:
            notes[c.pk] = c.feedback
return MarkResult(correct=is_correct, fraction=..., reveal=correct_set, notes=notes)
```

### 3. Reveal template — `templates/courses/elements/_reveal_choice.html`

Currently lists each choice and ticks the ones in `mark_result.reveal`. Add: under a
choice whose pk is present in `mark_result.notes`, render its nudge text (auto-escaped;
KaTeX delimiters preserved). The correct-✓ block is untouched. Because `notes` is only
ever non-empty on a wrong submission and only for selected choices, no extra guard is
needed in the template beyond "is this pk in `notes`".

### 4. Editor — `templates/courses/manage/editor/_edit_choicequestion.html`

Add an optional per-choice feedback text input to each `.choice-row`, below the choice
text (label: "Feedback (optional)"). Add `"feedback"` to the `ChoiceFormSet` field
list (`inlineformset_factory(..., fields=[...])` in `courses/element_forms.py`). The
"Add option" JS clones an existing `.choice-row`, so a new row inherits the field
automatically — to be **verified** during implementation (see Testing). No new form
class; `ChoiceQuestionElementForm` is unchanged.

### 5. Transfer (export / import) — `courses/transfer/`

- **Export** `_ser_choice` (`export.py`): emit `"feedback": c.feedback` in each choice
  dict.
- **Validate** `_val_choice` (`payloads.py`): before the `_exact_keys` check, shim
  legacy archives with `if isinstance(c, dict): c.setdefault("feedback", "")` (identical
  pattern to the iframe `width`/`height` v2 shim and the tabs `parent`/`tab` v3 shim),
  then `_exact_keys(c, ["text", "is_correct", "feedback"], ...)` and
  `check_str(c["feedback"], _("choice feedback"), max_length=500)` (optional, not
  required).
- **Import** `_build_choice` (`importer.py`): pass `feedback=c["feedback"]` when
  constructing each `Choice`.
- **Version:** bump `FORMAT_VERSION` `3 → 4` in `courses/transfer/schema.py` (the
  on-disk element shape changed). The importer's version check accepts any
  `version <= FORMAT_VERSION`, and the `setdefault` shim makes older (v3 and earlier)
  archives import unchanged.

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

New translatable strings: the editor label/hint ("Feedback (optional)"). Extract and
provide the Polish translation; run the catalog-clean check in DoD.

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

**Quiz:** identical `mark()` output, but the whole feedback/reveal block is server-
rendered into `feedback_html` **only once the question is locked/marked** (existing
no-leak gate). Since the nudges ride `mark_result`, they inherit that gate — nothing
renders pre-lock.

**Results page:** reveals all questions; for choice questions it renders the same
reveal template with the frozen `mark_result`, so a reviewing student sees the nudges
on the options they mis-picked. Already locked/graded → no leak.

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

- `mark()` populates `notes` with `{pk: feedback}` for selected annotated choices on a
  **wrong** answer; leaves `notes` empty on a **correct** answer.
- `notes` excludes selected choices with blank feedback, and excludes annotated choices
  the student did **not** select.
- `MarkResult.notes` defaults to empty for every other question type (no regression).

Rendering:

- `_reveal_choice.html` shows the nudge under a wrongly-selected annotated choice and
  not under others; correct-✓ behaviour unchanged.
- KaTeX delimiters in feedback survive to the client (auto-escaped, not mangled).

Quiz no-leak (explicit):

- A selected-distractor's nudge is **absent** from the withheld pre-lock quiz fragment
  and **present** only after the question is locked/marked (negative + positive
  assertion, mirroring the existing choice withhold test).

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
