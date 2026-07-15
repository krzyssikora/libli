# Two-column Layout Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new zero-JS "Two-column layout" container element that arranges its nested child elements into 2–4 equal-width columns, reusing the existing Tabs `parent`/`tab_id` join-row substrate.

**Architecture:** `TwoColumnElement` is a thin container model (like `TabsElement`) whose `data` JSON holds only column stable ids; children are `Element` join rows with `parent`=the two-column join row and `tab_id`=the column id. The column count is driven by a bare `column_count` select; grow/shrink lives server-side in `save_element` (shrink **moves** children to the last column, never deletes). Three Tabs-hardcoded gates (`resolve_scope`, export `walk_unit_joins`, import `validate_nesting`) are generalized to accept a second container type.

**Tech Stack:** Django, Python 3, pytest, `uv run` for all tooling (ruff/pytest/manage.py), Playwright for e2e, gettext (EN/PL) for i18n.

## Global Constraints

- **Element key triple:** model_name `twocolumnelement`, form key `twocolumn`, transfer key `two_column`. Keep them straight — they differ deliberately (transfer keys are snake_case).
- **Column bounds:** `MIN_COLUMNS = 2`, `MAX_COLUMNS = 4`. Column id shape: `COLUMN_ID_RE = re.compile(r"c[0-9a-f]{6}")` (`c` + 6 lowercase hex, fits `tab_id` max_length 12).
- **Two normalizers, load-bearing:** `normalize_ids` (NON-destructive, save-side + write paths + resolve_scope + export) vs `normalize_data` (DESTRUCTIVE pad/truncate to 2–4, read-side only in `resolved_columns`/render). `save()` must NEVER call `normalize_data`.
- **Form owns only the count:** `TwoColumnElementForm` carries a non-model `column_count` `TypedChoiceField(coerce=int)` (2–4), no `data` field, no `clean_data`; `form.save()` never writes `columns`. Column list + ids are owned by the model + `save_element`.
- **Test-harness conventions (apply to EVERY test snippet below):**
  - Course+unit come from `from tests.factories import make_course_with_unit` → `course, unit = make_course_with_unit()` (returns a `(course, unit)` tuple; there is NO unit-only helper — use `_, unit = make_course_with_unit()` when only a unit is needed). All such tests need `@pytest.mark.django_db`. These are plain functions, NOT pytest fixtures — do not put `make_unit`/`make_course_unit` in a test's parameter list.
  - `save_element`'s real signature is `save_element(course, unit_pk, type_key, element_ref, post_data, files)` — pass `unit.pk` (not the unit object) and keep `type_key` before `element_ref`.
  - View/authoring tests log in via `from tests.factories import make_login` → `make_login(client, owner.username)` against a course owned by `owner`; resolve URLs with `reverse("courses:manage_element_add", kwargs={"slug": course.slug})` (and `manage_element_save`); include `unit_token=unit.updated.isoformat()` on POSTs the save path token-checks.
  - `TransferError` is imported from `courses.transfer.schema`.
- **Shrink moves, never deletes:** do NOT copy the Tabs `save_element` delete branch. Dropped (trailing) columns' children are reassigned to the new last column.
- **Two-column is top-level only** (not in `NESTABLE_TYPE_KEYS`; add-menu card gated `{% if not nested %}`) and columns accept the same allowlist as Tabs (no questions, no containers).
- **No `FORMAT_VERSION` bump** (reuses the parent/tab_id on-disk shape). It stays `4`.
- **Fully no-JS element:** no enhancer wired into `editor.js`/`editor.html`.
- **Tooling:** all Python/tests via `uv run` (bash `ruff`/`pytest`/`python` are NOT on PATH). Run from the worktree root `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/two-column-layout`.
- **i18n:** module-level dict/label strings use `gettext_lazy`; transfer error strings use eager `gettext`; every new translatable string must land in `locale/en` and `locale/pl` `.po` catalogs.

---

## File Structure

**Create:**
- `courses/migrations/0047_twocolumnelement_*.py` — generated migration
- `templates/courses/elements/twocolumnelement.html` — student render
- `templates/courses/manage/editor/_edit_twocolumn.html` — host-form edit control (count select)
- `tests/test_twocolumn_model.py`, `tests/test_twocolumn_registry.py`, `tests/test_twocolumn_save_views.py`, `tests/test_twocolumn_transfer.py`, `tests/test_twocolumn_has_math.py`, `tests/test_twocolumn_partial.py`, `tests/test_twocolumn_css.py`, `tests/test_e2e_twocolumn.py`

**Modify:**
- `courses/models.py` — `ELEMENT_MODELS` (+`twocolumnelement`), new `TwoColumnElement` class
- `courses/builder.py` — container registry + generalize `resolve_scope`; `save_element` twocolumn branch
- `courses/element_forms.py` — `TwoColumnElementForm`, `FORM_FOR_TYPE`
- `courses/transfer/export.py` — `_ser_twocolumn`, `SERIALIZERS`, generalize `walk_unit_joins`
- `courses/transfer/payloads.py` — `_val_twocolumn`, `VALIDATORS`, generalize `validate_nesting`
- `courses/transfer/importer.py` — `_build_twocolumn`, `BUILDERS`
- `courses/views.py` — `_twocolumn_has_math` + wire into `_element_has_math`
- `courses/views_manage.py` — `_EDITOR_TYPE_LABELS`, `element_add`/`element_save` allow-tuples
- `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS`, `element_summary`
- `templates/courses/manage/editor/_element_row.html` — twocolumn container branch
- `templates/courses/manage/editor/_add_menu.html` — Content-group card (gated) + sprite symbol
- CSS file for element styles (locate the Tabs `.el--tabs` rules; add `.el--twocolumn` beside them)
- `tests/test_transfer_schema.py` — count 28→29
- `tests/test_models_multigrid.py` — `len(ELEMENT_MODELS)` assert 28→29
- `tests/test_manage_editor_menu.py` — card count 22→23, content list +twocolumn
- `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

---

## Task 1: TwoColumnElement model + migration

**Files:**
- Modify: `courses/models.py` (`ELEMENT_MODELS` ~259-288; add class near `TabsElement` ~936-1063)
- Create: `courses/migrations/0047_twocolumnelement_*.py` (generated)
- Test: `tests/test_twocolumn_model.py`

**Interfaces:**
- Produces: `TwoColumnElement` with `MIN_COLUMNS=2`, `MAX_COLUMNS=4`, `COLUMN_ID_RE`, static `new_column_id(taken=())`, `default_data()`, `normalize_ids(data)`, `normalize_data(data)`, `resolved_columns()`, `render()`, `join_row()`, `save()`. `normalize_ids`/`normalize_data`/`default_data` return `{"columns": [{"id": <str>}, ...]}`.

- [ ] **Step 1: Write failing model tests**

```python
# tests/test_twocolumn_model.py
import re
import pytest
from courses.models import TwoColumnElement, ELEMENT_MODELS

def test_registered_in_element_models():
    assert "twocolumnelement" in ELEMENT_MODELS

def test_default_data_two_unique_ids():
    d = TwoColumnElement.default_data()
    ids = [c["id"] for c in d["columns"]]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert all(re.fullmatch(r"c[0-9a-f]{6}", i) for i in ids)

def test_normalize_ids_keeps_valid_ids():
    data = {"columns": [{"id": "c000abc"}, {"id": "c111def"}]}
    assert TwoColumnElement.normalize_ids(data) == data

def test_normalize_ids_mints_missing_malformed_duplicate():
    data = {"columns": [{"id": "BAD"}, {"id": "c111def"}, {"id": "c111def"}]}
    out = TwoColumnElement.normalize_ids(data)["columns"]
    ids = [c["id"] for c in out]
    assert len(ids) == 3
    assert len(set(ids)) == 3            # duplicate regenerated
    assert ids[1] == "c111def"           # first of a dup pair kept
    assert all(re.fullmatch(r"c[0-9a-f]{6}", i) for i in ids)

def test_normalize_ids_never_creates_columns():
    assert TwoColumnElement.normalize_ids({})["columns"] == []
    assert TwoColumnElement.normalize_ids({"columns": []})["columns"] == []

def test_normalize_data_pads_to_min_and_truncates_to_max():
    assert len(TwoColumnElement.normalize_data({"columns": []})["columns"]) == 2
    five = {"columns": [{"id": f"c00000{n}"} for n in range(5)]}
    assert len(TwoColumnElement.normalize_data(five)["columns"]) == 4

@pytest.mark.django_db
def test_save_runs_normalize_ids_not_normalize_data():
    el = TwoColumnElement(data={"columns": [{"id": "c000abc"}]})
    el.save()
    # save() is non-destructive: it does NOT pad the single column up to 2.
    assert el.data == {"columns": [{"id": "c000abc"}]}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twocolumn_model.py -v`
Expected: FAIL / collection error — `cannot import name 'TwoColumnElement'`.

- [ ] **Step 3: Add `twocolumnelement` to `ELEMENT_MODELS`**

In `courses/models.py`, append to the `ELEMENT_MODELS` list (after `"multigridquestionelement"`):

```python
    "multigridquestionelement",
    "twocolumnelement",
]
```

- [ ] **Step 4: Add the `TwoColumnElement` class**

In `courses/models.py`, near `TabsElement`, add (imports `re`, `secrets`, `models`, `GenericRelation`, `ElementBase` already present):

```python
class TwoColumnElement(ElementBase):
    """Layout container: holds ONLY the ordered column ids. Children live in Element
    rows whose `parent` points at this element's join row and whose `tab_id` is the
    column id. Two normalizers, deliberately separate (mirrors TabsElement):
      * normalize_ids   -- NON-destructive; called by save(); persisted.
      * normalize_data  -- DESTRUCTIVE (pads/truncates to 2..4); read-side only.
    save() must NEVER call normalize_data -- it mints phantom ids and orphans children.
    """

    MIN_COLUMNS = 2
    MAX_COLUMNS = 4
    COLUMN_ID_RE = re.compile(r"c[0-9a-f]{6}")

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def new_column_id(taken=()):
        """'c' + 6 lowercase hex (7 chars, fits tab_id's max_length=12)."""
        while True:
            cid = "c" + secrets.token_hex(3)
            if cid not in taken:
                return cid

    @staticmethod
    def default_data():
        """The two empty columns a freshly-added two-column element is born with."""
        first = TwoColumnElement.new_column_id()
        second = TwoColumnElement.new_column_id({first})
        return {"columns": [{"id": first}, {"id": second}]}

    @staticmethod
    def normalize_ids(data):
        """NON-DESTRUCTIVE. Never changes which columns exist; mints a fresh id for any
        entry whose id is missing, malformed, or a duplicate (first of a dup pair kept).
        Never raises."""
        data = data if isinstance(data, dict) else {}
        raw = data.get("columns")
        raw = raw if isinstance(raw, list) else []
        columns, taken = [], set()
        for item in raw:
            item = item if isinstance(item, dict) else {}
            cid = item.get("id")
            if (not isinstance(cid, str)
                    or not TwoColumnElement.COLUMN_ID_RE.fullmatch(cid)
                    or cid in taken):
                cid = TwoColumnElement.new_column_id(taken)
            taken.add(cid)
            columns.append({"id": cid})
        return {"columns": columns}

    @staticmethod
    def normalize_data(data):
        """DESTRUCTIVE (pads to MIN_COLUMNS, truncates to MAX_COLUMNS). READ-SIDE ONLY --
        called by resolved_columns() when rendering, never persisted."""
        norm = TwoColumnElement.normalize_ids(data)
        columns = norm["columns"][: TwoColumnElement.MAX_COLUMNS]
        taken = {c["id"] for c in columns}
        while len(columns) < TwoColumnElement.MIN_COLUMNS:
            cid = TwoColumnElement.new_column_id(taken)
            taken.add(cid)
            columns.append({"id": cid})
        return {"columns": columns}

    def save(self, *args, **kwargs):
        self.data = self.normalize_ids(self.data)
        super().save(*args, **kwargs)

    def join_row(self):
        """This concrete's single Element join row (the GFK is effectively 1:1)."""
        return self.elements.order_by("pk").first()

    def resolved_columns(self):
        """Ordered [(column_dict, [child Element join rows])], grouped by tab_id and
        ordered by `order`. EVERY column emitted (including empty). Enumerates columns
        via the DESTRUCTIVE read-side normalize_data (the 2..4 render clamp)."""
        columns = self.normalize_data(self.data)["columns"]
        join = self.join_row()
        if join is None:  # transient, mid-create
            return [(col, []) for col in columns]
        by_col = {}
        children = (
            join.children.order_by("order", "pk")
            .select_related("content_type")
            .prefetch_related("content_object")
        )
        for child in children:
            by_col.setdefault(child.tab_id, []).append(child)
        return [(col, by_col.get(col["id"], [])) for col in columns]

    def render(self):
        from django.template.loader import render_to_string

        join = self.join_row()
        return render_to_string(
            "courses/elements/twocolumnelement.html",
            {"el": self, "columns": self.resolved_columns(),
             "eid": join.pk if join else 0},
        )
```

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0047_twocolumnelement_*.py` with `CreateModel(TwoColumnElement, options={'abstract': False})` + an `AlterField` on `element.content_type` re-listing `model__in` with `twocolumnelement` appended. Open the file and confirm both operations are present.

- [ ] **Step 6: Bump the ELEMENT_MODELS count assertions**

Adding to `ELEMENT_MODELS` breaks two existing count assertions. Update both now (they live in separate files):
- `tests/test_models_multigrid.py:11` — change `assert len(ELEMENT_MODELS) == 28` to `== 29`.
- `tests/test_transfer_schema.py:11` — change `assert len(ELEMENT_MODELS) == 28` to `== 29`. (Task 5 additionally extends this file's registry-parity loop.)

- [ ] **Step 7: Run tests to verify pass**

Run: `uv run pytest tests/test_twocolumn_model.py tests/test_models_multigrid.py tests/test_transfer_schema.py::test_element_models -v`
Expected: PASS (model tests + both count assertions green).

- [ ] **Step 8: Commit**

```bash
git add courses/models.py courses/migrations/0047_*.py tests/test_twocolumn_model.py tests/test_models_multigrid.py tests/test_transfer_schema.py
git commit -m "feat(twocolumn): TwoColumnElement model + migration"
```

---

## Task 2: Container registry + generalize resolve_scope

**Files:**
- Modify: `courses/builder.py` (`resolve_scope` ~64-102; add registry after `NESTABLE_TYPE_KEYS` ~52)
- Test: `tests/test_twocolumn_registry.py`

**Interfaces:**
- Consumes: `TwoColumnElement.normalize_ids` (Task 1).
- Produces: `_CONTAINER_REGISTRY` dict (model class → `(normalizer, slot_list_key, slot_id_key)`); `resolve_scope` now accepts any registered container parent. `NESTABLE_TYPE_KEYS` unchanged (two_column deliberately absent).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_twocolumn_registry.py
import pytest
from courses.builder import resolve_scope, NestingError
from courses.models import TwoColumnElement, TabsElement, Element, TextElement

@pytest.mark.django_db
def test_two_column_not_nestable_itself():
    from courses.builder import NESTABLE_TYPE_KEYS
    assert "two_column" not in NESTABLE_TYPE_KEYS
    assert "twocolumn" not in NESTABLE_TYPE_KEYS

@pytest.mark.django_db
def test_resolve_scope_accepts_two_column_parent():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    parent_join, tab_id = resolve_scope(unit, str(join.pk), cid, "text")
    assert parent_join == join and tab_id == cid

@pytest.mark.django_db
def test_resolve_scope_rejects_unknown_column():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data()); col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), "cffffff", "text")

@pytest.mark.django_db
def test_resolve_scope_rejects_container_child_in_two_column():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data()); col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), cid, "tabs")       # containers can't nest
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), cid, "choicequestion")  # questions can't nest

@pytest.mark.django_db
def test_resolve_scope_rejects_non_container_parent():
    _, unit = make_course_with_unit()
    txt = TextElement.objects.create(body="hi")
    join = Element.objects.create(unit=unit, content_object=txt)
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), "c000abc", "text")
```

> Per Global Constraints: `course, unit = make_course_with_unit()` (import from `tests.factories`); there is no unit-only helper.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twocolumn_registry.py -v`
Expected: FAIL — `resolve_scope` raises "parent is not a tabs element" for the two-column parent.

- [ ] **Step 3: Add the container registry + generalize `resolve_scope`**

In `courses/builder.py`, ensure `TwoColumnElement` is imported alongside `TabsElement`. After the `_NESTABLE_FORM_KEY_ALIASES` block, add:

```python
# Container element registry: model class -> (non_destructive_normalizer,
# slot_list_key, slot_id_key). CONTRACT: each normalizer returns
# {slot_list_key: [{slot_id_key: <id>}, ...]}. resolve_scope indexes the normalizer
# output by slot_list_key, so slot_list_key MUST equal the key the normalizer emits.
_CONTAINER_REGISTRY = {
    TabsElement: (TabsElement.normalize_labels_and_ids, "tabs", "id"),
    TwoColumnElement: (TwoColumnElement.normalize_ids, "columns", "id"),
}
```

Replace the tabs-hardcoded block in `resolve_scope`:

```python
    parent_obj = join.content_object
    if not isinstance(parent_obj, TabsElement):
        raise NestingError("parent is not a tabs element")
    valid_tab_ids = {
        t["id"] for t in TabsElement.normalize_labels_and_ids(parent_obj.data)["tabs"]}
    if tab not in valid_tab_ids:
        raise NestingError("unknown tab")
```

with:

```python
    parent_obj = join.content_object
    container = _CONTAINER_REGISTRY.get(type(parent_obj))
    if container is None:
        raise NestingError("parent is not a container")
    normalizer, list_key, id_key = container
    valid_slot_ids = {s[id_key] for s in normalizer(parent_obj.data)[list_key]}
    if tab not in valid_slot_ids:
        raise NestingError("unknown slot")
```

(The `nestable_key` child-type check below it is unchanged.)

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_twocolumn_registry.py tests/test_tabs_form_views.py -v`
Expected: PASS (new tests + existing Tabs nesting tests still green — the generalization is behavior-preserving for Tabs).

- [ ] **Step 5: Commit**

```bash
git add courses/builder.py tests/test_twocolumn_registry.py
git commit -m "feat(twocolumn): container registry + generalize resolve_scope"
```

---

## Task 3: TwoColumnElementForm + FORM_FOR_TYPE

**Files:**
- Modify: `courses/element_forms.py` (add form near `TabsElementForm` ~1382; `FORM_FOR_TYPE` ~1508-1537)
- Test: `tests/test_twocolumn_save_views.py` (form portion)

**Interfaces:**
- Consumes: `TwoColumnElement` (Task 1).
- Produces: `TwoColumnElementForm` with a non-model `column_count` `TypedChoiceField` (coerce=int, choices 2–4), no `data` field, no `clean_data`; `__init__` initializes `column_count` to the persisted column count on unbound (edit) render, else 2. `FORM_FOR_TYPE["twocolumn"] = TwoColumnElementForm`.

- [ ] **Step 1: Write failing form tests**

```python
# tests/test_twocolumn_save_views.py  (form section — more added in Task 4)
import pytest
from courses.element_forms import TwoColumnElementForm, FORM_FOR_TYPE
from courses.models import TwoColumnElement

def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["twocolumn"] is TwoColumnElementForm

def test_form_has_no_data_field():
    f = TwoColumnElementForm()
    assert "data" not in f.fields
    assert "column_count" in f.fields

def test_form_column_count_coerces_int_and_bounds():
    f = TwoColumnElementForm(data={"column_count": "3"})
    assert f.is_valid()
    assert f.cleaned_data["column_count"] == 3
    bad = TwoColumnElementForm(data={"column_count": "5"})
    assert not bad.is_valid()

def test_form_initializes_count_to_persisted_on_edit():
    inst = TwoColumnElement(data={"columns": [{"id": "c000001"},
                                              {"id": "c000002"},
                                              {"id": "c000003"}]})
    f = TwoColumnElementForm(instance=inst)
    assert f.fields["column_count"].initial == 3

def test_form_initializes_count_to_two_on_create():
    f = TwoColumnElementForm()
    assert f.fields["column_count"].initial == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twocolumn_save_views.py -v`
Expected: FAIL — cannot import `TwoColumnElementForm`.

- [ ] **Step 3: Add the form**

In `courses/element_forms.py` (imports `forms`, `cached_property`, `gettext_lazy as _`, and `TwoColumnElement` — add the model import beside `TabsElement`):

```python
class TwoColumnElementForm(forms.ModelForm):
    """Two-column layout: the ONLY input is the column count. Columns + ids are owned
    by save_element, NOT the form. No `data` field and no clean_data -> form.save()
    never writes `columns` (so it can never clobber persisted ids on edit)."""

    column_count = forms.TypedChoiceField(
        coerce=int,
        choices=[(n, str(n)) for n in range(
            TwoColumnElement.MIN_COLUMNS, TwoColumnElement.MAX_COLUMNS + 1)],
        label=_("Columns"),
    )

    class Meta:
        model = TwoColumnElement
        fields = []  # bind no model fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            existing = getattr(self.instance, "data", None) or {}
            cols = existing.get("columns")
            n = (len(cols) if isinstance(cols, list) and cols
                 else len(TwoColumnElement.default_data()["columns"]))
            n = max(TwoColumnElement.MIN_COLUMNS,
                    min(TwoColumnElement.MAX_COLUMNS, n))
            self.fields["column_count"].initial = n
```

Add to `FORM_FOR_TYPE`:

```python
    "tabs": TabsElementForm,
    "twocolumn": TwoColumnElementForm,
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_twocolumn_save_views.py -v`
Expected: PASS (5).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py tests/test_twocolumn_save_views.py
git commit -m "feat(twocolumn): count-only form + FORM_FOR_TYPE"
```

---

## Task 4: save_element twocolumn branch (grow / shrink / move)

**Files:**
- Modify: `courses/builder.py` (`save_element` — add branch beside the `tabs` branch ~519-542; ensure `ordering` + `TwoColumnElement` imported)
- Test: `tests/test_twocolumn_save_views.py` (append)

**Interfaces:**
- Consumes: `TwoColumnElementForm` (Task 3), `TwoColumnElement` (Task 1), `ordering.assign_orders_elements` (`courses/ordering.py:30`).
- Produces: creating/editing a `twocolumn` element seeds/grows/shrinks columns; shrink **moves** dropped columns' children to the new last column.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_twocolumn_save_views.py  (append)
import pytest
from courses import builder as builder_svc
from courses.models import TwoColumnElement, TextElement, Element

def _add_two_column(course, unit, count):
    post = {"unit_token": unit.updated.isoformat(), "column_count": str(count)}
    # save_element(course, unit_pk, type_key, element_ref, post_data, files)
    builder_svc.save_element(course, unit.pk, "twocolumn", "new", post, {})
    return Element.objects.filter(unit=unit, parent__isnull=True).latest("pk")

@pytest.mark.django_db
def test_create_honors_initial_count():
    course, unit = make_course_with_unit()
    join = _add_two_column(course, unit, 4)
    assert len(join.content_object.data["columns"]) == 4

@pytest.mark.django_db
def test_shrink_moves_children_to_last_column():
    course, unit = make_course_with_unit()
    join = _add_two_column(course, unit, 4)
    col = join.content_object
    ids = [c["id"] for c in col.data["columns"]]
    # put a text child in column 3 and one in column 4
    c3 = Element.objects.create(unit=unit, parent=join, tab_id=ids[2],
                                content_object=TextElement.objects.create(body="C3"))
    c4 = Element.objects.create(unit=unit, parent=join, tab_id=ids[3],
                                content_object=TextElement.objects.create(body="C4"))
    # shrink 4 -> 2
    post = {"unit_token": unit.updated.isoformat(), "column_count": "2"}
    builder_svc.save_element(course, unit.pk, "twocolumn", str(join.pk), post, {})
    col.refresh_from_db(); c3.refresh_from_db(); c4.refresh_from_db()
    new_ids = [c["id"] for c in col.data["columns"]]
    assert len(new_ids) == 2
    last = new_ids[-1]
    assert c3.tab_id == last and c4.tab_id == last          # moved, not deleted
    assert TextElement.objects.filter(body="C3").exists()
    assert TextElement.objects.filter(body="C4").exists()
    # deterministic drain order: column 3's child before column 4's
    merged = list(Element.objects.filter(parent=join, tab_id=last)
                  .order_by("order", "pk"))
    assert [m.pk for m in merged] == [c3.pk, c4.pk]

@pytest.mark.django_db
def test_grow_keeps_existing_children():
    course, unit = make_course_with_unit()
    join = _add_two_column(course, unit, 2)
    col = join.content_object
    first_id = col.data["columns"][0]["id"]
    child = Element.objects.create(unit=unit, parent=join, tab_id=first_id,
                                   content_object=TextElement.objects.create(body="X"))
    post = {"unit_token": unit.updated.isoformat(), "column_count": "4"}
    builder_svc.save_element(course, unit.pk, "twocolumn", str(join.pk), post, {})
    col.refresh_from_db(); child.refresh_from_db()
    assert len(col.data["columns"]) == 4
    assert col.data["columns"][0]["id"] == first_id      # existing id stable
    assert child.tab_id == first_id                       # child untouched
```

> Use whatever course/unit construction the existing Tabs view tests use; if there's no `make_course_unit` fixture, build the course+unit inline as `tests/test_tabs_form_views.py` does.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twocolumn_save_views.py -v`
Expected: FAIL — `save_element` has no `twocolumn` branch (raises unknown-type or KeyError).

- [ ] **Step 3: Add the `twocolumn` branch to `save_element`**

In `courses/builder.py`, add before the generic `else:` fallthrough (ensure `from courses import ordering` and `TwoColumnElement` are imported):

```python
    elif type_key == "twocolumn":
        form = FORM_FOR_TYPE["twocolumn"](data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        count = form.cleaned_data["column_count"]
        obj = form.save(commit=False)  # binds no fields; does not write `data`
        # Derive the column list from the EXISTING persisted list (create -> default).
        if instance is None:
            existing = TwoColumnElement.default_data()["columns"]
        else:
            existing = TwoColumnElement.normalize_ids(instance.data)["columns"]
            if len(existing) < TwoColumnElement.MIN_COLUMNS:
                existing = TwoColumnElement.default_data()["columns"]
        taken = {c["id"] for c in existing}
        if count > len(existing):                      # GROW
            new_columns = list(existing)
            while len(new_columns) < count:
                cid = TwoColumnElement.new_column_id(taken)
                taken.add(cid)
                new_columns.append({"id": cid})
            dropped = []
        else:                                          # SHRINK (drop trailing)
            new_columns = existing[:count]
            dropped = existing[count:]
        obj.data = {"columns": new_columns}
        obj.save()  # non-destructive normalize_ids keeps these ids
        # Move dropped columns' children to the new last column (never delete).
        if join is not None and dropped:
            new_last = new_columns[-1]["id"]
            target = list(
                Element.objects.filter(parent=join, tab_id=new_last)
                .order_by("order", "pk"))
            moved = []
            for col in dropped:                        # original column order
                moved.extend(
                    Element.objects.filter(parent=join, tab_id=col["id"])
                    .order_by("order", "pk"))
            for child in moved:
                child.tab_id = new_last
            if moved:
                Element.objects.bulk_update(moved, ["tab_id"])
                ordering.assign_orders_elements(target + moved)
```

(The shared join-create / title-update block after the `if/elif` chain handles the new element's join row unchanged — do not duplicate it.)

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_twocolumn_save_views.py -v`
Expected: PASS (all form + save tests).

- [ ] **Step 5: Commit**

```bash
git add courses/builder.py tests/test_twocolumn_save_views.py
git commit -m "feat(twocolumn): save_element grow/shrink with child-move on shrink"
```

---

## Task 5: Transfer — serializer, validator, builder + generalize walkers

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_twocolumn` near `_ser_tabs` ~160; `SERIALIZERS` ~300-329; `walk_unit_joins` ~392-413)
- Modify: `courses/transfer/payloads.py` (`_val_twocolumn` near `_val_tabs` ~609; `VALIDATORS` ~673-702; `validate_nesting` ~638-670)
- Modify: `courses/transfer/importer.py` (`_build_twocolumn` near `_build_tabs` ~744; `BUILDERS` ~751-780)
- Modify: `tests/test_transfer_schema.py` (count 28→29)
- Test: `tests/test_twocolumn_transfer.py`

**Interfaces:**
- Consumes: `TwoColumnElement` (Task 1).
- Produces: transfer key `two_column` registered in `SERIALIZERS`/`VALIDATORS`/`BUILDERS`; export/import round-trip includes two-column children.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_twocolumn_transfer.py
import pytest
from courses.transfer.export import SERIALIZERS, walk_unit_joins
from courses.transfer.payloads import VALIDATORS, validate_nesting
from courses.transfer.importer import BUILDERS

def test_two_column_registered_in_all_registries():
    assert "two_column" in SERIALIZERS
    assert "two_column" in VALIDATORS
    assert "two_column" in BUILDERS

def test_validator_enforces_bounds_and_id_shape():
    from courses.transfer.payloads import VALIDATORS
    from courses.transfer.schema import TransferError
    good = {"columns": [{"id": "c000001"}, {"id": "c000002"}]}
    VALIDATORS["two_column"](good, "e1", set())  # no raise
    for bad in ({"columns": [{"id": "c000001"}]},                # < 2
                {"columns": [{"id": f"c00000{n}"} for n in range(5)]},  # > 4
                {"columns": [{"id": "BAD"}, {"id": "c000002"}]}):       # id shape
        with pytest.raises(TransferError):
            VALIDATORS["two_column"](bad, "e1", set())

def test_validate_nesting_accepts_two_column_parent():
    elements = [
        {"id": "p", "type": "two_column", "parent": None, "tab": "",
         "data": {"columns": [{"id": "c000001"}, {"id": "c000002"}]}},
        {"id": "k", "type": "text", "parent": "p", "tab": "c000001",
         "data": {"body": "hi"}},
    ]
    validate_nesting(elements)  # no raise

def test_validate_nesting_rejects_unknown_column():
    elements = [
        {"id": "p", "type": "two_column", "parent": None, "tab": "",
         "data": {"columns": [{"id": "c000001"}, {"id": "c000002"}]}},
        {"id": "k", "type": "text", "parent": "p", "tab": "cffffff",
         "data": {"body": "hi"}},
    ]
    with pytest.raises(Exception):
        validate_nesting(elements)

@pytest.mark.django_db
def test_export_walk_yields_two_column_children():
    from courses.models import TwoColumnElement, TextElement, Element
    course, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data()); col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    Element.objects.create(unit=unit, parent=join, tab_id=cid,
                           content_object=TextElement.objects.create(body="K"))
    joins_by_unit = {unit.pk: [join]}
    yielded = list(walk_unit_joins(unit.pk, joins_by_unit))
    # parent + child both yielded, child carries the column id
    assert any(p is join and t == cid for (_, p, t) in yielded)
```

> Fix the `TransferError` import path to match the codebase (read `courses/transfer/payloads.py` imports). Reuse the Tabs transfer test's course/unit setup if `make_course_unit` isn't a fixture.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twocolumn_transfer.py -v`
Expected: FAIL — `two_column` absent from registries; `validate_nesting`/`walk_unit_joins` reject/skip two-column.

- [ ] **Step 3: Serializer + SERIALIZERS + walk_unit_joins**

In `courses/transfer/export.py` (import `TwoColumnElement`):

```python
def _ser_twocolumn(el, ids):
    # Column ids only. NON-destructive normalizer (mirrors save()).
    return {"columns": [dict(c) for c in el.normalize_ids(el.data)["columns"]]}
```

Add to `SERIALIZERS`:

```python
    "tabs": (TabsElement, _ser_tabs),
    "two_column": (TwoColumnElement, _ser_twocolumn),
```

Generalize `walk_unit_joins` — replace the tabs-only expansion:

```python
        obj = join.content_object
        if isinstance(obj, TabsElement):
            for tab, children in obj.resolved_tabs():
                for child in children:
                    yield child, join, tab["id"]
```

with:

```python
        obj = join.content_object
        if isinstance(obj, TabsElement):
            for tab, children in obj.resolved_tabs():
                for child in children:
                    yield child, join, tab["id"]
        elif isinstance(obj, TwoColumnElement):
            for col, children in obj.resolved_columns():
                for child in children:
                    yield child, join, col["id"]
```

- [ ] **Step 4: Validator + VALIDATORS + validate_nesting**

In `courses/transfer/payloads.py` (import `TwoColumnElement` locally, mirroring `_val_tabs`):

```python
def _val_twocolumn(data, elid, media_kinds):
    from courses.models import TwoColumnElement
    _exact_keys(data, ["columns"], _("two-column data"))
    columns = data["columns"]
    if not isinstance(columns, list):
        _err(_("Element '%(el)s' has malformed columns."), el=elid)
    if not (TwoColumnElement.MIN_COLUMNS <= len(columns)
            <= TwoColumnElement.MAX_COLUMNS):
        _err(_("Element '%(el)s' has an invalid number of columns."), el=elid)
    seen = set()
    for col in columns:
        if not isinstance(col, dict):
            _err(_("Element '%(el)s' has a malformed column."), el=elid)
        _exact_keys(col, ["id"], _("column"))
        cid = col["id"]
        if not isinstance(cid, str) or not TwoColumnElement.COLUMN_ID_RE.fullmatch(cid):
            _err(_("Element '%(el)s' has a malformed column id."), el=elid)
        if cid in seen:
            _err(_("Element '%(el)s' has duplicate column ids."), el=elid)
        seen.add(cid)
    return set()  # a two-column element references no media
```

Add to `VALIDATORS`:

```python
    "tabs": _val_tabs,
    "two_column": _val_twocolumn,
```

Generalize `validate_nesting`. Add a **module-level constant** `_CONTAINER_SLOT_KEY` in `payloads.py` (transfer-type-string keyed, distinct from the model-keyed builder registry), then replace the tabs-hardcoded checks inside the function:

```python
# module level in courses/transfer/payloads.py (transfer-type-string keyed)
_CONTAINER_SLOT_KEY = {"tabs": "tabs", "two_column": "columns"}
```

Replace:

```python
        if parent["type"] != "tabs":
            _err(_("Element '%(el)s' has a parent that is not a tabs element."),
                 el=el["id"])
        if parent["parent"] is not None:
            _err(_("Element '%(el)s' is nested more than one level deep."), el=el["id"])
        if el["tab"] not in {t["id"] for t in parent["data"]["tabs"]}:
            _err(_("Element '%(el)s' references a tab its parent does not have."),
                 el=el["id"])
```

with:

```python
        slot_key = _CONTAINER_SLOT_KEY.get(parent["type"])
        if slot_key is None:
            _err(_("Element '%(el)s' has a parent that is not a container element."),
                 el=el["id"])
        if parent["parent"] is not None:
            _err(_("Element '%(el)s' is nested more than one level deep."), el=el["id"])
        if el["tab"] not in {s["id"] for s in parent["data"][slot_key]}:
            _err(_("Element '%(el)s' references a slot its parent does not have."),
                 el=el["id"])
```

- [ ] **Step 5: Builder + BUILDERS**

In `courses/transfer/importer.py` (import `TwoColumnElement`, mirror `_build_tabs`):

```python
def _build_twocolumn(data, assets):
    # Column ids pass through VERBATIM (save() runs only normalize_ids, which never
    # rewrites a present/unique/well-formed id -- regenerating would orphan children).
    return _clean_save(TwoColumnElement(data={"columns": data["columns"]})), ()
```

Add to `BUILDERS`:

```python
    "tabs": _build_tabs,
    "two_column": _build_twocolumn,
```

- [ ] **Step 6: Extend the schema registry-parity loop**

In `tests/test_transfer_schema.py`, add `"twocolumnelement"` to the registry-parity loop that iterates model names (around lines 12-28), so the new type is checked for `SERIALIZERS`/`VALIDATORS`/`BUILDERS` parity. (The `len(ELEMENT_MODELS) == 29` bump was already applied in Task 1 Step 6.) Leave `FORMAT_VERSION == 4` unchanged.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_twocolumn_transfer.py tests/test_transfer_schema.py tests/test_tabs_transfer.py -v`
Expected: PASS (new + schema count + existing Tabs transfer round-trip still green).

- [ ] **Step 8: Commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py tests/test_twocolumn_transfer.py tests/test_transfer_schema.py
git commit -m "feat(twocolumn): transfer serializer/validator/builder + generalize walkers"
```

---

## Task 6: has_math wiring (_twocolumn_has_math)

**Files:**
- Modify: `courses/views.py` (add `_twocolumn_has_math` near `_tabs_has_math` ~207; wire into `_element_has_math` final return ~202-204)
- Test: `tests/test_twocolumn_has_math.py`

**Interfaces:**
- Consumes: `TwoColumnElement` (Task 1), `_element_has_math` recursion.
- Produces: `_twocolumn_has_math(el)`; `_element_has_math` returns True when a math-bearing child lives in a column.

- [ ] **Step 1: Write failing test**

```python
# tests/test_twocolumn_has_math.py
import pytest
from courses.views import _element_has_math
from courses.models import TwoColumnElement, MathElement, TextElement, Element

@pytest.mark.django_db
def test_two_column_reports_math_from_nested_child():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data()); col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    assert _element_has_math(col) is False
    Element.objects.create(unit=unit, parent=join, tab_id=cid,
                           content_object=MathElement.objects.create(latex="x^2"))
    assert _element_has_math(col) is True

@pytest.mark.django_db
def test_two_column_no_math_when_children_plain():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data()); col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    Element.objects.create(unit=unit, parent=join, tab_id=cid,
                           content_object=TextElement.objects.create(body="plain"))
    assert _element_has_math(col) is False
```

> Confirm `MathElement`'s field name (`latex` vs `body`) from `courses/models.py` before running.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twocolumn_has_math.py -v`
Expected: FAIL — `_element_has_math(col)` returns False even with nested math.

- [ ] **Step 3: Add helper + wire it in**

In `courses/views.py`, add near `_tabs_has_math`:

```python
def _twocolumn_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _tabs_has_math. has_math consumes the element
    list AFTER the render filter strips nested children, so it walks into them here."""
    from courses.models import TwoColumnElement

    if not isinstance(el, TwoColumnElement):
        return False
    join = el.join_row()
    if join is None:
        return False
    return any(_element_has_math(child.content_object)
               for child in join.children.prefetch_related("content_object"))
```

Extend the final `return (...)` of `_element_has_math`:

```python
    return (_table_has_math(obj) or _gallery_has_math(obj)
            or _tabs_has_math(obj) or _fill_table_has_math(obj)
            or _twocolumn_has_math(obj))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_twocolumn_has_math.py -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add courses/views.py tests/test_twocolumn_has_math.py
git commit -m "feat(twocolumn): _twocolumn_has_math recursion wired into _element_has_math"
```

---

## Task 7: Student render template + CSS + sprite

**Files:**
- Create: `templates/courses/elements/twocolumnelement.html`
- Modify: the CSS file holding `.el--tabs` rules (add `.el--twocolumn`); `templates/courses/manage/editor/_add_menu.html` sprite `<symbol id="el-twocolumn">` (or wherever the `#el-*` sprite lives — grep for `id="el-tabs"`)
- Test: `tests/test_twocolumn_partial.py`, `tests/test_twocolumn_css.py`

**Interfaces:**
- Consumes: `TwoColumnElement.render()` passing `columns`, `eid` (Task 1).
- Produces: `.el--twocolumn` flex row; each column renders its children via `{% render_element child %}`.

- [ ] **Step 1: Write failing render test**

```python
# tests/test_twocolumn_partial.py
import pytest
from courses.models import TwoColumnElement, TextElement, Element

@pytest.mark.django_db
def test_render_emits_columns_with_children():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data()); col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    ids = [c["id"] for c in col.data["columns"]]
    Element.objects.create(unit=unit, parent=join, tab_id=ids[0],
                           content_object=TextElement.objects.create(body="LEFT"))
    Element.objects.create(unit=unit, parent=join, tab_id=ids[1],
                           content_object=TextElement.objects.create(body="RIGHT"))
    html = col.render()
    assert 'class="el el--twocolumn"' in html
    assert html.count("twocolumn__column") == 2
    assert "LEFT" in html and "RIGHT" in html

@pytest.mark.django_db
def test_render_empty_column_still_emitted():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data={"columns": [{"id": "c000001"}, {"id": "c000002"},
                                             {"id": "c000003"}]})
    col.save()
    Element.objects.create(unit=unit, content_object=col)
    html = col.render()
    assert html.count("twocolumn__column") == 3   # empty columns still render
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twocolumn_partial.py -v`
Expected: FAIL — `TemplateDoesNotExist: courses/elements/twocolumnelement.html`.

- [ ] **Step 3: Create the student template**

`templates/courses/elements/twocolumnelement.html`:

```django
{% load courses_extras %}
{% comment %}
Student-facing two-column layout. `columns` is [(column, [child Element rows])] from
TwoColumnElement.resolved_columns(); EVERY column is emitted (including empty ones).
Zero JS: this markup IS the final render. Columns are equal-width, wrap/stack on narrow
screens via flex-wrap + min-width. `eid` (join row pk) namespaces nothing today but is
passed for parity with other containers.
{% endcomment %}
<div class="el el--twocolumn" data-twocolumn data-twocolumn-eid="{{ eid }}">
  {% for column, children in columns %}
    <div class="twocolumn__column" data-column-id="{{ column.id }}">
      {% for child in children %}
        <div class="twocolumn__child">{% render_element child %}</div>
      {% endfor %}
    </div>
  {% endfor %}
</div>
```

- [ ] **Step 4: Add CSS beside `.el--tabs`**

Grep for `.el--tabs` to find the stylesheet. Add (theme-token driven; light + dark via existing tokens — mirror how `.el--tabs` handles color):

```css
.el--twocolumn {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}
.el--twocolumn > .twocolumn__column {
  flex: 1 1 260px;
  min-width: 260px;
}
.el--twocolumn > .twocolumn__column > .twocolumn__child + .twocolumn__child {
  margin-top: 0.75rem;
}
```

- [ ] **Step 5: Write + satisfy CSS presence test**

```python
# tests/test_twocolumn_css.py
from pathlib import Path

def test_twocolumn_css_present():
    # point CSS_PATH at the stylesheet that holds .el--tabs
    css = Path("courses/static/courses/css/elements.css").read_text(encoding="utf-8")
    assert ".el--twocolumn" in css
    assert "flex-wrap" in css
```

> Correct `CSS_PATH` to the real stylesheet discovered in Step 4 (mirror `tests/test_tabs_css.py`'s path).

- [ ] **Step 6: Add the sprite symbol**

Grep for `id="el-tabs"` to find the SVG sprite. Add an `<symbol id="el-twocolumn" viewBox="...">` with a simple two-column glyph (two vertical rectangles), matching the monochrome `currentColor` line-icon style of the neighbouring symbols.

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_twocolumn_partial.py tests/test_twocolumn_css.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/elements/twocolumnelement.html tests/test_twocolumn_partial.py tests/test_twocolumn_css.py courses/static
git commit -m "feat(twocolumn): student render template + CSS + sprite icon"
```

---

## Task 8: Editor — edit partial, element-row branch, add-menu card, views_manage wiring

**Files:**
- Create: `templates/courses/manage/editor/_edit_twocolumn.html`
- Modify: `templates/courses/manage/editor/_element_row.html` (add twocolumn container branch beside the tabs branch)
- Modify: `templates/courses/manage/editor/_add_menu.html` (Content-group card, gated `{% if not nested %}`)
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS`; `element_add` + `element_save` allow-tuples)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`; `element_summary`)
- Modify: `tests/test_manage_editor_menu.py` (22→23; content list +twocolumn)
- Test: `tests/test_twocolumn_save_views.py` (append authoring-path GET/POST 200)

**Interfaces:**
- Consumes: `TwoColumnElementForm` (Task 3), `TwoColumnElement.resolved_columns` (Task 1).
- Produces: palette card + editable element with per-column nested add-menus; `manage_element_add` GET/POST for `twocolumn` returns 200.

- [ ] **Step 1: Write failing authoring + menu tests**

```python
# tests/test_twocolumn_save_views.py  (append)
from django.urls import reverse
from tests.factories import CourseFactory, ContentNodeFactory, make_pa

@pytest.mark.django_db
def test_element_add_twocolumn_renders_edit_partial(client):
    pa = make_pa(client, "pa")                  # creates + logs in a platform admin
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit",
                              unit_type="lesson")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "twocolumn", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200              # guards missing _edit_twocolumn.html
    assert 'name="column_count"' in resp.content.decode()
    assert Element.objects.filter(unit=unit).count() == 0   # add is render-only

@pytest.mark.django_db
def test_save_twocolumn_creates_element(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit",
                              unit_type="lesson")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {"type": "twocolumn", "element": "new", "unit": unit.pk,
         "unit_token": unit.updated.isoformat(), "column_count": "3"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit, parent__isnull=True)
    assert isinstance(el.content_object, TwoColumnElement)
    assert len(el.content_object.data["columns"]) == 3
```

```python
# tests/test_manage_editor_menu.py  — adjust existing assertions
assert body.count('data-add-type="') == 23   # was 22 (+ twocolumn content card)
# and add "twocolumn" to the expected content-card list assertion (10 -> 11)
```

> Read `tests/test_manage_editor_menu.py` first to match its exact content-card list assertion shape (mirror how it lists the 10 content cards, extend to 11). The authoring test above mirrors `courses/tests/test_spoiler_authoring.py` (`make_pa` + `CourseFactory` + `ContentNodeFactory` lesson unit + `HTTP_X_REQUESTED_WITH="fetch"`).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_manage_editor_menu.py tests/test_twocolumn_save_views.py -v`
Expected: FAIL — menu count still 22; element-add 500s (`TemplateDoesNotExist: _edit_twocolumn.html`) or the type is rejected by the allow-tuple.

- [ ] **Step 3: Create the edit partial**

`templates/courses/manage/editor/_edit_twocolumn.html`:

```django
{% load i18n %}
{% comment %}
Two-column editor control: JUST the column count. The columns + their nested elements
are managed in the element-row list (per-column add-menus), not here. No hidden `data`
field -- grow/shrink is applied server-side in save_element from `column_count`.
{% endcomment %}
<div class="el-editor el-editor--twocolumn">
  <label class="editor-form__label">{% trans "Columns" %}
    {{ form.column_count }}
  </label>
  {% for e in form.column_count.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

- [ ] **Step 4: Add the element-row container branch**

In `templates/courses/manage/editor/_element_row.html`, mirror the tabs branch (`{% if ... %}`/`{% elif ... %}` dispatch on `el.content_type.model` or the existing `obj` isinstance check the tabs branch uses — read the file to match its exact dispatch idiom). Add a two-column branch rendering `obj.resolved_columns` with a per-column nested add-menu:

```django
  <div class="el-row__columns">
    {% for column, children in obj.resolved_columns %}
      <details class="columns-rows" data-column-id="{{ column.id }}" {% if forloop.first %}open{% endif %}>
        <summary class="columns-rows__summary">{% blocktrans with n=forloop.counter %}Column {{ n }}{% endblocktrans %} <span class="columns-rows__count">{{ children|length }}</span></summary>
        <ol class="element-list element-list--nested">
          {% for child in children %}
            {% include "courses/manage/editor/_element_row.html" with el=child obj=child.content_object unit=unit open_form=open_form open_form_pk=open_form_pk %}
          {% empty %}
            <li class="empty-state">{% trans "This column is empty." %}</li>
          {% endfor %}
        </ol>
        {% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=column.id %}
      </details>
    {% endfor %}
  </div>
```

Ensure the branch also renders the inline edit-slot exactly as the tabs branch does (the `{% if open_form_pk == el.pk|stringformat:'s' %}{{ open_form|safe }}{% endif %}` line) so the count select opens in place.

- [ ] **Step 5: Add the add-menu card**

In `templates/courses/manage/editor/_add_menu.html`, inside the Content group, beside the tabs card, gated identically:

```django
      {% if not nested %}<button type="button" class="typecard" data-add-type="twocolumn"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-twocolumn"/></svg>{% trans "Two-column layout" %}</button>{% endif %}
```

- [ ] **Step 6: Wire views_manage**

In `courses/views_manage.py`:
- `_EDITOR_TYPE_LABELS`: add `"twocolumn": gettext_lazy("Two-column layout"),`
- `element_add` allow-tuple: add `"twocolumn"`.
- `element_save` allow-tuple: add `"twocolumn"`.

- [ ] **Step 7: Wire courses_manage_extras**

In `courses/templatetags/courses_manage_extras.py`:
- `_ELEMENT_LABELS`: add `"twocolumnelement": _("Two columns"),`
- `element_summary`: add a branch (mirror the TabsElement branch, using `ngettext` for the plural):

```python
    if name == "TwoColumnElement":
        n = len(TwoColumnElement.normalize_ids(el.data)["columns"])
        return ngettext("%(n)d column", "%(n)d columns", n) % {"n": n}
```

(Import `TwoColumnElement` where `TabsElement` is imported in this module.)

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_manage_editor_menu.py tests/test_twocolumn_save_views.py -v`
Expected: PASS (menu count 23, authoring GET/POST 200).

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/editor/_edit_twocolumn.html templates/courses/manage/editor/_element_row.html templates/courses/manage/editor/_add_menu.html courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_manage_editor_menu.py tests/test_twocolumn_save_views.py
git commit -m "feat(twocolumn): editor partial, per-column rows, palette card + labels"
```

---

## Task 9: i18n catalogs (EN + PL)

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

**Interfaces:**
- Consumes: all new `{% trans %}` / `gettext_lazy` / `_err` strings from Tasks 1–8.

- [ ] **Step 1: Regenerate catalogs**

Run: `uv run python manage.py makemessages -l en -l pl`
Expected: new msgids appear (e.g. "Two-column layout", "Columns", "Column %(n)d", "%(n)d column"/"%(n)d columns", "This column is empty.", the validator error strings). Watch the fuzzy-flag gotcha — remove any spurious `#, fuzzy` markers on the new entries.

Note: Task 5 **re-worded two existing `validate_nesting` strings** ("...parent that is not a tabs element." → "...container element."; "...references a tab its parent does not have." → "...references a slot..."). `makemessages` will mint these as new msgids and mark the old ones obsolete (`#~`). Provide fresh PL `msgstr` for the two new wordings and let the obsolete pair be dropped — otherwise `test_i18n_catalog` may flag an untranslated entry. No test asserts on these message strings, so runtime behavior is unaffected.

- [ ] **Step 2: Fill in Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po`, providing `msgstr` for each new `msgid` (e.g. "Two-column layout" → "Układ dwukolumnowy", "Columns" → "Kolumny", "This column is empty." → "Ta kolumna jest pusta.", plural forms for the column count). English `msgstr` can mirror the msgid.

- [ ] **Step 3: Compile + run catalog tests**

Run: `uv run python manage.py compilemessages && uv run pytest tests/test_i18n_catalog.py -v`
Expected: PASS (no untranslated/fuzzy new entries).

- [ ] **Step 4: Commit**

```bash
git add locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(twocolumn): EN/PL catalog entries"
```

---

## Task 10: Frontend-design pass (student render + editor)

**Files:**
- Modify: `templates/courses/elements/twocolumnelement.html`, `templates/courses/manage/editor/_edit_twocolumn.html`, the `.el--twocolumn` CSS (as design dictates)

**Interfaces:**
- Consumes: the working render from Tasks 7–8.

- [ ] **Step 1: Invoke the frontend-design skill**

Use the `frontend-design:frontend-design` skill to give the two-column student render and its editor an intentional, non-templated look consistent with the existing element system (Tabs/Callout as reference). Focus: equal-width column balance, the gutter/gap, empty-column affordance, and the editor's per-column grouping + count select.

- [ ] **Step 2: Verify light + dark with screenshots**

Drive the app (or a Playwright screenshot harness, mirroring `tests/test_e2e_tabs.py`) to capture the student render AND the editor in BOTH light and dark themes. Self-critique: column widths balanced, wraps cleanly at narrow widths, empty column reads intentionally, dark-mode borders/tokens correct. Iterate until it reads as designed, not default.

- [ ] **Step 3: Commit**

```bash
git add templates/courses/elements/twocolumnelement.html templates/courses/manage/editor/_edit_twocolumn.html courses/static
git commit -m "feat(twocolumn): frontend-design pass on render + editor (light+dark)"
```

---

## Task 11: e2e + full Definition-of-Done

**Files:**
- Create: `tests/test_e2e_twocolumn.py`

**Interfaces:**
- Consumes: the complete feature.

- [ ] **Step 1: Write the e2e test (mirror test_e2e_tabs.py)**

Drive the REAL UI (no `page.evaluate` shortcuts): add a two-column element, set count to 3, add a text child into two different columns via the per-column add-menus, save, open the taking view, and assert the three columns render side-by-side with the children in the right columns. Also exercise a shrink (3→2) and assert the third column's child moved (not vanished).

- [ ] **Step 2: Run the focused e2e**

Run: `uv run pytest tests/test_e2e_twocolumn.py -v` (foreground; do NOT background `-m e2e` — it spawns runaway browsers).
Expected: PASS.

- [ ] **Step 3: Full DoD sweep**

Run each and confirm clean:
- `uv run pytest -p no:cacheprovider -q` (or the project's standard non-e2e invocation) — full non-e2e suite green, including `tests/test_tabs_*` (regression) and `tests/test_manage_editor_menu.py`.
- `uv run pytest -m e2e -q` — full e2e green (watch for the drag-reorder `:scope > .el-row` regression with a two-column present; if `tests/test_tabs_editor_dnd.py` has an analogue, confirm dragging still works around an expanded two-column).
- `uv run ruff check .` and `uv run ruff format --check .` — clean.
- `uv run python manage.py makemigrations --check --dry-run` — no missing migrations.
- `uv run python manage.py makemessages -l en -l pl` then `git diff --exit-code locale/` — no uncommitted catalog drift.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_twocolumn.py
git commit -m "test(twocolumn): e2e coverage + DoD sweep"
```

---

## Self-Review Notes (author)

- **Spec coverage:** model + two normalizers (T1); container registry + resolve_scope (T2); count-only form (T3); grow/shrink/move (T4); transfer serializer/validator/builder + walk_unit_joins + validate_nesting (T5); has_math (T6); render + CSS + sprite (T7); editor partial + row branch + palette + labels + summary (T8); i18n (T9); frontend-design (T10); e2e + DoD (T11). All spec touch-points mapped.
- **No FORMAT_VERSION bump** — asserted unchanged in T5 Step 6.
- **Name consistency:** `normalize_ids` / `normalize_data` / `resolved_columns` / `new_column_id` / `COLUMN_ID_RE` / `column_count` used identically across tasks; transfer key `two_column`, form key `twocolumn`, model_name `twocolumnelement` used consistently.
- **Editor source-of-truth:** the row list uses the model's `resolved_columns()` (persisted-instance sourced via `normalize_data`) — no form-side `editor_rows` equivalent is needed, satisfying the spec's "sourced from persisted instance, not submitted data" requirement.
