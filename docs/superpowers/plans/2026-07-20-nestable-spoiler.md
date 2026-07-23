# Nestable SpoilerElement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `SpoilerElement` a nestable single-slot container so images/tables/math render *inside* a spoiler (fixing the dominant remaining LAL import image-loss bucket), while keeping the legacy flat `body` path fully working.

**Architecture:** Mirror the existing `TabsElement`/`TwoColumnElement` join-row substrate (Approach A). A spoiler's children live in `Element` rows whose `parent` is the spoiler's join row and whose `tab_id` is a single fixed slot id. **No schema change / no migration** — nesting is expressed purely through the existing `Element.parent` rows. The nested path is opt-in by presence of children; a spoiler with none falls back to `body`. Because `SpoilerElement` becomes the first type that is *both* a container AND a member of `NESTABLE_TYPE_KEYS`, three explicit guards keep the codebase's load-bearing one-level depth invariant: the parser flattens inner containers, the loader refuses a container child, and `resolve_scope` refuses giving children to an already-nested spoiler.

**Tech Stack:** Django 5.2, Postgres, pytest / pytest-django, BeautifulSoup (`html.parser`) parser under `scripts/lal_import/`, server-rendered Django templates (no React/Bootstrap).

## Global Constraints

- **No migration.** `SpoilerElement` keeps only `label` (max_length 120) and `body`. Nesting reuses existing `Element.parent`/`Element.tab_id`.
- **Depth-1 invariant is kept unchanged.** `validate_nesting` (`courses/transfer/payloads.py:722`) still rejects any element whose parent itself has a parent. Only *top-level* spoilers may have children; children must be leaf (non-container) elements.
- **Single-slot id constant.** Define `SpoilerElement.SLOT_ID = "only"` (a class attribute) and use it verbatim everywhere a spoiler child's `tab_id`/slot is written or validated: loader, `resolve_scope`, `walk_unit_joins`, `validate_nesting`, editor template. A non-empty id is required — `resolve_scope` treats an empty `tab` with a non-empty parent as an error.
- **Server-enforced spoiler-child allowlist** = `{"text", "math", "image", "video", "iframe", "table", "gallery", "callout"}` (the static content leaves). Enforced inside the `resolve_scope` spoiler branch; NOT merely hidden in the add-menu.
- **No `FORMAT_VERSION` bump.** The `parent`/`tab` nesting refs already exist at `FORMAT_VERSION = 4` (`courses/transfer/schema.py:14`).
- **Math escaping (see [[bs4-navigablestring-decodes-tag-reescapes]]).** Sanitized/`|safe` fields need `&lt;` entities; the parser already escapes math on the raw HTML before parsing. Use `node.decode_contents()` for bodies, never `"".join(str(c) ...)`.
- **Test DB / commands.** Settings module is `config.settings.test` (from `pyproject.toml`). Prefix EVERY pytest command with the isolated DB URL:
  `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest <path> -v`
  (`bash` cannot see `ruff`/`pytest`/`python` on PATH — always go through `uv run`; see [[uv-run-tooling]].)
- **Commit after each task** (frequent commits). Use the branch `worktree-matematyka-content-import` (do NOT open a PR — 57 local-only commits, no remote).

---

### Task 1: Model — SLOT_ID, `join_row()`, `resolved_children()`, `render()`

Make `SpoilerElement` expose the children-consumer handles that every other layer relies on. Mirrors `TabsElement.join_row()`/`resolved_tabs()`/`render()` (`courses/models.py:1188-1227`).

**Files:**
- Modify: `courses/models.py` (class `SpoilerElement`, `courses/models.py:397-408`)
- Test: `courses/tests/test_spoiler_nesting.py` (create)

**Interfaces:**
- Produces: `SpoilerElement.SLOT_ID` (str `"only"`); `SpoilerElement.join_row() -> Element | None`; `SpoilerElement.resolved_children() -> list[Element]` (join rows, ordered `("order","pk")`); `SpoilerElement.render(*, element=None, state=None, slug=None, node_pk=None) -> str`.
- Consumes: existing `SpoilerElement.elements` GenericRelation; `Element.children` reverse accessor (the `parent` FK's related_name — same one `TabsElement.resolved_tabs()` uses at `models.py:1206`).

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_nesting.py`:

```python
import pytest

from courses.models import Element
from courses.models import ImageElement
from courses.models import SpoilerElement
from courses.models import TextElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _nested_spoiler(unit, child_bodies=("<p>a</p>", "<p>b</p>")):
    """A top-level spoiler with N TextElement children, in order."""
    sp = SpoilerElement.objects.create(label="Hint")
    join = Element.objects.create(unit=unit, content_object=sp)
    for i, body in enumerate(child_bodies):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=body),
            parent=join,
            tab_id=SpoilerElement.SLOT_ID,
            order=i,
        )
    return sp, join


def test_slot_id_is_a_nonempty_class_attr():
    assert SpoilerElement.SLOT_ID == "only"


def test_resolved_children_returns_join_rows_in_order():
    _course, unit = make_course_with_unit()
    sp, join = _nested_spoiler(unit, ("<p>first</p>", "<p>second</p>"))
    children = sp.resolved_children()
    assert [c.content_object.body for c in children] == ["<p>first</p>", "<p>second</p>"]
    assert all(c.parent_id == join.pk for c in children)


def test_resolved_children_empty_when_no_join_row():
    sp = SpoilerElement(label="x")  # unsaved, no join row
    assert sp.resolved_children() == []


def test_render_prefers_children_over_body():
    _course, unit = make_course_with_unit()
    sp, join = _nested_spoiler(unit, ("<p>CHILD-BODY</p>",))
    sp.body = "<p>LEGACY-BODY</p>"
    sp.save()
    html = sp.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "CHILD-BODY" in html
    assert "LEGACY-BODY" not in html


def test_render_falls_back_to_body_when_no_children():
    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="x", body="<p>LEGACY-BODY</p>")
    el = add_element(unit, sp)
    html = sp.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert "LEGACY-BODY" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -v`
Expected: FAIL — `AttributeError: type object 'SpoilerElement' has no attribute 'SLOT_ID'` (and no `resolved_children`/`render`).

- [ ] **Step 3: Write minimal implementation**

In `courses/models.py`, replace the `SpoilerElement` class body (`courses/models.py:397-408`) with:

```python
class SpoilerElement(ElementBase):
    """A self-contained show/hide disclosure: an author-labelled button that
    expands/collapses either legacy rich-text `body` OR (nestable-spoiler) an
    ordered list of native child elements. Rendered as a native <details>;
    two-way, repeatable, ungraded. Single-slot container: its children live in
    Element rows whose `parent` is this element's join row and whose `tab_id` is
    the one fixed slot id SLOT_ID. Mirrors the TabsElement join-row substrate."""

    SLOT_ID = "only"  # the single implicit child slot; child Element.tab_id value

    label = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)

    def join_row(self):
        """This concrete's single Element join row (the GFK is effectively 1:1)."""
        return self.elements.order_by("pk").first()

    def resolved_children(self):
        """Ordered child Element join rows (order_by('order','pk')); [] when the
        join row is transient/mid-create. Grouped by `parent` alone — the single
        slot means tab_id is not needed to disambiguate."""
        join = self.join_row()
        if join is None:
            return []
        return list(
            join.children.order_by("order", "pk")
            .select_related("content_type")
            .prefetch_related("content_object")
        )

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        return render_to_string(
            "courses/elements/spoilerelement.html",
            {
                "el": self,
                "children": self.resolved_children(),
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
            },
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -v`
Expected: PASS (4 tests). `test_render_prefers_children_over_body` passes because Task 3 has not yet changed the template — wait: the template still renders only `body`. **This test will FAIL until Task 3.** To keep Task 1 green in isolation, mark it now with `@pytest.mark.xfail(reason="template branch lands in Task 3", strict=True)` on `test_render_prefers_children_over_body`, and REMOVE the xfail in Task 3 Step 1.

- [ ] **Step 5: Commit**

```bash
git add courses/models.py courses/tests/test_spoiler_nesting.py
git commit -m "feat(spoiler): SLOT_ID + join_row/resolved_children/render (nestable-spoiler task 1)"
```

---

### Task 2: `has_math` recursion into spoiler children

A nested spoiler has an empty `body`; without recursion, math in child `MathElement`/`TextElement` is never detected and KaTeX is not enabled. Mirror `_tabs_has_math` (`courses/views.py:222`).

**Files:**
- Modify: `courses/views.py` (`_element_has_math` SpoilerElement branch at `courses/views.py:197-198`; add `_spoiler_has_math` near `_tabs_has_math` at `courses/views.py:222`)
- Test: `courses/tests/test_spoiler_nesting.py` (append)

**Interfaces:**
- Consumes: `SpoilerElement.resolved_children()`/`.join_row()` (Task 1); `has_math_delimiters`, `_element_has_math` (existing in `courses/views.py`).

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_spoiler_nesting.py`:

```python
def test_spoiler_with_math_child_reports_has_math():
    from courses.models import MathElement
    from courses.views import _element_has_math

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="x")
    join = Element.objects.create(unit=unit, content_object=sp)
    Element.objects.create(
        unit=unit,
        content_object=MathElement.objects.create(latex="x^2"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    assert _element_has_math(sp) is True


def test_legacy_body_spoiler_math_still_detected():
    from courses.views import _element_has_math

    sp = SpoilerElement.objects.create(label="x", body=r"<p>\(a\)</p>")
    assert _element_has_math(sp) is True


def test_empty_spoiler_reports_no_math():
    from courses.views import _element_has_math

    sp = SpoilerElement.objects.create(label="x", body="")
    assert _element_has_math(sp) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k has_math -v`
Expected: FAIL on `test_spoiler_with_math_child_reports_has_math` (returns `has_math_delimiters(obj.body)` = `False` for the empty-body nested spoiler).

- [ ] **Step 3: Write minimal implementation**

In `courses/views.py`, change the SpoilerElement branch (`courses/views.py:197-198`) from:

```python
    if isinstance(obj, SpoilerElement):
        return has_math_delimiters(obj.body)
```

to:

```python
    if isinstance(obj, SpoilerElement):
        return _spoiler_has_math(obj)
```

And add, next to `_tabs_has_math` (after `courses/views.py:238`):

```python
def _spoiler_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _tabs_has_math. A nested spoiler has an
    empty body, so math lives in its children; a legacy body-only spoiler has no
    children and falls back to its body."""
    from courses.models import SpoilerElement

    if not isinstance(el, SpoilerElement):
        return False
    children = el.resolved_children()
    if not children:
        return has_math_delimiters(el.body)
    return any(_element_has_math(c.content_object) for c in children)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k has_math -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/views.py courses/tests/test_spoiler_nesting.py
git commit -m "feat(spoiler): recurse has_math into nested children (nestable-spoiler task 2)"
```

---

### Task 3: Template — children-vs-body branch

Render children recursively when present, else legacy `body`, else a truly empty `<details>` (no stray `el--text` wrapper).

**Files:**
- Modify: `templates/courses/elements/spoilerelement.html`
- Test: `courses/tests/test_spoiler_nesting.py` (remove the Task 1 xfail; add empty-case test)

**Interfaces:**
- Consumes: `children` (list of Element join rows), `el.body`, and the `render_element` tag (`courses/templatetags/courses_extras.py:25`), which reads `element_state`/`slug`/`node_pk` from context — all supplied by `SpoilerElement.render()` (Task 1).

- [ ] **Step 1: Remove the Task 1 xfail and add the empty-case test**

In `courses/tests/test_spoiler_nesting.py`, delete the `@pytest.mark.xfail(...)` line above `test_render_prefers_children_over_body`, and append:

```python
def test_empty_nested_spoiler_renders_no_body_wrapper():
    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="x", body="")
    join = Element.objects.create(unit=unit, content_object=sp)  # join, zero children
    html = sp.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "spoiler__body" not in html  # no stray el--text wrapper
    assert "<details" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k "render or body_wrapper" -v`
Expected: FAIL — `test_render_prefers_children_over_body` (template always renders `body`) and `test_empty_nested_spoiler_renders_no_body_wrapper` (always emits `spoiler__body`).

- [ ] **Step 3: Write minimal implementation**

Replace `templates/courses/elements/spoilerelement.html` entirely with:

```django
{% load i18n courses_extras %}
<details class="spoiler">
  <summary class="spoiler__toggle">
    <span class="spoiler__label spoiler__label--show">{% if el.label %}{{ el.label }}{% else %}{% trans "Reveal" %}{% endif %}</span>
    <span class="spoiler__label spoiler__label--hide">{% trans "Hide" %}</span>
  </summary>
  {% if children %}
    {% for child in children %}
      <div class="spoiler__child">{% render_element child %}</div>
    {% endfor %}
  {% elif el.body %}
    <div class="el el--text spoiler__body">{{ el.body|sanitize }}</div>
  {% endif %}
</details>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -v`
Expected: PASS (all tests, including the previously-xfail render test).

- [ ] **Step 5: Commit**

```bash
git add templates/courses/elements/spoilerelement.html courses/tests/test_spoiler_nesting.py
git commit -m "feat(spoiler): template renders children else body (nestable-spoiler task 3)"
```

---

### Task 4: Loader — dual-path `build_element` spoiler branch + depth guard

Build the nested form (join row + recursed children) when the dict carries `elements` (by key presence), else the legacy flat form. Refuse a container child (defence-in-depth).

**Files:**
- Modify: `courses/lal_loader/builders.py` (spoiler branch at `courses/lal_loader/builders.py:64-71`; imports `Element`, `LoaderError`, `SpoilerElement` are already present)
- Test: `tests/test_lal_loader_units.py` (append)

**Interfaces:**
- Consumes: `SpoilerElement.SLOT_ID` (Task 1); the `build_element(course, unit, el, *, source_root, source_dir, allow_html, parent=None, tab_id="")` signature (`courses/lal_loader/builders.py:41`); `_attach` local; `Element.objects.create(...)` join-row pattern from the `tabs` branch (`builders.py:116-118`).
- Produces: a nested `{type:"spoiler", label, elements:[...]}` dict builds a `SpoilerElement` + join row + one child `Element` per entry (each `tab_id == SLOT_ID`); returns the concrete `SpoilerElement`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_lal_loader_units.py` (match the file's existing import style — inspect its top for `build_element`/`LoaderError`/factory helpers and reuse them; the assertions below are the contract):

```python
def test_build_spoiler_nested_creates_children_in_order():
    from courses.lal_loader.builders import build_element
    from courses.models import Element, SpoilerElement, TextElement, ImageElement
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "Answer",
        "elements": [
            {"type": "text", "body": "<p>step 1</p>"},
            {"type": "text", "body": "<p>step 2</p>"},
        ],
    }
    obj = build_element(
        course, unit, el, source_root="", source_dir="", allow_html=False
    )
    assert isinstance(obj, SpoilerElement)
    join = obj.join_row()
    kids = list(join.children.order_by("order", "pk"))
    assert [k.tab_id for k in kids] == [SpoilerElement.SLOT_ID, SpoilerElement.SLOT_ID]
    assert [k.content_object.body for k in kids] == ["<p>step 1</p>", "<p>step 2</p>"]


def test_build_spoiler_empty_elements_list_builds_empty_disclosure():
    from courses.lal_loader.builders import build_element
    from courses.models import SpoilerElement
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {"type": "spoiler", "label": "L", "elements": []}  # key present, no body
    obj = build_element(course, unit, el, source_root="", source_dir="", allow_html=False)
    assert isinstance(obj, SpoilerElement)
    assert obj.resolved_children() == []
    assert obj.body == ""


def test_build_spoiler_legacy_body_still_flat():
    from courses.lal_loader.builders import build_element
    from courses.models import SpoilerElement
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {"type": "spoiler", "label": "L", "body": "<p>legacy</p>"}
    obj = build_element(course, unit, el, source_root="", source_dir="", allow_html=False)
    assert obj.resolved_children() == []
    assert "<p>legacy</p>" in obj.body


def test_build_spoiler_rejects_container_child():
    import pytest
    from courses.lal_loader.builders import build_element, LoaderError
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = {
        "type": "spoiler",
        "label": "L",
        "elements": [{"type": "tabs", "tabs": []}],  # container child -> refuse
    }
    with pytest.raises(LoaderError):
        build_element(course, unit, el, source_root="", source_dir="", allow_html=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_lal_loader_units.py -k spoiler -v`
Expected: FAIL — the current branch does `body=el["body"]` and `KeyError: 'body'` on the nested dicts (no `body` key).

- [ ] **Step 3: Write minimal implementation**

In `courses/lal_loader/builders.py`, replace the spoiler branch (`courses/lal_loader/builders.py:64-71`) with:

```python
    if etype == "spoiler":
        if "elements" in el:  # nested path — key presence, NOT truthiness
            obj = SpoilerElement.objects.create(label=el.get("label", "")[:120])
            join = Element.objects.create(
                unit=unit, parent=parent, tab_id=tab_id, content_object=obj
            )
            for child in el["elements"]:
                ctype = child.get("type")
                # Defence-in-depth: the parser's no-nest-container mode never emits
                # a container child of a spoiler, so one here is malformed JSON.
                if ctype in ("tabs", "two_column") or (
                    ctype == "spoiler" and "elements" in child
                ):
                    raise LoaderError(
                        f"container element ({ctype}) nested inside a spoiler "
                        f"in unit {unit.pk}"
                    )
                build_element(
                    course,
                    unit,
                    child,
                    source_root=source_root,
                    source_dir=source_dir,
                    allow_html=allow_html,
                    parent=join,
                    tab_id=SpoilerElement.SLOT_ID,
                )
            return obj
        return _attach(
            unit,
            SpoilerElement.objects.create(
                label=el.get("label", "")[:120],  # varchar(120); parser labels uncapped
                body=el["body"],
            ),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_lal_loader_units.py -k spoiler -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/lal_loader/builders.py tests/test_lal_loader_units.py
git commit -m "feat(lal-loader): dual-path spoiler builder + container-child guard (nestable-spoiler task 4)"
```

---

### Task 5: Parser — no-nest-container mode + nested `elements` from all three spoiler sources

Change `_emit_details`, `_reveal_table_spoilers`, and the `show_solution` handler to emit `{type:"spoiler", label, elements:[...]}`, walking the content through `_walk`. Inside a spoiler sub-walk (`state["in_spoiler"]`), inner disclosures and `ks_tabs` are flattened inline so no nested container dict is ever produced (keeps depth 1).

**Files:**
- Modify: `scripts/lal_import/lesson.py` (`_walk` details/ks_tabs/show_solution branches; `_emit_details` at `lesson.py:1130`; `_reveal_table_spoilers` at `lesson.py:235`; add `_flatten_tabs_inline`; caller of `_reveal_table_spoilers` at `lesson.py:516`)
- Test: `tests/lal_import/test_lesson.py` (append; update any existing spoiler-`body` assertions to the nested shape)

**Interfaces:**
- Consumes: `_walk(nodes, elements, flags, consumed, state)`; `_emit_tabs(node, flags, consumed, state) -> dict | None`; `state` dict (shared, already threads a mutable `h2_skipped` flag — this task adds an `in_spoiler` flag the same way).
- Produces: all three spoiler emitters yield `{"type":"spoiler", "label":..., "elements":[<child dicts>]}` (no `body` key). Images inside spoiler content become `image` child dicts automatically (the existing image-table/prose-image logic runs in the sub-walk).

- [ ] **Step 1: Write the failing test**

Append to `tests/lal_import/test_lesson.py` (reuse the file's existing `parse_lesson`/helper imports at its top):

```python
def _only_spoiler(elements):
    sp = [e for e in elements if e.get("type") == "spoiler"]
    assert len(sp) == 1, elements
    return sp[0]


def test_details_with_image_becomes_nested_spoiler_with_image_child():
    html = (
        "<body><details><summary>Solution</summary>"
        "<p>see</p><img src='fig.png' alt='f'></details></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)
    assert "elements" in sp and "body" not in sp
    kinds = [c["type"] for c in sp["elements"]]
    assert "image" in kinds


def test_show_solution_with_image_becomes_nested_spoiler():
    html = (
        "<body>"
        "<div class='show_solution'>zobacz</div>"
        "<div class='question_solution'><p>x</p><img src='a.png'></div>"
        "</body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)
    assert "elements" in sp
    assert any(c["type"] == "image" for c in sp["elements"])


def test_reveal_table_row_becomes_nested_spoiler():
    html = (
        "<body><table><tr>"
        "<td>concept</td>"
        "<td class='question_solution'><p>ans</p><img src='r.png'></td>"
        "</tr></table></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)
    assert sp["label"] == "concept"
    assert any(c["type"] == "image" for c in sp["elements"])


def test_details_inside_solution_is_inlined_not_nested_spoiler():
    # No-nest-container mode: an inner <details> must NOT emit a nested spoiler dict.
    html = (
        "<body>"
        "<div class='show_solution'>zobacz</div>"
        "<div class='question_solution'>"
        "<p>outer</p><details><summary>inner</summary><p>deep</p></details>"
        "</div></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)  # exactly ONE spoiler total (no nested one)
    child_types = [c["type"] for c in sp["elements"]]
    assert "spoiler" not in child_types  # inner disclosure inlined
    # inner content is present (heading + deep text among the inlined children)
    assert any(c["type"] == "text" for c in sp["elements"])


def test_show_solution_inside_solution_is_inlined_not_nested_spoiler():
    # A show_solution button + its solution INSIDE a question_solution cell must
    # NOT emit a depth-2 spoiler dict (which the loader guard would abort on).
    html = (
        "<body>"
        "<div class='show_solution'>outer</div>"
        "<div class='question_solution'>"
        "<p>lead</p>"
        "<div class='show_solution'>inner</div>"
        "<div class='question_solution'><p>deep</p></div>"
        "</div></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)  # exactly ONE spoiler (the inner one inlined)
    assert "spoiler" not in [c["type"] for c in sp["elements"]]
    assert any(c["type"] == "text" for c in sp["elements"])


def test_reveal_table_inside_solution_is_inlined_not_nested_spoiler():
    # A reveal-<table> INSIDE a question_solution cell must inline its rows, not
    # emit nested spoiler dicts.
    html = (
        "<body>"
        "<div class='show_solution'>outer</div>"
        "<div class='question_solution'>"
        "<table><tr><td>row</td>"
        "<td class='question_solution'><p>ans</p></td></tr></table>"
        "</div></body>"
    )
    elements, _flags = parse_lesson(html, html)
    sp = _only_spoiler(elements)  # exactly ONE spoiler total
    assert "spoiler" not in [c["type"] for c in sp["elements"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/lal_import/test_lesson.py -k "nested_spoiler or inlined" -v`
Expected: FAIL — emitters currently produce `{"type":"spoiler","label","body"}` (no `elements`; the `"elements" in sp` assertions fail).

- [ ] **Step 3: Write minimal implementation**

**(a)** Add a shared `_emit_solution_region` helper (place near `_walk`, after `parse_lesson`). This is the single place that decides nested-spoiler vs. inline, so **all three** spoiler sources get no-nest-container behavior uniformly:

```python
def _emit_solution_region(label, content_nodes, elements, flags, consumed, state):
    """A labelled disclosure region (from <details>, show_solution, or a reveal-
    table row). At TOP LEVEL -> a nested SpoilerElement dict whose children are the
    walked content (images/tables/math survive as their own children). INSIDE a
    spoiler (no-nest-container mode) -> inlined in place (label -> heading child,
    content walked inline), never a nested container dict, keeping depth at 1."""
    if state.get("in_spoiler"):
        if label:
            elements.append({"type": "text", "body": f"<h4>{label}</h4>"})
        _walk(content_nodes, elements, flags, consumed, state)
    else:
        child_elements = []
        prev = state.get("in_spoiler", False)  # always False here, but be explicit
        state["in_spoiler"] = True
        try:
            _walk(content_nodes, child_elements, flags, consumed, state)
        finally:
            state["in_spoiler"] = prev
        elements.append(
            {"type": "spoiler", "label": label, "elements": child_elements}
        )
```

> **Note (relative-href flags, intentional):** the emitters below keep their
> pre-walk `_flag_relative_hrefs(sol/details, flags)` call even though
> `_emit_solution_region` then sub-walks the same nodes (whose text/inline branch
> also flags descendant `<a>` hrefs). This double-flags a relative href inside a
> spoiler. Keep it: dropping the pre-walk call risks *under*-flagging a href in a
> node type the sub-walk doesn't route through text/inline, whereas double-flagging
> only inflates a diagnostic warning count. It does NOT affect the Task 10 image
> re-measure (`measure_lost_imgs.py` counts `<img>`, not href flags).

**(b)** Change `_emit_details` (`scripts/lal_import/lesson.py:1130-1143`) to delegate to it:

```python
def _emit_details(details, elements, flags, consumed, state):
    """<details><summary>LABEL</summary>BODY</details> -> nested SpoilerElement
    (or inlined, inside a spoiler). BODY is walked into child element dicts."""
    summary = details.find("summary")
    label = summary.get_text(strip=True) if summary is not None else ""
    if summary is not None:
        summary.extract()
    _flag_relative_hrefs(details, flags)  # spoiler children are nh3-sanitized too
    _emit_solution_region(label, list(details.children), elements, flags, consumed, state)
```

**(c)** Change `_reveal_table_spoilers` (`scripts/lal_import/lesson.py:235-254`) to delegate per row:

```python
def _reveal_table_spoilers(table, consumed, state):
    """One nested Spoiler per <tr> with a .question_solution cell (or inlined rows,
    inside a spoiler). label = the row's first <td> text."""
    elements, flags = [], []
    for tr in table.find_all("tr"):
        sol = tr.find(class_="question_solution")
        if sol is None:
            continue
        first_td = tr.find("td")
        label = first_td.get_text(strip=True) if first_td is not None else ""
        _flag_relative_hrefs(sol, flags)
        _emit_solution_region(label, list(sol.children), elements, flags, consumed, state)
    return elements, flags
```

Update its caller (`scripts/lal_import/lesson.py:516`) from
`sp_elements, sp_flags = _reveal_table_spoilers(node)` to
`sp_elements, sp_flags = _reveal_table_spoilers(node, consumed, state)`. (The `table`-branch call site is reached in BOTH modes — when `state["in_spoiler"]` is set, `_emit_solution_region` inlines each row, so no `in_spoiler` check is needed at the call site.)

**(d)** Change the `show_solution` handler (`scripts/lal_import/lesson.py:490-503`) to delegate:

```python
        if _is_show_solution_button(node):
            sol = _find_solution(nodes, i, consumed)
            if sol is not None:
                consumed.add(id(sol))  # so the loop does not re-flag it (I2)
                _flag_relative_hrefs(sol, flags)
                _emit_solution_region(
                    node.get_text(strip=True) or "zobacz",
                    list(sol.children),
                    elements,
                    flags,
                    consumed,
                    state,
                )
                continue
            _unmapped("show_solution button without solution", node, elements, flags)
            continue
```

**(e)** In `_walk`, change the `details` branch (`scripts/lal_import/lesson.py:475-489`) — the plain-`<details>` case just calls `_emit_details` (which now handles both modes via `_emit_solution_region`); the `<details>`-wrapping-`ks_tabs` case keeps its existing drop-wrapper behavior:

```python
        if name == "details":
            if node.find(class_="ks_tabs") is not None:
                # A <details> wrapping a tab group: drop the collapse wrapper and
                # emit its content (summary -> heading). At top level the inner
                # ks_tabs becomes a native TabsElement; inside a spoiler the ks_tabs
                # branch below flattens it (in_spoiler propagates via `state`).
                summary = node.find("summary")
                if summary is not None:
                    label = summary.decode_contents().strip()
                    if label:
                        elements.append({"type": "text", "body": f"<h4>{label}</h4>"})
                    summary.extract()
                _walk(list(node.children), elements, flags, consumed, state)
            else:
                _emit_details(node, elements, flags, consumed, state)
            continue
```

**(f)** In `_walk`, change the `ks_tabs` branch (`scripts/lal_import/lesson.py:392-404`) to:

```python
        if "ks_tabs" in classes_here:
            if state.get("in_spoiler"):
                # No-nest-container mode: a ks_tabs inside a spoiler can't become a
                # nested Tabs (depth-1), so flatten it inline.
                _flatten_tabs_inline(node, elements, flags, consumed, state)
            else:
                # Group B #6: a tabbed container -> TabsElement with nested children.
                tabs_el = _emit_tabs(node, flags, consumed, state)
                if tabs_el is not None:
                    elements.append(tabs_el)
                else:
                    _unmapped(
                        "ks_tabs outside TabsElement's 2..10 tab bounds",
                        node,
                        elements,
                        flags,
                    )
            continue
```

**(g)** Add `_flatten_tabs_inline` (near `_emit_tabs`):

```python
def _flatten_tabs_inline(node, elements, flags, consumed, state):
    """No-nest-container mode: reuse _emit_tabs to parse the tab group, then splice
    it inline -- each tab label -> a heading text child, each tab's parsed content
    appended as sibling children. _emit_tabs's internal walk sees state['in_spoiler']
    too, so any deeper container inside a panel is likewise flattened."""
    tabs_el = _emit_tabs(node, flags, consumed, state)
    if tabs_el is None:
        _unmapped(
            "ks_tabs inside spoiler outside 2..10 tab bounds", node, elements, flags
        )
        return
    for tab in tabs_el["tabs"]:
        if tab.get("label"):
            elements.append({"type": "text", "body": f"<h4>{tab['label']}</h4>"})
        elements.extend(tab.get("elements", []))
```

- [ ] **Step 4: Migrate the pre-existing spoiler-`body` tests, then run the full parser suite**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/lal_import/test_lesson.py -v`
Expected: the new tests PASS. Four pre-existing tests assert `sp["body"]` and now fail because all spoiler sources emit `elements` (no `body` key). Migrate EXACTLY these, preserving each test's original invariant — do NOT weaken a negative/exclusion assertion into a presence check:

1. `test_spoiler_from_show_solution` (`test_lesson.py:53`): replace `assert "emptyset" in sp["body"]` with
   `assert any("emptyset" in c.get("body", "") for c in sp["elements"])`.
2. `test_spoiler_body_preserves_escaped_math` (`test_lesson.py:121`): replace `assert r"\(a&lt;b\)" in sp["body"]` with
   `assert any(r"\(a&lt;b\)" in c.get("body", "") for c in sp["elements"])`  (entity `&lt;` preserved in the child body, not literal `<`).
3. `test_r4_details_becomes_spoiler` (`test_lesson.py:169-170`): keep `assert sp["label"] == "obliczenia"`; replace the body-escaping line with
   `assert any(r"\(a&lt;b\)" in c.get("body", "") for c in sp["elements"])`; and re-express the **exclusion** invariant `assert "obliczenia" not in sp["body"]` as
   `assert not any("obliczenia" in c.get("body", "") for c in sp["elements"])`  (the summary label must not leak into any child body).
4. `test_reverse_order_show_solution_finds_preceding_solution` (`test_lesson.py:307`): replace `assert "x=2" in sp["body"]` with
   `assert any("x=2" in c.get("body", "") for c in sp["elements"])`. Line 310's top-level "must not leak as a standalone text element" assertion still holds (the solution content is now a CHILD of the spoiler, not a top-level element) — leave it.

Do NOT touch these (their assertions survive unchanged): `test_r3_reveal_table_becomes_spoilers_per_row` (labels only), `test_plain_details_still_becomes_spoiler` (asserts a spoiler exists), `test_details_wrapping_tabs_emits_native_tabs_no_spoiler` (no spoiler; text bodies), `test_relative_href_inside_spoiler_is_flagged` (flags only). Re-run until the whole file is green.

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/lesson.py tests/lal_import/test_lesson.py
git commit -m "feat(lal-import): spoiler sources emit nested elements; no-nest-container mode (nestable-spoiler task 5)"
```

---

### Task 6: Transfer — export walk + validator special-case (serializers unchanged)

A nested spoiler's children must survive export, import, and duplicate-unit. Children ride as separate `Element` payloads (like Tabs), so `_ser`/`_val`/`_build_spoiler` stay `{label, body}`; only `walk_unit_joins` and `validate_nesting` change.

**Files:**
- Modify: `courses/transfer/export.py` (`walk_unit_joins`, `courses/transfer/export.py:430-440`)
- Modify: `courses/transfer/payloads.py` (`_CONTAINER_SLOT_KEY` at `payloads.py:697`; `validate_nesting` at `payloads.py:700-733`)
- Test: `courses/tests/test_spoiler_transfer.py` (append)

**Interfaces:**
- Consumes: `SpoilerElement.SLOT_ID`, `SpoilerElement.resolved_children()` (Task 1). `validate_nesting` reads `parent["type"]`, `parent["parent"]`, `el["tab"]`; the depth check `parent["parent"] is not None` is at `payloads.py:722`.
- Produces: `walk_unit_joins` yields `(child, join, SpoilerElement.SLOT_ID)` for each nested spoiler child; `validate_nesting` accepts a spoiler child whose `tab == SLOT_ID` and still rejects a depth-2 spoiler child.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_spoiler_transfer.py`:

```python
@pytest.mark.django_db
def test_walk_unit_joins_expands_spoiler_children():
    from courses.models import Element, SpoilerElement, TextElement
    from courses.transfer.export import walk_unit_joins
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="L")
    join = Element.objects.create(unit=unit, content_object=sp)
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>c</p>"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    joins_by_unit = {unit.pk: [join]}  # only top-level joins
    yielded = list(walk_unit_joins(unit.pk, joins_by_unit))
    assert (join, None, "") in yielded
    assert (child, join, SpoilerElement.SLOT_ID) in yielded


def test_validate_nesting_accepts_spoiler_slot_and_rejects_depth2():
    from courses.transfer.payloads import validate_nesting
    from courses.transfer.schema import TransferError
    from courses.models import SpoilerElement

    slot = SpoilerElement.SLOT_ID
    ok = [
        {"id": "sp", "type": "spoiler", "parent": None, "tab": None, "data": {"label": "L", "body": ""}},
        {"id": "c1", "type": "text", "parent": "sp", "tab": slot, "data": {"body": "<p>x</p>"}},
    ]
    validate_nesting(ok)  # must not raise

    bad_slot = [
        {"id": "sp", "type": "spoiler", "parent": None, "tab": None, "data": {"label": "", "body": ""}},
        {"id": "c1", "type": "text", "parent": "sp", "tab": "wrong", "data": {"body": "x"}},
    ]
    with pytest.raises(TransferError):
        validate_nesting(bad_slot)

    depth2 = [
        {"id": "t", "type": "tabs", "parent": None, "tab": None, "data": {"tabs": [{"id": "t000001", "label": "T"}]}},
        {"id": "sp", "type": "spoiler", "parent": "t", "tab": "t000001", "data": {"label": "", "body": ""}},
        {"id": "c1", "type": "text", "parent": "sp", "tab": slot, "data": {"body": "x"}},
    ]
    with pytest.raises(TransferError):  # depth-2 child still rejected
        validate_nesting(depth2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_transfer.py -k "walk_unit or validate_nesting" -v`
Expected: FAIL — `walk_unit_joins` yields only the join (not the child); `validate_nesting` `_err`s on the spoiler parent ("not a container element") because `spoiler` is absent from `_CONTAINER_SLOT_KEY`.

- [ ] **Step 3: Write minimal implementation**

**(a)** In `courses/transfer/export.py`, add a spoiler branch to `walk_unit_joins` after the `TwoColumnElement` branch (`courses/transfer/export.py:437-440`):

```python
        elif isinstance(obj, SpoilerElement):
            for child in obj.resolved_children():
                yield child, join, SpoilerElement.SLOT_ID
```

Ensure `SpoilerElement` is imported at the top of `export.py` (add to the existing `from courses.models import ...` block if missing).

**(b)** In `courses/transfer/payloads.py`, rework `validate_nesting` (`payloads.py:700-733`) so the spoiler single-slot is recognized WITHOUT a `data` slot-list, while still falling through to the depth check. Replace the per-element body of the loop with:

```python
    from courses.builder import NESTABLE_TYPE_KEYS
    from courses.models import SpoilerElement

    by_id = {el["id"]: el for el in elements}
    for el in elements:
        parent_ref = el["parent"]
        if parent_ref is None:
            continue
        parent = by_id.get(parent_ref)
        if parent is None:
            _err(_("Element '%(el)s' references an unknown parent."), el=el["id"])
        # Slot-membership: spoiler is a single-slot container with no `data` slot
        # list, so its sole valid slot id is SpoilerElement.SLOT_ID; every other
        # container reads its slot list from `data` via _CONTAINER_SLOT_KEY.
        if parent["type"] == "spoiler":
            valid_slot_ids = {SpoilerElement.SLOT_ID}
        else:
            slot_key = _CONTAINER_SLOT_KEY.get(parent["type"])
            if slot_key is None:
                _err(
                    _("Element '%(el)s' has a parent that is not a container element."),
                    el=el["id"],
                )
            valid_slot_ids = {s["id"] for s in parent["data"][slot_key]}
        # Depth check runs for EVERY container (must NOT be skipped for spoiler).
        if parent["parent"] is not None:
            _err(_("Element '%(el)s' is nested more than one level deep."), el=el["id"])
        if el["tab"] not in valid_slot_ids:
            _err(
                _("Element '%(el)s' references a slot its parent does not have."),
                el=el["id"],
            )
        if el["type"] not in NESTABLE_TYPE_KEYS:
            _err(
                _("Element '%(el)s' may not be nested inside a tabs element."),
                el=el["id"],
            )
```

(`_CONTAINER_SLOT_KEY` is left unchanged — spoiler is handled by the explicit branch, not the map.)

- [ ] **Step 4: Run test to verify it passes + full transfer suite**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_transfer.py courses/tests/test_switchgrid_transfer.py -v`
Expected: PASS (new tests + the existing flat-spoiler round-trip/validator-strict tests still green — serializers unchanged).

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/tests/test_spoiler_transfer.py
git commit -m "feat(transfer): export/validate nested spoiler children (nestable-spoiler task 6)"
```

---

### Task 7: Builder editor — `resolve_scope` single-slot branch + allowlist + top-level guard

Recognize a spoiler parent as a single-slot container without touching `_CONTAINER_REGISTRY` or `parent_obj.data`; enforce the child-type allowlist; refuse giving children to a nested spoiler.

**Files:**
- Modify: `courses/builder.py` (`resolve_scope` at `courses/builder.py:78-116`; add a `SPOILER_CHILD_TYPES` constant near `NESTABLE_TYPE_KEYS`)
- Test: `courses/tests/test_spoiler_nesting.py` (append)

**Interfaces:**
- Consumes: `SpoilerElement.SLOT_ID`; `Element` lookup by pk/unit; `NestingError`.
- Produces: `resolve_scope(unit, parent_ref, tab, type_key)` returns `(join, SLOT_ID)` for a valid top-level-spoiler add of an allowlisted leaf type; raises `NestingError` otherwise.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_spoiler_nesting.py`:

```python
def _spoiler_join(unit, parent=None, tab_id=""):
    sp = SpoilerElement.objects.create(label="L")
    return sp, Element.objects.create(
        unit=unit, content_object=sp, parent=parent, tab_id=tab_id
    )


def test_resolve_scope_accepts_leaf_child_in_top_level_spoiler():
    from courses import builder

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    parent_join, tab = builder.resolve_scope(
        unit, str(join.pk), SpoilerElement.SLOT_ID, "text"
    )
    assert parent_join == join
    assert tab == SpoilerElement.SLOT_ID


def test_resolve_scope_rejects_disallowed_child_type_in_spoiler():
    import pytest
    from courses import builder
    from courses.builder import NestingError

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    for bad in ("tabs", "spoiler", "revealgate", "choicequestion"):
        with pytest.raises(NestingError):
            builder.resolve_scope(unit, str(join.pk), SpoilerElement.SLOT_ID, bad)


def test_resolve_scope_rejects_wrong_slot_for_spoiler():
    import pytest
    from courses import builder
    from courses.builder import NestingError

    _course, unit = make_course_with_unit()
    _sp, join = _spoiler_join(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(join.pk), "wrong", "text")


def test_resolve_scope_refuses_children_for_nested_spoiler():
    import pytest
    from courses import builder
    from courses.builder import NestingError
    from courses.models import TabsElement

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tjoin = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    # a spoiler nested inside a tab (depth 1) may NOT itself receive children
    _sp, sp_join = _spoiler_join(unit, parent=tjoin, tab_id=tab_id)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(sp_join.pk), SpoilerElement.SLOT_ID, "text")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k resolve_scope -v`
Expected: FAIL — current `resolve_scope` calls `_CONTAINER_REGISTRY.get(type(parent_obj))` → `None` for a spoiler → `NestingError("parent is not a container")`, so the accept test fails (and it would `AttributeError` on `parent_obj.data` if registered).

- [ ] **Step 3: Write minimal implementation**

In `courses/builder.py`, add near `NESTABLE_TYPE_KEYS` (after `courses/builder.py:66`):

```python
# Static content leaves a spoiler may hold as children (server-enforced). Excludes
# spoiler itself, containers, interactive/stateful types, and questions -- the
# depth-1 leaf-only scope of the nestable-spoiler feature.
SPOILER_CHILD_TYPES = frozenset(
    {"text", "math", "image", "video", "iframe", "table", "gallery", "callout"}
)
```

In `resolve_scope` (`courses/builder.py:78-116`), insert a spoiler branch AFTER `parent_obj = join.content_object` (`builder.py:100`) and BEFORE the `_CONTAINER_REGISTRY.get(...)` lookup (`builder.py:106`):

```python
    from courses.models import SpoilerElement

    if isinstance(parent_obj, SpoilerElement):
        # Single-slot container: no `data` slot list to read. A spoiler may receive
        # children only when it is itself top-level (depth-1 invariant), and only
        # allowlisted leaf child types (spoiler/containers/interactive excluded).
        if join.parent_id is not None:
            raise NestingError("a nested spoiler may not have children")
        if tab != SpoilerElement.SLOT_ID:
            raise NestingError("unknown slot")
        if type_key not in SPOILER_CHILD_TYPES:
            raise NestingError(f"{type_key} may not be nested inside a spoiler")
        return join, SpoilerElement.SLOT_ID
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k resolve_scope -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/builder.py courses/tests/test_spoiler_nesting.py
git commit -m "feat(builder): resolve_scope single-slot spoiler branch + allowlist + top-level guard (nestable-spoiler task 7)"
```

---

### Task 8: Editor form — `SpoilerElementForm` drops `body` when the instance has children

Prevent the flat body editor from running on a spoiler that has children (a save would otherwise orphan them behind a re-shown `body`).

**Files:**
- Modify: `courses/element_forms.py` (`SpoilerElementForm` at `courses/element_forms.py:218-221`)
- Test: `courses/tests/test_spoiler_nesting.py` (append)

**Interfaces:**
- Consumes: `SpoilerElement.resolved_children()` (Task 1). `SpoilerElementForm` is opened by `element_form`/`element_save` via `FORM_FOR_TYPE["spoiler"](instance=...)` (`courses/views_manage.py:1123`, `:845`).

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_spoiler_nesting.py`:

```python
def test_spoiler_form_keeps_body_for_legacy_spoiler():
    from courses.element_forms import SpoilerElementForm

    sp = SpoilerElement.objects.create(label="L", body="<p>x</p>")
    form = SpoilerElementForm(instance=sp)
    assert "body" in form.fields
    assert "label" in form.fields


def test_spoiler_form_drops_body_when_instance_has_children():
    from courses.element_forms import SpoilerElementForm

    _course, unit = make_course_with_unit()
    sp, _join = _nested_spoiler(unit, ("<p>c</p>",))
    form = SpoilerElementForm(instance=sp)
    assert "body" not in form.fields
    assert "label" in form.fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k spoiler_form -v`
Expected: FAIL — `SpoilerElementForm` always includes `body`.

- [ ] **Step 3: Write minimal implementation**

In `courses/element_forms.py`, replace `SpoilerElementForm` (`courses/element_forms.py:218-221`) with:

```python
class SpoilerElementForm(forms.ModelForm):
    class Meta:
        model = SpoilerElement
        fields = ["label", "body"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A nested spoiler edits its children via the nested editor rows, not this
        # flat form; drop `body` so a save can never blank it or orphan children.
        inst = self.instance
        if inst is not None and inst.pk and inst.resolved_children():
            self.fields.pop("body", None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k spoiler_form -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py courses/tests/test_spoiler_nesting.py
git commit -m "feat(editor): SpoilerElementForm drops body when spoiler has children (nestable-spoiler task 8)"
```

---

### Task 9: Editor templates — `_element_row` spoiler branch + `in_spoiler` add-menu

Render the recursive child list + add-menu for a *top-level* spoiler; pass a distinct `in_spoiler` flag so the add-menu hides the cards the server allowlist rejects, without regressing the Tabs/TwoColumn nested menus.

**Files:**
- Modify: `templates/courses/manage/editor/_element_row.html` (add a `spoilerelement` branch before the generic `{% else %}` at line 136)
- Modify: `templates/courses/manage/editor/_add_menu.html` (gate `spoiler` + Interactive group + `html` card on `in_spoiler`)
- Test: `courses/tests/test_spoiler_nesting.py` (append; uses the Django test client)

**Interfaces:**
- Consumes: `obj.resolved_children` (Task 1), `obj.SLOT_ID` (Task 1, class attr — resolves in templates); the recursive `_element_row.html` include; the editor route `courses:manage_editor`.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_spoiler_nesting.py`. These use the Django `client` fixture and `make_pa` exactly like `courses/tests/test_switchgrid_authoring.py:19-37,66-89` (do NOT use an inline `Client()` shim). A `_spoiler_menu_block(html)` helper isolates the spoiler's own `addwrap` so the card assertions are not satisfied by the top-level menu:

```python
from django.urls import reverse
from tests.factories import CourseFactory
from tests.factories import ContentNodeFactory
from tests.factories import make_pa


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _editor_html(client, course, unit):
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    return resp.content.decode()


def _spoiler_menu_block(html, join_pk):
    """The spoiler's OWN in_spoiler add-menu, bounded to its addwrap. The editor
    renders an unconditional top-level `_add_menu` after the element list, so a
    fixed-size window would overrun into it and defeat the assertions. Slice from
    this spoiler's `data-parent="<pk>"` marker to the START of the NEXT addwrap
    (the token `addwrap` appears only in an add-menu wrapper's class, and the two
    occurrences in THIS wrapper's `class="addwrap addwrap--nested"` are before the
    marker), so the window contains exactly this spoiler's menu."""
    marker = f'data-parent="{join_pk}"'
    start = html.index(marker)
    rest = html[start + len(marker):]
    nxt = rest.find("addwrap")  # start of the next add-menu wrapper, if any
    return rest if nxt == -1 else rest[:nxt]


def test_top_level_spoiler_renders_child_list_and_add_menu(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    sp, join = _nested_spoiler(unit, ("<p>c</p>",))
    html = _editor_html(client, course, unit)
    assert f'data-parent="{join.pk}"' in html          # add-menu scope present
    assert f'data-tab="{SpoilerElement.SLOT_ID}"' in html


def test_spoiler_add_menu_hides_disallowed_cards(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _sp, join = _nested_spoiler(unit, ("<p>c</p>",))
    block = _spoiler_menu_block(_editor_html(client, course, unit), join.pk)
    # allowlisted leaves ARE offered inside the spoiler menu
    for allowed in ("text", "image", "table", "math", "video", "iframe", "gallery", "callout"):
        assert f'data-add-type="{allowed}"' in block, allowed
    # disallowed cards are NOT offered inside the spoiler menu
    for banned in ("html", "spoiler", "revealgate", "fillgate", "switchgate", "stepper"):
        assert f'data-add-type="{banned}"' not in block, banned


def test_tabs_nested_menu_still_offers_spoiler(client):
    # PR #126 no-regression: the Tabs nested add-menu (nested=True, NOT in_spoiler)
    # must still offer the spoiler + interactive cards.
    from courses.models import TabsElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=unit, content_object=tabs)
    html = _editor_html(client, course, unit)
    assert 'data-add-type="spoiler"' in html  # still present via the tabs nested menu


def test_reorder_and_delete_spoiler_child_via_generic_element_ops(client):
    # add/edit are covered by resolve_scope (Task 7) + the form (Task 8); reorder/
    # delete are generic Element ops (shared with Tabs). Prove they work for the
    # spoiler slot: reorder swaps child order; delete removes one child cleanly.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    sp, join = _nested_spoiler(unit, ("<p>A</p>", "<p>B</p>"))
    a, b = sp.resolved_children()
    b_pk = b.pk
    # reorder: give the second child a lower order -> it comes first
    b.order = -1
    b.save(update_fields=["order"])
    assert [c.pk for c in sp.resolved_children()] == [b_pk, a.pk]
    # delete the first child's concrete -> its Element join row cascades away
    # (TextElement.elements is a GenericRelation), leaving exactly one child.
    a.content_object.delete()
    remaining = sp.resolved_children()
    assert [c.pk for c in remaining] == [b_pk]
    assert remaining[0].content_object.body == "<p>B</p>"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -k "spoiler and (menu or child_list or renders)" -v`
Expected: FAIL — `test_top_level_spoiler_renders_child_list_and_add_menu` and `test_spoiler_add_menu_hides_disallowed_cards` fail because a spoiler currently renders through the generic `{% else %}` leaf row (no child list, no `data-parent` add-menu). `test_tabs_nested_menu_still_offers_spoiler` and the reorder/delete test already pass (they exercise existing behavior — that's fine, they guard against regressions introduced by this task).

- [ ] **Step 3: Write minimal implementation**

**(a)** In `templates/courses/manage/editor/_element_row.html`, add a branch immediately before `{% else %}` (`_element_row.html:136`), modelled on the tabs branch (`_element_row.html:44-89`) but single-slot and gated top-level:

```django
{% elif el.content_type.model == "spoilerelement" and el.parent_id is None %}
<li class="el-row el-row--spoiler{% if open_form_pk == el.pk|stringformat:'s' %} el-row--editing{% endif %}"
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
  Single implicit slot. Recursive include terminates: a nested spoiler (el.parent_id
  set) does NOT match this branch (falls to {% else %}), and the resolve_scope/loader
  depth guards forbid a container child, so the realized depth is exactly 2.
  {% endcomment %}
  <div class="el-row__spoiler">
    <ol class="element-list element-list--nested">
      {% for child in obj.resolved_children %}
        {% include "courses/manage/editor/_element_row.html" with el=child obj=child.content_object unit=unit open_form=open_form open_form_pk=open_form_pk %}
      {% empty %}
        {% if obj.body %}
          <li class="empty-state">{% trans "This spoiler shows saved text (edit it with the pencil). Add an element below to start nesting content." %}</li>
        {% else %}
          <li class="empty-state">{% trans "This spoiler is empty." %}</li>
        {% endif %}
      {% endfor %}
    </ol>
    {% include "courses/manage/editor/_add_menu.html" with nested=True in_spoiler=True parent=el.pk tab=obj.SLOT_ID %}
  </div>
</li>
```

**(b)** In `templates/courses/manage/editor/_add_menu.html`, gate the three disallowed surfaces on `in_spoiler`:

- `html` card (`_add_menu.html:20`): wrap in `{% if not in_spoiler %}...{% endif %}`:

```django
      {% if not in_spoiler %}<button type="button" class="typecard" data-add-type="html"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-html"/></svg>{% trans "HTML" %}</button>{% endif %}
```

- The Interactive group (`_add_menu.html:27-40`): change the opening guard from `{% if not unit_is_quiz %}` to `{% if not unit_is_quiz and not in_spoiler %}` (the whole Interactive group — which contains the `spoiler` card at `:35` and the stateful self-checks — is then hidden inside a spoiler).

- [ ] **Step 4: Run test to verify it passes**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest courses/tests/test_spoiler_nesting.py -v` and the authoring guard `courses/tests/test_switchgrid_authoring.py::test_switchgrid_card_in_nested_add_menu`
Expected: PASS — spoiler child list + add-menu render for a top-level spoiler; the spoiler menu omits `html`/`spoiler`/interactive cards; the Tabs nested menu STILL shows those cards (no PR #126 regression).

- [ ] **Step 5: Commit**

```bash
git add templates/courses/manage/editor/_element_row.html templates/courses/manage/editor/_add_menu.html courses/tests/test_spoiler_nesting.py
git commit -m "feat(editor): recursive spoiler editor row + in_spoiler add-menu (nestable-spoiler task 9)"
```

---

### Task 10: Integration — full suite, real import re-seed/reload, image-loss re-measure

Prove the feature end-to-end on the real corpus and confirm the image-loss count drops.

**Files:**
- No production code. Verification + memory update only.

- [ ] **Step 1: Run the full non-e2e suite**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -q`
Expected: green (or only pre-existing unrelated failures — triage per [[flaky-tests-separate-pr]] if any). Also run `uv run ruff format --check .` and `uv run ruff check .` (see [[uv-run-tooling]]).

- [ ] **Step 2: Re-seed a spoiler-heavy part and reload into `libli_mat`**

Re-seed the JSON for a part known to have `<details>`/reveal-table/show_solution spoilers with images (e.g. `030_kwadratowa` or `001_zbiory_liczbowe` — the 4 Venn diagrams the pilot missed), then reload:

```bash
SR="C:/Users/krzys/Documents/teaching/LAL/html"
uv run python -m scripts.lal_import.parser 030_kwadratowa --source-root "$SR" --force
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run python manage.py import_lal_content --course matematyka --part 030_kwadratowa \
  --source-root "$SR" --json-dir scripts/lal_import/out --allow-html
```

- [ ] **Step 3: Render-check live (DEBUG server) and hand the user URLs**

Start the server (DEBUG on, else no static/media):

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  DJANGO_DEBUG=True uv run python manage.py runserver 127.0.0.1:8000 --noreload
```

Log in as `pilot / pilot-pass-123`. Confirm a spoiler that previously lost images now renders images/tables behind the `<details>` toggle. **Hand the user the exact `/courses/matematyka/u/<id>/` URLs** for the reseeded units (find the ids from the import output) and ask them to confirm.

- [ ] **Step 4: Re-run the image-loss measure**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run python <scratchpad>/measure_lost_imgs.py` (the existing script). Expected: total lost `<img>` count drops materially from **640** (the spoiler-type bucket ~ details 103 + reveal-step 91 + question_text-in-spoiler share should now be recovered). Record the new number.

- [ ] **Step 5: Update the memory file + commit any final notes**

Update `matematyka-content-import-status.md`: mark nestable-spoiler SHIPPED with the commit range, the new image-loss number, and the remaining buckets (fill-table cell images; any residual). No code commit needed unless notes files changed.

---

## Self-Review

**1. Spec coverage** (each spec section → task):
- §1 Model & rendering (SLOT_ID, join_row, resolved_children, render, has_math) → Tasks 1, 2, 3.
- §2 Parser (3 emitters, no-nest-container mode, ks_tabs flatten) → Task 5.
- §3 Loader (dual-path, key-presence discriminator, label[:120], depth guard) → Task 4.
- §4 Builder editor (no `_CONTAINER_REGISTRY`, resolve_scope single-slot branch, no early return, allowlist, top-level guard, `_element_row` branch gated top-level, `in_spoiler` add-menu) → Tasks 7, 9.
- §5 Backward-compat & safety (opt-in by children, body-fate, template branch, form guard) → Tasks 3, 4, 8.
- §6 Transfer (walk_unit_joins branch, validate_nesting special-case with depth fall-through, serializers unchanged, no FORMAT_VERSION bump) → Task 6.
- §Error handling / §Testing / §Out of scope → covered by the per-task tests + Task 10.

**2. Placeholder scan:** every code step shows the actual code; test steps show real assertions. The Task 9 client tests carry an explicit implementer note to swap the inline `__import__` shim for the project's `client`/`make_pa` fixtures and to scope the card-hiding assertion — the behavioral contract is fully pinned.

**3. Type consistency:** `SpoilerElement.SLOT_ID` (`"only"`), `resolved_children()`, `join_row()`, `render(*, element, state, slug, node_pk)`, `SPOILER_CHILD_TYPES`, `_spoiler_has_math`, `_emit_solution_region`, `_flatten_tabs_inline`, and the `{type:"spoiler", label, elements}` dict shape are used identically across Tasks 1–9.
