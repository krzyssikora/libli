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
- **Imports are one name per line.** `pyproject.toml` selects `["E","F","I","UP","B","S"]`
  with `[tool.ruff.lint.isort] force-single-line = true`, so `from x import a, b` fails
  `I001` and any unused import fails `F401`. Lines are capped at 88 (`E501`). Run
  `uv run ruff check <file> && uv run ruff format --check <file>` **at the end of each
  task**, not only at the end of the plan — otherwise the lint gate fails with a dozen
  files to fix at once.
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
from django.urls import resolve
from django.urls import reverse

from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.factories import seed_roles

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


def test_sanitiser_passes_internal_links_through_untouched():
    """The single assumption every other decision in part 1 rests on.

    No custom scheme, no marker class, href-prefix CSS -- all of it is justified by
    sanitize_html leaving a relative anchor alone. A future tightening of
    ALLOWED_ATTRIBUTES would silently void every stored link with nothing going red.
    The two negative rows are what the URL contract's rejections exist for.
    """
    from courses.sanitize import sanitize_html

    keeps = '<a href="/courses/n/12/">u</a>'
    assert sanitize_html(keeps) == keeps
    # Survives untouched -- an off-site link wearing a relative disguise, which is why
    # the dialog rejects it rather than trusting the sanitiser to.
    off_site = '<a href="//evil.com/x">x</a>'
    assert sanitize_html(off_site) == off_site
    # Stripped at SAVE, after the author saw a working-looking link -- which is why the
    # dialog rejects it up front instead.
    assert sanitize_html('<a href="javascript:alert(1)">j</a>') == "<a>j</a>"


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
Expected: PASS (9 tests).

- [ ] **Step 6: Falsify the sanitiser guard**

Temporarily add `"class"` to `ALLOWED_ATTRIBUTES["a"]` in `courses/sanitize.py` and
change the first assertion's input to carry a class. Confirm
`test_sanitiser_passes_internal_links_through_untouched` still passes (the guard is
about *hrefs*), then instead remove `"href"` from `ALLOWED_ATTRIBUTES["a"]` and confirm
it FAILS. Restore.

- [ ] **Step 7: Falsify the 404-not-403 guard**

Temporarily change `raise Http404(...)` to `raise PermissionDenied`. Run
`uv run pytest tests/test_node_permalink.py -q`. Expected: `test_inaccessible_course_is_404_not_403` and `test_manager_who_is_not_an_accessor_gets_404` FAIL. Restore the `Http404`.

- [ ] **Step 8: Commit**

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
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

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
    # Scoped to the rule, not the file: a bare `"scroll-margin-top" in css` would pass
    # on any unrelated occurrence in a 3000-line stylesheet -- including before this
    # change was made at all.
    # Anchored on a NEWLINE: the bare substring ".outline-node {" already matches the
    # pre-existing `.outline-tree > ul > .outline-node {` rule (app.css:488), so an
    # unanchored split lands on that block and the assertion fails even after the work
    # is done correctly. Measured: "\n.outline-node {" is absent today and appears only
    # once the new standalone rule is added -- so this still falsifies.
    css = APP_CSS.read_text(encoding="utf-8")
    assert "\n.outline-node {" in css
    block = css.split("\n.outline-node {", 1)[1].split("}", 1)[0]
    assert "scroll-margin-top" in block
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

- [ ] **Step 6: Falsify both guards**

Remove `id="node-{{ item.node.pk }}"` from `_outline_node.html`; confirm
`test_outline_rows_carry_a_node_id` FAILS; restore. Then change the highlight selector
to a bare `.outline-node:target`; confirm
`test_target_highlight_is_scoped_to_the_row_not_the_li` FAILS; restore.

- [ ] **Step 7: Check both themes**

Start the app (`uv run python manage.py runserver`), open a course outline with `#node-<pk>` for a chapter, and screenshot in light and dark. Judge dark separately — do not infer it from light. If the highlight is illegible in either, adjust the two custom properties above and re-check.

- [ ] **Step 8: Commit**

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
- Produces: URL name `courses:manage_link_picker` taking `slug`. Response is a bare `<ol class="link-picker__scope" role="none">` whose rows are `<li class="link-picker__item" role="treeitem">` carrying `data-node`, `data-title`, `data-href`, `aria-level`, `aria-selected="false"`, `tabindex="-1"`. Task 6 reads exactly these attributes.

  **`role="tree"` is not on this root `<ol>`** — it belongs on the dialog's mount `<div>` (Task 5), which is the element carrying the translated `aria-label`. An `aria-label` on a role-less wrapper names *that wrapper*, not a `role="tree"` child injected inside it, so putting the role here would leave the tree announced nameless. The root `<ol>` is therefore `role="none"`, keeping the `<li role="treeitem">` rows owned by the labelled tree; nested `<ol>`s keep `role="group"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_picker.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

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
    # role="tree" lives on the dialog's mount div (which carries the aria-label);
    # this root <ol> is presentational so the <li> treeitems remain owned by the tree.
    assert 'role="none"' in html
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
    with django_assert_num_queries(9) as captured:
        # Measured: session, user, allauth's EmailAddress read, the course lookup, the
        # permission/group reads behind can_manage_course, and one _children_map. The
        # exact total is incidental; the assertion below is the invariant that matters.
        client.get(url)
    # The invariant that actually matters: the tree costs ONE query regardless of size.
    node_queries = [
        q for q in captured.captured_queries if "courses_contentnode" in q["sql"]
    ]
    assert len(node_queries) == 1, node_queries
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
{# get_item is needed only in the ROW partial; this one just loops top_nodes. #}
<ol class="link-picker__scope" role="none">
  {% for node in top_nodes %}
    {% include "courses/manage/editor/_link_picker_node.html" with n=node children_map=children_map level=1 %}
  {% endfor %}
</ol>
```

- [ ] **Step 5: Create the row partial**

`templates/courses/manage/editor/_link_picker_node.html`. Note it includes **itself**, rebinding `n=child` and re-passing `children_map` — omit the rebind and you get infinite recursion on the same node:

```html
{% load courses_manage_extras %}
{% comment %}One picker row. No translatable text here -- the only strings are the node
title and the model's own get_kind_display / get_unit_type_display, which is why §i18n
can say the picker partials contribute no new msgids. The <li> IS the treeitem so that its children's
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

Expected: 7 pass, and `test_query_count_is_flat_in_tree_size` **fails** with the real
number. Measured on this repo at the time of writing: **9**, with exactly one query
touching `courses_contentnode`. Treat 9 as a starting point rather than gospel — it will
drift with middleware and auth changes — and re-derive it with the rule below. `can_manage_course` runs
`user.has_perm(...)` (a group/permission query on a cold cache) and allauth's
`AccountMiddleware` reads `EmailAddress` on every authenticated request, neither of which
the comment lists. Record the real number, then apply the rule below.

If the query-count test reports a different number, do **not** just record it. Read the
captured queries (`django_assert_num_queries` prints them on failure) and apply this
rule: **exactly one** must touch `courses_contentnode` — that is `_children_map`, and it
is the one a per-row regression would multiply. Everything else is incidental
auth/session/course overhead; allauth's `AccountMiddleware` reads `EmailAddress` on
authenticated requests, for instance, which the comment does not list. Update the number
*and* extend the comment to name what you actually found, so the next reader can do the
same check.

- [ ] **Step 7: Falsify the href guard**

Change the route's **path** — not its name. Temporarily set it to
`path("courses/node/<int:node_pk>/", views.node_permalink, name="node_permalink")`, then:

- with the partial's `data-href="{% url 'courses:node_permalink' node_pk=n.pk %}"`:
  `test_row_href_equals_reverse` still **PASSES** (both sides moved together);
- with it hand-built as `data-href="/courses/n/{{ n.pk }}/"`: it **FAILS**.

Restore both. Renaming the *route* instead would redden both variants — the test body
calls `reverse("courses:node_permalink", …)` itself, so it dies with `NoReverseMatch`
before it can tell you anything about the template. This is the same recipe Task 8
Step 5 uses, for the same reason.

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

**Not in scope here: the raw-`>`-in-an-attribute hazard.** That is a *string-scanning* problem, and this module never scans HTML — it walks the live DOM, where the browser's parser has already resolved attribute boundaries correctly. `surface.querySelectorAll("a")` cannot be fooled by `title="a > b"`. The attribute-aware scanner belongs to part 2's `courses/richtext.py`, which does scan strings; a test for it here could never go red for a real defect.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_link_apply.py`. This uses Playwright as a JS runtime, following `tests/test_table_grid_algebra.py` — there is no jsdom in this repo. The file **must** carry the e2e marker or it lands in the unit job where no browser is installed.

Note the import style: `pyproject.toml` selects `I` with `force-single-line = true`, so every import is on its own line. Grouped imports fail `ruff check`.

```python
"""Unit tests for link_apply.js, run in a real browser.

There is no jsdom here (no package.json, no vitest/jest). The repo's one precedent for
unit-testing a JS module is Playwright as a JS runtime: add_script_tag the module into a
blank page and call its exports via evaluate. That is WHY the mutation logic lives in
link_apply.js rather than inside text_toolbar.js's IIFE -- logic private to that closure
would only be reachable by driving the whole editor.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # tests/conftest.py makes `db` autouse for EVERY test, and _django_db_helper
    # touches the ORM while Playwright's sync-API event loop is running. Without this
    # the whole file ERRORs at setup with SynchronousOnlyOperation -- even though these
    # tests never use the database themselves. Every e2e file in the repo carries it,
    # including the cited precedent tests/test_table_grid_algebra.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


MODULE = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "js"
    / "link_apply.js"
)

SELECT_ALL = (
    "(s) => { const r = document.createRange();"
    " r.selectNodeContents(s); return r; }"
)
CARET_IN_FIRST_LINK = (
    "(s) => { const a = s.querySelector('a');"
    " const r = document.createRange();"
    " r.setStart(a.firstChild, 1); r.collapse(true); return r; }"
)
SELECT_FIRST_LINK = (
    "(s) => { const r = document.createRange();"
    " r.selectNodeContents(s.querySelector('a')); return r; }"
)
CARET_AT_END = (
    "(s) => { const r = document.createRange();"
    " r.setStart(s.firstChild, s.firstChild.length);"
    " r.collapse(true); return r; }"
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


def _apply_then(page, html, build_range_js, result, probe_js):
    """Same, but return the value of probe_js evaluated against the surface after."""
    return page.evaluate(
        """([html, buildRange, result, probe]) => {
            const s = document.getElementById('s');
            s.innerHTML = html;
            const range = (new Function('s', 'return (' + buildRange + ')(s)'))(s);
            window.libliLinkApply.apply(s, range, result);
            return (new Function('s', 'return (' + probe + ')(s)'))(s);
        }""",
        [html, build_range_js, result, probe_js],
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
        SELECT_FIRST_LINK,
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


def test_partial_selection_inside_a_link_exposes_the_full_text(page_with_module):
    # The prefill-precedence hazard: existing.text must be the anchor's WHOLE
    # textContent, or an author shown "vertex" would silently lose "the ... form unit"
    # when they edit the field. text_toolbar.js reads exactly this.
    got = page_with_module.evaluate(
        """() => {
            const s = document.getElementById('s');
            s.innerHTML = '<a href="/old/">the vertex form unit</a>';
            const t = s.querySelector('a').firstChild;
            const r = document.createRange();
            r.setStart(t, 4); r.setEnd(t, 10);        // "vertex"
            const enc = window.libliLinkApply.enclosing(s, r);
            return [r.toString(), enc.textContent];
        }"""
    )
    assert got == ["vertex", "the vertex form unit"]


def test_rule2_selection_starting_at_an_anchors_first_character(page_with_module):
    # The marker-node ordering case: a boundary container that IS the anchor would be
    # detached by the unwrap, leaving the range pointing at nothing.
    out = _apply(
        page_with_module,
        '<a href="/a/">AB</a>CD',
        (
            "(s) => { const a = s.querySelector('a');"
            " const r = document.createRange();"
            " r.setStart(a.firstChild, 0); r.setEnd(s.lastChild, 2); return r; }"
        ),
        {"href": "/courses/n/9/", "text": "linked"},
    )
    assert out.count("<a") == 1
    assert 'href="/courses/n/9/"' in out


def test_rule2_leaves_no_marker_or_split_text_node(page_with_module):
    # The stated point of the marker sequence: markers removed, text nodes merged.
    kids = _apply_then(
        page_with_module,
        'before <a href="/a/">AB</a> after',
        SELECT_ALL,
        {"href": "/courses/n/9/", "text": "L"},
        "(s) => Array.from(s.childNodes).map(n => n.nodeName)",
    )
    assert kids == ["A"], kids


def test_rule2_overlap_unlinks_the_unselected_remainder(page_with_module):
    # Stated loss: a selection covering the tail of A and the head of B leaves BOTH
    # fully unlinked, including the parts never selected. The alternative (splitting
    # A and B) would produce three anchors from one gesture.
    out = _apply(
        page_with_module,
        '<a href="/a/">AAA</a> mid <a href="/b/">BBB</a>',
        (
            "(s) => { const as = s.querySelectorAll('a');"
            " const r = document.createRange();"
            " r.setStart(as[0].firstChild, 2);"
            " r.setEnd(as[1].firstChild, 1); return r; }"
        ),
        {"href": "/courses/n/9/", "text": "L"},
    )
    assert out.count("<a") == 1
    assert "/a/" not in out
    assert "/b/" not in out


def test_rule3_collapsed_caret_inserts_a_new_anchor(page_with_module):
    out = _apply(
        page_with_module,
        "plain",
        CARET_AT_END,
        {"href": "/courses/n/9/", "text": "New"},
    )
    assert 'href="/courses/n/9/"' in out
    assert ">New<" in out


def test_caret_after_an_insert_sits_outside_the_anchor(page_with_module):
    # This is what makes collapseAfter load-bearing: without it the caret stays INSIDE
    # the new link and every subsequent keystroke silently extends the link text.
    inside = _apply_then(
        page_with_module,
        "plain",
        CARET_AT_END,
        {"href": "/courses/n/9/", "text": "New"},
        (
            "(s) => { const r = window.getSelection().getRangeAt(0);"
            " const a = s.querySelector('a');"
            " return a.contains(r.startContainer) && r.startContainer !== s; }"
        ),
    )
    assert inside is False


def test_remove_unwraps_all_touched_anchors(page_with_module):
    out = _apply(
        page_with_module,
        'x <a href="/a/">A</a> y <a href="/b/">B</a> z',
        SELECT_ALL,
        {"remove": True},
    )
    assert "<a" not in out
    assert "A" in out
    assert "B" in out


def test_remove_leaves_the_caret_at_the_end_of_the_recovered_text(page_with_module):
    # Spec: "the caret is collapsed at the end of the recovered text". Also guards the
    # normalize() hazard: merging text nodes DETACHES all but the first, so a caret
    # anchored to a pre-normalise node would make setStartAfter throw.
    got = _apply_then(
        page_with_module,
        'x <a href="/a/">AAA</a> y',
        CARET_IN_FIRST_LINK,
        {"remove": True},
        (
            "(s) => { const r = window.getSelection().getRangeAt(0);"
            " const before = r.startContainer.textContent.slice(0, r.startOffset);"
            " return [r.collapsed, before]; }"
        ),
    )
    assert got[0] is True
    assert got[1].endswith("AAA")


def test_link_text_is_written_as_a_text_node(page_with_module):
    # Node titles are author-supplied and may contain markup characters.
    out = _apply(
        page_with_module,
        "plain",
        CARET_AT_END,
        {"href": "/courses/n/9/", "text": "<b>bold</b>"},
    )
    assert "&lt;b&gt;bold&lt;/b&gt;" in out
    assert "<b>bold</b>" not in out
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

  // A marker is an empty text node used as a stable position handle across mutations
  // that would otherwise detach the nodes we are holding.
  function marker() { return textNode(""); }

  function dropMarker(m) { if (m.parentNode) m.parentNode.removeChild(m); }

  function apply(surface, range, result) {
    var touched = anchorsFor(surface, range);

    if (result && result.remove) {
      // No deleteContents here: the recovered text is exactly what this preserves.
      // The caret is pinned with a MARKER, not with a neighbouring node: normalize()
      // merges adjacent text nodes into the FIRST and removes the rest, so a caret
      // anchored to one of the removed nodes would make setStartAfter throw
      // InvalidNodeTypeError. Insert the marker after the last unwrapped anchor's
      // content, normalise, then collapse to the marker's position and drop it.
      var endMark = marker();
      if (touched.length) {
        var lastAnchor = touched[touched.length - 1];
        lastAnchor.parentNode.insertBefore(endMark, lastAnchor.nextSibling);
      }
      for (var i = 0; i < touched.length; i++) unwrap(touched[i]);
      if (endMark.parentNode) {
        var sel = window.getSelection();
        var r = document.createRange();
        r.setStartBefore(endMark);
        r.collapse(true);
        sel.removeAllRanges();
        sel.addRange(r);
        dropMarker(endMark);
      }
      surface.normalize();   // AFTER the caret is set: normalize invalidates handles
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
      var startMark = marker();
      var endMark2 = marker();
      var r2 = range.cloneRange();
      r2.collapse(false);
      r2.insertNode(endMark2);
      var r1 = range.cloneRange();
      r1.collapse(true);
      r1.insertNode(startMark);

      for (var j = 0; j < touched.length; j++) unwrap(touched[j]);

      var work = document.createRange();
      work.setStartAfter(startMark);   // after/before, so removing the markers
      work.setEndBefore(endMark2);     // cannot shift the boundaries
      work.deleteContents();
      var anchor = makeAnchor(result.href, result.text);
      work.insertNode(anchor);
      dropMarker(startMark);
      dropMarker(endMark2);
      collapseAfter(anchor);           // BEFORE normalize, which detaches handles
      surface.normalize();
      return;
    }

    // Rule 3.
    var fresh = makeAnchor(result.href, result.text);
    range.insertNode(fresh);
    collapseAfter(fresh);
    surface.normalize();
  }

  window.libliLinkApply = {
    anchorsFor: anchorsFor,
    enclosing: enclosing,
    apply: apply,
    normalizeUrl: normalizeUrl
  };
})();
```

**Note the ordering rule this module obeys throughout:** `surface.normalize()` runs
**last**, after the selection has been set. Normalising merges adjacent text nodes into
the first and removes the others, so any node handle taken before it may be detached
afterwards — and `Range.setStartAfter` on a parentless node throws
`InvalidNodeTypeError`. Collapsing the selection to a *live* node first, then
normalising, keeps the caret valid because the selection is repaired by the browser
rather than by a stale reference.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_link_apply.py -m e2e -q`
Expected: PASS. `-m e2e` is mandatory — without it pytest deselects everything and exits 5.

- [ ] **Step 5: Lint this file now, not at the end**

Run: `uv run ruff format tests/test_link_apply.py && uv run ruff check tests/test_link_apply.py`
`ruff format` **first**, then `check`: the snippets in this plan are hand-wrapped and
the formatter will re-wrap some of them (implicit string concatenation, blank lines,
trailing-comment spacing). Running `--check` on unformatted code reports "would be
reformatted" and stops you for no reason. After formatting, `check` must be clean —
`E501` (88 cols), `F401` (unused imports) and `I001` (isort, `force-single-line = true`)
are all selected, so a grouped or over-long import block fails here rather than at
Task 10.

- [ ] **Step 6: Falsify the rule-1 markup-preservation guard**

Temporarily delete the `if (result.text !== enc.textContent)` condition so the contents are always replaced. Run the tests. Expected: `test_rule1_unmodified_text_preserves_inline_markup` FAILS. Restore it.

- [ ] **Step 7: Falsify the normalise-ordering guard**

Move `surface.normalize()` in the removal branch to *before* the caret is set (i.e. immediately after the unwrap loop) and anchor the caret to `touched[last].previousSibling` instead of the marker. Run the tests. Expected:
`test_remove_leaves_the_caret_at_the_end_of_the_recovered_text` FAILS — with an
`InvalidNodeTypeError` on a multi-anchor fixture, which is precisely the bug this
ordering prevents. Restore.

- [ ] **Step 8: Commit**

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
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db

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


def test_dialog_is_not_inside_any_data_scope(client):
    # editor.js REPLACES the [data-scope] panes and re-runs libliInitRte. Dropped
    # inside one, the <dialog> and every listener bound to it at load are destroyed on
    # the first save -- an intermittent dead toolbar button that is painful to
    # attribute.
    #
    # Assert the DOM invariant, not source ordering: _editor_scope.html itself includes
    # _preview.html, so a future edit that moves the include INTO a swapped pane would
    # leave editor.html's tag order unchanged and keep a text-ordering check green
    # while reintroducing exactly this bug.
    from bs4 import BeautifulSoup

    html, _course = _editor(client)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one(".link-dialog")
    assert node is not None, "dialog partial is not rendered at all"
    for parent in node.parents:
        assert not parent.get("data-scope"), (
            "the dialog must not sit inside a [data-scope] pane"
        )


def test_editor_loads_both_js_modules(client):
    html, _course = _editor(client)
    assert "link_apply.js" in html
    assert "link_dialog.js" in html


def test_tree_mount_is_a_named_tree(client):
    # role="tree" and the aria-label must live on the SAME element -- the mount div.
    # Delete either and every treeitem becomes an orphan with no owning tree, and
    # nothing else in the suite notices.
    html, _course = _editor(client)
    from bs4 import BeautifulSoup

    mount = BeautifulSoup(html, "html.parser").select_one("[data-link-tree]")
    assert mount is not None
    assert mount.get("role") == "tree"
    assert (mount.get("aria-label") or "").strip()


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
        ".link-picker__title",
        ".tree__badge",
        # Exact substring: data-scope is NOT editor-only (the builder puts it on every
        # tree scope), so a "simplification" to [data-scope] .el a would break the
        # builder, and deleting the rule lets a preview click discard unsaved work --
        # both silently.
        '[data-scope="preview"] .el a',
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
      {% comment %}role="tab" implies the tablist keyboard contract: ONE tab stop, with
    Left/Right moving between the tabs (link_dialog.js maintains the roving tabindex).
    Shipping the roles without it would be worse than the media picker's role-free
    tabs -- AT would announce a contract nothing implements.{% endcomment %}
      <button type="button" class="picker__tab is-on" role="tab" aria-selected="true"
              tabindex="0" id="link-tab-node" aria-controls="link-panel-node"
              data-tab="node">{% trans "In this course" %}</button>
      <button type="button" class="picker__tab" role="tab" aria-selected="false"
              tabindex="-1" id="link-tab-url" aria-controls="link-panel-url"
              data-tab="url">{% trans "Web address" %}</button>
    </div>

    <div class="picker__panel" role="tabpanel" id="link-panel-node"
         aria-labelledby="link-tab-node" data-panel="node">
      <label class="search">{% trans "Filter" %}
        <input type="search" class="input" data-link-filter
               placeholder="{% trans 'Filter by title…' %}">
      </label>
      <div class="link-picker__mount" data-link-tree role="tree"
           aria-label="{% trans 'Course content' %}"></div>
      <p class="link-dialog__msg" data-msg="loading">{% trans "Loading…" %}</p>
      <p class="link-dialog__msg" data-msg="empty" hidden>{% trans "This course has no content yet." %}</p>

      <p class="link-dialog__msg" data-msg="foreign" hidden>{% trans "This link's target is not in this course." %}</p>
      <p class="link-dialog__msg link-dialog__msg--error" data-msg="fetch" hidden>
        {% trans "Could not load the course tree." %}
        <button type="button" class="btn btn--small" data-link-retry>{% trans "Retry" %}</button>
      </p>
      {% comment %}The live region owns BOTH the count and the zero-match line, so the
      state the debounce exists to convey is actually announced. A bare digit outside
      it would be announced with no context and in no language.{% endcomment %}
      <p class="link-dialog__status" aria-live="polite" data-link-status>
        <span data-msg="nomatch" hidden>{% trans "No matches." %}</span>
        <span data-link-count hidden></span>
      </p>
      {% comment %}The count's noun, carried as translatable text the JS reads. A fully
      inflected count would need ngettext, which this dialog has no request cycle for --
      an accepted simplification, stated so it is not mistaken for an oversight.
      {% endcomment %}
      <span data-count-template hidden>{% trans "matches found" %}</span>
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
/* editor.css's existing .search rules are scoped to .picker, which this dialog is not,
   so without these the filter renders at the UA default width inside a 34rem dialog. */
.link-dialog .search { display: block; margin-bottom: var(--space-3); }
.link-dialog .search .input { width: 100%; }

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
/* min-width: 0 is what lets a long title actually truncate inside the 34rem dialog --
   a flex item's default min-width is auto, so without it the row overflows instead. */
.link-picker__title { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* DUPLICATED from builder.css .tree__badge block -- twin. The editor page does not load builder.css
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

- [ ] **Step 8: Lint this task's files**

Run: `uv run ruff format tests/test_link_dialog_markup.py tests/test_editor_styles.py && uv run ruff check tests/test_link_dialog_markup.py tests/test_editor_styles.py`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/editor/_link_dialog.html templates/courses/manage/editor/editor.html courses/static/courses/css/editor.css tests/test_link_dialog_markup.py tests/test_editor_styles.py
git commit -m "feat(links): link dialog partial, editor wiring, picker CSS"
```

---

### Task 6: `link_dialog.js` — the dialog behaviour

**Files:**
- Create: `courses/static/courses/js/link_dialog.js`
- Test: `tests/test_link_dialog_behaviour.py` (create, `pytestmark = pytest.mark.e2e`)

**Interfaces:**
- Consumes: `window.libliLinkApply.normalizeUrl` (Task 4); the markup from Task 5; `courses:manage_link_picker` via `data-link-picker-url`.
- Produces: `window.libliLinkDialog.open(opts, cb)` where `opts = {existing, touchedAnchors, selectionText}` and `cb(result)` receives `{href, text}` | `{remove: true}` | `null`. **Defined only when `showModal` exists and `.link-dialog` is present** — the export is the capability signal.

- [ ] **Step 1: Write the failing tests**

This module gets real coverage, not just a smoke check: it is ~300 lines with several
invariants the spec names explicitly (one-dialog-at-a-time, the tab toggle contract,
callback-fires-exactly-once, open-time reset). The harness mounts the **real rendered
partial** into a blank page, so no live server or DB is needed; only the fetch is
stubbed.

Create `tests/test_link_dialog_behaviour.py`:

```python
"""Behaviour tests for link_dialog.js against the REAL rendered partial.

Playwright as a JS runtime (see tests/test_table_grid_algebra.py). The picker fetch is
stubbed with page.route so no server is needed; everything else -- <dialog>, focus,
tabs, keyboard -- is the genuine browser.
"""

import os
from pathlib import Path

import pytest
from django.template.loader import render_to_string

pytestmark = pytest.mark.e2e

JS_DIR = (
    Path(__file__).resolve().parent.parent / "courses" / "static" / "courses" / "js"
)

# page.set_content leaves the document on about:blank, where a ROOT-RELATIVE fetch
# throws "Failed to parse URL" before it ever reaches the network -- so page.route
# never fires and every test hangs. MEASURED, not assumed. A <base> gives the injected
# document a real origin; the value is arbitrary because the fetch is stubbed.
BASE = "<base href='https://example.test/'>"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Every e2e file in this repo sets this; the fixture below touches the ORM inside a
    # live Playwright session, which raises SynchronousOnlyOperation without it.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield

TREE_HTML = """
<ol class="link-picker__scope" role="none">
  <li class="link-picker__item" role="treeitem" aria-level="1" aria-selected="false"
      tabindex="-1" data-node="1" data-title="Algebra" data-href="/courses/n/1/">
    <span class="link-picker__row">Algebra</span>
    <ol class="link-picker__scope" role="group">
      <li class="link-picker__item" role="treeitem" aria-level="2" aria-selected="false"
          tabindex="-1" data-node="2" data-title="Quadratics" data-href="/courses/n/2/">
        <span class="link-picker__row">Quadratics</span>
      </li>
    </ol>
  </li>
</ol>
"""


@pytest.fixture
def dialog_page(page, db):
    """A blank page holding the rendered dialog partial plus both JS modules.

    Yields (rather than returns) so the teardown can assert no uncaught JS error was
    raised anywhere -- including inside a setTimeout or an event listener.
    """
    from tests.factories import CourseFactory

    course = CourseFactory()
    markup = render_to_string(
        "courses/manage/editor/_link_dialog.html", {"course": course}
    )
    page.set_content(f"{BASE}<main>{markup}</main>")
    routed = {"n": 0}

    def _serve(route):
        routed["n"] += 1
        route.fulfill(status=200, body=TREE_HTML)

    page.route("**/link-picker/", _serve)
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))
    page.__routed = routed  # so _open can prove the stub was really hit
    # Most of this module runs in listeners, timers and promise catches, where an
    # exception never reaches page.evaluate -- so a broken build can leave assertions
    # green while throwing on every keystroke. Fail loudly instead.
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.__errors = errors
    yield page
    assert not errors, f"uncaught JS errors: {errors}"


def _open(page, **opts):
    page.evaluate(
        """(opts) => {
            window.__result = "PENDING";
            window.__calls = 0;
            window.libliLinkDialog.open(opts, (r) => {
                window.__calls += 1;
                window.__result = r;
            });
        }""",
        {"existing": None, "touchedAnchors": 0, "selectionText": "", **opts},
    )
    page.locator(".link-picker__item").first.wait_for()
    # Prove the stub was actually reached. Without this, a regression to about:blank
    # shows up as an opaque wait_for timeout instead of a clear cause.
    assert page.__routed["n"] >= 1


def test_module_exports_when_markup_is_present(dialog_page):
    assert dialog_page.evaluate("() => typeof window.libliLinkDialog") == "object"


def test_initial_focus_is_the_filter_input(dialog_page):
    # showModal() autofocuses the first focusable DESCENDANT -- which is the first tab
    # button -- so the focus call must happen AFTER showModal, not before.
    _open(dialog_page)
    focused = dialog_page.evaluate(
        "() => document.activeElement.getAttribute('data-link-filter') !== null"
    )
    assert focused is True


def test_default_tab_is_in_this_course(dialog_page):
    _open(dialog_page)
    assert (
        dialog_page.locator("[data-tab='node']").get_attribute("aria-selected")
        == "true"
    )


def test_tab_toggle_sets_is_on_and_hidden(dialog_page):
    # editor.css styles the active tab as .picker__tab.is-on and hides panels via
    # .picker__panel[hidden]. Without BOTH, two panels render at once.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    assert dialog_page.locator("[data-tab='url']").evaluate(
        "el => el.classList.contains('is-on')"
    )
    assert dialog_page.locator("[data-panel='node']").is_hidden()
    assert dialog_page.locator("[data-panel='url']").is_visible()


def test_tabs_are_a_single_tab_stop_with_arrow_keys(dialog_page):
    # role="tab" implies the tablist keyboard contract. Half the pattern -- roles
    # without roving tabindex and Left/Right -- is worse than no roles at all.
    _open(dialog_page)
    tabindexes = dialog_page.evaluate(
        "() => Array.from(document.querySelectorAll('.picker__tab'))"
        ".map(t => t.tabIndex)"
    )
    assert sorted(tabindexes) == [-1, 0]
    dialog_page.locator("[data-tab='node']").focus()
    dialog_page.keyboard.press("ArrowRight")
    assert (
        dialog_page.locator("[data-tab='url']").get_attribute("aria-selected") == "true"
    )


def test_enter_selects_a_row_and_never_inserts(dialog_page):
    _open(dialog_page)
    dialog_page.keyboard.press("Tab")          # filter -> the tree's single tab stop
    dialog_page.keyboard.press("Enter")
    assert dialog_page.locator("[aria-selected='true'][data-node]").count() == 1
    assert dialog_page.evaluate("() => window.__result") == "PENDING"


def test_arrow_down_moves_within_the_roving_set(dialog_page):
    _open(dialog_page)
    dialog_page.keyboard.press("Tab")
    dialog_page.keyboard.press("ArrowDown")
    dialog_page.keyboard.press("Enter")
    assert (
        dialog_page.locator("[aria-selected='true'][data-node]").get_attribute(
            "data-node"
        )
        == "2"
    )


def test_enter_in_the_url_field_inserts(dialog_page):
    # Spec: "Enter presses Insert from the URL field and the Link text field only ...
    # without this rule Enter would do nothing anywhere." Nothing else exercises it.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    dialog_page.locator("[data-link-url]").fill("https://ok.test/a")
    dialog_page.locator("[data-link-text]").fill("Ref")
    dialog_page.locator("[data-link-url]").press("Enter")
    assert dialog_page.evaluate("() => window.__result") == {
        "href": "https://ok.test/a",
        "text": "Ref",
    }


def test_insert_returns_href_and_text(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-node='2']").click()
    dialog_page.locator("[data-link-text]").fill("Quadratics")
    dialog_page.locator("[data-link-insert]").click()
    assert dialog_page.evaluate("() => window.__result") == {
        "href": "/courses/n/2/",
        "text": "Quadratics",
    }


def test_url_is_normalised_in_the_field_before_insert(dialog_page):
    # The spec promises "the normalised value is shown before inserting". Normalising
    # only inside the insert handler would close the dialog on the next statement, so
    # the author would never see it.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    dialog_page.locator("[data-link-url]").fill("example.com")
    dialog_page.locator("[data-link-url]").blur()
    assert dialog_page.locator("[data-link-url]").input_value() == "https://example.com"


@pytest.mark.parametrize(
    "value,key",
    [
        ("javascript:alert(1)", "scheme"),
        ("//evil.com/x", "protocol-relative"),
        ("/path", "relative"),
    ],
)
def test_rejected_url_shows_its_own_message_and_disables_insert(
    dialog_page, value, key
):
    # All THREE reject keys, because msg() no-ops silently when a key has no element:
    # rename one and the author gets a disabled Insert with no explanation, suite green.
    _open(dialog_page)
    dialog_page.locator("[data-tab='url']").click()
    dialog_page.locator("[data-link-url]").fill(value)
    dialog_page.locator("[data-link-text]").fill("x")
    assert dialog_page.locator(f"[data-msg='{key}']").is_visible()
    assert dialog_page.locator("[data-link-insert]").is_disabled()


@pytest.mark.parametrize("how", ["cancel", "escape", "backdrop"])
def test_every_dismissal_path_fires_the_callback_exactly_once(dialog_page, how):
    _open(dialog_page)
    if how == "cancel":
        dialog_page.locator("[data-link-cancel]").click()
    elif how == "escape":
        dialog_page.keyboard.press("Escape")
    else:
        # A modal <dialog> does NOT close on a backdrop click by itself; the content
        # lives in an inner card so e.target === dialog means the backdrop.
        # Click demonstrably OUTSIDE the dialog's own box: bounding_box() returns the
        # <dialog>, not the backdrop, and the card fills it (padding: 0), so a point
        # just inside the corner hits the card and only "works" if the border-radius
        # happens to reject that pixel -- a coincidence, not a contract.
        box = dialog_page.locator(".link-dialog").bounding_box()
        x, y = 10, 10
        assert x < box["x"] or y < box["y"], (x, y, box)
        dialog_page.mouse.click(x, y)
    assert dialog_page.evaluate("() => window.__calls") == 1
    assert dialog_page.evaluate("() => window.__result") is None


def test_a_second_open_while_pending_is_rejected(dialog_page):
    _open(dialog_page)
    dialog_page.evaluate(
        "() => { window.__second = 0;"
        " window.libliLinkDialog.open({existing: null, touchedAnchors: 0,"
        " selectionText: ''}, () => { window.__second += 1; }); }"
    )
    dialog_page.locator("[data-link-cancel]").click()
    # The FIRST callback stands and fires once; the second never registers.
    assert dialog_page.evaluate("() => window.__calls") == 1
    assert dialog_page.evaluate("() => window.__second") == 0


def test_a_second_open_starts_clean(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-node='2']").click()
    dialog_page.locator("[data-link-filter]").fill("quad")
    dialog_page.locator("[data-link-cancel]").click()
    _open(dialog_page)
    assert dialog_page.locator("[data-link-filter]").input_value() == ""
    assert dialog_page.locator("[aria-selected='true'][data-node]").count() == 0
    assert dialog_page.locator("[data-link-text]").input_value() == ""


def test_existing_internal_link_preselects_its_row(dialog_page):
    _open(
        dialog_page,
        existing={"href": "/courses/n/2/", "text": "Quadratics"},
        touchedAnchors=1,
    )
    assert (
        dialog_page.locator("[aria-selected='true'][data-node]").get_attribute(
            "data-node"
        )
        == "2"
    )
    assert dialog_page.locator("[data-link-remove]").is_enabled()


def test_target_not_in_this_course_explains_itself(dialog_page):
    _open(
        dialog_page,
        existing={"href": "/courses/n/999/", "text": "gone"},
        touchedAnchors=1,
    )
    assert dialog_page.locator("[data-msg='foreign']").is_visible()
    assert dialog_page.locator("[data-link-url]").input_value() == "/courses/n/999/"


def test_no_match_hides_the_tree_and_says_so(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-link-filter]").fill("zzz-nothing")
    assert dialog_page.locator("[data-msg='nomatch']").is_visible()
    # The zero-match line must sit INSIDE the live region, or the state the debounce
    # exists to convey is never announced.
    assert dialog_page.locator("[data-link-status] [data-msg='nomatch']").count() == 1


def test_the_live_region_announces_a_labelled_count(dialog_page):
    _open(dialog_page)
    dialog_page.locator("[data-link-filter]").fill("quad")
    dialog_page.wait_for_timeout(600)          # past the 400ms debounce
    text = dialog_page.locator("[data-link-count]").inner_text().strip()
    assert text.startswith("1 ")
    assert len(text) > 2, "a naked digit is not an announcement"


def test_a_failed_fetch_is_not_cached_and_retries_on_the_next_open(page, db):
    from tests.factories import CourseFactory

    course = CourseFactory()
    markup = render_to_string(
        "courses/manage/editor/_link_dialog.html", {"course": course}
    )
    page.set_content(f"{BASE}<main>{markup}</main>")
    calls = {"n": 0}

    def handler(route):
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=500, body="nope")
        else:
            route.fulfill(status=200, body=TREE_HTML)

    page.route("**/link-picker/", handler)
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))

    page.evaluate(
        "() => window.libliLinkDialog.open("
        "{existing: null, touchedAnchors: 0, selectionText: ''}, () => {})"
    )
    page.locator("[data-msg='fetch']").wait_for()
    page.locator("[data-link-cancel]").click()

    page.evaluate(
        "() => window.libliLinkDialog.open("
        "{existing: null, touchedAnchors: 0, selectionText: ''}, () => {})"
    )
    page.locator(".link-picker__item").first.wait_for()
    assert calls["n"] == 2


def test_dismissing_mid_fetch_does_not_paint_a_fetch_error(page, db):
    # A deliberate abort must be distinguishable from a failure, or a clean dismissal
    # toggles the error line on.
    from tests.factories import CourseFactory

    course = CourseFactory()
    markup = render_to_string(
        "courses/manage/editor/_link_dialog.html", {"course": course}
    )
    page.set_content(f"{BASE}<main>{markup}</main>")
    page.route("**/link-picker/", lambda route: None)  # never resolves
    page.add_script_tag(path=str(JS_DIR / "link_apply.js"))
    page.add_script_tag(path=str(JS_DIR / "link_dialog.js"))
    page.evaluate(
        "() => window.libliLinkDialog.open("
        "{existing: null, touchedAnchors: 0, selectionText: ''}, () => {})"
    )
    page.locator("[data-link-cancel]").click()
    assert page.locator("[data-msg='fetch']").is_hidden()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_link_dialog_behaviour.py -m e2e -q`
Expected: FAIL — `window.libliLinkDialog` is undefined because the module does not exist.

- [ ] **Step 3: Write the module**

Create `courses/static/courses/js/link_dialog.js`:

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
  var countEl = dialog.querySelector("[data-link-count]");
  var countLabel = dialog.querySelector("[data-count-template]");
  var tabsEl = dialog.querySelector(".picker__tabs");
  var PERMALINK = /^\/courses\/n\/(\d+)\/$/;

  var callback = null;        // pending; a second open() is REJECTED, not superseding
  var committed = null;       // set by Insert/Remove; the close handler reads it
  var treeHtml = null;        // cached SUCCESSFUL response, for the life of the page
  var pending = null;         // in-flight fetch, reused by a second open()
  var aborter = null;
  var aborted = false;        // distinguishes a deliberate abort from a real failure
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
  // two panels render at once. role="tab" also implies the tablist keyboard contract,
  // so the tabs are ONE tab stop with Left/Right between them.
  function showTab(name, focusField) {
    var tabs = dialog.querySelectorAll(".picker__tab");
    for (var i = 0; i < tabs.length; i++) {
      var on = tabs[i].getAttribute("data-tab") === name;
      tabs[i].classList.toggle("is-on", on);
      tabs[i].setAttribute("aria-selected", on ? "true" : "false");
      tabs[i].tabIndex = on ? 0 : -1;
    }
    var panels = dialog.querySelectorAll(".picker__panel");
    for (var j = 0; j < panels.length; j++) {
      panels[j].hidden = panels[j].getAttribute("data-panel") !== name;
    }
    if (focusField) (name === "node" ? filterEl : urlEl).focus();
    refresh();
  }
  tabsEl.addEventListener("click", function (e) {
    var t = e.target.closest(".picker__tab");
    if (t) showTab(t.getAttribute("data-tab"), true);
  });
  tabsEl.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    var next = activeTab() === "node" ? "url" : "node";
    showTab(next, false);
    dialog.querySelector('[data-tab="' + next + '"]').focus();
    e.preventDefault();
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
      if (!all[i].hidden && all[i].getAttribute("aria-disabled") !== "true") {
        out.push(all[i]);
      }
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
    msg("nomatch", !!(q && shown === 0));
    mount.hidden = !!(q && shown === 0);
    setTabStop();
    // Debounced: a polite region that changes every keystroke queues one utterance per
    // character and drowns the "No matches." case it exists for.
    clearTimeout(filterTimer);
    filterTimer = setTimeout(function () {
      // Announce a COUNT WITH A LABEL, never a naked digit. The zero-match line lives
      // inside this same region, so entering and leaving that state is announced too.
      countEl.hidden = false;
      countEl.textContent =
        shown + " " + (countLabel ? countLabel.textContent.trim() : "");
    }, 400);
  }
  filterEl.addEventListener("input", applyFilter);

  mount.addEventListener("click", function (e) {
    var row = e.target.closest(".link-picker__item");
    if (row && row.getAttribute("aria-disabled") !== "true") selectRow(row);
  });

  mount.addEventListener("keydown", function (e) {
    var set = rovingSet();
    var cur = document.activeElement.closest
      ? document.activeElement.closest(".link-picker__item")
      : null;
    var i = set.indexOf(cur);
    if (e.key === "ArrowDown" && i > -1 && set[i + 1]) {
      set[i + 1].focus(); e.preventDefault();
    } else if (e.key === "ArrowUp" && i > 0) {
      set[i - 1].focus(); e.preventDefault();
    } else if (e.key === "Home" && set[0]) {
      set[0].focus(); e.preventDefault();
    } else if (e.key === "End" && set.length) {
      set[set.length - 1].focus(); e.preventDefault();
    } else if ((e.key === "Enter" || e.key === " ") && cur) {
      // Enter SELECTS a row here; it never inserts. Otherwise arrowing to a new row
      // and pressing Enter would fire Insert against the previously selected node.
      selectRow(cur); e.preventDefault();
    }
  });

  function loadTree() {
    clearMessages();
    msg("loading", true);
    if (treeHtml !== null) { paint(treeHtml); return; }
    // NOTE: this only guards a re-entrant loadTree() from the Retry button. A second
    // open() while one is pending is rejected in open() itself, and close() aborts and
    // nulls `pending`, so there is no cross-open "reuse the in-flight request" path.
    if (pending) return;
    aborted = false;
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
      if (aborted) return;             // a deliberate abort is not a failure
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
    insertBtn.disabled = !(currentHref() && textEl.value.trim());
  }
  urlEl.addEventListener("input", function () {
    clearMessages();
    var res = window.libliLinkApply.normalizeUrl(urlEl.value, window.location.origin);
    if (res.reject && urlEl.value.trim()) msg(res.reject, true);
    refresh();
  });
  // Normalise IN THE FIELD on blur, not inside the insert handler: commit() closes the
  // dialog on the next statement, so a value rewritten there is never seen. The author
  // must be able to see (and reject) https:// being prepended.
  urlEl.addEventListener("blur", function () {
    var res = window.libliLinkApply.normalizeUrl(urlEl.value, window.location.origin);
    if (res.href) urlEl.value = res.href;
    refresh();
  });
  textEl.addEventListener("input", refresh);

  function commit(result) { committed = result; dialog.close(); }
  insertBtn.addEventListener("click", function () {
    var href = currentHref();
    if (href) commit({ href: href, text: textEl.value });
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
    if (aborter) { aborted = true; aborter.abort(); aborter = null; pending = null; }
    clearTimeout(filterTimer);   // a timer armed by the last keystroke would otherwise
                                 // fire up to 400ms later, repainting the count AFTER
                                 // the next open()'s reset
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
      // NOT statusEl.textContent = "" -- that replaces ALL children, destroying the
      // [data-msg="nomatch"] and [data-link-count] spans that live inside the region.
      // They never come back, and the debounce then throws on a null element.
      countEl.textContent = "";
      countEl.hidden = true;
      clearTimeout(filterTimer);
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
      var tab = "node";
      // The raw stored href goes into the URL field WHENEVER there is one, including
      // for an internal permalink: if the pk turns out not to be in this course's
      // tree, paint() shows the "not in this course" line and the author still needs
      // to see and edit exactly what is stored. Setting it only on the else-branch
      // would leave that field empty in precisely that case.
      if (existing) urlEl.value = existing.href || "";
      if (m) { wantNode = m[1]; }
      else if (existing) { tab = "url"; }

      // showModal FIRST, then focus. A closed <dialog> is display:none, so a .focus()
      // before it is a no-op -- and showModal then autofocuses the first focusable
      // descendant, which is the first TAB BUTTON, not the field.
      showTab(tab, false);
      dialog.showModal();
      (tab === "node" ? filterEl : urlEl).focus();
      loadTree();
      refresh();
    }
  };
})();
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_link_dialog_behaviour.py -m e2e -q`
Expected: PASS.

- [ ] **Step 5: Lint**

Run: `uv run ruff format tests/test_link_dialog_behaviour.py && uv run ruff check tests/test_link_dialog_behaviour.py`
Expected: clean.

- [ ] **Step 6: Falsify the focus ordering**

Move the `(tab === "node" ? filterEl : urlEl).focus();` line to *before* `dialog.showModal()`. Run the tests. Expected: `test_initial_focus_is_the_filter_input` FAILS — focus lands on the first tab button instead. Restore.

- [ ] **Step 7: Falsify the one-dialog-at-a-time guard**

Delete the `if (callback) return;` line. Run the tests. Expected:
`test_a_second_open_while_pending_is_rejected` FAILS. Restore.

- [ ] **Step 8: Screenshot the dialog in both themes**

This is the largest new UI surface in the feature and the only one with no theme pass
yet. Open it on a real editor page and capture, in **light and dark separately**:

1. the *In this course* tab with the tree **scrolled** and a row **selected**;
2. the same with a filter applied, so `aria-disabled` ancestor rows are visible;
3. the *Web address* tab showing a rejection message.

Judge dark on its own — do not infer it from light. `--surface-raised` /
`--surface-sunken` / `--border-subtle` invert between themes, the `::backdrop` sits over
different content, and `.link-picker__item[aria-disabled="true"] { opacity: .55 }` on
`--text-secondary` is exactly the low-contrast shape this repo's `--text-tertiary`
lesson warns about. If a recessed row is unreadable in either theme, raise the opacity
or switch to a colour token rather than leaving it.

- [ ] **Step 9: Check it in the real page**

Start the server, open a unit editor, and confirm the console shows no error on page load. The toolbar link button still opens the **old `window.prompt`** at this point — Task 7 is what replaces it.

- [ ] **Step 10: Commit**

```bash
git add courses/static/courses/js/link_dialog.js tests/test_link_dialog_behaviour.py
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


def test_detached_surface_surfaces_the_conflict_message():
    # The spec's error table promises "the result is discarded with the existing
    # conflict message". A bare `return` is the same data loss with no feedback.
    src = TEXT_TOOLBAR.read_text(encoding="utf-8")
    assert "data-msg-conflict" in src
    assert "op-error" in src


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
          // on save -- so discard the result AND say so. A silent return is the same
          // data loss with no feedback, which is what the message exists to prevent.
          if (!surface.isConnected) {
            var ed = document.querySelector(".editor");
            var note = ed && ed.getAttribute("data-msg-conflict");
            if (note) {
              var bar = document.createElement("div");
              bar.className = "op-error";
              bar.textContent = note;
              (ed || document.body).prepend(bar);
              setTimeout(function () { bar.remove(); }, 6000);
            }
            return;
          }
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
Expected: PASS (4 tests).

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


def test_css_prefix_matches_the_route():
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

Open `locale/pl/LC_MESSAGES/django.po` and fill each new entry — *Insert link*, *In this course*, *Web address*, *Filter*, *Filter by title…*, *Course content*, *Loading…*, *This course has no content yet.*, *No matches.*, *matches found*, *This link's target is not in this course.*, *Could not load the course tree.*, *Retry*, *Link text*, *Remove link*, *Cancel*, *Insert*, and the three URL-rejection messages.

**Clear any fuzzy entry properly — that is TWO deletions:** the `#, fuzzy` line *and* the `#| msgid` comment above it. A fuzzy match arrives pre-filled from an *unrelated* msgid, so an un-cleared one ships a wrong translation that looks finished.

This is not hypothetical here. Measured on this repo: `makemessages` produces **17
entries needing work, 8 of them fuzzy with actively wrong pre-fills** — including
*Insert link* → `Wstaw`, *No matches.* → `Brak pasujących plików multimedialnych`
("no matching media files"), and *Remove link* → `Usuń wiersz` ("delete row"). Every one
of those would ship as a plausible-looking mistranslation. Read each fuzzy entry against
its real msgid rather than accepting the pre-fill.

Note also that *Filter*, *Cancel* and *Insert* already exist in the catalog and will come
back translated — only the genuinely new strings need writing.

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

Task 6 already covers the dialog's internals against the rendered partial. These tests
cover only what that harness cannot: the real editor page, the real fetch, a real save,
and the student-side round trip.

**Deliberately not covered here:** following a link to a *unit* in the browser. The
chapter hop is the one worth driving end to end, because it is the only one that
exercises the outline `:target` highlight; the unit hop is a plain redirect already
pinned by Task 1's `test_lesson_unit_redirects_to_lesson_page` and
`test_quiz_unit_redirects_straight_to_quiz_in_one_hop`. Adding a browser round trip for
it would re-test a `302` through a much slower harness.

- [ ] **Step 1: Write the e2e**

Follow the repo's proven e2e idiom exactly — module-level `_make_pa_user` / `_login`
helpers, the `DJANGO_ALLOW_ASYNC_UNSAFE` session fixture, and
`@pytest.mark.django_db(transaction=True)` per test. Do **not** invent a login fixture;
`tests/test_e2e_builder.py` is the pattern to mirror.

Three selector facts, each verified against the templates, that the tests depend on:

- the element type cards live in `<div class="typemenu" hidden data-type-menu>`, so
  `[data-add-toggle]` must be clicked **first** or Playwright's actionability check
  times out;
- the element list is `.element-list`, and a row's edit affordance is the button
  carrying `data-form-url` (it fetches `courses:manage_element_form`) — clicking the
  `<li data-element>` itself does nothing;
- the save control is `form[data-op="element-save"] button[type="submit"]`;
- **click `[data-node='<pk>'] > .link-picker__row`, never the `<li>` itself.** A non-leaf
  row's `<li>` contains its children's nested `<ol>`, so its bounding box spans the
  descendants too and Playwright's centre-point click lands on a *child* row — which is
  a legitimate element, so actionability passes and the wrong node is silently selected.

Create `tests/test_e2e_link_dialog.py`:

```python
"""Playwright e2e for the rich-text link dialog on the REAL editor page: insert an
internal link, save it, follow it as a student, and re-open it to remove it. The
dialog's own internals are covered by tests/test_link_dialog_behaviour.py."""

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
    """A course with part > chapter > lesson unit, optionally holding a text element
    whose body already contains an internal link (for the re-open/remove path)."""
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

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


def _add_text_element(page):
    # The type cards sit inside `<div class="typemenu" hidden>`; without the toggle
    # click Playwright waits for visibility and times out.
    page.click("[data-add-toggle]")
    page.click("[data-add-type='text']")
    page.locator(".rte-surface").wait_for()


def _open_link_dialog(page):
    page.click("[data-cmd='link']")
    dialog = page.locator(".link-dialog")
    dialog.wait_for(state="visible")
    # The tree arrives over fetch AFTER showModal, and setTabStop only runs once it has
    # painted. Pressing keys before then lands them nowhere.
    dialog.locator(".link-picker__item").first.wait_for()
    return dialog


@pytest.mark.django_db(transaction=True)
def test_insert_internal_link_then_follow_it(page, live_server):
    from courses.models import Enrollment
    from courses.models import TextElement

    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("See the chapter on quadratics")
    # Select the LAST word deterministically. `text=` matches ELEMENTS, and the whole
    # sentence is one text node, so `dblclick(".rte-surface >> text=quadratics")` would
    # double-click the container's centre and select whatever word sits there.
    page.keyboard.press("Control+Shift+ArrowLeft")
    assert page.evaluate("() => window.getSelection().toString()") == "quadratics"

    dialog = _open_link_dialog(page)
    assert dialog.locator("[data-tab='node']").get_attribute("aria-selected") == "true"
    dialog.locator(f"[data-node='{chapter.pk}'] > .link-picker__row").click()
    # Prefill precedence: a non-empty selection beats the node title.
    assert dialog.locator("[data-link-text]").input_value() == "quadratics"
    dialog.locator("[data-link-insert]").click()
    dialog.wait_for(state="hidden")

    page.click('form[data-op="element-save"] button[type="submit"]')
    page.locator(".element-list [data-element]").first.wait_for()

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
    # or written into a stylesheet the outline page never loads, passes a weaker check.
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent")


@pytest.mark.django_db(transaction=True)
def test_collapsed_caret_defaults_link_text_to_the_node_title(page, live_server):
    """The other half of the precedence rule, and what the Purpose section promises."""
    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    dialog = _open_link_dialog(page)
    dialog.locator(f"[data-node='{chapter.pk}'] > .link-picker__row").click()
    assert dialog.locator("[data-link-text]").input_value() == chapter.title


@pytest.mark.django_db(transaction=True)
def test_keyboard_only_insert(page, live_server):
    """Tab into the tree, move with arrows, press with Enter -- no mouse.

    This is what makes the roving-tabindex model real: with ~925 rows a Tab-only path
    to a deep row is not a realistic gesture, so a Tab-only test would prove nothing.
    """
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("text")
    dialog = _open_link_dialog(page)

    # Focus starts in the filter (Task 6 pins that); one Tab reaches the tree.
    assert page.evaluate(
        "() => document.activeElement.hasAttribute('data-link-filter')"
    )
    page.keyboard.press("Tab")
    assert page.evaluate(
        "() => document.activeElement.classList.contains('link-picker__item')"
    )
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert dialog.locator("[aria-selected='true'][data-node]").count() == 1

    # Finish without the mouse too. A test that advertises itself as keyboard-only must
    # not click Insert. Tab UNTIL the text field has focus rather than hard-coding a
    # count: the intervening focusables depend on state (Remove link is disabled when
    # touchedAnchors is 0; the retry button and URL input sit in hidden panels), so a
    # fixed number silently breaks when that state changes.
    for _ in range(6):
        if page.evaluate(
            "() => document.activeElement.hasAttribute('data-link-text')"
        ):
            break
        page.keyboard.press("Tab")
    else:
        raise AssertionError("never reached the link-text field by tabbing")
    page.keyboard.type("Chapter")
    page.keyboard.press("Enter")
    dialog.wait_for(state="hidden")


@pytest.mark.django_db(transaction=True)
def test_dismissing_restores_the_caret(page, live_server):
    """The case the spec says would silently regress if the range were not cloned.

    A source grep for "cloneRange()" passes for code that clones the wrong object,
    clones after showModal(), or drops the restore entirely.
    """
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("See the chapter on quadratics")
    page.keyboard.press("Control+Shift+ArrowLeft")
    assert page.evaluate("() => window.getSelection().toString()") == "quadratics"

    _open_link_dialog(page)
    page.keyboard.press("Escape")
    page.locator(".link-dialog").wait_for(state="hidden")
    assert page.evaluate("() => window.getSelection().toString()") == "quadratics"


@pytest.mark.django_db(transaction=True)
def test_detached_surface_discards_and_explains(page, live_server):
    """A data-loss path: without this the author sees a successful insert and then
    loses the link on save. Two source greps cannot tell dead code from live code."""
    owner = _make_pa_user("pa")
    course, chapter, unit = _seed(owner)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)
    _add_text_element(page)

    page.locator(".rte-surface").click()
    page.keyboard.type("text")
    dialog = _open_link_dialog(page)
    # Simulate editor.js swapping the pane out from under the open dialog.
    page.evaluate("() => document.querySelector('.rte-surface').remove()")
    dialog.locator(f"[data-node='{chapter.pk}'] > .link-picker__row").click()
    dialog.locator("[data-link-text]").fill("Chapter")
    dialog.locator("[data-link-insert]").click()
    dialog.wait_for(state="hidden")

    assert page.locator(".op-error").count() == 1
    conflict = page.locator(".editor").get_attribute("data-msg-conflict")
    assert page.locator(".op-error").inner_text().strip() == conflict.strip()


@pytest.mark.django_db(transaction=True)
def test_reopening_prefills_and_remove_unwraps(page, live_server):
    owner = _make_pa_user("pa")
    course, _chapter, unit = _seed(owner, with_link=True)
    _login(page, live_server, "pa")
    _open_editor(page, live_server, course, unit)

    # The row's edit affordance is the button carrying data-form-url; clicking the
    # <li data-element> itself does nothing.
    page.click(".element-list [data-form-url]")
    page.locator(".rte-surface").wait_for()
    page.click(".rte-surface a")                # caret inside the link

    dialog = _open_link_dialog(page)
    assert dialog.locator("[data-tab='node']").get_attribute("aria-selected") == "true"
    selected = dialog.locator("[aria-selected='true'][data-node]")
    assert selected.count() == 1
    # The preselected row must be scrolled into view, not merely marked.
    assert selected.is_visible()

    dialog.locator("[data-link-remove]").click()
    dialog.wait_for(state="hidden")
    assert page.locator(".rte-surface a").count() == 0
    assert "quadratics" in page.locator(".rte-surface").inner_text()
```

- [ ] **Step 2: Run the e2e**

Run: `uv run pytest tests/test_e2e_link_dialog.py -m e2e -q`
Expected: PASS. `-m e2e` is mandatory — without it pytest deselects everything and
exits 5. Run it in the foreground; a backgrounded e2e run hides failures.

If a selector fails, fix it against the rendered page rather than weakening the
assertion — every selector here was read off the templates, but the editor's fragment
swaps can change what is attached at a given moment.

- [ ] **Step 3: Falsify the keyboard test**

Comment out the `keydown` listener on `mount` in `link_dialog.js`. Confirm
`test_keyboard_only_insert` FAILS (ArrowDown/Enter select nothing). Restore it.

- [ ] **Step 4: Lint the new file**

Run: `uv run ruff format tests/test_e2e_link_dialog.py && uv run ruff check tests/test_e2e_link_dialog.py`

- [ ] **Step 5: Full suite and lint**

Run: `uv run pytest -q`
Run: `uv run pytest -m e2e -q`
Run: `uv run ruff check . && uv run ruff format --check .`

All green. If a failure appears that your diff cannot explain, do not fold a fix into
this branch — an unrelated or flaky failure belongs in its own PR.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_link_dialog.py
git commit -m "test(links): end-to-end coverage for the link dialog"
```

---

## Self-Review

**Spec coverage.** §1 permalink → Task 1. §2 outline anchors → Task 2. §3 picker endpoint, partials, roving tabindex, chip, fetch policy, filter states → Tasks 3, 6. §4 dialog markup, feature detection, tabs, ownership split, insertion rules, URL contract, dismissal, prefill precedence → Tasks 4, 5, 6, 7. §5 styling → Tasks 5 (preview-inert), 8 (student-side). §Testing → distributed, with the falsification steps called out per task. §i18n → Task 9.

**Known gap, deliberate:** the spec's "wrong-surface case" is a *claim to be measured* — `applyCmd` calls `surface.focus()` before any branch reads the selection, which may make the mis-insert impossible. Task 7 ships the containment guard (cheap, correct either way) but no test asserts the mis-insert, because a test written before reproducing it would pass vacuously. Reproduce it against pre-change code during Task 7 and record the finding in the PR; add the test only if it is real.

**Deliberately NOT tested in Task 4:** the raw-`>`-in-an-attribute hazard. `link_apply.js` walks the live DOM, where the browser's parser has already resolved attribute boundaries — `querySelectorAll("a")` cannot be fooled by `title="a > b"`. That hazard is a *string-scanning* problem and belongs to part 2's `courses/richtext.py`, which does scan strings. A test for it here could never go red for a real defect, which is exactly the vacuous guard the Global Constraints forbid.

**Ordering invariant across Task 4:** `surface.normalize()` runs **last**, after the selection is set. Normalising merges adjacent text nodes into the first and detaches the rest, and `Range.setStartAfter` on a parentless node throws `InvalidNodeTypeError` — so a caret pinned to a pre-normalise node handle is a crash, not a cosmetic bug. The removal path uses a marker node for the same reason.

**Type consistency.** `window.libliLinkApply` exposes `anchorsFor`, `enclosing`, `apply`, `normalizeUrl` — defined in Task 4 and called with those exact names in Tasks 6 and 7. `window.libliLinkDialog.open(opts, cb)` takes `{existing, touchedAnchors, selectionText}` in Task 6 and is called with exactly those keys in Task 7. `normalizeUrl`'s reject keys (`"scheme"`, `"protocol-relative"`, `"relative"`) match the `data-msg` attribute values in Task 5's partial.
