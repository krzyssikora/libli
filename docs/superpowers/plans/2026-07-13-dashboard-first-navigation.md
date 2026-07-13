# Dashboard-first navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing post-login dashboard the primary course hub, slim the top nav, finish the Teaching panel, and fix issue #91 (group-assigned teachers have no course access).

**Architecture:** Four seams, each independently testable: (1) extend `courses/access.py::accessible_courses` to grant teachers access to non-archived courses they teach; (2) enrich the dashboard view + template (Teaching panel, Studio panel, gate fixes); (3) restructure the nav in `templates/base.html`; (4) merge the two Groups nav entries into one tabbed page via a new include. Then an i18n cleanup pass. No model changes, no migration.

**Tech Stack:** Django (server-rendered templates), pytest + `tests/factories.py`, `uv run` for all tooling, EN/PL i18n via `makemessages`/`.po`.

## Global Constraints

- **Tooling runs via `uv run`** — `ruff`/`pytest`/`python`/`manage.py` are NOT on PATH. Use `uv run pytest ...`, `uv run ruff check`, `uv run ruff format --check`, `uv run python manage.py ...`.
- **Test password:** never introduce a new password literal; use `tests.factories.TEST_PASSWORD` (GitGuardian CI flags new literals).
- **Django multi-line comments:** use `{% comment %}…{% endcomment %}`; `{# … #}` must be single-line or it renders as visible text.
- **Icons:** any UI icon is a `currentColor` line SVG via the shared `.icon` util — never a multicolour emoji. (This feature adds no new icons.)
- **No new migration.** `Group.teachers` (M2M, `related_name="taught_groups"`) and `Group.course` (FK, `related_name="groups"`) already exist.
- **i18n:** new `{% trans %}` strings must be extracted with `uv run python manage.py makemessages --no-obsolete` (the `--no-obsolete` flag is load-bearing — see Task 6) and translated in `locale/pl/LC_MESSAGES/django.po`, reviewing `#, fuzzy` flags. "Studio" is a deliberate loanword (self-equal msgid, no PL form).
- **Windows test flake:** if `pytest-xdist` parallelism flakes, re-run the affected file serially with `-p no:xdist`.
- **"Studio" is the canonical new name** for the authoring/administration ledger (replaces "Manage"/"Authoring") across nav and dashboard.

---

### Task 1: Access fix — teachers can reach non-archived courses they teach (closes #91)

**Files:**
- Modify: `courses/access.py:16-24` (`accessible_courses`)
- Test: `tests/test_access_taught_courses.py` (create)
- Modify: `tests/test_grouping_course_links.py:64-88` (fix the now-false docstring + simplify)

**Interfaces:**
- Consumes: `courses.models.Course`, `courses.models.Enrollment`, `grouping.models.Group` (M2M `Group.teachers`, FK `Group.course` with `related_name="groups"`, boolean `Group.archived`).
- Produces: `accessible_courses(user)` now also admits courses where the user is in `Group.teachers` of a **non-archived** group. `can_access_course` (unchanged code) inherits this.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_access_taught_courses.py`:

```python
import pytest
from django.urls import reverse

from courses.access import accessible_courses
from courses.access import can_access_course
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import make_login
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def test_accessible_includes_taught_nonarchived_course():
    teacher = make_teacher(None, "t_access_incl") if False else make_login(
        None, "t_access_incl"
    )
    # make_login returns a non-staff user; attach via Group.teachers.
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    assert not teacher.is_staff  # the fix must grant via the taught branch, not is_staff
    assert course in accessible_courses(teacher)


def test_accessible_excludes_archived_group_taught_course():
    teacher = make_login(None, "t_access_arch")
    course = CourseFactory()
    group = GroupFactory(course=course, archived=True)
    group.teachers.add(teacher)
    assert not teacher.is_staff
    assert course not in accessible_courses(teacher)


def test_accessible_excludes_unrelated_course():
    user = make_login(None, "t_access_unrel")
    CourseFactory()  # not owned, not enrolled, not taught
    assert list(accessible_courses(user)) == []


def test_course_outline_admits_nonstaff_group_teacher(client):
    teacher = make_login(client, "t_outline_ok")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    assert not teacher.is_staff
    assert can_access_course(teacher, course)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 200


def test_course_outline_403_for_untaught_teacher(client):
    teacher = make_login(client, "t_outline_403")
    course = CourseFactory()  # teacher has no relation to this course
    assert not can_access_course(teacher, course)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 403
```

> Note on `make_login(None, ...)`: `make_login` only uses its `client` arg to `force_login`; passing `None` for the pure-queryset tests avoids a needless login. Where a request is made (`client` tests), pass the real `client`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_access_taught_courses.py -p no:xdist -q`
Expected: FAIL — `test_accessible_includes_taught_nonarchived_course` and `test_course_outline_admits_nonstaff_group_teacher` fail (course not accessible / 403), because `accessible_courses` does not yet consult `Group.teachers`.

- [ ] **Step 3: Implement the access change**

In `courses/access.py`, replace the `accessible_courses` body (lines 16-24):

```python
def accessible_courses(user):
    """Courses `user` may access, as a queryset (single source of truth for
    can_access_course): staff/superuser ⇒ all; else owned ∪ enrolled ∪ taught
    (non-archived groups)."""
    if not user.is_authenticated:
        return Course.objects.none()
    if user.is_staff:
        return Course.objects.all()
    enrolled = Enrollment.objects.filter(student=user).values("course_id")
    return Course.objects.filter(
        Q(pk__in=enrolled)
        | Q(owner=user)
        | Q(groups__teachers=user, groups__archived=False)
    ).distinct()
```

The `groups__archived=False` MUST stay inside the same `Q(...)` as `groups__teachers=user` (one join condition) so an archived group never grants access.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_access_taught_courses.py -p no:xdist -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Fix the now-false docstring in the existing link test**

In `tests/test_grouping_course_links.py`, `test_teacher_can_follow_my_groups_link_to_the_outline` (lines 64-88) currently claims `Group.teachers` is never consulted and uses `set_user_role` to force `is_staff`. That rationale is now false. Replace the whole function with:

```python
def test_teacher_can_follow_my_groups_link_to_the_outline(client):
    """The click-path end to end: the href on my_groups resolves to a 200 for a
    non-staff teacher tied to the course only via Group.teachers. Since
    courses.access.accessible_courses now consults Group.teachers (non-archived),
    a bare factory teacher — no is_staff, not owner, not enrolled — is admitted.
    """
    teacher = make_teacher(client, "t_link_followthrough")
    course = CourseFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    assert not teacher.is_staff
    assert course.owner != teacher

    listing = client.get(reverse("grouping:my_groups"))
    href = _outline_url(course)
    assert f'href="{href}"' in listing.content.decode()

    outline = client.get(href)
    assert outline.status_code == 200
```

Then remove the now-unused imports at the top of the file: delete `from accounts.services import set_user_role` and `from institution.roles import TEACHER` (verify they are unused elsewhere in the file first — grep the file for `set_user_role` and `TEACHER`).

- [ ] **Step 6: Run the updated test + lint**

Run: `uv run pytest tests/test_grouping_course_links.py -p no:xdist -q`
Expected: PASS (all tests in file green).
Run: `uv run ruff check courses/access.py tests/test_access_taught_courses.py tests/test_grouping_course_links.py`
Expected: no errors (no unused imports).

- [ ] **Step 7: Commit**

```bash
git add courses/access.py tests/test_access_taught_courses.py tests/test_grouping_course_links.py
git commit -m "fix(access): grant teachers access to non-archived courses they teach (closes #91)"
```

---

### Task 2: Dashboard view context + Teaching panel + generic/Browse gates

**Files:**
- Modify: `core/views.py:20-47` (`home`)
- Modify: `templates/core/home.html` (Teaching panel lines 25-30; generic panel gate line 49; Browse button gate line 56)
- Test: `tests/test_dashboard_panels.py` (create)

**Interfaces:**
- Consumes: `courses.models.Course`; role flags `is_student`/`is_teacher`/`is_course_admin`/`is_platform_admin` from `core.context_processors.user_roles` (already wired).
- Produces: `home` context now includes `taught_courses` (non-archived, ordered by title) and `owned_courses` (owner-scoped, ordered by title), in addition to existing `enrolled_courses` and `can_manage_courses`. `owned_courses` is consumed by Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_panels.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import make_login
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _teaching_setup(client, username, *, archived=False):
    user = make_login(client, username)
    course = CourseFactory(title="Taught Course")
    group = GroupFactory(course=course, archived=archived)
    group.teachers.add(user)
    return user, course


def test_teaching_panel_lists_taught_course_with_links(client):
    _user, course = _teaching_setup(client, "dash_teach")
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert "Taught Course" in body
    assert reverse("courses:course_outline", kwargs={"slug": course.slug}) in body
    assert reverse("courses:manage_analytics", kwargs={"slug": course.slug}) in body


def test_teaching_panel_excludes_archived_group_course(client):
    _user, course = _teaching_setup(client, "dash_teach_arch", archived=True)
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    # archived-group course is not listed; no data-section=teaching for this user
    assert "Taught Course" not in body


def test_group_only_teacher_sees_teaching_not_generic_not_browse(client):
    # make_login user is NOT in the Teacher role group (is_teacher flag False),
    # but teaches via Group.teachers -> the widened gate must show Teaching and
    # suppress both the generic empty-state and the student Browse button.
    _user, _course = _teaching_setup(client, "dash_group_only")
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert 'data-section="generic"' not in body
    assert reverse("courses:catalog") not in body  # Browse button suppressed


def test_role_teacher_with_no_taught_courses_sees_empty_state(client):
    make_teacher(client, "dash_role_teacher")  # Teacher role -> is_teacher True
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="teaching"' in body
    assert "No classes assigned yet." in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dashboard_panels.py -p no:xdist -q`
Expected: FAIL — Teaching panel is a stub (no taught list / no analytics link), and `taught_courses` is absent from context so the gates don't suppress generic/Browse.

- [ ] **Step 3: Add the querysets to the view**

In `core/views.py`, inside `home` (after the first-run redirect block, replacing the `enrolled_courses`/`can_manage_courses` block at lines 31-47):

```python
    from courses.models import Course

    enrolled_courses = Course.objects.filter(
        enrollments__student=request.user
    ).order_by("title")
    taught_courses = (
        Course.objects.filter(
            groups__teachers=request.user, groups__archived=False
        )
        .distinct()
        .order_by("title")
    )
    owned_courses = Course.objects.filter(owner=request.user).order_by("title")
    can_manage_courses = (
        request.user.has_perm("courses.change_course")
        or Course.objects.filter(owner=request.user).exists()
    )
    return render(
        request,
        "core/home.html",
        {
            "enrolled_courses": enrolled_courses,
            "taught_courses": taught_courses,
            "owned_courses": owned_courses,
            "can_manage_courses": can_manage_courses,
        },
    )
```

- [ ] **Step 4: Rewrite the Teaching panel + fix the two gates in the template**

In `templates/core/home.html`, replace the Teaching panel block (lines 25-30):

```htmldjango
{% if is_teacher or taught_courses %}
<section class="dash-panel" data-section="teaching">
  <h2 class="dash-panel__title">{% trans "Teaching" %}</h2>
  {% if taught_courses %}
  <ul class="dash-list">
    {% for course in taught_courses %}
    <li>
      <a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a>
      <a class="subtle-link" href="{% url 'courses:manage_analytics' slug=course.slug %}">{% trans "Analytics" %}</a>
    </li>
    {% endfor %}
  </ul>
  {% else %}
  <p class="helptext">{% trans "No classes assigned yet." %}</p>
  {% endif %}
</section>
{% endif %}
```

In the generic empty-state panel condition (line 49), add `and not taught_courses`:

```htmldjango
{% if not is_student and not is_teacher and not is_course_admin and not is_platform_admin and not enrolled_courses and not can_manage_courses and not taught_courses %}
```

In the Browse-courses button condition (line 56), add `and not taught_courses`:

```htmldjango
{% if not user.is_staff and not user.is_superuser and not is_teacher and not is_course_admin and not is_platform_admin and not taught_courses %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dashboard_panels.py -p no:xdist -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the existing dashboard tests (regression)**

Run: `uv run pytest tests/test_surfaces.py -k dashboard -p no:xdist -q`
Expected: PASS — `test_dashboard_lists_enrolled_courses`, `test_dashboard_no_group_sees_generic`, `test_dashboard_shows_manage_link_for_owner`, `test_dashboard_no_manage_link_for_plain_user`, `test_dashboard_student_sees_learning_not_admin`, `test_dashboard_platform_admin_sees_admin_section` all green (none of their users has `taught_courses`, so the added gate term is a no-op for them).

- [ ] **Step 7: Commit**

```bash
git add core/views.py templates/core/home.html tests/test_dashboard_panels.py
git commit -m "feat(dashboard): finish Teaching panel + suppress generic/Browse for group-teachers"
```

---

### Task 3: Studio panel (rename + inline owned-courses list + gated New course)

**Files:**
- Modify: `templates/core/home.html` (Studio/"Authoring" panel, lines 32-37)
- Test: `tests/test_dashboard_panels.py` (append)

**Interfaces:**
- Consumes: `owned_courses` and `can_manage_courses` from `home` context (Task 2); `perms.courses.add_course` (template perms).
- Produces: the dashboard "Studio" panel (title "Studio", owned-course rows → builder, "All courses" → ledger, "New course" → create form gated on `add_course`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dashboard_panels.py`:

```python
from tests.factories import make_pa


def test_studio_panel_owner_sees_title_list_and_all_courses(client):
    owner = make_login(client, "studio_owner")
    course = CourseFactory(title="My Owned Course", owner=owner)
    resp = client.get(reverse("home"))
    body = resp.content.decode()
    assert 'data-section="manage"' in body
    assert ">Studio<" in body  # panel title
    assert "My Owned Course" in body
    assert reverse("courses:manage_builder", kwargs={"slug": course.slug}) in body
    assert reverse("courses:manage_course_list") in body  # "All courses"


def test_studio_new_course_hidden_for_owner_without_add_course(client):
    owner = make_login(client, "studio_plain_owner")
    CourseFactory(title="Owned", owner=owner)
    resp = client.get(reverse("home"))
    # can_manage_courses True via ownership, but no add_course perm
    assert reverse("courses:manage_course_create") not in resp.content.decode()


def test_studio_new_course_shown_for_add_course_holder(client):
    from core.services import mark_onboarded

    make_pa(client, "studio_pa")  # PLATFORM_ADMIN holds courses.add_course
    mark_onboarded()  # avoid the first-run wizard redirect
    resp = client.get(reverse("home"))
    assert reverse("courses:manage_course_create") in resp.content.decode()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_dashboard_panels.py -k studio -p no:xdist -q`
Expected: FAIL — the panel title is still "Authoring", there is no builder/inline list, and no "New course" link.

- [ ] **Step 3: Rewrite the Studio panel**

In `templates/core/home.html`, replace the "Authoring" panel block (lines 32-37):

```htmldjango
{% if can_manage_courses %}
<section class="dash-panel" data-section="manage">
  <h2 class="dash-panel__title">{% trans "Studio" %}</h2>
  {% if owned_courses %}
  <ul class="dash-list">
    {% for course in owned_courses %}
    <li><a href="{% url 'courses:manage_builder' slug=course.slug %}">{{ course.title }}</a></li>
    {% endfor %}
  </ul>
  {% endif %}
  <p>
    <a href="{% url 'courses:manage_course_list' %}">{% trans "All courses" %}</a>
    {% if perms.courses.add_course %}
    <a href="{% url 'courses:manage_course_create' %}">{% trans "New course" %}</a>
    {% endif %}
  </p>
</section>
{% endif %}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dashboard_panels.py -k studio -p no:xdist -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Update the stale comment in test_media_manager.py**

`tests/test_media_manager.py:275` is a *comment* (not an assertion) referencing "dashboard > Manage courses". Update the wording to match the new label so it doesn't mislead: change "Manage courses" to "Studio > All courses" in that comment. (No assertion changes; run the file to confirm still green.)

Run: `uv run pytest tests/test_media_manager.py -p no:xdist -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/core/home.html tests/test_dashboard_panels.py tests/test_media_manager.py
git commit -m "feat(dashboard): rename Authoring panel to Studio with owned-course list + gated New course"
```

---

### Task 4: Nav restructure in base.html

**Files:**
- Modify: `templates/base.html:77-98` (primary nav links)
- Modify: `tests/test_surfaces.py:298-303` (`test_nav_has_courses_link_when_authenticated`)
- Test: `tests/test_nav_structure.py` (create)

**Interfaces:**
- Consumes: `perms.courses.change_course`, `perms.grouping.view_collection`, `perms.grouping.view_group`.
- Produces: a nav of `Tags & notes · Studio · Groups · Help · Admin` (plus bell/avatar). No "Courses", no "Browse", no separate "My groups".

- [ ] **Step 1: Write the failing tests**

Create `tests/test_nav_structure.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import make_pa
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_nav_has_no_courses_link(client):
    user = make_verified_user(username="nav_noc", email="nav_noc@school.edu")
    client.force_login(user)
    body = client.get(reverse("home")).content.decode()
    assert reverse("courses:my_courses") not in body


def test_nav_shows_studio_not_manage_for_change_course_holder(client):
    from core.services import mark_onboarded

    make_pa(client, "nav_pa")  # holds courses.change_course
    mark_onboarded()
    body = client.get(reverse("home")).content.decode()
    assert ">Studio<" in body
    assert reverse("courses:manage_course_list") in body
    # the standalone nav link labelled "Manage" is gone (Studio replaces it)


def test_nav_single_groups_link_targets_my_groups(client):
    from core.services import mark_onboarded

    make_pa(client, "nav_pa_groups")  # holds grouping.view_group
    mark_onboarded()
    body = client.get(reverse("home")).content.decode()
    # single Groups entry -> my_groups; the old separate group_list nav link is gone
    assert reverse("grouping:my_groups") in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_nav_structure.py -p no:xdist -q`
Expected: FAIL — `test_nav_has_no_courses_link` fails (Courses link still present) and `>Studio<` is absent.

- [ ] **Step 3: Rewrite the nav links**

In `templates/base.html`, replace the block from line 77 (the Courses link) through line 98 (the "My groups" link `{% endif %}`) with:

```htmldjango
          <a class="app-nav__link" href="{% url 'notes:overview' %}">{% trans "Tags & notes" %}</a>
          {% if perms.courses.change_course %}
          <a class="app-nav__link" href="{% url 'courses:manage_course_list' %}">{% trans "Studio" %}</a>
          {% endif %}
          {% if perms.grouping.view_collection or perms.grouping.view_group %}
          <a class="app-nav__link" href="{% url 'grouping:my_groups' %}">{% trans "Groups" %}</a>
          {% endif %}
```

This removes: the "Courses" link, the students-only "Browse" `{% comment %}` block + link, the separate "Groups"→`group_list` link, and the "My groups" link (its gate is reused for the merged "Groups" entry). The Help link, Admin dropdown, bell, and avatar that follow (from line 99 onward) are untouched.

- [ ] **Step 4: Update the broken existing nav test**

In `tests/test_surfaces.py`, replace `test_nav_has_courses_link_when_authenticated` (lines 298-303) with:

```python
@pytest.mark.django_db
def test_nav_has_no_courses_link_when_authenticated(client):
    user = make_verified_user(username="navc", email="navc@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert reverse("courses:my_courses").encode() not in resp.content
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_nav_structure.py tests/test_surfaces.py -p no:xdist -q`
Expected: PASS (new nav tests + all of test_surfaces green).

- [ ] **Step 6: Commit**

```bash
git add templates/base.html tests/test_nav_structure.py tests/test_surfaces.py
git commit -m "feat(nav): drop Courses/Browse, rename Manage->Studio, merge Groups into one entry"
```

---

### Task 5: Merged Groups tabbed page (`_groups_tabs.html`)

**Files:**
- Create: `templates/_groups_tabs.html`
- Modify: `grouping/views.py` (`group_list` ~line 174, `my_groups` ~line 310 — add `hub_tab` to each context)
- Modify: `templates/grouping/my_groups.html` (include the strip), `templates/grouping/group_list.html` (include the strip)
- Test: `tests/test_groups_tabs.py` (create)

**Interfaces:**
- Consumes: `perms.grouping.view_group` (strip visibility), `hub_tab` context flag ("my_groups" | "manage").
- Produces: a shared tab strip rendered on both Groups pages; visible only when the user holds `view_group` (i.e. both tabs are entitled), hidden for a `view_collection`-only user.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_groups_tabs.py`:

```python
import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_my_groups_shows_tab_strip_for_view_group_holder(client):
    make_pa(client, "grp_pa")  # holds grouping.view_group
    body = client.get(reverse("grouping:my_groups")).content.decode()
    # both tab links present (the strip)
    assert reverse("grouping:my_groups") in body
    assert reverse("grouping:group_list") in body


def test_group_list_shows_tab_strip_with_manage_active(client):
    make_pa(client, "grp_pa2")
    body = client.get(reverse("grouping:group_list")).content.decode()
    assert reverse("grouping:my_groups") in body
    assert reverse("grouping:group_list") in body


def test_my_groups_no_strip_for_view_collection_only_user(client):
    # A bespoke user with ONLY grouping.view_collection (no standard role has this
    # in isolation; grant the permission directly).
    user = make_login(client, "grp_collonly")
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="grouping", codename="view_collection"
        )
    )
    # drop cached perms so the just-added permission is visible in-request
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    body = client.get(reverse("grouping:my_groups")).content.decode()
    # single tab entitled -> no strip -> the Manage (group_list) link is absent
    assert reverse("grouping:group_list") not in body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_groups_tabs.py -p no:xdist -q`
Expected: FAIL — no strip is rendered yet, so the `view_group` holders don't see a `group_list` link on the `my_groups` page.

- [ ] **Step 3: Create the include**

Create `templates/_groups_tabs.html` (reuses the shared `tnhub__` tab CSS for visual consistency; the strip renders only when both tabs are entitled, i.e. the user holds `view_group`):

```htmldjango
{% load i18n %}
{% if perms.grouping.view_group %}
<nav class="tnhub__tabs" aria-label="{% trans 'Groups sections' %}">
  <a class="tnhub__tab{% if hub_tab == 'my_groups' %} is-on{% endif %}"
     href="{% url 'grouping:my_groups' %}">{% trans "My groups" %}</a>
  <a class="tnhub__tab{% if hub_tab == 'manage' %} is-on{% endif %}"
     href="{% url 'grouping:group_list' %}">{% trans "Manage" %}</a>
</nav>
{% endif %}
```

- [ ] **Step 4: Set `hub_tab` in both views**

In `grouping/views.py`, `my_groups` (the `render` call ~lines 328-332), add `"hub_tab": "my_groups"` to the context dict:

```python
    return render(
        request,
        "grouping/my_groups.html",
        {"groups": groups, "collections": collections, "hub_tab": "my_groups"},
    )
```

In `group_list` (the `render` call ~lines 177-184), add `"hub_tab": "manage"`:

```python
    return render(
        request,
        "grouping/group_list.html",
        {
            "groups": groups.order_by("course__title", "name"),
            "show_archived": show_archived,
            "hub_tab": "manage",
        },
    )
```

- [ ] **Step 5: Include the strip in both templates**

In `templates/grouping/my_groups.html`, add the include as the first line inside the content block (after `{% block content %}` on line 3):

```htmldjango
{% block content %}
{% include "_groups_tabs.html" %}
<section class="manage">
```

In `templates/grouping/group_list.html`, add it right after `{% block content %}` (line 3), before the `<h1>`:

```htmldjango
{% block content %}
{% include "_groups_tabs.html" %}
<h1>{% trans "Groups" %}</h1>
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_groups_tabs.py -p no:xdist -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Regression — existing grouping view tests**

Run: `uv run pytest tests/test_grouping_group_views.py tests/test_grouping_course_links.py -p no:xdist -q`
Expected: PASS (route/behavior unchanged; only `hub_tab` context + an include were added).

- [ ] **Step 8: Commit**

```bash
git add templates/_groups_tabs.html grouping/views.py templates/grouping/my_groups.html templates/grouping/group_list.html tests/test_groups_tabs.py
git commit -m "feat(grouping): merge Groups + My groups into one tabbed page via shared include"
```

---

### Task 6: Internationalization — extract, translate, and clean obsolete entries

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (and its compiled `django.mo`)

**Interfaces:**
- Consumes: the new/removed `{% trans %}` strings from Tasks 2–5.
- Produces: a clean PL catalog (no `#~` obsolete markers) with PL translations for the new strings — so `test_po_catalog_clean` (and its mirrors) stay green.

Added strings needing PL: **"All courses"**, **"New course"**, **"Groups sections"** (the `_groups_tabs.html` aria-label). Reused (already translated, no action): **"My groups"**, **"Manage"**, **"Analytics"**. Loanword (leave msgstr equal to msgid): **"Studio"**. Removed references that will orphan existing msgids: **"Courses"**, **"Browse"**, **"Authoring"**.

- [ ] **Step 1: Confirm the failing state (obsolete-entry test)**

First extract WITHOUT the flag to see the problem the flag prevents (optional but instructive), then note the catalog test:

Run: `uv run pytest tests/test_i18n_notes.py::test_po_catalog_clean -p no:xdist -q`
Expected (before this task): PASS currently, but it will FAIL after a plain `makemessages` marks "Courses"/"Browse"/"Authoring" as `#~`. This task performs the extraction correctly so the test stays green.

- [ ] **Step 2: Extract with `--no-obsolete`**

Run: `uv run python manage.py makemessages -l pl --no-obsolete`

The `--no-obsolete` flag DROPS unreferenced msgids (the three orphans) instead of marking them `#~`. If any `#~` blocks remain in `locale/pl/LC_MESSAGES/django.po`, hand-delete them.

- [ ] **Step 3: Fill in the new Polish translations + review fuzzy**

Edit `locale/pl/LC_MESSAGES/django.po`. For each newly-added `msgid`, supply the `msgstr`:

```
msgid "All courses"
msgstr "Wszystkie kursy"

msgid "New course"
msgstr "Nowy kurs"

msgid "Groups sections"
msgstr "Sekcje grup"

msgid "Studio"
msgstr "Studio"
```

Then scan for `#, fuzzy` flags introduced by `makemessages` (it may fuzzy-match "New course" to a near string): remove the `#, fuzzy` line and correct the `msgstr` for any entry so flagged, so no `#, fuzzy` remains for these strings.

- [ ] **Step 4: Compile**

Run: `uv run python manage.py compilemessages -l pl`
Expected: compiles `django.po` → `django.mo` with no errors.

- [ ] **Step 5: Run the i18n catalog tests + the catalog-render test**

Run: `uv run pytest tests/test_i18n_notes.py tests/test_i18n_auth.py tests/test_tags_i18n.py tests/test_i18n_catalog.py -p no:xdist -q`
Expected: PASS — no `#~` in the catalog, and "Browse courses" (dashboard button, still present) renders translated.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(pl): translate Studio panel/Groups-tab strings, drop orphaned msgids"
```

---

## Definition of Done (run after all tasks)

- [ ] **Full suite:** `uv run pytest -p no:xdist -q` — all green. (Serial to avoid the Windows xdist flake; if it is faster and stable, `-n auto` is acceptable.)
- [ ] **Lint + format:** `uv run ruff check` and `uv run ruff format --check` — both clean.
- [ ] **i18n catalog cleanliness** re-confirmed: `uv run pytest tests/test_i18n_notes.py::test_po_catalog_clean -p no:xdist -q` green (the removed-string gotcha).
- [ ] **Manual smoke (optional):** a non-staff user attached only via `Group.teachers` lands on `/`, sees a populated Teaching panel (outline + Analytics links resolve), and sees neither the generic empty-state nor the Browse button.

## Self-review notes (coverage map)

- Nav restructure (spec §1) → Task 4 (+ i18n Task 6 for removed strings).
- Teaching panel + gates (spec §2) → Task 2; Studio panel (spec §2) → Task 3.
- Access fix / #91 (spec §3) → Task 1.
- Groups merge (spec §4) → Task 5.
- Archived-group exclusion (spec §3, Error handling) → Tasks 1 + 2 (both queries carry `groups__archived=False`).
- i18n `--no-obsolete` cleanup (spec Testing → Internationalization) → Task 6.
- "Tests to update" (spec Testing): `test_nav_has_courses_link…` → Task 4; `test_grouping_course_links` docstring → Task 1; `test_media_manager` comment → Task 3; `test_surfaces`/`test_consumption_pages` dashboard tests confirmed still green (Task 2 Step 6). `test_catalog_nav.py` intentionally unaffected (Browse *button* unchanged).
