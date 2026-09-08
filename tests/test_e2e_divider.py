"""Playwright e2e for the Divider element — the two things server tests cannot prove.

The server side (allow-tuple, NESTABLE_TYPE_KEYS, resolve_scope, the serializers) is
covered by courses/tests/test_divider_element.py. All of it can be green while the
author still cannot *get there*, because the two authoring facts live in the client:

  1. Divider is FIELD-LESS, so editor.js must post it straight to element_save. On the
     normal add -> open-form path it would hit element_add, which does not list
     "divider", and the click would 400 with nothing on screen.
  2. Its card must work from a NESTED menu. The Structure group is inside
     `{% if not nested %}`; a card placed there renders only at top level, and the one
     case the element exists for — a rule between a callout's children — stays
     unreachable while every server test passes.

So this file drives the real gesture and then reads the result as a student:
authoring the reader never sees is not a feature.

Login/seed/menu-scoping helpers mirror tests/test_e2e_depth3.py rather than being
invented — same PA-user helper, same scoped [data-add-menu] locators, same
count-the-saved-rows checkpoint instead of a sleep.
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

SLOT_ID = "only"  # CalloutElement.SLOT_ID — the single implicit child slot


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


def _seed_unit(owner, slug):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _open_card(menu, add_type):
    """The cards live inside `<div class="typemenu" hidden>`, so the toggle click is
    not decoration: without it Playwright waits for visibility and times out."""
    menu.locator("[data-add-toggle]").click()
    menu.locator(f"[data-add-type='{add_type}']").click()


def _top_menu(page):
    return page.locator("[data-add-menu]:not(.addwrap--nested)")


def _nested_menu(page, parent_pk, tab_id):
    return page.locator(
        f"[data-add-menu][data-parent='{parent_pk}'][data-tab='{tab_id}']"
    )


def _save_open_form(page):
    page.locator(
        "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    ).first.click()


def _wait_saved_rows(page, expected):
    """Poll until the pane holds `expected` SAVED top-level rows.

    `[data-element]` is the point: a row holding an open CREATE form is drawn as soon
    as the form opens and carries no data-element until the save lands, so a bare
    `.el-row` count would go green on the stale pane — the read this helper exists to
    prevent."""
    page.wait_for_function(
        """(n) => document.querySelectorAll(
               '[data-scope="editor"] .el-row[data-element]').length === n""",
        arg=expected,
    )


@pytest.mark.django_db(transaction=True)
def test_author_adds_a_divider_inside_a_callout_and_the_student_sees_it(
    page, live_server
):
    author = _make_pa_user("divauthor")
    course, unit = _seed_unit(author, "divc")
    _login(page, live_server, "divauthor")
    page.goto(_editor_url(live_server, course, unit))

    # 1. a callout at top level (a normal add -> form -> save round trip)
    _open_card(_top_menu(page), "callout")
    _save_open_form(page)
    _wait_saved_rows(page, 1)

    callout_pk = page.locator(
        '[data-scope="editor"] .el-row[data-element]'
    ).first.get_attribute("data-element")

    # 2. the divider, from the CALLOUT's own menu. No form opens: a field-less type
    #    is created directly against element_save, so the row is saved on arrival.
    _open_card(_nested_menu(page, callout_pk, SLOT_ID), "divider")
    expect(page.locator(".element-row--divider[data-element]")).to_have_count(1)

    # 3. and the reader actually gets a rule, inside the callout
    page.goto(_lesson_url(live_server, unit))
    expect(page.locator(".callout hr.el-divider")).to_have_count(1)


@pytest.mark.django_db(transaction=True)
def test_nested_divider_row_still_draws_its_rules(page, live_server):
    """A NESTED divider row must render as a rule, not a bare label.

    `.element-list--nested .ica--grip { display: none }` removes the grip from
    `.el-row__head`'s `grid-template-columns: auto 1fr`, so in a nested row the body
    auto-places into the `auto` column and sizes to its CONTENT. A text row does not
    care. This row's `.divider-row__rule` spans are `flex: 1 1 auto` with no content,
    so with zero free space they collapse to 0px and the row reads as a stray
    "DIVIDER" label with the buttons packed left.

    MEASURED on the broken build: top-level rule 135.9px, nested rule 0px in the same
    pane -- which is why this asserts the nested width directly rather than trusting
    that the class is applied."""
    from courses.models import CalloutElement
    from courses.models import DividerElement
    from courses.models import Element
    from tests.factories import add_element

    author = _make_pa_user("divnested")
    course, unit = _seed_unit(author, "divnest")
    callout = CalloutElement.objects.create(kind="example", heading="C")
    join = add_element(unit, callout)
    Element.objects.create(
        unit=unit,
        content_object=DividerElement.objects.create(),
        parent=join,
        tab_id=SLOT_ID,
    )

    _login(page, live_server, "divnested")
    page.goto(_editor_url(live_server, course, unit))
    rule = page.locator(
        ".element-list--nested .element-row--divider .divider-row__rule"
    ).first
    rule.wait_for(state="attached")
    assert rule.bounding_box()["width"] > 20
