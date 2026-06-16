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


@pytest.mark.django_db(transaction=True)
def test_move_picker_places_between_via_slot(page, live_server):
    from tests.factories import ContentNodeFactory, CourseFactory
    from courses.models import ContentNode
    pa = _make_pa_user("pa9w2")
    course = CourseFactory(slug="ws2mv", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    items = [ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title=f"L{i}") for i in range(1, 5)]
    _login(page, live_server, "pa9w2")
    page.goto(f"{live_server.url}/manage/courses/ws2mv/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    # Open the Move picker for L1; choose Ch1 as destination; pick the slot between L3 and L4.
    page.locator(f'a[data-move="{items[0].pk}"]').click()
    page.locator(f'[data-move-tree] [data-dest="{ch.pk}"]').wait_for(state="visible", timeout=5000)
    page.locator(f'[data-move-tree] [data-dest="{ch.pk}"]').click()
    # slot between L3 and L4: after excluding the moving L1, others=[L2,L3,L4], insert-before L4 => position 2
    page.locator('[data-move-slot="2"]').click()
    page.locator('.move-picker__submit').click()
    # final order under Ch1 must be [L2, L3, L1, L4]
    page.wait_for_function(
        "([sel, want]) => {const ol=document.querySelector(sel); if(!ol) return false;"
        "const got=Array.from(ol.children).filter(li=>li.classList.contains('tree__row'))"
        ".map(li=>li.getAttribute('data-node')); return got.join(',')===want;}",
        arg=[f'[data-scope="{ch.pk}"]', ",".join(str(items[i].pk) for i in (1, 2, 0, 3))],
        timeout=5000,
    )


@pytest.mark.django_db(transaction=True)
def test_inline_add_second_click_commits_exactly_one(page, live_server):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    from courses.models import ContentNode

    pa = _make_pa_user("pa9w1b")
    course = CourseFactory(slug="ws2add2", owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    _login(page, live_server, "pa9w1b")
    page.goto(f"{live_server.url}/manage/courses/ws2add2/build/")
    page.wait_for_selector('[data-scope="top"]', state="attached")
    scope = page.locator(f'[data-add-scope="{ch.pk}"]')
    scope.locator('button[data-add-kind="unit"]').click()  # first click: open inline row
    scope.locator("input[data-add-title]").fill("Once")
    scope.locator('button[data-add-kind="unit"]').click()  # second click: COMMIT
    page.wait_for_selector("text=Once")
    # Give any erroneous second POST time to land, then assert exactly one node exists.
    page.wait_for_timeout(500)
    assert (
        ContentNode.objects.filter(
            course=course, parent=ch, title="Once", kind="unit"
        ).count()
        == 1
    )
