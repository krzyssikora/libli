"""Measured browser tests for the per-table width preset.

`full` (the default) stretches the table to the reading column, exactly as every
table did before the preset existed. `fit` shrinks it to its content and centres
it.

Only a browser can fail these. The class name is emitted either way, so a
source-scanning test stays green with the CSS rule deleted -- the precedent is
tests/test_e2e_table_cell_images.py, and the reason #314's blast radius went
unnoticed until it reached prod.
"""

import os

import pytest

from courses.models import TableElement
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PA_USERNAME = "pa-tblwidth"

EPS = 1.0

# The reported pair from prod unit 567: identical first column, second columns of
# very different length. Under `full` these disagree (measured 115.8 vs 257.1);
# under `fit` both hug their content, so the first columns match.
LONG = "odsetki każdorazowo przelewane na konto pana Michała"
SHORT = "procent prosty"


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


def _unit(username, slug):
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )


def _add(unit, rows, *, width=None, normalize=True):
    """`normalize=False` stores the RAW dict, which is how all 265 existing rows
    look: `save()` runs only `_sanitized_data`, so no `width` key is added."""
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[{"html": c} for c in row] for row in rows],
    }
    if width is not None:
        data["width"] = width
    el = TableElement.objects.create(
        data=TableElement.normalize_data(data) if normalize else data
    )
    add_element(unit, el)
    return el


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _boxes(page):
    page.wait_for_selector(".el--table table")
    return page.evaluate(
        """() => [...document.querySelectorAll('.el--table')].map(el => {
             const s = el.querySelector('.el--table__scroll').getBoundingClientRect();
             const t = el.querySelector('table').getBoundingClientRect();
             const td = el.querySelector('tr:first-child td').getBoundingClientRect();
             return { table_w: t.width, scroll_w: s.width, col1: td.width,
                      left_gap: t.left - s.left, right_gap: s.right - t.right };
           })"""
    )


def test_full_fills_the_reading_column(page, live_server):
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "tw-full")
    _add(unit, [["(2)", "wzor", "1200"]], width="full")

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    box = _boxes(page)[0]

    assert abs(box["table_w"] - box["scroll_w"]) < EPS, (
        f"full table is {box['table_w']:.1f}px in a {box['scroll_w']:.1f}px column"
    )


def test_fit_hugs_its_content_and_is_centred(page, live_server):
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "tw-fit")
    _add(unit, [["(2)", "wzor", "1200"]], width="fit")

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    box = _boxes(page)[0]

    assert box["table_w"] < box["scroll_w"] - EPS, (
        f"fit table still fills the column ({box['table_w']:.1f}px)"
    )
    assert abs(box["left_gap"] - box["right_gap"]) < EPS, (
        f"fit table is not centred: {box['left_gap']:.1f}px left, "
        f"{box['right_gap']:.1f}px right"
    )


def test_a_table_stored_before_the_preset_renders_as_full(page, live_server):
    """The no-migration claim, measured.

    The stored dict has NO `width` key -- the shape all 265 live rows have. If
    the default were wrong, or the template emitted a bare `el--table--width-`,
    this table would not fill its column.
    """
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "tw-legacy")
    el = _add(unit, [["(2)", "wzor", "1200"]], normalize=False)
    el.refresh_from_db()
    assert "width" not in el.data, "fixture is not the legacy shape"

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    box = _boxes(page)[0]

    assert abs(box["table_w"] - box["scroll_w"]) < EPS, (
        f"legacy table is {box['table_w']:.1f}px in a {box['scroll_w']:.1f}px column"
    )


def test_fit_makes_the_reported_pair_agree(page, live_server):
    """The original complaint, and why the preset is worth having.

    Two tables with the same first column and very different second columns
    disagree under `full` (115.8px vs 257.1px measured). Set both to `fit` and
    each sizes from its own content, so the shared column matches.
    """
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "tw-pair")
    for neighbour in (LONG, SHORT):
        _add(
            unit,
            [["Przykład 1", neighbour], ["Przykład 2", neighbour]],
            width="fit",
        )

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    boxes = _boxes(page)

    assert len(boxes) == 2
    assert abs(boxes[0]["col1"] - boxes[1]["col1"]) < EPS, (
        f"first columns still disagree: {boxes[0]['col1']:.1f}px vs "
        f"{boxes[1]['col1']:.1f}px"
    )


def test_a_fit_table_wider_than_the_column_still_starts_at_the_left_edge(
    page, live_server
):
    """`margin-inline: auto` must not strand a too-wide table.

    Auto margins resolve to 0 when the box overflows, unlike flex centring, whose
    leading edge cannot be scrolled back into view. Asserted with a fixture that
    genuinely overflows, so it cannot pass vacuously.

    The cells hold UNBREAKABLE tokens, not long prose. A table's used width is
    max(min-content, min(max-content, available)), so prose -- however long --
    just wraps and caps at the column; only content whose MIN-content exceeds the
    column pushes the table past it. Long prose here measured exactly 648.0px in
    a 648.0px column, i.e. the assertion below could never have failed.
    """
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "tw-wide")
    wide = ["W" * 40] * 6
    _add(unit, [wide, wide], width="fit")

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    box = _boxes(page)[0]

    assert box["table_w"] > box["scroll_w"] + EPS, (
        "fixture does not overflow, so the claim is untested "
        f"({box['table_w']:.1f}px in {box['scroll_w']:.1f}px)"
    )
    assert box["left_gap"] >= -EPS, (
        f"wide fit table starts {box['left_gap']:.1f}px left of its scroller"
    )


def test_the_editor_round_trips_the_preset(page, live_server):
    """The control must reach the stored data -- the grid is serialised to a
    hidden field by table_editor.js, so a select the JS never reads would look
    correct in the form and save nothing."""
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "tw-editor")
    el = _add(unit, [["(2)", "wzor", "1200"]], width="full")
    element = unit.elements.order_by("-order").first()

    _login(page, live_server, PA_USERNAME)
    page.goto(
        f"{live_server.url}/manage/courses/{unit.course.slug}"
        f"/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f'.el-act-edit[data-element-id="{element.pk}"]').click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")

    assert page.locator("[data-edit-slot] [data-width]").input_value() == "full"
    page.locator("[data-edit-slot] [data-width]").select_option("fit")
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]", state="detached")

    el.refresh_from_db()
    assert el.data["width"] == "fit", el.data
