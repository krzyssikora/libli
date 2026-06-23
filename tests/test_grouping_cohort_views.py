import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from grouping.models import Cohort
from grouping.models import CohortMembership
from grouping.services import get_default_cohort
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import CohortFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_cohort_list_requires_permission(client):
    make_login(client, "plainstudent")
    resp = client.get(reverse("grouping:cohort_list"))
    assert resp.status_code == 403


def test_course_admin_cannot_reach_cohort_list(client):
    # CA holds only `view_cohort` (for the picker filter), not `change_cohort`,
    # so the PA-only management list must 403 for a Course Admin (spec §4).
    seed_roles()
    user = make_login(client, "courseadmin")
    user.groups.add(AuthGroup.objects.get(name="Course Admin"))
    resp = client.get(reverse("grouping:cohort_list"))
    assert resp.status_code == 403


def test_pa_can_create_cohort(client):
    make_pa(client)
    resp = client.post(reverse("grouping:cohort_create"), {"name": "Year 9"})
    assert resp.status_code == 302
    assert Cohort.objects.filter(name="Year 9").exists()


def test_pa_can_promote_default(client):
    make_pa(client)
    other = CohortFactory(name="Year 10")
    resp = client.post(reverse("grouping:cohort_promote", args=[other.slug]))
    assert resp.status_code == 302
    other.refresh_from_db()
    assert other.is_default is True


def test_pa_cannot_delete_default(client):
    make_pa(client)
    default = get_default_cohort()
    resp = client.post(reverse("grouping:cohort_delete", args=[default.slug]))
    # Service raises ValidationError -> view re-renders the confirm page with the
    # error surfaced (200), and the row survives. Assert all three so a regression
    # that swallowed the error or redirected can't pass.
    assert resp.status_code == 200
    assert resp.context["error"]
    assert Cohort.objects.filter(pk=default.pk).exists()


def test_archive_via_ui_reassigns_members_and_guards_default(client):
    # Archiving routes through services.archive_cohort, so members move to Default
    # and the Default cohort itself can never be archived (spec §2/§3).
    make_pa(client)
    default = get_default_cohort()
    other = CohortFactory(name="Spanish")
    student = UserFactory()
    from grouping import services

    services.assign_student_to_cohort(student, other)
    resp = client.post(reverse("grouping:cohort_archive", args=[other.slug]))
    assert resp.status_code == 302
    other.refresh_from_db()
    assert other.archived is True
    assert CohortMembership.objects.get(user=student).cohort == default
    # Archiving the Default is a no-op (guarded).
    client.post(reverse("grouping:cohort_archive", args=[default.slug]))
    default.refresh_from_db()
    assert default.archived is False


def test_pa_can_assign_student_to_cohort(client):
    make_pa(client)
    target = CohortFactory(name="Year 11")
    student = UserFactory()  # starts in Default via the signal
    resp = client.post(
        reverse("grouping:cohort_assign_students", args=[target.slug]),
        {"students": [student.pk]},
    )
    assert resp.status_code == 302
    assert CohortMembership.objects.get(user=student).cohort == target


def test_cohort_assign_picker_students_only_and_excludes_current_members(client):
    """cohort_edit GET: all_students includes any non-staff user (even one with no
    role, as created via Django admin), excludes current members of this cohort,
    and excludes staff (Teacher role)."""
    seed_roles()
    make_pa(client)
    cohort = CohortFactory(name="Year 8")

    # A plain non-staff user with no role — must appear (admin-created learner).
    plain = UserFactory(username="plain_no_role_student")

    # A user explicitly in the Student role — also must appear.
    eligible = UserFactory(username="eligible_student")
    eligible.groups.add(AuthGroup.objects.get(name=STUDENT))

    # A Student already assigned to this cohort — must NOT appear.
    already_in = UserFactory(username="already_in_student")
    already_in.groups.add(AuthGroup.objects.get(name=STUDENT))
    from grouping import services

    services.assign_student_to_cohort(already_in, cohort)

    # A Teacher — must NOT appear (staff excluded).
    teacher = UserFactory(username="picker_teacher")
    teacher.groups.add(AuthGroup.objects.get(name=TEACHER))

    resp = client.get(reverse("grouping:cohort_edit", args=[cohort.slug]))
    assert resp.status_code == 200
    picker_ids = {u.pk for u in resp.context["all_students"]}

    assert plain.pk in picker_ids, "Plain non-staff user must appear in picker"
    assert eligible.pk in picker_ids, "Eligible student must appear in picker"
    assert already_in.pk not in picker_ids, "Current member must not appear in picker"
    assert teacher.pk not in picker_ids, "Teacher must not appear in picker"
