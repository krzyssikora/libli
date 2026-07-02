"""Playwright e2e for the notification bell dropdown (slice 3).

Real browser gestures only (project lesson: e2e that bypasses the real gesture
ships broken UX green). Marked `e2e` (excluded by default; run with -m e2e).
"""

import os
import re

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e

# mark_read's path is /notifications/<pk>/read/ (the URL *name* "mark_read" is
# not in the path). \d+ before /read excludes mark_all_read's /notifications/read-all/.
_MARK_READ_PATH = re.compile(r"/notifications/\d+/read/?$")


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

    # Clicking the row fires the mark-read POST AND navigates to the target.
    # Synchronize on the POST's response so the badge check can't race it: a bare
    # `to_have_count(0)` after page.goto only re-queries the already-rendered DOM
    # (it never re-navigates), so if mark_read hadn't committed before that GET
    # rendered, the badge would be baked in as "1" and the auto-retry could never
    # recover. Waiting for the mark_read response guarantees it committed first.
    with page.expect_response(
        lambda r: r.request.method == "POST" and _MARK_READ_PATH.search(r.url)
    ):
        panel.locator(".notif-menu__row", has_text="Astronomy").click()
    expect(page).to_have_url(f"{live_server.url}{outline_path}")

    # mark_read has now committed server-side → reload the list; the badge is gone.
    page.goto(f"{live_server.url}/notifications/")
    expect(page.locator(".nav-badge")).to_have_count(0)
