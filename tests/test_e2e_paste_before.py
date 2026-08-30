"""Playwright e2e for "move before this element": the gesture that lets an element
added at the BOTTOM of a long unit reach the top in one round trip.

Covered here and nowhere else: the button only exists while a mark is pending, so
the whole path -- mark, re-render, click, re-render -- has to survive two fragment
swaps before anything moves. A template test renders one page and a service test
never touches the DOM; neither can see a swap drop the control.
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


def _seed(owner, slug):
    """Four top-level text elements, A B C then the subject last."""
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    joins = [
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(
                body=f"<p>ORDERMARKER-{name}</p>"
            ),
        )
        for name in ("a", "b", "c", "subject")
    ]
    return course, unit, joins


def _editor_order(page):
    return page.eval_on_selector_all(
        '[data-scope="editor"] .element-list > .el-row[data-element]',
        "rows => rows.map(r => r.getAttribute('data-element'))",
    )


@pytest.mark.django_db(transaction=True)
def test_an_element_at_the_bottom_moves_above_the_first_in_one_click(page, live_server):
    user = _make_pa_user("pa")
    course, unit, (a, b, c, subject) = _seed(user, "pastebefore")
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )

    assert _editor_order(page) == [str(j.pk) for j in (a, b, c, subject)]
    # No mark yet, so no row offers the control.
    expect(page.locator("form[data-op='element-paste-before']")).to_have_count(0)

    # 1. Mark the LAST element, through the real button. Scoped to the row's own
    #    control bar for the strict-mode reason test_e2e_clipboard documents.
    subject_row = page.locator(f".el-row[data-element='{subject.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        subject_row.locator(
            "> .el-row__head .el-actions form[data-op='element-clip'] button"
        ).click()
    expect(page.locator("#clip-banner")).to_be_visible()

    # 2. The marked row and the row directly below it offer nothing; the rest do.
    #    `subject` is last, so only its own row is suppressed here.
    expect(
        page.locator(
            f".el-row[data-element='{subject.pk}'] form[data-op='element-paste-before']"
        )
    ).to_have_count(0)
    expect(page.locator("form[data-op='element-paste-before']")).to_have_count(3)

    # 3. Move it above the FIRST element -- the trip that costs three arrow clicks.
    with page.expect_response(lambda r: "element/paste/" in r.url):
        page.locator(
            f".el-row[data-element='{a.pk}'] "
            "> .el-row__head .el-actions form[data-op='element-paste-before'] button"
        ).click()

    assert _editor_order(page) == [str(j.pk) for j in (subject, a, b, c)]
    # A move clears the mark, so every button goes with it.
    expect(page.locator("#clip-banner")).to_have_count(0)
    expect(page.locator("form[data-op='element-paste-before']")).to_have_count(0)

    # 4. The new order is what a STUDENT sees, not just what the editor pane drew.
    from django.urls import reverse

    page.goto(
        live_server.url
        + reverse(
            "courses:lesson_unit",
            kwargs={"slug": course.slug, "node_pk": unit.pk},
        )
    )
    text = page.locator("main").inner_text()
    assert text.index("ORDERMARKER-subject") < text.index("ORDERMARKER-a"), text
