"""Playwright e2e for notifications slice 1: event → badge → page → mark read.

Real browser gestures only (project lesson: e2e that bypasses the real gesture
ships broken UX green). Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_enrolled_notification_visible_and_markable(page, live_server):
    from grouping import services as grouping_svc
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import GroupFactory
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug="e2e-notif", title="Astronomy")
    student = make_verified_user(
        username="e2e_notif_student", email="e2e_notif_student@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    # Fire an `enrolled` event via the real service. Self-enrollment no longer
    # notifies (a student shouldn't be told "you were enrolled" for their own
    # action); group-driven enrollment still does, so use that path here.
    group = GroupFactory(course=course)
    grouping_svc.add_students_to_group(group, [student])

    _login(page, live_server, "e2e_notif_student")
    # Go straight to the notifications page — base.html renders the nav (and badge)
    # on every authenticated page, avoiding any assumption about what "/" shows.
    page.goto(f"{live_server.url}/notifications/")
    # Badge shows an unread count in the nav, and the row is visible.
    expect(page.locator(".nav-badge")).to_have_text("1")
    expect(page.locator(".notif-row")).to_contain_text("Astronomy")

    # Mark it read → redirect back to the list → badge gone.
    page.get_by_role("button", name="Mark read").first.click()
    expect(page.locator(".nav-badge")).to_have_count(0)
