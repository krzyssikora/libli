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
    from institution.roles import STUDENT
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    pa = _make_pa_user()
    course = CourseFactory(owner=pa, slug="e2e-grp-course")
    student = UserFactory(username="e2e_student")
    # The group roster picker now shows only Student-role users; add the student
    # to that role so their checkbox renders in the picker.
    student.groups.add(AuthGroup.objects.get(name=STUDENT))

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")
    page.locator("input[name='name']").fill("7A")
    page.select_option("select[name='course']", str(course.pk))
    page.check(f"input[name='students'][value='{student.pk}']")
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
def test_roster_search_filters_and_added_count_is_live(page, live_server):
    """Drive the real JS: typing in the student picker's name search hides
    non-matching rows (without dropping them), and the 'Added' count updates live
    when a box is checked."""
    from playwright.sync_api import expect

    from institution.roles import STUDENT
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-roster-course")
    alice = UserFactory(username="alice_roster")
    bob = UserFactory(username="bob_roster")
    for u in (alice, bob):
        u.groups.add(AuthGroup.objects.get(name=STUDENT))

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    # Two roster components render in order: teachers (0), students (1).
    students = page.locator("[data-roster]").nth(1)
    alice_row = students.locator("label[data-name='alice_roster']")
    bob_row = students.locator("label[data-name='bob_roster']")
    expect(alice_row).to_be_visible()
    expect(bob_row).to_be_visible()

    # Name search hides the non-matching row (but keeps it in the DOM).
    students.locator("[data-roster-search]").fill("alice")
    expect(alice_row).to_be_visible()
    expect(bob_row).to_be_hidden()

    # The 'Added' count goes live as soon as a checkbox is ticked. On a NEW group
    # nothing is saved yet, so ticking one diverges from the saved baseline (0).
    added = students.locator("[data-roster-selected]")
    expect(added).to_have_text("0")
    alice_row.locator("input[name='students']").check()
    expect(added).to_have_text("1 (saved: 0)")


@pytest.mark.django_db(transaction=True)
def test_added_count_shows_saved_baseline_on_unsaved_changes(page, live_server):
    """On edit, the count shows just N while it matches what's saved, and switches
    to 'N (saved: M)' the moment the live selection diverges."""
    from playwright.sync_api import expect

    from grouping import services
    from grouping.models import Group
    from institution.roles import STUDENT
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    pa = _make_pa_user()
    course = CourseFactory(owner=pa, slug="e2e-saved-course")
    alice = UserFactory(username="alice_saved")
    bob = UserFactory(username="bob_saved")
    for u in (alice, bob):
        u.groups.add(AuthGroup.objects.get(name=STUDENT))
    group = Group.objects.create(name="9B", course=course)
    services.add_students_to_group(group, [alice])  # alice is the saved baseline

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/{group.pk}/edit/")

    students = page.locator("[data-roster]").nth(1)
    added = students.locator("[data-roster-selected]")
    expect(added).to_have_text("1")  # matches saved -> bare count

    bob_row = students.locator("label[data-name='bob_saved']")
    bob_row.locator("input[name='students']").check()
    expect(added).to_have_text("2 (saved: 1)")  # diverged -> show baseline

    bob_row.locator("input[name='students']").uncheck()
    expect(added).to_have_text("1")  # back in sync -> bare count again


@pytest.mark.django_db(transaction=True)
def test_teacher_picker_search_filters_rows(page, live_server):
    """The teacher picker is a Django CheckboxSelectMultiple (div/label rows, no
    data-name). Its name search must still hide non-matching teacher rows."""
    from playwright.sync_api import expect

    from institution.roles import TEACHER
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-teacher-course")
    # display_name="" so the row shows the username (User.__str__ falls back to it).
    tina = UserFactory(username="tina_teacher", display_name="")
    tom = UserFactory(username="tom_teacher", display_name="")
    for u in (tina, tom):
        u.groups.add(AuthGroup.objects.get(name=TEACHER))

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    teachers = page.locator("[data-roster]").nth(0)
    tina_row = teachers.locator("label", has_text="tina_teacher")
    tom_row = teachers.locator("label", has_text="tom_teacher")
    expect(tina_row).to_be_visible()
    expect(tom_row).to_be_visible()

    teachers.locator("[data-roster-search]").fill("tina")
    expect(tina_row).to_be_visible()
    expect(tom_row).to_be_hidden()


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
