"""Playwright e2e for the builder-tree layout refresh: L/Q unit badges, the 2:1
column ratio, and single-line title truncation. Self-contained (own PA/login
helpers, per the repo e2e convention). Marked e2e — run foreground only."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

# Long enough to overflow the tree column at the fixed narrow viewport set below,
# so the truncation assertion is viewport-deterministic, not environment-dependent.
# Kept under the ContentNode.title CharField(max_length=200) limit.
LONG_TITLE = "A deliberately very long unit title that must truncate " * 3


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_builder_tree_layout(page, live_server, tmp_path):
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.models import TextElement

    _make_pa_user("pa")
    course = Course.objects.create(slug="layout-demo", title="Layout Demo")
    lesson = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title=LONG_TITLE
    )
    # Give the lesson a long-summary element so the unit panel's .element-list has a
    # row whose .element-list__summary must ellipsis-truncate at the narrowed width.
    Element.objects.create(
        unit=lesson,
        content_object=TextElement.objects.create(
            body="<p>"
            + ("A very long element summary that must truncate. " * 6)
            + "</p>"
        ),
    )
    ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="Quick check"
    )

    # Fixed narrow viewport so the long title deterministically overflows the tree
    # column regardless of the CI default.
    page.set_viewport_size({"width": 1000, "height": 800})
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}/manage/courses/layout-demo/build/")

    # Badges: exactly the L and Q letters render in the tree.
    badges = page.locator(".tree__badge--unit")
    texts = sorted(badges.all_inner_texts())
    assert texts == ["L", "Q"], f"expected L and Q unit badges, got {texts}"

    # Column ratio ~2:1 (tree vs panel). Viewport-INDEPENDENT: follows only from the
    # 2fr/1fr grid track split, not the absolute width.
    tree_box = page.locator(".builder__tree").bounding_box()
    panel_box = page.locator(".builder__panel").bounding_box()
    ratio = tree_box["width"] / panel_box["width"]
    assert 1.7 < ratio < 2.4, f"tree:panel width ratio {ratio:.2f} not ~2:1"

    # Long title truncates on one line: content overflows the button box.
    title = page.locator(".tree__title", has_text="deliberately very long").first
    metrics = title.evaluate("el => ({sw: el.scrollWidth, cw: el.clientWidth})")
    assert metrics["sw"] > metrics["cw"], (
        "long title is not overflowing (not truncated)"
    )

    # Capture light + dark. This app themes via a `data-theme` attribute on the root.
    page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    page.screenshot(path=str(tmp_path / "builder_tree_light.png"), full_page=True)
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    page.screenshot(path=str(tmp_path / "builder_tree_dark.png"), full_page=True)

    # (d) Unit panel at the narrowed 1/3 width: select the lesson unit so its detail
    # panel renders (with the seeded element list), then screenshot light + dark.
    page.locator(".tree__title", has_text="deliberately very long").first.click()
    page.wait_for_selector(".builder__panel .element-list")
    page.evaluate("document.documentElement.setAttribute('data-theme', 'light')")
    page.screenshot(path=str(tmp_path / "unit_panel_light.png"), full_page=True)
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    page.screenshot(path=str(tmp_path / "unit_panel_dark.png"), full_page=True)
    print(f"SCREENSHOTS: {tmp_path}")
