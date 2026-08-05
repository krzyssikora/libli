"""Playwright e2e for the clipboard: select a POPULATED container and move it
into a spoiler, through the real buttons.

A populated container landing in a new slot is a shape an ADD can never produce,
so no existing test covers it -- which is exactly how the depth-3 slice shipped
two client-side defects that thirteen per-task reviews missed.
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


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _seed(owner, slug):
    """A unit holding a POPULATED Tabs (child in tab 2) and an empty Spoiler.

    Seeded through the ORM on purpose: the gesture under test is select-then-paste,
    not the authoring of a container (test_e2e_depth3 already drives the real
    add-menu for that).
    """
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>CLIPMARKER-child</p>"),
        parent=tabs_join,
        tab_id=t2,
    )
    spoiler = Element.objects.create(
        unit=unit,
        content_object=SpoilerElement.objects.create(
            label="Rozwiązanie", body="<p>s</p>"
        ),
    )
    return course, unit, tabs_join, t1, t2, child, spoiler


@pytest.mark.django_db(transaction=True)
def test_a_populated_container_moves_into_a_spoiler_and_reaches_the_student(
    page, live_server
):
    user = _make_pa_user("pa")
    course, unit, tabs_join, t1, _t2, child, spoiler = _seed(user, "clipboard")
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )

    # Plant a stored collapse on tab 1 BEFORE marking. Without the force-open
    # stamp the mark's re-render would re-collapse it client-side, and this is the
    # only way to prove the stamp is honoured -- a template test never runs
    # applyStoredTabs. The key shape is editor.js's tabStoreKey.
    tab1 = page.locator(f"details.tabs-rows[data-tab-id='{t1}']")
    tab1.locator("summary").click()  # toggle -> saveTab writes an entry
    page.evaluate(
        "key => localStorage.setItem(key, '0')",
        f"libli:tabopen:{tabs_join.pk}:{t1}",
    )

    # 1. Select the POPULATED container, through the real button.
    #
    # The locator must be scoped to the row's OWN control bar. A tabs row nests its
    # child rows inside its own <li class="el-row" data-element=...> (_element_row
    # .html:80-95), and every row carries its own element-clip form -- so a plain
    # descendant locator matches the container's button AND its child's, and
    # Playwright's strict mode raises before anything is clicked.
    tabs_row = page.locator(f".el-row[data-element='{tabs_join.pk}']")
    tabs_controls = tabs_row.locator(
        "> .el-row__head .el-actions form[data-op='element-clip'] button"
    )
    with page.expect_response(lambda r: "element/clip/" in r.url):
        tabs_controls.click()

    expect(page.locator("#clip-banner")).to_be_visible()
    expect(page.locator(f".el-row[data-element='{tabs_join.pk}']")).to_have_class(
        __import__("re").compile(r"el-row--marked")
    )
    # The stored collapse must NOT win while a mark is pending.
    expect(page.locator(f"details.tabs-rows[data-tab-id='{t1}']")).to_have_attribute(
        "open", ""
    )

    # 2. Paste it into the spoiler's slot, through the real button. Scoped to the
    #    spoiler's own slot container for the same strict-mode reason: once the
    #    tabs element lands inside it, that subtree carries paste forms of its own.
    spoiler_row = page.locator(f".el-row[data-element='{spoiler.pk}']")
    with page.expect_response(lambda r: "element/paste/" in r.url):
        spoiler_row.locator(
            "> .el-row__spoiler > form[data-op='element-paste'] button[value='move']"
        ).click()

    # 3. The container and its child are now inside the spoiler.
    moved = page.locator(
        f".el-row[data-element='{spoiler.pk}'] .el-row__spoiler "
        f".el-row[data-element='{tabs_join.pk}']"
    )
    expect(moved).to_have_count(1)
    expect(page.locator(f".el-row[data-element='{child.pk}']")).to_have_count(1)
    # The mark is cleared by a move, so the banner is gone.
    expect(page.locator("#clip-banner")).to_have_count(0)

    # 4. The moved subtree reaches the student page's MARKUP. Deliberately a
    #    count, not a visibility check: after the move the child sits in tab 2 of
    #    a tabs element nested inside a closed spoiler, so it is present but not
    #    visible -- which is correct, and asserting to_be_visible() here would
    #    fail for the right reasons. What this pins is that the move did not lose
    #    the subtree somewhere between the editor and the student render.
    page.goto(_lesson_url(live_server, unit))
    expect(page.get_by_text("CLIPMARKER-child")).to_have_count(1)
