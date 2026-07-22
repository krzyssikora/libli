"""Playwright e2e for inline renaming of builder tree node titles.

Marked e2e (excluded from the default run; run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

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


def _seed_course(username="owner"):
    """A course shaped for the token-refresh cases: a chapter that CONTAINS a nested
    section with its own add row, so a naive descendant query for parent_token finds
    the GRANDCHILD's and the test goes RED.

    Every non-unit node passes unit_type=None -- the factory defaults it to "lesson",
    which ContentNode.clean() rejects for non-units, so a chapter built without it
    422s on rename and the chapter-centric scenarios below fail looking like
    applyRename bugs.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = _make_pa_user(username)
    course = CourseFactory(slug="c1", owner=owner)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Chapter 1"
    )
    section = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=chapter, title="Section 1"
    )
    unit1 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=section, title="Unit 1"
    )
    unit2 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=section, title="Unit 2"
    )
    return course, {
        "owner": owner,
        "chapter": chapter,
        "section": section,
        "unit1": unit1,
        "unit2": unit2,
    }


def _open_builder(page, live_server, course, username):
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/")
    page.wait_for_selector(".tree__title")


@pytest.mark.django_db(transaction=True)
def test_enter_commits_a_unit_rename(page, live_server):
    course, nodes = _seed_course()
    _open_builder(page, live_server, course, "owner")
    title = page.locator('.tree__title[value="Unit 1"]')
    title.click()
    title.press("Control+a")
    page.keyboard.type("Renamed unit")
    with page.expect_response(
        lambda r: "rename" in r.url and r.request.method == "POST"
    ):
        title.press("Enter")
    expect(page.locator('.tree__title[value="Renamed unit"]')).to_have_count(1)
    nodes["unit1"].refresh_from_db()
    assert nodes["unit1"].title == "Renamed unit"
