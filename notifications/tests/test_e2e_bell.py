"""Playwright e2e for the notification bell dropdown (slice 3).

Real browser gestures only (project lesson: e2e that bypasses the real gesture
ships broken UX green). Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse
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
def test_bell_opens_and_row_click_marks_read_and_navigates(page, live_server):
    from grouping import services as grouping_svc
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import GroupFactory
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug="e2e-bell", title="Astronomy")
    student = make_verified_user(
        username="e2e_bell_student", email="e2e_bell_student@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    group = GroupFactory(course=course)
    grouping_svc.add_students_to_group(group, [student])
    outline_path = reverse("courses:course_outline", kwargs={"slug": course.slug})

    _login(page, live_server, "e2e_bell_student")
    page.goto(f"{live_server.url}/notifications/")

    # Badge shows the unread count on the bell.
    expect(page.locator(".nav-badge")).to_have_text("1")

    trigger = page.locator(".bell__trigger")
    panel = page.locator(".notif-menu[data-menu-panel]")
    expect(panel).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")

    # A plain click opens the panel (does NOT navigate to the list).
    trigger.click()
    expect(panel).to_be_visible()
    expect(trigger).to_have_attribute("aria-expanded", "true")

    # Clicking the row fires the mark-read POST (fire-and-forget keepalive, no
    # preventDefault) AND navigates via the <a href>. Assert the navigation first
    # — that part is deterministic.
    panel.locator(".notif-menu__row", has_text="Astronomy").click()
    expect(page).to_have_url(f"{live_server.url}{outline_path}")

    # The keepalive POST races the navigation and commits a beat later, so the
    # badge may still show on the first reload. Poll a bounded number of reloads
    # until it clears (condition-based waiting).
    #
    # Do NOT try to synchronize by observing the mark_read *response* mid-click
    # (e.g. page.expect_response): that click also navigates the page, and under
    # headless-CI timing the navigation commits before the keepalive response is
    # surfaced, so the waiter times out (this is exactly what failed in CI). A
    # single un-polled reload is also wrong — it can bake in a stale "1" with no
    # recovery. Polling reloads handles both. A clean final assert still fails
    # loudly if the row was never actually marked read.
    for _ in range(20):
        page.goto(f"{live_server.url}/notifications/")
        if page.locator(".nav-badge").count() == 0:
            break
        page.wait_for_timeout(250)
    expect(page.locator(".nav-badge")).to_have_count(0)
