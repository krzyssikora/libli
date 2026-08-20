"""Playwright e2e for Task 9: the roster "add-all" checkbox and the group
form's client-side allocation-select filter.

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


def _make_pa_user(username="e2e_pa"):
    from accounts.emails import ensure_verified_primary_email
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = User.objects.create_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(user, f"{username}@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    # Same proven pattern as tests/test_e2e_grouping.py::_login.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _students_fieldset(page):
    """Anchor on the [data-roster] fieldset that carries [data-roster-cohort] —
    only the students roster does. Locating by the add-all label text would
    match BOTH roster fieldsets (teachers and students each get one) and be a
    Playwright strict-mode violation."""
    return page.locator("[data-roster]").filter(
        has=page.locator("[data-roster-cohort]")
    )


def _make_cohort_students():
    """A cohort with two students (alice, bob) plus one cohortless student
    (carol), all Student-role. Used by every add-all cohort-filter test:
    filtering to the cohort must show alice+bob and hide carol."""
    from grouping import services
    from grouping.models import Cohort
    from institution.roles import STUDENT
    from tests.factories import UserFactory

    cohort = Cohort.objects.create(name="Year 1", slug="year-1")
    alice = UserFactory(username="alice_addall")
    bob = UserFactory(username="bob_addall")
    carol = UserFactory(username="carol_addall")
    for u in (alice, bob, carol):
        u.groups.add(AuthGroup.objects.get(name=STUDENT))
    services.assign_student_to_cohort(alice, cohort)
    services.assign_student_to_cohort(bob, cohort)
    return cohort, alice, bob, carol


@pytest.mark.django_db(transaction=True)
def test_add_all_visible_on_freshly_loaded_form_with_no_filter(page, live_server):
    """Row 30a: add-all must be visible the moment the form loads, before any
    filter is applied — unlike [data-roster-count], which stays hidden until a
    filter is active."""
    from playwright.sync_api import expect

    from tests.factories import CourseFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-addall-course")

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    students = _students_fieldset(page)
    add_all = students.locator("[data-roster-all]")
    expect(add_all).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_add_all_invisible_and_inert_with_js_disabled(browser, live_server):
    """Row 30c: with JS off, add-all's bounding_box() must be None (not merely
    `hidden` present — that only holds if no author `display` beats the UA
    [hidden] rule), and the roster must still submit exactly as before."""
    from courses.models import Enrollment
    from grouping.models import Group
    from institution.roles import STUDENT
    from tests.factories import CourseFactory
    from tests.factories import UserFactory

    pa = _make_pa_user("e2e_pa_nojs")
    course = CourseFactory(owner=pa, slug="e2e-addall-nojs-course")
    student = UserFactory(username="e2e_nojs_student")
    student.groups.add(AuthGroup.objects.get(name=STUDENT))

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "e2e_pa_nojs")
    page.goto(f"{live_server.url}/manage/groups/new/")

    students = _students_fieldset(page)
    add_all = students.locator("[data-roster-all]")
    assert add_all.bounding_box() is None

    page.locator("input[name='name']").fill("7NJ")
    page.select_option("select[name='course']", str(course.pk))
    page.check(f"input[name='students'][value='{student.pk}']")
    page.get_by_role("button", name="Save").click()

    group = Group.objects.get(name="7NJ")
    assert group.memberships.filter(student=student).exists()
    assert Enrollment.objects.filter(
        student=student, course=course, source="group"
    ).exists()
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_add_all_under_filter_ticks_only_filtered_students(page, live_server):
    """Row 31: with a cohort filter active, checking add-all must tick only the
    filtered-in (visible) students — carol, filtered out, must stay unticked."""
    from playwright.sync_api import expect

    from tests.factories import CourseFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-addall-31")
    cohort, alice, bob, carol = _make_cohort_students()

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    students = _students_fieldset(page)
    students.locator("[data-roster-cohort]").select_option(cohort.slug)
    add_all = students.locator("[data-roster-all]")
    add_all.check()

    expect(students.locator(f"input[value='{alice.pk}']")).to_be_checked()
    expect(students.locator(f"input[value='{bob.pk}']")).to_be_checked()
    expect(students.locator(f"input[value='{carol.pk}']")).not_to_be_checked()


@pytest.mark.django_db(transaction=True)
def test_add_all_untick_under_filter_clears_only_filtered_students(page, live_server):
    """Row 32: the unchecking direction matters most — a stray sweep must never
    clear students outside the active filter."""
    from playwright.sync_api import expect

    from tests.factories import CourseFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-addall-32")
    cohort, alice, bob, carol = _make_cohort_students()

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    students = _students_fieldset(page)
    # Tick everyone first (unfiltered), including carol.
    students.locator(f"input[value='{alice.pk}']").check()
    students.locator(f"input[value='{bob.pk}']").check()
    students.locator(f"input[value='{carol.pk}']").check()

    students.locator("[data-roster-cohort]").select_option(cohort.slug)
    add_all = students.locator("[data-roster-all]")
    expect(add_all).to_be_checked()  # both visible students are ticked
    add_all.uncheck()

    expect(students.locator(f"input[value='{alice.pk}']")).not_to_be_checked()
    expect(students.locator(f"input[value='{bob.pk}']")).not_to_be_checked()
    expect(students.locator(f"input[value='{carol.pk}']")).to_be_checked()


@pytest.mark.django_db(transaction=True)
def test_add_all_tristate_and_zero_visible_disabled(page, live_server):
    """Row 33: add-all is indeterminate when some (not all) visible students
    are ticked, and unchecked + disabled when nothing is visible at all."""
    from playwright.sync_api import expect

    from tests.factories import CourseFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-addall-33")
    cohort, alice, bob, carol = _make_cohort_students()

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    students = _students_fieldset(page)
    # Check the OUTSIDE-the-cohort student first (unfiltered) so a mutant that
    # derives add-all's state from the whole list, rather than only visible
    # items, diverges from the correct computation once the filter is applied:
    # with alice/bob (visible, unchecked) and carol (hidden, checked), the
    # correct state is "unchecked" (0 of 2 visible), a whole-list mutant sees
    # 1 of 3 checked and renders indeterminate instead.
    students.locator(f"input[value='{carol.pk}']").check()
    students.locator("[data-roster-cohort]").select_option(cohort.slug)

    add_all = students.locator("[data-roster-all]")
    expect(add_all).not_to_be_checked()
    assert add_all.evaluate("el => el.indeterminate") is False

    students.locator(f"input[value='{alice.pk}']").check()
    expect(add_all).not_to_be_checked()
    assert add_all.evaluate("el => el.indeterminate") is True

    # A search term matching nobody in the cohort drives visible count to 0.
    students.locator("[data-roster-search]").fill("zzz-nomatch-zzz")
    expect(add_all).to_be_disabled()
    expect(add_all).not_to_be_checked()
    assert add_all.evaluate("el => el.indeterminate") is False


@pytest.mark.django_db(transaction=True)
def test_add_all_click_from_indeterminate_adds_not_clears(page, live_server):
    """Row 33a: from an indeterminate state, a click must ADD the remaining
    visible students, never clear the ones already ticked. Setup matters —
    `checked` must be genuinely True right before the transition, which only
    happens after a real tick-all-then-untick-one sequence."""
    from playwright.sync_api import expect

    from tests.factories import CourseFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-addall-33a")
    cohort, alice, bob, _carol = _make_cohort_students()

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    students = _students_fieldset(page)
    students.locator("[data-roster-cohort]").select_option(cohort.slug)
    add_all = students.locator("[data-roster-all]")

    add_all.check()  # ticks both alice and bob
    expect(add_all).to_be_checked()

    students.locator(f"input[value='{bob.pk}']").uncheck()
    expect(add_all).not_to_be_checked()
    assert add_all.evaluate("el => el.indeterminate") is True

    add_all.click()

    expect(students.locator(f"input[value='{alice.pk}']")).to_be_checked()
    expect(students.locator(f"input[value='{bob.pk}']")).to_be_checked()


@pytest.mark.django_db(transaction=True)
def test_add_all_sweep_updates_added_counter(page, live_server):
    """Row 34: ticking add-all under a filter must update the live 'Added'
    counter, which only refreshes via an explicit updateSelected() call since a
    scripted .checked fires no change event on the list."""
    from playwright.sync_api import expect

    from tests.factories import CourseFactory

    pa = _make_pa_user()
    CourseFactory(owner=pa, slug="e2e-addall-34")
    cohort, alice, bob, _carol = _make_cohort_students()

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    students = _students_fieldset(page)
    added = students.locator("[data-roster-selected]")
    expect(added).to_have_text("0")

    students.locator("[data-roster-cohort]").select_option(cohort.slug)
    students.locator("[data-roster-all]").check()

    expect(added).to_have_text("2 (saved: 0)")


def _make_two_course_allocation_fixture(pa):
    """A PA with two courses, each carrying one non-archived allocation — the
    minimum fixture that leaves a non-matching optgroup to hide AND a way to
    make a selection stale (spec row 37a)."""
    from tests.factories import AllocationFactory
    from tests.factories import CourseFactory

    course_a = CourseFactory(owner=pa, slug="e2e-alloc-course-a", title="Course A")
    course_b = CourseFactory(owner=pa, slug="e2e-alloc-course-b", title="Course B")
    alloc_a = AllocationFactory(course=course_a, name="Alloc A1")
    alloc_b = AllocationFactory(course=course_b, name="Alloc B1")
    return course_a, course_b, alloc_a, alloc_b


def _visible_optgroup_labels(select_locator):
    return select_locator.evaluate(
        "el => [...el.querySelectorAll('optgroup')]"
        ".filter(g => !g.hidden).map(g => g.label)"
    )


@pytest.mark.django_db(transaction=True)
def test_allocation_select_hides_every_optgroup_on_fresh_create_form(page, live_server):
    """Row 36a: on a freshly loaded create form, before any course is chosen,
    every optgroup must already be hidden — proving the filter runs an init
    pass, not only on `change`."""
    pa = _make_pa_user()
    _make_two_course_allocation_fixture(pa)

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    select = page.locator("[data-allocation-select]")
    assert _visible_optgroup_labels(select) == []


@pytest.mark.django_db(transaction=True)
def test_allocation_select_filters_by_course_and_resets_stale_selection(
    page, live_server
):
    """Row 37a: selecting course A narrows the allocation optgroups to A;
    picking one of A's allocations then switching to course B must hide A's
    optgroup, show B's, and reset the now-stale selection to "" — never
    bounding_box(), since a collapsed size=1 select's options/optgroups are not
    laid out in the page."""
    pa = _make_pa_user()
    course_a, course_b, alloc_a, alloc_b = _make_two_course_allocation_fixture(pa)

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")

    select = page.locator("[data-allocation-select]")
    page.select_option("select[name='course']", str(course_a.pk))
    assert _visible_optgroup_labels(select) == [course_a.title]

    page.select_option("[data-allocation-select]", str(alloc_a.pk))
    assert select.input_value() == str(alloc_a.pk)

    page.select_option("select[name='course']", str(course_b.pk))
    assert _visible_optgroup_labels(select) == [course_b.title]
    assert select.input_value() == ""
