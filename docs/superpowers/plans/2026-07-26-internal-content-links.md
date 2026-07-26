# Internal Content Links (Part 1: dialog + permalink) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a Course Admin insert links to other places in the same course from any rich-text toolbar, via one dialog that also finally gives external links an edit path.

**Architecture:** Links are stored as ordinary relative anchors (`<a href="/courses/n/1234/">`) — no sanitiser change, because `sanitize_html` already passes relative hrefs through untouched. A slug-free permalink view redirects to the unit page or to the outline anchored on the node. The dialog is a server-rendered `<trans>` partial (there is no JavaScriptCatalog in this repo) driven by two JS modules: `link_apply.js` owns every DOM mutation and is unit-testable in a real browser; `link_dialog.js` owns only its own dialog.

**Tech Stack:** Django templates, vanilla ES5-style JS (no build step), pytest + pytest-django, Playwright for e2e and as a JS runtime.

**Spec:** `docs/superpowers/specs/2026-07-26-internal-content-links-design.md`

## Global Constraints

- Run everything through `uv run` — bare `pytest`/`python`/`ruff` are not on PATH.
- `uv run pytest` defaults to `-m 'not e2e'`. Browser tests **must** carry `pytestmark = pytest.mark.e2e` and are run with `uv run pytest -m e2e`.
- Never hardcode a test password; use `tests.factories.TEST_PASSWORD`.
- Django templates: `{# #}` comments must be single-line; use `{% comment %}` for multi-line.
- All user-visible strings are `{% trans %}` in templates. Polish translations must be non-empty — `tests/test_i18n_po_health.py::test_pl_has_no_untranslated_msgid` fails on a blank msgstr.
- No JS test runner exists (no `package.json`, no jsdom). JS unit tests load a module with `page.add_script_tag` and call it via `page.evaluate`, following `tests/test_table_grid_algebra.py`.
- Every guard must be falsified before it is trusted: delete the behaviour it protects, confirm RED, restore. A test that has never failed is not evidence.
- The app is served from the domain root; `/courses/n/` may be used as a literal CSS prefix. Tests tie that literal to `reverse()`.

---

### Task 1: The permalink route and view

**Files:**
- Modify: `courses/urls.py` (add one path near the other `courses/` routes)
- Modify: `courses/views.py` (add `node_permalink`)
- Test: `tests/test_node_permalink.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: URL name `courses:node_permalink`, taking `node_pk` (int). Every later task reverses this name rather than building the path.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_node_permalink.py`:

```python
import pytest
from django.urls import resolve, reverse

from courses.models import ContentNode, Enrollment
from tests.factories import (
    ContentNodeFactory,
    CourseFactory,
    UserFactory,
    make_login,
    seed_roles,
)

pytestmark = pytest.mark.django_db


def _course_with_chapter():
    course = CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    return course, chapter, unit


def test_resolver_does_not_collide_with_course_slug():
    # /courses/n/12/ is three segments; courses/<slug>/ matches two. A course
    # slugged "n" must keep working.
    assert resolve("/courses/n/12/").view_name == "courses:node_permalink"
    assert resolve("/courses/n/").view_name == "courses:course_outline"


def test_lesson_unit_redirects_to_lesson_page(client):
    course, _chapter, unit = _course_with_chapter()
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


def test_quiz_unit_redirects_straight_to_quiz_in_one_hop(client):
    # Fixture pinned to NO submission: quiz_unit itself 302s to quiz_results for a
    # SUBMITTED submission, so a followed chain would fail for an unrelated reason.
    # Assert on the FIRST hop's Location.
    course = CourseFactory()
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": quiz.pk}))
    assert resp.status_code == 302
    assert resp["Location"] == reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )


def test_chapter_redirects_to_outline_with_fragment(client):
    course, chapter, _unit = _course_with_chapter()
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": chapter.pk}))
    assert resp.status_code == 302
    expected = (
        reverse("courses:course_outline", kwargs={"slug": course.slug})
        + f"#node-{chapter.pk}"
    )
    assert resp["Location"] == expected


def test_missing_node_is_404(client):
    make_login(client, "someone")
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": 999999}))
    assert resp.status_code == 404


def test_inaccessible_course_is_404_not_403(client):
    # 404-before-403, matching get_node_or_404's documented convention. A 403 here
    # would make this the one route that answers "does node N exist?" for any
    # logged-in user -- a node/course enumeration oracle.
    course, _chapter, unit = _course_with_chapter()
    make_login(client, "outsider")
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 404


def test_manager_who_is_not_an_accessor_gets_404(client):
    # Known, deliberate: can_manage_course (owner OR courses.change_course) and
    # can_access_course (staff OR owner OR enrolled OR teaches) are not nested. A PA
    # who is neither owner nor enrolled can author a link and then 404 on it. This is
    # pre-existing app-wide behaviour -- they cannot read ANY unit page -- pinned here
    # so it is a known behaviour rather than a surprise.
    from django.contrib.auth.models import Group as AuthGroup

    course, _chapter, unit = _course_with_chapter()
    seed_roles()
    user = make_login(client, "pa")
    user.groups.add(AuthGroup.objects.get(name="Platform Admin"))
    assert not user.is_staff
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 404


def test_anonymous_is_redirected_to_login(client):
    course, _chapter, unit = _course_with_chapter()
    resp = client.get(reverse("courses:node_permalink", kwargs={"node_pk": unit.pk}))
    assert resp.status_code == 302
    assert "/login" in resp["Location"] or "accounts" in resp["Location"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_node_permalink.py -q`
Expected: FAIL — `django.urls.exceptions.NoReverseMatch: Reverse for 'node_permalink' not found`.

- [ ] **Step 3: Add the route**

In `courses/urls.py`, immediately after the `courses/<slug:slug>/u/<int:node_pk>/` group (keep it with the other consumption routes):

```python
    path("courses/n/<int:node_pk>/", views.node_permalink, name="node_permalink"),
```

- [ ] **Step 4: Add the view**

In `courses/views.py`, next to `lesson_unit`. Check the existing imports at the top of the file — add `Http404` from `django.http` and `reverse` from `django.urls` only if they are not already imported.

```python
@login_required
def node_permalink(request, node_pk):
    """Slug-free permalink to any ContentNode.

    Stored links carry only a pk, so this survives a course being re-slugged and
    lets the redirect target change without touching a single stored body.

    404 -- NOT PermissionDenied -- for an inaccessible node. get_node_or_404's
    docstring states the convention: "a foreign node always 404s before any 403."
    Every other node-addressed view scopes by slug first; this one has no slug, so
    returning 403 would make it an existence oracle for every node in the install.
    """
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if not can_access_course(request.user, node.course):
        raise Http404("node is not accessible")
    if node.kind == ContentNode.Kind.UNIT:
        # Branch explicitly rather than letting lesson_unit forward a quiz: that
        # would cost a second redirect hop on every quiz link and couple this view
        # to another's implementation detail.
        name = (
            "courses:quiz_unit"
            if node.unit_type == ContentNode.UnitType.QUIZ
            else "courses:lesson_unit"
        )
        return redirect(name, slug=node.course.slug, node_pk=node.pk)
    return redirect(
        reverse("courses:course_outline", kwargs={"slug": node.course.slug})
        + f"#node-{node.pk}"
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_node_permalink.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Falsify the 404-not-403 guard**

Temporarily change `raise Http404(...)` to `raise PermissionDenied`. Run
`uv run pytest tests/test_node_permalink.py -q`. Expected: `test_inaccessible_course_is_404_not_403` and `test_manager_who_is_not_an_accessor_gets_404` FAIL. Restore the `Http404`.

- [ ] **Step 7: Commit**

```bash
git add courses/urls.py courses/views.py tests/test_node_permalink.py
git commit -m "feat(links): slug-free /courses/n/<pk>/ permalink view"
```

---

### Task 2: Outline anchors and the :target highlight

**Files:**
- Modify: `templates/courses/_outline_node.html` (the `<li>` open tag, both branches share it)
- Modify: `core/static/core/css/app.css` (next to the existing `.outline-*` rules, ~line 487-549)
- Test: `tests/test_outline_anchors.py` (create)

**Interfaces:**
- Consumes: `courses:node_permalink` from Task 1 (its chapter branch emits `#node-<pk>`).
- Produces: `id="node-<pk>"` on every outline `<li>`; CSS classes `.outline-node:target > .outline-node__head` and `.outline-node:target > .outline-unit`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outline_anchors.py`:

```python
from pathlib import Path

import pytest
from django.urls import reverse

from courses.models import Enrollment
from tests.factories import ContentNodeFactory, CourseFactory, make_login

pytestmark = pytest.mark.django_db

APP_CSS = (
    Path(__file__).resolve().parent.parent
    / "core"
    / "static"
    / "core"
    / "css"
    / "app.css"
)


def test_outline_rows_carry_a_node_id(client):
    course = CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U"
    )
    user = make_login(client, "student")
    Enrollment.objects.create(student=user, course=course)
    html = client.get(
        reverse("courses:course_outline", kwargs={"slug": course.slug})
    ).content.decode()
    assert f'id="node-{chapter.pk}"' in html
    assert f'id="node-{unit.pk}"' in html


def test_target_highlight_is_scoped_to_the_row_not_the_li():
    # A non-unit <li> contains the nested <ul> of every descendant, so a bare
    # `li:target { background: ... }` would tint a whole part's subtree. The id goes
    # on the <li> (it is the scroll target); the highlight goes on the row inside it.
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".outline-node:target > .outline-node__head" in css
    assert ".outline-node:target > .outline-unit" in css
    assert "\n.outline-node:target {" not in css, "highlight must not target the <li>"


def test_outline_li_has_scroll_margin():
    css = APP_CSS.read_text(encoding="utf-8")
    assert "scroll-margin-top" in css
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_outline_anchors.py -q`
Expected: FAIL — no `id="node-` in the rendered outline.

- [ ] **Step 3: Add the id to the template**

In `templates/courses/_outline_node.html`, the `<li>` open tag currently reads:

```html
<li class="outline-node outline-node--{{ item.node.kind }}"{% if item.tag_hidden %} hidden{% endif %}
```

Add the id (uniformly for every kind — the `<li>` is shared markup and an `{% if %}` around an `id` earns nothing):

```html
<li class="outline-node outline-node--{{ item.node.kind }}" id="node-{{ item.node.pk }}"{% if item.tag_hidden %} hidden{% endif %}
```

- [ ] **Step 4: Add the CSS**

In `core/static/core/css/app.css`, immediately after the existing `.outline-unit` rules. **This must be `app.css`, not `courses.css`** — `outline.html` never links `courses.css` (its `extra_css` block adds only `notes.css` and `tags.css`), so a rule there would be dead on the only page that can ever be a `:target`.

```css
/* Internal-link landing cue. The id lives on the <li> (the scroll target) but the
   highlight must not: a non-unit <li> contains its whole descendant subtree, so
   `li:target` would tint most of the page. The two branches of _outline_node.html
   render different row elements, hence two selectors.
   scroll-margin-top is for breathing room, NOT sticky chrome -- .app-header is
   position: relative and .outline sits in the normal .app-main flow. */
.outline-node { scroll-margin-top: var(--space-4); }
.outline-node:target > .outline-node__head,
.outline-node:target > .outline-unit {
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  box-shadow: 0 0 0 2px var(--primary);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_outline_anchors.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Check both themes**

Start the app (`uv run python manage.py runserver`), open a course outline with `#node-<pk>` for a chapter, and screenshot in light and dark. Judge dark separately — do not infer it from light. If the highlight is illegible in either, adjust the two custom properties above and re-check.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/_outline_node.html core/static/core/css/app.css tests/test_outline_anchors.py
git commit -m "feat(links): per-node outline anchors + :target highlight"
```

---

### Task 3: The picker endpoint and its two partials

**Files:**
- Modify: `courses/urls.py`, `courses/views_manage.py`
- Create: `templates/courses/manage/editor/_link_picker.html`
- Create: `templates/courses/manage/editor/_link_picker_node.html`
- Test: `tests/test_link_picker.py` (create)

**Interfaces:**
- Consumes: `courses:node_permalink` (Task 1).
- Produces: URL name `courses:manage_link_picker` taking `slug`. Response is a bare `<ol class="link-picker__scope" role="tree">` whose rows are `<li class="link-picker__item" role="treeitem">` carrying `data-node`, `data-title`, `data-href`, `aria-level`, `aria-selected="false"`, `tabindex="-1"`. Task 6 reads exactly these attributes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_picker.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory, CourseFactory, make_login

pytestmark = pytest.mark.django_db


def _tree(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="Algebra")
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part, title="Quadratics"
    )
    lesson = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="Vertex"
    )
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=chapter, title="Practice"
    )
    return course, part, chapter, lesson, quiz


def test_picker_lists_every_node_for_a_manager(client):
    course, part, chapter, lesson, quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    for node in (part, chapter, lesson, quiz):
        assert f'data-node="{node.pk}"' in html


def test_row_href_equals_reverse(client):
    # The route name is the single source of the URL shape for the JS path. A route
    # rename must fail here, not silently invalidate every future link.
    course, _part, _chapter, lesson, _quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    expected = reverse("courses:node_permalink", kwargs={"node_pk": lesson.pk})
    assert f'data-href="{expected}"' in html


def test_unit_rows_distinguish_lesson_from_quiz(client):
    # The permalink sends a lesson and a quiz to DIFFERENT pages, so an author
    # choosing a target must be able to tell them apart. Mirrors _tree_node.html.
    course, _part, _chapter, _lesson, _quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    assert "tree__badge--lesson" in html
    assert "tree__badge--quiz" in html


def test_rows_are_treeitems_owning_their_children(client):
    # The <li> must BE the treeitem: with role="none" on the <li>, each role="group"
    # becomes a SIBLING of the item it belongs to, so no item owns any subtree and
    # the nesting is not conveyed at all.
    course, _part, _chapter, _lesson, _quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    assert 'role="tree"' in html
    assert 'role="treeitem"' in html
    assert 'aria-level="1"' in html
    assert 'aria-level="2"' in html
    # ownership: the group must open INSIDE an item, i.e. after a treeitem <li> and
    # before its closing tag.
    item_start = html.index('role="treeitem"')
    group_start = html.index('role="group"')
    assert group_start > item_start


def test_response_is_a_bare_partial(client):
    course, *_ = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    assert "<html" not in html.lower()


def test_non_manager_gets_403(client):
    course = CourseFactory()
    make_login(client, "outsider")
    resp = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    )
    assert resp.status_code == 403


def test_unknown_slug_is_404(client):
    make_login(client, "someone")
    resp = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": "no-such-course"})
    )
    assert resp.status_code == 404


def test_query_count_is_flat_in_tree_size(client, django_assert_num_queries):
    # _children_map is ONE query and must stay one -- the point is that a regression
    # to one query per row goes red. assertNumQueries(1) would simply be wrong: the
    # view also runs auth/session lookups, resolves the course and checks the perm.
    course, *_ = _tree(client)
    for i in range(10):
        ContentNodeFactory(course=course, kind="part", parent=None, title=f"P{i}")
    url = reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    client.get(url)  # warm any session/auth caching
    with django_assert_num_queries(4):
        # 1 session, 1 user, 1 course lookup (+perm), 1 _children_map
        client.get(url)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_link_picker.py -q`
Expected: FAIL — `NoReverseMatch` for `manage_link_picker`.

- [ ] **Step 3: Add the route and view**

In `courses/urls.py`, beside the other `manage/courses/<slug:slug>/` routes:

```python
    path(
        "manage/courses/<slug:slug>/link-picker/",
        views_manage.link_picker,
        name="manage_link_picker",
    ),
```

In `courses/views_manage.py`, next to `builder` (which already uses `_children_map`):

```python
@login_required
def link_picker(request, slug):
    """The course tree, as a bare partial, for the rich-text link dialog.

    Rendered standalone (no base.html) because the dialog fetches it and injects the
    markup directly. Like `builder`, passes children_map PLUS top_nodes: _children_map
    keys roots under None, which a template cannot index.
    """
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    cmap = _children_map(course)
    return render(
        request,
        "courses/manage/editor/_link_picker.html",
        {"course": course, "children_map": cmap, "top_nodes": cmap.get(None, [])},
    )
```

- [ ] **Step 4: Create the root partial**

`templates/courses/manage/editor/_link_picker.html` — seeds `level=1`. Django's `add` filter returns `""` for a non-numeric input, so a missing `level` would render *every* `aria-level` empty at every depth:

```html
{% load courses_manage_extras %}
<ol class="link-picker__scope" role="tree">
  {% for node in top_nodes %}
    {% include "courses/manage/editor/_link_picker_node.html" with n=node children_map=children_map level=1 %}
  {% endfor %}
</ol>
```

- [ ] **Step 5: Create the row partial**

`templates/courses/manage/editor/_link_picker_node.html`. Note it includes **itself**, rebinding `n=child` and re-passing `children_map` — omit the rebind and you get infinite recursion on the same node:

```html
{% load i18n courses_manage_extras %}
{% comment %}One picker row. The <li> IS the treeitem so that its children's
<ol role="group"> sits INSIDE it -- with role="none" on the li, each group would be a
sibling of the item it belongs to and no item would own a subtree. The row is not a
<button>: role="treeitem" overrides button semantics anyway, and link_dialog.js
implements Enter/Space and roving tabindex by hand. What matters is that it is
focusable and keyboard-operable.{% endcomment %}
<li class="link-picker__item" role="treeitem"
    aria-level="{{ level }}" aria-selected="false" tabindex="-1"
    data-node="{{ n.pk }}" data-title="{{ n.title }}"
    data-href="{% url 'courses:node_permalink' node_pk=n.pk %}">
  <span class="link-picker__row">
    {% if n.kind == "unit" %}
      {% if n.unit_type == "quiz" %}
        <span class="tree__badge tree__badge--unit tree__badge--quiz" title="{{ n.get_unit_type_display }}">Q</span>
      {% else %}
        <span class="tree__badge tree__badge--unit tree__badge--lesson" title="{{ n.get_unit_type_display }}">L</span>
      {% endif %}
    {% else %}
      <span class="tree__badge tree__badge--{{ n.kind }}">{{ n.get_kind_display }}</span>
    {% endif %}
    <span class="link-picker__title">{{ n.title }}</span>
  </span>
  {% with children=children_map|get_item:n.pk %}
    {% if children %}
      <ol class="link-picker__scope" role="group">
        {% for child in children %}
          {% include "courses/manage/editor/_link_picker_node.html" with n=child children_map=children_map level=level|add:1 %}
        {% endfor %}
      </ol>
    {% endif %}
  {% endwith %}
</li>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_link_picker.py -q`
Expected: PASS (8 tests). If the query-count test fails with a different number, read the reported count, confirm each query is one of the four named in the comment, and update the number — do **not** simply record whatever the first run printed.

- [ ] **Step 7: Falsify the href guard**

Temporarily change `data-href="{% url 'courses:node_permalink' node_pk=n.pk %}"` to a hand-built `data-href="/courses/n/{{ n.pk }}/"`. The test still passes (the strings match), which is expected — now rename the route in `urls.py` to `node_permalink2` and confirm `test_row_href_equals_reverse` FAILS for the `{% url %}` version but PASSES for the hardcoded one. Restore both.

- [ ] **Step 8: Commit**

```bash
git add courses/urls.py courses/views_manage.py templates/courses/manage/editor/_link_picker.html templates/courses/manage/editor/_link_picker_node.html tests/test_link_picker.py
git commit -m "feat(links): link-picker endpoint serving the course tree"
```

---

### Task 4: `link_apply.js` — anchor enumeration, insertion rules, URL contract

**Files:**
- Create: `courses/static/courses/js/link_apply.js`
- Test: `tests/test_link_apply.py` (create, `pytestmark = pytest.mark.e2e`)

**Interfaces:**
- Consumes: nothing (pure DOM + string logic).
- Produces: `window.libliLinkApply` with exactly four functions:
  - `anchorsFor(surface, range) -> Array<HTMLAnchorElement>`
  - `enclosing(surface, range) -> HTMLAnchorElement | null`
  - `apply(surface, range, result) -> void` where `result` is `{href, text}` or `{remove: true}`
  - `normalizeUrl(input, origin) -> {href: string} | {reject: string}`

  Task 7 calls all four. `normalizeUrl`'s `reject` value is a message **key**, one of `"scheme"`, `"protocol-relative"`, `"relative"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_apply.py`. This uses Playwright as a JS runtime, following `tests/test_table_grid_algebra.py` — there is no jsdom in this repo. The file **must** carry the e2e marker or it lands in the unit job where no browser is installed:

```python
"""Unit tests for link_apply.js, run in a real browser.

There is no jsdom here (no package.json, no vitest/jest). The repo's one precedent for
unit-testing a JS module is Playwright as a JS runtime: add_script_tag the module into a
blank page and call its exports via evaluate. That is WHY the mutation logic lives in
link_apply.js rather than inside text_toolbar.js's IIFE -- logic private to that closure
would only be reachable by driving the whole editor.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

MODULE = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "js"
    / "link_apply.js"
)


@pytest.fixture
def page_with_module(page):
    page.set_content("<div id='s' contenteditable='true'></div>")
    page.add_script_tag(path=str(MODULE))
    return page


def _apply(page, html, build_range_js, result):
    """Set the surface's HTML, build a Range with build_range_js, apply, return HTML."""
    return page.evaluate(
        """([html, buildRange, result]) => {
            const s = document.getElementById('s');
            s.innerHTML = html;
            const range = (new Function('s', 'return (' + buildRange + ')(s)'))(s);
            window.libliLinkApply.apply(s, range, result);
            return s.innerHTML;
        }""",
        [html, build_range_js, result],
    )


# ---- URL contract: an ORDERED table, first match wins ----------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("//evil.com/x", {"reject": "protocol-relative"}),
        ("https://example.test/courses/n/12/", {"href": "/courses/n/12/"}),
        ("javascript:alert(1)", {"reject": "scheme"}),
        ("ftp://x.test/f", {"reject": "scheme"}),
        ("https://ok.test/a", {"href": "https://ok.test/a"}),
        ("mailto:a@b.test", {"href": "mailto:a@b.test"}),
        ("example.com", {"href": "https://example.com"}),
        ("example.com:8080/x", {"href": "https://example.com:8080/x"}),
        ("../foo", {"reject": "relative"}),
        ("/path", {"reject": "relative"}),
        ("#section", {"reject": "relative"}),
        ("example", {"reject": "relative"}),
    ],
)
def test_normalize_url(page_with_module, value, expected):
    got = page_with_module.evaluate(
        "([v, o]) => window.libliLinkApply.normalizeUrl(v, o)",
        [value, "https://example.test"],
    )
    assert got == expected


def test_permalink_on_a_different_origin_is_not_normalised(page_with_module):
    # Row 2 compares location.origin EXACTLY (scheme + host + port).
    got = page_with_module.evaluate(
        "([v, o]) => window.libliLinkApply.normalizeUrl(v, o)",
        ["https://other.test/courses/n/12/", "https://example.test"],
    )
    assert got == {"href": "https://other.test/courses/n/12/"}


def test_permalink_with_query_suffix_is_an_ordinary_url(page_with_module):
    got = page_with_module.evaluate(
        "([v, o]) => window.libliLinkApply.normalizeUrl(v, o)",
        ["https://example.test/courses/n/12/?x=1", "https://example.test"],
    )
    assert got == {"href": "https://example.test/courses/n/12/?x=1"}


# ---- anchor enumeration ----------------------------------------------------

SELECT_ALL = "(s) => { const r = document.createRange(); r.selectNodeContents(s); return r; }"
CARET_IN_FIRST_LINK = """
(s) => { const a = s.querySelector('a'); const r = document.createRange();
         r.setStart(a.firstChild, 1); r.collapse(true); return r; }
"""


def test_touched_anchors_spans_links_wholly_inside_the_range(page_with_module):
    # closest() from the boundaries is NOT enough: with the selection starting in plain
    # text before link A and ending after link B, both boundary walks return null, so
    # Remove link would be disabled and rule 2 would unwrap nothing.
    n = page_with_module.evaluate(
        """(build) => {
            const s = document.getElementById('s');
            s.innerHTML = 'x <a href="/a/">A</a> y <a href="/b/">B</a> z';
            const r = (new Function('s', 'return (' + build + ')(s)'))(s);
            return window.libliLinkApply.anchorsFor(s, r).length;
        }""",
        SELECT_ALL,
    )
    assert n == 2


def test_collapsed_caret_inside_a_link_counts_one(page_with_module):
    # intersectsNode reports true for merely ADJACENT nodes in some engines, so the
    # collapsed case is decided by the enclosing predicate alone.
    n = page_with_module.evaluate(
        """(build) => {
            const s = document.getElementById('s');
            s.innerHTML = 'x <a href="/a/">A</a> y';
            const r = (new Function('s', 'return (' + build + ')(s)'))(s);
            return window.libliLinkApply.anchorsFor(s, r).length;
        }""",
        CARET_IN_FIRST_LINK,
    )
    assert n == 1


def test_collapsed_caret_outside_any_link_counts_zero(page_with_module):
    n = page_with_module.evaluate(
        """() => {
            const s = document.getElementById('s');
            s.innerHTML = 'plain text';
            const r = document.createRange();
            r.setStart(s.firstChild, 2); r.collapse(true);
            return window.libliLinkApply.anchorsFor(s, r).length;
        }"""
    )
    assert n == 0


# ---- insertion rules: ordered, first match wins, total over ranges ---------


def test_rule1_selection_coextensive_with_a_link_edits_it(page_with_module):
    # The most common re-link gesture (double-click a one-word link). A "strictly
    # inside" reading would leave this matching NO rule.
    out = _apply(
        page_with_module,
        '<a href="/old/">Word</a>',
        "(s) => { const r = document.createRange(); r.selectNodeContents(s.querySelector('a')); return r; }",
        {"href": "/courses/n/9/", "text": "Word"},
    )
    assert out.count("<a") == 1
    assert 'href="/courses/n/9/"' in out


def test_rule1_unmodified_text_preserves_inline_markup(page_with_module):
    out = _apply(
        page_with_module,
        '<a href="/old/">the <b>vertex</b> unit</a>',
        CARET_IN_FIRST_LINK,
        {"href": "/courses/n/9/", "text": "the vertex unit"},
    )
    assert "<b>vertex</b>" in out
    assert 'href="/courses/n/9/"' in out


def test_rule1_edited_text_replaces_contents(page_with_module):
    out = _apply(
        page_with_module,
        '<a href="/old/">the <b>vertex</b> unit</a>',
        CARET_IN_FIRST_LINK,
        {"href": "/courses/n/9/", "text": "new label"},
    )
    assert "<b>" not in out
    assert "new label" in out


def test_rule2_selection_starting_at_an_anchors_first_character(page_with_module):
    # The marker-node ordering case: a boundary container that IS the anchor would be
    # detached by the unwrap, leaving the range pointing at nothing.
    out = _apply(
        page_with_module,
        '<a href="/a/">AB</a>CD',
        """(s) => { const a = s.querySelector('a'); const r = document.createRange();
                   r.setStart(a.firstChild, 0); r.setEnd(s.lastChild, 2); return r; }""",
        {"href": "/courses/n/9/", "text": "linked"},
    )
    assert out.count("<a") == 1
    assert 'href="/courses/n/9/"' in out


def test_rule2_overlap_unlinks_the_unselected_remainder(page_with_module):
    # Stated loss: a selection covering the tail of A and the head of B leaves BOTH
    # fully unlinked, including the parts never selected. The alternative (splitting
    # A and B) would produce three anchors from one gesture.
    out = _apply(
        page_with_module,
        '<a href="/a/">AAA</a> mid <a href="/b/">BBB</a>',
        """(s) => { const as = s.querySelectorAll('a'); const r = document.createRange();
                   r.setStart(as[0].firstChild, 2); r.setEnd(as[1].firstChild, 1); return r; }""",
        {"href": "/courses/n/9/", "text": "L"},
    )
    assert out.count("<a") == 1
    assert "/a/" not in out and "/b/" not in out


def test_rule3_collapsed_caret_inserts_a_new_anchor(page_with_module):
    out = _apply(
        page_with_module,
        "plain",
        "(s) => { const r = document.createRange(); r.setStart(s.firstChild, 5); r.collapse(true); return r; }",
        {"href": "/courses/n/9/", "text": "New"},
    )
    assert 'href="/courses/n/9/"' in out
    assert ">New<" in out


def test_remove_unwraps_all_touched_anchors(page_with_module):
    out = _apply(
        page_with_module,
        'x <a href="/a/">A</a> y <a href="/b/">B</a> z',
        SELECT_ALL,
        {"remove": True},
    )
    assert "<a" not in out
    assert "A" in out and "B" in out


def test_link_text_is_written_as_a_text_node(page_with_module):
    # Node titles are author-supplied and may contain markup characters.
    out = _apply(
        page_with_module,
        "plain",
        "(s) => { const r = document.createRange(); r.setStart(s.firstChild, 5); r.collapse(true); return r; }",
        {"href": "/courses/n/9/", "text": "<b>bold</b>"},
    )
    assert "&lt;b&gt;bold&lt;/b&gt;" in out
    assert "<b>bold</b>" not in out


# ---- the attribute-aware scanner ------------------------------------------


def test_raw_gt_inside_an_anchor_attribute_is_handled_correctly(page_with_module):
    # MEASURED: nh3 does NOT escape > inside attribute values, and `title` is an
    # allowed <a> attribute. A naive <a[^>]*> matches `<a title="a >` -- a
    # syntactically CLEAN match of the wrong span -- so the href falls outside it and
    # the link is silently neither rewritten nor counted. Assert the rewrite, not the
    # absence of damage: a "byte-identical" assertion passes the broken version.
    for html in (
        '<a title="a > b" href="/old/">W</a>',
        '<a href="/old/" title="a > b">W</a>',
    ):
        out = _apply(
            page_with_module,
            html,
            "(s) => { const r = document.createRange(); r.selectNodeContents(s.querySelector('a')); return r; }",
            {"href": "/courses/n/9/", "text": "W"},
        )
        assert 'href="/courses/n/9/"' in out, html
        assert "/old/" not in out, html
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_link_apply.py -m e2e -q`
Expected: FAIL — `link_apply.js` does not exist, so `add_script_tag` errors.

- [ ] **Step 3: Write the module**

Create `courses/static/courses/js/link_apply.js`:

```js
(function () {
  "use strict";

  // Pure DOM + string logic for internal/external links. Deliberately separate from
  // link_dialog.js and text_toolbar.js so it can be loaded into a blank page and
  // unit-tested (see tests/test_link_apply.py) -- logic inside text_toolbar.js's
  // IIFE would only be reachable by driving the whole editor.

  var PERMALINK = /^\/courses\/n\/(\d+)\/$/;   // anchored: must match the dialog

  // ---- URL contract: an ORDERED table, first match wins ---------------------
  // Order is load-bearing. An absolute same-origin permalink satisfies BOTH the
  // normalisation row and the scheme-allowlist row; evaluating the allowlist first
  // would accept it verbatim and then trip the outbound-marker misclassification the
  // normalisation exists to prevent.
  function normalizeUrl(input, origin) {
    var v = (input || "").trim();
    if (!v) return { reject: "relative" };

    // 1. protocol-relative: an off-site link wearing a relative disguise. It survives
    //    the sanitiser untouched and matches NEITHER student-side selector, so it
    //    would render with no marker at all.
    if (v.indexOf("//") === 0) return { reject: "protocol-relative" };

    // 2. absolute same-origin permalink -> relative form
    if (origin && v.indexOf(origin + "/") === 0) {
      var rest = v.slice(origin.length);
      if (PERMALINK.test(rest)) return { href: rest };
    }

    // 3. has a scheme? Only when the leading token has NO dot -- `example.com:8080/x`
    //    is a syntactically valid scheme token but is really a host:port.
    var m = /^([A-Za-z][A-Za-z0-9+.-]*):/.exec(v);
    if (m && m[1].indexOf(".") === -1) {
      var scheme = m[1].toLowerCase();
      if (scheme === "http" || scheme === "https" || scheme === "mailto") {
        return { href: v };
      }
      return { reject: "scheme" };
    }

    // 4. bare host: first segment contains a dot, no whitespace, no leading / or .
    if (v.charAt(0) !== "/" && v.charAt(0) !== "." && !/\s/.test(v)) {
      var first = v.split("/")[0];
      if (first.indexOf(".") !== -1) return { href: "https://" + v };
    }

    // 5. catch-all -- the table is TOTAL over input strings.
    return { reject: "relative" };
  }

  // ---- anchor enumeration ---------------------------------------------------
  function elementOf(node) {
    // Range.startContainer is usually a TEXT node, which has no closest().
    return node && node.nodeType === 3 ? node.parentNode : node;
  }

  function enclosing(surface, range) {
    // An anchor ENCLOSES a range when BOTH boundary points are within it. Covers a
    // caret inside a link and a selection exactly coextensive with its text. Anchors
    // never nest, so at most one can enclose. A caret at a leading/trailing text
    // boundary counts as enclosed -- deliberately: clicking just after a link's last
    // character means "edit this link", matching how typing there behaves.
    var start = elementOf(range.startContainer);
    var a = start && start.closest ? start.closest("a") : null;
    if (!a || !surface.contains(a)) return null;
    return a.contains(range.endContainer) ? a : null;
  }

  function anchorsFor(surface, range) {
    var enc = enclosing(surface, range);
    if (range.collapsed) return enc ? [enc] : [];
    var out = [];
    var all = surface.querySelectorAll("a");
    for (var i = 0; i < all.length; i++) {
      if (range.intersectsNode(all[i])) out.push(all[i]);
    }
    if (enc && out.indexOf(enc) === -1) out.push(enc);
    return out;
  }

  // ---- mutation -------------------------------------------------------------
  function textNode(s) { return document.createTextNode(s == null ? "" : String(s)); }

  function unwrap(a) {
    var parent = a.parentNode;
    while (a.firstChild) parent.insertBefore(a.firstChild, a);
    parent.removeChild(a);
  }

  function makeAnchor(href, text) {
    var a = document.createElement("a");
    a.setAttribute("href", href);
    a.appendChild(textNode(text));
    return a;
  }

  function collapseAfter(node) {
    var sel = window.getSelection();
    var r = document.createRange();
    r.setStartAfter(node);
    r.collapse(true);
    sel.removeAllRanges();
    sel.addRange(r);
  }

  function apply(surface, range, result) {
    var touched = anchorsFor(surface, range);

    if (result && result.remove) {
      // No deleteContents here: the recovered text is exactly what this preserves.
      var last = null;
      for (var i = 0; i < touched.length; i++) { last = touched[i].previousSibling || touched[i].parentNode; unwrap(touched[i]); }
      surface.normalize();
      if (last) collapseAfter(last);
      return;
    }

    var enc = enclosing(surface, range);
    if (enc) {
      // Rule 1: edit in place. If the text came back byte-identical to the anchor's
      // own textContent, touch only the href so inline <b>/<em>/math survives an
      // author who only wanted to fix the URL.
      enc.setAttribute("href", result.href);
      if (result.text !== enc.textContent) {
        while (enc.firstChild) enc.removeChild(enc.firstChild);
        enc.appendChild(textNode(result.text));
      }
      collapseAfter(enc);
      return;
    }

    if (!range.collapsed) {
      // Rule 2. Marker nodes first: unwrapping removes the element a boundary
      // container may BE, leaving the range pointing at a detached node so the
      // following deleteContents()/insertNode() would misbehave or throw.
      var startMark = textNode("");
      var endMark = textNode("");
      var r2 = range.cloneRange();
      r2.collapse(false);
      r2.insertNode(endMark);
      var r1 = range.cloneRange();
      r1.collapse(true);
      r1.insertNode(startMark);

      for (var j = 0; j < touched.length; j++) unwrap(touched[j]);

      var work = document.createRange();
      work.setStartAfter(startMark);   // after/before, so removing the markers
      work.setEndBefore(endMark);      // cannot shift the boundaries
      work.deleteContents();
      var anchor = makeAnchor(result.href, result.text);
      work.insertNode(anchor);
      if (startMark.parentNode) startMark.parentNode.removeChild(startMark);
      if (endMark.parentNode) endMark.parentNode.removeChild(endMark);
      surface.normalize();            // last: markers would block the merge
      collapseAfter(anchor);
      return;
    }

    // Rule 3.
    var fresh = makeAnchor(result.href, result.text);
    range.insertNode(fresh);
    surface.normalize();
    collapseAfter(fresh);
  }

  window.libliLinkApply = {
    anchorsFor: anchorsFor,
    enclosing: enclosing,
    apply: apply,
    normalizeUrl: normalizeUrl
  };
})();
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_link_apply.py -m e2e -q`
Expected: PASS. `-m e2e` is mandatory — without it pytest deselects everything and exits 5.

- [ ] **Step 5: Falsify the rule-1 markup-preservation guard**

Temporarily delete the `if (result.text !== enc.textContent)` condition so the contents are always replaced. Run the tests. Expected: `test_rule1_unmodified_text_preserves_inline_markup` FAILS. Restore it.

- [ ] **Step 6: Falsify the attribute-aware claim**

Temporarily reimplement `anchorsFor` using a naive `surface.innerHTML.match(/<a[^>]*>/g)`-style scan. Confirm `test_raw_gt_inside_an_anchor_attribute_is_handled_correctly` FAILS for the `title`-first case. Restore.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/link_apply.js tests/test_link_apply.py
git commit -m "feat(links): link_apply.js — anchor rules + total URL contract"
```

---

### Task 5: The dialog partial, editor wiring, and editor CSS

**Files:**
- Create: `templates/courses/manage/editor/_link_dialog.html`
- Modify: `templates/courses/manage/editor/editor.html` (include + two script tags)
- Modify: `courses/static/courses/css/editor.css`
- Test: `tests/test_editor_styles.py` (extend), `tests/test_link_dialog_markup.py` (create)

**Interfaces:**
- Consumes: `courses:manage_link_picker` (Task 3).
- Produces: `<dialog class="link-dialog" data-link-picker-url="...">` in the editor page, outside every `[data-scope]`; CSS classes `.link-dialog*`, `.link-picker__*`, and duplicated `.tree__badge*`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_dialog_markup.py`:

```python
from pathlib import Path

import pytest
from django.urls import reverse

from tests.factories import CourseFactory, ContentNodeFactory, make_login

pytestmark = pytest.mark.django_db

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
EDITOR_HTML = TEMPLATES / "courses" / "manage" / "editor" / "editor.html"


def _editor(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode(), course


def test_dialog_is_rendered_with_the_picker_url(client):
    html, course = _editor(client)
    assert 'class="link-dialog"' in html
    assert reverse("courses:manage_link_picker", kwargs={"slug": course.slug}) in html


def test_dialog_include_is_outside_every_data_scope():
    # editor.js REPLACES the [data-scope] panes and re-runs libliInitRte. Dropped
    # inside one, the <dialog> and every listener bound to it at load are destroyed on
    # the first save -- an intermittent dead toolbar button that is painful to
    # attribute. Assert the invariant, not a line number.
    src = EDITOR_HTML.read_text(encoding="utf-8")
    include_at = src.index("_link_dialog.html")
    scope_include_at = src.index("_editor_scope.html")
    assert include_at > scope_include_at, "dialog must come after the swapped scope"


def test_editor_loads_both_js_modules(client):
    html, _course = _editor(client)
    assert "link_apply.js" in html
    assert "link_dialog.js" in html


def test_dialog_buttons_are_type_button(client):
    # editor.html is full of forms; a form-associated bare <button> defaults to
    # type="submit", so Insert would POST the element form.
    html, _course = _editor(client)
    start = html.index('class="link-dialog"')
    end = html.index("</dialog>", start)
    block = html[start:end]
    assert "<button" in block
    assert block.count("<button") == block.count('type="button"')
```

Append to `tests/test_editor_styles.py`:

```python
BUILDER_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "builder.css"
)
EDITOR_HTML = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "courses"
    / "manage"
    / "editor"
    / "editor.html"
)


def test_editor_page_links_no_builder_css():
    # The badge rules are DUPLICATED into editor.css precisely because this page does
    # not load builder.css. That constraint was previously only prose in this module's
    # docstring -- adding builder.css to the editor page would have kept the suite
    # green. Now it cannot.
    assert "builder.css" not in EDITOR_HTML.read_text(encoding="utf-8")


def test_editor_css_defines_every_class_the_link_ui_uses():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    for cls in (
        ".link-dialog",
        ".link-picker__scope",
        ".link-picker__item",
        ".link-picker__row",
        ".tree__badge",
    ):
        assert cls in css, f"editor.css must style {cls}"


def test_duplicated_badge_rules_match_their_twin():
    # A class-name substring check cannot catch what this duplication actually risks:
    # the two copies drifting. Compare declarations.
    import re

    def decls(text, selector):
        m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text)
        assert m, f"{selector} not found"
        return {d.strip() for d in m.group(1).split(";") if d.strip()}

    editor = EDITOR_CSS.read_text(encoding="utf-8")
    builder = BUILDER_CSS.read_text(encoding="utf-8")
    assert decls(editor, ".tree__badge") == decls(builder, ".tree__badge")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_link_dialog_markup.py tests/test_editor_styles.py -q`
Expected: FAIL — no `link-dialog` in the editor page.

- [ ] **Step 3: Create the dialog partial**

`templates/courses/manage/editor/_link_dialog.html`. Every string is `{% trans %}` — the repo has **no** `JavaScriptCatalog` route, so `makemessages` cannot extract a string that lives only in a `.js` file:

```html
{% load i18n %}
{% comment %}Server-rendered so makemessages can see every string. The JS only wires
behaviour to this markup. The content lives in an inner wrapper and the <dialog>
carries no padding, so a click whose target IS the dialog means the backdrop and
nothing else -- see the dismissal handler in link_dialog.js.{% endcomment %}
<dialog class="link-dialog" aria-labelledby="link-dialog-title"
        data-link-picker-url="{% url 'courses:manage_link_picker' slug=course.slug %}">
  <div class="link-dialog__card">
    <h2 class="link-dialog__title" id="link-dialog-title">{% trans "Insert link" %}</h2>

    <div class="picker__tabs" role="tablist">
      <button type="button" class="picker__tab is-on" role="tab" aria-selected="true"
              id="link-tab-node" aria-controls="link-panel-node" data-tab="node">{% trans "In this course" %}</button>
      <button type="button" class="picker__tab" role="tab" aria-selected="false"
              id="link-tab-url" aria-controls="link-panel-url" data-tab="url">{% trans "Web address" %}</button>
    </div>

    <div class="picker__panel" role="tabpanel" id="link-panel-node"
         aria-labelledby="link-tab-node" data-panel="node">
      <label class="search">
        <input type="search" class="input" data-link-filter
               placeholder="{% trans 'Filter by title…' %}">
      </label>
      <div class="link-picker__mount" data-link-tree
           aria-label="{% trans 'Course content' %}"></div>
      <p class="link-dialog__msg" data-msg="loading">{% trans "Loading…" %}</p>
      <p class="link-dialog__msg" data-msg="empty" hidden>{% trans "This course has no content yet." %}</p>
      <p class="link-dialog__msg" data-msg="nomatch" hidden>{% trans "No matches." %}</p>
      <p class="link-dialog__msg" data-msg="foreign" hidden>{% trans "This link's target is not in this course." %}</p>
      <p class="link-dialog__msg link-dialog__msg--error" data-msg="fetch" hidden>
        {% trans "Could not load the course tree." %}
        <button type="button" class="btn btn--small" data-link-retry>{% trans "Retry" %}</button>
      </p>
      <p class="link-dialog__status" aria-live="polite" data-link-status></p>
    </div>

    <div class="picker__panel" role="tabpanel" id="link-panel-url"
         aria-labelledby="link-tab-url" data-panel="url" hidden>
      <label class="field">{% trans "Web address" %}
        <input type="url" class="input" data-link-url>
      </label>
      <p class="link-dialog__msg link-dialog__msg--error" data-msg="scheme" hidden>
        {% trans "Only http, https and mailto addresses are allowed." %}</p>
      <p class="link-dialog__msg link-dialog__msg--error" data-msg="protocol-relative" hidden>
        {% trans "Add https:// to the front of this address." %}</p>
      <p class="link-dialog__msg link-dialog__msg--error" data-msg="relative" hidden>
        {% trans "That is not a web address. Use the other tab to link inside this course." %}</p>
    </div>

    <label class="field">{% trans "Link text" %}
      <input type="text" class="input" data-link-text>
    </label>

    <div class="link-dialog__actions">
      <button type="button" class="btn btn--ghost" data-link-remove disabled>{% trans "Remove link" %}</button>
      <button type="button" class="btn btn--ghost" data-link-cancel>{% trans "Cancel" %}</button>
      <button type="button" class="btn" data-link-insert disabled>{% trans "Insert" %}</button>
    </div>
  </div>
</dialog>
```

- [ ] **Step 4: Wire it into the editor page**

In `templates/courses/manage/editor/editor.html`, immediately **before** the closing `</section>` on line 118 (i.e. after the `_editor_scope.html` include, outside every `[data-scope]`):

```html
  {% include "courses/manage/editor/_link_dialog.html" %}
```

And in the script block, right before the existing `text_toolbar.js` tag:

```html
  <script src="{% static 'courses/js/link_apply.js' %}" defer></script>
  <script src="{% static 'courses/js/link_dialog.js' %}" defer></script>
```

Order is convention only — `text_toolbar.js` guards on both globals, so it gets no assertion. A test that cannot go red for a real defect is not evidence.

- [ ] **Step 5: Add the CSS**

Append to `courses/static/courses/css/editor.css`:

```css
/* ---- Link dialog + picker -------------------------------------------------
   Layout classes are picker-LOCAL. The builder's .tree__scope/.tree__row/.tree__rowhead
   are deliberately NOT reused: they live in builder.css, which this page does not load
   (asserted in tests/test_editor_styles.py), so borrowing the names would ship an
   unindented, unstyled list. */
.link-dialog { padding: 0; border: 0; border-radius: var(--radius-md); max-width: 34rem; width: 92vw; }
.link-dialog::backdrop { background: rgb(0 0 0 / .45); }
.link-dialog__card { padding: var(--space-5); background: var(--surface-raised); border-radius: var(--radius-md); }
.link-dialog__title { margin: 0 0 var(--space-4); font-size: 1.05rem; }
.link-dialog__actions { display: flex; gap: var(--space-2); justify-content: flex-end; margin-top: var(--space-4); }
.link-dialog__msg { margin: var(--space-2) 0 0; color: var(--text-secondary); font-size: .85rem; }
.link-dialog__msg--error { color: var(--danger); }
.link-dialog__status { margin: var(--space-2) 0 0; font-size: .8rem; color: var(--text-secondary); }

/* A UA <dialog> caps at roughly the viewport, so without an explicit cap a 925-row
   tree either overflows or grows the dialog past the screen. */
.link-picker__mount { max-height: 40vh; overflow-y: auto; margin-top: var(--space-3);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: var(--space-2); }
.link-picker__scope { list-style: none; margin: 0; padding: 0; }
.link-picker__scope .link-picker__scope { padding-left: 14px; border-left: 2px solid var(--border-subtle); }
.link-picker__item { margin: 0; }
.link-picker__item:focus { outline: 2px solid var(--primary); outline-offset: 2px; }
.link-picker__item[aria-selected="true"] > .link-picker__row { background: var(--surface-sunken); font-weight: 600; }
.link-picker__item[aria-disabled="true"] > .link-picker__row { opacity: .55; }
.link-picker__row { display: flex; align-items: center; gap: var(--space-2); padding: 3px 4px;
  border-radius: var(--radius-sm); cursor: pointer; }
.link-picker__row:hover { background: var(--surface-sunken); }

/* DUPLICATED from builder.css:35-37 -- twin. The editor page does not load builder.css
   (tests/test_editor_styles.py asserts it), and pulling that stylesheet in would drag
   along .tree__title overrides that exist to win a specificity fight with app.css.
   tests/test_editor_styles.py::test_duplicated_badge_rules_match_their_twin keeps the
   two copies in step. */
.tree__badge { font-size: .6rem; text-transform: uppercase; letter-spacing: .03em; border: 1px solid currentColor; border-radius: 8px; padding: 0 6px; }
.tree__badge--part, .tree__badge--chapter, .tree__badge--section { color: var(--primary); }
.tree__badge--unit { color: var(--accent); }

/* Preview-pane links are click-inert: clicking one would navigate away and discard
   whatever is open in the edit form. NOT full inertness -- the anchors stay in the tab
   order and Enter still navigates; closing that would need the preview render to set
   tabindex="-1", a template change not worth it for a pane authors read rather than tab
   through. Note data-scope is NOT editor-only (the builder puts it on every tree
   scope), so this selector must stay pinned to ="preview". */
[data-scope="preview"] .el a { pointer-events: none; }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_link_dialog_markup.py tests/test_editor_styles.py -q`
Expected: PASS.

- [ ] **Step 7: Falsify the drift guard**

Change `.tree__badge` in `editor.css` to `padding: 0 8px`. Run
`uv run pytest tests/test_editor_styles.py -q`. Expected:
`test_duplicated_badge_rules_match_their_twin` FAILS. Restore.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/editor/_link_dialog.html templates/courses/manage/editor/editor.html courses/static/courses/css/editor.css tests/test_link_dialog_markup.py tests/test_editor_styles.py
git commit -m "feat(links): link dialog partial, editor wiring, picker CSS"
```

---

### Task 6: `link_dialog.js` — the dialog behaviour

**Files:**
- Create: `courses/static/courses/js/link_dialog.js`

**Interfaces:**
- Consumes: `window.libliLinkApply.normalizeUrl` (Task 4); the markup from Task 5; `courses:manage_link_picker` via `data-link-picker-url`.
- Produces: `window.libliLinkDialog.open(opts, cb)` where `opts = {existing, touchedAnchors, selectionText}` and `cb(result)` receives `{href, text}` | `{remove: true}` | `null`. **Defined only when `showModal` exists and `.link-dialog` is present** — the export is the capability signal.

- [ ] **Step 1: Write the module**

There is no cheap unit harness for this one (it needs the real `<dialog>` and the real fetch), so its behaviour is covered by the e2e in Task 8. Create `courses/static/courses/js/link_dialog.js`:

```js
(function () {
  "use strict";

  // Bail leaves window.libliLinkDialog UNDEFINED -- the export is the capability
  // signal, not merely a platform signal. A page that loaded this script without the
  // partial would otherwise pass text_toolbar.js's guard and then throw on a null
  // query. Follows imagezoom.js's precedent; the button becomes a no-op, an accepted
  // regression from window.prompt on browsers lacking <dialog>.
  if (typeof document.createElement("dialog").showModal !== "function") return;
  var dialog = document.querySelector(".link-dialog");
  if (!dialog) return;

  var pickerUrl = dialog.getAttribute("data-link-picker-url");
  var filterEl = dialog.querySelector("[data-link-filter]");
  var mount = dialog.querySelector("[data-link-tree]");
  var urlEl = dialog.querySelector("[data-link-url]");
  var textEl = dialog.querySelector("[data-link-text]");
  var insertBtn = dialog.querySelector("[data-link-insert]");
  var removeBtn = dialog.querySelector("[data-link-remove]");
  var cancelBtn = dialog.querySelector("[data-link-cancel]");
  var retryBtn = dialog.querySelector("[data-link-retry]");
  var statusEl = dialog.querySelector("[data-link-status]");
  var PERMALINK = /^\/courses\/n\/(\d+)\/$/;

  var callback = null;        // pending; a second open() is REJECTED, not superseding
  var committed = null;       // set by Insert/Remove; the close handler reads it
  var treeHtml = null;        // cached SUCCESSFUL response, for the life of the page
  var pending = null;         // in-flight fetch, reused by a second open()
  var aborter = null;
  var wantNode = null;        // preselection requested before the payload arrived
  var filterTimer = null;

  function msg(key, on) {
    var el = dialog.querySelector('[data-msg="' + key + '"]');
    if (el) el.hidden = !on;
  }
  function clearMessages() {
    var all = dialog.querySelectorAll("[data-msg]");
    for (var i = 0; i < all.length; i++) all[i].hidden = true;
  }

  // ---- tabs ---------------------------------------------------------------
  // editor.css styles the active tab as .picker__tab.is-on and hides panels via
  // .picker__panel[hidden] -- the pair media_picker.js already toggles. Without both,
  // two panels render at once.
  function showTab(name) {
    var tabs = dialog.querySelectorAll(".picker__tab");
    for (var i = 0; i < tabs.length; i++) {
      var on = tabs[i].getAttribute("data-tab") === name;
      tabs[i].classList.toggle("is-on", on);
      tabs[i].setAttribute("aria-selected", on ? "true" : "false");
    }
    var panels = dialog.querySelectorAll(".picker__panel");
    for (var j = 0; j < panels.length; j++) {
      panels[j].hidden = panels[j].getAttribute("data-panel") !== name;
    }
    (name === "node" ? filterEl : urlEl).focus();
    refresh();
  }
  dialog.querySelector(".picker__tabs").addEventListener("click", function (e) {
    var t = e.target.closest(".picker__tab");
    if (t) showTab(t.getAttribute("data-tab"));
  });

  function activeTab() {
    var on = dialog.querySelector(".picker__tab.is-on");
    return on ? on.getAttribute("data-tab") : "node";
  }

  // ---- picker -------------------------------------------------------------
  function rows() { return mount.querySelectorAll(".link-picker__item"); }
  function selectedRow() { return mount.querySelector('[aria-selected="true"]'); }

  function rovingSet() {
    var out = [], all = rows();
    for (var i = 0; i < all.length; i++) {
      if (!all[i].hidden && all[i].getAttribute("aria-disabled") !== "true") out.push(all[i]);
    }
    return out;
  }

  function setTabStop() {
    // The tab stop is a function of the roving set ALONE: the selected row only when
    // it is IN that set. Otherwise a filter that hides the selection would put
    // tabindex="0" on an unfocusable element and strand the tree with no tab stop.
    var set = rovingSet(), all = rows();
    for (var i = 0; i < all.length; i++) all[i].tabIndex = -1;
    var sel = selectedRow();
    var target = (sel && set.indexOf(sel) !== -1) ? sel : set[0];
    if (target) target.tabIndex = 0;
  }

  function selectRow(row) {
    var all = rows();
    for (var i = 0; i < all.length; i++) all[i].setAttribute("aria-selected", "false");
    if (row) {
      row.setAttribute("aria-selected", "true");
      if (!textEl.value) textEl.value = row.getAttribute("data-title") || "";
      row.scrollIntoView({ block: "nearest" });
    }
    setTabStop();
    refresh();
  }

  function applyFilter() {
    var q = (filterEl.value || "").trim().toLowerCase();
    var all = rows(), shown = 0;
    for (var i = 0; i < all.length; i++) {
      var title = (all[i].getAttribute("data-title") || "").toLowerCase();
      // Title only -- the kind label is a translated word and would match half the
      // tree in Polish.
      var hit = !q || title.indexOf(q) !== -1;
      all[i].hidden = false;
      all[i].setAttribute("aria-disabled", hit ? "false" : "true");
      if (hit) shown++;
    }
    if (q) {
      // Non-matching rows stay visible as ancestor context, recessed and
      // aria-disabled -- so the indentation still reads as a path -- but a row with
      // no matching descendant is hidden outright.
      for (var j = all.length - 1; j >= 0; j--) {
        if (all[j].getAttribute("aria-disabled") === "true" &&
            !all[j].querySelector('[aria-disabled="false"]')) {
          all[j].hidden = true;
        }
      }
    }
    msg("nomatch", q && shown === 0);
    mount.hidden = !!(q && shown === 0);
    setTabStop();
    // Debounced: a polite region that changes every keystroke queues one utterance per
    // character and drowns the "No matches." case it exists for.
    clearTimeout(filterTimer);
    filterTimer = setTimeout(function () {
      statusEl.textContent = shown + "";
    }, 400);
  }
  filterEl.addEventListener("input", applyFilter);

  mount.addEventListener("click", function (e) {
    var row = e.target.closest(".link-picker__item");
    if (row && row.getAttribute("aria-disabled") !== "true") selectRow(row);
  });

  mount.addEventListener("keydown", function (e) {
    var set = rovingSet();
    var cur = document.activeElement.closest ? document.activeElement.closest(".link-picker__item") : null;
    var i = set.indexOf(cur);
    if (e.key === "ArrowDown" && i > -1 && set[i + 1]) { set[i + 1].focus(); e.preventDefault(); }
    else if (e.key === "ArrowUp" && i > 0) { set[i - 1].focus(); e.preventDefault(); }
    else if (e.key === "Home" && set[0]) { set[0].focus(); e.preventDefault(); }
    else if (e.key === "End" && set.length) { set[set.length - 1].focus(); e.preventDefault(); }
    else if ((e.key === "Enter" || e.key === " ") && cur) {
      // Enter SELECTS a row here; it never inserts. Otherwise arrowing to a new row
      // and pressing Enter would fire Insert against the previously selected node.
      selectRow(cur); e.preventDefault();
    }
  });

  function loadTree() {
    clearMessages();
    msg("loading", true);
    if (treeHtml !== null) { paint(treeHtml); return; }
    if (pending) return;
    aborter = new AbortController();
    pending = fetch(pickerUrl, {
      headers: { "X-Requested-With": "fetch" },
      signal: aborter.signal
    }).then(function (r) {
      // "Successful" means ok AND not redirected: link_picker is @login_required, so an
      // expired session gives 302 -> login page -> 200, and fetch follows it. Caching
      // that would inject the login page into the tree mount AS the tree.
      if (!r.ok || r.redirected) throw new Error("bad");
      return r.text();
    }).then(function (html) {
      treeHtml = html;                 // cache SUCCESSES only
      pending = null;
      paint(html);
    }).catch(function () {
      pending = null;
      clearMessages();
      msg("fetch", true);              // not cached -> the next open() retries
    });
  }

  function paint(html) {
    // Server-rendered, autoescaped markup: innerHTML is correct here. The
    // never-innerHTML rule governs author-supplied strings crossing into an editing
    // surface, which this is not.
    mount.innerHTML = html;
    clearMessages();
    if (!rows().length) msg("empty", true);
    if (wantNode) {
      var row = mount.querySelector('[data-node="' + wantNode + '"]');
      if (row) selectRow(row); else msg("foreign", true);
      wantNode = null;
    }
    applyFilter();
  }
  retryBtn.addEventListener("click", loadTree);

  // ---- validity -----------------------------------------------------------
  function currentHref() {
    if (activeTab() === "node") {
      var row = selectedRow();
      return row ? row.getAttribute("data-href") : null;
    }
    var res = window.libliLinkApply.normalizeUrl(urlEl.value, window.location.origin);
    return res.href || null;
  }

  function refresh() {
    var ok = !!currentHref() && !!textEl.value.trim();
    insertBtn.disabled = !ok;
  }
  urlEl.addEventListener("input", function () {
    clearMessages();
    var res = window.libliLinkApply.normalizeUrl(urlEl.value, window.location.origin);
    if (res.reject && urlEl.value.trim()) msg(res.reject, true);
    refresh();
  });
  textEl.addEventListener("input", refresh);

  function commit(result) { committed = result; dialog.close(); }
  insertBtn.addEventListener("click", function () {
    var href = currentHref();
    if (!href) return;
    if (activeTab() === "url") urlEl.value = href;   // show the normalised value
    commit({ href: href, text: textEl.value });
  });
  removeBtn.addEventListener("click", function () { commit({ remove: true }); });
  cancelBtn.addEventListener("click", function () { dialog.close(); });

  // Enter inserts from the URL and Link-text fields only (the tree owns its own Enter).
  function enterInserts(e) {
    if (e.key === "Enter" && !insertBtn.disabled) { insertBtn.click(); e.preventDefault(); }
  }
  urlEl.addEventListener("keydown", enterInserts);
  textEl.addEventListener("keydown", enterInserts);

  // A modal <dialog> does NOT close on a backdrop click by itself; only Escape is
  // native. The content lives in an inner card and the dialog carries no padding, so
  // e.target === dialog means the backdrop and never the card's own padding. (Note
  // imagezoom.js closes on EVERY click inside it -- copying that here would make this
  // dialog unusable.)
  dialog.addEventListener("click", function (e) {
    if (e.target === dialog) dialog.close();
  });

  // Every dismissal path routes through ONE close handler, which fires the callback
  // exactly once -- pinning the classic double-fire where a button handler and a close
  // handler both call back.
  dialog.addEventListener("close", function () {
    var cb = callback, result = committed;
    callback = null;
    committed = null;
    if (aborter) { aborter.abort(); aborter = null; pending = null; }
    if (cb) cb(result || null);
  });

  window.libliLinkDialog = {
    open: function (opts, cb) {
      if (callback) return;            // one dialog at a time; the pending call stands
      callback = cb;
      committed = null;

      // Reset BEFORE preselection: the tree DOM is cached and aria-selected is the only
      // record of the target, so without this the second open arrives pre-armed with
      // the previous session's target and filter.
      filterEl.value = "";
      urlEl.value = "";
      textEl.value = "";
      var all = rows();
      for (var i = 0; i < all.length; i++) {
        all[i].setAttribute("aria-selected", "false");
        all[i].hidden = false;
        all[i].setAttribute("aria-disabled", "false");
      }
      clearMessages();
      statusEl.textContent = "";
      wantNode = null;

      var existing = opts.existing;
      removeBtn.disabled = !(opts.touchedAnchors > 0);

      // Prefill precedence: when an anchor ENCLOSES the range (i.e. rule 1 will fire)
      // existing.text wins, so the field shows the WHOLE text the mutation will
      // operate on. Prefilling a partial selection would show "vertex" in a field
      // whose edit replaces "the vertex form unit" -- three words lost, no undo.
      if (existing) textEl.value = existing.text || "";
      else if (opts.selectionText) textEl.value = opts.selectionText;

      var m = existing && PERMALINK.exec(existing.href || "");
      if (m) { wantNode = m[1]; showTab("node"); }
      else if (existing) { urlEl.value = existing.href || ""; showTab("url"); }
      else { showTab("node"); }

      dialog.showModal();
      loadTree();
      refresh();
    }
  };
})();
```

- [ ] **Step 2: Sanity-check it loads**

Run: `uv run python manage.py collectstatic --noinput --dry-run 2>&1 | tail -3` — confirm no error. Then open a unit editor in the browser and confirm the toolbar link button still does nothing yet (Task 7 wires it) and the console shows no error on page load.

- [ ] **Step 3: Commit**

```bash
git add courses/static/courses/js/link_dialog.js
git commit -m "feat(links): link_dialog.js — tabs, picker, URL validation, dismissal"
```

---

### Task 7: Wire the toolbar button

**Files:**
- Modify: `courses/static/courses/js/text_toolbar.js` (the `case "link":` branch only)
- Test: `tests/test_link_toolbar_wiring.py` (create)

**Interfaces:**
- Consumes: `window.libliLinkDialog.open` (Task 6), `window.libliLinkApply` (Task 4).
- Produces: nothing further.

- [ ] **Step 1: Write the failing test**

Create `tests/test_link_toolbar_wiring.py`:

```python
from pathlib import Path

TEXT_TOOLBAR = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "js"
    / "text_toolbar.js"
)


def test_prompt_is_gone():
    assert "window.prompt" not in TEXT_TOOLBAR.read_text(encoding="utf-8")


def test_guards_on_both_modules():
    # The dialog's export is a capability signal; the same reasoning extends to the
    # second module. Without this, a missing script tag or a collectstatic gap opens
    # the dialog and then throws when the result comes back.
    src = TEXT_TOOLBAR.read_text(encoding="utf-8")
    assert "window.libliLinkDialog" in src
    assert "window.libliLinkApply" in src


def test_range_is_cloned():
    # getRangeAt(0) returns the selection's LIVE Range, and showModal() focuses the
    # dialog's first focusable child, which collapses/replaces the document selection
    # -- mutating the very object the insertion and the dismissal caret-restore rely
    # on. The math command has the same unguarded pattern, but its modal is a plain
    # div, not a showModal() dialog.
    src = TEXT_TOOLBAR.read_text(encoding="utf-8")
    assert "cloneRange()" in src
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_link_toolbar_wiring.py -q`
Expected: FAIL — `window.prompt` is still present.

- [ ] **Step 3: Replace the `case "link":` branch**

In `courses/static/courses/js/text_toolbar.js`, replace:

```js
      case "link":
        var url = window.prompt("URL");
        if (url) exec("createLink", url);
        break;
```

with:

```js
      case "link": {
        if (!window.libliLinkDialog || !window.libliLinkApply) break;
        var lsel = window.getSelection();
        if (!lsel || !lsel.rangeCount) break;
        // CLONE: getRangeAt(0) hands back the live Range, and showModal() moves focus
        // out of the contenteditable, which collapses/replaces the document selection
        // and would mutate the object steps below depend on.
        var lrange = lsel.getRangeAt(0).cloneRange();
        var touched = window.libliLinkApply.anchorsFor(surface, lrange);
        var enc = window.libliLinkApply.enclosing(surface, lrange);
        window.libliLinkDialog.open({
          existing: enc
            ? { href: enc.getAttribute("href"), text: enc.textContent }
            : null,
          touchedAnchors: touched.length,
          selectionText: lrange.toString()
        }, function (result) {
          surface.focus();
          // editor.js can replace the pane while the dialog is open (the page carries
          // data-msg-conflict, so a background reload path exists). Mutating an
          // orphaned node would look like a successful insert and then lose the link
          // on save.
          if (!surface.isConnected) return;
          var sel2 = window.getSelection();
          sel2.removeAllRanges();
          sel2.addRange(lrange);
          if (!result) return;                      // dismissed: caret restored above
          // Should belong to the invoking surface; several RTE surfaces are live at
          // once (a question mounts one textarea for the stem and another for the
          // explanation). Fall back to appending, as the math command does.
          if (!surface.contains(lrange.commonAncestorContainer)) {
            var end = document.createRange();
            end.selectNodeContents(surface);
            end.collapse(false);
            window.libliLinkApply.apply(surface, end, result);
          } else {
            window.libliLinkApply.apply(surface, lrange, result);
          }
          surface.dispatchEvent(new Event("input"));
        });
        break;
      }
```

**`existing.href` is `getAttribute("href")`, never the `.href` IDL property** — the IDL property returns the resolved absolute URL, which would never match the dialog's anchored `^/courses/n/(\d+)/$`, so every re-open of an internal link would land on the wrong tab.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_link_toolbar_wiring.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Try it by hand**

Start the server, open a unit editor, add a text element, type a sentence, select a word, click the chain-link button. The dialog should open on *In this course* with the tree loaded and the selected word in *Link text*. Pick a chapter, Insert, save, and confirm the stored body holds `<a href="/courses/n/<pk>/">`.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/text_toolbar.js tests/test_link_toolbar_wiring.py
git commit -m "feat(links): toolbar link button opens the dialog instead of window.prompt"
```

---

### Task 8: Student-side link styling and the route-literal guard

**Files:**
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_link_styling.py` (create)

**Interfaces:**
- Consumes: `courses:node_permalink` (Task 1).
- Produces: `.el a[href^="/courses/n/"]` and `.el a[href^="http"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_styling.py`:

```python
from pathlib import Path

from django.urls import reverse

COURSES_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "css"
    / "courses.css"
)


def test_internal_and_external_markers_exist():
    css = COURSES_CSS.read_text(encoding="utf-8")
    assert '.el a[href^="/courses/n/"]' in css
    assert '.el a[href^="http"]' in css


def test_css_prefix_matches_the_route(db):
    # The selector duplicates the route's literal path, which the route NAME does not
    # protect: changing path("courses/n/<int:node_pk>/", ...) keeps every reverse-based
    # test green while silently stripping the marker off every internal link.
    prefix = "/courses/n/"
    assert reverse("courses:node_permalink", kwargs={"node_pk": 1}).startswith(prefix)
    assert '.el a[href^="' + prefix + '"]' in COURSES_CSS.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_link_styling.py -q`
Expected: FAIL — the selectors are absent.

- [ ] **Step 3: Add the CSS**

Append to `courses/static/courses/css/courses.css`:

```css
/* ---- Content link affordances ---------------------------------------------
   Scoped to .el (the wrapper every rendered element carries) so site chrome and
   navigation are untouched. Keying off the href PREFIX is what lets this work with no
   sanitiser change -- a class on <a> would be stripped by nh3.
   TWIN: the "/courses/n/" literal below duplicates the node_permalink route path. The
   route NAME does not protect it; tests/test_link_styling.py ties the two together.
   The glyphs are ::before/::after content, so they are not copied with the text and
   are not announced -- the link text alone must carry the meaning. */
.el a[href^="/courses/n/"] {
  color: var(--primary); text-decoration: underline;
}
.el a[href^="/courses/n/"]::before {
  content: "\21B3\00A0"; /* downwards arrow with tip rightwards */
  text-decoration: none; display: inline-block;
}
.el a[href^="http"]::after {
  content: "\00A0\2197"; /* north-east arrow */
  text-decoration: none; display: inline-block;
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_link_styling.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Falsify the twin guard**

Temporarily change the route to `path("courses/node/<int:node_pk>/", ...)`. Run
`uv run pytest tests/test_link_styling.py -q`. Expected: `test_css_prefix_matches_the_route` FAILS. Restore.

- [ ] **Step 6: Screenshot both themes**

Render a lesson containing one internal and one external link. Screenshot light and dark, judged separately. Confirm both markers are legible and the underline does not swallow the glyph.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_link_styling.py
git commit -m "feat(links): distinct internal/external link affordances"
```

---

### Task 9: Translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ both `.mo`)

- [ ] **Step 1: Extract**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`

- [ ] **Step 2: Translate every new msgid into Polish**

Open `locale/pl/LC_MESSAGES/django.po` and fill each new entry — *Insert link*, *In this course*, *Web address*, *Filter by title…*, *Course content*, *Loading…*, *This course has no content yet.*, *No matches.*, *This link's target is not in this course.*, *Could not load the course tree.*, *Retry*, *Link text*, *Remove link*, *Cancel*, *Insert*, and the three URL-rejection messages.

**Clear any fuzzy entry properly — that is TWO deletions:** the `#, fuzzy` line *and* the `#| msgid` comment above it. A fuzzy match arrives pre-filled from an unrelated msgid, so an un-cleared one ships a wrong translation that looks done.

- [ ] **Step 3: Verify catalogue health**

Run: `uv run pytest tests/test_i18n_po_health.py -q`
Expected: PASS. `test_pl_has_no_untranslated_msgid` fails on any blank msgstr.

- [ ] **Step 4: Compile**

Run: `uv run python manage.py compilemessages`

- [ ] **Step 5: Commit**

```bash
git add locale/
git commit -m "i18n(links): pl/en strings for the link dialog"
```

---

### Task 10: End-to-end coverage

**Files:**
- Test: `tests/test_e2e_link_dialog.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1-9.

- [ ] **Step 1: Write the e2e**

Follow the repo's proven e2e idiom exactly — module-level `_make_pa_user` / `_login` helpers, the `DJANGO_ALLOW_ASYNC_UNSAFE` session fixture, and `@pytest.mark.django_db(transaction=True)` per test. Do **not** invent a new login fixture; `tests/test_e2e_builder.py` is the pattern to mirror. Every step drives the real gesture — a `page.evaluate` shortcut would ship broken UX green.

Create `tests/test_e2e_link_dialog.py`:

```python
"""Playwright e2e for the rich-text link dialog: insert an internal link, follow it,
re-open and remove it, and complete an insert with the keyboard alone. Marked e2e
(excluded from the default run)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    # Mirrors tests/test_e2e_builder.py::_login -- allauth's field is name="login",
    # and the form must be scoped because the shell header also carries submits.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(owner, *, with_link=False):
    """A course with part > chapter > lesson unit. Optionally seed a text element whose
    body already holds an internal link, for the re-open/remove path."""
    from courses.models import ContentNode, Course, Element, TextElement

    course = Course.objects.create(title="Algebra", slug="algebra", owner=owner)
    part = ContentNode.objects.create(course=course, kind="part", title="Part A")
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", parent=part, title="Quadratics"
    )
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="Lesson"
    )
    if with_link:
        el = TextElement(
            body=f'<p>see <a href="/courses/n/{chapter.pk}/">quadratics</a></p>'
        )
        el.save()
        Element.objects.create(unit=unit, content_object=el)
    return course, chapter, unit


def _open_editor(page, live_server, course, unit):
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )


@pytest.mark.django_db(transaction=True)
def test_insert_internal_link_then_follow_it(page, live_server):
    from courses.models import Enrollment, TextElement

    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)

    page.click("[data-add-type='text']")
    page.locator(".rte-surface").click()
    page.keyboard.type("See the quadratics chapter")
    page.dblclick(".rte-surface >> text=quadratics")

    page.click("[data-cmd='link']")
    dialog = page.locator(".link-dialog")
    dialog.wait_for(state="visible")

    # Default tab is "In this course" -- the feature's reason to exist.
    assert dialog.locator("[data-tab='node']").get_attribute("aria-selected") == "true"

    dialog.locator("[data-link-filter]").fill("zzz-nothing-matches")
    assert dialog.locator("[data-msg='nomatch']").is_visible()
    dialog.locator("[data-link-filter]").fill("")

    dialog.locator(f"[data-node='{chapter.pk}']").click()
    # Prefill precedence: a non-empty selection beats the node title.
    assert dialog.locator("[data-link-text]").input_value() == "quadratics"
    dialog.locator("[data-link-insert]").click()

    page.click('form[data-op="element-save"] button[type="submit"]')
    page.wait_for_selector(".editor-form", state="attached")

    body = TextElement.objects.latest("pk").body
    assert f'href="/courses/n/{chapter.pk}/"' in body

    # Follow it as an enrolled reader.
    Enrollment.objects.create(student=owner, course=course)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.click(f".el a[href='/courses/n/{chapter.pk}/']")
    page.wait_for_url(f"**#node-{chapter.pk}")
    row = page.locator(f"#node-{chapter.pk} > .outline-node__head")
    bg = row.evaluate("el => getComputedStyle(el).backgroundColor")
    # "Highlighted" is not otherwise assertable: a :target rule mis-scoped to the <li>,
    # or written into a stylesheet the outline page does not load, passes a weaker check.
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent")


@pytest.mark.django_db(transaction=True)
def test_collapsed_caret_defaults_link_text_to_the_node_title(page, live_server):
    """The other half of the precedence rule, and what the Purpose section promises."""
    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)

    page.click("[data-add-type='text']")
    page.locator(".rte-surface").click()
    page.click("[data-cmd='link']")
    dialog = page.locator(".link-dialog")
    dialog.wait_for(state="visible")
    dialog.locator(f"[data-node='{chapter.pk}']").click()
    assert dialog.locator("[data-link-text]").input_value() == chapter.title


@pytest.mark.django_db(transaction=True)
def test_keyboard_only_insert(page, live_server):
    """Tab once into the tree, move with arrows, press with Enter -- no mouse.

    This is what makes the roving-tabindex model real: with ~925 rows a Tab-only path
    to a deep row is not a realistic gesture, so a Tab-only test would prove nothing.
    """
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)

    page.click("[data-add-type='text']")
    page.locator(".rte-surface").click()
    page.keyboard.type("text")
    page.click("[data-cmd='link']")
    dialog = page.locator(".link-dialog")
    dialog.wait_for(state="visible")

    page.keyboard.press("Tab")          # filter -> the tree's single tab stop
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")        # Enter SELECTS a row; it never inserts
    assert dialog.locator("[aria-selected='true']").count() == 1
    dialog.locator("[data-link-text]").fill("Chapter")
    dialog.locator("[data-link-insert]").click()
    dialog.wait_for(state="hidden")


@pytest.mark.django_db(transaction=True)
def test_reopening_prefills_and_remove_unwraps(page, live_server):
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner, with_link=True)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)

    page.click(".editor-list [data-element]")   # open the seeded text element
    page.click(".rte-surface a")                # caret inside the link
    page.click("[data-cmd='link']")
    dialog = page.locator(".link-dialog")
    dialog.wait_for(state="visible")
    assert dialog.locator("[data-tab='node']").get_attribute("aria-selected") == "true"
    selected = dialog.locator("[aria-selected='true']")
    assert selected.count() == 1
    # The preselected row must be scrolled into view, not merely marked.
    assert selected.is_visible()

    dialog.locator("[data-link-remove]").click()
    dialog.wait_for(state="hidden")
    assert page.locator(".rte-surface a").count() == 0
    assert "quadratics" in page.locator(".rte-surface").inner_text()
```

- [ ] **Step 2: Confirm the element-list selector**

`test_reopening_prefills_and_remove_unwraps` clicks `.editor-list [data-element]` to open the seeded element. Open the editor in a browser, inspect the element row, and correct that selector to whatever the list actually renders before running the test. Every other selector in the file was verified against the templates.

- [ ] **Step 3: Run the e2e**

Run: `uv run pytest tests/test_e2e_link_dialog.py -m e2e -q`
Expected: PASS. `-m e2e` is mandatory — without it pytest deselects everything and exits 5. Run it in the foreground; a backgrounded e2e run hides failures.

- [ ] **Step 4: Falsify the keyboard test**

Comment out the `keydown` listener in `link_dialog.js`. Confirm `test_keyboard_only_insert` FAILS (no row becomes selected). Restore it.

- [ ] **Step 5: Full suite and lint**

Run: `uv run pytest -q`
Run: `uv run pytest -m e2e -q`
Run: `uv run ruff check . && uv run ruff format --check .`

All green. If a failure appears that your diff cannot explain, do not fold a fix into this branch — an unrelated or flaky failure belongs in its own PR.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_link_dialog.py
git commit -m "test(links): end-to-end coverage for the link dialog"
```

---

## Self-Review

**Spec coverage.** §1 permalink → Task 1. §2 outline anchors → Task 2. §3 picker endpoint, partials, roving tabindex, chip, fetch policy, filter states → Tasks 3, 6. §4 dialog markup, feature detection, tabs, ownership split, insertion rules, URL contract, dismissal, prefill precedence → Tasks 4, 5, 6, 7. §5 styling → Tasks 5 (preview-inert), 8 (student-side). §Testing → distributed, with the falsification steps called out per task. §i18n → Task 9.

**Known gap, deliberate:** the spec's "wrong-surface case" is a *claim to be measured* — `applyCmd` calls `surface.focus()` before any branch reads the selection, which may make the mis-insert impossible. Task 7 ships the containment guard (cheap, correct either way) but no test asserts the mis-insert, because a test written before reproducing it would pass vacuously. Reproduce it against pre-change code during Task 7 and record the finding in the PR; add the test only if it is real.

**Type consistency.** `window.libliLinkApply` exposes `anchorsFor`, `enclosing`, `apply`, `normalizeUrl` — defined in Task 4 and called with those exact names in Tasks 6 and 7. `window.libliLinkDialog.open(opts, cb)` takes `{existing, touchedAnchors, selectionText}` in Task 6 and is called with exactly those keys in Task 7. `normalizeUrl`'s reject keys (`"scheme"`, `"protocol-relative"`, `"relative"`) match the `data-msg` attribute values in Task 5's partial.
