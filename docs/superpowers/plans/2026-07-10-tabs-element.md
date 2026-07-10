# Tabs Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `TabsElement` course-content element that wraps other content elements in labelled tab panels — the codebase's first true element nesting.

**Architecture:** `Element` (the GFK join row) gains `parent` (self-FK) and `tab_id` (char). `TabsElement.data` holds only the tab labels + stable ids. Nested children keep their `unit` FK, so course/subtree delete keeps working untouched. One rule governs every existing element-list walker: **RENDER walkers exclude children (`parent__isnull=True`); COLLECT walkers include them; SCOPE walkers (ordering) partition by `(unit, parent, tab_id)`.**

**Tech Stack:** Django, PostgreSQL, vanilla JS (no framework), KaTeX, pytest + pytest-django, Playwright (e2e), ruff, `uv` for all tooling.

**Spec:** `docs/superpowers/specs/2026-07-10-tabs-element-design.md` — read it before Task 1. Every task below implements a part of it.

## Global Constraints

- Worktree: `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/tabs-element`, branch `pipeline/tabs-element`. Work only here.
- All tooling via `uv run` — `ruff`/`pytest`/`python` are **not** on the bash PATH. e.g. `uv run pytest`, `uv run ruff check`.
- **Never pipe pytest to `tail`** — it masks the exit code. Run it bare, then `echo "EXIT=$?"` on its own line.
- TDD: write the failing test, run it, see it fail, implement, see it pass, commit. One commit per task.
- **e2e discipline (load-bearing):** if your task touches e2e, run **only your focused test file, in the foreground**. Never `pytest -m e2e` (the whole suite), never a background/parked run — that spawns dozens of `chrome-headless-shell.exe` windows. The controller owns the full-suite check.
- No hardcoded test passwords. Use `tests.factories.TEST_PASSWORD`. CI's secret scanner fails the build on password literals.
- Module-level translatable dicts use `gettext_lazy`, never `gettext` — eager `gettext` freezes labels to English at import.
- Django `{# ... #}` comments must be **single-line**. Multi-line needs `{% comment %}...{% endcomment %}` or it renders as visible text.
- Icons are monochrome `currentColor` SVGs referenced from a sprite. Never emoji. `el-*` symbols live in `templates/courses/manage/_icon_sprite.html` at **16×16 fill**; `ed-*` symbols live in `templates/courses/manage/editor/editor.html`.
- `MIN_TABS = 2`, `MAX_TABS = 10`, `LABEL_MAX = 80`. Tab id format: literal `"t"` + 6 lowercase hex chars (7 total), fits `tab_id`'s `max_length=12`.
- `NESTABLE_TYPE_KEYS = {"text", "math", "image", "video", "iframe", "html", "table", "gallery"}` — a **positive** allowlist. Questions, slide breaks, and tabs-in-tabs are blocked.
- EN + PL translation catalogs must both be updated. Polish has 3 plural forms.

## File Structure

**Modify:**
- `courses/models.py` — `Element.parent`/`Element.tab_id`; new `TabsElement`; `ELEMENT_MODELS`.
- `courses/sanitize.py` — new `sanitize_label`.
- `courses/ordering.py` — scope sibling queries to `(unit, parent, tab_id)`.
- `courses/builder.py` — `NESTABLE_TYPE_KEYS`, `resolve_scope`, scoped reorder, recursive delete, tabs save + tab-removal diff.
- `courses/element_forms.py` — `TabsElementForm`, `FORM_FOR_TYPE`.
- `courses/views_manage.py` — allow-tuples, `_EDITOR_TYPE_LABELS`, `parent`/`tab` plumbing, three RENDER filters.
- `courses/views.py` — RENDER filters + `_tabs_has_math` recursion.
- `courses/quiz.py`, `courses/review.py`, `courses/views_review.py`, `courses/rollups.py` — defensive RENDER filters.
- `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS`, `element_summary`.
- `courses/transfer/{schema,export,payloads,importer}.py` — `FORMAT_VERSION` 2→3, `parent`/`tab` payload keys, two-pass import.
- `courses/static/courses/js/{math.js,editor.js,gallery.js}` — `.el--tabs` math scope; `libliInitTabs` hook; `libli:reveal` listener.
- `courses/static/courses/css/courses.css`, `editor.css`.
- `templates/courses/manage/_icon_sprite.html`, `.../editor/{_element_row,_add_menu,editor}.html`, `templates/courses/{lesson_unit,quiz_unit}.html`.

**Create:**
- `courses/migrations/0035_tabselement_element_parent_element_tab_id.py`
- `courses/static/courses/js/tabs.js`
- `templates/courses/elements/tabselement.html`
- `templates/courses/manage/editor/_edit_tabs.html`
- `tests/test_tabs_model.py`, `test_tabs_ordering_delete.py`, `test_tabs_form_views.py`, `test_tabs_invariant.py`, `test_tabs_transfer.py`, `test_tabs_css.py`, `test_tabs_partial.py`, `test_e2e_tabs.py`

---

### Task 1: Model, nesting substrate, migration

**Files:**
- Modify: `courses/models.py` (`ELEMENT_MODELS` ~255, `Element` ~276), `courses/sanitize.py`
- Create: `courses/migrations/0035_...`
- Test: `tests/test_tabs_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Element.parent` (self-FK, `related_name="children"`, nullable, CASCADE), `Element.tab_id` (`CharField(max_length=12, blank=True, default="")`).
  - `TabsElement` with `MIN_TABS=2`, `MAX_TABS=10`, `LABEL_MAX=80`, `TAB_ID_RE`, and staticmethods `new_tab_id(taken=())`, `default_data()`, `normalize_labels_and_ids(data)`, `normalize_data(data)`; instance methods `join_row()`, `resolved_tabs()`, `render()`; property `normalized_data`.
  - `courses.sanitize.sanitize_label(value, max_length=80)`.

**Key invariant:** `save()` calls `normalize_labels_and_ids` (non-destructive) and **must never call `normalize_data`** (destructive: pads/truncates, which would orphan children).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tabs_model.py`:

```python
import pytest

from courses.models import Element
from courses.models import TabsElement
from courses.sanitize import sanitize_label

pytestmark = pytest.mark.django_db


def test_new_tab_id_format_and_uniqueness():
    tid = TabsElement.new_tab_id()
    assert TabsElement.TAB_ID_RE.fullmatch(tid), tid
    assert len(tid) == 7
    assert TabsElement.new_tab_id({tid}) != tid


def test_default_data_has_min_tabs_with_distinct_ids():
    data = TabsElement.default_data()
    assert len(data["tabs"]) == TabsElement.MIN_TABS
    ids = [t["id"] for t in data["tabs"]]
    assert len(set(ids)) == len(ids)


def test_sanitize_label_strips_tags_and_truncates():
    assert sanitize_label("<b>Hi</b> there") == "Hi there"
    assert len(sanitize_label("x" * 200)) == 80
    assert sanitize_label(None) == ""


def test_normalize_labels_and_ids_is_non_destructive():
    """It may never change WHICH tabs exist — only their labels/ids."""
    raw = {"tabs": [{"id": "tabcdef", "label": "A"}]}
    out = TabsElement.normalize_labels_and_ids(raw)
    assert len(out["tabs"]) == 1  # NOT padded to MIN_TABS
    assert out["tabs"][0]["id"] == "tabcdef"


def test_normalize_labels_and_ids_fills_blank_label_and_missing_id():
    out = TabsElement.normalize_labels_and_ids({"tabs": [{}, {"label": "  "}]})
    assert out["tabs"][0]["label"] == "Tab 1"
    assert out["tabs"][1]["label"] == "Tab 2"
    assert all(TabsElement.TAB_ID_RE.fullmatch(t["id"]) for t in out["tabs"])


def test_normalize_labels_and_ids_keeps_first_duplicate_regenerates_later():
    out = TabsElement.normalize_labels_and_ids(
        {"tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "taaaaaa", "label": "B"}]}
    )
    assert out["tabs"][0]["id"] == "taaaaaa"
    assert out["tabs"][1]["id"] != "taaaaaa"


def test_normalize_data_pads_and_truncates():
    padded = TabsElement.normalize_data({"tabs": [{"id": "taaaaaa", "label": "A"}]})
    assert len(padded["tabs"]) == TabsElement.MIN_TABS
    many = {"tabs": [{"label": f"T{i}"} for i in range(30)]}
    assert len(TabsElement.normalize_data(many)["tabs"]) == TabsElement.MAX_TABS


@pytest.mark.parametrize("blob", [None, {}, {"tabs": None}, {"tabs": "x"}, "junk", []])
def test_normalize_data_never_raises(blob):
    out = TabsElement.normalize_data(blob)
    assert len(out["tabs"]) >= TabsElement.MIN_TABS


def test_save_does_not_pad_or_truncate():
    """save() runs only the non-destructive normalizer."""
    el = TabsElement(data={"tabs": [{"id": "taaaaaa", "label": "Solo"}]})
    el.save()
    el.refresh_from_db()
    assert len(el.data["tabs"]) == 1  # padding is read-side only


def test_save_never_rewrites_an_existing_unique_id():
    el = TabsElement.objects.create(data={"tabs": [{"id": "tbbbbbb", "label": "A"}]})
    el.data["tabs"][0]["label"] = "renamed"
    el.save()
    el.refresh_from_db()
    assert el.data["tabs"][0]["id"] == "tbbbbbb"


def test_element_defaults_to_top_level():
    f = Element._meta.get_field("parent")
    assert f.null is True
    assert Element._meta.get_field("tab_id").default == ""
```

- [ ] **Step 2: Run the tests, watch them fail**

```
uv run pytest tests/test_tabs_model.py -q
echo "EXIT=$?"
```
Expected: collection error / `ImportError: cannot import name 'TabsElement'`.

- [ ] **Step 3: Add `sanitize_label` to `courses/sanitize.py`**

Append after `desc_to_alt` (module already imports `html`, `nh3`, and defines `_WS`):

```python
def sanitize_label(value, max_length=80):
    """Plain-text label: strip every tag, unescape entities, collapse whitespace,
    truncate. Used for tab labels, which are plain text by design (never rich
    text, never math). Applied on BOTH the save and the read path, so a label
    dirtied by a direct DB edit never reaches a template as markup."""
    text = nh3.clean(value or "", tags=set(), attributes={}, link_rel=None)
    return _WS.sub(" ", html.unescape(text)).strip()[:max_length]
```

- [ ] **Step 4: Add the nesting fields to `Element` in `courses/models.py`**

Inside `class Element`, after the `unit` field:

```python
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    tab_id = models.CharField(max_length=12, blank=True, default="")
```

Note the docstring should be updated to mention nesting:

```python
    """GFK join-row: an ordered slot in a unit pointing at one concrete element.

    A row with `parent` set is a child of a TabsElement's join row, living in the
    tab named by `tab_id`. Children KEEP their `unit` FK, which is what lets
    Course.delete / ContentNode.delete sweep them up unchanged. `order` is compared
    only within a (unit, parent, tab_id) group, so groups may reuse integers.
    """
```

Do **not** change `order = OrderField(for_fields=["unit"], blank=True)`.

- [ ] **Step 5: Register the model name**

In `ELEMENT_MODELS`, append `"tabselement"` after `"galleryelement"`.

- [ ] **Step 6: Add `TabsElement` to `courses/models.py`**

Place it after `GalleryElement`. Add `import re` and `import secrets` at the top of the module if absent, and import `sanitize_label` alongside the existing `sanitize_cell` import.

```python
class TabsElement(ElementBase):
    """Tabbed container: holds ONLY the tab labels + stable ids. The children live
    in Element rows whose `parent` points at this element's join row.

    Two normalizers, deliberately separate:
      * normalize_labels_and_ids -- non-destructive; called by save(); persisted.
      * normalize_data           -- destructive (pads/truncates); read-side only.
    save() must NEVER call normalize_data: padding/truncation changes WHICH tabs
    exist, and persisting that would permanently orphan a tab's children.
    """

    MIN_TABS = 2
    MAX_TABS = 10
    LABEL_MAX = 80
    TAB_ID_RE = re.compile(r"t[0-9a-f]{6}")

    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)

    @staticmethod
    def new_tab_id(taken=()):
        """'t' + 6 lowercase hex (7 chars, fits tab_id's max_length=12). Unique
        only WITHIN one element, so collision is checked against `taken`."""
        while True:
            tid = "t" + secrets.token_hex(3)
            if tid not in taken:
                return tid

    @staticmethod
    def default_data():
        """The two empty tabs a freshly-added tabs element is born with. Labels are
        stored untranslated (they are stored data, not UI copy; translating at write
        time would freeze them to the author's locale)."""
        first = TabsElement.new_tab_id()
        second = TabsElement.new_tab_id({first})
        return {
            "tabs": [
                {"id": first, "label": "Tab 1"},
                {"id": second, "label": "Tab 2"},
            ]
        }

    @staticmethod
    def normalize_labels_and_ids(data):
        """NON-DESTRUCTIVE. Never changes which tabs exist, so it can never orphan a
        child by removing its tab. Fills blank labels, strips/truncates them, mints
        missing ids, and regenerates the LATER of a duplicate pair (the first keeps
        its id). Never raises."""
        data = data if isinstance(data, dict) else {}
        raw = data.get("tabs")
        raw = raw if isinstance(raw, list) else []
        tabs, taken = [], set()
        for i, item in enumerate(raw, start=1):
            item = item if isinstance(item, dict) else {}
            label = item.get("label")
            label = sanitize_label(label if isinstance(label, str) else "",
                                   TabsElement.LABEL_MAX)
            if not label:
                label = f"Tab {i}"
            tid = item.get("id")
            if (
                not isinstance(tid, str)
                or not TabsElement.TAB_ID_RE.fullmatch(tid)
                or tid in taken
            ):
                tid = TabsElement.new_tab_id(taken)
            taken.add(tid)
            tabs.append({"id": tid, "label": label})
        return {"tabs": tabs}

    @staticmethod
    def normalize_data(data):
        """DESTRUCTIVE (pads to MIN_TABS, truncates to MAX_TABS). READ-SIDE ONLY --
        called by resolved_tabs() when rendering a damaged blob, never persisted.
        Never raises. A blob can only become out-of-bounds via a direct DB edit: the
        form enforces the bounds on every authored write and import rejects them."""
        norm = TabsElement.normalize_labels_and_ids(data)
        tabs = norm["tabs"][: TabsElement.MAX_TABS]
        taken = {t["id"] for t in tabs}
        while len(tabs) < TabsElement.MIN_TABS:
            tid = TabsElement.new_tab_id(taken)
            taken.add(tid)
            tabs.append({"id": tid, "label": f"Tab {len(tabs) + 1}"})
        return {"tabs": tabs}

    def save(self, *args, **kwargs):
        self.data = self.normalize_labels_and_ids(self.data)
        super().save(*args, **kwargs)

    @property
    def normalized_data(self):
        return self.normalize_data(self.data)

    def join_row(self):
        """This concrete's single Element join row (the GFK is effectively 1:1).
        The ONE handle every children-consumer uses: render(), resolved_tabs(),
        has_math, and the export walk. order_by('pk') is defensive determinism."""
        return self.elements.order_by("pk").first()

    def resolved_tabs(self):
        """Ordered [(tab_dict, [child Element join rows])], grouped by tab_id and
        ordered by `order` within each group. EVERY tab is emitted, including empty
        ones -- a new tabs element has two empty tabs, and skipping them would erase
        them from the strip the enhancer builds. Children whose tab_id resolves to no
        tab (direct DB edit, read-side truncation) are skipped, never raised on."""
        tabs = self.normalize_data(self.data)["tabs"]
        join = self.join_row()
        if join is None:  # transient, mid-create
            return [(tab, []) for tab in tabs]
        by_tab = {}
        children = (
            join.children.order_by("order", "pk")
            .select_related("content_type")
            .prefetch_related("content_object")
        )
        for child in children:
            by_tab.setdefault(child.tab_id, []).append(child)
        return [(tab, by_tab.get(tab["id"], [])) for tab in tabs]

    def render(self):
        from django.template.loader import render_to_string

        join = self.join_row()
        return render_to_string(
            "courses/elements/tabselement.html",
            {"el": self, "tabs": self.resolved_tabs(), "eid": join.pk if join else 0},
        )
```

- [ ] **Step 7: Generate the migration**

```
uv run python manage.py makemigrations courses --name tabselement_element_parent_element_tab_id
echo "EXIT=$?"
```
It must create `TabsElement`, add `Element.parent` + `Element.tab_id`, and alter `Element.content_type`'s `limit_choices_to`. Verify with `uv run python manage.py makemigrations --check --dry-run` (expect "No changes detected").

- [ ] **Step 8: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_model.py -q
echo "EXIT=$?"
```
Expected: all pass.

- [ ] **Step 9: Lint and commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/models.py courses/sanitize.py courses/migrations/ tests/test_tabs_model.py
git commit -m "feat(tabs): TabsElement model + Element.parent/tab_id nesting substrate"
```

---

### Task 2: Scoped ordering + recursive delete

**Files:**
- Modify: `courses/ordering.py` (`compact_elements` ~47, `place_element` ~103), `courses/builder.py` (`reorder_element` ~158, `delete_element` ~181)
- Test: `tests/test_tabs_ordering_delete.py`

**Interfaces:**
- Consumes: `Element.parent`, `Element.tab_id`, `TabsElement` (Task 1).
- Produces:
  - `ordering.element_siblings(unit, parent, tab_id)` → QuerySet
  - `ordering.compact_elements(unit, parent=None, tab_id="")`
  - `ordering.place_element(element, unit, position)` — now scopes to the element's own `(parent, tab_id)`.
  - `builder.delete_element` deletes a tabs element's children's **concretes** before the parent.

**Why:** `ordering.py` is the spec's one SCOPE-class walker: it must *include* children but partition them. Filtering `parent__isnull=True` here would be wrong. And deleting a tabs element cascades child *join rows* via the `parent` FK, but child **concretes** are only reachable through the GFK — they would orphan.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tabs_ordering_delete.py`:

```python
import pytest

from courses import builder as builder_svc
from courses import ordering
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit  # use the existing helper

pytestmark = pytest.mark.django_db


def _tabs(unit):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    return obj, join


def _child(unit, join, tab_id, body="x"):
    txt = TextElement.objects.create(body=body)
    return Element.objects.create(
        unit=unit, content_object=txt, parent=join, tab_id=tab_id
    )


def test_siblings_are_scoped_to_parent_and_tab():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1, t2 = [t["id"] for t in obj.data["tabs"]]
    a = _child(unit, join, t1, "a")
    b = _child(unit, join, t1, "b")
    c = _child(unit, join, t2, "c")
    sibs = list(ordering.element_siblings(unit, join, t1))
    assert {e.pk for e in sibs} == {a.pk, b.pk}
    assert c.pk not in {e.pk for e in sibs}
    assert list(ordering.element_siblings(unit, None, "")) == [join]


def test_compact_elements_renumbers_only_its_own_group():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1 = obj.data["tabs"][0]["id"]
    a = _child(unit, join, t1, "a")
    b = _child(unit, join, t1, "b")
    Element.objects.filter(pk=a.pk).update(order=7)
    Element.objects.filter(pk=b.pk).update(order=9)
    ordering.compact_elements(unit, parent=join, tab_id=t1)
    a.refresh_from_db()
    b.refresh_from_db()
    join.refresh_from_db()
    assert (a.order, b.order) == (0, 1)
    assert join.order == 0  # top-level group untouched


def test_reorder_within_a_tab_succeeds():
    """The regression the spec's scope-immutability rule exists to protect: a
    within-tab reorder sends no parent/tab and must still work."""
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1 = obj.data["tabs"][0]["id"]
    a = _child(unit, join, t1, "a")
    b = _child(unit, join, t1, "b")
    unit.refresh_from_db()
    builder_svc.reorder_element(
        course, str(b.pk), unit.updated.isoformat(), direction="up"
    )
    a.refresh_from_db()
    b.refresh_from_db()
    assert b.order < a.order


def test_deleting_tabs_element_leaves_zero_orphaned_concretes():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1, t2 = [t["id"] for t in obj.data["tabs"]]
    _child(unit, join, t1, "a")
    _child(unit, join, t2, "b")
    assert TextElement.objects.count() == 2
    unit.refresh_from_db()
    builder_svc.delete_element(course, str(join.pk), unit.updated.isoformat())
    assert TextElement.objects.count() == 0  # concretes gone, not orphaned
    assert TabsElement.objects.count() == 0
    assert Element.objects.filter(unit=unit).count() == 0


def test_deleting_a_nested_child_leaves_the_tabs_element():
    course, unit = make_course_with_unit()
    obj, join = _tabs(unit)
    t1 = obj.data["tabs"][0]["id"]
    child = _child(unit, join, t1, "a")
    unit.refresh_from_db()
    builder_svc.delete_element(course, str(child.pk), unit.updated.isoformat())
    assert TextElement.objects.count() == 0
    assert TabsElement.objects.filter(pk=obj.pk).exists()
```

If `tests/factories.py` has no `make_course_with_unit`, use whatever course/unit factory the neighbouring tests (`tests/test_gallery_model.py`, `tests/test_manage_element_ops.py`) already use — do **not** invent a new one, and never add a password literal.

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_ordering_delete.py -q
echo "EXIT=$?"
```
Expected: `AttributeError: module 'courses.ordering' has no attribute 'element_siblings'`.

- [ ] **Step 3: Scope the sibling queries in `courses/ordering.py`**

Replace `compact_elements` and `place_element` with:

```python
def element_siblings(unit, parent, tab_id):
    """The ordering group an element belongs to. Elements are ordered ONLY within
    their (unit, parent, tab_id) group, so two groups may freely reuse the same
    `order` integers (OrderField tolerates duplicates within a scope).
    `parent=None, tab_id=""` is the top-level group.

    This is the spec's one SCOPE-class walker: it INCLUDES nested children but
    partitions them. Filtering parent__isnull=True here would be actively wrong.
    """
    return Element.objects.filter(unit=unit, parent=parent, tab_id=tab_id)


def compact_elements(unit, parent=None, tab_id=""):
    els = list(element_siblings(unit, parent, tab_id).order_by("order", "pk"))
    assign_orders_elements(els)


def place_element(element, unit, position):
    """Insert `element` at a 0-based `position` among its OWN group's other elements
    (clamped 0..len(others)), renumbering only rows whose order changed. Returns True
    iff any order changed. `others` is the POST-REMOVAL sibling list."""
    others = list(
        element_siblings(unit, element.parent, element.tab_id)
        .select_for_update()
        .exclude(pk=element.pk)
        .order_by("order", "pk")
    )
    if position is None or position > len(others):
        position = len(others)
    if position < 0:
        position = 0
    ordered = others[:position] + [element] + others[position:]
    changed = False
    for idx, el in enumerate(ordered):
        if el.order != idx:
            el.order = idx
            el.save(update_fields=["order"])
            changed = True
    return changed
```

- [ ] **Step 4: Scope `reorder_element`, make `delete_element` recursive**

In `courses/builder.py` replace both functions:

```python
@transaction.atomic
def reorder_element(course, element_pk, unit_token, *, direction=None, position=None):
    """Reorder WITHIN the element's own scope. Takes no parent/tab: a reorder gesture
    never sends them (top-level reorders never have), so scope is read off the row.
    That is also what makes a cross-scope move impossible by construction."""
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    if position is not None:
        changed = ordering.place_element(el, unit, position)
    else:
        siblings = list(
            ordering.element_siblings(unit, el.parent, el.tab_id)
            .select_for_update()
            .order_by("order", "pk")
        )
        moved = ordering.move_in_list(siblings, el, direction)
        if moved is None:
            return unit, False
        ordering.assign_orders_elements(moved)
        changed = True
    if not changed:
        return unit, False
    unit.save(update_fields=["updated"])
    return unit, True


@transaction.atomic
def delete_element(course, element_pk, unit_token):
    """Delete an element. If it is a tabs element, its children's CONCRETE rows must
    go first: the `parent` FK cascades the child join rows, but a concrete is only
    reachable through the GFK, which DB cascade cannot traverse -- they would orphan.
    """
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)
    parent, tab_id = el.parent, el.tab_id  # capture before the row disappears
    _delete_element_content_objects(Element.objects.filter(parent=el))
    obj = el.content_object
    if obj is not None:
        obj.delete()  # cascades the Element join-row via GenericRelation
    else:
        el.delete()
    ordering.compact_elements(unit, parent=parent, tab_id=tab_id)
    unit.save(update_fields=["updated"])
    return unit
```

Add `from courses.models import _delete_element_content_objects` to `courses/builder.py`'s imports. `Element.objects.filter(parent=el)` is empty for every non-tabs element, so the extra call costs one cheap query and needs no `isinstance` branch.

- [ ] **Step 5: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_ordering_delete.py -q
echo "EXIT=$?"
```

- [ ] **Step 6: Neighbouring ordering suites must stay green**

```
uv run pytest tests/test_ordering.py tests/test_manage_element_ops.py tests/test_element_editor_ops.py -q
echo "EXIT=$?"
```
`compact_elements(unit)` keeps its old single-argument call sites working because `parent`/`tab_id` default to the top-level group.

- [ ] **Step 7: Lint and commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/ordering.py courses/builder.py tests/test_tabs_ordering_delete.py
git commit -m "feat(tabs): scope element ordering to (unit,parent,tab_id); recursive delete"
```

---

### Task 3: TabsElementForm, scope resolution, tab-removal diff

**Files:**
- Modify: `courses/element_forms.py` (add form; `FORM_FOR_TYPE` ~714), `courses/builder.py` (`save_element` ~206)
- Test: `tests/test_tabs_form_views.py`

**Interfaces:**
- Consumes: `TabsElement` (Task 1); `_delete_element_content_objects` import (Task 2).
- Produces:
  - `element_forms.TabsElementForm` (ModelForm on `data`, property `editor_rows` → `[{id,label}]`), registered as `FORM_FOR_TYPE["tabs"]`.
  - `builder.NESTABLE_TYPE_KEYS`, `builder.NestingError`, `builder.resolve_scope(unit, parent_ref, tab, type_key)` → `(parent_join_or_None, tab_id_str)`.
  - `save_element(...)` reads `parent`/`tab` from `post_data` **on create only**, and runs the tab-removal diff for tabs elements.

**The two data-loss traps this task must not fall into:**
1. The removed-tab diff must never read `t["id"]` off a raw submitted row — a save that adds *and* deletes a tab in one gesture sends a brand-new row with no id yet, and a bare `t["id"]` raises `KeyError`. Structural fix below: mint ids in the form first, then diff.
2. `save_element` on **update** must never write `parent`/`tab_id`; the edit form does not resubmit them, so "absent means top-level" would silently reparent every nested child on every edit.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tabs_form_views.py`:

```python
import json

import pytest

from courses import builder as builder_svc
from courses.element_forms import FORM_FOR_TYPE
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

Form = FORM_FOR_TYPE["tabs"]


def _bound(payload):
    return Form(data={"data": json.dumps(payload)})


def test_blank_add_yields_two_default_tabs():
    form = Form(data={"data": ""})
    assert form.is_valid(), form.errors
    assert len(form.cleaned_data["data"]["tabs"]) == TabsElement.MIN_TABS


def test_rejects_below_min_tabs():
    assert not _bound({"tabs": [{"id": "taaaaaa", "label": "only"}]}).is_valid()


def test_rejects_above_max_tabs():
    assert not _bound({"tabs": [{"label": f"T{i}"} for i in range(11)]}).is_valid()


def test_preserves_submitted_ids():
    form = _bound(
        {"tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]}
    )
    assert form.is_valid(), form.errors
    assert [t["id"] for t in form.cleaned_data["data"]["tabs"]] == [
        "taaaaaa",
        "tbbbbbb",
    ]


def test_mints_id_for_a_new_idless_row():
    form = _bound({"tabs": [{"id": "taaaaaa", "label": "A"}, {"label": "New"}]})
    assert form.is_valid(), form.errors
    assert TabsElement.TAB_ID_RE.fullmatch(form.cleaned_data["data"]["tabs"][1]["id"])


def _make_tabs(unit):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    return obj, join


def _post(unit, **extra):
    d = {"unit_token": unit.updated.isoformat(), "unit": str(unit.pk)}
    d.update(extra)
    return d


def test_create_nested_child_sets_parent_and_tab():
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    tab = obj.data["tabs"][1]["id"]
    unit.refresh_from_db()
    builder_svc.save_element(
        course, unit.pk, "text", "new",
        _post(unit, body="hi", parent=str(join.pk), tab=tab), {},
    )
    child = Element.objects.get(parent=join)
    assert child.tab_id == tab
    assert child.unit_id == unit.pk  # children KEEP their unit FK


def test_update_of_a_nested_child_never_reparents_it():
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    tab = obj.data["tabs"][0]["id"]
    txt = TextElement.objects.create(body="a")
    child = Element.objects.create(
        unit=unit, content_object=txt, parent=join, tab_id=tab
    )
    unit.refresh_from_db()
    builder_svc.save_element(
        course, unit.pk, "text", str(child.pk), _post(unit, body="edited"), {}
    )
    child.refresh_from_db()
    assert child.parent_id == join.pk and child.tab_id == tab


@pytest.mark.parametrize(
    "kwargs",
    [
        {"parent": "PARENT"},                    # parent without tab
        {"tab": "taaaaaa"},                      # tab without parent
        {"parent": "PARENT", "tab": "tzzzzzz"},  # tab not in parent
        {"parent": "999999", "tab": "taaaaaa"},  # unknown parent
        {"parent": "abc", "tab": "taaaaaa"},     # non-numeric parent ref
    ],
)
def test_bad_scope_raises_nesting_error(kwargs):
    course, unit = make_course_with_unit()
    _obj, join = _make_tabs(unit)
    kwargs = {k: (str(join.pk) if v == "PARENT" else v) for k, v in kwargs.items()}
    unit.refresh_from_db()
    with pytest.raises(builder_svc.NestingError):
        builder_svc.save_element(
            course, unit.pk, "text", "new", _post(unit, body="x", **kwargs), {}
        )


def test_non_nestable_child_type_raises():
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    tab = obj.data["tabs"][0]["id"]
    unit.refresh_from_db()
    with pytest.raises(builder_svc.NestingError):  # tabs-in-tabs
        builder_svc.save_element(
            course, unit.pk, "tabs", "new",
            _post(unit, data="", parent=str(join.pk), tab=tab), {},
        )


def test_deleting_a_tab_deletes_exactly_that_tabs_children():
    """Also covers the add-and-delete-in-one-save KeyError trap: the submitted list
    carries a brand-new, id-less row alongside the survivor."""
    course, unit = make_course_with_unit()
    obj, join = _make_tabs(unit)
    keep, drop = [t["id"] for t in obj.data["tabs"]]
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="keep"),
        parent=join, tab_id=keep,
    )
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="drop"),
        parent=join, tab_id=drop,
    )
    unit.refresh_from_db()
    payload = json.dumps(
        {"tabs": [{"id": keep, "label": "Keep"}, {"label": "Brand new"}]}
    )
    builder_svc.save_element(
        course, unit.pk, "tabs", str(join.pk), _post(unit, data=payload), {}
    )
    assert set(TextElement.objects.values_list("body", flat=True)) == {"keep"}
    assert not Element.objects.filter(parent=join, tab_id=drop).exists()
    obj.refresh_from_db()
    assert len(obj.data["tabs"]) == 2  # survivor + the minted new tab
```

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_form_views.py -q
echo "EXIT=$?"
```
Expected: `KeyError: 'tabs'` from `FORM_FOR_TYPE`.

- [ ] **Step 3: Add `TabsElementForm` to `courses/element_forms.py`**

Place it after `GalleryElementForm`; import `TabsElement` from `courses.models`.

```python
class TabsElementForm(forms.ModelForm):
    """Tab labels only -- the children are Element rows, not form data. The hidden
    name="data" field is the sole authoritative input; tabs_editor.js mirrors the
    label rows into it, carrying each SURVIVING tab's id so it round-trips. Only a
    genuinely new row arrives id-less; the server mints its id here."""

    class Meta:
        model = TabsElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Same rationale as TableElementForm/GalleryElementForm: JSONField(default=dict)
        # is required and {} is empty, so "add tabs, Save without editing" would fail
        # "This field is required" before clean_data runs.
        self.fields["data"].required = False

    def clean_data(self):
        raw = self.cleaned_data.get("data")
        raw = raw if isinstance(raw, dict) else {}
        tabs = raw.get("tabs")
        if tabs is None:
            # Plain add + save with no edit -> the two default tabs. Built explicitly
            # rather than via normalize_data, because normalize_data is the DESTRUCTIVE
            # read-side normalizer and must never be reachable from a write path.
            return TabsElement.default_data()
        if not isinstance(tabs, list):
            raise forms.ValidationError(_("A tabs element needs a list of tabs."))
        if len(tabs) < TabsElement.MIN_TABS:
            raise forms.ValidationError(
                _("A tabs element must keep at least %(n)d tabs.")
                % {"n": TabsElement.MIN_TABS}
            )
        if len(tabs) > TabsElement.MAX_TABS:
            raise forms.ValidationError(
                _("A tabs element is limited to %(n)d tabs.")
                % {"n": TabsElement.MAX_TABS}
            )
        # Mints ids for new rows and preserves existing unique ones. Doing it HERE is
        # what lets save_element diff old-vs-new ids without ever touching a raw row.
        return TabsElement.normalize_labels_and_ids({"tabs": tabs})

    @property
    def editor_rows(self):
        """[{id, label}] for the editor: from submitted data when bound (so an invalid
        re-render keeps the author's edits), else from the instance."""
        source = (
            self._raw_data_json() if self.is_bound else getattr(self.instance, "data", {})
        )
        return TabsElement.normalize_labels_and_ids(source)["tabs"]

    def _raw_data_json(self):
        import json

        try:
            return json.loads(self.data.get("data") or "{}")
        except (ValueError, TypeError):
            return {}
```

Register it: add `"tabs": TabsElementForm,` to `FORM_FOR_TYPE`.

- [ ] **Step 4: Add scope resolution to `courses/builder.py`**

Near the top of the module (after the existing exception classes):

```python
class NestingError(Exception):
    """A nested add/save violated the nesting rules -> HTTP 400."""


# Positive allowlist: any type NOT named here is non-nestable, including types added
# by future slices. Deliberately NOT the element_add/element_save allow-tuples, which
# admit every question type and slidebreak.
NESTABLE_TYPE_KEYS = frozenset(
    {"text", "math", "image", "video", "iframe", "html", "table", "gallery"}
)


def resolve_scope(unit, parent_ref, tab, type_key):
    """Validate and resolve a nested element's scope. Returns (parent_join|None, tab_id).

    `parent` and `tab` come together or not at all; neither means top-level. Any
    violation raises NestingError, which the view turns into a 400. Filtering the
    parent by `unit` enforces same-unit and (transitively) same-course, because `unit`
    was already resolved against the course by the caller.
    """
    parent_ref = (parent_ref or "").strip()
    tab = (tab or "").strip()
    if not parent_ref and not tab:
        return None, ""
    if not parent_ref or not tab:
        raise NestingError("parent and tab must be supplied together")
    try:
        join = Element.objects.filter(pk=int(parent_ref), unit=unit).first()
    except (TypeError, ValueError):
        raise NestingError("bad parent ref") from None
    if join is None:
        raise NestingError("unknown parent")
    parent_obj = join.content_object
    if not isinstance(parent_obj, TabsElement):
        raise NestingError("parent is not a tabs element")
    if tab not in {t["id"] for t in parent_obj.normalized_data["tabs"]}:
        raise NestingError("unknown tab")
    if type_key not in NESTABLE_TYPE_KEYS:
        raise NestingError(f"{type_key} may not be nested")
    return join, tab
```

Import `TabsElement` and `_delete_element_content_objects` in `courses/builder.py`.

- [ ] **Step 5: Add the `tabs` branch to `save_element`**

Immediately before the final `else:` of the type ladder:

```python
    elif type_key == "tabs":
        # Capture the OLD tab ids BEFORE the form mutates instance.data on save.
        old_ids = (
            set()
            if instance is None
            else {t["id"] for t in TabsElement.normalize_labels_and_ids(instance.data)["tabs"]}
        )
        form = FORM_FOR_TYPE["tabs"](data=post_data, instance=instance)
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()
        if join is not None:
            # clean_data already minted ids for new rows, so new_ids is complete and a
            # brand-new tab can never be mistaken for a removal.
            new_ids = {t["id"] for t in obj.data["tabs"]}
            removed = old_ids - new_ids
            if removed:
                # Concretes first -- the join rows cascade, the concretes would orphan.
                doomed = Element.objects.filter(parent=join, tab_id__in=removed)
                _delete_element_content_objects(doomed)
                Element.objects.filter(parent=join, tab_id__in=removed).delete()
```

- [ ] **Step 6: Thread scope into the create at the bottom of `save_element`**

```python
    title = (post_data.get("el_title") or "").strip()
    if join is None:
        # Scope is chosen ONCE, at creation, and is immutable thereafter.
        parent_join, tab_id = resolve_scope(
            unit, post_data.get("parent"), post_data.get("tab"), type_key
        )
        Element.objects.create(
            unit=unit,
            content_object=obj,
            title=title,
            parent=parent_join,
            tab_id=tab_id,
        )
    elif join.title != title:
        join.title = title
        join.save(update_fields=["title"])
    # NOTE: the update path deliberately never touches join.parent / join.tab_id. The
    # inline edit form does not resubmit them; writing "absent means top-level" here
    # would silently reparent every nested child on every edit.
    unit.save(update_fields=["updated"])
    return unit
```

- [ ] **Step 7: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_form_views.py -q
echo "EXIT=$?"
```

- [ ] **Step 8: Lint and commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/element_forms.py courses/builder.py tests/test_tabs_form_views.py
git commit -m "feat(tabs): TabsElementForm, scope resolution, tab-removal child cleanup"
```

---

### Task 4: The invariant — RENDER filters and `has_math` recursion

**Files:**
- Modify: `courses/views.py` (`build_lesson_context`, `build_quiz_context`, both `has_math` expressions, **and the `seen` endpoint**), `courses/views_manage.py` (three element-row queries), `courses/quiz.py`, `courses/review.py` (×2), `courses/views_review.py`, `courses/rollups.py` (×2)
- Test: `tests/test_tabs_invariant.py`

Line numbers below are **indicative only** — anchor on the function name, which is stable.

**Interfaces:**
- Consumes: `TabsElement.join_row()` (Task 1).
- Produces: `views._tabs_has_math(el)` and `views._element_has_math(obj)`.

**The rule, applied exactly once per walker:**

| Walker | Class | Change |
|---|---|---|
| `views.build_lesson_context` element list | RENDER | `.filter(parent__isnull=True)` |
| `views.build_quiz_context` element list | RENDER | same |
| **`views.seen` endpoint's `current` set** | RENDER | **same — see below; this one is a real bug, not defensive** |
| `views_manage` three element-row queries | RENDER | same |
| `quiz.py`, `review.py` ×2, `views_review.py`, `rollups.py` ×2 | RENDER | same (defensive — a question can never nest in v1) |
| `has_math` (lesson **and** quiz) | COLLECT, **must recurse** | consumes the already-filtered list |

Exempt, and deliberately unchanged: the quiz-**results** page (renders question rows only, and a question can never nest) and `partition_into_slides()` (a downstream consumer of the already-filtered list — **verify** it does not re-query the unit).

**The `seen` walker breaks unit completion, and the spec missed it.** In `courses/views.py`'s `seen` endpoint (~329):

```python
    current = set(node.elements.exclude(content_type=break_ct).values_list("pk", flat=True))
```

Completion is gated on `current.issubset(merged)`. Without the filter, every nested child's pk lands in `current` — but the frontend only ever reports `.lesson-block[data-element-id]` ids, and `_lesson_article.html` emits those sections for **top-level elements only**. A nested child's pk therefore can never enter `merged`, so **any lesson containing a tabs element with children would never complete.** This is a RENDER walker (it enumerates the blocks a student can see) and needs the same filter. Add it to the spec's invariant table too, in the same commit.

`has_math` is the highest-risk line: if it does not recurse, math authored inside tab 2 never typesets, and it fails silently because tab 1 usually has no math to reveal it. The recursion must dispatch each child through the **per-type predicate** (`_table_has_math`, `_gallery_has_math`, …), never `isinstance(child, MathElement)` — math lives in gallery descriptions and table cells too.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tabs_invariant.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import GalleryElement
from courses.models import MediaAsset
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _tabs_with_child(unit, child_obj, tab_index=1):
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][tab_index]["id"]
    Element.objects.create(
        unit=unit, content_object=child_obj, parent=join, tab_id=tab_id
    )
    return tabs, join


def test_nested_child_is_not_a_top_level_lesson_block(client, django_user_model):
    from courses.views import build_lesson_context

    course, unit = make_course_with_unit()
    _tabs_with_child(unit, TextElement.objects.create(body="inside"))
    ctx = build_lesson_context(unit, django_user_model.objects.create(username="u"))
    assert len(ctx["elements"]) == 1  # the tabs element only
    assert all(el.parent_id is None for el in ctx["elements"])


def test_nested_child_is_not_a_top_level_editor_row():
    from courses.views_manage import _editor_rows

    course, unit = make_course_with_unit()
    _tabs_with_child(unit, TextElement.objects.create(body="inside"))
    join_rows, rows = _editor_rows(unit)
    assert len(join_rows) == 1
    assert all(j.parent_id is None for j in join_rows)


def test_has_math_recurses_into_a_nested_gallery_description(
    django_user_model, tmp_path, settings
):
    """A bare nested MathElement would pass even a naive isinstance() recursion.
    A gallery DESCRIPTION forces the per-type predicate path."""
    from courses.views import build_lesson_context

    course, unit = make_course_with_unit()
    a = MediaAsset.objects.create(course=course, kind="image", file="x.png")
    b = MediaAsset.objects.create(course=course, kind="image", file="y.png")
    gal = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": a.pk, "desc": r"\(x^2\)"},
                {"media": b.pk, "desc": ""},
            ],
        }
    )
    _tabs_with_child(unit, gal)
    ctx = build_lesson_context(unit, django_user_model.objects.create(username="m"))
    assert ctx["has_math"] is True


def test_a_unit_with_a_populated_tabs_element_can_still_complete():
    """The `seen` endpoint's `current` set must exclude nested children. The frontend
    only ever reports top-level .lesson-block ids, so a nested pk in `current` could
    never be satisfied and the unit would never complete."""
    from courses.views import _seen_current_ids

    course, unit = make_course_with_unit()
    tabs, join = _tabs_with_child(unit, TextElement.objects.create(body="inside"))
    current = _seen_current_ids(unit)
    assert current == {join.pk}, "a nested child's pk leaked into the completion set"


def test_quiz_has_math_recurses_into_a_nested_gallery_description(
    django_user_model,
):
    from courses.models import ContentNode
    from courses.views import build_quiz_context

    course, unit = make_course_with_unit()
    unit.is_quiz = True  # adapt to however the repo marks a quiz unit
    unit.save()
    a = MediaAsset.objects.create(course=course, kind="image", file="x.png")
    b = MediaAsset.objects.create(course=course, kind="image", file="y.png")
    gal = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [
                {"media": a.pk, "desc": r"\(y^2\)"},
                {"media": b.pk, "desc": ""},
            ],
        }
    )
    _tabs_with_child(unit, gal)
    ctx = build_quiz_context(unit, django_user_model.objects.create(username="q"))
    assert ctx["has_math"] is True
```

Adapt the quiz-unit construction and the user/enrolment helpers to the repo's existing conventions (see `tests/test_quiz_*.py`). Never introduce a password literal — import `TEST_PASSWORD` from `tests.factories` if a login is needed.

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_invariant.py -q
echo "EXIT=$?"
```
Expected: the two element-count assertions fail (nested child leaks in) and `has_math` is `False`.

- [ ] **Step 3: Add the RENDER filter to every render walker**

In `courses/views.py`, both `build_lesson_context` and `build_quiz_context`:

```python
    elements = list(
        node.elements.filter(parent__isnull=True)  # RENDER: children render inside their tabs
        .order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
```

In `courses/views_manage.py`, all three queries — e.g.

```python
        elements = list(
            node.elements.filter(parent__isnull=True)
            .select_related("content_type")
            .order_by("order", "pk")
        )
```
and, in `_editor_rows`'s source query,
```python
    join_rows = list(
        unit.elements.filter(parent__isnull=True)
        .select_related("content_type", "unit__course")
        .order_by("order", "pk")
    )
```

In the `seen` endpoint (~329) — **this one fixes a real completion bug, not a hypothetical one.** Extract the expression into a module-level helper so the view and the regression test reference **one** symbol rather than two copies that can drift:

```python
def _seen_current_ids(node):
    """Element pks a student must see to complete `node`. Excludes slide breaks (never
    "seen") and nested children: the frontend only reports .lesson-block[data-element-id]
    ids, which _lesson_article.html emits for top-level elements only. A nested pk here
    could never be satisfied, so the unit would never complete."""
    break_ct = ContentType.objects.get_for_model(SlideBreakElement).id
    return set(
        node.elements.filter(parent__isnull=True)
        .exclude(content_type=break_ct)
        .values_list("pk", flat=True)
    )
```

and call it from `seen`: `current = _seen_current_ids(node)`. Read the existing `seen` view first — reuse whatever it already computes for `break_ct` rather than duplicating the lookup.

In `courses/quiz.py` (~104), `courses/review.py` (~107 and ~171), `courses/views_review.py` (~68), and `courses/rollups.py` (~159 and ~195), add `.filter(parent__isnull=True)` to each `elements` query. These are defensive: a question can never be nested in v1, so they cannot change behaviour today — they exist so the later questions-in-tabs slice starts from a correct baseline.

Also update the spec's invariant table (`docs/superpowers/specs/2026-07-10-tabs-element-design.md`) to list the `seen` walker, and stage it in this task's commit. The spec claimed the table was an exhaustive enumeration; it was one short.

- [ ] **Step 4: Add the `has_math` recursion to `courses/views.py`**

After `_gallery_has_math`:

```python
def _element_has_math(obj):
    """Per-type math detection for ONE concrete element. Shared by the top-level walk
    and the tabs recursion, so a nested gallery description or table cell is found the
    same way a top-level one is."""
    from courses.models import MathElement
    from courses.models import TextElement

    if isinstance(obj, MathElement):
        return True
    if isinstance(obj, TextElement):
        return has_math_delimiters(obj.body)
    return _table_has_math(obj) or _gallery_has_math(obj)


def _tabs_has_math(el):
    """COLLECT + MUST RECURSE. `has_math` consumes the element list AFTER the RENDER
    filter has removed nested children, so it has to walk into them itself. Dispatches
    each child through _element_has_math -- an isinstance(child, MathElement) shortcut
    would pass a bare-MathElement test while silently missing math inside a nested
    gallery description or table cell."""
    from courses.models import TabsElement

    if not isinstance(el, TabsElement):
        return False
    join = el.join_row()
    if join is None:
        return False
    return any(
        _element_has_math(child.content_object)
        for child in join.children.prefetch_related("content_object")
    )
```

Add one clause to **both** `has_math` expressions (lesson ~152 and quiz ~492):

```python
        or any(_tabs_has_math(el.content_object) for el in elements)
```

- [ ] **Step 5: Verify `partition_into_slides` does not re-query**

```
uv run python - <<'PY'
import inspect, courses.slideshow as s
print(inspect.getsource(s.partition_into_slides))
PY
```
It must operate purely on the list it is handed. If it queries `Element.objects` or `unit.elements`, add the same `parent__isnull=True` filter there and say so in the commit message.

- [ ] **Step 6: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_invariant.py -q
echo "EXIT=$?"
```

- [ ] **Step 7: Run the consumption + analytics suites (the filters touched them)**

```
uv run pytest tests/ -q -k "lesson or quiz or review or rollup or slideshow or analytics"
echo "EXIT=$?"
```

- [ ] **Step 8: Lint and commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/views.py courses/views_manage.py courses/quiz.py courses/review.py courses/views_review.py courses/rollups.py tests/test_tabs_invariant.py
git commit -m "feat(tabs): RENDER filters on every element walker + has_math recursion"
```

---

### Task 5: Manage-UI registry (labels, summary, editor labels, allow-tuples, views)

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS` ~25, `element_summary` ~69), `courses/views_manage.py` (`_EDITOR_TYPE_LABELS` ~723, `element_add` allow-tuple ~846, `element_save` allow-tuple ~878, `_render_open_form`, `element_form` ~937)
- Test: `tests/test_tabs_registry.py`

**Interfaces:**
- Consumes: `TabsElement` (Task 1), `builder.NestingError` + `resolve_scope` (Task 3).
- Produces: `element_add`/`element_save` accept `parent`+`tab` and return **400** on any nesting violation; `_render_open_form(..., parent="", tab="")` renders them as hidden fields so scope survives the two-hop create.

**Why the hidden fields matter:** adding a nested element is two requests. The nested add menu's `data-parent`/`data-tab` go to `element_add`, which only *renders* a blank host form; a later `element_save` persists. Without hidden fields, scope is lost between the hops and `element_save` silently creates the child at top level.

The gallery slice shipped a raw `GalleryElement` class name in the element list because it forgot `_ELEMENT_LABELS` + `element_summary`. Do not repeat that.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tabs_registry.py`:

```python
import json

import pytest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import activate

from courses.models import Element
from courses.models import TabsElement
from courses.templatetags.courses_manage_extras import element_summary
from tests.factories import TEST_PASSWORD
from tests.factories import make_course_with_unit
from tests.factories import make_teacher  # or the repo's existing manage-user helper

pytestmark = pytest.mark.django_db


def test_element_summary_pluralises_tabs_not_class_name():
    el = TabsElement(data=TabsElement.default_data())
    assert element_summary(el) == "2 tabs"
    one = TabsElement(data={"tabs": [{"id": "taaaaaa", "label": "A"}]})
    assert element_summary(one) == "1 tab"
    assert "TabsElement" not in element_summary(el)


def test_element_summary_polish_plural_forms():
    activate("pl")
    try:
        five = TabsElement(
            data={"tabs": [{"id": f"t{i:06x}", "label": "x"} for i in range(5)]}
        )
        assert "TabsElement" not in element_summary(five)
    finally:
        activate("en")


def _login(client, course):
    user = make_teacher(course)
    client.login(username=user.username, password=TEST_PASSWORD)
    return user


def test_add_tabs_renders_the_editor_form(client):
    course, unit = make_course_with_unit()
    _login(client, course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "tabs", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b"data-tabs-editor" in resp.content


def test_nested_add_embeds_parent_and_tab_as_hidden_fields(client):
    course, unit = make_course_with_unit()
    _login(client, course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab = tabs.data["tabs"][1]["id"]
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "parent": join.pk, "tab": tab},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert f'name="parent" value="{join.pk}"' in html
    assert f'name="tab" value="{tab}"' in html


@pytest.mark.parametrize(
    "post",
    [
        {"type": "choicequestion"},          # question inside a tab
        {"type": "slidebreak"},              # slide break inside a tab
        {"type": "tabs"},                    # tabs inside a tab
    ],
)
def test_nested_add_of_a_blocked_type_is_400(client, post):
    course, unit = make_course_with_unit()
    _login(client, course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"unit": unit.pk, "parent": join.pk, "tab": tabs.data["tabs"][0]["id"], **post},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 400


def test_parent_without_tab_is_400(client):
    course, unit = make_course_with_unit()
    _login(client, course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "parent": join.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_registry.py -q
echo "EXIT=$?"
```

- [ ] **Step 3: Create a MINIMAL `_edit_tabs.html` so the add form can render**

`_host_form.html` includes `courses/manage/editor/_edit_{{ type_key }}.html`, so rendering the tabs add form raises `TemplateDoesNotExist` until that partial exists. Task 8 builds the real one; this task needs a stub that satisfies its own green gate:

```html
{% load i18n %}
{% comment %}Minimal tabs editor -- Task 8 replaces this with the full label editor.{% endcomment %}
<div class="el-editor el-editor--tabs" data-tabs-editor>
  <input type="hidden" name="data" value="{{ form.data.data|default:'' }}">
  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  {% for e in form.data.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

This is enough for `test_add_tabs_renders_the_editor_form` (it asserts `data-tabs-editor`) and for a blank add + save to persist the two default tabs, since `clean_data` supplies them when `data` is empty.

- [ ] **Step 4: Register the labels**

`courses/templatetags/courses_manage_extras.py` — add to `_ELEMENT_LABELS` after `"galleryelement"`:

```python
    "tabselement": _("Tabs"),
```

and add an `element_summary` branch next to the `GalleryElement` one:

```python
    if name == "TabsElement":
        n = len(TabsElement.normalize_labels_and_ids(el.data)["tabs"])
        # ngettext (not the lazy `_`) so the plural form is chosen against the
        # request's active locale at render time. Polish has three plural forms.
        return ngettext("%(n)d tab", "%(n)d tabs", n) % {"n": n}
```

Import `TabsElement` there. Use `normalize_labels_and_ids` (non-destructive), **not** `normalize_data` — the ledger should report what is stored, not a padded view.

`courses/views_manage.py` — add to `_EDITOR_TYPE_LABELS` (module-level dict, so `gettext_lazy`):

```python
    "tabs": gettext_lazy("Tabs"),
```

- [ ] **Step 5: Extend the two allow-tuples**

Add `"tabs",` to the `element_add` allow-tuple (~846) and the `element_save` allow-tuple (~878). These gate what may exist at **top level**; nesting is gated separately by `NESTABLE_TYPE_KEYS`.

Note for the blocked-type test: `slidebreak` is not in `element_add`'s allow-tuple at all, so a nested `slidebreak` 400s at the "bad type" check *before* `resolve_scope` ever runs. The test still passes, but it is not exercising the nesting gate for that type — the `choicequestion` and `tabs` cases are the ones that actually reach `resolve_scope`. Leave a comment saying so, rather than letting a future reader assume the coverage is real.

- [ ] **Step 6: Plumb `parent`/`tab` through `element_add`**

In `element_add`, after the unit lookup and before `_render_open_form`:

```python
    # Validate the scope now (render-only), so a blocked nested type 400s on the click
    # rather than at save. resolve_scope raises NestingError on any violation.
    try:
        parent_join, tab_id = builder_svc.resolve_scope(
            unit, request.POST.get("parent"), request.POST.get("tab"), type_key
        )
    except builder_svc.NestingError:
        return HttpResponseBadRequest("bad nesting")
    return _render_open_form(
        request,
        unit,
        type_key,
        element_pk="new",
        initial=initial,
        parent=str(parent_join.pk) if parent_join else "",
        tab=tab_id,
    )
```

Give `_render_open_form` two new keyword arguments defaulting to `""`, and pass them into the template context as `parent` and `tab`. `element_form` (the edit-an-existing flow) leaves both at `""` — the update path never reads them.

- [ ] **Step 7: Emit the hidden fields in `_host_form.html`**

`templates/courses/manage/editor/_host_form.html`, after the `unit_token` hidden input:

```html
  {% comment %}
  Scope for a NESTED create. element_add renders the blank form; element_save persists
  it in a second request, so parent/tab must round-trip here or the child lands at top
  level. Blank on the edit path -- save-on-update never reads them.
  {% endcomment %}
  <input type="hidden" name="parent" value="{{ parent }}">
  <input type="hidden" name="tab" value="{{ tab }}">
```

- [ ] **Step 8: Turn `NestingError` into a 400 in `element_save`**

Wrap the `builder_svc.save_element(...)` call:

```python
    except builder_svc.NestingError:
        return HttpResponseBadRequest("bad nesting")
```
placed alongside the existing `ConflictError` / `ElementFormInvalid` handlers (order does not matter; they are disjoint).

- [ ] **Step 9: Run the tests, watch them pass, then regenerate catalogs**

```
uv run pytest tests/test_tabs_registry.py -q
echo "EXIT=$?"
uv run python manage.py makemessages -l en -l pl --no-obsolete
```
Fill in the Polish strings for `Tabs`, `%(n)d tab` (3 plural forms), `A tabs element must keep at least %(n)d tabs.`, `A tabs element is limited to %(n)d tabs.`, `A tabs element needs a list of tabs.` Then:

```
uv run python manage.py compilemessages
uv run pytest tests/ -q -k "i18n or catalog"
echo "EXIT=$?"
```
The catalog tests fail on obsolete `#~` entries — that is why `--no-obsolete` is passed.

- [ ] **Step 10: Lint and commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/templatetags/ courses/views_manage.py templates/courses/manage/editor/ locale/ tests/test_tabs_registry.py
git commit -m "feat(tabs): manage-UI registry, nested add/save scope plumbing, EN/PL catalogs"
```

---

### Task 6: Student template, CSS, sprite, math scope

**Files:**
- Create: `templates/courses/elements/tabselement.html`
- Modify: `courses/static/courses/css/courses.css`, `templates/courses/manage/_icon_sprite.html`, `courses/static/courses/js/math.js`
- Test: `tests/test_tabs_partial.py`

**Interfaces:**
- Consumes: `TabsElement.render()` → context `{el, tabs, eid}` where `tabs` is `[(tab_dict, [child Element rows])]` (Task 1).
- Produces: the server-rendered DOM contract `tabs.js` enhances (Task 7): root `.el--tabs[data-tabs][data-tabs-eid]`, per-tab `.tabs__panel-label[data-tab-label]` heading + `.tabs__panel[data-tab-panel][data-tab-id]`.

**Server output is simultaneously the no-JS fallback and what print shows:** every panel visible, each preceded by its label as a heading. Every tab is emitted, **including empty ones** — a new tabs element is born with two empty tabs, and skipping them would erase them from the strip the enhancer builds.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tabs_partial.py`:

```python
import re
from pathlib import Path

import pytest

from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"
SPRITE = ROOT / "templates/courses/manage/_icon_sprite.html"
MATH_JS = ROOT / "courses/static/courses/js/math.js"


def test_empty_tabs_still_render_a_label_and_panel_each():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=unit, content_object=obj)
    html = obj.render()
    assert html.count("data-tab-panel") == 2
    assert html.count("data-tab-label") == 2


def test_child_renders_inside_its_panel():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][1]["id"]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>nested</p>"),
        parent=join,
        tab_id=tab,
    )
    html = obj.render()
    panel = html.split(f'data-tab-id="{tab}"')[1]
    assert "nested" in panel


def test_root_carries_the_join_row_pk_for_dom_id_namespacing():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    assert f'data-tabs-eid="{join.pk}"' in obj.render()


def test_courses_css_defines_the_tabs_element():
    css = CSS.read_text(encoding="utf-8")
    for cls in [
        ".el--tabs",
        ".tabs__strip",
        ".tabs__panel",
        ".tabs__panel-label",
        ".tabs__tab",
        ".tabs__scroller",
        ".tabs__chev",
    ]:
        assert cls in css, f"missing tabs class: {cls}"


def test_print_stylesheet_reveals_hidden_panels_and_labels():
    """Print happens AFTER enhancement, so both reveals need !important or the
    screen-hiding rules win and the printed lesson silently loses content."""
    css = CSS.read_text(encoding="utf-8")
    block = css.split("@media print")[1][:800]
    assert '[role="tabpanel"][hidden]' in block
    assert "display: block !important" in block
    assert ".tabs__panel-label" in block
    assert block.count("!important") >= 3


def test_sprite_defines_el_tabs_at_16x16():
    sprite = SPRITE.read_text(encoding="utf-8")
    m = re.search(r'<symbol id="el-tabs" viewBox="([^"]+)"', sprite)
    assert m, "sprite is missing an #el-tabs symbol"
    assert m.group(1) == "0 0 16 16"  # match every sibling el-* symbol
    symbol = sprite.split('id="el-tabs"')[1].split("</symbol>")[0]
    assert 'fill="currentColor"' in symbol  # fill, not stroke (the table slice got this wrong)


def test_math_js_scopes_inline_rendering_to_tabs():
    assert ".el--tabs" in MATH_JS.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_partial.py -q
echo "EXIT=$?"
```

- [ ] **Step 3: Create `templates/courses/elements/tabselement.html`**

```html
{% load courses_extras %}
{% comment %}
Student-facing tabs. `tabs` is [(tab, [child Element rows])] from
TabsElement.resolved_tabs(); EVERY tab is emitted, including empty ones, because a new
tabs element is born with two empty tabs and the enhancer builds one strip button per
label heading. This markup IS the no-JS fallback (all panels visible, each under its
heading) and is also exactly what @media print shows. tabs.js upgrades it in place to a
role=tablist and hides the inactive panels with the `hidden` ATTRIBUTE -- never an inline
display:none, which a print rule could not override. DOM ids are namespaced with the join
row pk (`eid`), because a tab id is unique only WITHIN one element and two tabs elements
on one page may legitimately share one.
{% endcomment %}
<div class="el el--tabs" data-tabs data-tabs-eid="{{ eid }}">
  {% for tab, children in tabs %}
    <section class="tabs__section">
      <h3 class="tabs__panel-label" data-tab-label id="tabs-{{ eid }}-{{ tab.id }}-label">{{ tab.label }}</h3>
      <div class="tabs__panel" data-tab-panel data-tab-id="{{ tab.id }}"
           id="tabs-{{ eid }}-{{ tab.id }}-panel">
        {% for child in children %}
          <div class="tabs__child">{% render_element child %}</div>
        {% endfor %}
      </div>
    </section>
  {% endfor %}
</div>
```

- [ ] **Step 4: Add the `#el-tabs` sprite symbol**

In `templates/courses/manage/_icon_sprite.html`, beside `#el-gallery`. 16×16, `fill="currentColor"`, matching every sibling (a strip of three tab shapes over a panel):

```html
  <symbol id="el-tabs" viewBox="0 0 16 16"><path fill="currentColor" d="M1 5.5A1.5 1.5 0 0 1 2.5 4h3A1.5 1.5 0 0 1 7 5.5V6h6.5A1.5 1.5 0 0 1 15 7.5v5A1.5 1.5 0 0 1 13.5 14h-11A1.5 1.5 0 0 1 1 12.5zm1.5-.5a.5.5 0 0 0-.5.5v7a.5.5 0 0 0 .5.5h11a.5.5 0 0 0 .5-.5v-5a.5.5 0 0 0-.5-.5H6V5.5a.5.5 0 0 0-.5-.5z"/><path fill="currentColor" d="M8.5 2h5A1.5 1.5 0 0 1 15 3.5V5h-1V3.5a.5.5 0 0 0-.5-.5h-5z"/></symbol>
```

- [ ] **Step 5: Add `.el--tabs` to the math scope**

`courses/static/courses/js/math.js`, in `renderInlineText`:

```js
    (root || document).querySelectorAll(".el--text, .el--table, .el--gallery, .el--tabs").forEach(function (el) {
```
KaTeX typesets hidden nodes happily, so every panel's math renders once at load — no reveal hook needed for math (unlike the gallery's measurement, Task 7).

- [ ] **Step 6: Style it in `courses/static/courses/css/courses.css`**

Append after the gallery block. Use the existing design tokens (`--border-strong`, `--surface-raised`, `--surface-sunken`, `--primary`, `--text-secondary`, `--space-*`, `--radius-md`) — do not introduce raw colours.

```css
/* ── Tabs (student) ────────────────────────────────────────────────────────
   tabs.js upgrades .el--tabs[data-tabs] into a role=tablist + hidden panels.
   Without JS every panel is visible under its own heading -- readable, and the
   exact markup @media print reveals. The strip scrolls horizontally; the fade
   and chevrons make it obvious that more tabs exist off-screen. */
.el--tabs { margin-block: var(--space-6); }

/* Screen: once enhanced, the per-panel headings are hidden by CLASS (never by an
   inline style) so the print rule below can override them. */
.el--tabs.tabs--js .tabs__panel-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.el--tabs .tabs__bar { display: flex; align-items: center; gap: var(--space-2); border-bottom: 1px solid var(--border-strong); }
.el--tabs .tabs__scroller { flex: 1; display: flex; gap: var(--space-1); overflow-x: auto; scrollbar-width: none; scroll-behavior: smooth; }
.el--tabs .tabs__scroller::-webkit-scrollbar { display: none; }
.el--tabs .tabs__strip { display: flex; gap: var(--space-1); }

.el--tabs .tabs__tab {
  flex: 0 0 auto; padding: var(--space-3) var(--space-4);
  border: 0; border-bottom: 2px solid transparent; background: none;
  color: var(--text-secondary); font: inherit; font-weight: 600; cursor: pointer;
  white-space: nowrap;
}
.el--tabs .tabs__tab:hover { color: var(--primary); }
.el--tabs .tabs__tab[aria-selected="true"] { color: var(--primary); border-bottom-color: var(--primary); }
.el--tabs .tabs__tab:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }

/* Overflow affordance: BOTH an edge fade and a chevron, so it is always obvious
   more tabs exist. Chevrons are decorative -- keyboard users have arrow keys. */
.el--tabs .tabs__bar { position: relative; }
.el--tabs .tabs__bar::before,
.el--tabs .tabs__bar::after { content: ""; position: absolute; top: 0; bottom: 1px; width: 2rem; pointer-events: none; opacity: 0; transition: opacity .2s ease; }
.el--tabs .tabs__bar::before { left: 0; background: linear-gradient(to right, var(--surface-raised), transparent); }
.el--tabs .tabs__bar::after { right: 0; background: linear-gradient(to left, var(--surface-raised), transparent); }
.el--tabs .tabs__bar.is-scroll-start::before { opacity: 1; }
.el--tabs .tabs__bar.is-scroll-end::after { opacity: 1; }

.el--tabs .tabs__chev {
  flex: 0 0 auto; display: none; align-items: center; justify-content: center;
  width: 1.9rem; height: 1.9rem; padding: 0;
  border: 1px solid var(--border-strong); border-radius: .4rem;
  background: var(--surface-raised); color: var(--text-secondary); cursor: pointer;
}
.el--tabs .tabs__bar.is-scroll-start .tabs__chev--prev,
.el--tabs .tabs__bar.is-scroll-end .tabs__chev--next { display: inline-flex; }
.el--tabs .tabs__chev .ic { width: 1rem; height: 1rem; }

.el--tabs .tabs__panel { padding-top: var(--space-5); }
.el--tabs .tabs__child + .tabs__child { margin-top: var(--space-5); }

/* No-JS / print: panels stack under visible headings. */
.el--tabs:not(.tabs--js) .tabs__section + .tabs__section { margin-top: var(--space-6); }

@media print {
  /* The enhancer hides inactive panels with the `hidden` ATTRIBUTE and the labels
     with a class; both reveals need !important or the screen rules win and the
     printed lesson silently loses every inactive panel and every tab title. */
  .el--tabs [role="tabpanel"][hidden] { display: block !important; }
  .el--tabs .tabs__panel-label { position: static !important; width: auto !important; height: auto !important; clip: auto !important; display: block !important; }
  .el--tabs .tabs__bar { display: none !important; }
}
```

- [ ] **Step 7: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_partial.py -q
echo "EXIT=$?"
```

- [ ] **Step 8: Lint and commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add templates/courses/elements/tabselement.html templates/courses/manage/_icon_sprite.html courses/static/courses/css/courses.css courses/static/courses/js/math.js tests/test_tabs_partial.py
git commit -m "feat(tabs): student template, tabs CSS incl. print rules, el-tabs sprite, math scope"
```

---

### Task 7: `tabs.js` enhancer + the `libli:reveal` handshake

**Files:**
- Create: `courses/static/courses/js/tabs.js`
- Modify: `courses/static/courses/js/gallery.js` (add the reveal listener), `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html`, `templates/courses/manage/editor/editor.html`, `courses/static/courses/js/editor.js` (`applyFragments` ~28)
- Test: `tests/test_tabs_css.py` (static-contract regressions)

**Interfaces:**
- Consumes: the DOM contract from Task 6.
- Produces: `window.libliInitTabs(root)` — idempotent, multi-instance, guarded by `dataset.tabsReady`.

**Three hazards this task exists to close:**
1. **Document-unique DOM ids.** A tab id is unique only within one element. Namespace with `data-tabs-eid` — otherwise two tabs elements on one page control each other's panels.
2. **A gallery inside a hidden panel measures zero height,** so its ResizeObserver stable-frame reservation computes a collapsed letterbox the student sees the moment they open that tab. `gallery.js` gains a `libli:reveal` listener. **This is new work in `gallery.js`, a file this slice otherwise never touches.**
3. **Every surface that renders the student template must load the script** — the lesson page, the quiz page, *and* `editor.js`'s `applyFragments()`. The gallery slice shipped this bug (PR #89): the editor preview, labelled "as students see it", never loaded `gallery.js` and so rendered the no-JS fallback, which read as broken.

- [ ] **Step 1: Write the failing static-contract tests**

Create `tests/test_tabs_css.py`:

```python
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABS_JS = ROOT / "courses/static/courses/js/tabs.js"
GALLERY_JS = ROOT / "courses/static/courses/js/gallery.js"
EDITOR_JS = ROOT / "courses/static/courses/js/editor.js"
CSS = ROOT / "courses/static/courses/css/courses.css"
TEMPLATES = ROOT / "templates/courses"


def test_tabs_js_is_multi_instance_and_idempotent():
    js = TABS_JS.read_text(encoding="utf-8")
    assert "querySelectorAll" in js          # no module singleton
    assert "tabsReady" in js                 # re-entry guard
    assert "isConnected" in js               # detached-container check


def test_tabs_js_namespaces_dom_ids_with_the_element_id():
    """A bare tab_id is unique only within one element; two tabs elements on one
    page may share one. Unnamespaced ids => duplicate DOM ids and cross-talk."""
    js = TABS_JS.read_text(encoding="utf-8")
    assert "tabsEid" in js or "data-tabs-eid" in js


def test_tabs_js_hides_panels_with_the_hidden_attribute_not_inline_display():
    js = TABS_JS.read_text(encoding="utf-8")
    assert "hidden" in js
    assert "style.display" not in js  # inline display:none would defeat @media print


def test_tabs_js_dispatches_the_reveal_event():
    assert "libli:reveal" in TABS_JS.read_text(encoding="utf-8")


def test_gallery_js_listens_for_reveal_and_remeasures():
    """Without this, a gallery in a non-default tab renders a collapsed frame the
    first time a student opens that tab -- and every other test still passes."""
    js = GALLERY_JS.read_text(encoding="utf-8")
    assert "libli:reveal" in js


def test_every_surface_that_renders_the_student_template_loads_tabs_js():
    for name in ["lesson_unit.html", "quiz_unit.html", "manage/editor/editor.html"]:
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        assert "courses/js/tabs.js" in html, f"{name} never loads tabs.js"


def test_editor_reinitialises_tabs_after_a_fragment_swap():
    js = EDITOR_JS.read_text(encoding="utf-8")
    assert "libliInitTabs" in js


def test_every_tabs_class_the_js_emits_is_styled():
    """table_editor.js once drifted from editor.css and shipped unstyled, permanently
    visible handles. Pin the contract for tabs.js too."""
    js = TABS_JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    emitted = set(re.findall(r'className = "([\w-]*tabs__[\w-]+)"', js))
    assert emitted, "expected tabs.js to assign tabs__* classes"
    for cls in sorted(emitted):
        first = cls.split()[0]
        assert f".{first}" in css, f"courses.css never styles .{first} (emitted by tabs.js)"
```

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_css.py -q
echo "EXIT=$?"
```
Expected: `FileNotFoundError` for `tabs.js`.

- [ ] **Step 3: Create `courses/static/courses/js/tabs.js`**

```js
(function () {
  "use strict";

  var i18n = window.TABS_I18N || { nav: "Tabs", prev: "Scroll tabs left", next: "Scroll tabs right" };

  function chevron(cls, pathD, label) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = cls;
    // Decorative: keyboard users move between tabs with the arrow keys, so the
    // chevrons are removed from the tab order and hidden from AT.
    b.setAttribute("aria-hidden", "true");
    b.tabIndex = -1;
    b.title = label;
    b.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ' +
      'focusable="false"><path d="' + pathD + '"/></svg>';
    return b;
  }

  function initOne(container) {
    // Idempotent: the editor preview pane is rebuilt on every fragment swap and re-runs
    // this over the whole pane. Re-entering would append a second tab bar.
    if (container.dataset.tabsReady === "1") return;

    var sections = Array.prototype.slice.call(container.querySelectorAll(".tabs__section"));
    if (!sections.length) return;
    container.dataset.tabsReady = "1";
    container.classList.add("tabs--js");

    // A tab id is unique only WITHIN one element. Namespace every DOM id with the join
    // row pk, or two tabs elements on one page produce duplicate ids and activating a
    // tab in one reveals a panel in the other.
    var eid = container.getAttribute("data-tabs-eid") || "0";

    var strip = document.createElement("div");
    strip.className = "tabs__strip";
    strip.setAttribute("role", "tablist");
    strip.setAttribute("aria-label", i18n.nav);

    var scroller = document.createElement("div");
    scroller.className = "tabs__scroller";
    scroller.appendChild(strip);

    var prev = chevron("tabs__chev tabs__chev--prev", "M15 6l-6 6 6 6", i18n.prev);
    var next = chevron("tabs__chev tabs__chev--next", "M9 6l6 6-6 6", i18n.next);

    var bar = document.createElement("div");
    bar.className = "tabs__bar";
    bar.appendChild(prev);
    bar.appendChild(scroller);
    bar.appendChild(next);
    container.insertBefore(bar, container.firstChild);

    var tabs = [];
    var panels = [];

    sections.forEach(function (section, k) {
      var label = section.querySelector("[data-tab-label]");
      var panel = section.querySelector("[data-tab-panel]");
      if (!label || !panel) return;
      var tid = panel.getAttribute("data-tab-id");
      var tabId = "tabs-" + eid + "-" + tid + "-tab";
      var panelId = "tabs-" + eid + "-" + tid + "-panel";

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tabs__tab";
      btn.id = tabId;
      btn.setAttribute("role", "tab");
      btn.setAttribute("aria-controls", panelId);
      btn.textContent = label.textContent;
      strip.appendChild(btn);

      panel.id = panelId;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tabId);
      panel.tabIndex = 0;

      // The label headings STAY in the DOM (hidden by class on screen). @media print
      // reveals them; detaching or reusing the nodes would silently lose every panel
      // title from the printed lesson while the bodies still appear.
      btn.addEventListener("click", function () { select(k); });
      tabs.push(btn);
      panels.push(panel);
    });

    if (!tabs.length) return;

    var active = -1;
    function select(n, focus) {
      var i = Math.max(0, Math.min(tabs.length - 1, n));
      if (i === active) return;
      active = i;
      tabs.forEach(function (t, k) {
        var on = k === i;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;  // roving tabindex
        // `hidden` ATTRIBUTE, never an inline display:none -- an inline style cannot be
        // overridden by the @media print rule that reveals every panel.
        if (on) { panels[k].removeAttribute("hidden"); } else { panels[k].setAttribute("hidden", ""); }
      });
      if (focus) tabs[i].focus();
      scrollIntoStrip(tabs[i]);
      // A gallery inside a hidden panel measured zero height; tell it to re-measure now
      // that it is visible. gallery.js listens for this.
      panels[i].dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
    }

    strip.addEventListener("keydown", function (e) {
      var delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
      if (delta) {
        e.preventDefault();
        // Automatic activation, per the ARIA authoring practices.
        select((active + delta + tabs.length) % tabs.length, true);
      } else if (e.key === "Home") {
        e.preventDefault(); select(0, true);
      } else if (e.key === "End") {
        e.preventDefault(); select(tabs.length - 1, true);
      }
    });

    function scrollIntoStrip(tab) {
      var l = tab.offsetLeft, r = l + tab.offsetWidth;
      if (l < scroller.scrollLeft) scroller.scrollLeft = l;
      else if (r > scroller.scrollLeft + scroller.clientWidth) scroller.scrollLeft = r - scroller.clientWidth;
    }

    // Overflow affordance: fade + chevron at whichever edge has more tabs.
    function updateOverflow() {
      if (!container.isConnected) {
        window.removeEventListener("resize", updateOverflow);
        return;
      }
      var max = scroller.scrollWidth - scroller.clientWidth;
      bar.classList.toggle("is-scroll-start", scroller.scrollLeft > 1);
      bar.classList.toggle("is-scroll-end", scroller.scrollLeft < max - 1);
    }
    scroller.addEventListener("scroll", updateOverflow);
    window.addEventListener("resize", updateOverflow);
    prev.addEventListener("click", function () { scroller.scrollLeft -= scroller.clientWidth * 0.7; });
    next.addEventListener("click", function () { scroller.scrollLeft += scroller.clientWidth * 0.7; });

    select(0);
    updateOverflow();
  }

  // Enhance every tabs element under `root`. Exposed so the editor can re-run it over
  // the live-preview pane after each fragment swap, like libliInitGallery. Idempotent.
  function initTabs(root) {
    var scope = root || document;
    if (scope.matches && scope.matches("[data-tabs]")) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-tabs]"), initOne);
  }

  window.libliInitTabs = initTabs;
  initTabs(document);
})();
```

- [ ] **Step 4: Teach `gallery.js` to re-measure on reveal**

In `initOne`, immediately after `window.addEventListener("resize", scheduleMeasure);`:

```js
    // A gallery inside a hidden tab panel measures zero height, so the stable-frame
    // reservation computes a collapsed letterbox the student sees the instant they open
    // that tab. tabs.js dispatches libli:reveal on the panel when it becomes visible.
    container.addEventListener("libli:reveal", scheduleMeasure);
    document.addEventListener("libli:reveal", function (e) {
      if (e.target.contains && e.target.contains(container)) scheduleMeasure();
    });
```
The event is dispatched on the *panel*, which is an ancestor of the gallery, so it bubbles past the gallery rather than through it — hence the document-level listener with a `contains` check. Keep both: the direct listener costs nothing and covers a future direct dispatch.

- [ ] **Step 5: Load the script on all three surfaces**

Add beside the existing `gallery.js` tag in each of `templates/courses/lesson_unit.html` (~32), `templates/courses/quiz_unit.html` (~28), `templates/courses/manage/editor/editor.html` (~94):

```html
  <script src="{% static 'courses/js/tabs.js' %}" defer></script>
```

- [ ] **Step 6: Re-init after each editor fragment swap**

In `courses/static/courses/js/editor.js`'s `applyFragments`, beside the `libliInitGallery` line:

```js
    if (preview && window.libliInitTabs) window.libliInitTabs(preview);  // re-enhance tabs
```
Order matters only in that `libliInitGallery(preview)` already runs over the whole pane, so a gallery nested in a panel is enhanced regardless of which tab is active; `tabs.js` then reveals tab 1 and fires `libli:reveal`, which re-measures it.

- [ ] **Step 7: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_css.py -q
echo "EXIT=$?"
```

- [ ] **Step 8: Lint and commit**

```
uv run ruff check tests && uv run ruff format --check tests
git add courses/static/courses/js/tabs.js courses/static/courses/js/gallery.js courses/static/courses/js/editor.js templates/courses/lesson_unit.html templates/courses/quiz_unit.html templates/courses/manage/editor/editor.html tests/test_tabs_css.py
git commit -m "feat(tabs): tabs.js enhancer, gallery libli:reveal re-measure, load on all 3 surfaces"
```

---

### Task 8: Editor — inline nested list, tabs edit form, nested add menu

**Files:**
- Create: `templates/courses/manage/editor/_edit_tabs.html`, `courses/static/courses/js/tabs_editor.js`
- Modify: `templates/courses/manage/editor/_element_row.html`, `.../_add_menu.html`, `.../editor.html` (sprite + script tag), `courses/static/courses/js/editor.js`, `courses/static/courses/css/editor.css`
- Test: `tests/test_tabs_editor_partial.py`

**Interfaces:**
- Consumes: `TabsElementForm.editor_rows` (Task 3); `resolved_tabs()` (Task 1); the `parent`/`tab` hidden fields (Task 5).
- Produces: `window.libliInitTabsEditor(root)`; `_add_menu.html` accepts `parent` + `tab` + `nested` params.

The tabs row expands in place to a tab strip, an indented `<ol class="element-list element-list--nested">` of child rows (a **recursive include of `_element_row.html` itself**), and a nested add menu carrying `data-parent`/`data-tab`. Because a child row is the same partial, clicking ✎ on a nested element expands the same inline `.el-edit-slot` host form it would at top level. No navigation, no new editing concept.

The recursive include terminates **only** because tabs-in-tabs is impossible (`NESTABLE_TYPE_KEYS` on every write path, plus import validation). The template carries no depth guard; the realized depth is always exactly 2.

The editor branch groups children with the **same `resolved_tabs()` helper** the student template uses — single-sourcing it keeps the two views from diverging over read-side normalization.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tabs_editor_partial.py`:

```python
import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
EDITOR_HTML = ROOT / "templates/courses/manage/editor/editor.html"
BASE_SPRITE = ROOT / "templates/courses/manage/_icon_sprite.html"
TABS_EDITOR_JS = ROOT / "courses/static/courses/js/tabs_editor.js"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"

# Symbols live in TWO files: `ed-*` (rich-text toolbar) in editor.html, `bi-*` (generic
# up/down/trash) in _icon_sprite.html. The tabs editor uses bi-* for reorder/delete, the
# same as _edit_gallery.html. Union both, or a valid bi-* ref reads as undefined.
def _sprite_symbols():
    text = EDITOR_HTML.read_text(encoding="utf-8") + BASE_SPRITE.read_text(encoding="utf-8")
    return set(re.findall(r'<symbol id="([\w-]+)"', text))


def _render_form(instance):
    form = FORM_FOR_TYPE["tabs"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_tabs.html", {"form": form, "type_key": "tabs"}
    )


def test_new_tabs_form_renders_two_label_rows():
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    assert "data-tabs-editor" in html
    assert html.count("data-tab-row") == 2


def test_each_row_round_trips_its_id_as_a_hidden_field():
    """Ids in, ids out. Without this the delete diff sees every old id as removed
    and destroys every child, and save() mints fresh ids for the survivors."""
    el = TabsElement(data={"tabs": [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]})
    html = _render_form(el)
    assert 'data-tab-id="taaaaaa"' in html
    assert 'data-tab-id="tbbbbbb"' in html


def test_element_row_renders_nested_children_indented():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="child body"),
        parent=join, tab_id=tab,
    )
    html = render_to_string(
        "courses/manage/editor/_element_row.html",
        {"el": join, "obj": obj, "unit": unit, "open_form_pk": ""},
    )
    assert "element-list--nested" in html
    assert "child body" in html                       # the child's own row
    assert f'data-parent="{join.pk}"' in html         # nested add menu carries scope
    assert f'data-tab="{tab}"' in html


def test_nested_add_menu_offers_only_nestable_types():
    course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    html = render_to_string(
        "courses/manage/editor/_add_menu.html",
        {"nested": True, "parent": join.pk, "tab": obj.data["tabs"][0]["id"]},
    )
    for blocked in ["choice-single", "slidebreak", 'data-add-type="tabs"']:
        assert blocked not in html
    assert 'data-add-type="text"' in html
    assert 'data-add-type="gallery"' in html


def test_tabs_editor_icons_resolve_to_sprite_symbols():
    """Icon-only buttons fail silently (blank) on a typo'd href, so pin every ref."""
    html = _render_form(TabsElement(data=TabsElement.default_data()))
    refs = set(re.findall(r'use href="#((?:ed|bi)-[\w-]+)"', html))
    assert refs, "expected the tabs editor to use sprite icons, not glyphs"
    assert refs <= _sprite_symbols(), f"undefined symbols: {refs - _sprite_symbols()}"


def test_tabs_editor_js_icon_refs_resolve_too():
    used = set(re.findall(r'"((?:ed|bi)-[\w-]+)"', TABS_EDITOR_JS.read_text(encoding="utf-8")))
    assert used <= _sprite_symbols(), f"undefined symbols: {used - _sprite_symbols()}"


def test_served_tabs_form_carries_the_bounds_the_js_reads(client):
    """tabs_editor.js reads data-min-tabs/data-max-tabs to disable add/remove at the
    bounds. Rendering the partial directly leaves them blank and every partial test
    still passes, so assert them on the SERVED form, where the wiring actually lives."""
    from django.urls import reverse

    from tests.factories import TEST_PASSWORD
    from tests.factories import make_teacher

    course, unit = make_course_with_unit()
    user = make_teacher(course)
    client.login(username=user.username, password=TEST_PASSWORD)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "tabs", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    html = resp.content.decode()
    assert 'data-min-tabs="2"' in html
    assert 'data-max-tabs="10"' in html
    assert 'maxlength="80"' in html


def test_editor_css_styles_every_class_tabs_editor_js_emits():
    js = TABS_EDITOR_JS.read_text(encoding="utf-8")
    css = EDITOR_CSS.read_text(encoding="utf-8")
    emitted = set(re.findall(r'className = "(tabs-editor__[\w-]+)"', js))
    for cls in sorted(emitted):
        assert f".{cls}" in css, f"editor.css never styles .{cls} (emitted by tabs_editor.js)"
```

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_editor_partial.py -q
echo "EXIT=$?"
```

- [ ] **Step 3: Replace the `_edit_tabs.html` stub with the real editor**

Task 5 created a minimal `_edit_tabs.html` (hidden `data` field only) so its own add-form test could render. **Overwrite** it here.

Model it on `_edit_gallery.html`: a hidden `name="data"` field is the sole authoritative input, mirrored from the visible rows by `tabs_editor.js`. The delete button is disabled at `MIN_TABS`; the add button is disabled at `MAX_TABS`.

```html
{% load i18n %}
{% comment %}
Tabs editor: labels only. The hidden name="data" field is the SOLE authoritative
input; tabs_editor.js mirrors the rows into it as {"tabs":[{id,label}]}. Each existing
row carries its id in data-tab-id so the id ROUND-TRIPS on save -- without that, the
server's removed-tab diff would treat every old id as deleted and destroy every child,
and save() would mint fresh ids for the survivors. A brand-new row has an empty
data-tab-id; the server mints its id.
{% endcomment %}
<div class="el-editor el-editor--tabs" data-tabs-editor
     data-min-tabs="{{ min_tabs }}" data-max-tabs="{{ max_tabs }}"
     data-msg-remove="{% trans 'Remove tab' %}"
     data-msg-confirm="{% trans 'Deleting this tab also deletes everything inside it.' %}">
  <input type="hidden" name="data" value="{{ form.data.data|default:'' }}">

  <ol class="tabs-editor__rows" data-tab-rows>
    {% for row in form.editor_rows %}
    <li class="tabs-editor__row" data-tab-row data-tab-id="{{ row.id }}">
      <input type="text" class="tabs-editor__label" data-tab-label-input
             value="{{ row.label }}" maxlength="{{ label_max }}"
             aria-label="{% trans 'Tab label' %}">
      <span class="tabs-editor__ctl">
        <button type="button" class="iconbtn" data-tab-up title="{% trans 'Move up' %}" aria-label="{% trans 'Move up' %}"><svg class="ic"><use href="#bi-up"/></svg></button>
        <button type="button" class="iconbtn" data-tab-down title="{% trans 'Move down' %}" aria-label="{% trans 'Move down' %}"><svg class="ic"><use href="#bi-down"/></svg></button>
        <button type="button" class="iconbtn iconbtn--danger" data-tab-remove title="{% trans 'Remove tab' %}" aria-label="{% trans 'Remove tab' %}"><svg class="ic"><use href="#bi-trash"/></svg></button>
      </span>
    </li>
    {% endfor %}
  </ol>

  <button type="button" class="btn btn--small" data-tab-add>{% trans "Add tab" %}</button>

  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  {% for e in form.data.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

Pass `min_tabs`, `max_tabs` and `label_max` into the host-form context from `_render_open_form` (or expose them as `TabsElement.MIN_TABS` etc. via a small template tag — pick whichever matches the codebase; do not hardcode `2`/`10`/`80` in the template).

- [ ] **Step 4: Create `courses/static/courses/js/tabs_editor.js`**

Mirror `gallery_editor.js`'s shape. Requirements:
- Serialize `[{id, label}]` from the rows into the hidden `data` field on every input/reorder/remove/add, and once on init.
- A new row gets `data-tab-id=""` (server mints the id).
- Disable `[data-tab-remove]` on every row when the row count is at `MIN_TABS`; disable `[data-tab-add]` at `MAX_TABS`.
- `data-tab-remove` confirms first, using the `data-msg-confirm` string (JS-built controls cannot call `{% trans %}`; labels ride on `data-msg-*` attributes, read via a `label(root, key, fallback)` helper, following `table_editor.js`).
- Expose an idempotent `window.libliInitTabsEditor(root)` guarded by `dataset.tabsEditorReady`.

- [ ] **Step 5: Recursive nested rows in `_element_row.html`**

Add a `tabselement` branch **before** the existing `{% else %}`, keeping the slidebreak branch first:

```html
{% elif el.content_type.model == "tabselement" %}
<li class="el-row el-row--tabs{% if open_form_pk == el.pk|stringformat:'s' %} el-row--editing{% endif %}"
    data-element="{{ el.pk }}" data-updated="{{ unit.updated.isoformat }}" data-unit="{{ unit.pk }}">
  <div class="el-row__head">
    <button type="button" class="iconbtn ica--grip" draggable="true"
            aria-label="{% trans 'Drag to reorder' %}" title="{% trans 'Drag to reorder' %}">⠿</button>
    <div class="el-row__body">
      <div class="el-row__top">
        <span class="el-tag">{% element_type_label el.content_type obj %}</span>
        <span class="el-actions">
          <button type="button" class="iconbtn el-select el-act-edit" data-element-id="{{ el.pk }}"
                  data-form-url="{% url 'courses:manage_element_form' slug=unit.course.slug pk=el.pk %}"
                  aria-label="{% trans 'Edit' %}" title="{% trans 'Edit' %}">✎</button>
          <button type="button" class="iconbtn el-act-cancel" data-cancel-edit
                  aria-label="{% trans 'Cancel' %}" title="{% trans 'Cancel' %}">✕</button>
          {% include "courses/manage/editor/_element_row_controls.html" with el=el unit=unit %}
        </span>
      </div>
      <button type="button" class="el-select el-row__label" data-element-id="{{ el.pk }}"
              data-form-url="{% url 'courses:manage_element_form' slug=unit.course.slug pk=el.pk %}">{% if el.title %}{{ el.title }}{% else %}{{ obj|element_summary }}{% endif %}</button>
    </div>
  </div>
  <div class="el-edit-slot" data-edit-slot>{% if open_form_pk == el.pk|stringformat:'s' %}{{ open_form|safe }}{% endif %}</div>

  {% comment %}
  Nested children, grouped by the SAME resolved_tabs() helper the student template uses.
  This include is recursive -- a child row is this very partial. It terminates only
  because tabs-in-tabs is impossible (NESTABLE_TYPE_KEYS + import validation), so the
  realized depth is always exactly 2. There is no depth guard here.
  {% endcomment %}
  <div class="el-row__tabs">
    {% for tab, children in obj.resolved_tabs %}
      <details class="tabs-rows" {% if forloop.first %}open{% endif %}>
        <summary class="tabs-rows__summary">{{ tab.label }} <span class="tabs-rows__count">{{ children|length }}</span></summary>
        <ol class="element-list element-list--nested">
          {% for child in children %}
            {% include "courses/manage/editor/_element_row.html" with el=child obj=child.content_object unit=unit open_form=open_form open_form_pk=open_form_pk %}
          {% empty %}
            <li class="empty-state">{% trans "This tab is empty." %}</li>
          {% endfor %}
        </ol>
        {% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=tab.id %}
      </details>
    {% endfor %}
  </div>
</li>
```

- [ ] **Step 6: Make `_add_menu.html` scope-aware**

Wrap the root element's attributes and gate the non-nestable groups:

```html
<div class="addwrap{% if nested %} addwrap--nested{% endif %}" data-add-menu
     {% if nested %}data-parent="{{ parent }}" data-tab="{{ tab }}"{% endif %}>
```
and wrap the **Questions** and **Structure** groups plus the `data-add-type="tabs"` card in `{% if not nested %} ... {% endif %}`. The server still enforces `NESTABLE_TYPE_KEYS`; hiding the cards is courtesy, not enforcement.

Add the new top-level card in the Content group beside Gallery:

```html
      <button type="button" class="typecard" data-add-type="tabs"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-tabs"/></svg>{% trans "Tabs" %}</button>
```

- [ ] **Step 7: Send scope from the add click in `editor.js`**

In the `[data-add-type]` handler, read the nearest menu's scope and append it:

```js
      var menu = add.closest("[data-add-menu]");
      var fd = new FormData();
      fd.append("type", addType);
      fd.append("unit", pane.getAttribute("data-unit"));
      // A nested add menu carries the scope. element_add echoes it back as hidden fields
      // in the host form, so it survives the second hop to element_save.
      if (menu && menu.getAttribute("data-parent")) {
        fd.append("parent", menu.getAttribute("data-parent"));
        fd.append("tab", menu.getAttribute("data-tab"));
      }
      postFragment(pane.getAttribute("data-add-url"), fd, function () { ... });
```
Guard the slidebreak fast-path so it can never fire from a nested menu (the card is hidden there, but be explicit): `if (addType === "slidebreak" && !(menu && menu.getAttribute("data-parent")))`.

Register the editor widget in `applyFragments`, beside `libliInitGalleryEditor`:

```js
    if (editorPane && window.libliInitTabsEditor) window.libliInitTabsEditor(editorPane);
```
and add `<script src="{% static 'courses/js/tabs_editor.js' %}" defer></script>` to `editor.html`.

- [ ] **Step 8: Style the editor bits in `editor.css`**

Style `.el-row--tabs`, `.el-row__tabs`, `.tabs-rows`, `.tabs-rows__summary`, `.tabs-rows__count`, `.element-list--nested` (indent + a left rule), `.tabs-editor__rows`, `.tabs-editor__row`, `.tabs-editor__label`, `.tabs-editor__ctl`, `.addwrap--nested`, and every `tabs-editor__*` class `tabs_editor.js` emits. The regression test in Step 1 fails if any emitted class is unstyled — that drift is what left the table slice's handles permanently visible.

- [ ] **Step 9: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_editor_partial.py tests/test_tabs_registry.py -q
echo "EXIT=$?"
```

- [ ] **Step 10: Regenerate catalogs, lint, commit**

```
uv run python manage.py makemessages -l en -l pl --no-obsolete && uv run python manage.py compilemessages
uv run ruff check courses tests && uv run ruff format --check courses tests
git add templates/courses/manage/editor/ courses/static/courses/js/ courses/static/courses/css/editor.css locale/ tests/test_tabs_editor_partial.py
git commit -m "feat(tabs): inline nested element list, tabs edit form, scope-aware add menu"
```

---

### Task 9: Transfer — export

**Files:**
- Modify: `courses/transfer/schema.py` (`FORMAT_VERSION` ~14), `courses/transfer/export.py` (`SERIALIZERS` ~199, `build_export` element walk ~298)
- Test: `tests/test_tabs_transfer.py` (export half)

**Interfaces:**
- Consumes: `TabsElement.resolved_tabs()` (Task 1).
- Produces: `FORMAT_VERSION = 3`; every element payload gains `parent` (an internal `e#` ref or `None`) and `tab` (a tab id or `""`); `export._ser_tabs`; `export.walk_unit_joins(unit_pk, joins_by_unit)`.

**The walk enumerates each element exactly once.** Query only top-level joins (`parent__isnull=True`), then expand each tabs element's children inline via `resolved_tabs()`. This gives parents-before-children *and* preserves within-tab order — and because every element is visited once, `_element_mids` needs **no** recursion and a nested gallery's media are counted exactly once by construction. (The spec describes a top-level media walk that recurses; this is the same invariant reached more simply. Keep the exactly-once test.)

- [ ] **Step 1: Write the failing export tests**

Create `tests/test_tabs_transfer.py` (import half added in Task 10):

```python
import pytest

from courses.models import Element
from courses.models import GalleryElement
from courses.models import MediaAsset
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.export import build_export
from courses.transfer.schema import FORMAT_VERSION
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _nested_course():
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    a = MediaAsset.objects.create(course=course, kind="image", file="a.png")
    b = MediaAsset.objects.create(course=course, kind="image", file="b.png")
    gal = GalleryElement.objects.create(
        data={"desc_pos": "below", "images": [{"media": a.pk, "desc": ""}, {"media": b.pk, "desc": ""}]}
    )
    first = Element.objects.create(unit=unit, content_object=TextElement.objects.create(body="one"), parent=join, tab_id=t2)
    second = Element.objects.create(unit=unit, content_object=gal, parent=join, tab_id=t2)
    return course, unit, join, t1, t2, first, second


def test_format_version_is_3():
    assert FORMAT_VERSION == 3


def test_export_emits_parent_before_child_with_parent_and_tab_refs(tmp_path):
    course, unit, join, t1, t2, first, second = _nested_course()
    doc = build_export(course)["document"]  # adapt to build_export's real return shape
    els = doc["elements"]
    ids = [e["id"] for e in els]
    parent_el = next(e for e in els if e["type"] == "tabs")
    kids = [e for e in els if e.get("parent")]
    assert len(kids) == 2
    assert all(k["parent"] == parent_el["id"] for k in kids)
    assert all(k["tab"] == t2 for k in kids)
    # parents precede children
    assert ids.index(parent_el["id"]) < min(ids.index(k["id"]) for k in kids)
    # top-level element carries explicit nulls, not a missing key
    assert parent_el["parent"] is None and parent_el["tab"] == ""


def test_within_tab_child_order_is_preserved(tmp_path):
    course, unit, join, t1, t2, first, second = _nested_course()
    doc = build_export(course)["document"]
    kids = [e for e in doc["elements"] if e.get("parent")]
    assert kids[0]["type"] == "text" and kids[1]["type"] == "gallery"


def test_nested_gallery_media_appear_exactly_once(tmp_path):
    """'The media survive' stays green under a double-count -- the duplicate manifest
    entry re-imports the same file and the gallery still references one asset. Count."""
    course, unit, join, t1, t2, first, second = _nested_course()
    export = build_export(course)
    mids = [m["id"] for m in export["document"]["media"]]
    assert len(mids) == len(set(mids)) == 2


def test_empty_tabs_element_exports_its_labels():
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=unit, content_object=tabs)
    doc = build_export(course)["document"]
    payload = next(e for e in doc["elements"] if e["type"] == "tabs")
    assert len(payload["data"]["tabs"]) == 2
```

Read `build_export`'s real return shape before finalising these assertions — adapt the accessors, not the assertions' intent.

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_transfer.py -q
echo "EXIT=$?"
```

- [ ] **Step 3: Bump the format version**

`courses/transfer/schema.py`: `FORMAT_VERSION = 3`.

- [ ] **Step 4: Add the serializer**

`courses/transfer/export.py`:

```python
def _ser_tabs(el, ids):
    # Labels + stable ids only. The children are separate elements carrying `parent`
    # and `tab` refs; a tabs element itself references no media.
    return {"tabs": [dict(t) for t in el.normalize_labels_and_ids(el.data)["tabs"]]}
```
Register `"tabs": (TabsElement, _ser_tabs),` in `SERIALIZERS` (which also feeds `_MODEL_TO_KEY`). The editor/UI key and the transfer key are both `tabs` — keep them consistent.

`_element_mids` needs **no change**: `"tabs"` data has no `media` key, so it returns `[]`, and every nested element is visited once by the walk below.

- [ ] **Step 5: Rewrite the element walk in `build_export`**

Restrict the join query to top level, and expand children inline:

```python
        joins_by_unit = {}
        for join in (
            Element.objects.filter(unit_id__in=unit_pks, parent__isnull=True)
            .order_by("unit_id", "order", "pk")
            .prefetch_related("content_object")
        ):
            joins_by_unit.setdefault(join.unit_id, []).append(join)


def walk_unit_joins(unit_pk, joins_by_unit):
    """Yield (join, parent_join_or_None, tab_id) for one unit, parents before children,
    each element EXACTLY ONCE. Children come from resolved_tabs(), so they arrive in
    their within-tab `order` -- which is what makes the import's payload-order pass 1
    reproduce that order without serializing `order` itself."""
    for join in joins_by_unit.get(unit_pk, []):
        yield join, None, ""
        obj = join.content_object
        if isinstance(obj, TabsElement):
            for tab, children in obj.resolved_tabs():
                for child in children:
                    yield child, join, tab["id"]
```

In the Pass-2 loop, iterate `walk_unit_joins(n.pk, joins_by_unit)` instead of `joins_by_unit.get(n.pk, [])`.

`walk_unit_joins` yields the parent **join object**, not its `walk_index`, so build the mapping as you go. Parents always precede their children in the walk, so the lookup is always populated by the time a child needs it:

```python
        walk_index_by_join_pk = {}
        for n in nodes:
            for join, parent_join, tab_id in walk_unit_joins(n.pk, joins_by_unit):
                walk_index += 1
                walk_index_by_join_pk[join.pk] = walk_index
                parent_walk_index = (
                    walk_index_by_join_pk[parent_join.pk] if parent_join else None
                )
                if join.content_object is None:  # dangling GFK: concrete row gone
                    broken.append((walk_index, n.title))
                    continue
                ...
```

Note the `walk_index += 1` must stay **before** the broken-join `continue`, exactly as today, so every join (including skipped ones) shares one ordering space.

Then record each element's `parent` as that `parent_walk_index` in the `pending` tuple. After the loop, when `pending` entries are turned into `e1..eN` ids, translate `walk_index → e#`:

```python
                pending.append(
                    (
                        walk_index,
                        {
                            "unit": node_ids[n.pk],
                            "title": join.title,
                            "type": type_key,
                            "data": data,
                            "parent": parent_walk_index,  # int or None; resolved below
                            "tab": tab_id,
                        },
                        mids,
                    )
                )
```
Then, where the code assigns element ids, build `eid_by_walk = {walk_index: eid}` as it goes and, in a second pass over the emitted dicts, replace `d["parent"]` with `eid_by_walk[d["parent"]]` (or `None`). Because parents always precede children in the walk, the parent's `walk_index` is always already in the map. **Read `build_export` fully before editing** — the id-assignment site is below the excerpt above.

Skipped broken joins (dangling GFK) already `continue` before `pending.append`. If a *tabs* element is broken, its children are never yielded (they hang off `resolved_tabs()` on a `None` content_object), so no child can reference a missing parent.

**Orphaned children are deliberately not exported.** Routing children through `resolved_tabs()` means a child whose `tab_id` matches no tab — reachable only via a direct DB edit or a read-side truncation — is omitted from the archive. This is intentional, and it is the right call: exporting one would produce a payload whose `tab` ref fails the import validator in Task 10, so the archive could never be re-imported. It does mean export is not a byte-faithful COLLECT snapshot in that one damaged case. The delete helpers, which sweep orphans, are unaffected. Say this in a code comment on `walk_unit_joins` so nobody "fixes" it later by iterating `join.children.all()` directly.

- [ ] **Step 6: Run the export tests, watch them pass**

```
uv run pytest tests/test_tabs_transfer.py -q
echo "EXIT=$?"
```

- [ ] **Step 7: Run the whole transfer suite — the payload shape changed for every element**

```
uv run pytest tests/ -q -k transfer
echo "EXIT=$?"
```
Existing tests that assert exact element-payload keys will need `parent`/`tab` added. That is expected; update them.

- [ ] **Step 8: Lint and commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/transfer/schema.py courses/transfer/export.py tests/
git commit -m "feat(tabs): export nesting (FORMAT_VERSION 3, parent/tab refs, exactly-once media)"
```

---

### Task 10: Transfer — validation + two-pass import

**Files:**
- Modify: `courses/transfer/payloads.py` (`VALIDATORS` ~404, `validate_element_data` ~425), `courses/transfer/schema.py` (`validate_document` element loop), `courses/transfer/importer.py` (`BUILDERS` ~614, `_create_elements` ~683)
- Test: `tests/test_tabs_transfer.py` (import half)

**Interfaces:**
- Consumes: Task 9's payload shape.
- Produces: `payloads._val_tabs`, `payloads.validate_nesting(elements)`, `importer._build_tabs`; `_create_elements` becomes two-pass.

**Import rejects, rather than repairs:** an out-of-bounds tab count, a duplicate tab id, a malformed tab id, an unknown `parent` ref, a `parent` that is not a tabs element, a `tab` absent from that parent, a non-nestable child type, and a `parent` chain deeper than one level. Rejecting the count is what keeps `normalize_data`'s destructive padding/truncation from ever firing on imported data — so the question of validating a `tab` ref before or after truncation never arises. Rejecting duplicates is what makes `save()`'s "never rewrites an existing **unique** id" guarantee hold on the import path.

**Import preserves tab ids verbatim.** `_build_tabs` passes `data["tabs"]` straight through; `save()` runs only `normalize_labels_and_ids`, which never rewrites a present, unique, well-formed id.

**Two-pass, for reference resolution.** Pass 1 creates every concrete + join row with `parent = None`, **in payload order**. Pass 2 resolves the `parent` refs. Pass 1's payload order is what makes `OrderField`'s unit-wide `max+1` hand out strictly increasing `order` values in archive sequence, so within-tab child order survives without serializing `order`. Pass 2 must never touch `order`.

- [ ] **Step 1: Write the failing import tests** (append to `tests/test_tabs_transfer.py`)

```python
import pytest

from courses.transfer.payloads import validate_nesting
from courses.transfer.schema import TransferError  # TransferError lives in schema.py


def _els(*items):
    return list(items)


def _tabs_el(eid="e1", tabs=None):
    tabs = tabs or [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]
    return {"id": eid, "type": "tabs", "data": {"tabs": tabs}, "parent": None, "tab": ""}


def _child(eid="e2", parent="e1", tab="taaaaaa", type_="text"):
    return {"id": eid, "type": type_, "data": {}, "parent": parent, "tab": tab}


def test_nesting_validation_accepts_a_wellformed_document():
    validate_nesting(_els(_tabs_el(), _child()))  # must not raise


@pytest.mark.parametrize(
    "elements",
    [
        _els(_tabs_el(), _child(parent="e9")),                       # unknown parent
        _els(_tabs_el(), _child(tab="tzzzzzz")),                     # tab not in parent
        _els(_tabs_el(), _child(type_="choice")),                    # non-nestable child
        _els(_tabs_el(), _child(type_="tabs")),                      # tabs in tabs
        _els(_tabs_el(), _child(), _child("e3", parent="e2")),       # depth > 1
        _els({"id": "e1", "type": "text", "data": {}, "parent": None, "tab": ""},
             _child(parent="e1")),                                   # parent not tabs
    ],
)
def test_nesting_validation_rejects(elements):
    with pytest.raises(TransferError):
        validate_nesting(elements)


@pytest.mark.parametrize(
    "tabs",
    [
        [{"id": "taaaaaa", "label": "only"}],                                    # < MIN
        [{"id": f"t{i:06x}", "label": "x"} for i in range(11)],                  # > MAX
        [{"id": "taaaaaa", "label": "A"}, {"id": "taaaaaa", "label": "B"}],      # duplicate
        [{"id": "NOPE", "label": "A"}, {"id": "tbbbbbb", "label": "B"}],         # bad format
        [{"id": "t" + "a" * 20, "label": "A"}, {"id": "tbbbbbb", "label": "B"}], # too long
    ],
)
def test_tabs_validator_rejects_bad_tab_lists(tabs):
    from courses.transfer.payloads import validate_element_data

    with pytest.raises(TransferError):
        validate_element_data(_tabs_el(tabs=tabs), {})


def test_round_trip_preserves_nesting_media_and_child_order(tmp_path):
    """The spec's headline transfer test: a gallery nested in tab 2, with a sibling
    ahead of it, survives export -> import with nesting, media AND order intact."""
    course, unit, join, t1, t2, first, second = _nested_course()
    # Export to a zip, import into a fresh course, then assert. Follow the exact
    # round-trip harness used by tests/test_gallery_transfer.py -- do not invent one.
    ...
    imported_tabs = TabsElement.objects.exclude(pk=join.content_object.pk).get()
    imported_join = imported_tabs.join_row()
    kids = list(imported_join.children.order_by("order", "pk"))
    assert [type(k.content_object).__name__ for k in kids] == ["TextElement", "GalleryElement"]
    assert {k.tab_id for k in kids} == {imported_tabs.data["tabs"][1]["id"]}
    assert imported_tabs.data["tabs"][1]["id"] == t2  # tab ids preserved VERBATIM


def test_v2_archive_still_imports_with_everything_top_level():
    """No `parent` key at all -> setdefault shim -> all elements top-level."""
    ...
```

Fill the two `...` bodies from `tests/test_gallery_transfer.py`'s round-trip harness and the existing v1→v2 shim test. Do not invent a new harness.

- [ ] **Step 2: Run them, watch them fail**

```
uv run pytest tests/test_tabs_transfer.py -q
echo "EXIT=$?"
```

- [ ] **Step 3: Add `_val_tabs` and register it**

`courses/transfer/payloads.py`:

```python
def _val_tabs(data, elid, media_kinds):
    from courses.models import TabsElement

    _exact_keys(data, ["tabs"], _("tabs data"))
    tabs = data["tabs"]
    if not isinstance(tabs, list):
        _err(_("Element '%(el)s' has malformed tabs."), el=elid)
    if not (TabsElement.MIN_TABS <= len(tabs) <= TabsElement.MAX_TABS):
        # REJECT rather than repair: this is what keeps normalize_data's destructive
        # padding/truncation from ever firing on imported data, so a child's `tab` ref
        # can never be validated against a different tab list than the one imported.
        _err(_("Element '%(el)s' has an invalid number of tabs."), el=elid)
    seen = set()
    for tab in tabs:
        if not isinstance(tab, dict):
            _err(_("Element '%(el)s' has a malformed tab."), el=elid)
        _exact_keys(tab, ["id", "label"], _("tab"))
        tid = tab["id"]
        if not isinstance(tid, str) or not TabsElement.TAB_ID_RE.fullmatch(tid):
            _err(_("Element '%(el)s' has a malformed tab id."), el=elid)
        if len(tid) > 12:  # must fit Element.tab_id
            _err(_("Element '%(el)s' has an over-long tab id."), el=elid)
        if tid in seen:
            # Duplicates would be regenerated by save()'s normalizer, orphaning the
            # child that referenced the later one. Reject instead.
            _err(_("Element '%(el)s' has duplicate tab ids."), el=elid)
        seen.add(tid)
        check_str(tab["label"], "label", max_length=TabsElement.LABEL_MAX)
    return set()  # a tabs element references no media
```
Register `"tabs": _val_tabs,` in `VALIDATORS`.

- [ ] **Step 4a: Teach the element-level `_exact_keys` check about `parent`/`tab` — do this FIRST**

`courses/transfer/schema.py`'s `validate_document` element loop (~283) runs:

```python
        _exact_keys(el, ["id", "unit", "title", "type", "data"], _("element"))
```

`_exact_keys` raises on **any** unknown key *and* requires **every** listed key to be present. So:
- leaving it alone rejects every element of every **v3** archive (they now carry `parent`/`tab`), and
- merely adding the two keys to the list rejects every **v2** archive (they carry neither).

It has no notion of an optional key. Apply the v2 shim **before** the check, then widen the list:

```python
        # v2 archives carry neither key; v3 carries both. setdefault first so a legacy
        # archive gains them and passes the exact-keys check, and so downstream code
        # never KeyErrors. Same shape as the v1->v2 iframe width/height shim.
        el.setdefault("parent", None)
        el.setdefault("tab", "")
        _exact_keys(el, ["id", "unit", "title", "type", "data", "parent", "tab"], _("element"))
```

Without this step **every transfer test in the repo fails**, not just the new ones. Add a test:

```python
def test_v2_element_without_parent_or_tab_passes_exact_keys():
    el = {"id": "e1", "unit": "n1", "title": "", "type": "text", "data": {"body": ""}}
    validate_document({"elements": [el], ...})  # adapt to the real signature
    assert el["parent"] is None and el["tab"] == ""
```

- [ ] **Step 4b: Add the cross-element nesting validator**

Also in `payloads.py`:

```python
def validate_nesting(elements):
    """Cross-element checks the per-element validators cannot see. Rejects (never
    repairs) an unknown/ill-typed parent, an unknown tab, a non-nestable child, and a
    parent chain deeper than one level -- that depth bound is what lets the editor's
    recursive row template terminate without a guard."""
    from courses.builder import NESTABLE_TYPE_KEYS

    # Step 4a already applied the v2 shim before _exact_keys, so both keys are present.
    by_id = {el["id"]: el for el in elements}
    for el in elements:
        parent_ref = el["parent"]
        if parent_ref is None:
            continue
        parent = by_id.get(parent_ref)
        if parent is None:
            _err(_("Element '%(el)s' references an unknown parent."), el=el["id"])
        if parent["type"] != "tabs":
            _err(_("Element '%(el)s' has a parent that is not a tabs element."), el=el["id"])
        if parent["parent"] is not None:
            _err(_("Element '%(el)s' is nested more than one level deep."), el=el["id"])
        if el["tab"] not in {t["id"] for t in parent["data"]["tabs"]}:
            _err(_("Element '%(el)s' references a tab its parent does not have."), el=el["id"])
        if el["type"] not in NESTABLE_TYPE_KEYS:
            _err(_("Element '%(el)s' may not be nested inside a tabs element."), el=el["id"])
```

Note `NESTABLE_TYPE_KEYS` holds **editor** keys (`text`, `gallery`, …), which for every nestable type happen to equal the transfer keys. Assert that in a test rather than assuming it silently:

```python
def test_nestable_keys_agree_across_the_two_namespaces():
    from courses.builder import NESTABLE_TYPE_KEYS
    from courses.transfer.export import SERIALIZERS

    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)
```

Call `validate_nesting(document["elements"])` from `schema.validate_document`, **after** the per-element `validate_element_data` loop (it depends on each tabs element's `data["tabs"]` already being shape-checked).

Import it **locally, inside `validate_document`** — never at module level. `payloads.py` already does a module-level `from courses.transfer.schema import check_str`, so a module-level import the other way is circular and fails at import time. The existing code sidesteps this exactly the same way (`schema.py` imports `validate_element_data` locally inside `validate_document`); follow that pattern:

```python
    from courses.transfer.payloads import validate_nesting  # local: avoids a circular import
    validate_nesting(document["elements"])
```

- [ ] **Step 5: Add the builder and make `_create_elements` two-pass**

`courses/transfer/importer.py`:

```python
def _build_tabs(data, assets):
    # Tab ids pass through VERBATIM. save() runs only normalize_labels_and_ids, which
    # never rewrites a present, unique, well-formed id -- and the validator has already
    # guaranteed all three. Regenerating here would orphan every child.
    return _clean_save(TabsElement(data={"tabs": data["tabs"]})), ()
```
Register `"tabs": _build_tabs,` in `BUILDERS`.

```python
def _create_elements(document, node_map, assets):
    """Two-pass, for reference resolution. Pass 1 creates every join row with
    parent=None, IN PAYLOAD ORDER -- OrderField's unit-wide max+1 therefore hands out
    strictly increasing `order` values in archive sequence, which is what preserves
    within-tab child order without ever serializing `order`. Pass 2 links children and
    must NOT touch `order`. Two passes also make the import robust to a hand-edited
    archive in which a child precedes its parent."""
    joins = {}
    for el in document["elements"]:
        try:
            concrete, child_rows = BUILDERS[el["type"]](el["data"], assets)
            for row in child_rows:
                row.full_clean(exclude=["order"])
                row.save()
            join = Element(
                unit=node_map[el["unit"]], title=el["title"], content_object=concrete
            )
            join.full_clean(exclude=["order"])
            join.save()
            joins[el["id"]] = join
        except ValidationError as exc:
            raise TransferError(
                _("Element %(id)s (%(type)s) failed validation on import: %(detail)s")
                % {"id": el["id"], "type": el["type"], "detail": _validation_detail(exc)}
            ) from exc

    for el in document["elements"]:
        parent_ref = el.get("parent")
        if not parent_ref:
            continue
        join = joins[el["id"]]
        join.parent = joins[parent_ref]
        join.tab_id = el.get("tab") or ""
        join.save(update_fields=["parent", "tab_id"])  # never `order`
```

- [ ] **Step 6: Run the tests, watch them pass**

```
uv run pytest tests/test_tabs_transfer.py -q
echo "EXIT=$?"
uv run pytest tests/ -q -k transfer
echo "EXIT=$?"
```

- [ ] **Step 7: Regenerate catalogs (new translatable error strings), lint, commit**

```
uv run python manage.py makemessages -l en -l pl --no-obsolete && uv run python manage.py compilemessages
uv run pytest tests/ -q -k "i18n or catalog"
echo "EXIT=$?"
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/transfer/ locale/ tests/test_tabs_transfer.py
git commit -m "feat(tabs): import validation (reject, never repair) + two-pass nesting resolution"
```

---

### Task 11: End-to-end — real gestures  **(use opus)**

**Files:**
- Create: `tests/test_e2e_tabs.py`
- Test: itself

**RUN DISCIPLINE — read this before running anything.** Run **only this file**, in the **foreground**:

```
uv run pytest tests/test_e2e_tabs.py -m e2e -q
echo "EXIT=$?"
```

Never run `pytest -m e2e` (the whole suite), never launch a pytest run in the background, and never park a turn on one. Each parked background e2e run re-spawns the full Playwright suite and opens dozens of `chrome-headless-shell.exe` windows on the user's desktop. The controller owns the full-suite check. Do not pipe pytest to `tail` — it masks the exit code.

**Drive the real gestures.** An e2e that reaches for `page.evaluate` to shortcut a click ships broken UX green. Click the actual buttons; press the actual keys.

**Interfaces:** consumes everything from Tasks 1–10.

- [ ] **Step 1: Write the e2e**

Model the fixtures and login on `tests/test_e2e_editor_ws3.py` and `tests/test_e2e_gallery*.py`. Use `tests.factories.TEST_PASSWORD` — never a literal.

Cover, in one or two tests:

1. **Authoring.** Open the unit editor. Click *Add element → Tabs*. Save. Assert two tab rows appear in the element list and the preview pane shows a real tab strip (`[role="tablist"]`), **not** the stacked no-JS fallback — that is the exact bug the gallery slice shipped, where the preview never loaded the enhancer.
2. **Nested add.** Expand tab 2's section, click its nested *Add element → Text*, type a body, Save. Assert the child row renders indented under tab 2, and that the preview's second panel contains the text.
3. **Student page — click.** Visit the lesson as an enrolled student. Assert panel 1 is visible and panel 2 has the `hidden` attribute. Click tab 2. Assert the attributes swap and `aria-selected` follows.
4. **Student page — keyboard.** Focus tab 1, press `ArrowRight`. Assert tab 2 activates (automatic activation) and receives focus. Press `Home`. Assert tab 1 activates.
5. **Multi-instance isolation.** Two tabs elements on one lesson. Activate tab 2 of the second element. Assert the first element's active panel is unchanged. (Construct them so the two share a tab id if the fixture allows — that is what the namespaced DOM ids protect.)
6. **Reveal handshake.** Put a gallery in tab 2. Reveal tab 2 by clicking. Assert the gallery's `.gallery__stage` has a non-zero `min-height` / `offsetHeight` after a frame. Without the `libli:reveal` listener this is zero and the carousel ships visibly collapsed while every other test passes.

- [ ] **Step 2: Run it (focused, foreground) until green**

```
uv run pytest tests/test_e2e_tabs.py -m e2e -q
echo "EXIT=$?"
```

If it fails on a database error rather than an assertion, suspect a contaminated `test_libli` from a concurrent/killed run before suspecting a code defect: re-run once with `--create-db`.

- [ ] **Step 3: Commit**

```
git add tests/test_e2e_tabs.py
git commit -m "test(tabs): e2e authoring, nested add, click + keyboard, isolation, reveal handshake"
```

---

### Task 12: Frontend-design pass  **(use opus)**

**Files:** `courses/static/courses/css/courses.css`, `courses/static/courses/css/editor.css`, and the templates as needed.

Ship this slice **styled** — a design pass inside the slice, as the gallery slice did, not deferred as the table slice did.

- [ ] **Step 1: Invoke the `frontend-design` skill** and apply it to the two new surfaces: the student tab strip + panels, and the editor's nested rows + tabs edit form.

- [ ] **Step 2: Screenshot both, in light and dark**

Drive a real browser (Playwright), navigate to a lesson containing a tabs element with a nested gallery and a nested table, and to the unit editor with that element expanded. Capture light and dark. Save to the scratchpad, then **look at them** and self-critique before declaring done. Specifically check:
- the active tab is unmistakably active in both themes (the `--primary` underline must read against `--surface-raised` in dark);
- the overflow fade uses `--surface-raised`, so it fades to the panel's real background, not white;
- the nested element list reads as *inside* the tabs row (indent + left rule), not as a sibling;
- the empty-tab state (`This tab is empty.`) is not visually broken;
- the chevrons appear only when the strip actually overflows.

- [ ] **Step 3: Verify the no-JS and print paths**

With JS disabled, every panel is visible under its heading. In print preview, every panel **and every label** is visible and the tab bar is gone. These fail invisibly — nobody prints a lesson during development.

- [ ] **Step 4: Re-run the static-contract tests** (they pin CSS/JS class drift)

```
uv run pytest tests/test_tabs_css.py tests/test_tabs_partial.py tests/test_tabs_editor_partial.py -q
echo "EXIT=$?"
```

- [ ] **Step 5: Commit**

```
uv run ruff check courses tests && uv run ruff format --check courses tests
git add courses/static/courses/css/ templates/
git commit -m "style(tabs): frontend-design pass, light + dark verified"
```

---

## Definition of Done (controller-owned)

Run these **after** the last task, from the worktree. The controller owns this; individual task implementers must not run the full e2e suite.

- [ ] `uv run pytest -q` — full non-e2e suite green (~2240 tests + the new ones).
- [ ] `uv run pytest -m e2e -q` — **the full e2e suite**, once, at the end. `pytest` deselects e2e by default, so a per-task e2e written early can silently go stale; this is what caught the table slice's failure in CI. Rendering and JS changed in Tasks 6–8, so this re-run is mandatory.
- [ ] `uv run ruff check .` **and** `uv run ruff format --check .` — both, not just the first.
- [ ] `uv run pytest -q -k "i18n or catalog"` — the catalog tests fail on obsolete `#~` entries; this slice adds and renames translatable strings.
- [ ] `uv run python manage.py makemigrations --check --dry-run` — no un-generated migrations.
- [ ] EN + PL catalogs complete; Polish plurals filled for `%(n)d tab`.
- [ ] No password literals anywhere in the diff (`git diff master... | grep -i password`).
- [ ] Screenshots reviewed, light and dark (Task 12).

## Self-Review Notes

- **Spec coverage.** Model + substrate → T1. Invariant table (all 12 walkers + 2 exemptions) → T4. Deletion + tab-removal diff → T2, T3. Nesting validation → T3, T5. Editor inline nested list → T8. Student widget, overflow, print, reveal, multi-instance → T6, T7. Transfer → T9, T10. Registry sites (all nine) → T1 (`ELEMENT_MODELS`), T3 (`FORM_FOR_TYPE`), T5 (`_ELEMENT_LABELS`, `element_summary`, `_EDITOR_TYPE_LABELS`, both allow-tuples), T9 (`SERIALIZERS`), T10 (`VALIDATORS`, `BUILDERS`). All 14 weighted tests are scheduled.
- **One deliberate deviation from the spec.** The spec describes a top-level-only media walk that recurses into children. Task 9 instead enumerates every element exactly once (top-level joins + inline child expansion), so `_element_mids` needs no recursion and the double-count cannot arise. The invariant the spec cared about — *nested media counted exactly once* — is preserved and still tested.
- **Naming consistency.** `normalize_labels_and_ids` / `normalize_data` / `join_row()` / `resolved_tabs()` / `new_tab_id()` / `default_data()` / `element_siblings()` / `resolve_scope()` / `NESTABLE_TYPE_KEYS` / `NestingError` / `libliInitTabs` / `libliInitTabsEditor` / `libli:reveal` are used identically everywhere they appear.
- **Two places the plan deliberately over-explains,** because a literal reading of an earlier draft shipped a bug: the `save()`-must-never-call-`normalize_data` rule (T1, T3), and the id-minting-before-diffing structure that removes the `KeyError` on an add-and-delete save (T3).
