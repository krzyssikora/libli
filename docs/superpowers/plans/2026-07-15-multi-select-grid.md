# Multi-select grid element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a graded "Multi-select grid" question element — N row-statements × a shared set of columns, each row answered by a *set* of checked columns, all-or-nothing per row with grid-level partial credit.

**Architecture:** A new `MultiGridQuestionElement(QuestionElement)` with two child models (`MultiGridColumn`, `MultiGridRow`), the direct sibling of the shipped Matrix `ChoiceGridQuestionElement`. It mirrors Matrix's entire two-formset / client-temp-id / positional-payload plumbing, with one structural change: a row owns a **`ManyToManyField` set** of correct columns instead of a single FK. Marking is all-or-nothing per row averaged across rows. Ungraded formatively in lessons, scored in quizzes.

**Tech Stack:** Django (server-rendered), Python, vanilla JS enhancers, KaTeX (client math), pytest + Playwright (e2e), `uv` for tooling.

## Global Constraints

- **`ELEMENT_MODELS`** (courses/models.py) goes from **27 → 28** entries; the new model is `multigridquestionelement`, appended last.
- **Migration** is the next number after `0045_stepper` → **`0046_multigrid…`**; it re-`AlterField`s `Element.content_type`'s `limit_choices_to` `model__in` list to append `multigridquestionelement` (the list currently ends at `stepperelement`).
- **Do NOT bump `FORMAT_VERSION`** (courses/transfer/schema.py stays `4`) — additive element type.
- **Form/type key** is the literal `multigridquestion` everywhere (FORM_FOR_TYPE, save_element, add-menu, allow-tuples, `_edit_multigridquestion.html`). **Transfer key** is the snake_case `multi_grid` (≠ form key).
- **Not nestable** — no question type is; omit from `NESTABLE_TYPE_KEYS`.
- **Marking:** per row `is_correct = (set(chosen_pks) == {c.pk for c in row.correct_columns.all()})`; grid `fraction = (# fully-correct rows)/(# rows)`, `correct = (all rows correct and rows > 0)`.
- **≥1 correct column per row** is a hard invariant (formset raw check + save_element resolution + importer validator).
- **i18n:** module-level label dicts use `gettext_lazy`; forms use `from django.utils.translation import gettext_lazy as _`; templates use `{% trans %}`; JS strings pass via `data-*` attrs. EN + PL catalogs; strip any `makemessages` fuzzy matches on new msgids.
- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH — always `uv run …`. Run the heavy suite with `-n auto` (pytest-xdist). e2e is deselected by default `addopts`; run a single e2e file foreground with explicit `-m e2e` (never background/whole-suite `-m e2e` → runaway browsers).
- **Test conventions (match the Matrix siblings EXACTLY — verified against the suite):**
  - **File naming** is `tests/test_<aspect>_multigrid.py` (mirrors `test_models_choicegrid.py`, `test_marking_choicegrid.py`, `test_save_choicegrid.py`, `test_render_choicegrid.py`, `test_forms_choicegrid.py`, `test_transfer_choicegrid.py`, `test_context_choicegrid.py`, `test_e2e_choicegrid.py`). The editor add-render test mirrors `test_editor_choicegrid_add.py` → `tests/test_editor_multigrid_add.py`; the script-load assertion is ADDED to the existing `tests/test_editor_scripts.py`.
  - **No `teacher`/`student`/`unit`/`lesson_unit_with` fixtures exist.** Use the `tests/factories` helpers: `make_pa(client, "pa")` (returns a platform-admin user; sets up session), `make_login(client, "name")` (returns a plain logged-in user), `make_verified_user(username=…, email=…, password=TEST_PASSWORD)` (e2e), `CourseFactory(owner=…, slug=…)`, `ContentNodeFactory(course=…, parent=None, kind="unit", unit_type="lesson"|"quiz")`, `Element.objects.create(unit=…, content_object=q)`, `Enrollment.objects.create(student=…, course=…)`, `TEST_PASSWORD`. `client` is pytest-django's built-in fixture. Every DB test sets `pytestmark = pytest.mark.django_db` at module level.
  - **`save_element` signature is POSITIONAL:** `save_element(course, unit_pk, type_key, element_ref, post_data, files)`. `element_ref` = `"new"` (create) or `str(join.pk)` (edit). It **returns the unit**, not the Element. `post_data` MUST include `"unit_token": unit.updated.isoformat()` and `"unit": str(unit.pk)` (a `_check_token` guard rejects a missing/stale token BEFORE the type branch). Fetch the saved object via `MultiGridQuestionElement.objects.get()` and the join via `Element.objects.get()`.
  - **URL names:** add-render → POST `reverse("courses:manage_element_add", kwargs={"slug": course.slug})` body `{"type": "multigridquestion", "unit": unit.pk}` (a GET 404s at the unit lookup); lesson body → `reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})`; editor page → `reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})` (**kwarg is `pk`, not `node_pk`**).
  - **e2e:** file `tests/test_e2e_multigrid.py`, module `pytestmark = pytest.mark.e2e`, harness copied from `tests/test_e2e_choicegrid.py` (`_login`, `make_verified_user`, `data-question` locators, real clicks — never `page.evaluate`). Run `uv run pytest tests/test_e2e_multigrid.py -m e2e -v`.

---

### Task 1: Models + migration

**Files:**
- Modify: `courses/models.py` (append to `ELEMENT_MODELS` ~line 259; add three classes after `GridRow` ~line 1606)
- Create: `courses/migrations/0046_multigridquestionelement_and_more.py`
- Test: `tests/test_models_multigrid.py`

**Interfaces:**
- Produces: `MultiGridQuestionElement` (with `columns` reverse rel, `rows` reverse rel, `REVEAL_TEMPLATE`, `build_answer`, `mark` added in Task 2), `MultiGridColumn(question FK, label, order)`, `MultiGridRow(question FK, statement, order, correct_columns M2M)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_multigrid.py
import pytest
from courses.models import ELEMENT_MODELS
from courses.models import MultiGridQuestionElement, MultiGridColumn, MultiGridRow


def test_multigrid_in_element_models():
    assert "multigridquestionelement" in ELEMENT_MODELS
    assert len(ELEMENT_MODELS) == 28
    assert ELEMENT_MODELS[-1] == "multigridquestionelement"


@pytest.mark.django_db
def test_row_owns_a_set_of_correct_columns():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    c = MultiGridColumn.objects.create(question=q, label="C")
    row = MultiGridRow.objects.create(question=q, statement="row1")
    row.correct_columns.set([a, c])
    assert {col.pk for col in row.correct_columns.all()} == {a.pk, c.pk}
    # deleting a column drops it from the row's set (no PROTECT)
    b_pk = b.pk
    c.delete()
    assert {col.pk for col in row.correct_columns.all()} == {a.pk}
    assert MultiGridColumn.objects.filter(pk=b_pk).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_multigrid.py -v`
Expected: FAIL with `ImportError` / `cannot import name 'MultiGridQuestionElement'`.

- [ ] **Step 3: Add the model to `ELEMENT_MODELS`**

In `courses/models.py`, append to the `ELEMENT_MODELS` list (currently ending `"stepperelement",`):

```python
    "stepperelement",
    "multigridquestionelement",
]
```

- [ ] **Step 4: Add the three model classes**

In `courses/models.py`, immediately after the `GridRow` class (~line 1606, before `ZONE_COORD_EPSILON`), add:

```python
class MultiGridQuestionElement(QuestionElement):
    """Multi-select grid: N statements each answered by a *set* of columns.
    All-or-nothing per row, grid-level partial credit. Sibling of
    ChoiceGridQuestionElement, but a row owns a ManyToMany set of correct
    columns instead of a single FK."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_multigrid.html"
    elements = GenericRelation(Element)

    # build_answer / mark added in Task 2.


class MultiGridColumn(models.Model):
    question = models.ForeignKey(
        MultiGridQuestionElement, on_delete=models.CASCADE, related_name="columns"
    )
    label = models.CharField(max_length=500)  # plain text + KaTeX; never sanitised
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.label


class MultiGridRow(models.Model):
    question = models.ForeignKey(
        MultiGridQuestionElement, on_delete=models.CASCADE, related_name="rows"
    )
    statement = models.CharField(max_length=500)  # plain text + KaTeX
    # Set of correct columns. M2M (not a FK): deleting a column simply drops it
    # from every row's set (no PROTECT dance). related_name="+" (no reverse needed).
    correct_columns = models.ManyToManyField(MultiGridColumn, related_name="+")
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.statement
```

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0046_multigridquestionelement_and_more.py` with `CreateModel` for the three models (M2M through auto-table) + an `AlterField` on `element.content_type` appending `multigridquestionelement` to `limit_choices_to`. Confirm it depends on `0045_stepper`.

- [ ] **Step 6: Verify migration is complete**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (exit 0).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_models_multigrid.py -v`
Expected: PASS (both tests).

- [ ] **Step 8: Commit**

```bash
git add courses/models.py courses/migrations/0046_multigridquestionelement_and_more.py tests/test_models_multigrid.py
git commit -m "feat(multigrid): models + migration (28th ELEMENT_MODELS entry)"
```

---

### Task 2: Marking (`build_answer`, `mark`) + `answer_is_empty` fix

**Files:**
- Modify: `courses/models.py` (add `build_answer` + `mark` to `MultiGridQuestionElement`)
- Modify: `courses/quiz.py` (`answer_is_empty` ~line 54)
- Test: `tests/test_marking_multigrid.py`, `tests/test_answer_is_empty.py`

**Interfaces:**
- Consumes: `MultiGridQuestionElement`, `MultiGridColumn`, `MultiGridRow` (Task 1); `MarkResult` (already imported in models.py).
- Produces: `build_answer(post) -> list[list[int]]` (positional per row, sorted pk list, `[]` = untouched); `mark(answer) -> MarkResult(correct, fraction, reveal)` where `reveal` is a tuple of `{statement, correct_labels: list[str], chosen_labels: list[str], is_correct}` in **column order**.

- [ ] **Step 1: Write the failing marking test**

```python
# tests/test_marking_multigrid.py
import pytest
from django.http import QueryDict
from courses.models import MultiGridQuestionElement, MultiGridColumn, MultiGridRow


def _grid():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    c = MultiGridColumn.objects.create(question=q, label="C")
    r1 = MultiGridRow.objects.create(question=q, statement="r1")
    r1.correct_columns.set([a, c])
    r2 = MultiGridRow.objects.create(question=q, statement="r2")
    r2.correct_columns.set([b])
    return q, (a, b, c), (r1, r2)


@pytest.mark.django_db
def test_build_answer_reads_getlist_and_sorts():
    q, (a, b, c), (r1, r2) = _grid()
    post = QueryDict(mutable=True)
    post.update({})
    post.setlist(f"row_{r1.pk}", [str(c.pk), str(a.pk)])  # unsorted
    post.setlist(f"row_{r2.pk}", [])  # untouched
    ans = q.build_answer(post)
    assert ans == [[a.pk, c.pk], []]  # sorted, [] for untouched


@pytest.mark.django_db
def test_build_answer_drops_forged_ids():
    q, (a, b, c), (r1, r2) = _grid()
    post = QueryDict(mutable=True)
    post.setlist(f"row_{r1.pk}", [str(a.pk), "999999", "notanint"])
    ans = q.build_answer(post)
    assert ans[0] == [a.pk]


@pytest.mark.django_db
def test_mark_all_or_nothing_per_row():
    q, (a, b, c), (r1, r2) = _grid()
    # r1 exact, r2 exact -> fully correct
    res = q.mark([[a.pk, c.pk], [b.pk]])
    assert res.correct is True
    assert res.fraction == 1.0
    # r1 partial (missing c) -> row 0, r2 exact -> 1/2
    res = q.mark([[a.pk], [b.pk]])
    assert res.correct is False
    assert res.fraction == 0.5
    # r1 over-selected -> 0 for that row
    res = q.mark([[a.pk, b.pk, c.pk], [b.pk]])
    assert res.fraction == 0.5


@pytest.mark.django_db
def test_mark_empty_grid_is_zero():
    q, (a, b, c), (r1, r2) = _grid()
    res = q.mark([[], []])
    assert res.correct is False
    assert res.fraction == 0.0


@pytest.mark.django_db
def test_mark_reveal_labels_in_column_order():
    q, (a, b, c), (r1, r2) = _grid()
    res = q.mark([[c.pk, a.pk], []])
    item = res.reveal[0]
    assert item["statement"] == "r1"
    assert item["correct_labels"] == ["A", "C"]  # column order, not set order
    assert item["chosen_labels"] == ["A", "C"]
    assert item["is_correct"] is True


@pytest.mark.django_db
def test_mark_defends_against_type_and_length_drift():
    q, (a, b, c), (r1, r2) = _grid()
    # scalar / None entries coerced to []; short answer padded
    res = q.mark([None])  # too short + wrong type
    assert res.fraction == 0.0  # neither row correct, no crash
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_marking_multigrid.py -v`
Expected: FAIL (`build_answer`/`mark` not defined on `MultiGridQuestionElement`).

- [ ] **Step 3: Implement `build_answer` + `mark`**

In `courses/models.py`, inside `MultiGridQuestionElement` (replacing the `# build_answer / mark added in Task 2.` comment):

```python
    def build_answer(self, post):
        rows = list(self.rows.all())
        valid = {c.pk for c in self.columns.all()}
        out = []
        for row in rows:
            chosen = set()
            for raw in post.getlist(f"row_{row.pk}"):
                try:
                    pk = int(raw)
                except (TypeError, ValueError):
                    continue
                if pk in valid:
                    chosen.add(pk)
            out.append(sorted(chosen))
        return out

    def mark(self, answer):
        rows = list(self.rows.all())
        n = len(rows)
        answer = (list(answer) + [[]] * n)[:n]  # pad/truncate; guards length drift
        cols = list(self.columns.all())  # column order for deterministic reveal
        reveal = []
        n_correct = 0
        for i, row in enumerate(rows):
            entry = answer[i]
            chosen = set(entry) if isinstance(entry, (list, tuple)) else set()
            correct = {c.pk for c in row.correct_columns.all()}
            is_correct = chosen == correct
            if is_correct:
                n_correct += 1
            reveal.append(
                {
                    "statement": row.statement,
                    "correct_labels": [c.label for c in cols if c.pk in correct],
                    "chosen_labels": [c.label for c in cols if c.pk in chosen],
                    "is_correct": is_correct,
                }
            )
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=tuple(reveal),
        )
```

- [ ] **Step 4: Write the failing `answer_is_empty` regression test**

```python
# tests/test_answer_is_empty.py
from courses.quiz import answer_is_empty


def test_answer_is_empty_nested_lists():
    assert answer_is_empty([[], [], []]) is True
    assert answer_is_empty([[3], []]) is False


def test_answer_is_empty_flat_preserved():
    assert answer_is_empty(["", ""]) is True
    assert answer_is_empty(["", 3]) is False


def test_answer_is_empty_set_preserved():
    # ChoiceQuestionElement.build_answer returns a set — must not regress
    assert answer_is_empty(set()) is True
    assert answer_is_empty({3}) is False


def test_answer_is_empty_scalars_preserved():
    assert answer_is_empty("") is True
    assert answer_is_empty("x") is False
    assert answer_is_empty(None) is True
```

- [ ] **Step 5: Run to verify the nested case fails**

Run: `uv run pytest tests/test_answer_is_empty.py -v`
Expected: `test_answer_is_empty_nested_lists` FAILS (`[[], [], []]` currently judged non-empty).

- [ ] **Step 6: Fix `answer_is_empty` surgically**

In `courses/quiz.py`, replace the function (only the `list`/`tuple` branch gains recursion; `set`/`frozenset`, `str`, and the scalar fallback are preserved byte-for-byte):

```python
def answer_is_empty(answer):
    """True iff a build_answer() payload carries nothing markable."""
    if isinstance(answer, (set, frozenset)):
        return not answer
    if isinstance(answer, str):
        return not answer.strip()
    if isinstance(answer, (list, tuple)):
        # Recurse so a list-of-lists (multigrid: [[], [], []]) reads as empty,
        # while the flat cases (matrix ["", 3]) are unchanged.
        return all(answer_is_empty(v) for v in answer)
    return not answer
```

Note the leaf semantics: a string leaf hits the `str` branch (`.strip()`), a nested list recurses, and any other scalar leaf (an `int` pk) hits `return not answer` — `not 3` is `False` (non-empty), `not 0` would be `True` but pks are always ≥1, so this matches the old `str(v).strip()` behaviour for real payloads without a `TypeError`.

- [ ] **Step 7: Run both test files**

Run: `uv run pytest tests/test_marking_multigrid.py tests/test_answer_is_empty.py -v`
Expected: PASS (all).

- [ ] **Step 8: Commit**

```bash
git add courses/models.py courses/quiz.py tests/test_marking_multigrid.py tests/test_answer_is_empty.py
git commit -m "feat(multigrid): build_answer + mark + answer_is_empty nested-list fix"
```

---

### Task 3: Student render tag + templates

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (add `render_multigrid` + `_multigrid_row_cells` after `render_choice_grid`)
- Create: `templates/courses/elements/multigridquestionelement.html`
- Create: `templates/courses/elements/_reveal_multigrid.html`
- Test: `tests/test_render_multigrid.py`

**Interfaces:**
- Consumes: `build_answer`/`mark` reveal shape (Task 2); `MultiGridColumn`/`MultiGridRow` (Task 1).
- Produces: `{% render_multigrid el submitted_values %}` tag — a `<table class="multigrid">` with a checkbox per cell (`name="row_{rowpk}" value="{colpk}"`), checked when `colpk in submitted_values[i]`.

- [ ] **Step 1: Write the failing render test**

```python
# tests/test_render_multigrid.py
import pytest
from django.template import Context, Template
from courses.models import MultiGridQuestionElement, MultiGridColumn, MultiGridRow


def _grid():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    r1 = MultiGridRow.objects.create(question=q, statement="r1")
    r1.correct_columns.set([a])
    return q, (a, b), r1


@pytest.mark.django_db
def test_render_multigrid_checkboxes_and_names():
    q, (a, b), r1 = _grid()
    html = Template(
        "{% load courses_extras %}{% render_multigrid el %}"
    ).render(Context({"el": q}))
    assert 'type="checkbox"' in html
    assert f'name="row_{r1.pk}"' in html
    assert f'value="{a.pk}"' in html
    assert "checked" not in html  # nothing submitted -> nothing checked


@pytest.mark.django_db
def test_render_multigrid_prechecks_submitted():
    q, (a, b), r1 = _grid()
    html = Template(
        "{% load courses_extras %}{% render_multigrid el sv %}"
    ).render(Context({"el": q, "sv": [[a.pk]]}))
    # the A cell is checked, the B cell is not
    assert f'value="{a.pk}" checked' in html
    assert f'value="{b.pk}" checked' not in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_render_multigrid.py -v`
Expected: FAIL (`Invalid block tag 'render_multigrid'`).

- [ ] **Step 3: Add the render tag**

In `courses/templatetags/courses_extras.py`, after `render_choice_grid`/`_grid_row_cells`, add (mirrors them, radios→checkboxes, single chosen→chosen list):

```python
@register.simple_tag
def render_multigrid(el, submitted_values=None):
    """Render a multi-select grid: a <table> whose header lists the column labels
    and whose body has one row per statement carrying a checkbox group
    (name="row_<rowpk>", value="<colpk>"), each checked when its col pk is in that
    row's positional chosen-pk list. See courses.models.MultiGridQuestionElement."""
    cols = list(el.columns.all())
    rows = list(el.rows.all())
    sv = submitted_values or []
    head = format_html_join("", "<th>{}</th>", ((c.label,) for c in cols))
    body = format_html_join(
        "",
        '<tr><td class="multigrid__stmt">{}</td>{}</tr>',
        (
            (row.statement, _multigrid_row_cells(row, cols, sv[i] if i < len(sv) else []))
            for i, row in enumerate(rows)
        ),
    )
    return format_html(
        '<table class="multigrid"><thead><tr><th></th>{}</tr></thead>'
        "<tbody>{}</tbody></table>",
        head,
        body,
    )


def _multigrid_row_cells(row, cols, chosen):
    # chosen is a list of chosen col-pks (Task 2). Branch between two format_html
    # templates so `checked` is a literal, not a value arg — no mark_safe, no escape.
    chosen_set = set(chosen or [])
    cells = []
    for c in cols:
        if c.pk in chosen_set:
            cells.append(
                format_html(
                    '<td><label><input type="checkbox" name="row_{}" value="{}" checked>'
                    "</label></td>",
                    row.pk,
                    c.pk,
                )
            )
        else:
            cells.append(
                format_html(
                    '<td><label><input type="checkbox" name="row_{}" value="{}">'
                    "</label></td>",
                    row.pk,
                    c.pk,
                )
            )
    return format_html_join("", "{}", ((cell,) for cell in cells))
```

- [ ] **Step 4: Create the student template**

`templates/courses/elements/multigridquestionelement.html` (mirror of `choicegridquestionelement.html`, class `el--multigrid`, tag `render_multigrid`, scroll wrapper `multigrid-scroll`):

```django
{% load i18n courses_extras %}
<div class="el el--question el--multigrid" data-question>
  {% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}
  {% if element %}
  <form class="question__form" method="post" action="{{ action_url }}">
    {% csrf_token %}
    <fieldset {% if quiz_submitted or locked %}disabled{% endif %}
              style="border:0;padding:0;margin:0;">
      <div class="multigrid-scroll">
        {% if element.pk == feedback_for_pk %}
          {% render_multigrid el submitted_values %}
        {% else %}
          {% render_multigrid el %}
        {% endif %}
      </div>
    </fieldset>
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% else %}
    <div class="multigrid-scroll">{% render_multigrid el %}</div>
  {% endif %}
</div>
```

- [ ] **Step 5: Create the reveal template**

`templates/courses/elements/_reveal_multigrid.html` (mirror of `_reveal_choicegrid.html`; correct/chosen are now *lists* joined with commas). Uses a `join` filter over the label lists:

```django
{% load i18n %}
<ul class="question__reveal question__reveal--grid">
  {% for item in mark_result.reveal %}
    <li class="question__reveal-item {% if item.is_correct %}answer-correct{% else %}answer-wrong{% endif %}">
      <span class="question__reveal-left">{{ item.statement }}</span>
      {% if item.is_correct %}
        <span class="question__tick" aria-hidden="true">✓</span>
      {% else %}
        <span class="question__glyph" aria-hidden="true">✗</span>
        <span class="question__reveal-text">
          {% trans "Correct answers:" %} <strong>{{ item.correct_labels|join:", " }}</strong>
          {% if item.chosen_labels %}
            <span class="question__reveal-chosen">({% trans "you chose" %} {{ item.chosen_labels|join:", " }})</span>
          {% endif %}
        </span>
      {% endif %}
    </li>
  {% endfor %}
</ul>
{% comment %}
  el.explanation is intentionally NOT rendered here: the containing feedback
  partials and quiz_results.html already render it (double-render guard), exactly
  as _reveal_choicegrid.html does.
{% endcomment %}
```

- [ ] **Step 6: Run the render tests**

Run: `uv run pytest tests/test_render_multigrid.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/templatetags/courses_extras.py templates/courses/elements/multigridquestionelement.html templates/courses/elements/_reveal_multigrid.html tests/test_render_multigrid.py
git commit -m "feat(multigrid): render_multigrid tag + student + reveal templates"
```

---

### Task 4: Forms + formsets

**Files:**
- Modify: `courses/element_forms.py` (add form, column form, row form, two base formsets, factories, `build_*` helpers; add `multigridquestion` to `FORM_FOR_TYPE`; import the models)
- Test: `tests/test_forms_multigrid.py`

**Interfaces:**
- Consumes: `MultiGridQuestionElement`/`MultiGridColumn`/`MultiGridRow` (Task 1); `_MarkingFieldsMixin` (existing).
- Produces: `MultiGridQuestionElementForm`, `build_multigrid_columns_formset(*, data, files, instance, prefix="columns")`, `build_multigrid_rows_formset(*, data, files, instance, prefix="rows")`; `_MultiGridRowForm.correct_temp_ids` is a comma-joined hidden `CharField` (multi-value analogue of Matrix's `correct_temp_id`); `FORM_FOR_TYPE["multigridquestion"]`.

- [ ] **Step 1: Write the failing formset test**

```python
# tests/test_forms_multigrid.py
import pytest
from courses.element_forms import (
    build_multigrid_columns_formset,
    build_multigrid_rows_formset,
)


def _mgmt(prefix, total):
    return {
        f"{prefix}-TOTAL_FORMS": str(total),
        f"{prefix}-INITIAL_FORMS": "0",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }


@pytest.mark.django_db
def test_rows_formset_requires_at_least_one_correct_temp_id():
    data = {}
    data.update(_mgmt("columns", 1))
    data.update({"columns-0-label": "A", "columns-0-temp_id": "t1"})
    data.update(_mgmt("rows", 1))
    data.update({"rows-0-statement": "r1", "rows-0-correct_temp_ids": ""})  # empty
    rows = build_multigrid_rows_formset(data=data, instance=None)
    assert not rows.is_valid()


@pytest.mark.django_db
def test_rows_formset_accepts_comma_joined_ids():
    data = {}
    data.update(_mgmt("rows", 1))
    data.update({"rows-0-statement": "r1", "rows-0-correct_temp_ids": "t1,t2"})
    rows = build_multigrid_rows_formset(data=data, instance=None)
    assert rows.is_valid(), rows.errors


@pytest.mark.django_db
def test_columns_formset_requires_one_column():
    data = {}
    data.update(_mgmt("columns", 0))
    cols = build_multigrid_columns_formset(data=data, instance=None)
    assert not cols.is_valid()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_forms_multigrid.py -v`
Expected: FAIL (`cannot import name 'build_multigrid_columns_formset'`).

- [ ] **Step 3: Import the models**

In `courses/element_forms.py`, near the other model imports (~line 18–29), add:

```python
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridColumn
from courses.models import MultiGridRow
```

- [ ] **Step 4: Add the forms + formsets + factories**

In `courses/element_forms.py`, after the choicegrid block (after `build_choicegrid_rows_formset`, ~line 948), add:

```python
class MultiGridQuestionElementForm(_MarkingFieldsMixin, forms.ModelForm):
    class Meta:
        model = MultiGridQuestionElement
        fields = ["stem", "explanation", "marking_mode", "max_attempts", "max_marks"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
        }


class _MultiGridColumnForm(forms.ModelForm):
    temp_id = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = MultiGridColumn
        fields = ["label"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed a saved column's temp_id from its pk on edit, so the row checkbox
        # sets (which seed correct_temp_ids from the columns' pks) reconstruct the
        # client-only column<->row linkage. New columns keep a blank temp_id.
        if self.instance and self.instance.pk:
            self.fields["temp_id"].initial = str(self.instance.pk)

    def has_changed(self):
        # Key on the visible field only so a blank added column (whose hidden
        # temp_id JS fills) is pruned, not validated into a spurious 422.
        return "label" in self.changed_data


class BaseMultiGridColumnFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank column."""

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


def _parse_temp_ids(raw):
    """Comma-joined temp-id string -> list of non-blank ids (order-preserving)."""
    return [t for t in (raw or "").split(",") if t.strip()]


class _MultiGridRowForm(forms.ModelForm):
    # Comma-joined set of correct-column temp-ids. required=False: a blank added row
    # must not hard-fail; completeness of a KEPT row is enforced in the formset clean.
    correct_temp_ids = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = MultiGridRow
        # correct_columns M2M resolved in save_element, not bound here
        fields = ["statement"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed correct_temp_ids from the saved M2M (column pks == their temp_ids) on
        # edit, so the rendered checkboxes restore the saved set and save_element
        # re-resolves it. Guarded on pk (unsaved rows have no M2M).
        if self.instance and self.instance.pk:
            pks = list(self.instance.correct_columns.values_list("pk", flat=True))
            if pks:
                self.fields["correct_temp_ids"].initial = ",".join(
                    str(pk) for pk in pks
                )

    def has_changed(self):
        return "statement" in self.changed_data


class BaseMultiGridRowFormSet(forms.BaseInlineFormSet):
    """>=1 non-deleted, non-blank row; each kept row's raw correct_temp_ids must
    parse to >=1 id (a within-formset check; surviving-column resolution and the
    zero-survivors error live in save_element)."""

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
            if not _parse_temp_ids(f.cleaned_data.get("correct_temp_ids")):
                raise forms.ValidationError(
                    _("Each row needs at least one correct column.")
                )


MultiGridColumnFormSet = inlineformset_factory(
    MultiGridQuestionElement,
    MultiGridColumn,
    form=_MultiGridColumnForm,
    formset=BaseMultiGridColumnFormSet,
    extra=0,
    can_delete=True,
)
MultiGridRowFormSet = inlineformset_factory(
    MultiGridQuestionElement,
    MultiGridRow,
    form=_MultiGridRowForm,
    formset=BaseMultiGridRowFormSet,
    extra=0,
    can_delete=True,
)


def build_multigrid_columns_formset(
    *, data=None, files=None, instance=None, prefix="columns"
):
    return MultiGridColumnFormSet(data=data, files=files, instance=instance, prefix=prefix)


def build_multigrid_rows_formset(
    *, data=None, files=None, instance=None, prefix="rows"
):
    return MultiGridRowFormSet(data=data, files=files, instance=instance, prefix=prefix)
```

- [ ] **Step 5: Register in `FORM_FOR_TYPE`**

In the `FORM_FOR_TYPE` dict (~line 1367, next to `"choicegridquestion": ChoiceGridQuestionElementForm,`), add:

```python
    "multigridquestion": MultiGridQuestionElementForm,
```

- [ ] **Step 6: Run the formset tests**

Run: `uv run pytest tests/test_forms_multigrid.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/element_forms.py tests/test_forms_multigrid.py
git commit -m "feat(multigrid): element form + two inline formsets (M2M temp-id linkage)"
```

---

### Task 5: `save_element` builder branch

**Files:**
- Modify: `courses/builder.py` (add `elif type_key == "multigridquestion":` branch in `save_element`)
- Test: `tests/test_save_multigrid.py`

**Interfaces:**
- Consumes: `MultiGridQuestionElementForm`, `build_multigrid_*_formset`, `_parse_temp_ids` (Task 4); `ElementFormInvalid` (existing, accepts `form, formset, formset2`).
- Produces: persisted `MultiGridQuestionElement` with columns + rows + each row's `correct_columns` M2M set from resolved temp-ids.

- [ ] **Step 1: Write the failing save tests** (mirror `tests/test_save_choicegrid.py` exactly)

```python
# tests/test_save_multigrid.py
import pytest

from courses.builder import ElementFormInvalid
from courses.builder import save_element
from courses.models import Element
from courses.models import MultiGridQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _make_course_with_unit(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    return course, unit


def _post(unit, cols, rows, **extra):
    """cols: list[(temp_id, label)]; rows: list[(statement, [temp_ids])]."""
    data = {
        "unit_token": unit.updated.isoformat(),
        "unit": str(unit.pk),
        "stem": "Pick the truths",
        "explanation": "",
        "marking_mode": "A",
        "max_attempts": "0",
        "max_marks": "1",
        "columns-TOTAL_FORMS": str(len(cols)),
        "columns-INITIAL_FORMS": "0",
        "columns-MIN_NUM_FORMS": "0",
        "columns-MAX_NUM_FORMS": "1000",
        "rows-TOTAL_FORMS": str(len(rows)),
        "rows-INITIAL_FORMS": "0",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
    }
    for i, (tid, label) in enumerate(cols):
        data[f"columns-{i}-temp_id"] = tid
        data[f"columns-{i}-label"] = label
    for i, (stmt, tids) in enumerate(rows):
        data[f"rows-{i}-statement"] = stmt
        data[f"rows-{i}-correct_temp_ids"] = ",".join(tids)
    data.update(extra)
    return data


def test_save_creates_grid_with_m2m(client):
    course, unit = _make_course_with_unit(client)
    data = _post(unit, [("t1", "A"), ("t2", "B"), ("t3", "C")],
                 [("r1", ["t1", "t3"]), ("r2", ["t2"])])
    save_element(course, unit.pk, "multigridquestion", "new", data, {})
    q = MultiGridQuestionElement.objects.get()
    assert [c.label for c in q.columns.all()] == ["A", "B", "C"]
    r1, r2 = list(q.rows.all())
    assert {c.label for c in r1.correct_columns.all()} == {"A", "C"}
    assert {c.label for c in r2.correct_columns.all()} == {"B"}


def test_save_rejects_row_with_no_correct(client):
    course, unit = _make_course_with_unit(client)
    data = _post(unit, [("t1", "A")], [("r1", [])])
    with pytest.raises(ElementFormInvalid):
        save_element(course, unit.pk, "multigridquestion", "new", data, {})
    assert not MultiGridQuestionElement.objects.exists()  # atomic rollback
```

Also add the two spec-required edit-path tests (they mirror `test_save_choicegrid.py`'s `test_edit_forms_seed_temp_ids_from_pk` and `test_edit_delete_column_and_repoint_same_submission`, generalised to the M2M set):

```python
def test_edit_row_form_seeds_correct_temp_ids_from_m2m(client):
    # The temp-id linkage is client-only; on edit the row form must seed
    # correct_temp_ids from the saved correct_columns pks (guards the Matrix edit-drop
    # bug, generalised to a set). Column pk == its temp_id.
    from courses.element_forms import _MultiGridRowForm
    from courses.models import MultiGridColumn, MultiGridRow

    q = MultiGridQuestionElement.objects.create(stem="s")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    MultiGridColumn.objects.create(question=q, label="C")
    row = MultiGridRow.objects.create(question=q, statement="x")
    row.correct_columns.set([a, b])
    initial = _MultiGridRowForm(instance=row).fields["correct_temp_ids"].initial
    assert set(initial.split(",")) == {str(a.pk), str(b.pk)}


def test_edit_delete_a_correct_column_repoints_and_errors_only_when_empty(client):
    # Delete one of a row's two correct columns in one submission -> succeeds, row keeps
    # the other. Delete the row's ONLY correct column -> ElementFormInvalid.
    course, unit = _make_course_with_unit(client)
    data = _post(unit, [("t1", "A"), ("t2", "B")], [("r1", ["t1", "t2"])])
    save_element(course, unit.pk, "multigridquestion", "new", data, {})
    q = MultiGridQuestionElement.objects.get()
    cols = list(q.columns.all())  # [A, B], pk == server temp_id on edit
    row = q.rows.get()
    join = Element.objects.get()
    unit.refresh_from_db()

    def _edit(delete_idx, row_correct):
        d = {
            "unit_token": unit.updated.isoformat(), "unit": str(unit.pk),
            "stem": "Pick the truths", "explanation": "", "marking_mode": "A",
            "max_attempts": "0", "max_marks": "1",
            "columns-TOTAL_FORMS": "2", "columns-INITIAL_FORMS": "2",
            "columns-MIN_NUM_FORMS": "0", "columns-MAX_NUM_FORMS": "1000",
            "columns-0-id": str(cols[0].pk), "columns-0-label": "A",
            "columns-0-temp_id": str(cols[0].pk),
            "columns-1-id": str(cols[1].pk), "columns-1-label": "B",
            "columns-1-temp_id": str(cols[1].pk),
            "rows-TOTAL_FORMS": "1", "rows-INITIAL_FORMS": "1",
            "rows-MIN_NUM_FORMS": "0", "rows-MAX_NUM_FORMS": "1000",
            "rows-0-id": str(row.pk), "rows-0-statement": "r1",
            "rows-0-correct_temp_ids": ",".join(str(cols[i].pk) for i in row_correct),
        }
        d[f"columns-{delete_idx}-DELETE"] = "on"
        return d

    # delete B (idx 1); row keeps A -> succeeds
    save_element(course, unit.pk, "multigridquestion", str(join.pk), _edit(1, [0]), {})
    q.refresh_from_db()
    assert q.columns.count() == 1
    assert {c.label for c in q.rows.get().correct_columns.all()} == {"A"}

    # now delete the surviving A (idx 0) leaving the row with zero -> invalid
    cols2 = list(q.columns.all())  # [A]
    row2 = q.rows.get()
    unit.refresh_from_db()
    bad = {
        "unit_token": unit.updated.isoformat(), "unit": str(unit.pk),
        "stem": "Pick the truths", "explanation": "", "marking_mode": "A",
        "max_attempts": "0", "max_marks": "1",
        "columns-TOTAL_FORMS": "1", "columns-INITIAL_FORMS": "1",
        "columns-MIN_NUM_FORMS": "0", "columns-MAX_NUM_FORMS": "1000",
        "columns-0-id": str(cols2[0].pk), "columns-0-label": "A",
        "columns-0-temp_id": str(cols2[0].pk), "columns-0-DELETE": "on",
        "rows-TOTAL_FORMS": "1", "rows-INITIAL_FORMS": "1",
        "rows-MIN_NUM_FORMS": "0", "rows-MAX_NUM_FORMS": "1000",
        "rows-0-id": str(row2.pk), "rows-0-statement": "r1",
        "rows-0-correct_temp_ids": str(cols2[0].pk),
    }
    with pytest.raises(ElementFormInvalid):
        save_element(course, unit.pk, "multigridquestion", str(join.pk), bad, {})
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_save_multigrid.py -v`
Expected: FAIL (no `multigridquestion` branch → falls through / raises).

- [ ] **Step 3: Add the `save_element` branch**

In `courses/builder.py`, add after the `choicegridquestion` branch (~line 445), mirroring it but with the M2M resolution:

```python
    elif type_key == "multigridquestion":
        from courses.element_forms import MultiGridQuestionElementForm
        from courses.element_forms import build_multigrid_columns_formset
        from courses.element_forms import build_multigrid_rows_formset
        from courses.element_forms import _parse_temp_ids

        form = MultiGridQuestionElementForm(data=post_data, instance=instance)
        col_fs = build_multigrid_columns_formset(
            data=post_data, files=files, instance=instance
        )
        row_fs = build_multigrid_rows_formset(
            data=post_data, files=files, instance=instance
        )
        if not form.is_valid() or not col_fs.is_valid() or not row_fs.is_valid():
            raise ElementFormInvalid(form, col_fs, row_fs)

        obj = form.save()

        # 1) Save/keep columns without applying deletions yet (deletions deferred).
        col_fs.instance = obj
        kept_cols = col_fs.save(commit=False)
        for col in kept_cols:
            col.save()
        # temp_id -> surviving MultiGridColumn, from NON-deleted column forms.
        temp_map = {}
        for f in col_fs.forms:
            cd = f.cleaned_data
            if not cd or cd.get("DELETE") or not cd.get("label"):
                continue
            temp_map[cd.get("temp_id") or str(f.instance.pk)] = f.instance

        # 2) Resolve + set the M2M for EVERY non-deleted row form (not just changed):
        #    deleting a column cascade-clears the M2M for untouched rows too, so each
        #    must be re-validated against surviving columns.
        row_fs.instance = obj
        row_fs.save(commit=False)  # populate .instance (incl. inline FK); persist nothing
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
            resolved = [
                temp_map[t] for t in _parse_temp_ids(cd.get("correct_temp_ids"))
                if t in temp_map
            ]
            if not resolved:  # zero surviving correct columns -> invalid
                raise ElementFormInvalid(form, col_fs, row_fs)
            rf.instance.save()  # need a pk before .set()
            rf.instance.correct_columns.set(resolved)

        # 3) Only now apply column deletions (M2M through-rows drop automatically).
        for dead_col in col_fs.deleted_objects:
            dead_col.delete()
```

- [ ] **Step 4: Run the save tests**

Run: `uv run pytest tests/test_save_multigrid.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/builder.py tests/test_save_multigrid.py
git commit -m "feat(multigrid): save_element branch (resolve temp-ids -> correct_columns M2M)"
```

---

### Task 6: Editor wiring (views_manage + edit partial)

**Files:**
- Modify: `courses/views_manage.py` (`element_add`/`element_save` allow-tuples; `_EDITOR_TYPE_LABELS`; `_render_open_form` branch; `element_form` edit branch)
- Create: `templates/courses/manage/editor/_edit_multigridquestion.html`
- Test: `tests/test_editor_multigrid_add.py`

**Interfaces:**
- Consumes: `build_multigrid_*_formset` (Task 4); the named context vars `columns_formset` / `rows_formset` already threaded by `_render_open_form`.
- Produces: a 200 add/edit render path for `multigridquestion`.

- [ ] **Step 1: Write the failing editor test** (mirror `tests/test_editor_choicegrid_add.py`)

```python
# tests/test_editor_multigrid_add.py
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_manage_element_add_renders_multigrid_editor_200(client):
    # element_add renders the open-form host, which auto-includes
    # _edit_multigridquestion.html. POST is required (the view reads
    # request.POST["type"] / ["unit"]; a GET 404s at the unit lookup).
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "multigridquestion", "unit": unit.pk},
    )
    assert resp.status_code == 200
    assert b"columns-TOTAL_FORMS" in resp.content
    assert b"rows-TOTAL_FORMS" in resp.content
    assert b"data-multigrid-editor" in resp.content
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_editor_multigrid_add.py -v`
Expected: FAIL — either `bad type` (400) or `TemplateDoesNotExist: .../_edit_multigridquestion.html`.

- [ ] **Step 3: Add `multigridquestion` to both allow-tuples**

In `courses/views_manage.py`, add `"multigridquestion",` to the `element_add` tuple (~line 926, next to `"choicegridquestion",`) AND the `element_save` tuple (~line 989).

- [ ] **Step 4: Add the editor label**

In `_EDITOR_TYPE_LABELS` (~line 762), add:

```python
    "multigridquestion": gettext_lazy("Multi-select grid"),
```

- [ ] **Step 5: Add the `_render_open_form` + `element_form` branches**

In `_render_open_form` (~line 827, after the choicegrid branch), add:

```python
    elif type_key == "multigridquestion" and formset is None:
        from courses.element_forms import build_multigrid_columns_formset
        from courses.element_forms import build_multigrid_rows_formset

        instance = form.instance if form.instance.pk else None
        formset = build_multigrid_columns_formset(instance=instance)
        formset2 = build_multigrid_rows_formset(instance=instance)
```

In `element_form` (edit, ~line 1070, after the choicegrid branch), add:

```python
    elif type_key == "multigridquestion":
        from courses.element_forms import build_multigrid_columns_formset
        from courses.element_forms import build_multigrid_rows_formset

        formset = build_multigrid_columns_formset(instance=el.content_object)
        formset2 = build_multigrid_rows_formset(instance=el.content_object)
```

- [ ] **Step 6: Create the edit partial**

`templates/courses/manage/editor/_edit_multigridquestion.html` — mirror of `_edit_choicegridquestion.html`, but each row shows a **checkbox per column** (multi-select) instead of a `<select>`, backed by a single hidden `correct_temp_ids` the JS keeps in sync. Uses named context vars `columns_formset`/`rows_formset`:

```django
{% load i18n %}
{% comment %}
Multi-select grid editor. Two inline formsets joined by client temp-ids: columns
(label + hidden temp_id) and rows (statement + a hidden correct_temp_ids comma-list +
a JS-built checkbox per current column). save_element resolves correct_temp_ids to the
correct_columns M2M after columns save. multigrid.js (Task 9) builds the per-row
checkboxes from the current columns and keeps correct_temp_ids in sync. Reads the two
named context vars columns_formset / rows_formset.
{% endcomment %}
<div class="el-editor el-editor--question el-editor--multigrid" data-multigrid-editor>
  <label class="el-editor__label">{% trans "Prompt (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="2">{{ form.stem.value|default:"" }}</textarea>
  </div>

  <label class="el-editor__label">{% trans "Columns (the answer options)" %}</label>
  <p class="el-editor__hint">{% trans "Each statement may have several correct columns." %}</p>
  {{ columns_formset.management_form }}
  <ul class="multigrid-cols" data-multigrid-cols>
    {% for f in columns_formset %}
      <li class="multigrid-col" data-multigrid-col>
        {{ f.id }}
        {{ f.temp_id }}
        {{ f.label }}
        {% if columns_formset.can_delete %}
          <label class="multigrid-col__del">{{ f.DELETE }} {% trans "Remove" %}</label>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
  <button type="button" class="btn btn--small btn--ghost" data-multigrid-add-col>＋ {% trans "Add column" %}</button>
  {% for e in columns_formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Statements (the rows)" %}</label>
  <p class="el-editor__hint">{% trans "Tick every correct column for each statement." %}</p>
  {{ rows_formset.management_form }}
  <ul class="multigrid-rows" data-multigrid-rows>
    {% for f in rows_formset %}
      <li class="multigrid-row" data-multigrid-row>
        {{ f.id }}
        {{ f.statement }}
        <input type="hidden" name="{{ f.correct_temp_ids.html_name }}" data-multigrid-correct
               value="{{ f.correct_temp_ids.value|default:'' }}">
        <span class="multigrid-row__checks" data-multigrid-checks></span>
        {% if rows_formset.can_delete %}
          <label class="multigrid-row__del">{{ f.DELETE }} {% trans "Remove" %}</label>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
  <button type="button" class="btn btn--small btn--ghost" data-multigrid-add-row>＋ {% trans "Add row" %}</button>
  {% for e in rows_formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  {% comment %}Clone blueprints for multigrid.js (__prefix__ renumbered client-side).{% endcomment %}
  <template data-multigrid-col-template>
    <li class="multigrid-col" data-multigrid-col>
      <input type="hidden" name="columns-__prefix__-temp_id" data-multigrid-temp-id>
      <input type="text" name="columns-__prefix__-label" maxlength="500">
      <label class="multigrid-col__del">
        <input type="checkbox" name="columns-__prefix__-DELETE"> {% trans "Remove" %}
      </label>
    </li>
  </template>
  <template data-multigrid-row-template>
    <li class="multigrid-row" data-multigrid-row>
      <input type="text" name="rows-__prefix__-statement" maxlength="500">
      <input type="hidden" name="rows-__prefix__-correct_temp_ids" data-multigrid-correct value="">
      <span class="multigrid-row__checks" data-multigrid-checks></span>
      <label class="multigrid-row__del">
        <input type="checkbox" name="rows-__prefix__-DELETE"> {% trans "Remove" %}
      </label>
    </li>
  </template>

  {% include "courses/manage/editor/_marking_fields.html" %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

- [ ] **Step 7: Run the editor test**

Run: `uv run pytest tests/test_editor_multigrid_add.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/editor/_edit_multigridquestion.html tests/test_editor_multigrid_add.py
git commit -m "feat(multigrid): editor add/edit wiring + _edit partial"
```

---

### Task 7: Transfer (export / validate / import)

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_multi_grid` + `SERIALIZERS`)
- Modify: `courses/transfer/payloads.py` (`_val_multi_grid` + `VALIDATORS`)
- Modify: `courses/transfer/importer.py` (`_build_multi_grid` + `BUILDERS`)
- Test: `tests/test_multigrid_transfer.py`

**Interfaces:**
- Consumes: models (Task 1); helpers `_question_fields`, `Q_KEYS`, `_check_question_fields`, `check_str`, `check_list`, `_exact_keys`, `_q_kwargs`, `_clean_save`, `_err` (all existing).
- Produces: transfer key `multi_grid`; `_build_multi_grid` returns `(question, [])` (saves rows + M2M internally).

- [ ] **Step 1: Write the failing transfer test**

```python
# tests/test_multigrid_transfer.py
import pytest
from courses.transfer.payloads import _val_multi_grid
from courses.transfer.schema import TransferError  # or wherever TransferError lives


def _payload(rows_correct):
    return {
        "stem": "s", "explanation": "", "marking_mode": "A",
        "max_attempts": 1, "max_marks": "1.00",
        "columns": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
        "rows": [{"statement": "r1", "correct": rc} for rc in rows_correct],
    }


def test_val_multi_grid_accepts_valid():
    assert _val_multi_grid(_payload([[0, 2], [1]]), "el1", {}) == set()


def test_val_multi_grid_rejects_scalar_correct():
    with pytest.raises(TransferError):
        _val_multi_grid(_payload([2]), "el1", {})  # correct must be a list


def test_val_multi_grid_rejects_out_of_range_ordinal():
    with pytest.raises(TransferError):
        _val_multi_grid(_payload([[5]]), "el1", {})


def test_val_multi_grid_rejects_empty_correct():
    with pytest.raises(TransferError):
        _val_multi_grid(_payload([[]]), "el1", {})
```

Then an end-to-end round-trip test mirroring the Matrix `tests/test_*choicegrid*transfer*.py` (build a grid, export the course, re-import, assert columns/rows/correct-sets reproduced). Read that Matrix test first and copy its export/import harness, swapping the element type.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_multigrid_transfer.py -v`
Expected: FAIL (`cannot import name '_val_multi_grid'`).

- [ ] **Step 3: Add the serializer**

In `courses/transfer/export.py`, after `_ser_choice_grid`, add (sorted ordinals, `{"label"}` dicts):

```python
def _ser_multi_grid(el, ids):
    cols = list(el.columns.all())
    index = {c.pk: i for i, c in enumerate(cols)}
    return {
        **_question_fields(el),
        "columns": [{"label": c.label} for c in cols],
        "rows": [
            {
                "statement": r.statement,
                "correct": sorted(index[c.pk] for c in r.correct_columns.all()),
            }
            for r in el.rows.all()
        ],
    }
```

Register in `SERIALIZERS` (next to the `choice_grid` entry): `"multi_grid": (MultiGridQuestionElement, _ser_multi_grid),` and import `MultiGridQuestionElement` at the top.

- [ ] **Step 4: Add the validator**

In `courses/transfer/payloads.py`, after `_val_choice_grid`, add (full mirror + list-assert + empty-reject + bounds):

```python
def _val_multi_grid(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["columns", "rows"], _("multi_grid data"))
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
        correct = check_list(r["correct"], "correct")  # must be a list, not a scalar
        if not correct:
            _err(_("Element '%(el)s': each row needs at least one correct column."), el=elid)
        for ordinal in correct:
            if not isinstance(ordinal, int) or not (0 <= ordinal < len(columns)):
                _err(_("Element '%(el)s': row correct-column out of range."), el=elid)
    return set()
```

Register in `VALIDATORS` (next to `choice_grid`): `"multi_grid": _val_multi_grid,`.

- [ ] **Step 5: Add the importer builder**

In `courses/transfer/importer.py`, after `_build_choice_grid`, add (saves cols + rows + M2M internally, returns `(question, [])`):

```python
def _build_multi_grid(data, assets):
    # DEVIATES from the flat-child-list contract: an M2M cannot be assigned before a
    # row has a pk, and the generic _create_elements loop has no post-save hook. So we
    # save columns, then save each row and set its correct_columns M2M HERE, and return
    # (question, []) so the generic loop does not re-process already-saved rows.
    q = _clean_save(MultiGridQuestionElement(**_q_kwargs(data)))
    saved_cols = []
    for c in data["columns"]:
        col = MultiGridColumn(question=q, label=c["label"])
        col.full_clean(exclude=["order"])
        col.save()
        saved_cols.append(col)
    for r in data["rows"]:
        row = MultiGridRow(question=q, statement=r["statement"])
        row.full_clean(exclude=["order"])
        row.save()
        row.correct_columns.set([saved_cols[i] for i in r["correct"]])
    return q, []  # rows already saved; nothing for the generic loop to do
```

Register in `BUILDERS` (next to `choice_grid`): `"multi_grid": _build_multi_grid,` and import the three models at the top.

- [ ] **Step 6: Run the transfer tests**

Run: `uv run pytest tests/test_multigrid_transfer.py -v`
Expected: PASS.

- [ ] **Step 7: Verify `FORMAT_VERSION` is untouched**

Run: `uv run python -c "from courses.transfer.schema import FORMAT_VERSION; assert FORMAT_VERSION == 4, FORMAT_VERSION; print('ok')"` (via `uv run`).
Expected: `ok`.

- [ ] **Step 8: Commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_multigrid_transfer.py
git commit -m "feat(multigrid): transfer export/validate/import (multi_grid key, M2M)"
```

---

### Task 8: Lesson/quiz wiring (prefetch, has_questions, has_math, labels, add-menu)

**Files:**
- Modify: `courses/views.py` (prefetch `multigrid_qs` at both sites; `question_models`; `_question_has_math` branch)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`)
- Modify: `templates/courses/manage/editor/_add_menu.html` (palette card)
- Test: `tests/test_context_multigrid.py`

**Interfaces:**
- Consumes: models (Task 1); student template (Task 3).
- Produces: a lesson containing a multigrid loads `question.js` (`has_questions` true) and prefetches `rows__correct_columns`.

- [ ] **Step 1: Write the failing lesson-wiring test** (mirror `tests/test_context_choicegrid.py`)

```python
# tests/test_context_multigrid.py
import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _enrolled_lesson(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _grid(unit, *, label="B"):
    q = MultiGridQuestionElement.objects.create(stem="Pick the truths")
    a = MultiGridColumn.objects.create(question=q, label="A")
    MultiGridColumn.objects.create(question=q, label=label)
    r1 = MultiGridRow.objects.create(question=q, statement="2+2=4")
    r1.correct_columns.set([a])
    Element.objects.create(unit=unit, content_object=q)
    return q


def _lesson_body(client, course, unit):
    return client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()


def test_multigrid_only_lesson_sets_has_questions(client):
    course, unit = _enrolled_lesson(client)
    _grid(unit)
    body = _lesson_body(client, course, unit)
    assert "courses/js/question.js" in body
    assert "multigrid" in body


def test_multigrid_math_in_column_sets_has_math(client):
    course, unit = _enrolled_lesson(client)
    _grid(unit, label=r"\(x^2\)")  # math in a column label
    body = _lesson_body(client, course, unit)
    assert "katex.min.js" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_context_multigrid.py -v`
Expected: FAIL (`question.js` absent — `MultiGridQuestionElement` not yet in `question_models`).

- [ ] **Step 3: Add prefetch + question_models + has_math (views.py)**

In `courses/views.py`:

Import (~line 35, next to `ChoiceGridQuestionElement`): `from courses.models import MultiGridQuestionElement`.

In `build_lesson_context` (~line 240) and the quiz/results builder (~line 682), add alongside the `choicegrid_qs` lines:

```python
    multigrid_qs = [q for q in questions if isinstance(q, MultiGridQuestionElement)]
```
and, alongside the `if choicegrid_qs:` prefetch:
```python
    if multigrid_qs:
        prefetch_related_objects(multigrid_qs, "columns", "rows", "rows__correct_columns")
```

In `question_models` (~line 257), add `MultiGridQuestionElement,` to the list.

In `_question_has_math` (~line 80), after the `ChoiceGridQuestionElement` branch, add:

```python
    if isinstance(q, MultiGridQuestionElement):
        return any(has_math_delimiters(c.label) for c in q.columns.all()) or any(
            has_math_delimiters(r.statement) for r in q.rows.all()
        )
```

- [ ] **Step 4: Add the manage label**

In `courses/templatetags/courses_manage_extras.py` `_ELEMENT_LABELS` (~line 44), add:

```python
    "multigridquestionelement": _("Multi-select grid"),
```

(No `element_summary` branch needed — `MultiGridQuestionElement` has a `stem` and falls through to the generic question-stem tail.)

- [ ] **Step 5: Add the add-menu card**

In `templates/courses/manage/editor/_add_menu.html`, in the **Questions** group (next to the Matrix card ~line 48, inside `{% if not nested %}`), add:

```django
      <button type="button" class="typecard" data-add-type="multigridquestion"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-switchgrid"/></svg>{% trans "Multi-select grid" %}</button>
```

- [ ] **Step 6: Run the lesson test**

Run: `uv run pytest tests/test_context_multigrid.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/views.py courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/_add_menu.html tests/test_context_multigrid.py
git commit -m "feat(multigrid): lesson/quiz wiring (prefetch, has_questions, has_math, add-menu)"
```

---

### Task 9: Editor JS enhancer + CSS

**Files:**
- Create: `courses/static/courses/js/multigrid.js`
- Modify: `courses/static/courses/js/editor.js` (re-init after preview swap)
- Modify: `templates/courses/manage/editor/editor.html` (`<script defer>` include)
- Modify: `courses/static/courses/css/courses.css` + `editor.css` (`.multigrid*` selectors)
- Test: `tests/test_editor_scripts.py` (add a `test_editor_loads_multigrid_js` alongside the existing `test_editor_loads_choicegrid_js`)

**Interfaces:**
- Consumes: the `_edit_multigridquestion.html` hooks (Task 6): `[data-multigrid-editor]`, `[data-multigrid-col]`, `[data-multigrid-row]`, `[data-multigrid-checks]`, `[data-multigrid-correct]`, the two `<template>` blueprints, `[data-multigrid-add-col]`/`[data-multigrid-add-row]`.
- Produces: `window.libliInitMultiGrid(root)` — assigns column temp_ids, renders a checkbox per column inside each row's `[data-multigrid-checks]`, keeps each row's hidden `correct_temp_ids` in sync, wires Add column/Add row/Remove, seeds a fresh grid.

- [ ] **Step 1: Write the failing script-loaded test** (add to `tests/test_editor_scripts.py`, mirroring `test_editor_loads_choicegrid_js`)

```python
# append to tests/test_editor_scripts.py
@pytest.mark.django_db
def test_editor_loads_multigrid_js(client):
    owner = make_login(client, "owner2")
    course = CourseFactory(slug="c2", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="U"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": "c2", "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert b"courses/js/multigrid.js" in resp.content
```

(The imports `pytest`, `reverse`, `make_login`, `CourseFactory`, `ContentNodeFactory` are already at the top of `test_editor_scripts.py`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_editor_scripts.py -v`
Expected: FAIL (`multigrid.js` not in the page).

- [ ] **Step 3: Write `multigrid.js`**

Create `courses/static/courses/js/multigrid.js`, adapting `choicegrid.js`: keep the column temp_id assignment, Add column/row, renumber, seedIfFresh, and delegated listeners; **replace the per-row `<select>` sync with a per-row checkbox set**. Core differences from `choicegrid.js`:

```javascript
(function () {
  "use strict";
  // Multi-select grid authoring enhancer. Mirrors choicegrid.js but each row shows a
  // checkbox per current column (multi-select) backed by a hidden comma-joined
  // correct_temp_ids field kept in sync. window.libliInitMultiGrid(root) re-syncs
  // after each editor.js fragment swap.
  var counter = 0;
  function freshTempId() { counter += 1; return "t" + Date.now().toString(36) + "-" + counter; }
  function cols(ed) { return Array.prototype.slice.call(ed.querySelectorAll("[data-multigrid-col]")); }
  function rows(ed) { return Array.prototype.slice.call(ed.querySelectorAll("[data-multigrid-row]")); }
  function tempIdInput(col) { return col.querySelector('input[name$="-temp_id"]'); }
  function labelInput(col) { return col.querySelector('input[name$="-label"]'); }
  function isDeleted(item) { var d = item.querySelector('input[name$="-DELETE"]'); return !!(d && d.checked); }
  function totalForms(ed, prefix) { return ed.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]'); }
  function editorOf(n) { return n.closest ? n.closest("[data-multigrid-editor]") : null; }

  function assignTempIds(ed) {
    cols(ed).forEach(function (col) { var ti = tempIdInput(col); if (ti && !ti.value) ti.value = freshTempId(); });
  }
  function currentColumns(ed) {
    return cols(ed).filter(function (c) { return !isDeleted(c); }).map(function (c) {
      var ti = tempIdInput(c), lbl = labelInput(c);
      return { tempId: ti ? ti.value : "", label: lbl ? lbl.value : "" };
    }).filter(function (c) { return c.tempId; });
  }
  // Rebuild each row's checkbox set from the current columns; a box is checked iff its
  // tempId is in the row's hidden correct_temp_ids (the single source of truth).
  function syncChecks(ed) {
    var columns = currentColumns(ed);
    rows(ed).forEach(function (row) {
      var hidden = row.querySelector("[data-multigrid-correct]");
      var host = row.querySelector("[data-multigrid-checks]");
      if (!hidden || !host) return;
      var chosen = (hidden.value || "").split(",").filter(Boolean);
      host.innerHTML = "";
      columns.forEach(function (col) {
        var lab = document.createElement("label");
        var box = document.createElement("input");
        box.type = "checkbox";
        box.value = col.tempId;
        box.checked = chosen.indexOf(col.tempId) !== -1;
        box.setAttribute("data-multigrid-box", "");
        lab.appendChild(box);
        lab.appendChild(document.createTextNode(" " + col.label));
        host.appendChild(lab);
      });
      // prune removed columns from the hidden value
      var live = columns.map(function (c) { return c.tempId; });
      hidden.value = chosen.filter(function (t) { return live.indexOf(t) !== -1; }).join(",");
    });
  }
  function writeHidden(row) {
    var hidden = row.querySelector("[data-multigrid-correct]");
    var host = row.querySelector("[data-multigrid-checks]");
    if (!hidden || !host) return;
    var picked = Array.prototype.slice.call(host.querySelectorAll("[data-multigrid-box]"))
      .filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
    hidden.value = picked.join(",");
  }
  function cloneTemplate(ed, sel) { var t = ed.querySelector("template[" + sel + "]"); return t ? t.content.firstElementChild.cloneNode(true) : null; }
  function renumber(node, idx) {
    Array.prototype.forEach.call(node.querySelectorAll("[name],[id],[for]"), function (el) {
      ["name", "id", "for"].forEach(function (a) { var v = el.getAttribute(a); if (v) el.setAttribute(a, v.split("__prefix__").join(idx)); });
    });
  }
  function addColumn(ed, label) {
    var total = totalForms(ed, "columns"), list = ed.querySelector("[data-multigrid-cols]");
    if (!total || !list) return null;
    var idx = parseInt(total.value, 10) || 0;
    var node = cloneTemplate(ed, "data-multigrid-col-template"); if (!node) return null;
    renumber(node, idx); list.appendChild(node); total.value = idx + 1;
    var ti = tempIdInput(node); if (ti) ti.value = freshTempId();
    if (label != null) { var lbl = labelInput(node); if (lbl) lbl.value = label; }
    return node;
  }
  function addRow(ed) {
    var total = totalForms(ed, "rows"), list = ed.querySelector("[data-multigrid-rows]");
    if (!total || !list) return null;
    var idx = parseInt(total.value, 10) || 0;
    var node = cloneTemplate(ed, "data-multigrid-row-template"); if (!node) return null;
    renumber(node, idx); list.appendChild(node); total.value = idx + 1;
    return node;
  }
  function seedIfFresh(ed) {
    if (cols(ed).length === 0 && rows(ed).length === 0) {
      addColumn(ed, ""); addColumn(ed, ""); addRow(ed); syncChecks(ed);
    }
  }
  function initEditor(ed) {
    assignTempIds(ed);
    if (!ed.dataset.multigridReady) { ed.dataset.multigridReady = "1"; seedIfFresh(ed); }
    syncChecks(ed);
  }
  document.addEventListener("click", function (e) {
    var ed = editorOf(e.target); if (!ed) return;
    if (e.target.closest("[data-multigrid-add-col]")) { addColumn(ed, ""); syncChecks(ed); return; }
    if (e.target.closest("[data-multigrid-add-row]")) { addRow(ed); syncChecks(ed); return; }
  });
  document.addEventListener("input", function (e) {
    var ed = editorOf(e.target); if (!ed) return;
    if (e.target.matches('[data-multigrid-col] input[name$="-label"]')) syncChecks(ed);
  });
  document.addEventListener("change", function (e) {
    var ed = editorOf(e.target); if (!ed) return;
    if (e.target.matches("[data-multigrid-box]")) { writeHidden(e.target.closest("[data-multigrid-row]")); return; }
    if (e.target.matches('[data-multigrid-col] input[name$="-DELETE"]')) syncChecks(ed);
  });
  window.libliInitMultiGrid = function (root) { (root || document).querySelectorAll("[data-multigrid-editor]").forEach(initEditor); };
  document.addEventListener("DOMContentLoaded", function () { window.libliInitMultiGrid(document); });
})();
```

- [ ] **Step 4: Wire the enhancer into `editor.js`**

In `courses/static/courses/js/editor.js`, next to the `libliInitChoiceGrid` re-init (~line 91), add:

```javascript
    if (editorPane && window.libliInitMultiGrid) window.libliInitMultiGrid(editorPane);  // re-sync multi-select grid checkboxes
```

- [ ] **Step 5: Include the script in `editor.html`**

In `templates/courses/manage/editor/editor.html`, next to the `choicegrid.js` include (~line 165), add:

```django
  <script src="{% static 'courses/js/multigrid.js' %}" defer></script>
```

- [ ] **Step 6: Add CSS**

In `courses/static/courses/css/courses.css`, find the `.choicegrid` table rules and add a parallel `.multigrid` block (same table/scroll styling — `grep -n "choicegrid" courses/static/courses/css/courses.css` and mirror each rule with `.multigrid`). In `editor.css`, mirror the `.el-editor--choicegrid` / `.choicegrid-cols` / `.choicegrid-rows` rules to `.el-editor--multigrid` / `.multigrid-cols` / `.multigrid-rows` / `.multigrid-row__checks` (lay the checkboxes out in a row). Keep it minimal — this is a visual mirror, not new design.

- [ ] **Step 7: Run the script test**

Run: `uv run pytest tests/test_editor_scripts.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/multigrid.js courses/static/courses/js/editor.js templates/courses/manage/editor/editor.html courses/static/courses/css/courses.css courses/static/courses/css/editor.css tests/test_editor_scripts.py
git commit -m "feat(multigrid): editor JS enhancer + CSS"
```

---

### Task 10: i18n (EN/PL) + full-suite DoD + e2e

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Create: `tests/test_e2e_multigrid.py`
- Test: full non-e2e suite + the new e2e file

**Interfaces:**
- Consumes: every prior task.

- [ ] **Step 1: Regenerate message catalogs**

Run: `uv run python manage.py makemessages -l en -l pl` (or the project's exact invocation — check `Makefile`/docs).

- [ ] **Step 2: Strip fuzzy matches + set PL translations**

Open both `.po` files. For EVERY new multigrid msgid (`"Multi-select grid"`, `"Each statement may have several correct columns."`, `"Tick every correct column for each statement."`, `"Add at least one column."` (if new), `"Add at least one row."` (if new), `"Each row needs at least one correct column."`, `"Correct answers:"`, the validator strings `"multi_grid data"`, `"at least one correct column"`, `"row correct-column out of range."` etc.): **remove any `#, fuzzy` flag line and any `#| msgid` line**, keep `python-format`/`python-brace-format` flags, and fill the PL `msgstr`. (This is the recurring `makemessages` fuzzy gotcha — the project's `test_po_catalog_clean` fails on ANY fuzzy.) Suggested PL:
  - "Multi-select grid" → "Siatka wielokrotnego wyboru"
  - "Each statement may have several correct columns." → "Każde stwierdzenie może mieć kilka poprawnych kolumn."
  - "Tick every correct column for each statement." → "Zaznacz wszystkie poprawne kolumny dla każdego stwierdzenia."
  - "Each row needs at least one correct column." → "Każdy wiersz wymaga co najmniej jednej poprawnej kolumny."
  - "Correct answers:" → "Poprawne odpowiedzi:"
  - (translate the remaining validator/hint strings in the same register as their choicegrid siblings.)

- [ ] **Step 3: Compile + assert catalogs clean**

Run: `uv run python manage.py compilemessages` then `uv run pytest tests/test_i18n_auth.py tests/test_tags_i18n.py -k "po_catalog or catalog_clean" -v` (match the real catalog-clean test name).
Expected: PASS (no fuzzy).

- [ ] **Step 4: Write the e2e test**

Create `tests/test_e2e_multigrid.py` — mirror `tests/test_e2e_choicegrid.py` (module `pytestmark = pytest.mark.e2e`; `_allow_async_unsafe` session fixture; `_login(page, live_server, username)`; a `_seed_multigrid(...)` helper built like `_seed_matrix` but using `MultiGridQuestionElement`/`MultiGridColumn`/`MultiGridRow` and `row.correct_columns.set([...])`, `make_verified_user`, `CourseFactory(slug=…, owner=…)`, `Enrollment.objects.get_or_create`, `ContentNodeFactory`). Drive REAL checkbox clicks (never `page.evaluate`): as the enrolled author, open the lesson (`data-question` locator), tick a *partially*-correct set in one row and the exact set in another, click **Check**, and assert the feedback shows per-row all-or-nothing (one row `answer-correct`, one `answer-wrong`) and the reveal lists the wrong row's correct column *set*. Seed one column label with `\(x^2\)` and assert a `.katex` node renders.

- [ ] **Step 5: Run the e2e file (foreground, explicit -m e2e)**

Run: `uv run pytest tests/test_e2e_multigrid.py -m e2e -v`
Expected: PASS. (Never run the whole suite with `-m e2e` in the background → runaway browsers.)

- [ ] **Step 6: Full non-e2e suite + lint gates (DoD)**

Run each and confirm green:
- `uv run pytest -n auto -q` (full suite, xdist; expect ~2830+ passed, 0 failed)
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run python manage.py makemigrations --check --dry-run`
- `uv run python manage.py check`

Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add locale/ tests/test_e2e_multigrid.py
git commit -m "feat(multigrid): EN/PL i18n + e2e + full-suite DoD"
```

---

## Self-Review

**Spec coverage:** Data model + M2M (Task 1); marking all-or-nothing + set-cast + defensive coerce + column-order reveal + `answer_is_empty` surgical fix incl. `set()` preservation (Task 2); POST `getlist` field convention + `render_multigrid` + `submitted_values` pre-check + reveal template double-render guard (Tasks 2–3); two-formset editor + ≥1-correct formset check + temp-id seeding (Task 4); `save_element` iterate-all-rows + drop-missing + zero→`ElementFormInvalid` + save-before-`.set()` + deferred column deletion (Task 5); add/edit render path + `_edit` partial + labels (Task 6); transfer `multi_grid` with sorted ordinals + `{"label"}` dicts + full validator + list-assert + reject-empty + `(question, [])` builder + no `FORMAT_VERSION` bump (Task 7); prefetch `rows__correct_columns` at both sites + `question_models` + `_question_has_math` + add-menu (Task 8); editor JS both wiring points + CSS (Task 9); EN/PL fuzzy-free + e2e + DoD (Task 10). All spec sections map to a task.

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to Task N" — every code step carries concrete code. Fixture-name caveats ("read the Matrix test first to copy exact fixtures") are explicit instructions, not placeholders, because the repo's test-fixture names are not in the dossier and must be matched to reality.

**Type consistency:** `correct_temp_ids` (comma-joined `CharField`) and `_parse_temp_ids` are used identically in Tasks 4 and 5; `build_answer` returns `list[list[int]]` consumed by `mark`, `render_multigrid`, and `answer_is_empty` consistently; reveal keys `correct_labels`/`chosen_labels` match between `mark` (Task 2) and `_reveal_multigrid.html` (Task 3); form key `multigridquestion` and transfer key `multi_grid` used consistently across all tasks.
