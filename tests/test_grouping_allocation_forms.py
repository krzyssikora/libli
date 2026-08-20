import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping.forms import AllocationForm
from grouping.models import Allocation
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from tests.factories import AllocationFactory
from tests.factories import CohortFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _role_user(role_name, username):
    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    # Same shape as tests/factories.py::_make_role — a freshly created user has
    # never had has_perm() called on it, so these attributes do not exist yet and
    # a bare `del` would AttributeError before any assertion runs.
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_course_queryset_excludes_courses_the_ca_does_not_own():
    """This restriction IS the create-time gate; there is no PermissionDenied."""
    ca = _role_user(COURSE_ADMIN, "ca_form")
    mine = CourseFactory(owner=ca)
    theirs = CourseFactory()
    form = AllocationForm(user=ca)
    pks = set(form.fields["course"].queryset.values_list("pk", flat=True))
    assert mine.pk in pks
    assert theirs.pk not in pks


def test_platform_admin_sees_every_course():
    pa = _role_user(PLATFORM_ADMIN, "pa_form")
    other = CourseFactory()
    form = AllocationForm(user=pa)
    assert other.pk in set(form.fields["course"].queryset.values_list("pk", flat=True))


def test_posting_an_unowned_course_is_a_field_error_and_creates_nothing():
    ca = _role_user(COURSE_ADMIN, "ca_post")
    theirs = CourseFactory()
    form = AllocationForm(data={"name": "X", "course": theirs.pk}, user=ca)
    assert not form.is_valid()
    assert "course" in form.errors
    assert Allocation.objects.count() == 0


def test_rejects_case_different_duplicate_name_on_the_same_course_at_create():
    """Create path: instance.course_id is None, so the check must read
    cleaned_data['course'] — which is why it lives in clean(), not clean_name()."""
    pa = _role_user(PLATFORM_ADMIN, "pa_dupe")
    existing = AllocationFactory(name="Klasy")
    form = AllocationForm(data={"name": "klasy", "course": existing.course_id}, user=pa)
    assert not form.is_valid()
    assert "name" in form.errors


def test_allows_the_same_name_on_a_different_course():
    pa = _role_user(PLATFORM_ADMIN, "pa_dupe2")
    AllocationFactory(name="Klasy")
    form = AllocationForm(data={"name": "Klasy", "course": CourseFactory().pk}, user=pa)
    assert form.is_valid(), form.errors


def test_rejects_a_name_held_by_an_archived_allocation():
    """The unique constraint has no `archived` condition, so scoping the dedup
    lookup to archived=False would hit an unhandled IntegrityError in save()."""
    pa = _role_user(PLATFORM_ADMIN, "pa_arch_dupe")
    existing = AllocationFactory(name="Klasy", archived=True)
    form = AllocationForm(data={"name": "klasy", "course": existing.course_id}, user=pa)
    assert not form.is_valid()
    assert "name" in form.errors


def test_editing_keeps_its_own_name():
    pa = _role_user(PLATFORM_ADMIN, "pa_selfedit")
    a = AllocationFactory(name="Klasy")
    form = AllocationForm(
        data={"name": "Klasy", "course": a.course_id}, instance=a, user=pa
    )
    assert form.is_valid(), form.errors


def test_cohorts_queryset_keeps_an_already_attached_archived_cohort():
    pa = _role_user(PLATFORM_ADMIN, "pa_cohorts")
    a = AllocationFactory()
    archived = CohortFactory(archived=True)
    a.cohorts.add(archived)
    form = AllocationForm(instance=a, user=pa)
    assert archived.pk in set(
        form.fields["cohorts"].queryset.values_list("pk", flat=True)
    )


def test_editing_an_allocation_keeps_its_archived_cohort_in_the_m2m():
    """Vacuity trap: under the mutant the POST is REJECTED (invalid_choice), so
    nothing saves and 'the cohort survives' would pass anyway. Assert the save
    SUCCEEDED as well."""
    pa = _role_user(PLATFORM_ADMIN, "pa_cohort_save")
    a = AllocationFactory(name="A")
    archived = CohortFactory(archived=True)
    live = CohortFactory()
    a.cohorts.set([archived, live])
    form = AllocationForm(
        data={
            "name": "A renamed",
            "course": a.course_id,
            "cohorts": [archived.pk, live.pk],
        },
        instance=a,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    a.refresh_from_db()
    assert a.name == "A renamed"
    assert set(a.cohorts.values_list("pk", flat=True)) == {archived.pk, live.pk}


def test_attached_archived_cohort_renders_with_a_suffix():
    """Spec row 11i, cohort half. Assert on the RENDERED checkbox list."""
    pa = _role_user(PLATFORM_ADMIN, "pa_cohort_label")
    a = AllocationFactory()
    archived = CohortFactory(name="Rocznik 2024", archived=True)
    a.cohorts.add(archived)
    form = AllocationForm(instance=a, user=pa)
    html = str(form["cohorts"])
    assert "Rocznik 2024" in html
    assert "archived" in html.lower()


def test_course_disabled_once_groups_are_attached():
    pa = _role_user(PLATFORM_ADMIN, "pa_lock")
    a = AllocationFactory()
    GroupFactory(course=a.course, allocation=a)
    form = AllocationForm(instance=a, user=pa)
    assert form.fields["course"].disabled is True
