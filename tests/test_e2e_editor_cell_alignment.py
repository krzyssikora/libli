"""The table editors must SHOW the alignment their buttons set.

Both defects saved correctly (the lesson rendered the alignment) while the
editor grid did not move, so the button read as dead:

* valign -- editor.css declared `vertical-align: top` inside
  `.table-editor__grid td` (0,1,1), which outranked the cell's own
  `.va-middle`/`.va-bottom` (0,1,0). Shared by the table and fill-table editors.
* halign on a fill-table ANSWER cell -- the answer is an <input>, and a form
  control computes `text-align: start` from the UA sheet. The student input got
  `text-align: inherit` long ago; its editor twin `.filltable-editor__answer`
  never did.

Probes measure the RENDERED position (the text's slack inside its cell, the
computed text-align of the control that draws the answer), not the class the
button toggled: the class was always toggled correctly.

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _author_unit(page, live_server, username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    course = CourseFactory(slug=f"{username}-c", owner=user)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    return unit


def _open_editor(page, live_server, unit, join, editor_selector):
    page.goto(
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f"[data-element='{join.pk}'] .el-act-edit").click()
    page.wait_for_selector(f"[data-edit-slot] {editor_selector}")


# Slack (px) above and below the cell's text, inside the cell's content box.
_TEXT_SLACK = """td => {
  const r = document.createRange();
  r.selectNodeContents(td);
  const t = r.getBoundingClientRect();
  const c = td.getBoundingClientRect();
  return [t.top - c.top, c.bottom - t.bottom];
}"""

_CELLS = "[data-edit-slot] [data-table-grid] td[contenteditable]"
_TOOLBAR = "[data-edit-slot] [data-table-toolbar]"
_TALL = "a<br>b<br>c<br>d<br>e<br>f"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("valign", ["middle", "bottom"])
def test_table_editor_cell_moves_on_valign(page, live_server, valign):
    from courses.models import TableElement

    unit = _author_unit(page, live_server, f"tbl_valign_{valign}")
    table = TableElement.objects.create(
        data={
            "cells": [
                [
                    {"html": _TALL, "halign": "left", "valign": "top"},
                    {"html": "x", "halign": "left", "valign": "top"},
                ]
            ],
            "border": "grid",
        }
    )
    join = add_element(unit, table)
    _open_editor(page, live_server, unit, join, "[data-table-editor]")

    short = page.locator(_CELLS).nth(1)
    short.click()
    page.locator(f"{_TOOLBAR} [data-valign='{valign}']").click()

    above, below = short.evaluate(_TEXT_SLACK)
    assert above > 40, f"text did not leave the top of its cell: {above}/{below}"
    if valign == "middle":
        assert abs(above - below) <= 4, f"not centred: {above}/{below}"
    else:
        assert below < above, f"not at the bottom: {above}/{below}"


@pytest.mark.django_db(transaction=True)
def test_filltable_editor_static_cell_moves_on_valign(page, live_server):
    from courses.models import FillTableElement

    unit = _author_unit(page, live_server, "ftbl_valign")
    el = FillTableElement.objects.create(
        data={
            "cells": [
                [
                    {"kind": "static", "html": _TALL},
                    {"kind": "static", "html": "x"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    join = add_element(unit, el)
    _open_editor(page, live_server, unit, join, "[data-filltable-editor]")

    short = page.locator(_CELLS).nth(1)
    short.click()
    page.locator(f"{_TOOLBAR} [data-valign='middle']").click()

    above, below = short.evaluate(_TEXT_SLACK)
    assert above > 40 and abs(above - below) <= 4, f"not centred: {above}/{below}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("halign", ["center", "right"])
def test_filltable_editor_answer_text_follows_halign(page, live_server, halign):
    from courses.models import FillTableElement

    unit = _author_unit(page, live_server, f"ftbl_halign_{halign}")
    el = FillTableElement.objects.create(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "q"},
                    {"kind": "answer", "answer": "42", "halign": "left"},
                ]
            ]
        }
    )
    join = add_element(unit, el)
    _open_editor(page, live_server, unit, join, "[data-filltable-editor]")

    answer = page.locator("[data-edit-slot] .filltable-editor__answer")
    answer.click()
    page.locator(f"{_TOOLBAR} [data-halign='{halign}']").click()

    assert answer.evaluate("el => getComputedStyle(el).textAlign") == halign
