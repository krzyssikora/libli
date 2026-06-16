"""Playwright e2e for WS2 inline-add interaction (Task 4).

Tests that clicking a '+Kind' chip reveals an inline title field (JS-on path),
typing a title and pressing Enter submits via fetch and creates the node.
Marked e2e (excluded from the default run; run with -m e2e).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    u = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return u


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_inline_add_creates_node(page, live_server):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    from courses.models import ContentNode

    pa = _make_pa_user("pa9w1")
    course = CourseFactory(slug="ws2add", owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    _login(page, live_server, "pa9w1")
    page.goto(f"{live_server.url}/manage/courses/ws2add/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    # In Ch1's scope, click "+ Unit", type a title, Enter.
    scope = page.locator(f'[data-add-scope="{ch.pk}"]')
    scope.locator('button[data-add-kind="unit"]').click()
    field = scope.locator("input[data-add-title]")
    field.fill("Intro")
    field.press("Enter")
    page.wait_for_selector("text=Intro")
    assert ContentNode.objects.filter(
        course=course, parent=ch, title="Intro", kind="unit"
    ).exists()
