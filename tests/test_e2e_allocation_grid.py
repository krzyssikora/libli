"""Playwright e2e for the allocation assignment grid's CSS/JS (task 8).

Marked `e2e` (excluded by default; run with -m e2e). Server-side rendering
(row states, summary, save mechanics) is already covered by
tests/test_grouping_allocation_grid.py; this file drives the real browser to
prove the CLIENT layer — live summary, live row-state recompute, filters, and
the sticky/hidden CSS contract — without breaking the no-JS baseline the
server-rendered grid must still satisfy.
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from grouping import services
from grouping.models import CohortMembership
from grouping.models import GroupMembership
from tests.factories import TEST_PASSWORD
from tests.factories import AllocationFactory
from tests.factories import CohortFactory
from tests.factories import CohortMembershipFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username="alloc_pa", language=None):
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
    if language:
        # Session-based, not cookie-based: core.signals.seed_language_on_login
        # writes User.language into the session on login, and
        # core.middleware.SessionLocaleMiddleware prefers the session over the
        # cookie/Accept-Language. Must be set BEFORE the login form is driven.
        user.language = language
        user.save(update_fields=["language"])
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _grid_url(live_server, allocation):
    path = reverse("grouping:allocation_assign", args=[allocation.pk])
    return f"{live_server.url}{path}"


def _summary_texts(page):
    return {
        "total": page.locator("[data-grid-total]").text_content(),
        "assigned": page.locator("[data-grid-assigned]").text_content(),
        "unassigned": page.locator("[data-grid-unassigned]").text_content(),
        "conflict": page.locator("[data-grid-conflict]").text_content(),
    }


# --- Row 35: filter never touches the summary; a hidden row has no box ------


@pytest.mark.django_db(transaction=True)
def test_cohort_filter_leaves_summary_unchanged_and_hides_a_row(page, live_server):
    pa = _make_pa_user("row35_pa")
    course = CourseFactory(owner=pa)
    allocation = AllocationFactory(course=course)
    GroupFactory(course=course, allocation=allocation, name="Col")  # >=1 column
    cohort_a = CohortFactory(name="Cohort A")
    cohort_b = CohortFactory(name="Cohort B")
    allocation.cohorts.add(cohort_a, cohort_b)
    student_a = UserFactory(username="row35_a", display_name="Ala A")
    CohortMembershipFactory(user=student_a, cohort=cohort_a)
    student_b = UserFactory(username="row35_b", display_name="Bea B")
    CohortMembershipFactory(user=student_b, cohort=cohort_b)

    _login(page, live_server, "row35_pa")
    page.goto(_grid_url(live_server, allocation))

    before = _summary_texts(page)
    assert before == {
        "total": "2",
        "assigned": "0",
        "unassigned": "2",
        "conflict": "0",
    }

    row_b = page.locator(f'[data-grid-row][data-cohort="{cohort_b.slug}"]')
    row_a = page.locator(f'[data-grid-row][data-cohort="{cohort_a.slug}"]')

    page.select_option("[data-grid-cohort]", cohort_a.slug)

    # The whole-allocation summary must be byte-identical to before filtering.
    assert _summary_texts(page) == before
    # A filtered-out row has NO box at all (not merely the `hidden` attribute).
    assert row_b.bounding_box() is None
    assert row_a.bounding_box() is not None


# --- Row 35a: filtered-out rows still post; disabled would drop them --------


@pytest.mark.django_db(transaction=True)
def test_save_under_filter_leaves_hidden_row_untouched_and_still_posts_it(
    page, live_server
):
    pa = _make_pa_user("row35a_pa")
    course = CourseFactory(owner=pa)
    allocation = AllocationFactory(course=course)
    col_x = GroupFactory(course=course, allocation=allocation, name="X")
    col_y = GroupFactory(course=course, allocation=allocation, name="Y")
    cohort_a = CohortFactory(name="Cohort A")
    cohort_b = CohortFactory(name="Cohort B")
    allocation.cohorts.add(cohort_a, cohort_b)
    visible_student = UserFactory(username="row35a_vis", display_name="Vis Ible")
    CohortMembershipFactory(user=visible_student, cohort=cohort_a)
    hidden_student = UserFactory(username="row35a_hid", display_name="Hid Den")
    CohortMembershipFactory(user=hidden_student, cohort=cohort_b)
    services.add_students_to_group(col_x, [hidden_student])  # pre-existing placement

    _login(page, live_server, "row35a_pa")
    page.goto(_grid_url(live_server, allocation))

    posts = []

    def _record(resp):
        if resp.request.method == "POST":
            posts.append(resp.request.post_data or "")

    page.on("response", _record)

    # Filter down to cohort A -> the hidden student's row must remain in the
    # DOM (posting) even though it is not visible.
    page.select_option("[data-grid-cohort]", cohort_a.slug)
    page.locator(f'[data-grid-row][data-cohort="{cohort_b.slug}"]').wait_for(
        state="hidden"
    )

    # Assign the still-visible student, leaving the hidden one untouched.
    page.locator(
        f'input[name="student-{visible_student.pk}"][value="{col_y.pk}"]'
    ).check()
    page.get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")

    assert posts, "expected the form POST to be observed"
    body = posts[0]
    assert f"student-{hidden_student.pk}-was" in body
    assert f"student-{hidden_student.pk}=" in body
    # Byte-identical: the hidden student's membership is untouched.
    assert GroupMembership.objects.filter(group=col_x, student=hidden_student).exists()
    assert (
        not GroupMembership.objects.filter(student=hidden_student)
        .exclude(group=col_x)
        .exists()
    )
    # The visible student's assignment DID land.
    assert GroupMembership.objects.filter(group=col_y, student=visible_student).exists()


# --- Row 35c: the sentinel isolates outsiders, never duplicates "All" -------


@pytest.mark.django_db(transaction=True)
def test_outside_cohorts_sentinel_isolates_only_outsider_rows(page, live_server):
    pa = _make_pa_user("row35c_pa")
    course = CourseFactory(owner=pa)
    allocation = AllocationFactory(course=course)
    col = GroupFactory(course=course, allocation=allocation, name="Col")
    cohort = CohortFactory(name="Cohort A")
    allocation.cohorts.add(cohort)
    inside_student = UserFactory(username="row35c_in", display_name="In Side")
    CohortMembershipFactory(user=inside_student, cohort=cohort)
    outsider = UserFactory(username="row35c_out", display_name="Out Sider")
    CohortMembership.objects.filter(user=outsider).delete()
    services.add_students_to_group(col, [outsider])

    _login(page, live_server, "row35c_pa")
    page.goto(_grid_url(live_server, allocation))

    inside_row = page.locator('[data-grid-row][data-cohort="' + cohort.slug + '"]')
    outside_row = page.locator('[data-grid-row][data-cohort=""]')
    assert inside_row.bounding_box() is not None
    assert outside_row.bounding_box() is not None

    page.select_option("[data-grid-cohort]", "__none__")

    assert inside_row.bounding_box() is None
    assert outside_row.bounding_box() is not None


# --- Row 35d: search matches data-name only, never the "also in" note ------


@pytest.mark.django_db(transaction=True)
def test_name_search_matches_data_name_not_the_also_in_note(page, live_server):
    pa = _make_pa_user("row35d_pa")
    course = CourseFactory(owner=pa)
    allocation = AllocationFactory(course=course)
    col = GroupFactory(course=course, allocation=allocation, name="Col")
    other_group = GroupFactory(course=course, name="2B")  # NOT a column
    cohort = CohortFactory(name="Cohort A")
    allocation.cohorts.add(cohort)

    # Structured first_name/last_name (an SSO user's shape) so sort_name
    # ("Target Zenobia", last-first) and list_display_name ("Zenobia Target",
    # first-last) genuinely differ in WORD ORDER -- display_name="" so
    # list_display_name's "(nickname)" suffix logic never fires and muddy the
    # comparison.
    target = UserFactory(
        username="row35d_target",
        first_name="Zenobia",
        last_name="Target",
        display_name="",
    )
    CohortMembershipFactory(user=target, cohort=cohort)

    noted = UserFactory(username="row35d_noted", display_name="Wanda Noted")
    CohortMembershipFactory(user=noted, cohort=cohort)
    services.add_students_to_group(other_group, [noted])  # -> "also in: 2B"
    services.add_students_to_group(col, [noted])  # give them a column row too

    _login(page, live_server, "row35d_pa")
    page.goto(_grid_url(live_server, allocation))

    target_row = page.locator(
        f'[data-grid-row][data-name="{target.list_display_name.lower()}"]'
    )
    noted_row = page.locator(
        f'[data-grid-row][data-name="{noted.list_display_name.lower()}"]'
    )
    assert "also in: 2B" in noted_row.text_content()
    assert target.sort_name.lower() != target.list_display_name.lower()

    # "2b" is present in noted_row's rendered TEXT (the note) but not in its
    # data-name -- searching it must hide noted_row and never match on text.
    page.locator("[data-grid-search]").fill("2b")
    assert noted_row.bounding_box() is None
    assert target_row.bounding_box() is None  # "zenobia" doesn't contain "2b" either

    page.locator("[data-grid-search]").fill("zenobia")
    assert target_row.bounding_box() is not None
    assert noted_row.bounding_box() is None

    # The user reads "Zenobia Target" on screen (list_display_name) -- typing
    # that exact, displayed word order must find the row.
    page.locator("[data-grid-search]").fill("zenobia target")
    assert target_row.bounding_box() is not None

    # sort_name's word order ("Target Zenobia") is what the user NEVER sees.
    # Matching on it would mean data-name regressed to the sort key.
    page.locator("[data-grid-search]").fill("target zenobia")
    assert target_row.bounding_box() is None


# --- Row 36: picking a column on a conflict row resolves it live -----------


@pytest.mark.django_db(transaction=True)
def test_picking_a_column_on_a_conflict_row_clears_it_before_saving(page, live_server):
    pa = _make_pa_user("row36_pa")
    course = CourseFactory(owner=pa)
    allocation = AllocationFactory(course=course)
    col_x = GroupFactory(course=course, allocation=allocation, name="X")
    col_y = GroupFactory(course=course, allocation=allocation, name="Y")
    cohort = CohortFactory(name="Cohort A")
    allocation.cohorts.add(cohort)
    conflicted = UserFactory(username="row36_conf", display_name="Con Flicted")
    CohortMembershipFactory(user=conflicted, cohort=cohort)
    services.add_students_to_group(col_x, [conflicted])
    services.add_students_to_group(col_y, [conflicted])

    _login(page, live_server, "row36_pa")
    page.goto(_grid_url(live_server, allocation))

    row = page.locator(f'[data-grid-row][data-name="{conflicted.sort_name.lower()}"]')
    assert "is-conflict" in row.get_attribute("class")
    assert page.locator("[data-grid-conflict]").text_content() == "1"
    danger_badge = row.locator(".badge--danger")
    assert danger_badge.bounding_box() is not None

    page.locator(f'input[name="student-{conflicted.pk}"][value="{col_x.pk}"]').check()

    assert "is-conflict" not in row.get_attribute("class")
    assert "is-assigned" in row.get_attribute("class")
    assert page.locator("[data-grid-conflict]").text_content() == "0"
    assert page.locator("[data-grid-assigned]").text_content() == "1"
    assert danger_badge.bounding_box() is None

    # Nothing saved yet — the pending change is purely client-side.
    assert GroupMembership.objects.filter(student=conflicted, group=col_y).exists()


# --- Row 35b: Polish stays Polish through a live summary update ------------


@pytest.mark.django_db(transaction=True)
def test_polish_live_summary_survives_a_radio_change(new_context, live_server):
    pa = _make_pa_user("row35b_pa", language="pl")
    course = CourseFactory(owner=pa)
    allocation = AllocationFactory(course=course)
    col = GroupFactory(course=course, allocation=allocation, name="Col")
    cohort = CohortFactory(name="Cohort A")
    allocation.cohorts.add(cohort)
    student = UserFactory(username="row35b_student", display_name="Ola Studentka")
    CohortMembershipFactory(user=student, cohort=cohort)

    ctx = new_context(locale="pl-PL")
    page = ctx.new_page()
    _login(page, live_server, "row35b_pa")
    page.goto(_grid_url(live_server, allocation))

    summary = page.locator("[data-grid-summary]")
    # "Students" is already translated to "Uczniowie" in locale/pl (shared with
    # group_form.html's identical {% trans %} call), so it discriminates a
    # correct build from one that composes the summary in English JS literals.
    assert "Uczniowie" in summary.text_content()
    assert "Students" not in summary.text_content()

    page.locator(f'input[name="student-{student.pk}"][value="{col.pk}"]').check()

    assert page.locator("[data-grid-assigned]").text_content() == "1"
    assert "Uczniowie" in summary.text_content()
    assert "Students" not in summary.text_content()


# --- Row 37: a real save moves two students, and the old group loses one ---


@pytest.mark.django_db(transaction=True)
def test_assign_two_students_and_save_moves_them_and_the_old_group_loses_one(
    page, live_server
):
    pa = _make_pa_user("row37_pa")
    course = CourseFactory(owner=pa)
    allocation = AllocationFactory(course=course)
    col_x = GroupFactory(course=course, allocation=allocation, name="X")
    col_y = GroupFactory(course=course, allocation=allocation, name="Y")
    cohort = CohortFactory(name="Cohort A")
    allocation.cohorts.add(cohort)

    mover = UserFactory(username="row37_mover", display_name="Mo Ver")
    CohortMembershipFactory(user=mover, cohort=cohort)
    services.add_students_to_group(col_x, [mover])  # starts in X -> must move to Y

    fresh = UserFactory(username="row37_fresh", display_name="Fr Esh")
    CohortMembershipFactory(user=fresh, cohort=cohort)  # starts unassigned

    _login(page, live_server, "row37_pa")
    page.goto(_grid_url(live_server, allocation))

    page.locator(f'input[name="student-{mover.pk}"][value="{col_y.pk}"]').check()
    page.locator(f'input[name="student-{fresh.pk}"][value="{col_x.pk}"]').check()
    page.get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")

    assert GroupMembership.objects.filter(group=col_y, student=mover).exists()
    assert not GroupMembership.objects.filter(group=col_x, student=mover).exists()
    assert GroupMembership.objects.filter(group=col_x, student=fresh).exists()
