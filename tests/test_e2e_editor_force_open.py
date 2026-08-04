"""Playwright e2e for the force-open skip — the ONE behaviour of PR1 that a
template test cannot cover.

The server renders the destination <details> open, and then editor.js's
applyStoredTabs immediately re-applies the author's stored preference over the
top. For any tab the author has ever collapsed, a just-duplicated element is
therefore born invisible. The defect lives entirely in the browser: a template
test renders server HTML, never runs applyStoredTabs, and passes whether or not
the skip exists.
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
    """A unit holding a Tabs whose SECOND tab has one Text child.

    Seeded through the ORM on purpose: the gesture under test is the duplicate
    click and the swap that follows, not the authoring of a tab (which
    test_e2e_depth3 already drives through the real add-menu).
    """
    from courses.models import Element
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
    t2 = tabs.data["tabs"][1]["id"]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>FORCEOPEN-MARKER</p>"),
        parent=tabs_join,
        tab_id=t2,
    )
    return course, unit, tabs_join, t2, child


@pytest.mark.django_db(transaction=True)
def test_a_stored_collapse_does_not_hide_a_just_duplicated_element(page, live_server):
    user = _make_pa_user("pa")
    course, unit, tabs_join, t2, child = _seed(user, "forceopen")
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )

    tab2 = page.locator(f"details.tabs-rows[data-tab-id='{t2}']")
    # Tab 2 is not the first tab, so it renders closed. Open it -- the row inside
    # a closed <details> is in the DOM but not clickable (content-visibility),
    # so the duplicate button is unreachable until it is open.
    tab2.locator("summary").click()
    expect(tab2).to_have_attribute("open", "")

    # Now plant the stored preference the skip must override. Opening the tab
    # just wrote "1" via saveTab, so setting it directly is what reproduces "the
    # author collapsed this tab earlier"; clicking summary twice more would only
    # write "1" again by the time we click duplicate. The key shape is
    # editor.js's tabStoreKey: "libli:tabopen:" + <tabs row pk> + ":" + <tab id>.
    page.evaluate(
        "key => localStorage.setItem(key, '0')",
        f"libli:tabopen:{tabs_join.pk}:{t2}",
    )

    row = page.locator(f".el-row[data-element='{child.pk}']")
    with page.expect_response(lambda r: "element/duplicate/" in r.url):
        row.locator("form[data-op='element-duplicate'] button[type=submit]").click()

    tab2_after = page.locator(f"details.tabs-rows[data-tab-id='{t2}']")
    expect(tab2_after).to_have_attribute("data-force-open", "")
    # THIS is the assertion the defect breaks: applyStoredTabs has just re-applied
    # the stored "0" over the server's `open`.
    expect(tab2_after).to_have_attribute("open", "")
    # And this one proves the copy landed in the right slot. Note it does NOT
    # detect the defect: to_have_count matches DOM nodes regardless of visibility,
    # and a closed <details> keeps its children in the DOM (it hides them via
    # content-visibility), so the count is 2 either way.
    expect(tab2_after.locator(".el-row")).to_have_count(2)
