# Phase 3b — Self-enroll catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a student browse a catalog of *open* courses (cohort-gated) and enroll themselves, closing the enrollment loop that today is teacher-driven only.

**Architecture:** A new M2M `Course.self_enroll_cohorts` gates open-course visibility. Three DB-backed services in `grouping/services.py` (the enrollment authority) decide eligibility and perform the idempotent self-enroll. Three `courses` views (`catalog`, `catalog_detail`, `self_enroll`) render a bespoke card grid + an overview modal (server fragment, degrades to a full page) and handle the enroll POST. No schema change to `Enrollment` (`source="self"` already exists) or `visibility`.

**Tech Stack:** Django (server-rendered), pytest + factory_boy, Playwright (e2e), bespoke token-driven CSS (no Bootstrap/React), vanilla JS.

**Spec:** `docs/superpowers/specs/2026-06-23-phase-3b-self-enroll-catalog-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Resolved deferred decisions:**
  - Ineligible / unknown course → **HTTP 404** for both `catalog_detail` and `self_enroll` (avoids leaking the existence of cohort-gated courses). Never 403.
  - `enroll_self` performs **NO eligibility check** — the view is the sole gate. It is a pure idempotent `get_or_create`; the accepted-race path therefore can never raise. No `ValidationError`/sentinel guard.
- **Service naming:** the write service is `enroll_self` — distinct from the `courses` view `self_enroll`, so importing it into `courses/views.py` does not shadow the view.
- **Cross-app field-name asymmetry:** `Enrollment.student` but `CohortMembership.user`. The cohort lookup is `CohortMembership.objects.filter(user=student)`, NOT `student=`.
- **No Bootstrap/React.** Bespoke token-driven CSS; reuse existing `.card`, `.btn`, `.btn--primary`, `.btn--ghost`, `.app-nav__link` classes.
- **i18n:** wrap every new user-facing string in `{% trans %}` / `gettext_lazy as _`, and fill the **Polish** translation (3a shipped strings untranslated and had to be backfilled — do not repeat).
- **Django comments:** `{# #}` must be single-line; use `{% comment %}…{% endcomment %}` for multi-line, or it renders as visible text.
- **Per-task hygiene:** run `ruff check .` AND `ruff format .` (CI runs `ruff format --check`). Run the full suite with `pytest -q` before each commit; e2e tests are `@pytest.mark.e2e` (excluded by default, run explicitly with `-m e2e`).
- **Tests** live in top-level `tests/`. Use `tests/factories.py` helpers (`make_login`, `make_pa`, `make_verified_user`, `CourseFactory`, `ContentNodeFactory`, `SubjectFactory`, `CohortFactory`, `CohortMembershipFactory`, `EnrollmentFactory`). Mark DB tests `pytestmark = pytest.mark.django_db`.
- **Test-data note:** under migrations a **Default cohort exists** and the 3a `post_save` signal puts every non-staff `UserFactory`/`make_verified_user` user into it. So a plain student is in Default unless you reassign or delete the membership.

## File Structure

- **Modify** `courses/models.py` — add `Course.self_enroll_cohorts` M2M (Task 1).
- **Create** `courses/migrations/0021_course_self_enroll_cohorts.py` — auto-generated (Task 1).
- **Modify** `grouping/services.py` — `catalog_courses_for`, `can_self_enroll`, `enroll_self` (Tasks 2–3).
- **Modify** `courses/forms.py` — `CourseForm.self_enroll_cohorts` (Task 4).
- **Modify** `courses/views.py` — `catalog`, `catalog_detail`, `self_enroll` (Tasks 5–7).
- **Modify** `courses/urls.py` — three routes (Tasks 5–7).
- **Create** `templates/courses/catalog.html`, `templates/courses/_catalog_detail.html`, `templates/courses/catalog_detail.html` (Tasks 5–6).
- **Create** `courses/static/courses/js/catalog_modal.js` (Task 6).
- **Modify** `templates/base.html`, `templates/core/home.html` — nav link + dashboard card (Task 8).
- **Modify** `locale/pl/LC_MESSAGES/django.po` (+ template `.po` if present) — PL translations (Task 9).
- **Create** test files: `tests/test_catalog_service.py`, `tests/test_catalog_form.py`, `tests/test_catalog_views.py`, `tests/test_catalog_nav.py`, `tests/test_i18n_catalog.py`, `tests/test_e2e_catalog.py`.

---

### Task 1: Schema — `Course.self_enroll_cohorts` M2M + migration

**Files:**
- Modify: `courses/models.py` (the `Course` model, after the `visibility` field ~line 64)
- Create: `courses/migrations/0021_course_self_enroll_cohorts.py` (auto-generated; exact number may differ — use whatever `makemigrations` produces)
- Test: `tests/test_catalog_service.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Course.self_enroll_cohorts` (M2M → `grouping.Cohort`, `blank=True`, reverse `Cohort.self_enroll_courses`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog_service.py`:

```python
import pytest

from courses.models import Course
from tests.factories import CohortFactory, CourseFactory

pytestmark = pytest.mark.django_db


def test_course_has_self_enroll_cohorts_m2m():
    course = CourseFactory()
    cohort = CohortFactory(name="Year 9")
    course.self_enroll_cohorts.add(cohort)
    assert list(course.self_enroll_cohorts.all()) == [cohort]
    # reverse accessor
    assert list(cohort.self_enroll_courses.all()) == [course]


def test_self_enroll_cohorts_is_optional():
    course = CourseFactory()
    assert course.self_enroll_cohorts.count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_catalog_service.py -q`
Expected: FAIL — `AttributeError: 'Course' object has no attribute 'self_enroll_cohorts'`.

- [ ] **Step 3: Add the field**

In `courses/models.py`, inside `class Course`, immediately after the `visibility` field:

```python
    # Phase 3b: which cohorts may self-enroll when visibility="open".
    # Empty set = open to all students (see grouping.services.catalog_courses_for).
    # String ref avoids importing grouping (grouping.models already string-refs Course).
    self_enroll_cohorts = models.ManyToManyField(
        "grouping.Cohort", blank=True, related_name="self_enroll_courses"
    )
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations courses`
Expected: creates `courses/migrations/0021_course_self_enroll_cohorts.py`.

Open it and **verify** its `dependencies` list references `("grouping", "0001_initial")` (the migration that creates `Cohort`), auto-added by Django. Do NOT hand-add a dependency on a later grouping migration (e.g. `0003`) — it is unnecessary and wrong.

- [ ] **Step 5: Apply and run tests**

Run: `python manage.py migrate && pytest tests/test_catalog_service.py -q`
Expected: PASS (both tests).

- [ ] **Step 6: Lint + commit**

```bash
ruff check . && ruff format .
git add courses/models.py courses/migrations/ tests/test_catalog_service.py
git commit -m "feat(catalog): Course.self_enroll_cohorts M2M for cohort-gated open courses"
```

---

### Task 2: Service `catalog_courses_for`

**Files:**
- Modify: `grouping/services.py` (imports at top; new function near `recompute_enrollment`)
- Test: `tests/test_catalog_service.py`

**Interfaces:**
- Consumes: `Course.self_enroll_cohorts` (Task 1); `CohortMembership`, `ContentNode`.
- Produces: `catalog_courses_for(student) -> QuerySet[Course]` — eligible open courses (NOT ordered; caller applies `.order_by`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog_service.py`:

```python
from courses.models import ContentNode
from grouping.models import CohortMembership
from grouping.services import catalog_courses_for, get_default_cohort
from tests.factories import (
    ContentNodeFactory,
    CohortMembershipFactory,
    make_verified_user,
)


def _open_course_with_unit(**kw):
    course = CourseFactory(visibility="open", **kw)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    return course


def test_open_course_no_cohorts_visible_to_any_student():
    student = make_verified_user(username="s1", email="s1@t.example.com")
    course = _open_course_with_unit()
    assert course in catalog_courses_for(student)


def test_assigned_course_never_in_catalog():
    student = make_verified_user(username="s2", email="s2@t.example.com")
    course = CourseFactory(visibility="assigned")
    ContentNodeFactory(course=course, kind="unit")
    assert course not in catalog_courses_for(student)


def test_open_course_with_no_units_excluded():
    student = make_verified_user(username="s3", email="s3@t.example.com")
    course = CourseFactory(visibility="open")  # no units
    assert course not in catalog_courses_for(student)


def test_cohort_restricted_course_excluded_for_student_not_in_set():
    student = make_verified_user(username="s4", email="s4@t.example.com")  # in Default
    other = CohortFactory(name="Spanish")
    course = _open_course_with_unit()
    course.self_enroll_cohorts.add(other)
    assert course not in catalog_courses_for(student)


def test_cohort_restricted_course_visible_to_member():
    student = make_verified_user(username="s5", email="s5@t.example.com")
    cohort = CohortFactory(name="Year 10")
    CohortMembershipFactory(user=student, cohort=cohort)  # reassigns from Default
    course = _open_course_with_unit()
    course.self_enroll_cohorts.add(cohort)
    assert course in catalog_courses_for(student)


def test_student_with_no_membership_sees_only_empty_set_courses():
    student = make_verified_user(username="s6", email="s6@t.example.com")
    CohortMembership.objects.filter(user=student).delete()  # no cohort at all
    open_all = _open_course_with_unit()
    restricted = _open_course_with_unit()
    restricted.self_enroll_cohorts.add(CohortFactory(name="X"))
    visible = catalog_courses_for(student)
    assert open_all in visible
    assert restricted not in visible


def test_course_appears_exactly_once_despite_many_units_and_cohorts():
    student = make_verified_user(username="s7", email="s7@t.example.com")
    default = get_default_cohort()
    course = _open_course_with_unit()
    ContentNodeFactory(course=course, kind="unit")  # 2nd unit
    ContentNodeFactory(course=course, kind="unit")  # 3rd unit
    course.self_enroll_cohorts.add(default, CohortFactory(name="Y"))
    assert list(catalog_courses_for(student)).count(course) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_catalog_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'catalog_courses_for'`.

- [ ] **Step 3: Implement the service**

In `grouping/services.py`, extend the top-of-file imports:

```python
from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Q  # may already be imported — keep one copy

from courses.models import ContentNode
from courses.models import Course
from courses.models import Enrollment  # already imported — keep one copy
```

Add the function (place it just above `recompute_enrollment`):

```python
def catalog_courses_for(student):
    """Open courses this student may self-enroll in. Eligibility joins through the
    student's single cohort (CohortMembership.user); a student with NO membership
    matches only empty-set ("open to all") courses. The course must have >=1 unit
    (kind="unit", any unit_type). NOT ordered — the caller applies .order_by.
    .distinct() is required: the M2M OR-filter would otherwise emit one row per
    matching cohort. When cohort_id is None (no membership), the second Q arm
    degenerates to the empty-set arm, so the student matches only open-to-all
    courses (nothing extra)."""
    cohort_id = (
        CohortMembership.objects.filter(user=student)
        .values_list("cohort_id", flat=True)
        .first()
    )
    has_unit = ContentNode.objects.filter(course=OuterRef("pk"), kind="unit")
    return (
        Course.objects.filter(visibility="open")
        .filter(Q(self_enroll_cohorts__isnull=True) | Q(self_enroll_cohorts=cohort_id))
        .filter(Exists(has_unit))
        .distinct()
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_catalog_service.py -q`
Expected: PASS (all).

- [ ] **Step 5: Lint + commit**

```bash
ruff check . && ruff format .
git add grouping/services.py tests/test_catalog_service.py
git commit -m "feat(catalog): catalog_courses_for eligibility query"
```

---

### Task 3: Services `can_self_enroll` + `enroll_self`

**Files:**
- Modify: `grouping/services.py`
- Test: `tests/test_catalog_service.py`

**Interfaces:**
- Consumes: `catalog_courses_for` (Task 2); `is_staff_user` (existing); `Enrollment`.
- Produces:
  - `can_self_enroll(student, course) -> bool`
  - `enroll_self(student, course) -> Enrollment` (idempotent; never downgrades an existing row; NO eligibility check)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog_service.py`:

```python
from courses.models import Enrollment
from grouping.services import can_self_enroll, enroll_self
from tests.factories import EnrollmentFactory, make_pa


def test_can_self_enroll_true_for_eligible_student():
    student = make_verified_user(username="c1", email="c1@t.example.com")
    course = _open_course_with_unit()
    assert can_self_enroll(student, course) is True


def test_can_self_enroll_false_for_assigned_course():
    student = make_verified_user(username="c2", email="c2@t.example.com")
    course = CourseFactory(visibility="assigned")
    ContentNodeFactory(course=course, kind="unit")
    assert can_self_enroll(student, course) is False


def test_can_self_enroll_false_for_staff(client):
    # make_pa logs in a Platform Admin (staff via role). Staff have no cohort.
    staff = make_pa(client, username="capa")
    course = _open_course_with_unit()  # empty cohort set -> in catalog_courses_for
    assert course in catalog_courses_for(staff)        # divergence: catalog admits
    assert can_self_enroll(staff, course) is False     # ...but gate denies staff


def test_enroll_self_creates_self_sourced_row():
    student = make_verified_user(username="c3", email="c3@t.example.com")
    course = _open_course_with_unit()
    enrollment = enroll_self(student, course)
    assert enrollment.source == "self"
    assert Enrollment.objects.filter(student=student, course=course).count() == 1


def test_enroll_self_is_idempotent():
    student = make_verified_user(username="c4", email="c4@t.example.com")
    course = _open_course_with_unit()
    enroll_self(student, course)
    enroll_self(student, course)
    assert Enrollment.objects.filter(student=student, course=course).count() == 1


def test_enroll_self_never_downgrades_group_row():
    student = make_verified_user(username="c5", email="c5@t.example.com")
    course = _open_course_with_unit()
    # EnrollmentFactory writes the row directly (no recompute_enrollment), so the
    # source="group" precondition is durable and enroll_self's get_or_create is a
    # genuine no-op against it.
    EnrollmentFactory(student=student, course=course, source="group")
    enroll_self(student, course)
    row = Enrollment.objects.get(student=student, course=course)
    assert row.source == "group"  # unchanged
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_catalog_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'can_self_enroll'`.

- [ ] **Step 3: Implement the services**

In `grouping/services.py`, add after `catalog_courses_for`:

```python
def can_self_enroll(student, course):
    """Authoritative gate for the detail view and the enroll POST. Non-staff only,
    AND the course is in the student's catalog. Already-enrolled passes (the
    downstream enroll_self is an idempotent no-op)."""
    if is_staff_user(student):
        return False
    return catalog_courses_for(student).filter(pk=course.pk).exists()


def enroll_self(student, course):
    """Idempotent self-enroll. Performs NO eligibility check — the view is the sole
    gate. Never downgrades an existing group/manual row. Per-call savepoint so a
    concurrent create can't poison a surrounding transaction."""
    with transaction.atomic():
        enrollment, _created = Enrollment.objects.get_or_create(
            student=student, course=course, defaults={"source": "self"}
        )
    return enrollment
```

(`transaction` and `is_staff_user` are already in this module.)

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_catalog_service.py -q`
Expected: PASS (all).

- [ ] **Step 5: Lint + commit**

```bash
ruff check . && ruff format .
git add grouping/services.py tests/test_catalog_service.py
git commit -m "feat(catalog): can_self_enroll gate + idempotent enroll_self"
```

---

### Task 4: `CourseForm.self_enroll_cohorts`

**Files:**
- Modify: `courses/forms.py` (`CourseForm`)
- Test: `tests/test_catalog_form.py`

**Interfaces:**
- Consumes: `Course.self_enroll_cohorts` (Task 1); `Cohort`.
- Produces: `CourseForm` now exposes `self_enroll_cohorts` (checkbox list of non-archived cohorts ∪ already-selected).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_form.py`:

```python
import pytest

from courses.forms import CourseForm
from tests.factories import CohortFactory, CourseFactory

pytestmark = pytest.mark.django_db


def test_form_lists_non_archived_cohorts():
    live = CohortFactory(name="Live")
    archived = CohortFactory(name="Old", archived=True)
    form = CourseForm()
    qs = form.fields["self_enroll_cohorts"].queryset
    assert live in qs
    assert archived not in qs


def test_form_keeps_already_selected_archived_cohort():
    # A cohort archived AFTER being selected must stay rendered, else ModelMultiple-
    # ChoiceField treats it as invalid and silently drops it on the next save.
    archived = CohortFactory(name="Stale", archived=True)
    course = CourseFactory()
    course.self_enroll_cohorts.add(archived)
    form = CourseForm(instance=course)
    assert archived in form.fields["self_enroll_cohorts"].queryset


def test_form_saves_selected_cohorts():
    cohort = CohortFactory(name="Year 11")
    course = CourseFactory()
    form = CourseForm(
        data={
            "title": course.title,
            "slug": course.slug,
            "language": "en",
            "visibility": "open",
            "self_enroll_cohorts": [cohort.pk],
        },
        instance=course,
    )
    assert form.is_valid(), form.errors
    form.save()
    assert list(course.self_enroll_cohorts.all()) == [cohort]
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_catalog_form.py -q`
Expected: FAIL — `KeyError: 'self_enroll_cohorts'` (field not on the form).

- [ ] **Step 3: Implement**

In `courses/forms.py`:

Add the import at the top:

```python
from django.db.models import Q
```

Add `"self_enroll_cohorts"` to `Meta.fields` immediately after `"visibility"`. Add the widget and help text:

```python
        widgets = {
            # ...existing html_css / html_js widgets...
            "self_enroll_cohorts": forms.CheckboxSelectMultiple,
        }
        help_texts = {
            # ...existing...
            "self_enroll_cohorts": _("Leave empty = open to all students."),
        }
```

In the existing `__init__` (after `super().__init__(...)`), set the queryset:

```python
        from grouping.models import Cohort

        selected_pks = (
            list(self.instance.self_enroll_cohorts.values_list("pk", flat=True))
            if self.instance.pk
            else []
        )
        # Non-archived cohorts, plus any already-selected (possibly-archived) cohort,
        # as a single filterable Q-OR (NOT .union(), which can't be ordered for the
        # checkbox widget). Keeps an archived-after-selection cohort from being dropped.
        self.fields["self_enroll_cohorts"].queryset = Cohort.objects.filter(
            Q(archived=False) | Q(pk__in=selected_pks)
        ).order_by("-is_default", "name")
        self.fields["self_enroll_cohorts"].required = False
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_catalog_form.py -q`
Expected: PASS (all three).

- [ ] **Step 5: Lint + commit**

```bash
ruff check . && ruff format .
git add courses/forms.py tests/test_catalog_form.py
git commit -m "feat(catalog): CourseForm self_enroll_cohorts checkbox field"
```

---

### Task 5: `catalog` view + URL + page template + filters

**Files:**
- Modify: `courses/views.py` (imports + new `catalog` view)
- Modify: `courses/urls.py`
- Create: `templates/courses/catalog.html`
- Test: `tests/test_catalog_views.py`

**Interfaces:**
- Consumes: `catalog_courses_for` (Task 2); `Enrollment`, `Subject`, `COURSE_LANGUAGES`.
- Produces: URL name `courses:catalog`; template context `courses`, `enrolled_ids`, `subjects`, `languages`, `sel_subject`, `sel_language`, `q`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_views.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Enrollment
from grouping.models import CohortMembership
from tests.factories import (
    ContentNodeFactory,
    CohortFactory,
    CohortMembershipFactory,
    CourseFactory,
    EnrollmentFactory,
    SubjectFactory,
    make_login,
    make_pa,
)

pytestmark = pytest.mark.django_db


def _open_course_with_unit(**kw):
    course = CourseFactory(visibility="open", **kw)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    return course


def test_catalog_shows_open_course_and_marks_enrolled(client):
    student = make_login(client, "v2")
    open1 = _open_course_with_unit(title="Astro")
    enrolled = _open_course_with_unit(title="Bio")
    EnrollmentFactory(student=student, course=enrolled, source="group")
    resp = client.get(reverse("courses:catalog"))
    assert resp.status_code == 200
    assert open1 in resp.context["courses"]
    assert enrolled.pk in resp.context["enrolled_ids"]


def test_catalog_subject_filter(client):
    student = make_login(client, "v3")
    math = SubjectFactory(title="Math")
    _open_course_with_unit(title="Algebra", subject=math)
    _open_course_with_unit(title="History")  # no subject
    resp = client.get(reverse("courses:catalog"), {"subject": math.pk})
    titles = [c.title for c in resp.context["courses"]]
    assert titles == ["Algebra"]


def test_catalog_text_search_matches_title(client):
    make_login(client, "v4")
    _open_course_with_unit(title="Photosynthesis")
    _open_course_with_unit(title="Trigonometry")
    resp = client.get(reverse("courses:catalog"), {"q": "synth"})
    titles = [c.title for c in resp.context["courses"]]
    assert titles == ["Photosynthesis"]


def test_catalog_language_filter(client):
    make_login(client, "v5")
    _open_course_with_unit(title="EN course", language="en")
    _open_course_with_unit(title="PL course", language="pl")
    resp = client.get(reverse("courses:catalog"), {"language": "pl"})
    titles = [c.title for c in resp.context["courses"]]
    assert titles == ["PL course"]


def test_catalog_staff_sees_only_empty_set_open_courses(client):
    staff = make_pa(client, username="vpa")
    open_all = _open_course_with_unit(title="Open to all")
    restricted = _open_course_with_unit(title="Restricted")
    restricted.self_enroll_cohorts.add(CohortFactory(name="Z"))
    resp = client.get(reverse("courses:catalog"))
    courses = list(resp.context["courses"])
    assert open_all in courses
    assert restricted not in courses
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_catalog_views.py -q`
Expected: FAIL — `NoReverseMatch: 'catalog' is not a valid view function or pattern name`.

- [ ] **Step 3: Add imports to `courses/views.py`**

At the top of `courses/views.py`, ensure these are present (add any missing):

```python
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _

from courses.access import is_enrolled
from courses.constants import COURSE_LANGUAGES
from courses.models import Course
from courses.models import Enrollment
from courses.models import Subject
```

- [ ] **Step 4: Implement the `catalog` view**

Add to `courses/views.py`:

```python
@login_required
def catalog(request):
    """Browse open courses the student may self-enroll in. Filters are GET params
    composed on the (unfiltered) eligible set; option lists derive from that
    unfiltered set so picking one filter never erases the others' options."""
    from grouping.services import catalog_courses_for

    eligible = catalog_courses_for(request.user)

    subjects = (
        Subject.objects.filter(courses__in=eligible.values("pk"))
        .distinct()
        .order_by("title")
    )
    lang_labels = dict(COURSE_LANGUAGES)
    languages = [
        {"code": code, "label": lang_labels.get(code, code)}
        for code in eligible.values_list("language", flat=True).distinct()
    ]

    sel_subject = request.GET.get("subject") or ""
    sel_language = request.GET.get("language") or ""
    q = (request.GET.get("q") or "").strip()

    qs = eligible
    if sel_subject:
        qs = qs.filter(subject_id=sel_subject)
    if sel_language:
        qs = qs.filter(language=sel_language)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(overview__icontains=q))
    qs = qs.order_by("title")

    enrolled_ids = set(
        Enrollment.objects.filter(
            student=request.user, course__in=qs.values("pk")
        ).values_list("course_id", flat=True)
    )
    return render(
        request,
        "courses/catalog.html",
        {
            "courses": qs,
            "enrolled_ids": enrolled_ids,
            "subjects": subjects,
            "languages": languages,
            "sel_subject": sel_subject,
            "sel_language": sel_language,
            "q": q,
        },
    )
```

- [ ] **Step 5: Add the URL**

In `courses/urls.py`, add to `urlpatterns` (above the `courses/<slug:slug>/` block is fine — the `catalog/` prefix can't collide):

```python
    path("catalog/", views.catalog, name="catalog"),
```

- [ ] **Step 6: Create the catalog template**

Create `templates/courses/catalog.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Browse courses" %} — libli{% endblock %}
{% block content %}
<section class="catalog">
  <h1>{% trans "Browse courses" %}</h1>

  <form class="catalog__filters" method="get">
    <label>{% trans "Subject" %}
      <select name="subject">
        <option value="">{% trans "All subjects" %}</option>
        {% for s in subjects %}
          <option value="{{ s.pk }}" {% if sel_subject == s.pk|stringformat:"s" %}selected{% endif %}>{{ s.title }}</option>
        {% endfor %}
      </select>
    </label>
    <label>{% trans "Language" %}
      <select name="language">
        <option value="">{% trans "All languages" %}</option>
        {% for l in languages %}
          <option value="{{ l.code }}" {% if sel_language == l.code %}selected{% endif %}>{{ l.label }}</option>
        {% endfor %}
      </select>
    </label>
    <label>{% trans "Search" %}
      <input type="search" name="q" value="{{ q }}" placeholder="{% trans 'Title or description' %}">
    </label>
    <button class="btn btn--ghost" type="submit">{% trans "Filter" %}</button>
  </form>

  {% if courses %}
  <ul class="card-list catalog__grid">
    {% for course in courses %}
    <li class="card catalog__card">
      <h2>{{ course.title }}</h2>
      {% if course.subject %}<p class="badge">{{ course.subject.title }}</p>{% endif %}
      <p class="helptext">{{ course.get_language_display }}</p>
      {% if course.overview %}<p class="catalog__snippet">{{ course.overview|truncatewords:25 }}</p>{% endif %}
      <div class="row-actions">
        {% if course.pk in enrolled_ids %}
          <a class="btn btn--ghost" href="{% url 'courses:course_outline' slug=course.slug %}">{% trans "Open" %}</a>
        {% else %}
          <a class="btn btn--primary" data-catalog-detail
             href="{% url 'courses:catalog_detail' slug=course.slug %}">{% trans "Details" %}</a>
        {% endif %}
      </div>
    </li>
    {% endfor %}
  </ul>
  {% else %}
    <p class="empty">{% trans "No courses available to join right now." %}</p>
  {% endif %}

  {% comment %}
  Modal container + script are added in Task 6. The Details link above is a real
  navigable URL (catalog_detail full-page fallback) until JS upgrades it.
  {% endcomment %}
</section>
{% endblock %}
```

Note: `courses:catalog_detail` is referenced here but created in Task 6 — that is fine for subagent-driven execution because Task 6 lands before the template is exercised by a user, and the view tests in this task do not render the `{% url 'courses:catalog_detail' %}` tag with an enrolled-only fixture. **To keep this task's tests green now,** the `{% url 'courses:catalog_detail' ... %}` tag WILL raise `NoReverseMatch` at render time. Therefore: in Step 5 also add a placeholder route so the page renders:

```python
    path("catalog/<slug:slug>/", views.catalog_detail, name="catalog_detail"),
```

and add a minimal stub view in `courses/views.py` to be fleshed out in Task 6:

```python
@login_required
def catalog_detail(request, slug):  # fleshed out in Task 6
    raise Http404
```

The Task 5 tests assert on `resp.context["courses"]` / `enrolled_ids` and DO render the grid, so the stub route is required for them to pass.

- [ ] **Step 7: Run to verify they pass**

Run: `pytest tests/test_catalog_views.py -q`
Expected: PASS (all real tests).

- [ ] **Step 8: Lint + commit**

```bash
ruff check . && ruff format .
git add courses/views.py courses/urls.py templates/courses/catalog.html tests/test_catalog_views.py
git commit -m "feat(catalog): catalog view, filters, card grid"
```

---

### Task 6: `catalog_detail` view + fragment/page templates + modal JS

**Files:**
- Modify: `courses/views.py` (flesh out `catalog_detail`)
- Create: `templates/courses/_catalog_detail.html` (fragment partial)
- Create: `templates/courses/catalog_detail.html` (full-page wrapper)
- Create: `courses/static/courses/js/catalog_modal.js`
- Modify: `templates/courses/catalog.html` (add modal container + script block)
- Test: `tests/test_catalog_views.py`

**Interfaces:**
- Consumes: `can_self_enroll` (Task 3), `is_enrolled` (existing), `Course`.
- Produces: URL `courses:catalog_detail` (already routed in Task 5); renders fragment (XHR) or full page; body branches on `is_enrolled`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog_views.py`:

```python
def test_catalog_detail_full_page_for_eligible(client):
    make_login(client, "d1")
    course = _open_course_with_unit(title="Detail Me")
    resp = client.get(reverse("courses:catalog_detail", args=[course.slug]))
    assert resp.status_code == 200
    assert b"Detail Me" in resp.content
    # not-enrolled -> Enroll form present
    assert reverse("courses:self_enroll", args=[course.slug]).encode() in resp.content


def test_catalog_detail_fragment_via_xhr(client):
    make_login(client, "d2")
    course = _open_course_with_unit()
    resp = client.get(
        reverse("courses:catalog_detail", args=[course.slug]),
        HTTP_X_REQUESTED_WITH="fetch",  # matches the existing _wants_fragment convention
    )
    assert resp.status_code == 200
    assert resp.templates[0].name == "courses/_catalog_detail.html"


def test_catalog_detail_404_for_ineligible(client):
    make_login(client, "d3")
    course = CourseFactory(visibility="assigned")
    ContentNodeFactory(course=course, kind="unit")
    resp = client.get(reverse("courses:catalog_detail", args=[course.slug]))
    assert resp.status_code == 404


def test_catalog_detail_enrolled_but_ineligible_shows_outline_not_enroll(client):
    # Highest-risk branch: enrolled, but course no longer eligible (flipped to
    # assigned). Body must branch on is_enrolled, not the gate -> show outline link,
    # NO enroll form.
    student = make_login(client, "d4")
    course = _open_course_with_unit()
    EnrollmentFactory(student=student, course=course, source="self")
    course.visibility = "assigned"
    course.save(update_fields=["visibility"])
    resp = client.get(reverse("courses:catalog_detail", args=[course.slug]))
    assert resp.status_code == 200
    assert reverse("courses:course_outline", args=[course.slug]).encode() in resp.content
    assert b"Open course" in resp.content  # positive: enrolled branch rendered
    assert reverse("courses:self_enroll", args=[course.slug]).encode() not in resp.content
```

(These reference `courses:self_enroll`, added in Task 7. If executing strictly in order, add the Task-7 route stub now — see Task 7 Step 5 — or run Task 6 + Task 7 as a pair. Recommended: implement Task 7's URL + view first, then this task's tests pass cleanly. The subagent executing Task 6 should add the `self_enroll` route + a `require_POST` stub before running these tests.)

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_catalog_views.py -q`
Expected: FAIL — the stub `catalog_detail` raises 404 for everyone, so the eligible/fragment/enrolled tests fail.

- [ ] **Step 3: Flesh out the view**

Replace the Task-5 stub `catalog_detail` in `courses/views.py`:

```python
@login_required
def catalog_detail(request, slug):
    """Pre-enroll overview: modal fragment (XHR) or full-page fallback. Gated by
    can_self_enroll OR is_enrolled (NOT can_access_course). The body branches on
    is_enrolled so an already-enrolled user never sees an Enroll button."""
    from grouping.services import can_self_enroll

    course = get_object_or_404(Course, slug=slug)
    enrolled = is_enrolled(request.user, course)
    if not (enrolled or can_self_enroll(request.user, course)):
        raise Http404
    ctx = {
        "course": course,
        "enrolled": enrolled,
        "unit_count": course.nodes.filter(kind="unit").count(),
    }
    if _wants_fragment(request):
        return render(request, "courses/_catalog_detail.html", ctx)
    return render(request, "courses/catalog_detail.html", ctx)
```

Note: reuse the **existing** `_wants_fragment(request)` helper (`courses/views.py:56` — `X-Requested-With == "fetch"`), NOT the spec's illustrative `XMLHttpRequest` sentinel. One fragment convention per module; the modal JS (Step 6) and the test (Step 1) both send `fetch` to match.

- [ ] **Step 4: Create the fragment partial**

Create `templates/courses/_catalog_detail.html`:

```django
{% load i18n %}
<div class="catalog-detail">
  <h2>{{ course.title }}</h2>
  {% if course.subject %}<p class="badge">{{ course.subject.title }}</p>{% endif %}
  <p class="helptext">{{ course.get_language_display }}
    · {% blocktrans count n=unit_count %}{{ n }} unit{% plural %}{{ n }} units{% endblocktrans %}</p>
  {% if course.overview %}<div class="catalog-detail__overview">{{ course.overview|linebreaks }}</div>{% endif %}
  <div class="row-actions">
    {% if enrolled %}
      <a class="btn btn--primary" href="{% url 'courses:course_outline' slug=course.slug %}">{% trans "Open course" %}</a>
    {% else %}
      <form method="post" action="{% url 'courses:self_enroll' slug=course.slug %}">
        {% csrf_token %}
        <button class="btn btn--primary" type="submit">{% trans "Enroll" %}</button>
      </form>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 5: Create the full-page wrapper**

Create `templates/courses/catalog_detail.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{{ course.title }} — libli{% endblock %}
{% block content %}
<section class="catalog">
  <p><a class="app-nav__link" href="{% url 'courses:catalog' %}">← {% trans "Back to catalog" %}</a></p>
  {% include "courses/_catalog_detail.html" %}
</section>
{% endblock %}
```

- [ ] **Step 6: Create the modal JS**

Create `courses/static/courses/js/catalog_modal.js`:

```javascript
"use strict";
// Progressive enhancement: intercept [data-catalog-detail] links, fetch the
// server fragment with the XHR header, show it in the modal. With JS off the
// link is a normal navigation to the full detail page.
(function () {
  var modal = document.querySelector("[data-catalog-modal]");
  if (!modal) return;
  var body = modal.querySelector("[data-catalog-modal-body]");

  function close() {
    modal.hidden = true;
    body.innerHTML = "";
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-catalog-detail]");
    if (link) {
      e.preventDefault();
      fetch(link.href, { headers: { "X-Requested-With": "fetch" } })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          body.innerHTML = html;
          modal.hidden = false;
        });
      return;
    }
    if (e.target.closest("[data-catalog-modal-close]") || e.target === modal) {
      close();
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !modal.hidden) close();
  });
})();
```

- [ ] **Step 7: Wire the modal into the catalog page**

In `templates/courses/catalog.html`, replace the trailing `{% comment %}…{% endcomment %}` block with the modal container, and add the script block. Inside `<section class="catalog">`, before `</section>`:

```django
  <div class="modal" data-catalog-modal hidden>
    <div class="modal__panel">
      <button class="btn--icon" type="button" data-catalog-modal-close
              aria-label="{% trans 'Close' %}">×</button>
      <div data-catalog-modal-body></div>
    </div>
  </div>
```

After `{% endblock %}` content, add (or extend) an `extra_js` block at the end of the template:

```django
{% block extra_js %}{% load static %}<script src="{% static 'courses/js/catalog_modal.js' %}" defer></script>{% endblock %}
```

- [ ] **Step 8: Run to verify they pass**

Run: `pytest tests/test_catalog_views.py -q`
Expected: PASS (all detail tests).

- [ ] **Step 9: Lint + commit**

```bash
ruff check . && ruff format .
git add courses/views.py templates/courses/_catalog_detail.html templates/courses/catalog_detail.html templates/courses/catalog.html courses/static/courses/js/catalog_modal.js tests/test_catalog_views.py
git commit -m "feat(catalog): overview detail fragment, full-page fallback, modal JS"
```

---

### Task 7: `self_enroll` POST view + URL

**Files:**
- Modify: `courses/views.py` (new `self_enroll` view)
- Modify: `courses/urls.py`
- Test: `tests/test_catalog_views.py`

**Interfaces:**
- Consumes: `can_self_enroll`, `enroll_self` (Task 3); `Course`.
- Produces: URL `courses:self_enroll` (POST); creates `Enrollment(source="self")`; redirects to outline.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_catalog_views.py`:

```python
def test_self_enroll_creates_self_enrollment_and_redirects(client):
    student = make_login(client, "e1")
    course = _open_course_with_unit()
    resp = client.post(reverse("courses:self_enroll", args=[course.slug]))
    assert resp.status_code == 302
    assert resp.url == reverse("courses:course_outline", args=[course.slug])
    assert Enrollment.objects.filter(
        student=student, course=course, source="self"
    ).exists()


def test_self_enroll_get_not_allowed(client):
    make_login(client, "e2")
    course = _open_course_with_unit()
    resp = client.get(reverse("courses:self_enroll", args=[course.slug]))
    assert resp.status_code == 405


def test_self_enroll_ineligible_404(client):
    make_login(client, "e3")
    course = CourseFactory(visibility="assigned")
    ContentNodeFactory(course=course, kind="unit")
    resp = client.post(reverse("courses:self_enroll", args=[course.slug]))
    assert resp.status_code == 404


def test_self_enroll_staff_rejected_404(client):
    make_pa(client, username="epa")
    course = _open_course_with_unit()  # empty cohort set
    resp = client.post(reverse("courses:self_enroll", args=[course.slug]))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_catalog_views.py -q`
Expected: FAIL — `NoReverseMatch` (if the stub route wasn't added in Task 6) or 404/405 mismatches against the stub.

- [ ] **Step 3: Add the `require_POST` import**

Ensure `courses/views.py` imports:

```python
from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
```

- [ ] **Step 4: Implement the view**

Add to `courses/views.py` (replacing any Task-6 stub):

```python
@login_required
@require_POST
def self_enroll(request, slug):
    """Self-enroll the student in an open course. Re-checks eligibility server-side
    (the button is never trusted); ineligible -> 404. Calls the enroll_self service."""
    from grouping.services import can_self_enroll, enroll_self

    course = get_object_or_404(Course, slug=slug)
    if not can_self_enroll(request.user, course):
        raise Http404
    enroll_self(request.user, course)
    messages.success(
        request, _("You're now enrolled in %(course)s.") % {"course": course.title}
    )
    return redirect("courses:course_outline", slug=course.slug)
```

- [ ] **Step 5: Add the URL**

In `courses/urls.py`, add:

```python
    path("catalog/<slug:slug>/enroll/", views.self_enroll, name="self_enroll"),
```

- [ ] **Step 6: Run to verify they pass**

Run: `pytest tests/test_catalog_views.py -q`
Expected: PASS (all).

- [ ] **Step 7: Lint + commit**

```bash
ruff check . && ruff format .
git add courses/views.py courses/urls.py tests/test_catalog_views.py
git commit -m "feat(catalog): self_enroll POST view (404 on ineligible, redirect on success)"
```

---

### Task 8: Navigation — nav link + dashboard card

**Files:**
- Modify: `templates/base.html` (app-nav)
- Modify: `templates/core/home.html` (My learning card)
- Test: `tests/test_catalog_nav.py`

**Interfaces:**
- Consumes: URL `courses:catalog` (Task 5); template flags `is_teacher`/`is_course_admin`/`is_platform_admin` (existing context processor), `user.is_staff`, `user.is_superuser`.
- Produces: a "Browse" nav link and a dashboard link, shown only to non-staff (students).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalog_nav.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import make_login, make_pa

pytestmark = pytest.mark.django_db


def test_student_sees_browse_link_on_dashboard(client):
    make_login(client, "n1")
    resp = client.get(reverse("home"))
    assert reverse("courses:catalog").encode() in resp.content


def test_staff_does_not_see_browse_link(client):
    make_pa(client, username="npa")
    resp = client.get(reverse("home"))
    assert reverse("courses:catalog").encode() not in resp.content
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_catalog_nav.py -q`
Expected: FAIL — the catalog URL appears nowhere on the dashboard yet.

- [ ] **Step 3: Add the nav link**

In `templates/base.html`, inside `<nav class="app-nav">`, after the "Courses" link (~line 59), add:

```django
          {% comment %}
          "student" = non-staff (no staff role, not is_staff/superuser) — mirrors
          grouping.services.is_staff_user. The catalog views are login_required only;
          this link is merely hidden from staff to keep their nav clean.
          Do NOT simplify to positive `is_student`: catalog-eligible students include
          role-less make_verified_user / admin-created accounts that lack the Student
          role, which a positive is_student gate would wrongly hide.
          {% endcomment %}
          {% if not user.is_staff and not user.is_superuser and not is_teacher and not is_course_admin and not is_platform_admin %}
          <a class="app-nav__link" href="{% url 'courses:catalog' %}">{% trans "Browse" %}</a>
          {% endif %}
```

- [ ] **Step 4: Add the dashboard link**

In `templates/core/home.html`, inside the "My learning" `<section>` (after the courses list / empty paragraph, before `</section>` at ~line 21), add:

```django
  {% if not user.is_staff and not user.is_superuser and not is_teacher and not is_course_admin and not is_platform_admin %}
  <p><a class="btn btn--ghost" href="{% url 'courses:catalog' %}">{% trans "Browse courses" %}</a></p>
  {% endif %}
```

- [ ] **Step 5: Run to verify they pass**

Run: `pytest tests/test_catalog_nav.py -q`
Expected: PASS (both).

- [ ] **Step 6: Lint + commit**

```bash
ruff check . && ruff format .
git add templates/base.html templates/core/home.html tests/test_catalog_nav.py
git commit -m "feat(catalog): Browse nav link + dashboard entry for students"
```

---

### Task 9: Polish (PL) translations

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ `djangojs.po` if the project tracks JS strings — the modal JS has no user-facing strings, so likely only `django.po`)
- Test: `tests/test_i18n_catalog.py`

**Interfaces:**
- Consumes: all `{% trans %}` / `_()` strings added in Tasks 4–8.
- Produces: PL translations for every new catalog string.

- [ ] **Step 1: Write the failing test**

Create `tests/test_i18n_catalog.py` (mirrors the existing `test_i18n_*` pattern — assert the rendered page is Polish under `pl`):

```python
import pytest
from django.urls import reverse

from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_catalog_heading_translated_to_polish(client):
    make_login(client, "i1")
    # LocaleMiddleware re-activates the language per request from the session /
    # Accept-Language — translation.override() alone does NOT control what the test
    # client renders. Mirror the proven pattern in tests/test_i18n_results.py.
    session = client.session
    session["_language"] = "pl"
    session.save()
    resp = client.get(reverse("courses:catalog"), HTTP_ACCEPT_LANGUAGE="pl")
    # "Browse courses" must NOT appear untranslated; the PL string must be present.
    assert b"Browse courses" not in resp.content
    assert "Przeglądaj kursy".encode() in resp.content
```

(If the team's preferred PL wording differs, adjust the expected string and the `.po` entry together.)

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_i18n_catalog.py -q`
Expected: FAIL — the heading renders in English (no PL translation yet).

- [ ] **Step 3: Extract messages**

Run: `python manage.py makemessages -l pl`
Expected: new `msgid` entries appear in `locale/pl/LC_MESSAGES/django.po` for every new string (`Browse courses`, `Browse`, `Subject`, `Language`, `Search`, `Filter`, `All subjects`, `All languages`, `Title or description`, `Open`, `Details`, `No courses available to join right now.`, `Open course`, `Enroll`, `Back to catalog`, `Close`, `You're now enrolled in %(course)s.`, `Leave empty = open to all students.`, the `{n} unit/{n} units` plural, etc.).

- [ ] **Step 4: Fill in the Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po`, providing `msgstr` for each new `msgid`. Suggested copy (adjust to house style):

```
msgid "Browse courses"
msgstr "Przeglądaj kursy"

msgid "Browse"
msgstr "Przeglądaj"

msgid "Subject"
msgstr "Przedmiot"

msgid "Language"
msgstr "Język"

msgid "Search"
msgstr "Szukaj"

msgid "Filter"
msgstr "Filtruj"

msgid "All subjects"
msgstr "Wszystkie przedmioty"

msgid "All languages"
msgstr "Wszystkie języki"

msgid "Title or description"
msgstr "Tytuł lub opis"

msgid "Open"
msgstr "Otwórz"

msgid "Details"
msgstr "Szczegóły"

msgid "No courses available to join right now."
msgstr "Brak kursów, do których możesz teraz dołączyć."

msgid "Open course"
msgstr "Otwórz kurs"

msgid "Enroll"
msgstr "Zapisz się"

msgid "Back to catalog"
msgstr "Powrót do katalogu"

msgid "Close"
msgstr "Zamknij"

#, python-format
msgid "You're now enrolled in %(course)s."
msgstr "Zapisano Cię na kurs %(course)s."

msgid "Leave empty = open to all students."
msgstr "Pozostaw puste = otwarte dla wszystkich uczniów."
```

For the unit-count plural, fill the `msgstr[0]`/`msgstr[1]`/`msgstr[2]` forms (Polish has three plural forms), e.g. `msgstr[0] "%(n)s jednostka"`, `msgstr[1] "%(n)s jednostki"`, `msgstr[2] "%(n)s jednostek"`.

- [ ] **Step 5: Compile and run the test**

Run: `python manage.py compilemessages -l pl && pytest tests/test_i18n_catalog.py -q`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
ruff check . && ruff format .
git add locale/ tests/test_i18n_catalog.py
git commit -m "i18n(catalog): Polish translations for the self-enroll catalog"
```

---

### Task 10: e2e — browse → modal → enroll → outline

**Files:**
- Create: `tests/test_e2e_catalog.py`

**Interfaces:**
- Consumes: the whole feature (Tasks 1–9).
- Produces: a Playwright test driving the real gesture (no `page.evaluate` shortcuts), per the e2e-must-drive-real-UI lesson.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_catalog.py`:

```python
"""Playwright e2e for the self-enroll catalog. Marked `e2e` (excluded by default)."""

import os

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed_open_course():
    """A verified student (in Default cohort) + an open course with a unit, no enrollment."""
    from courses.models import Element, TextElement
    from tests.factories import (
        ContentNodeFactory,
        CourseFactory,
        SubjectFactory,
        make_verified_user,
    )

    user = make_verified_user(username="e2ecat", email="e2ecat@school.edu")
    course = CourseFactory(
        slug="e2e-open", title="E2E Open Course", visibility="open",
        subject=SubjectFactory(title="Science"), overview="A great course.",
    )
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="U1")
    el = Element.objects.create(unit=unit, content_object=TextElement.objects.create(body="<p>hi</p>"))
    return "e2ecat", course.slug


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    # Wait for the login POST/redirect to finish before navigating on, else the
    # next page.goto can race the redirect and land back on the login page.
    page.wait_for_selector("form[action*='login']", state="detached")


@pytest.mark.django_db(transaction=True)
def test_browse_open_modal_enroll_lands_on_outline(page, live_server):
    username, slug = _seed_open_course()
    _login(page, live_server, username)

    # Browse the catalog and open the overview modal via the real Details click.
    page.goto(f"{live_server.url}/catalog/")
    page.get_by_role("link", name="Details").first.click()

    # Modal shows the overview with a live Enroll button; click it (real gesture).
    modal = page.locator("[data-catalog-modal]")
    modal.get_by_role("button", name="Enroll").click()

    # Lands on the course outline; the course is now in "My courses".
    page.wait_for_url(f"**/courses/{slug}/")
    assert "E2E Open Course" in page.content()
```

- [ ] **Step 2: Run the e2e test**

Run: `pytest tests/test_e2e_catalog.py -m e2e -q`
Expected: PASS. (Requires Playwright browsers installed: `python -m playwright install chromium` if not already.)

- [ ] **Step 3: Run the full suite (non-e2e) to confirm no regressions**

Run: `pytest -q`
Expected: PASS, no failures.

- [ ] **Step 4: Lint + commit**

```bash
ruff check . && ruff format .
git add tests/test_e2e_catalog.py
git commit -m "test(catalog): e2e browse -> modal -> enroll -> outline (real gestures)"
```

---

## Self-Review

**1. Spec coverage:**
- §1 Schema → Task 1. ✓
- §2 Services (`catalog_courses_for`, `can_self_enroll`, `enroll_self`, naming split, no-cohort case, dedupe, no-downgrade, accepted-race-can't-raise) → Tasks 2–3. ✓
- §3 Views (`catalog` pipeline + filters + enrolled_ids; `catalog_detail` fragment-vs-page via X-Requested-With, body branches on is_enrolled, slug 404; `self_enroll` POST, 404 ineligible, redirect+message) → Tasks 5–7. ✓
- §4 UI (card grid, overview modal + degrade, CourseForm cohort field after `visibility` with Q-OR queryset, nav link + dashboard card hidden from staff, i18n) → Tasks 4, 5, 6, 8, 9. ✓
- §5 Access (unchanged; detail bypasses can_access_course) → honored in Task 6 (gate is can_self_enroll OR is_enrolled). ✓
- Edge cases (open→assigned persists; cohort dropped persists; empty course excluded; already-enrolled marked; concurrent enroll one row; staff browsing) → covered by service tests (Tasks 2–3) + view tests (Tasks 5–7). ✓
- Testing matrix (no-cohort student, appears-once, restricted-excluded, staff-by-URL, enrolled-but-ineligible detail branch, form, e2e) → Tasks 2, 3, 5, 6, 7, 4, 10. ✓
- Resolved deferrals (404 not 403; enroll_self no guard) → Global Constraints + Tasks 6–7. ✓

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — all code is shown. The one illustrative stub in Task 5 Step 1 (`test_catalog_lists_eligible_open_courses`) is explicitly flagged for deletion. The Task 5/6/7 ordering coupling (`catalog_detail`/`self_enroll` route stubs) is called out inline so a subagent doesn't hit `NoReverseMatch`.

**3. Type consistency:** Service names consistent across tasks: `catalog_courses_for`, `can_self_enroll`, `enroll_self` (write service) vs view `self_enroll` (the naming split is the whole point). URL names: `courses:catalog`, `courses:catalog_detail`, `courses:self_enroll`. Template context keys (`courses`, `enrolled_ids`, `subjects`, `languages`, `sel_subject`, `sel_language`, `q`; `course`, `enrolled`, `unit_count`) are produced in Tasks 5–6 and consumed by their templates. Cohort lookup uses `user=` (not `student=`) per the asymmetry constraint.
