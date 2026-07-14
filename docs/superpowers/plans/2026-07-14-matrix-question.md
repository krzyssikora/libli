# Matrix question Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Matrix question" — a graded `QuestionElement` subclass presenting N statements, each answered by picking one of a shared set of columns, with partial credit per row.

**Architecture:** Mirror `MatchPairQuestionElement`: a `QuestionElement` subclass with two relational children (`GridColumn`, `GridRow`). Answer is a JSON-safe positional list aligned to rows (`""` sentinel for unanswered). Authoring uses two inline formsets (columns + rows) joined by a client temp-id resolved server-side after columns save. No-JS grid markup is built by a `render_choice_grid` simple tag. Transfer adds a `choice_grid` trio entry whose importer builder saves columns internally.

**Tech Stack:** Django 5.2, server-rendered templates, token-driven bespoke CSS, vanilla JS enhancers, vendored KaTeX, pytest + Playwright.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-14-matrix-question-design.md`. Every task's requirements implicitly include it.
- **One form/type-key literal: `choicegridquestion`** — identical across `FORM_FOR_TYPE`, `save_element`, `_add_menu.html`, `element_add`/`element_save` allow-tuples, and the `_edit_choicegridquestion.html` partial name.
- Model class `ChoiceGridQuestionElement`; student template `choicegridquestionelement.html` (model-name); transfer key `choice_grid` (snake_case); reveal include `_reveal_choicegrid.html` (short).
- **Do NOT bump `FORMAT_VERSION`** (currently 3). `ELEMENT_MODELS` count assertion in `tests/test_transfer_schema.py` goes 25 → 26.
- NOT added to `NESTABLE_TYPE_KEYS` (top-level only).
- Answer payload: positional list aligned to rows; answered entry = column pk (int); unanswered = `""` (NOT `None`).
- `on_delete=models.PROTECT` on `GridRow.correct_column`.
- Marking mode defaults `AUTO`; author-selectable via `_MarkingFieldsMixin` (no hard-pin).
- Run `uv run` for ruff/pytest/python (not on PATH). Per task: `uv run ruff check --fix . && uv run ruff format .`. Migrations are ruff-excluded.
- Tests/Django via `.\.venv\Scripts\python.exe -m pytest -q -m "not e2e"`; e2e via `-m e2e`.
- Isolate the test DB per worktree (unique `DATABASE_URL`) to avoid Postgres `test_libli` contention.

---

## File Structure

- `courses/models.py` — `ChoiceGridQuestionElement`, `GridColumn`, `GridRow`; `ELEMENT_MODELS` entry.
- `courses/migrations/00NN_matrix_question.py` — 3 tables + `Element` AlterField.
- `courses/element_forms.py` — `ChoiceGridQuestionElementForm`, column & row formsets + builders, `FORM_FOR_TYPE` entry.
- `courses/builder.py` — `save_element` `choicegridquestion` branch (two-formset temp-id resolve); `ElementFormInvalid` extended to carry both formsets.
- `courses/views_manage.py` — `element_add`/`element_save` allow-tuples, `_EDITOR_TYPE_LABELS`, `_render_open_form`/`element_form` two-formset threading.
- `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS`, `element_summary`.
- `courses/templatetags/courses_extras.py` — `render_choice_grid` simple tag + Python builder.
- `courses/views.py` — `question_models` list, `_question_has_math`/`_element_has_math` branch, `build_lesson_context` + `build_quiz_context` prefetch.
- `templates/courses/elements/choicegridquestionelement.html` — student render.
- `templates/courses/elements/_reveal_choicegrid.html` — results reveal.
- `templates/courses/manage/editor/_edit_choicegridquestion.html` — authoring editor partial.
- `courses/static/courses/js/choicegrid.js` — editor enhancer; wired into `editor.js` + `editor.html`.
- `courses/transfer/{export,payloads,importer}.py` — `_ser_choice_grid`, `_val_choice_grid`, `_build_choice_grid` + registry entries.
- `locale/**` — EN/PL strings.
- `tests/` — unit + e2e.

---

### Task 1: Models + migration

**Files:**
- Modify: `courses/models.py` (add 3 models near `MatchPairQuestionElement`; add `ELEMENT_MODELS` entry)
- Create: `courses/migrations/00NN_matrix_question.py` (via makemigrations)
- Test: `tests/test_models_choicegrid.py`

**Interfaces:**
- Produces: `ChoiceGridQuestionElement` (QuestionElement subclass, `REVEAL_TEMPLATE="courses/elements/_reveal_choicegrid.html"`, `elements = GenericRelation(Element)`); `GridColumn(question FK related_name="columns", label CharField(500), order OrderField)`; `GridRow(question FK related_name="rows", statement CharField(500), correct_column FK->GridColumn on_delete=PROTECT, order OrderField)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_choicegrid.py
import pytest
from courses.models import ChoiceGridQuestionElement, GridColumn, GridRow, ELEMENT_MODELS

pytestmark = pytest.mark.django_db

def test_choicegrid_in_element_models():
    # ELEMENT_MODELS is a list of lowercase MODEL-NAME STRINGS (consumed by
    # Element.content_type limit_choices_to={"model__in": ELEMENT_MODELS}), NOT classes.
    assert "choicegridquestionelement" in ELEMENT_MODELS

def test_grid_relations_and_ordering():
    q = ChoiceGridQuestionElement.objects.create(stem="Pick the truths")
    c_true = GridColumn.objects.create(question=q, label="True")
    c_false = GridColumn.objects.create(question=q, label="False")
    r1 = GridRow.objects.create(question=q, statement="2+2=4", correct_column=c_true)
    r2 = GridRow.objects.create(question=q, statement="5 is even", correct_column=c_false)
    assert list(q.columns.all()) == [c_true, c_false]
    assert list(q.rows.all()) == [r1, r2]
    assert r1.correct_column_id == c_true.pk

def test_protect_blocks_deleting_referenced_column():
    from django.db.models import ProtectedError
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    c = GridColumn.objects.create(question=q, label="True")
    GridRow.objects.create(question=q, statement="x", correct_column=c)
    with pytest.raises(ProtectedError):
        c.delete()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_models_choicegrid.py -q`
Expected: FAIL (ImportError: cannot import name 'ChoiceGridQuestionElement').

- [ ] **Step 3: Implement the models**

Add near `MatchPairQuestionElement` in `courses/models.py`:

```python
class ChoiceGridQuestionElement(QuestionElement):
    """Matrix single-choice: N statements each answered by one of a shared set of
    columns. Partial credit per row. Mirrors MatchPairQuestionElement's relational
    shape but with two children (columns + rows)."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_choicegrid.html"
    elements = GenericRelation(Element)


class GridColumn(models.Model):
    question = models.ForeignKey(
        ChoiceGridQuestionElement, on_delete=models.CASCADE, related_name="columns"
    )
    label = models.CharField(max_length=500)  # plain text + KaTeX; never sanitised
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.label


class GridRow(models.Model):
    question = models.ForeignKey(
        ChoiceGridQuestionElement, on_delete=models.CASCADE, related_name="rows"
    )
    statement = models.CharField(max_length=500)  # plain text + KaTeX
    correct_column = models.ForeignKey(
        GridColumn, on_delete=models.PROTECT, related_name="+"
    )
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.statement
```

Add the **string** `"choicegridquestionelement"` (the lowercase model name, NOT the class) to the `ELEMENT_MODELS` list (find `ELEMENT_MODELS =` near line 259; it holds strings like `"matchpairquestionelement"`, consumed by `Element.content_type`'s `limit_choices_to={"model__in": ELEMENT_MODELS}`). Appending the class would corrupt `limit_choices_to` and the generated `AlterField`.

- [ ] **Step 4: Make the migration**

Run: `.\.venv\Scripts\python.exe manage.py makemigrations courses`
Expected: one new migration creating `ChoiceGridQuestionElement`, `GridColumn`, `GridRow` + an `AlterField` on `Element.content_type` (validation-only). Confirm no other app drift.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_models_choicegrid.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/models.py courses/migrations/ tests/test_models_choicegrid.py
git commit -m "feat(matrix): ChoiceGridQuestionElement + GridColumn/GridRow models + migration"
```

---

### Task 2: Marking — build_answer, mark (pad/truncate + "" sentinel), reveal via label_map

**Files:**
- Modify: `courses/models.py` (`ChoiceGridQuestionElement`: `build_answer`, `mark`; import `MarkResult`)
- Test: `tests/test_marking_choicegrid.py`

**Interfaces:**
- Consumes: `MarkResult(correct, fraction, reveal)` from `courses.marking`.
- Produces: `build_answer(post) -> list` (len == #rows; entries int col-pk or `""`); `mark(answer) -> MarkResult` (pads/truncates to #rows; per-row correctness; reveal tuple of `{statement, correct_label, chosen_label|None, is_correct}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_marking_choicegrid.py
import pytest
from django.http import QueryDict
from courses.models import ChoiceGridQuestionElement, GridColumn, GridRow

pytestmark = pytest.mark.django_db

def _grid():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    f = GridColumn.objects.create(question=q, label="False")
    r1 = GridRow.objects.create(question=q, statement="2+2=4", correct_column=t)
    r2 = GridRow.objects.create(question=q, statement="5 is even", correct_column=f)
    return q, t, f, r1, r2

def _post(**pairs):
    qd = QueryDict(mutable=True)
    for k, v in pairs.items():
        qd[k] = str(v)
    return qd

def test_build_answer_positional_with_blank_sentinel():
    q, t, f, r1, r2 = _grid()
    # answer row1 correctly, leave row2 blank
    ans = q.build_answer(_post(**{f"row_{r1.pk}": t.pk}))
    assert ans == [t.pk, ""]  # positional, blank sentinel is ""

def test_build_answer_drops_foreign_col():
    q, t, f, r1, r2 = _grid()
    ans = q.build_answer(_post(**{f"row_{r1.pk}": 999999, f"row_{r2.pk}": f.pk}))
    assert ans == ["", f.pk]  # forged col dropped -> ""

def test_mark_all_correct():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk, f.pk])
    assert mr.correct is True and mr.fraction == 1.0

def test_mark_partial():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk, t.pk])  # row2 wrong
    assert mr.correct is False and mr.fraction == 0.5

def test_mark_empty_all_wrong():
    q, t, f, r1, r2 = _grid()
    mr = q.mark(["", ""])
    assert mr.fraction == 0.0 and mr.correct is False

def test_mark_pads_short_stored_answer_no_indexerror():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk])  # a stale stored answer shorter than #rows
    assert mr.fraction == 0.5  # row2 padded to "" -> wrong, no IndexError

def test_reveal_shape():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk, t.pk])
    rev = list(mr.reveal)
    assert rev[0]["is_correct"] is True and rev[0]["correct_label"] == "True"
    assert rev[1]["is_correct"] is False and rev[1]["correct_label"] == "False"
    assert rev[1]["chosen_label"] == "True"
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_marking_choicegrid.py -q`
Expected: FAIL (`build_answer`/`mark` not defined on the model).

- [ ] **Step 3: Implement build_answer + mark**

Add to `ChoiceGridQuestionElement` (import `from courses.marking import MarkResult` is already at module top — reuse it):

```python
    def build_answer(self, post):
        rows = list(self.rows.all())
        valid = {c.pk for c in self.columns.all()}
        out = []
        for row in rows:
            raw = post.get(f"row_{row.pk}")
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                pk = None
            out.append(pk if pk in valid else "")
        return out

    def mark(self, answer):
        rows = list(self.rows.all())
        n = len(rows)
        answer = (list(answer) + [""] * n)[:n]  # pad/truncate; guards stored-answer drift
        label_map = {c.pk: c.label for c in self.columns.all()}
        reveal = []
        n_correct = 0
        for i, row in enumerate(rows):
            chosen = answer[i]
            is_correct = chosen == row.correct_column_id
            if is_correct:
                n_correct += 1
            reveal.append(
                {
                    "statement": row.statement,
                    "correct_label": label_map.get(row.correct_column_id),
                    "chosen_label": label_map.get(chosen) if chosen != "" else None,
                    "is_correct": is_correct,
                }
            )
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=tuple(reveal),
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_marking_choicegrid.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/models.py tests/test_marking_choicegrid.py
git commit -m "feat(matrix): positional-list build_answer + partial-credit mark with pad/truncate"
```

---

### Task 3: Forms + column & row formsets (temp-id linkage) + validation

**Files:**
- Modify: `courses/element_forms.py` (form, two formsets, builders, `FORM_FOR_TYPE` entry)
- Test: `tests/test_forms_choicegrid.py`

**Interfaces:**
- Produces: `ChoiceGridQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm)`; `build_choicegrid_columns_formset(*, data, files, instance, prefix="columns")`; `build_choicegrid_rows_formset(*, data, files, instance, prefix="rows")`. Column form carries an extra non-model `temp_id` CharField; row form carries an extra non-model `correct_temp_id` CharField (the temp-id of its correct column) and does NOT bind the `correct_column` FK directly.
- Consumes: `_MarkingFieldsMixin` (existing).

**Rationale (temp-id, per spec):** `GridRow.correct_column` cannot bind as a plain `ModelChoiceField` because at submit time a chosen column may be brand-new (no pk) and blank-pruning shifts positions. So the row form uses a stable client `correct_temp_id`; `save_element` (Task 4) resolves it to the real FK after columns save. The column form emits its `temp_id` so the map can be built.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_forms_choicegrid.py
import pytest
from courses.element_forms import (
    ChoiceGridQuestionElementForm,
    build_choicegrid_columns_formset,
    build_choicegrid_rows_formset,
    FORM_FOR_TYPE,
)

def test_registered():
    assert FORM_FOR_TYPE["choicegridquestion"] is ChoiceGridQuestionElementForm

def test_column_form_has_temp_id_field():
    fs = build_choicegrid_columns_formset(data=None, files=None, instance=None)
    assert "temp_id" in fs.empty_form.fields

def test_row_form_has_correct_temp_id_field_not_fk():
    fs = build_choicegrid_rows_formset(data=None, files=None, instance=None)
    assert "correct_temp_id" in fs.empty_form.fields
    assert "correct_column" not in fs.empty_form.fields
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_forms_choicegrid.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement forms + formsets**

Add to `courses/element_forms.py` (mirror `MatchPairQuestionElementForm` + `BaseMatchPairFormSet`):

```python
class ChoiceGridQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = ChoiceGridQuestionElement
        fields = ["stem", "explanation", "marking_mode", "max_attempts", "max_marks"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }


class _GridColumnForm(forms.ModelForm):
    temp_id = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = GridColumn
        fields = ["label"]


class BaseGridColumnFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank column (mirrors BaseMatchPairFormSet)."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("label")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one column."))


class _GridRowForm(forms.ModelForm):
    correct_temp_id = forms.CharField(widget=forms.HiddenInput())

    class Meta:
        model = GridRow
        fields = ["statement"]  # correct_column resolved in save_element, not bound here


class BaseGridRowFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank row; each kept row must carry a correct_temp_id."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("statement")
        ]
        if len(kept) < 1:
            raise forms.ValidationError(_("Add at least one row."))
        for f in kept:
            if not f.cleaned_data.get("correct_temp_id"):
                raise forms.ValidationError(_("Each row needs a correct column."))


GridColumnFormSet = inlineformset_factory(
    ChoiceGridQuestionElement, GridColumn, form=_GridColumnForm,
    formset=BaseGridColumnFormSet, extra=2, can_delete=True,
)
GridRowFormSet = inlineformset_factory(
    ChoiceGridQuestionElement, GridRow, form=_GridRowForm,
    formset=BaseGridRowFormSet, extra=2, can_delete=True,
)


def build_choicegrid_columns_formset(*, data=None, files=None, instance=None, prefix="columns"):
    return GridColumnFormSet(data=data, files=files, instance=instance, prefix=prefix)


def build_choicegrid_rows_formset(*, data=None, files=None, instance=None, prefix="rows"):
    return GridRowFormSet(data=data, files=files, instance=instance, prefix=prefix)
```

Register in `FORM_FOR_TYPE`: add `"choicegridquestion": ChoiceGridQuestionElementForm,`. Ensure `ChoiceGridQuestionElement, GridColumn, GridRow` are imported at the top of `element_forms.py` alongside the other models.

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_forms_choicegrid.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/element_forms.py tests/test_forms_choicegrid.py
git commit -m "feat(matrix): ChoiceGrid form + column/row formsets with temp-id linkage"
```

---

### Task 4: save_element branch (two-formset temp-id resolution) + authoring wiring

**Files:**
- Modify: `courses/builder.py` (`save_element` `choicegridquestion` branch)
- Modify: `courses/views_manage.py` (`element_add`/`element_save` type tuples; `_EDITOR_TYPE_LABELS`)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS` + `element_summary`)
- Modify: `templates/courses/manage/_add_menu.html` (Questions-group card)
- Test: `tests/test_save_choicegrid.py`

**Interfaces:**
- Consumes: `build_choicegrid_columns_formset`, `build_choicegrid_rows_formset`, `ChoiceGridQuestionElementForm`.
- Produces: creating/updating a `choicegridquestion` via `save_element` persists the question, its columns, and its rows with `correct_column` resolved from each row's `correct_temp_id` against the just-saved columns.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_save_choicegrid.py
import pytest
from courses.builder import save_element
from courses.models import ChoiceGridQuestionElement
from tests.factories import ... # reuse existing helpers: make_pa/course/unit builders used by test_questions_2d_*

pytestmark = pytest.mark.django_db

def _post(unit, **extra):
    # Mirror the wire shape the editor posts: management-form counts + column/row rows.
    data = {
        "unit_token": unit.updated.isoformat(),
        "stem": "Pick the truths", "explanation": "", "marking_mode": "AUTO",
        "max_attempts": "0", "max_marks": "1",
        # columns formset
        "columns-TOTAL_FORMS": "2", "columns-INITIAL_FORMS": "0",
        "columns-MIN_NUM_FORMS": "0", "columns-MAX_NUM_FORMS": "1000",
        "columns-0-label": "True", "columns-0-temp_id": "c1",
        "columns-1-label": "False", "columns-1-temp_id": "c2",
        # rows formset
        "rows-TOTAL_FORMS": "2", "rows-INITIAL_FORMS": "0",
        "rows-MIN_NUM_FORMS": "0", "rows-MAX_NUM_FORMS": "1000",
        "rows-0-statement": "2+2=4", "rows-0-correct_temp_id": "c1",
        "rows-1-statement": "5 is even", "rows-1-correct_temp_id": "c2",
    }
    data.update(extra)
    return data

def test_create_resolves_temp_ids(make_course_with_unit):
    course, unit = make_course_with_unit  # adapt to the real fixture in tests/
    save_element(course, unit.pk, "choicegridquestion", "new", _post(unit), files=None)
    q = ChoiceGridQuestionElement.objects.get()
    assert [c.label for c in q.columns.all()] == ["True", "False"]
    rows = list(q.rows.all())
    assert rows[0].correct_column.label == "True"
    assert rows[1].correct_column.label == "False"

def test_row_pointing_at_unknown_temp_id_is_422(make_course_with_unit):
    from courses.builder import ElementFormInvalid
    course, unit = make_course_with_unit
    bad = _post(unit)
    bad["rows-1-correct_temp_id"] = "nope"
    with pytest.raises(ElementFormInvalid):
        save_element(course, unit.pk, "choicegridquestion", "new", bad, files=None)
    assert not ChoiceGridQuestionElement.objects.exists()  # atomic rollback

def test_edit_delete_column_and_repoint_same_submission(make_course_with_unit):
    # Create a True/False grid, then in ONE edit submission delete the "False" column
    # and re-point its row onto "True". Must succeed (PROTECT ordering: rows re-pointed
    # BEFORE the column is deleted), not raise ProtectedError.
    course, unit = make_course_with_unit
    save_element(course, unit.pk, "choicegridquestion", "new", _post(unit), files=None)
    q = ChoiceGridQuestionElement.objects.get()
    cols = list(q.columns.all())          # [True(c1), False(c2)]
    rows = list(q.rows.all())             # row2 -> False(c2)
    join = q.elements.get()               # the Element join row (element_ref for edit)
    edit = {
        "unit_token": unit.updated.isoformat(),
        "stem": "Pick the truths", "explanation": "", "marking_mode": "AUTO",
        "max_attempts": "0", "max_marks": "1",
        "columns-TOTAL_FORMS": "2", "columns-INITIAL_FORMS": "2",
        "columns-MIN_NUM_FORMS": "0", "columns-MAX_NUM_FORMS": "1000",
        "columns-0-id": str(cols[0].pk), "columns-0-label": "True", "columns-0-temp_id": "c1",
        "columns-1-id": str(cols[1].pk), "columns-1-label": "False", "columns-1-temp_id": "c2",
        "columns-1-DELETE": "on",         # delete the False column
        "rows-TOTAL_FORMS": "2", "rows-INITIAL_FORMS": "2",
        "rows-MIN_NUM_FORMS": "0", "rows-MAX_NUM_FORMS": "1000",
        "rows-0-id": str(rows[0].pk), "rows-0-statement": "2+2=4", "rows-0-correct_temp_id": "c1",
        "rows-1-id": str(rows[1].pk), "rows-1-statement": "5 is even", "rows-1-correct_temp_id": "c1",  # re-pointed
    }
    save_element(course, unit.pk, "choicegridquestion", join.pk, edit, files=None)
    q.refresh_from_db()
    assert q.columns.count() == 1
    assert all(r.correct_column.label == "True" for r in q.rows.all())
```

> NOTE for implementer: adapt fixtures to the real helpers used in `tests/test_questions_2d_*` (`make_pa`, `add_element`, `ContentNodeFactory`, quiz/lesson unit builders) and the real edit `element_ref` convention (the Element join pk). Do NOT invent fixtures. Verify the exact management-form field names/prefixes against a real rendered editor POST.

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_save_choicegrid.py -q`
Expected: FAIL (no `choicegridquestion` branch → falls through / raises).

- [ ] **Step 3a: Extend the single-formset plumbing to carry TWO formsets**

The existing plumbing carries exactly ONE formset (`ElementFormInvalid(form, formset=None)` at `builder.py:291`; `_render_open_form(..., formset=None)` passes `"formset": formset` into `_host_form` context at `views_manage.py:851`; `element_save`'s 422 branch re-renders with `formset=e.formset` at `views_manage.py:1001`; `element_form` render-path builds one formset). The matrix needs two (columns + rows). "Mirror matchpair" is NOT sufficient — matchpair passes ONE generic `formset`. Make these concrete edits (a second formset channel + two named context vars):

- `courses/builder.py`: extend `ElementFormInvalid.__init__(self, form, formset=None, formset2=None)` and store `self.formset2 = formset2` (existing single-formset callers unaffected; `formset2` defaults None).
- `courses/views_manage.py` `_render_open_form`: add a `formset2=None` param; for `choicegridquestion`, when `formset is None` build BOTH formsets (columns → `formset`, rows → `formset2`) via `build_choicegrid_columns_formset(instance=instance)` / `build_choicegrid_rows_formset(instance=instance)`; add `"columns_formset": formset` and `"rows_formset": formset2` to the `_host_form` context dict (the generic `"formset"` key stays for other types). `_edit_choicegridquestion.html` (Task 5) reads `columns_formset`/`rows_formset` — NOT the generic `{{ formset }}`.
- `courses/views_manage.py` `element_save` 422 branch: re-render `_render_open_form(..., formset=e.formset, formset2=e.formset2)`.
- `courses/views_manage.py` `element_form` (render-only edit): for `choicegridquestion`, build both formsets from `el.content_object` and pass `formset=`/`formset2=`.

- [ ] **Step 3b: Implement the save_element branch (PROTECT-safe deletion ordering)**

Insert a branch in `save_element` (after `matchpairquestion`). `save_element` is already `@transaction.atomic` (`builder.py:297`), so any raise rolls the whole branch back:

```python
    elif type_key == "choicegridquestion":
        from courses.element_forms import (
            ChoiceGridQuestionElementForm,
            build_choicegrid_columns_formset,
            build_choicegrid_rows_formset,
        )

        form = ChoiceGridQuestionElementForm(data=post_data, instance=instance)
        col_fs = build_choicegrid_columns_formset(
            data=post_data, files=files, instance=instance
        )
        row_fs = build_choicegrid_rows_formset(
            data=post_data, files=files, instance=instance
        )
        if not form.is_valid() or not col_fs.is_valid() or not row_fs.is_valid():
            raise ElementFormInvalid(form, col_fs, row_fs)  # 422; both bound formsets re-render

        obj = form.save()

        # 1) Save/keep columns WITHOUT applying deletions yet (commit=False defers
        #    deletions), so rows can be re-pointed off any to-be-deleted column BEFORE
        #    PROTECT bites.
        col_fs.instance = obj
        kept_cols = col_fs.save(commit=False)  # new/changed instances only
        for col in kept_cols:
            col.save()
        # temp_id -> surviving GridColumn, from the NON-deleted column forms.
        temp_map = {}
        for f in col_fs.forms:
            cd = f.cleaned_data
            if not cd or cd.get("DELETE") or not cd.get("label"):
                continue
            temp_map[cd.get("temp_id") or str(f.instance.pk)] = f.instance

        # 2) Re-point + save EVERY non-deleted row against a surviving column; delete
        #    the rows marked for deletion. (Iterating row_fs.forms — not just the
        #    save(commit=False) changed set — so an unchanged row whose column was
        #    removed is still validated against surviving columns.)
        row_fs.instance = obj
        row_fs.save(commit=False)  # populate .instance on each form; persist nothing yet
        for rf in row_fs.forms:
            cd = rf.cleaned_data
            if not cd:
                continue
            if cd.get("DELETE"):
                if rf.instance.pk:
                    rf.instance.delete()
                continue
            if not cd.get("statement"):
                continue
            col = temp_map.get(cd.get("correct_temp_id"))
            if col is None:  # temp-id resolves to no surviving column
                raise ElementFormInvalid(form, col_fs, row_fs)  # 422, atomic rollback
            rf.instance.correct_column = col
            rf.instance.save()

        # 3) ONLY NOW apply column deletions — every surviving row points at a surviving
        #    column, so PROTECT is satisfied.
        for dead_col in col_fs.deleted_objects:
            dead_col.delete()
```

> Implementer note: this ordering (keep columns → re-point/save all non-deleted rows → delete columns last) is the spec's locked PROTECT-ordering invariant. Verify against a real POST that a same-submission "delete a column and re-point its rows" flow succeeds and a row pointing at a removed column returns 422 (both tested in Step 1 — add the delete-and-re-point edit case there).

- [ ] **Step 3c: Add the authoring wiring**

- `courses/views_manage.py`: add `"choicegridquestion"` to the `element_add` and `element_save` allow-tuples (L880-905, L940-966); add `_EDITOR_TYPE_LABELS["choicegridquestion"] = _("Matrix question")`.
- `courses/templatetags/courses_manage_extras.py`: add the `_ELEMENT_LABELS` entry `_("Matrix question")` (match the existing keying — verify whether keyed by model class or by model-name string, and mirror it); extend `element_summary` to return a short summary (e.g. stem or "N statements").
- `templates/courses/manage/_add_menu.html`: add a Questions-group card posting `type=choicegridquestion` (mirror the match-pairs card).

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_save_choicegrid.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/builder.py courses/views_manage.py courses/templatetags/courses_manage_extras.py templates/courses/manage/_add_menu.html tests/test_save_choicegrid.py
git commit -m "feat(matrix): save_element two-formset temp-id resolution + authoring wiring"
```

---

### Task 5: Edit-form partial + authoring add render (manage_element_add 200)

**Files:**
- Create: `templates/courses/manage/editor/_edit_choicegridquestion.html`
- Test: `tests/test_editor_choicegrid_add.py`

**Interfaces:**
- Consumes: `_host_form.html` dynamically includes `_edit_<form_key>.html`.
- Produces: GET/POST `manage_element_add` for `choicegridquestion` returns 200 (not `TemplateDoesNotExist`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_editor_choicegrid_add.py
import pytest
pytestmark = pytest.mark.django_db

def test_manage_element_add_renders_200(client, make_pa, make_course_with_unit):
    # adapt to the real manage_element_add route + login helper used in tests/test_questions_2d_*
    ...
    resp = client.get(reverse("courses:manage_element_add", kwargs={...}) + "?type=choicegridquestion")
    assert resp.status_code == 200
    assert b"columns-TOTAL_FORMS" in resp.content
    assert b"rows-TOTAL_FORMS" in resp.content
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_editor_choicegrid_add.py -q`
Expected: FAIL (`TemplateDoesNotExist: _edit_choicegridquestion.html`, or missing `columns_formset`/`rows_formset` context). This depends on the two-formset plumbing from **Task 4 Step 3a** (`_render_open_form` builds both formsets for `choicegridquestion` and passes `columns_formset`/`rows_formset` into the `_host_form` context). If Task 4 is done, that plumbing exists; this task adds the partial that consumes it.

- [ ] **Step 3: Implement the edit partial**

Create `_edit_choicegridquestion.html` mirroring `_edit_matchpairquestion.html`: stem RTE field, explanation RTE field, marking fields, then a **Columns** section rendering `{{ columns_formset }}` (each row: label input + hidden `temp_id`) and a **Rows** section rendering `{{ rows_formset }}` (each row: statement input + a correct-column `<select>` bound to `correct_temp_id`, options synced by JS in Task 10), plus a "Add column"/"Add row"/"True/False preset" control cluster (JS in Task 10). Use `{% comment %}`/single-line `{# #}` only (never multi-line `{# #}`). Field names must match the formset prefixes (`columns`, `rows`) and field names (`label`, `temp_id`, `statement`, `correct_temp_id`).

The context vars `columns_formset` and `rows_formset` are provided by the Task 4 Step 3a plumbing (`_render_open_form`/`element_form`). Do NOT reference the generic `{{ formset }}` (which matchpair uses for its single formset) — the matrix partial reads the two named vars.

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_editor_choicegrid_add.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add templates/courses/manage/editor/_edit_choicegridquestion.html courses/ tests/test_editor_choicegrid_add.py
git commit -m "feat(matrix): edit-form partial + formset render path (manage_element_add 200)"
```

---

### Task 6: Student render — render_choice_grid tag + Python builder + template

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (`render_choice_grid` simple tag + Python builder)
- Create: `templates/courses/elements/choicegridquestionelement.html`
- Test: `tests/test_render_choicegrid.py`

**Interfaces:**
- Consumes: base `QuestionElement.render` (no override) → renders `choicegridquestionelement.html` with `el`, `submitted_values`, `mark_result`, `reveal_template`, `mode`, `action_url`, `locked`, `attempts_left`.
- Produces: `{% render_choice_grid el submitted_values %}` emits a `<table>`: header row of column labels, one body row per statement with a radio group `name="row_<rowpk>"`, `value="<colpk>"`, checked per the positional `submitted_values` list.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render_choicegrid.py
import pytest
from django.template import Context, Template
from courses.models import ChoiceGridQuestionElement, GridColumn, GridRow

pytestmark = pytest.mark.django_db

def _grid():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    f = GridColumn.objects.create(question=q, label="False")
    r1 = GridRow.objects.create(question=q, statement="2+2=4", correct_column=t)
    r2 = GridRow.objects.create(question=q, statement="5 is even", correct_column=f)
    return q, t, f, r1, r2

def _render(q, submitted):
    tpl = Template("{% load courses_extras %}{% render_choice_grid el sv %}")
    return tpl.render(Context({"el": q, "sv": submitted}))

def test_renders_radios_per_row_and_column():
    q, t, f, r1, r2 = _grid()
    html = _render(q, None)
    assert f'name="row_{r1.pk}"' in html and f'value="{t.pk}"' in html
    assert f'name="row_{r2.pk}"' in html and f'value="{f.pk}"' in html
    assert "checked" not in html  # None -> nothing selected

def test_repopulates_from_submitted_values_positional():
    q, t, f, r1, r2 = _grid()
    html = _render(q, [t.pk, ""])  # row1 -> True checked, row2 blank
    assert f'value="{t.pk}" checked' in html.replace("'", '"') or "checked" in html

def test_none_and_short_list_no_spurious_check():
    q, t, f, r1, r2 = _grid()
    assert "checked" not in _render(q, None)
    assert _render(q, [t.pk])  # short list: row2 missing -> no crash
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_render_choicegrid.py -q`
Expected: FAIL (tag not registered).

- [ ] **Step 3: Implement the tag + builder + template**

In `courses/templatetags/courses_extras.py` (mirror `render_match_pairs`):

```python
@register.simple_tag
def render_choice_grid(el, submitted_values=None):
    return mark_safe(_build_choice_grid_html(el, submitted_values))


def _build_choice_grid_html(el, submitted_values):
    cols = list(el.columns.all())
    rows = list(el.rows.all())
    sv = submitted_values or []
    parts = ['<table class="choicegrid">', "<thead><tr><th></th>"]
    for c in cols:
        parts.append(f"<th>{escape(c.label)}</th>")  # KaTeX delims survive escape
    parts.append("</tr></thead><tbody>")
    for i, row in enumerate(rows):
        chosen = sv[i] if i < len(sv) else ""
        parts.append(f'<tr><td class="choicegrid__stmt">{escape(row.statement)}</td>')
        for c in cols:
            checked = " checked" if chosen != "" and chosen == c.pk else ""
            parts.append(
                f'<td><label><input type="radio" name="row_{row.pk}" '
                f'value="{c.pk}"{checked}></label></td>'
            )
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)
```

> Implementer: match the exact `escape`/`mark_safe` imports and helper style already used by `render_match_pairs` in this module; entries in `submitted_values` are ints or `""` (Task 2). Compare with `int(chosen) == c.pk` if the stored list came back as strings — verify against a real quiz round-trip and pin with a test.

Create `templates/courses/elements/choicegridquestionelement.html` mirroring `matchpairquestionelement.html`: render `el.stem` (via the existing question-stem include/markup), then the `<form>` posting to `action_url` with `{% csrf_token %}` and `{% render_choice_grid el submitted_values %}`, the feedback container, Check button, and `{% include reveal_template %}` gated exactly as matchpair does (mode/locked). Add `data-question` on the wrapper so `question.js` typesets it.

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_render_choicegrid.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/templatetags/courses_extras.py templates/courses/elements/choicegridquestionelement.html tests/test_render_choicegrid.py
git commit -m "feat(matrix): render_choice_grid tag + student template"
```

---

### Task 7: Lesson/quiz context — has_questions, has_math, prefetch

**Files:**
- Modify: `courses/views.py` (`question_models` list; `_question_has_math`/`_element_has_math` branch; `build_lesson_context` + `build_quiz_context` prefetch)
- Test: `tests/test_context_choicegrid.py`

**Interfaces:**
- Produces: a matrix-only lesson sets `has_questions=True`; a matrix with KaTeX in a column label or statement sets `has_math=True` on the lesson/results path; render context prefetches `columns`/`rows`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_context_choicegrid.py
import pytest
pytestmark = pytest.mark.django_db

def test_matrix_only_lesson_sets_has_questions(...):
    # build a lesson unit whose sole element is a matrix; render lesson_unit; assert question.js loaded
    ...

def test_matrix_math_in_statement_sets_has_math(...):
    # matrix with a statement containing \( ... \); assert has_math true on lesson path
    ...
```

> Implementer: adapt to the real lesson-render test pattern in `tests/` (e.g. `tests/test_questions_2d_*` render a lesson and assert on `resp.content`). Assert `question.js` presence via the same marker `lesson_unit.html` uses.

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_context_choicegrid.py -q`
Expected: FAIL (matrix not in `question_models`; no has_math branch).

- [ ] **Step 3: Implement**

- Add `ChoiceGridQuestionElement` to the hardcoded `question_models` list in `build_lesson_context` (`courses/views.py` ~L241-250).
- Add a matrix branch to **`_question_has_math` only** (NOT `_element_has_math` — it already routes any `QuestionElement` instance to `_question_has_math` at `views.py:168`, so a second branch there is dead code): return true if `stem` OR any `columns.label` OR any `rows.statement` contains KaTeX delimiters (reuse the existing `has_math_delimiters` helper the other branches use).
- Register a `choicegrid_qs` list + `prefetch_related_objects(choicegrid_qs, "columns", "rows")` in both `build_lesson_context` and `build_quiz_context`, mirroring the `matchpair`/`pairs` prefetch. Ensure the reveal path uses the `label_map` (Task 2), not `row.correct_column.label`, so the prefetch actually removes the N+1.

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_context_choicegrid.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/views.py tests/test_context_choicegrid.py
git commit -m "feat(matrix): lesson has_questions + has_math branch + render prefetch"
```

---

### Task 8: Reveal template + results-page integration

**Files:**
- Create: `templates/courses/elements/_reveal_choicegrid.html`
- Test: `tests/test_reveal_choicegrid.py`

**Interfaces:**
- Consumes: `mark_result.reveal` (tuple of `{statement, correct_label, chosen_label|None, is_correct}`) from Task 2.
- Produces: a correct row shows ✓ only; a wrong/unanswered row reveals `correct_label`; the global `explanation` renders.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reveal_choicegrid.py
import pytest
from django.template.loader import render_to_string
from courses.marking import MarkResult

def test_reveal_correct_row_shows_tick_only():
    reveal = ({"statement": "2+2=4", "correct_label": "True", "chosen_label": "True", "is_correct": True},)
    html = render_to_string("courses/elements/_reveal_choicegrid.html", {"mark_result": MarkResult(True, 1.0, reveal)})
    assert "2+2=4" in html and "✓" in html

def test_reveal_wrong_row_reveals_correct_label():
    reveal = ({"statement": "5 is even", "correct_label": "False", "chosen_label": "True", "is_correct": False},)
    html = render_to_string("courses/elements/_reveal_choicegrid.html", {"mark_result": MarkResult(False, 0.0, reveal)})
    assert "False" in html  # correct column revealed for the wrong row

def test_reveal_renders_explanation():
    from types import SimpleNamespace
    reveal = ({"statement": "s", "correct_label": "True", "chosen_label": None, "is_correct": True},)
    html = render_to_string(
        "courses/elements/_reveal_choicegrid.html",
        {"mark_result": MarkResult(True, 1.0, reveal), "el": SimpleNamespace(explanation="Because arithmetic.")},
    )
    assert "Because arithmetic." in html  # explanation branch actually exercised
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reveal_choicegrid.py -q`
Expected: FAIL (`TemplateDoesNotExist`).

- [ ] **Step 3: Implement the reveal template**

Create `_reveal_choicegrid.html` mirroring `_reveal_matchpair.html`: iterate `mark_result.reveal`; per row show statement + (✓ if `is_correct` else the `correct_label`, optionally the `chosen_label`); render `el.explanation` if present. `{% comment %}` for any multi-line comment.

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_reveal_choicegrid.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add templates/courses/elements/_reveal_choicegrid.html tests/test_reveal_choicegrid.py
git commit -m "feat(matrix): reveal template for results page"
```

---

### Task 9: Transfer trio (export/validate/import) + schema count

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_choice_grid` + `SERIALIZERS` entry)
- Modify: `courses/transfer/payloads.py` (`_val_choice_grid` + `VALIDATORS` entry)
- Modify: `courses/transfer/importer.py` (`_build_choice_grid` + `BUILDERS` entry)
- Test: `tests/test_transfer_choicegrid.py`; modify `tests/test_transfer_schema.py` (25 → 26)

**Interfaces:**
- Produces: transfer key `choice_grid`; serialized `data = {...question fields, columns:[{label}], rows:[{statement, correct}]}` where `correct` is the export-local ordinal of the correct column; `_build_choice_grid(data, assets) -> (question, rows)` saving columns internally.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transfer_choicegrid.py
import pytest
from courses.transfer.export import _ser_choice_grid, SERIALIZERS
from courses.transfer.payloads import _val_choice_grid, VALIDATORS
from courses.transfer.importer import _build_choice_grid, BUILDERS
from courses.models import ChoiceGridQuestionElement, GridColumn, GridRow

pytestmark = pytest.mark.django_db

def test_registered():
    assert SERIALIZERS["choice_grid"][0] is ChoiceGridQuestionElement
    assert "choice_grid" in VALIDATORS and "choice_grid" in BUILDERS

def test_roundtrip_links_intact():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    f = GridColumn.objects.create(question=q, label="False")
    GridRow.objects.create(question=q, statement="a", correct_column=t)
    GridRow.objects.create(question=q, statement="b", correct_column=f)
    data = _ser_choice_grid(q, None)
    assert data["rows"][0]["correct"] == 0 and data["rows"][1]["correct"] == 1
    q2, rows = _build_choice_grid(data, assets={})
    for r in rows:
        r.full_clean(exclude=["order"]); r.save()
    assert list(q2.columns.values_list("label", flat=True)) == ["True", "False"]
    assert q2.rows.get(statement="b").correct_column.label == "False"

def test_validator_rejects_out_of_range_ordinal():
    from courses.transfer.schema import TransferError
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    GridColumn.objects.create(question=q, label="True")
    data = _ser_choice_grid(q, None)
    data["rows"] = [{"statement": "a", "correct": 5}]  # out of range
    with pytest.raises(TransferError):
        _val_choice_grid(data, "el1", media_kinds={})
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_transfer_choicegrid.py -q`
Expected: FAIL (ImportError / KeyError).

- [ ] **Step 3: Implement the trio**

`export.py` (mirror `_ser_match_pair`):

```python
def _ser_choice_grid(el, ids):
    cols = list(el.columns.all())
    index = {c.pk: i for i, c in enumerate(cols)}
    return {
        **_question_fields(el),
        "columns": [{"label": c.label} for c in cols],
        "rows": [
            {"statement": r.statement, "correct": index[r.correct_column_id]}
            for r in el.rows.all()
        ],
    }
```
Add `"choice_grid": (ChoiceGridQuestionElement, _ser_choice_grid),` to `SERIALIZERS`.

`payloads.py` (mirror `_val_match_pair`, add ordinal bounds-check):

```python
def _val_choice_grid(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["columns", "rows"], _("choice_grid data"))
    _check_question_fields(data, elid)
    columns = check_list(data["columns"], "columns")
    if not columns:
        _err(_("Element '%(el)s': at least one column is required."), el=elid)
    for c in columns:
        _exact_keys(c, ["label"], _("column"))
        check_str(c["label"], _("column label"), max_length=500, required=True)
    rows = check_list(data["rows"], "rows")
    if not rows:
        _err(_("Element '%(el)s': at least one row is required."), el=elid)
    for r in rows:
        _exact_keys(r, ["statement", "correct"], _("row"))
        check_str(r["statement"], _("row statement"), max_length=500, required=True)
        if not isinstance(r["correct"], int) or not (0 <= r["correct"] < len(columns)):
            _err(_("Element '%(el)s': row correct-column out of range."), el=elid)
    return set()
```
Add `"choice_grid": _val_choice_grid,` to `VALIDATORS`.

`importer.py` (**deviates from flat-child-list**: save columns internally, return `(q, rows)`):

```python
def _build_choice_grid(data, assets):
    q = _clean_save(ChoiceGridQuestionElement(**_q_kwargs(data)))
    saved_cols = []
    for c in data["columns"]:
        col = GridColumn(question=q, label=c["label"])
        col.full_clean(exclude=["order"])
        col.save()
        saved_cols.append(col)
    rows = [
        GridRow(
            question=q,
            statement=r["statement"],
            correct_column=saved_cols[r["correct"]],
        )
        for r in data["rows"]
    ]
    return q, rows  # generic loop full_clean+saves the rows
```
Add `"choice_grid": _build_choice_grid,` to `BUILDERS`. Import the three models at the top of `importer.py`.

Update `tests/test_transfer_schema.py`: the `ELEMENT_MODELS` count assertion `== 25` becomes `== 26`.

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_transfer_choicegrid.py tests/test_transfer_schema.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/transfer/ tests/test_transfer_choicegrid.py tests/test_transfer_schema.py
git commit -m "feat(matrix): transfer trio (ordinal-linked columns/rows) + schema count 25->26"
```

---

### Task 10: JS enhancer (temp-id sync, presets, add/remove) + editor wiring

**Files:**
- Create: `courses/static/courses/js/choicegrid.js`
- Modify: `courses/static/courses/js/editor.js` (re-init after fragment swap)
- Modify: `templates/courses/manage/editor.html` (`<script defer>` tag)
- Test: `tests/test_editor_scripts.py` (script-presence) + e2e in Task 12

**Interfaces:**
- Produces: `window.libliInitChoiceGrid(root)` — assigns a stable `temp_id` to each column row (hidden field), syncs each row's correct-column `<select>` options to the current columns (option value = column temp_id, label = column label), wires "Add column"/"Add row" (clone formset row + bump TOTAL_FORMS), the True/False preset (seed two columns), and remove buttons; runs `renderMathInElement` over previews.

- [ ] **Step 1: Write the failing test (script presence)**

```python
# tests/test_editor_scripts.py (add a case; adapt to existing file if present)
def test_editor_loads_choicegrid_js(client, make_pa, make_course_with_unit):
    ...
    resp = client.get(reverse("courses:manage_editor", kwargs={...}))
    assert b"choicegrid.js" in resp.content
```

- [ ] **Step 2: Run to verify failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_editor_scripts.py -q`
Expected: FAIL (script not loaded).

- [ ] **Step 3: Implement choicegrid.js + wiring**

Write `choicegrid.js` mirroring the switch-grid/match editors' clone-row + i18n-via-data-attrs patterns:
- Column temp-id: on init, for each column row without a `temp_id`, generate one (e.g. `"t" + counter`) into its hidden `columns-<i>-temp_id`; existing (saved) columns keep whatever the server rendered (fall back to a synthetic if blank).
- Correct-column `<select>` per row (name `rows-<i>-correct_temp_id`): rebuild its `<option>`s from current columns (value=temp_id, text=label) whenever columns change; preserve the currently-selected temp_id.
- "Add column"/"Add row": clone `empty_form`, replace `__prefix__`, bump `TOTAL_FORMS`.
- True/False preset button: seed two columns labelled `True`/`False` (localised via `{% trans %}` `data-*` attrs, per the JS-side i18n rule), each with a fresh temp_id, then refresh all row selects.
- Inline KaTeX preview over statements/labels via `renderMathInElement`.

Wire into `editor.js`: call `window.libliInitChoiceGrid(preview)` after each fragment swap, next to the gallery/tabs/switch-grid re-inits. Add `<script src="{% static 'courses/js/choicegrid.js' %}" defer></script>` to `editor.html` next to the other question enhancers.

- [ ] **Step 4: Run to verify pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_editor_scripts.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/static/courses/js/choicegrid.js courses/static/courses/js/editor.js templates/courses/manage/editor.html tests/test_editor_scripts.py
git commit -m "feat(matrix): choicegrid.js editor enhancer (temp-id sync, T/F preset) + wiring"
```

---

### Task 11: Frontend-design pass (student grid + editor), screenshot-verified

**Files:**
- Modify: `courses/static/courses/css/*.css` (matrix table + editor styling; follow token system)
- Modify: `templates/courses/elements/choicegridquestionelement.html`, `_edit_choicegridquestion.html` (class hooks only, no behavior change)
- Test: `tests/test_choicegrid_styles.py` (CSS-presence/render guard)

**Interfaces:**
- Produces: `.choicegrid` table styled in the warm-teal identity, light + dark, mobile-safe (horizontal scroll or stacked), selected/correct/incorrect cell states within the existing feedback vocabulary; the editor's columns/rows sections styled to match the choice/match editors.

- [ ] **Step 1: Invoke the frontend-design skill**

Use `frontend-design:frontend-design` for aesthetic direction on BOTH surfaces (student matrix render, authoring editor). Apply token-driven CSS (no Bootstrap/React), style light + dark.

- [ ] **Step 2: Write a CSS-presence/render guard**

```python
# tests/test_choicegrid_styles.py
def test_matrix_table_class_styled():
    # assert the .choicegrid rule exists in the compiled/served CSS, like other element style guards
    ...
```

- [ ] **Step 3: Screenshot-verify light + dark**

Drive Playwright to screenshot: (a) a taken lesson with a True/False grid and a 3–4 column grid, (b) the authoring editor with columns + rows + preset button — in BOTH light and dark. Self-critique for contrast, column alignment, KaTeX legibility, mobile width. Iterate CSS until clean. Save screenshots under the scratchpad; do NOT commit binaries.

- [ ] **Step 4: Run guard + full render tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_choicegrid_styles.py tests/test_render_choicegrid.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add courses/static/courses/css/ templates/courses/ tests/test_choicegrid_styles.py
git commit -m "style(matrix): frontend-design pass — student grid + editor (light/dark)"
```

---

### Task 12: i18n (EN/PL) + Playwright e2e + DoD gate

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compile)
- Create: `tests/test_e2e_choicegrid.py`

**Interfaces:**
- Produces: all new strings translated EN/PL; e2e proves a matrix answered in a lesson (immediate feedback) and in a quiz (withheld → locked → results reveal), driving real radio clicks.

- [ ] **Step 1: Write the e2e (mark e2e)**

```python
# tests/test_e2e_choicegrid.py
import pytest
pytestmark = pytest.mark.e2e

def test_matrix_lesson_immediate_feedback(live_server, page, ...):
    # author or seed a matrix in a lesson; click radios; Check; assert per-row feedback + reveal
    ...

def test_matrix_quiz_withhold_then_results(live_server, page, ...):
    # answer in a quiz; assert feedback withheld until locked; finish; results reveal correct columns
    ...
```

> Implementer: mirror `tests/test_e2e_questions.py` / `test_questions_2d_*` structure and helpers; drive the REAL radio clicks (never `page.evaluate` shortcuts).

- [ ] **Step 2: Run e2e to verify failure/then pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_e2e_choicegrid.py -m e2e -q`
Expected: PASS after implementation (run focused foreground only — never a broad `-m e2e` in the background).

- [ ] **Step 3: i18n extract + translate + compile**

Run `makemessages` (heed the fuzzy-flag gotcha), fill Polish for every new msgid (Matrix question, Add column, Add row, True/False, "at least one column/row", etc.), `compilemessages -l pl`. Ensure no empty `msgstr ""`, no `#, fuzzy`, no `#~` obsolete entries.

- [ ] **Step 4: DoD gate (full)**

Run, all must pass:
```
uv run ruff check .
uv run ruff format --check .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe -m pytest -q -m "not e2e"
.\.venv\Scripts\python.exe -m pytest -q -m e2e tests/test_e2e_choicegrid.py
```
Also run the i18n catalog test (`test_po_catalog_clean`/`test_i18n_*`) — a new element adds translatable strings.

- [ ] **Step 5: Commit**

```bash
git add locale/ tests/test_e2e_choicegrid.py
git commit -m "i18n(matrix): EN/PL strings + Playwright e2e (lesson + quiz) + DoD"
```

---

## Self-Review

**Spec coverage:** Models (T1), marking + sentinel + pad/truncate + reveal map (T2), forms/formsets/temp-id (T3), save_element two-formset resolution + PROTECT ordering + authoring wiring (T4), edit partial + manage_element_add 200 (T5), render_choice_grid tag + template + no render() override (T6), has_questions + has_math + prefetch (T7), reveal template (T8), transfer trio + ordinal bounds-check + no FORMAT_VERSION bump + count 25→26 (T9), JS enhancer + editor.js/editor.html wiring + script test (T10), frontend-design both surfaces (T11), i18n + e2e + DoD (T12). Every spec section maps to a task.

**Placeholder scan:** Test fixtures in T4/T5/T7/T10/T12 are intentionally marked "adapt to real helpers" because the exact fixture names live in `tests/test_questions_2d_*` and must be read at implementation time — each such step names the concrete file to mirror rather than inventing a fixture. All code steps for novel logic (models, marking, forms, save, tag, transfer) carry complete code.

**Type consistency:** form/type key `choicegridquestion` everywhere; model `ChoiceGridQuestionElement`; student template `choicegridquestionelement.html`; transfer key `choice_grid`; reveal `_reveal_choicegrid.html`; edit `_edit_choicegridquestion.html`; JS `window.libliInitChoiceGrid`; answer entries int-or-`""`; reveal dict keys `statement/correct_label/chosen_label/is_correct` consistent across T2/T6/T8.
