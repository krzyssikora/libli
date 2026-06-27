"""Playwright e2e for Phase 3c-ii: the teacher analytics-matrix journey.

The owner opens the matrix (Progress), sees a student's 100% cell, toggles to
Results, then edits a colour-band threshold and saves — all via real gestures.
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_pa

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_teacher_views_matrix_toggles_mode_and_edits_a_band(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2eanalytics")  # PA: passes can_review + can_manage
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    les = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, obligatory=True
    )
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)

    _login(page, live_server, "e2eanalytics")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")
    expect(page.locator("table.analytics__matrix")).to_contain_text("100%")
    expect(page.get_by_text("Ada L.")).to_be_visible()

    # Toggle to Results (real click on the toggle link)
    page.get_by_role("link", name="Results").click()
    expect(page).to_have_url(re.compile(r"mode=results"))

    # Edit a colour-band threshold and save (real form submit)
    page.get_by_role("link", name="Configure colours").click()
    page.fill("input[name='min_1']", "10")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("table.analytics__matrix")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_teacher_drills_into_columns_and_a_student(page, live_server, client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import UnitProgressFactory
    from tests.factories import UserFactory

    owner = make_pa(client, "e2edrill")
    course = CourseFactory(owner=owner)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    sec = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch, title="Sec1"
    )
    les = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=sec,
        obligatory=True,
        title="U1",
    )
    student = UserFactory(display_name="Ada L.")
    Enrollment.objects.create(student=student, course=course)
    UnitProgressFactory(student=student, unit=les, completed=True)

    _login(page, live_server, "e2edrill")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/analytics/")

    # Expand Ch1 (real click on its expandable leaf-column header link)
    page.get_by_role("link", name=re.compile(r"Ch1")).click()
    expect(page.locator(".analytics__group")).to_contain_text("Ch1")
    # Now Sec1 is a leaf column; expand it (recursive)
    page.get_by_role("link", name=re.compile(r"Sec1")).click()
    expect(page.locator("table.analytics__matrix")).to_contain_text("U1")
    expect(page.locator(".analytics__group")).to_have_count(2)  # Ch1 + Sec1 span cells

    # Collapse via the ✕ on the spanning header cells: the deeper "Sec1" group
    # first (its cell uniquely contains "Sec1"), then the lone remaining "Ch1".
    page.locator(".analytics__group", has_text="Sec1").locator(
        ".analytics__collapse"
    ).click()
    expect(page.locator(".analytics__group")).to_have_count(1)
    page.locator(".analytics__group .analytics__collapse").click()
    expect(page.locator(".analytics__group")).to_have_count(0)

    # Drill into the student
    page.get_by_role("link", name="Ada L.").click()
    expect(page.locator(".manage__title")).to_contain_text("Ada L.")
    expect(page.locator(".badge--done")).to_be_visible()  # U1 completed ✓

    # Breadcrumb back to the matrix (scope the locator to the breakdown header so a
    # sibling "Analytics" nav link, if any, can't make this ambiguous).
    page.locator(".breakdown .manage__head").get_by_role("link").click()
    expect(page.locator("table.analytics__matrix")).to_be_visible()
