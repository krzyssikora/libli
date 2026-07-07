# Teacher-facing Analytics link — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give teachers a discoverable, in-UI link into the analytics matrix (`courses:manage_analytics`), pre-filtered to the group/collection they navigated from, on the three teacher-facing pages `my_groups`, `group_detail`, and `collection_detail`.

**Architecture:** Additive, link-only change. Each of the three templates gains an `{% trans "Analytics" %}` button linking to `courses:manage_analytics` with a `?scope=group:<pk>` or `?scope=collection:<pk>` query string. Group rows are ungated (a visible non-archived group implies review reach by invariant); collection links and both detail-page links are gated on a `can_review` flag the view supplies, plus `not <object>.archived`. No new view, URL, model, migration, or permission.

**Tech Stack:** Django server-rendered templates, `pytest` + `pytest-django`, `factory_boy` (`tests/factories.py`), `uv run` for all tooling.

## Global Constraints

- All Python/tooling runs via `uv run` (bash `ruff`/`pytest`/`python`/`django-admin` are NOT on PATH). E.g. `uv run pytest ...`, `uv run ruff check`, `uv run ruff format --check`, `uv run python manage.py makemessages`.
- Reuse the existing `{% trans "Analytics" %}` msgid — it already exists in the catalog, translated (e.g. PL `Analityka`). Do **not** invent a new string. (`_course_panel.html:8` also renders this string; note the catalog's `#:` provenance currently lists the analytics templates rather than that file — the catalog is stale, resynced in Task 4.)
- Link styling: reuse the existing `btn btn--ghost btn--small` class trio, matching `_course_panel.html:8`. Do not restyle the pages otherwise.
- The scope query string is literal template text: `?scope=group:{{ group.pk }}` / `?scope=collection:{{ c.pk }}` / `?scope=collection:{{ collection.pk }}` (the resolver `grouping/scoping.py:students_in_scope` re-derives and self-heals unreachable/malformed scopes).
- Tests: use `tests.factories` helpers (`make_teacher`, `make_ca`, `make_pa`, `CourseFactory`, `GroupFactory`, `CollectionFactory`, `UserFactory`, `grouping.services`). No hardcoded passwords — factories use `TEST_PASSWORD`.
- The real page-level guard is unchanged: `courses.views_analytics.analytics_matrix` raises `Http404` when `scoping.can_review_course` is false. This plan only adds links; it does not touch that gate.

---

## File Structure

- `grouping/views.py` — `my_groups` (materialize collections + per-instance `can_review`, `select_related`), `group_detail` (+`can_review` context), `collection_detail` (+`can_review` context).
- `templates/grouping/my_groups.html` — per-row Analytics links (group ungated, collection gated).
- `templates/grouping/group_detail.html` — gated Analytics link after the course-title line.
- `templates/grouping/collection_detail.html` — gated Analytics link between Edit and Delete.
- `tests/test_grouping_analytics_links.py` — **new** focused test module for all link behaviors.
- `locale/*/LC_MESSAGES/django.po` — refreshed `#:` location comments (Task 4).

---

## Task 1: `my_groups` hub — group (ungated) + collection (gated) Analytics links

**Files:**
- Modify: `grouping/views.py:297-307` (the `my_groups` view)
- Modify: `templates/grouping/my_groups.html:6-18`
- Test: `tests/test_grouping_analytics_links.py` (new)

**Interfaces:**
- Consumes: `scoping.groups_visible_to`, `scoping.collections_manageable_by`, `scoping.can_review_course` (all exist in `grouping/scoping.py`).
- Produces: `my_groups` context now passes `collections` as a **list** of `Collection` instances each carrying a `can_review: bool` attribute; `groups` unchanged (queryset). Template attribute read as `{% if c.can_review %}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_grouping_analytics_links.py` with **all** module imports up front (Tasks 2 and 3 append test functions but add no new imports — this avoids ruff E402, which is not auto-fixable):

```python
import pytest
from django.urls import reverse

from grouping import services
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import make_ca
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _analytics_url(course):
    return reverse("courses:manage_analytics", args=[course.slug])


def test_my_groups_group_row_has_scoped_analytics_link(client):
    teacher = make_teacher(client, "t_mygroups_grp")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)  # teaches a live group -> can_review true
    resp = client.get(reverse("grouping:my_groups"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=group:{group.pk}" in body


def test_my_groups_reachable_collection_row_has_scoped_analytics_link(client):
    teacher = make_teacher(client, "t_mygroups_coll_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)  # live group on the course -> can_review true
    coll = CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:my_groups"))
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=collection:{coll.pk}" in body


def test_my_groups_unreachable_collection_row_hides_analytics_link(client):
    # Teacher owns a collection on a course where they teach NO live group ->
    # can_review is false -> the collection's Analytics link must be absent,
    # otherwise the link would 404 at the analytics page gate.
    teacher = make_teacher(client, "t_mygroups_coll_no")
    course = CourseFactory()
    coll = CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:my_groups"))
    body = resp.content.decode()
    assert f"?scope=collection:{coll.pk}" not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_grouping_analytics_links.py -v`
Expected: all three FAIL (links not yet in the template; `c.can_review` unset).

- [ ] **Step 3: Update the `my_groups` view to supply `can_review` per collection**

In `grouping/views.py`, replace the body of `my_groups` (currently lines 297-307) with:

```python
def my_groups(request):
    groups = (
        scoping.groups_visible_to(request.user)
        .filter(archived=False)
        .select_related("course")
        .order_by("course__title", "name")
    )
    collections = list(
        scoping.collections_manageable_by(request.user)
        .filter(archived=False)
        .select_related("course")
        .order_by("name")
    )
    for c in collections:
        # can_review_course is course-wide and does NOT consult collection
        # ownership, so an owned collection on a course the user cannot review
        # must not offer a (dead) analytics link.
        c.can_review = scoping.can_review_course(request.user, c.course)
    return render(
        request,
        "grouping/my_groups.html",
        {"groups": groups, "collections": collections},
    )
```

Keep the existing `@login_required` decorator and its comment block (lines 293-296) intact.

- [ ] **Step 4: Add the links to `templates/grouping/my_groups.html`**

Replace the group `<li>` (line 8) with:

```html
  <li><a href="{% url 'grouping:group_detail' group.pk %}">{{ group.name }}</a> <span class="muted">{{ group.course.title }}</span> <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_analytics' slug=group.course.slug %}?scope=group:{{ group.pk }}">{% trans "Analytics" %}</a></li>
```

Replace the collection `<li>` (line 15) with:

```html
  <li><a href="{% url 'grouping:collection_detail' c.pk %}">{{ c.name }}</a> <span class="muted">{{ c.course.title }}</span>{% if c.can_review %} <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_analytics' slug=c.course.slug %}?scope=collection:{{ c.pk }}">{% trans "Analytics" %}</a>{% endif %}</li>
```

(`{% load i18n %}` is already present at line 2.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_analytics_links.py -v`
Expected: all three PASS.

- [ ] **Step 6: Lint**

Run: `uv run ruff check grouping/views.py tests/test_grouping_analytics_links.py && uv run ruff format --check grouping/views.py tests/test_grouping_analytics_links.py`
Expected: no errors. (If `format --check` fails, run `uv run ruff format grouping/views.py tests/test_grouping_analytics_links.py` and re-run.)

- [ ] **Step 7: Commit**

```bash
git add grouping/views.py templates/grouping/my_groups.html tests/test_grouping_analytics_links.py
git commit -m "feat(analytics): teacher Analytics links on my_groups hub"
```

---

## Task 2: `group_detail` — gated scoped Analytics link

**Files:**
- Modify: `grouping/views.py:275-290` (the `group_detail` view)
- Modify: `templates/grouping/group_detail.html:5` (insert after the course-title `<p>`)
- Test: `tests/test_grouping_analytics_links.py` (append)

**Interfaces:**
- Consumes: `scoping.can_review_course`.
- Produces: `group_detail` context gains `can_review: bool`. Template renders the link only when `can_review and not group.archived`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_grouping_analytics_links.py` (imports for `services` and `make_ca` are already at the module top from Task 1):

```python
def test_group_detail_teacher_sees_scoped_analytics_link(client):
    teacher = make_teacher(client, "t_gd_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=group:{group.pk}" in body


def test_group_detail_archived_group_hides_link_even_when_can_review(client):
    # ISOLATES the `not group.archived` term: a Course Admin who owns the course
    # has can_review == True and can see their own archived group, yet the link
    # must be hidden because a group:<pk> scope on an archived group silently
    # falls back to "all" (students_in_scope requires archived=False).
    ca = make_ca(client, "ca_gd_arch")
    course = CourseFactory(owner=ca)
    group = GroupFactory(course=course)
    services.set_group_archived(group, True)
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=group:{group.pk}" not in body


def test_group_detail_archived_only_reach_hides_link(client):
    # can_review == False path: a teacher whose ONLY group on the course is
    # archived. groups_visible_to still returns it (they teach it) so the page
    # loads, but can_review_course is false -> link absent.
    teacher = make_teacher(client, "t_gd_arch_only")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    services.set_group_archived(group, True)
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=group:{group.pk}" not in body
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_grouping_analytics_links.py -k group_detail -v`
Expected: `teacher_sees_scoped` FAILs (no link yet); the two "hides" tests may pass vacuously (no link exists yet) — that is fine; they lock behavior after Step 3-4.

- [ ] **Step 3: Add `can_review` to the `group_detail` view context**

In `grouping/views.py`, in `group_detail`, after the `owner = group.course.owner ...` line (currently line 279), add:

```python
    can_review = scoping.can_review_course(request.user, group.course)
```

and add `"can_review": can_review,` to the render context dict (alongside `"group"`, `"students"`, etc.):

```python
    return render(
        request,
        "grouping/group_detail.html",
        {
            "group": group,
            "students": students,
            "teachers": teachers,
            "owner": owner,
            "student_count": len(students),
            "can_review": can_review,
        },
    )
```

- [ ] **Step 4: Add the link to `templates/grouping/group_detail.html`**

Insert, immediately after `<p class="muted">{{ group.course.title }}</p>` (line 5), this bare `<a>` on its own line (it renders on its own line because it sits between two block elements — no wrapper needed):

```html
{% if can_review and not group.archived %}<a class="btn btn--ghost btn--small" href="{% url 'courses:manage_analytics' slug=group.course.slug %}?scope=group:{{ group.pk }}">{% trans "Analytics" %}</a>{% endif %}
```

- [ ] **Step 5: Run the group_detail tests to verify they pass**

Run: `uv run pytest tests/test_grouping_analytics_links.py -k group_detail -v`
Expected: all three PASS.

- [ ] **Step 6: Lint**

Run: `uv run ruff check grouping/views.py tests/test_grouping_analytics_links.py && uv run ruff format --check grouping/views.py tests/test_grouping_analytics_links.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add grouping/views.py templates/grouping/group_detail.html tests/test_grouping_analytics_links.py
git commit -m "feat(analytics): gated Analytics link on group_detail"
```

---

## Task 3: `collection_detail` — gated scoped Analytics link

**Files:**
- Modify: `grouping/views.py:354-374` (the `collection_detail` view)
- Modify: `templates/grouping/collection_detail.html:6-7` (insert between Edit `<a>` and Delete `<form>`)
- Test: `tests/test_grouping_analytics_links.py` (append)

**Interfaces:**
- Consumes: `scoping.can_review_course`.
- Produces: `collection_detail` context gains `can_review: bool`. Template renders the link only when `can_review and not collection.archived`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_grouping_analytics_links.py`:

```python
def test_collection_detail_reachable_shows_scoped_link(client):
    teacher = make_teacher(client, "t_cd_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)  # live group -> can_review true
    coll = CollectionFactory(course=course, owner=teacher)  # teacher owns -> visible
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"{_analytics_url(course)}?scope=collection:{coll.pk}" in body


def test_collection_detail_unreachable_hides_link(client):
    # Load-bearing can_review gate: teacher owns the collection (so the page is
    # reachable) but teaches no live group on the course -> can_review false.
    teacher = make_teacher(client, "t_cd_no")
    course = CourseFactory()
    coll = CollectionFactory(course=course, owner=teacher)
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=collection:{coll.pk}" not in body


def test_collection_detail_archived_hides_link_even_when_can_review(client):
    # ISOLATES `not collection.archived`: can_review true (teacher teaches a live
    # group on the course) but the collection is archived -> scope would fall back
    # to "all", so the link is hidden.
    teacher = make_teacher(client, "t_cd_arch")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    coll = CollectionFactory(course=course, owner=teacher, archived=True)
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"?scope=collection:{coll.pk}" not in body
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_grouping_analytics_links.py -k collection_detail -v`
Expected: `reachable_shows_scoped_link` FAILs; the two "hides" tests pass vacuously until Step 3-4 locks them.

- [ ] **Step 3: Add `can_review` to the `collection_detail` view context**

In `grouping/views.py`, in `collection_detail`, after the `students = (...)` block (currently ends line 365) and before `return render(`, add:

```python
    can_review = scoping.can_review_course(request.user, collection.course)
```

and add `"can_review": can_review,` to the render context dict:

```python
    return render(
        request,
        "grouping/collection_detail.html",
        {
            "collection": collection,
            "students": students,
            "student_count": students.count(),
            "can_review": can_review,
        },
    )
```

- [ ] **Step 4: Add the link to `templates/grouping/collection_detail.html`**

Insert, between the Edit `<a>` (line 6) and the Delete `<form>` (line 7), on its own line:

```html
{% if can_review and not collection.archived %}<a class="btn btn--ghost btn--small" href="{% url 'courses:manage_analytics' slug=collection.course.slug %}?scope=collection:{{ collection.pk }}">{% trans "Analytics" %}</a>{% endif %}
```

- [ ] **Step 5: Run the collection_detail tests to verify they pass**

Run: `uv run pytest tests/test_grouping_analytics_links.py -k collection_detail -v`
Expected: all three PASS.

- [ ] **Step 6: Lint**

Run: `uv run ruff check grouping/views.py tests/test_grouping_analytics_links.py && uv run ruff format --check grouping/views.py tests/test_grouping_analytics_links.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add grouping/views.py templates/grouping/collection_detail.html tests/test_grouping_analytics_links.py
git commit -m "feat(analytics): gated Analytics link on collection_detail"
```

---

## Task 4: i18n catalog refresh + Definition of Done (lint + targeted + full suite)

**Files:**
- Modify: `locale/*/LC_MESSAGES/django.po` (regenerated `#:` location comments only)

**Interfaces:**
- Consumes: nothing new. Produces: refreshed catalogs; a green `grouping` + i18n-catalog test run.

- [ ] **Step 1: Refresh the message catalogs**

The reused `"Analytics"` msgid now appears in three new templates, so `makemessages` will add new `#:` source-location lines (no new msgid, no `msgstr` change expected). Note the catalog is currently **stale**, so `-a` will also resync `#:` comments for unrelated msgids repo-wide (e.g. adding `_course_panel.html:8` to the `Analytics` entry and re-numbering strings in the two edited detail templates). That broader location churn is expected and harmless.

Run: `uv run python manage.py makemessages -a`

- [ ] **Step 2: Verify no new untranslated string and no fuzzy flags were introduced**

Run: `git diff -- locale/`
Expected: the only content changes are `#:` location comments (the churn may extend beyond the `Analytics` entry because the catalog was stale — see Step 1). There must be **no** new `msgid`/`msgstr` pair and **no** `#, fuzzy` marker anywhere in the diff. If a `#, fuzzy` was added, remove it (the recurring makemessages fuzzy-flag gotcha) and re-check.

- [ ] **Step 3: Run the i18n catalog assertion tests**

Run: `uv run pytest tests/test_i18n_catalog.py -v`
Expected: PASS (guards against obsolete `#~` / fuzzy entries and translation completeness).

- [ ] **Step 4: Lint the changed Python (DoD)**

Run: `uv run ruff check grouping/views.py tests/test_grouping_analytics_links.py && uv run ruff format --check grouping/views.py tests/test_grouping_analytics_links.py`
Expected: no errors.

- [ ] **Step 5: Run the targeted grouping + i18n suite**

Run: `uv run pytest tests/test_grouping_analytics_links.py tests/test_grouping_detail_views.py tests/test_grouping_collection_views.py tests/test_i18n_catalog.py -v`
Expected: all PASS. (No existing assertion in the detail/collection view tests inspects the new link, so they remain green.)

- [ ] **Step 6: Run the full test suite (additive-change insurance)**

Run: `uv run pytest -q`
Expected: all PASS — the change is additive (link-only), so nothing elsewhere should regress. If any pre-existing unrelated flake appears, re-run the specific file to confirm it is not caused by this change.

- [ ] **Step 7: Commit**

Review the staged catalog diff first (`git diff --cached -- locale/`) to confirm it is location-comment churn only, then:

```bash
git add locale/
git commit -m "i18n: resync catalog source locations after adding teacher Analytics links"
```

---

## Manual verification (after all tasks)

Per the "verify UI with screenshots" practice, before opening the PR: log in as a teacher who teaches a live group, and visit `my_groups`, that group's `group_detail`, and an owned collection's `collection_detail`; confirm the **Analytics** button appears, is styled like the other `btn--ghost btn--small` controls, and lands on the analytics matrix pre-filtered to the right scope. Then visit an archived group's detail page and confirm the button is absent. Screenshot light + dark.

---

## Self-Review (author checklist — completed)

- **Spec coverage:** §Design 1 → Task 1 (group ungated + collection gated, materialize/`can_review`/`select_related`); §Design 2 → Task 2 (`can_review and not group.archived`); §Design 3 → Task 3 (`collection_detail`, load-bearing `can_review`, placed between Edit/Delete); §Styling & i18n → Tasks 1-3 reuse `btn--ghost btn--small` + `{% trans "Analytics" %}`, Task 4 refreshes catalogs; §Testing matrix (reachable / unreachable-collection / archived-isolation / archived-only) → the eight tests across Tasks 1-3. Round-4 refinements folded in: collection_detail has no wrapper "action row" (Step 4 says "between Edit and Delete"), group_detail link is a bare `<a>` (Task 2 Step 4 note), and the empty-but-non-404 matrix edge is inherent to the unchanged resolver (documented in the spec's Non-goals; no code needed).
- **Placeholder scan:** none — every step shows the exact code/command.
- **Type consistency:** the template guard `{% if c.can_review %}` / `{% if can_review ... %}` matches the `can_review` attribute/context key set in each view; `_analytics_url(course)` helper defined once and reused; `scoping.can_review_course(user, course)` signature consistent across all three views.
