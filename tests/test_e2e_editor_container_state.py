"""Playwright e2e for the two pieces of editor state that a fragment swap used to
throw away. Both defects live entirely in the browser, so neither is reachable from
a template test: the response HTML is only half the story, and what breaks the
author's flow is what editor.js does to it afterwards.

1. A COLUMN's open state. editor.js persisted the open/closed state of container
   <details>, but the selector named only `details.tabs-rows` -- columns had no
   memory at all. Expand column 2, do anything, and it is shut again.

2. The PREVIEW's active tab. applyFragments replaces the whole preview pane, which
   destroys the node holding tabs.js's active-tab closure state, so every save came
   back on tab 1. An author editing tab 3 had to re-click tab 3 after every edit.
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


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _text(body):
    from courses.models import TextElement

    return TextElement.objects.create(body=body)


def _seed_columns(owner, slug):
    """A unit holding: a top-level Text element, and a two-column element whose
    SECOND column holds one Text child.

    The top-level element exists to give the test a swap that has NOTHING to do with
    the columns -- that is the only way to tell the client-side memory apart from the
    server's force-open, which would hold column 2 open on its own.
    """
    from courses.models import Element
    from courses.models import TwoColumnElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    loose = Element.objects.create(unit=unit, content_object=_text("<p>TOP-LEVEL</p>"))
    cols = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    cols_join = Element.objects.create(unit=unit, content_object=cols)
    c1, c2 = [c["id"] for c in cols.data["columns"]]
    child = Element.objects.create(
        unit=unit,
        content_object=_text("<p>IN-COLUMN-TWO</p>"),
        parent=cols_join,
        tab_id=c2,
    )
    return course, unit, loose, c1, c2, child


@pytest.mark.django_db(transaction=True)
def test_every_column_starts_collapsed(page, live_server):
    """No column is privileged. The old `forloop.first` default is what made column
    1 permanently open and every other column permanently shut."""
    user = _make_pa_user("colstate1")
    course, unit, _loose, c1, c2, _child = _seed_columns(user, "colstate1")
    _login(page, live_server, "colstate1")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    for cid in (c1, c2):
        expect(
            page.locator(f"details.columns-rows[data-column-id='{cid}']")
        ).not_to_have_attribute("open", "")


@pytest.mark.django_db(transaction=True)
def test_editing_an_element_in_column_two_leaves_its_form_visible(page, live_server):
    """THE REPORTED BUG, driven exactly as the author hits it: expand column 2,
    click Edit on the row inside it -- and on master the column shuts under them,
    hiding the form that was just opened.

    `to_be_visible` is the load-bearing assertion, NOT the `open` attribute: a
    closed <details> keeps its subtree in the DOM and hides it via
    content-visibility, so anything that only counted nodes would pass on master.

    A stored "0" is planted between the expand and the Edit click, so this test
    isolates the SERVER's open-set. Without it the stored preference alone would
    reopen the column -- expanding it to reach the Edit button necessarily records
    "1" -- and the test would stay green with the view fix reverted. Planting also
    covers the second half of the mechanism: a force-open must outrank whatever the
    author stored earlier, or the row is hidden by their own stale collapse.
    """
    user = _make_pa_user("colstate2")
    course, unit, _loose, _c1, c2, child = _seed_columns(user, "colstate2")
    _login(page, live_server, "colstate2")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    col2 = page.locator(f"details.columns-rows[data-column-id='{c2}']")
    col2.locator("summary").click()
    expect(col2).to_have_attribute("open", "")

    # Key shape is editor.js's slotStoreKey:
    # "libli:tabopen:" + <container row pk> + ":" + <slot id>.
    cols_row = page.locator(".el-row--twocolumn").first
    cols_join_pk = cols_row.get_attribute("data-element")
    page.evaluate(
        "key => localStorage.setItem(key, '0')",
        f"libli:tabopen:{cols_join_pk}:{c2}",
    )

    with page.expect_response(lambda r: f"element/{child.pk}/form/" in r.url):
        page.locator(f".el-act-edit[data-element-id='{child.pk}']").click()

    col2_after = page.locator(f"details.columns-rows[data-column-id='{c2}']")
    expect(col2_after).to_have_attribute("data-force-open", "")
    expect(col2_after).to_have_attribute("open", "")
    expect(
        col2_after.locator("[data-edit-slot] form[data-op='element-save']")
    ).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_an_expanded_column_survives_a_swap_it_had_no_part_in(page, live_server):
    """The client-side half, isolated. Editing the TOP-LEVEL element names no
    column in the open-set, so the server renders column 2 shut and only the stored
    preference can reopen it. Columns had no stored preference before this fix.
    """
    user = _make_pa_user("colstate3")
    course, unit, loose, _c1, c2, _child = _seed_columns(user, "colstate3")
    _login(page, live_server, "colstate3")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="editor"]')

    col2 = page.locator(f"details.columns-rows[data-column-id='{c2}']")
    col2.locator("summary").click()  # toggle -> saveSlot records "1"
    expect(col2).to_have_attribute("open", "")

    with page.expect_response(lambda r: f"element/{loose.pk}/form/" in r.url):
        page.locator(f".el-act-edit[data-element-id='{loose.pk}']").click()

    col2_after = page.locator(f"details.columns-rows[data-column-id='{c2}']")
    expect(col2_after).to_have_attribute("open", "")
    # And it is genuinely reopened by the STORED preference, not by a force-open the
    # server had no reason to send. Without this the test would still pass if a
    # future change started force-opening every slot on every render.
    expect(col2_after).not_to_have_attribute("data-force-open", "")


def _seed_tabs(owner, slug):
    """A unit holding a top-level Text element and a Tabs element with two tabs,
    each holding one distinctly-worded Text child."""
    from courses.models import Element
    from courses.models import TabsElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    loose = Element.objects.create(unit=unit, content_object=_text("<p>TOP-LEVEL</p>"))
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    for tid, body in ((t1, "<p>PANEL-ONE</p>"), (t2, "<p>PANEL-TWO</p>")):
        Element.objects.create(
            unit=unit, content_object=_text(body), parent=tabs_join, tab_id=tid
        )
    return course, unit, loose, tabs_join, t1, t2


@pytest.mark.django_db(transaction=True)
def test_the_preview_keeps_the_authors_tab_across_a_save(page, live_server):
    """THE SECOND REPORTED BUG. The author selects tab 2 in the preview, makes an
    unrelated edit, and on master the rebuilt preview is back on tab 1 -- so
    verifying any tab but the first meant re-clicking it after every single save.
    """
    user = _make_pa_user("tabstate")
    course, unit, loose, tabs_join, _t1, t2 = _seed_tabs(user, "tabstate")
    _login(page, live_server, "tabstate")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="preview"] .tabs__strip')

    preview_tabs = page.locator(
        f"[data-scope='preview'] [data-tabs-eid='{tabs_join.pk}'] .tabs__tab"
    )
    preview_tabs.nth(1).click()
    panel2 = page.locator(
        f"[data-scope='preview'] [data-tab-panel][data-tab-id='{t2}']"
    )
    expect(panel2).to_be_visible()

    # An edit with no connection to the tabs element at all.
    with page.expect_response(lambda r: f"element/{loose.pk}/form/" in r.url):
        page.locator(f".el-act-edit[data-element-id='{loose.pk}']").click()

    # The pane is a NEW node, so re-locate rather than reusing the handles above.
    panel2_after = page.locator(
        f"[data-scope='preview'] [data-tab-panel][data-tab-id='{t2}']"
    )
    expect(panel2_after).to_be_visible()
    expect(
        page.locator(
            f"[data-scope='preview'] [data-tabs-eid='{tabs_join.pk}'] .tabs__tab"
        ).nth(1)
    ).to_have_attribute("aria-selected", "true")
