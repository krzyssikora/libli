"""Playwright e2e for the grouping management surfaces (Phase 3a).

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user():
    from accounts.emails import ensure_verified_primary_email
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = User.objects.create_user(
        username="e2e_pa", email="e2epa@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(user, "e2epa@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    # Selectors mirror the PROVEN helper in tests/test_e2e_courses.py (and the
    # other e2e suites): allauth's login field is `login` (username OR email),
    # and the form action contains "login". Username login works because the
    # project's existing e2e suites log in by username via this exact pattern.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_create_group_and_add_student_via_ui(page, live_server):
    from courses.models import Enrollment
    from grouping.models import Group
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    pa = _make_pa_user()
    course = CourseFactory(owner=pa, slug="e2e-grp-course")
    student = UserFactory(username="e2e_student")

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")
    page.locator("input[name='name']").fill("7A")
    page.select_option("select[name='course']", str(course.pk))
    page.select_option("select[name='students']", str(student.pk))
    # Use role+name to target the form's Save button, avoiding the language-
    # switcher and log-out buttons that are also button[type=submit] on the page.
    page.get_by_role("button", name="Save").click()

    # Real outcome: membership + group-sourced enrollment created.
    group = Group.objects.get(name="7A")
    assert group.memberships.filter(student=student).exists()
    assert Enrollment.objects.filter(
        student=student, course=course, source="group"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_delete_cohort_reassigns_to_default_via_ui(page, live_server):
    from grouping import services
    from grouping.models import Cohort
    from grouping.models import CohortMembership
    from tests.factories import CohortFactory
    from tests.factories import UserFactory

    _make_pa_user()
    # TransactionTestCase flushes the DB before each test, removing the Default
    # cohort that migration 0002 created.  Re-create it explicitly so the
    # delete_cohort service can reassign members to a real row.
    default, _ = Cohort.objects.get_or_create(
        slug="default", defaults={"name": "Default", "is_default": True}
    )
    other = CohortFactory(name="E2E Spanish")
    student = UserFactory(username="e2e_reassign")
    services.assign_student_to_cohort(student, other)

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/cohorts/{other.slug}/delete/")
    # Use role+name to target the form's Delete button, avoiding the language-
    # switcher and log-out buttons that are also button[type=submit] on the page.
    page.get_by_role("button", name="Delete").click()

    assert not Cohort.objects.filter(pk=other.pk).exists()
    assert CohortMembership.objects.get(user=student).cohort == default
