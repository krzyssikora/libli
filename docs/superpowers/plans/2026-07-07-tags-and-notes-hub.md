# Tags & notes hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified **"Tags & notes"** hub (two tabs: *By course* overview + the existing *Manage tags* page) plus a **per-course notes index** for revision, over the existing `notes`/`tags` schema — no new model, no migration.

**Architecture:** Read/aggregate services in `notes` and `tags` (one-way `notes` → `tags` import), thin `@login_required` views in `notes`, server-rendered templates reusing existing note-card / tag-chip / tab-bar CSS vocabulary. All surfaces are author-scoped and restricted to `accessible_courses(user)`.

**Tech Stack:** Django 5.2 (server-rendered), pytest + factory_boy against real PostgreSQL, Playwright e2e, `uv run` for all tooling, EN/PL i18n (gettext).

## Global Constraints

- **Tooling:** run Python/ruff/pytest via `uv run` (bare `ruff`/`pytest`/`python` are NOT on PATH). CI checks `uv run ruff format --check` — always run `uv run ruff check --fix . && uv run ruff format .` before committing.
- **No model changes:** `uv run python manage.py makemigrations --check` MUST report "No changes detected" at the end. This slice touches no model.
- **Auth in tests:** a bare `UserFactory()` cannot log in (unverified email). Use `make_verified_user(...)` / `make_login(client, name)` / the enrolled-user helpers.
- **Scoping invariants:** every `Note`/`Tag`/`UnitTag` query filters `author=request.user`; every course set is restricted to `courses.access.accessible_courses(user)`.
- **i18n:** all new user-facing strings wrapped in `{% trans %}`/`gettext`; PL catalog (`locale/pl/LC_MESSAGES/django.po`) MUST stay **0 fuzzy / 0 obsolete**. `makemessages` is known to mis-guess fuzzies — verify each new `msgstr` by hand.
- **Read-only index:** the per-course notes view and overview render NO edit/delete/create controls; note mutation stays on the lesson page.

---

### Task 1: Notes aggregation services

**Files:**
- Modify: `notes/services.py`
- Test: `tests/test_tags_notes_hub.py` (create)

**Interfaces:**
- Produces:
  - `note_counts_by_course(author) -> dict[int, int]` — `{course_id: note_count}` over the author's notes in **accessible** courses, lesson units only.
  - `course_notes(author, course) -> list[dict]` — `[{"unit": ContentNode, "groups": [(element_or_None, [Note, ...]), ...]}, ...]`; lesson units in outline (pre-order) position, groups ordered by `Element.order` with the `None` (unanchored) bucket last, notes within a block ordered `created, pk`; units with no notes omitted.
- Consumes: `courses.rollups.units_in_order`, `courses.access.accessible_courses`, `courses.models.ContentNode`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tags_notes_hub.py` (create the file with this header + tests):

**Import discipline (read before writing the header):** this one test file grows across
Tasks 1–7. Because each task runs `ruff check --fix` on it, an import that is present but
not yet used by *any* landed test is auto-deleted (F401) at that task's commit — and an
unused-import that survives would fail `ruff check`. So each task adds **only the imports
its own tests use**; later tasks append their imports when they land. Task 1's header
imports only what Task 1 uses:

```python
import pytest

from courses.models import Enrollment
from notes import services
from tests.factories import (
    CourseFactory,
    ContentNodeFactory,
    ElementFactory,
    make_verified_user,
)

pytestmark = pytest.mark.django_db


def _user(n=0):
    return make_verified_user(username=f"hub{n}", email=f"hub{n}@test.example.com")


def _enroll(user, course):
    Enrollment.objects.create(student=user, course=course, source="manual")


def _lesson(course, title="U"):
    return ContentNodeFactory(course=course, title=title)  # lesson unit by default


# ---- Task 1: notes services ----

def test_note_counts_by_course_counts_accessible_lessons():
    me = _user(1)
    c1 = CourseFactory(title="Alpha")
    c2 = CourseFactory(title="Beta")
    _enroll(me, c1)
    _enroll(me, c2)
    u1 = _lesson(c1)
    u2 = _lesson(c2)
    services.create_note(me, u1, None, "a")
    services.create_note(me, u1, None, "b")
    services.create_note(me, u2, None, "c")
    counts = services.note_counts_by_course(me)
    assert counts == {c1.pk: 2, c2.pk: 1}


def test_note_counts_by_course_excludes_inaccessible():
    me = _user(2)
    other_course = CourseFactory()  # not enrolled, not owner
    u = _lesson(other_course)
    services.create_note(me, u, None, "secret")  # service create bypasses access on purpose
    assert services.note_counts_by_course(me) == {}


def test_course_notes_orders_by_element_order_reorder_stable():
    me = _user(3)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    e1 = ElementFactory(unit=unit)
    e2 = ElementFactory(unit=unit)
    assert e1.order < e2.order
    services.create_note(me, unit, e2.pk, "on-e2")
    services.create_note(me, unit, e1.pk, "on-e1")
    rows = services.course_notes(me, course)
    assert len(rows) == 1
    groups = rows[0]["groups"]
    assert [g[0].pk for g in groups] == [e1.pk, e2.pk]  # by Element.order, not creation
    # reorder: make e1 come AFTER e2
    e1.order = e2.order + 5
    e1.save(update_fields=["order"])
    rows = services.course_notes(me, course)
    assert [g[0].pk for g in rows[0]["groups"]] == [e2.pk, e1.pk]


def test_course_notes_unanchored_bucket_last_and_intrablock_order():
    me = _user(4)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    e1 = ElementFactory(unit=unit)
    n1 = services.create_note(me, unit, e1.pk, "first")
    n2 = services.create_note(me, unit, e1.pk, "second")
    services.create_note(me, unit, None, "unanchored")
    groups = services.course_notes(me, course)[0]["groups"]
    assert groups[0][0] == e1
    assert [n.pk for n in groups[0][1]] == [n1.pk, n2.pk]  # created, pk
    assert groups[-1][0] is None
    assert groups[-1][1][0].body == "unanchored"


def test_course_notes_units_in_outline_order_skip_empty():
    me = _user(5)
    course = CourseFactory()
    _enroll(me, course)
    u1 = _lesson(course, "First")
    u2 = _lesson(course, "Second")  # no notes -> omitted
    u3 = _lesson(course, "Third")
    services.create_note(me, u3, None, "z")
    services.create_note(me, u1, None, "a")
    rows = services.course_notes(me, course)
    assert [r["unit"].pk for r in rows] == [u1.pk, u3.pk]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tags_notes_hub.py -x -q`
Expected: FAIL — `AttributeError: module 'notes.services' has no attribute 'note_counts_by_course'`.

- [ ] **Step 3: Implement the two services**

In `notes/services.py`: add a new line `from collections import OrderedDict` alongside the existing `from collections import defaultdict`, and add `from courses.access import accessible_courses`. Then append:

```python
def note_counts_by_course(author):
    """{course_id: count} of the author's notes per accessible course (lesson units)."""
    rows = (
        Note.objects.filter(
            author=author,
            unit__course__in=accessible_courses(author),
            unit__unit_type=ContentNode.UnitType.LESSON,
        )
        .values("unit__course_id")
        .annotate(n=Count("pk"))
    )
    return {r["unit__course_id"]: r["n"] for r in rows}


def course_notes(author, course):
    """Ordered per-course notes for the revision index.

    Returns [{"unit": ContentNode, "groups": [(element_or_None, [Note, ...]), ...]}, ...]:
    lesson units in outline (pre-order) position; within a unit, groups ordered by the
    block's Element.order (the None/unanchored bucket last), and notes within a block in
    created, pk order. Units with no notes are omitted. No N+1: one nodes query
    (units_in_order) + one Note query (element select_related supplies Element.order).
    """
    from courses.rollups import units_in_order

    notes = list(
        Note.objects.filter(author=author, unit__course=course)
        .select_related("element")
        .order_by("created", "pk")
    )
    by_unit = OrderedDict()
    for note in notes:
        by_unit.setdefault(note.unit_id, []).append(note)

    result = []
    for unit in units_in_order(course):
        if unit.unit_type != ContentNode.UnitType.LESSON:
            continue
        unit_notes = by_unit.get(unit.pk)
        if not unit_notes:
            continue
        groups_map = OrderedDict()  # element_id -> [notes] (insertion order == created, pk)
        for note in unit_notes:
            groups_map.setdefault(note.element_id, []).append(note)
        anchored = [(eid, ns) for eid, ns in groups_map.items() if eid is not None]
        anchored.sort(key=lambda kv: (kv[1][0].element.order, kv[0]))
        ordered_groups = [(ns[0].element, ns) for _eid, ns in anchored]
        if None in groups_map:
            ordered_groups.append((None, groups_map[None]))
        result.append({"unit": unit, "groups": ordered_groups})
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tags_notes_hub.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix notes/services.py tests/test_tags_notes_hub.py
uv run ruff format notes/services.py tests/test_tags_notes_hub.py
git add notes/services.py tests/test_tags_notes_hub.py
git commit -m "feat(notes): note_counts_by_course + course_notes aggregation services"
```

---

### Task 2: Tags-by-course service

**Files:**
- Modify: `tags/services.py`
- Test: `tests/test_tags_notes_hub.py`

**Interfaces:**
- Produces: `tags_by_course(author) -> OrderedDict[Course, list[Tag]]` — distinct tags the author has used on each **accessible** course's units, courses keyed by `Course` object, tags in `Lower(name)` order. One `UnitTag` query.
- Consumes: `courses.access.accessible_courses` (already imported in `tags/services.py`), `tags.models.UnitTag`.

- [ ] **Step 1: Write the failing tests**

First add the imports Task 2 uses to the top of `tests/test_tags_notes_hub.py`: add
`from tags import services as tag_services`, and add `TagFactory` and `UnitTagFactory` to
the `from tests.factories import (...)` block. Then append:

```python
# ---- Task 2: tags_by_course ----

def test_tags_by_course_groups_distinct_tags_accessible_only():
    me = _user(6)
    c1 = CourseFactory(title="Alpha")
    c2 = CourseFactory(title="Beta")
    _enroll(me, c1)
    _enroll(me, c2)
    u1a = _lesson(c1)
    u1b = _lesson(c1)
    u2 = _lesson(c2)
    t1 = TagFactory(author=me, name="exam")
    t2 = TagFactory(author=me, name="hard")
    UnitTagFactory(tag=t1, unit=u1a)
    UnitTagFactory(tag=t1, unit=u1b)  # same tag twice in c1 -> distinct
    UnitTagFactory(tag=t2, unit=u1a)
    UnitTagFactory(tag=t1, unit=u2)
    out = tag_services.tags_by_course(me)
    assert set(out[c1]) == {t1, t2}
    assert list(out[c2]) == [t1]


def test_tags_by_course_excludes_inaccessible_and_other_authors():
    me = _user(7)
    other = _user(8)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    mine = TagFactory(author=me, name="mine")
    theirs = TagFactory(author=other, name="theirs")
    UnitTagFactory(tag=mine, unit=unit)
    UnitTagFactory(tag=theirs, unit=unit)
    inaccessible = _lesson(CourseFactory())  # me not enrolled
    UnitTagFactory(tag=TagFactory(author=me, name="lost"), unit=inaccessible)
    out = tag_services.tags_by_course(me)
    assert list(out[course]) == [mine]
    assert all(c == course for c in out)  # inaccessible course absent
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_notes_hub.py -k tags_by_course -q`
Expected: FAIL — `AttributeError: module 'tags.services' has no attribute 'tags_by_course'`.

- [ ] **Step 3: Implement**

Append to `tags/services.py` (all imports already present: `OrderedDict`, `defaultdict`, `Lower`, `accessible_courses`, `UnitTag`):

```python
def tags_by_course(author):
    """OrderedDict {Course: [Tag, ...]} — distinct tags the author used on each accessible
    course's units, courses keyed by object, tags in Lower(name) order. One UnitTag query."""
    links = (
        UnitTag.objects.filter(
            tag__author=author, unit__course__in=accessible_courses(author)
        )
        .select_related("tag", "unit__course")
        .order_by(Lower("tag__name"), "tag__pk")
    )
    by_course = OrderedDict()
    seen = defaultdict(set)  # course_id -> {tag_id}
    for link in links:
        course = link.unit.course
        if link.tag_id not in seen[course.pk]:
            seen[course.pk].add(link.tag_id)
            by_course.setdefault(course, []).append(link.tag)
    return by_course
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tags_notes_hub.py -k tags_by_course -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix tags/services.py tests/test_tags_notes_hub.py
uv run ruff format tags/services.py tests/test_tags_notes_hub.py
git add tags/services.py tests/test_tags_notes_hub.py
git commit -m "feat(tags): tags_by_course aggregation service"
```

---

### Task 3: "By course" overview page

**Files:**
- Modify: `notes/views.py`, `notes/urls.py`
- Create: `templates/_tags_notes_tabs.html`, `notes/templates/notes/overview.html`, `notes/templates/notes/_overview_card.html`
- Modify: `core/static/core/css/app.css` (add `.tnhub__tabs`/`.tnhub__tab`), `notes/static/notes/css/notes.css` (add overview-card rules)
- Test: `tests/test_tags_notes_hub.py`

**Interfaces:**
- Produces: URL `notes:overview` at `/tags-and-notes/`; view `overview(request)` rendering `notes/overview.html` with context `{"cards": [{"course", "note_count", "tags"}], "hub_tab": "by_course"}`.
- Consumes: `notes.services.note_counts_by_course`, `tags.services.tags_by_course`, `courses.models.Course`.

- [ ] **Step 1: Write the failing tests**

First add `from django.urls import reverse` to the top of `tests/test_tags_notes_hub.py`
(Task 3 is the first task to use `reverse`). Then append:

```python
# ---- Task 3: overview page ----

def _client_login(client, user):
    client.force_login(user)


def test_overview_union_sorted_notes_link_and_chip_href(client):
    me = _user(9)
    c_notes = CourseFactory(title="Zed notes-only")
    c_tags = CourseFactory(title="Alpha tags-only")
    c_both = CourseFactory(title="Mid both")
    c_none = CourseFactory(title="None")
    for c in (c_notes, c_tags, c_both, c_none):
        _enroll(me, c)
    services.create_note(me, _lesson(c_notes), None, "n")
    services.create_note(me, _lesson(c_both), None, "n")
    t = TagFactory(author=me, name="exam", color="teal")
    UnitTagFactory(tag=t, unit=_lesson(c_tags))
    UnitTagFactory(tag=TagFactory(author=me, name="k"), unit=_lesson(c_both))
    client.force_login(me)
    resp = client.get(reverse("notes:overview"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # union {notes, tags, both} present, "None" course absent
    assert "Zed notes-only" in body and "Alpha tags-only" in body and "Mid both" in body
    assert reverse("courses:course_outline", args=[c_none.slug]) not in body
    # alphabetical by title: Alpha < Mid < Zed
    assert body.index("Alpha tags-only") < body.index("Mid both") < body.index("Zed notes-only")
    # notes link only for note-bearing courses
    assert reverse("notes:course_notes", args=[c_notes.slug]) in body
    assert reverse("notes:course_notes", args=[c_tags.slug]) not in body
    # tag chip href = course_outline?tags=<pk>
    assert f'{reverse("courses:course_outline", args=[c_tags.slug])}?tags={t.pk}' in body
    # tab bar: By course active
    assert "tnhub__tab" in body and "is-on" in body


def test_overview_empty_state(client):
    me = _user(10)
    client.force_login(me)
    resp = client.get(reverse("notes:overview"))
    assert resp.status_code == 200
    assert "tnhub__card" not in resp.content.decode()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_notes_hub.py -k overview -q`
Expected: FAIL — `NoReverseMatch: 'overview' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the route**

In `notes/urls.py`, add to `urlpatterns` (above the existing `note_add` path is fine):

```python
    path("tags-and-notes/", views.overview, name="overview"),
```

- [ ] **Step 4: Add the view**

In `notes/views.py`, add imports near the top:

```python
from courses.models import Course
from tags import services as tag_services
```

Then add:

```python
@login_required
def overview(request):
    note_counts = services.note_counts_by_course(request.user)  # {course_id: count}
    tags_by_course = tag_services.tags_by_course(request.user)  # {Course: [Tag]}
    by_pk = {c.pk: c for c in tags_by_course}
    note_only_ids = [cid for cid in note_counts if cid not in by_pk]
    by_pk.update(Course.objects.in_bulk(note_only_ids))  # one batched query, no N+1
    cards = [
        {
            "course": course,
            "note_count": note_counts.get(course.pk, 0),
            "tags": tags_by_course.get(course, []),
        }
        for course in by_pk.values()
    ]
    cards.sort(key=lambda c: c["course"].title)
    return render(
        request, "notes/overview.html", {"cards": cards, "hub_tab": "by_course"}
    )
```

- [ ] **Step 5: Create the shared tab-bar partial**

Create `templates/_tags_notes_tabs.html`:

```django
{% load i18n %}
<nav class="tnhub__tabs" aria-label="{% trans 'Tags and notes sections' %}">
  <a class="tnhub__tab{% if hub_tab == 'by_course' %} is-on{% endif %}"
     href="{% url 'notes:overview' %}">{% trans "By course" %}</a>
  <a class="tnhub__tab{% if hub_tab == 'manage_tags' %} is-on{% endif %}"
     href="{% url 'tags:my_tags' %}">{% trans "Manage tags" %}</a>
</nav>
```

- [ ] **Step 6: Create the overview templates**

Create `notes/templates/notes/overview.html`:

```django
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "Tags & notes" %} — libli{% endblock %}
{% block extra_css %}{{ block.super }}
<link rel="stylesheet" href="{% static 'notes/css/notes.css' %}">
<link rel="stylesheet" href="{% static 'tags/css/tags.css' %}">
{% endblock %}
{% block content %}
<section class="tnhub">
  <h1>{% trans "Tags & notes" %}</h1>
  {% include "_tags_notes_tabs.html" %}
  {% if not cards %}
    <p class="tnhub__empty">{% trans "You haven't added any notes or tags yet." %}</p>
  {% else %}
    <div class="tnhub__cards">
      {% for card in cards %}{% include "notes/_overview_card.html" with card=card %}{% endfor %}
    </div>
  {% endif %}
</section>
{% endblock %}
```

Create `notes/templates/notes/_overview_card.html`:

```django
{% load i18n %}
<article class="tnhub__card">
  <h2 class="tnhub__card-title">
    <a href="{% url 'courses:course_outline' slug=card.course.slug %}">{{ card.course.title }}</a>
  </h2>
  {% if card.note_count %}
    <a class="tnhub__card-notes" href="{% url 'notes:course_notes' slug=card.course.slug %}">
      {% blocktrans count n=card.note_count %}{{ n }} note{% plural %}{{ n }} notes{% endblocktrans %}
    </a>
  {% endif %}
  {% if card.tags %}
    <div class="tnhub__card-tags">
      {% for tag in card.tags %}
        <a class="tag-chip tag-chip--{{ tag.color }}"
           href="{% url 'courses:course_outline' slug=card.course.slug %}?tags={{ tag.pk }}">{{ tag.name }}</a>
      {% endfor %}
    </div>
  {% endif %}
</article>
```

Note: `notes:course_notes` is referenced here and is created in Task 5. If executing strictly in order, temporarily this `{% url %}` will error only when a card has notes; Task 3's tests seed note-bearing courses, so **add the Task 5 route now** as a stub to keep this task shippable — OR run Task 5's Step "add route+view" before Task 3's tests. To keep tasks independent, add the route+view stub here:

In `notes/urls.py` also add:

```python
    path("courses/<slug:slug>/notes/", views.course_notes, name="course_notes"),
```

and a minimal stub in `notes/views.py` (fully implemented in Task 5):

```python
@login_required
def course_notes(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    return render(
        request,
        "notes/course_notes.html",
        {"course": course, "units": services.course_notes(request.user, course)},
    )
```

Create a minimal `notes/templates/notes/course_notes.html` placeholder so the stub renders (Task 5 fleshes it out):

```django
{% extends "base.html" %}{% load i18n %}
{% block content %}<section class="course-notes"><h1>{{ course.title }}</h1></section>{% endblock %}
```

- [ ] **Step 7: Add the tab-bar CSS (global) and overview card CSS**

Append to `core/static/core/css/app.css`:

```css
/* Tags & notes hub tab bar (shared by the overview + my_tags pages) */
.tnhub__tabs {
  display: flex;
  gap: var(--space-2);
  margin: var(--space-3) 0 var(--space-4);
  border-bottom: 1px solid var(--border-subtle);
}
.tnhub__tab {
  padding: var(--space-2) var(--space-3);
  color: var(--text-secondary);
  border-bottom: 2px solid transparent;
  text-decoration: none;
  margin-bottom: -1px;
}
.tnhub__tab:hover { color: var(--text-primary); }
.tnhub__tab.is-on {
  color: var(--text-primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}
```

Append to `notes/static/notes/css/notes.css`:

```css
.tnhub__cards {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
}
.tnhub__card {
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  padding: var(--space-3);
  background: var(--surface-raised);
}
.tnhub__card-title { margin: 0 0 var(--space-2); font-size: 1rem; }
.tnhub__card-notes {
  display: inline-block;
  margin-bottom: var(--space-2);
  color: var(--primary);
  font-weight: 600;
  text-decoration: none;
}
.tnhub__card-notes:hover { text-decoration: underline; }
.tnhub__card-tags { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.tnhub__empty, .course-notes__empty { color: var(--text-secondary); }
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_tags_notes_hub.py -k overview -q`
Expected: PASS (2 tests). If `collectstatic`-related asset errors appear, ignore (dev server only).

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check --fix notes/ tests/test_tags_notes_hub.py
uv run ruff format notes/ tests/test_tags_notes_hub.py
git add notes/ templates/_tags_notes_tabs.html core/static/core/css/app.css tests/test_tags_notes_hub.py
git commit -m "feat(notes): Tags & notes 'By course' overview page + shared tab bar"
```

---

### Task 4: "Manage tags" tab wiring

**Files:**
- Modify: `tags/views.py` (pass `hub_tab="manage_tags"` on both `my_tags` render paths)
- Modify: `tags/templates/tags/my_tags.html` (h1 → "Tags & notes", include tab bar)
- Test: `tests/test_tags_notes_hub.py`

**Interfaces:**
- Consumes: `notes:overview` (Task 3), `templates/_tags_notes_tabs.html` (Task 3).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tags_notes_hub.py`:

```python
# ---- Task 4: manage tags tab ----

def test_my_tags_renders_hub_tabs_manage_active(client):
    me = _user(11)
    client.force_login(me)
    resp = client.get(reverse("tags:my_tags"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'class="tnhub__tabs"' in body
    assert reverse("notes:overview") in body
    # Manage tags tab carries is-on
    assert 'href="' + reverse("tags:my_tags") + '"' in body
    idx = body.index(reverse("tags:my_tags"))
    assert "is-on" in body[body.index("tnhub__tab") : idx + 40]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_notes_hub.py -k my_tags_renders -q`
Expected: FAIL — `assert 'class="tnhub__tabs"' in body` (tab bar not present yet).

- [ ] **Step 3: Pass `hub_tab` from the view**

In `tags/views.py`, `my_tags`:

```python
@login_required
def my_tags(request):
    return render(
        request,
        "tags/my_tags.html",
        {
            "tags_by_tag": services.units_by_tag(request.user),
            "palette": TAG_PALETTE,
            "hub_tab": "manage_tags",
        },
    )
```

And in `tag_recolor`'s 422 re-render of `tags/my_tags.html` (the `except ValidationError` branch), add `"hub_tab": "manage_tags"` to that context dict too, so the tab bar renders on the error path.

- [ ] **Step 4: Include the tab bar in the template**

In `tags/templates/tags/my_tags.html`, change the `<h1>` line and add the include immediately after it:

```django
  <h1>{% trans "Tags & notes" %}</h1>
  {% include "_tags_notes_tabs.html" %}
```

(Leave `{% block head_title %}{% trans "My tags" %} — libli{% endblock %}` unchanged — this keeps the `"My tags"` msgid in use so the PL catalog gains no obsolete entry.)

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_tags_notes_hub.py -k my_tags_renders -q`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --fix tags/ tests/test_tags_notes_hub.py
uv run ruff format tags/ tests/test_tags_notes_hub.py
git add tags/ tests/test_tags_notes_hub.py
git commit -m "feat(tags): fold My tags into the Tags & notes hub as the Manage tags tab"
```

---

### Task 5: Per-course notes index view

**Files:**
- Modify: `notes/views.py` (course_notes already stubbed in Task 3 — no change needed unless refining), `notes/static/notes/js/notes.js`, `notes/static/notes/css/notes.css`, `templates/courses/lesson_unit.html` (DRY the `#notes-i18n` block into a partial)
- Create: `notes/templates/notes/course_notes.html` (replace the Task-3 placeholder), `notes/templates/notes/_readonly_note_card.html`, `notes/templates/notes/_notes_i18n.html`
- Test: `tests/test_tags_notes_hub.py`

**Interfaces:**
- Consumes: `notes.services.course_notes` (Task 1), `courses:lesson_unit`, `notes:overview`.
- Produces: the fully-rendered `notes:course_notes` page with clamp-ready note cards.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tags_notes_hub.py`:

```python
# ---- Task 5: per-course notes index ----

def test_course_notes_access_gate(client):
    me = _user(12)
    course = CourseFactory()  # not enrolled
    unit = _lesson(course)
    services.create_note(me, unit, None, "n")
    client.force_login(me)
    # inaccessible existing course -> 403
    assert client.get(reverse("notes:course_notes", args=[course.slug])).status_code == 403
    # nonexistent slug -> 404
    assert client.get(reverse("notes:course_notes", args=["nope-xyz"])).status_code == 404
    _enroll(me, course)
    assert client.get(reverse("notes:course_notes", args=[course.slug])).status_code == 200


def test_course_notes_shows_own_notes_ordered_with_gotolesson(client):
    me = _user(13)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    n = services.create_note(me, unit, el.pk, "MY REVISION NOTE")
    other = _user(14)
    _enroll(other, course)
    services.create_note(other, unit, el.pk, "OTHER NOTE")
    client.force_login(me)
    resp = client.get(reverse("notes:course_notes", args=[course.slug]))
    body = resp.content.decode()
    assert "MY REVISION NOTE" in body
    assert "OTHER NOTE" not in body  # author scoping
    lesson_url = reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    assert f'{lesson_url}?notes=1#note-{n.pk}' in body
    # read-only: no edit/delete controls
    assert "note-action--edit" not in body and "note-action--delete" not in body


def test_course_notes_empty_state(client):
    me = _user(15)
    course = CourseFactory()
    _enroll(me, course)
    _lesson(course)
    client.force_login(me)
    resp = client.get(reverse("notes:course_notes", args=[course.slug]))
    assert resp.status_code == 200
    assert "course-notes__unit" not in resp.content.decode()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_notes_hub.py -k course_notes -q`
Expected: FAIL — the Task-3 placeholder template renders neither the notes nor the "Go to lesson" link.

- [ ] **Step 3: Extract the `#notes-i18n` block into a shared partial**

Create `notes/templates/notes/_notes_i18n.html` with the exact markup currently inline in `lesson_unit.html` (lines 26-35):

```django
{% load i18n %}
<div id="notes-i18n" hidden
     data-msg-save="{% trans 'Save' %}"
     data-msg-cancel="{% trans 'Cancel' %}"
     data-msg-delete-q="{% trans 'Delete?' %}"
     data-msg-yes="{% trans 'Yes' %}"
     data-msg-no="{% trans 'No' %}"
     data-msg-confirm-delete="{% trans 'Confirm deletion' %}"
     data-msg-add-more="{% trans 'Add another note' %}"
     data-msg-show-more="{% trans 'Show more' %}"
     data-msg-show-less="{% trans 'Show less' %}"></div>
```

In `templates/courses/lesson_unit.html`, replace those inline lines (26-35) with:

```django
  {% include "notes/_notes_i18n.html" %}
```

- [ ] **Step 4: Create the read-only card partial**

Create `notes/templates/notes/_readonly_note_card.html`:

```django
{% load i18n notes_extras %}
<article class="note-card" id="note-{{ note.pk }}">
  <p class="note-card__body">{{ note.body|linebreaksbr }}</p>
  <p class="note-card__meta">
    {% if note|note_edited %}{% blocktrans with when=note.updated|timesince %}edited {{ when }} ago{% endblocktrans %}{% else %}{% blocktrans with when=note.updated|timesince %}added {{ when }} ago{% endblocktrans %}{% endif %}
  </p>
  <p class="note-card__gotolesson">
    <a href="{% url 'courses:lesson_unit' slug=course.slug node_pk=note.unit_id %}?notes=1#note-{{ note.pk }}">{% trans "Go to lesson" %}</a>
  </p>
</article>
```

- [ ] **Step 5: Replace the course_notes template**

Overwrite `notes/templates/notes/course_notes.html`:

```django
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% blocktrans with title=course.title %}Notes — {{ title }}{% endblocktrans %} — libli{% endblock %}
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'notes/css/notes.css' %}">{% endblock %}
{% block content %}
<section class="course-notes" data-course-notes>
  <div class="course-notes__head">
    <h1>{% blocktrans with title=course.title %}Notes — {{ title }}{% endblocktrans %}</h1>
    <a class="btn btn--ghost btn--small" href="{% url 'notes:overview' %}">{% trans "Tags & notes" %}</a>
  </div>
  {% if not units %}
    <p class="course-notes__empty">{% trans "No notes in this course yet." %}</p>
  {% else %}
    {% for row in units %}
      <section class="course-notes__unit">
        <h2 class="course-notes__unit-title">{{ row.unit.title }}</h2>
        {% for element, notes in row.groups %}
          {% if not element %}<h3 class="course-notes__general">{% trans "General" %}</h3>{% endif %}
          {% for note in notes %}{% include "notes/_readonly_note_card.html" with note=note course=course %}{% endfor %}
        {% endfor %}
      </section>
    {% endfor %}
  {% endif %}
</section>
{% include "notes/_notes_i18n.html" %}
{% endblock %}
{% block extra_js %}{{ block.super }}<script src="{% static 'notes/js/notes.js' %}" defer></script>{% endblock %}
```

**Layout note (intentional):** only the unanchored bucket gets a visible `General`
heading; anchored note groups render back-to-back with no per-block heading. This is
deliberate and consistent with the lesson panel, whose `note-card__on` block label is
itself `visually-hidden` — the reading order already follows block order, and each card's
"Go to lesson" link resolves the exact block. Do NOT add per-block headings (out of the
spec's scope).

- [ ] **Step 6: Wire the standalone clamp init in notes.js**

In `notes/static/notes/js/notes.js`, inside the file-level IIFE's init section (near the existing `requestAnimationFrame` that calls `setupClamp(panel)` for already-open panels, ~line 565-571), add a standalone-page init that runs the same clamp helper over the read-only index:

```javascript
  var courseNotes = document.querySelector("[data-course-notes]");
  if (courseNotes) {
    requestAnimationFrame(function () { setupClamp(courseNotes); });
  }
```

(`setupClamp` and `I18N` are already in scope in the IIFE; `I18N` is populated from the `#notes-i18n` element the template renders, so the "Show more"/"Show less" labels localize.)

- [ ] **Step 7: Add course-notes list CSS**

Append to `notes/static/notes/css/notes.css`:

```css
.course-notes__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.course-notes__unit { margin-bottom: var(--space-5); }
.course-notes__unit-title {
  font-size: 1.1rem;
  margin: 0 0 var(--space-2);
  padding-bottom: var(--space-1);
  border-bottom: 1px solid var(--border-subtle);
}
.course-notes__general {
  font-size: .8rem;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--text-secondary);
  margin: var(--space-2) 0 var(--space-1);
}
.note-card__gotolesson { margin: .15rem 0 0; }
.note-card__gotolesson a { font-size: .78rem; font-weight: 600; color: var(--primary); text-decoration: none; }
.note-card__gotolesson a:hover { text-decoration: underline; }
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_tags_notes_hub.py -k course_notes -q`
Expected: PASS (3 tests). Also re-run the notes regression suite to confirm the `lesson_unit.html` i18n refactor didn't break anything: `uv run pytest tests/test_notes_views.py -q` → all pass.

- [ ] **Step 9: Lint and commit**

```bash
uv run ruff check --fix notes/ tests/test_tags_notes_hub.py
uv run ruff format notes/ tests/test_tags_notes_hub.py
git add notes/ templates/courses/lesson_unit.html tests/test_tags_notes_hub.py
git commit -m "feat(notes): per-course notes index (revision view) with standalone clamp"
```

---

### Task 6: Entry points (nav + outline header)

**Files:**
- Modify: `templates/base.html` (rename nav link), `templates/courses/outline.html` (add "My notes" link)
- Test: `tests/test_tags_notes_hub.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tags_notes_hub.py`:

```python
# ---- Task 6: entry points ----

def test_nav_has_tags_and_notes_link(client):
    me = _user(16)
    client.force_login(me)
    resp = client.get(reverse("notes:overview"))
    body = resp.content.decode()
    assert reverse("notes:overview") in body
    assert "Tags &amp; notes" in body or "Tags & notes" in body
    # old label gone from nav
    assert 'app-nav__link" href="' + reverse("tags:my_tags") not in body


def test_outline_has_my_notes_link(client):
    me = _user(17)
    course = CourseFactory()
    _enroll(me, course)
    client.force_login(me)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 200
    assert reverse("notes:course_notes", args=[course.slug]) in resp.content.decode()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_notes_hub.py -k "nav_has or outline_has" -q`
Expected: FAIL (nav still says "My tags" → `tags:my_tags`; outline has no My notes link).

- [ ] **Step 3: Rename the nav link**

In `templates/base.html` (line 77), replace:

```django
          <a class="app-nav__link" href="{% url 'tags:my_tags' %}">{% trans "My tags" %}</a>
```

with:

```django
          <a class="app-nav__link" href="{% url 'notes:overview' %}">{% trans "Tags & notes" %}</a>
```

- [ ] **Step 4: Add the "My notes" link to the outline header**

In `templates/courses/outline.html`, inside `<div class="outline__head">`, add a sibling `<a>` immediately after the existing "My results" anchor (line 9):

```django
    <a class="btn btn--ghost btn--small outline__notes" href="{% url 'notes:course_notes' slug=course.slug %}"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h11l5 5v11H4z"/><path d="M15 4v5h5"/><path d="M8 13h8M8 17h6"/></svg> {% trans "My notes" %}</a>
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_tags_notes_hub.py -k "nav_has or outline_has" -q`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --fix tests/test_tags_notes_hub.py
uv run ruff format tests/test_tags_notes_hub.py
git add templates/base.html templates/courses/outline.html tests/test_tags_notes_hub.py
git commit -m "feat: Tags & notes nav entry + My notes link on the course outline"
```

---

### Task 7: Polish i18n

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_tags_notes_hub.py`

**Interfaces:** No code. New msgids introduced across Tasks 3-6: `"Tags & notes"`, `"By course"`, `"Manage tags"`, `"Tags and notes sections"`, `"You haven't added any notes or tags yet."`, `"No notes in this course yet."`, `"General"`, `"Go to lesson"`, `"My notes"`, the `"%(n)s note"/"%(n)s notes"` plural, and `"Notes — %(title)s"`. (`"Show more"`, `"Show less"`, `"Add another note"`, `"Save"`, etc. already exist.)

- [ ] **Step 1: Write the failing i18n gate test**

Append to `tests/test_tags_notes_hub.py`:

```python
# ---- Task 7: i18n ----

from django.utils import translation  # noqa: E402


@pytest.mark.parametrize(
    "msgid,expected_pl",
    [
        ("Tags & notes", "Tagi i notatki"),
        ("By course", "Według kursu"),
        ("Manage tags", "Zarządzaj tagami"),
        ("My notes", "Moje notatki"),
        ("Go to lesson", "Przejdź do lekcji"),
        ("No notes in this course yet.", "Brak notatek w tym kursie."),
        ("General", "Ogólne"),
        ("You haven't added any notes or tags yet.", "Nie masz jeszcze żadnych notatek ani tagów."),
        # Pre-existing strings the e2e clamp-label test depends on — verify the catalog value:
        ("Show more", "Pokaż więcej"),
        ("Show less", "Pokaż mniej"),
    ],
)
def test_new_strings_have_polish(msgid, expected_pl):
    with translation.override("pl"):
        from django.utils.translation import gettext
        assert gettext(msgid) == expected_pl
```

- [ ] **Step 2: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Then open `locale/pl/LC_MESSAGES/django.po`. For each new msgid above, set the exact `msgstr` and **remove any `#, fuzzy` flag** `makemessages` attached (it frequently mis-guesses — verify every one). Plural block:

```
msgid "%(n)s note"
msgid_plural "%(n)s notes"
msgstr[0] "%(n)s notatka"
msgstr[1] "%(n)s notatki"
msgstr[2] "%(n)s notatek"
```

Other msgstrs: `"Tags and notes sections" → "Sekcje tagów i notatek"`, `"Notes — %(title)s" → "Notatki — %(title)s"`.

- [ ] **Step 3: Verify no fuzzy / no obsolete, compile**

```bash
grep -n "#, fuzzy" locale/pl/LC_MESSAGES/django.po   # expect: no output
grep -n "#~" locale/pl/LC_MESSAGES/django.po         # expect: no output (no obsolete entries)
uv run python manage.py compilemessages -l pl
```

Run the existing catalog-cleanliness test if present (e.g. `uv run pytest tests/ -k "po_catalog or i18n_catalog" -q`) and the new gate: `uv run pytest tests/test_tags_notes_hub.py -k polish -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_tags_notes_hub.py
git commit -m "i18n(pl): Tags & notes hub + per-course notes index strings"
```

---

### Task 8: E2E + Definition of Done

**Files:**
- Create: `tests/test_e2e_tags_notes_hub.py`

- [ ] **Step 1: Write the e2e tests**

Create `tests/test_e2e_tags_notes_hub.py`, mirroring the existing Playwright e2e style. **Before writing, read `tests/test_e2e_notes.py`** for the exact `live_server`/`page` fixtures and the login-helper signature/selectors, and `tests/test_e2e_smoke.py` for the real language-switch gesture — reuse them verbatim, do NOT invent selectors. Note the two repo conventions confirmed in those files: module-level `pytestmark = pytest.mark.e2e` PLUS a **per-test `@pytest.mark.django_db(transaction=True)`** (a non-transactional `django_db` rolls back in a transaction the separate `live_server` thread can't see, so seeding/login would silently fail), and a **form-scoped** login helper (the header also renders submit buttons). Three scenarios:

```python
import pytest

from courses.models import Enrollment
from notes import services
from tests.factories import (
    CourseFactory,
    ContentNodeFactory,
    ElementFactory,
    make_verified_user,
    TEST_PASSWORD,
)

pytestmark = pytest.mark.e2e


def _seed(long_body=False):
    user = make_verified_user(username="e2estud", email="e2estud@test.example.com")
    course = CourseFactory(title="Revision Course")
    Enrollment.objects.create(student=user, course=course, source="manual")
    unit = ContentNodeFactory(course=course, title="Lesson One")
    el = ElementFactory(unit=unit)
    body = ("A very long revision note. " * 60) if long_body else "MY REVISION NOTE"
    note = services.create_note(user, unit, el.pk, body)
    return user, course, unit, note


def _login(page, live_server, username):
    # Form-scoped to avoid the header's language/theme submit buttons (per test_e2e_notes.py).
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_e2e_revision_loop(page, live_server):
    user, course, unit, note = _seed()
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}/tags-and-notes/")
    page.click(".tnhub__card-notes")  # the card's "N notes" link -> per-course index
    assert "MY REVISION NOTE" in page.content()
    page.click(".note-card__gotolesson a")
    page.wait_for_url(f"**/u/{unit.pk}/**")
    # the note is rendered on the lesson (annotated block expanded via ?notes=1)
    assert f"note-{note.pk}" in page.content()


@pytest.mark.django_db(transaction=True)
def test_e2e_standalone_clamp_activates(page, live_server):
    user, course, unit, note = _seed(long_body=True)
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/notes/")
    more = page.locator(".note-card__more")
    more.wait_for(state="visible")
    assert more.count() == 1
    body = page.locator(".note-card__body").first
    assert "note-card__body--clamp" in (body.get_attribute("class") or "")
    more.click()
    assert "note-card__body--clamp" not in (body.get_attribute("class") or "")


@pytest.mark.django_db(transaction=True)
def test_e2e_standalone_clamp_label_localizes(page, live_server):
    """Drive the real PL language switch, then assert the clamp toggle localizes."""
    user, course, unit, note = _seed(long_body=True)
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/notes/")
    # Header language form (test_e2e_smoke.py): posts next=<current path>, reloads in PL.
    page.click("button[name='language'][value='pl']")
    page.wait_for_load_state("networkidle")
    more = page.locator(".note-card__more")
    more.wait_for(state="visible")
    # "Show more" -> "Pokaż więcej" (Task 7's i18n gate verifies this against the catalog).
    assert more.inner_text().strip() == "Pokaż więcej"
```

Use real gestures only (no `page.evaluate` shortcut), per the project rule. If the `button[name='language'][value='pl']` selector differs in the current `base.html`, use the exact one `test_e2e_smoke.py` drives.

- [ ] **Step 2: Run the e2e**

Run: `uv run pytest tests/test_e2e_tags_notes_hub.py -m e2e -q`
Expected: PASS (3 tests). Debug selectors against the actual rendered pages if needed.

- [ ] **Step 3: Full Definition of Done gate**

Run each and confirm clean:

```bash
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check   # "No changes detected"
uv run python manage.py check
uv run pytest -m "not e2e" -q                     # full suite green
uv run pytest -m e2e -q                           # e2e green
uv run python manage.py compilemessages -l pl
grep -n "#, fuzzy\|#~" locale/pl/LC_MESSAGES/django.po   # no output
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_tags_notes_hub.py
git commit -m "test(e2e): Tags & notes revision loop + standalone clamp activation"
```

---

## Notes for the implementer

- **Reuse, don't reinvent:** the read-only card copies only the `.note-card` / `.note-card__body` / `.note-card__meta` markup + the `edited/added … ago` `blocktrans` from `_note_card.html`; it must NOT include `_note_card.html` (that hardcodes edit/delete actions). Tag chips reuse `.tag-chip tag-chip--<color>` from `tags.css`.
- **One-way import:** `notes/views.py` imports `tags.services`; `tags` must never import `notes` (no cycle).
- **Clamp footgun:** `setupClamp` is a private IIFE helper bound to panel call sites; the standalone page needs the explicit `[data-course-notes]` init (Task 5 Step 6) AND the `#notes-i18n` element (for localized labels) AND the notes.js `<script>` AND the notes.css link — all four are wired in Task 5.
- **No migration:** if `makemigrations --check` reports changes, you touched a model by accident — revert it.
