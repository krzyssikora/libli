"""Playwright e2e for the "Fill-in table" self-check element (FillTableElement, plan
Task 9). Drives the REAL student gesture end-to-end — types into the actual answer
input and clicks the actual Check button — never a page.evaluate shortcut into the
grading endpoint or the JS internals (this repo's standing lesson: an e2e that
bypasses the real gesture ships broken UX green).

Covers the behaviour matrix from the task brief:
  1. A seeded table whose single answer cell sits at a NON-(0,0) position (row 1,
     col 1) — proving the 0-based data-r/data-c wiring is not accidentally right
     only for the trivial (0,0) case.
  2. Filling the correct value and clicking Check -> the input gets
     filltable__input--correct, the summary shows the success text/class, and the
     Check button (.filltable__confirm) becomes hidden (lock).
  3. Filling a wrong value and clicking Check -> the input gets
     filltable__input--incorrect, the summary shows the retry text/class, and the
     Check button stays visible (NOT locked).

The table is seeded via the ORM so the grid/answer are deterministic — but the
FILL/CHECK interaction is real browser gestures. Mirrors the login/seed/unit
harness of tests/test_e2e_switchgrid.py. Marked e2e (excluded from the default
run; run focused + foreground with -m e2e or by file)."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

_CORRECT = re.compile(r"\bfilltable__input--correct\b")
_INCORRECT = re.compile(r"\bfilltable__input--incorrect\b")
_SUCCESS = re.compile(r"\bfilltable__summary--success\b")
_RETRY = re.compile(r"\bfilltable__summary--retry\b")


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Login / seed helpers (mirrored from tests/test_e2e_switchgrid.py)
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_student(username):
    from tests.factories import make_verified_user

    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _new_unit(username, unit_type="lesson"):
    """An enrolled student + a fresh lesson unit. Returns (student, unit)."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type)
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _unit_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _seed_filltable(unit):
    """A 2x2 grid whose sole answer cell is at (row 1, col 1) — a deliberately
    NON-(0,0) position, exercising the 0-based data-r/data-c wiring end to end."""
    from courses.models import FillTableElement

    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "czas"},
                    {"kind": "static", "html": "woda"},
                ],
                [
                    {"kind": "static", "html": "0"},
                    {"kind": "answer", "answer": "4"},
                ],
            ]
        }
    )
    el.save()
    add_element(unit, el)
    return el


# Shared locators (scoped to the first fill-table on the page).
def _table(page):
    return page.locator(".filltable").first


def _answer_input(page):
    return _table(page).locator('.filltable__input[data-r="1"][data-c="1"]')


def _confirm(page):
    return _table(page).locator(".filltable__confirm")


def _summary(page):
    return _table(page).locator(".filltable__summary")


# ---------------------------------------------------------------------------
# 1. Correct value -> Check -> success + correct class + lock (Check hidden)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_filltable_correct_value_locks_and_summarizes(page, live_server):
    """Fill the (1,1) answer cell with the correct value, Check, and assert:
    filltable__input--correct on that input, the success summary, and the Check
    button hidden (lock)."""
    _student, unit = _new_unit("ftbl_ok")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_ok")
    page.goto(_unit_url(live_server, unit))

    inp = _answer_input(page)
    expect(inp).to_be_visible()
    expect(_confirm(page)).to_be_visible()
    expect(_summary(page)).to_be_hidden()

    inp.fill("4")
    _confirm(page).click()

    expect(inp).to_have_class(_CORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_SUCCESS)

    # Solved -> Check hidden (lock) and the input disabled.
    expect(_confirm(page)).to_be_hidden()
    expect(inp).to_be_disabled()


@pytest.mark.django_db(transaction=True)
def test_filltable_enter_key_submits_like_check(page, live_server):
    """Pressing Enter in a fill cell submits the same as clicking Check: the
    correct value locks + summarizes without ever touching the button."""
    _student, unit = _new_unit("ftbl_enter")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_enter")
    page.goto(_unit_url(live_server, unit))

    inp = _answer_input(page)
    expect(inp).to_be_visible()
    inp.fill("4")
    inp.press("Enter")

    expect(inp).to_have_class(_CORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_SUCCESS)
    expect(_confirm(page)).to_be_hidden()


# ---------------------------------------------------------------------------
# 2. Wrong value -> Check -> retry summary + incorrect class; NOT locked
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_filltable_wrong_value_retry_not_locked(page, live_server):
    """Fill the (1,1) answer cell with a wrong value, Check, and assert:
    filltable__input--incorrect on that input, the retry summary, and the Check
    button stays visible (NOT locked)."""
    _student, unit = _new_unit("ftbl_bad")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_bad")
    page.goto(_unit_url(live_server, unit))

    inp = _answer_input(page)
    inp.fill("9")
    _confirm(page).click()

    expect(inp).to_have_class(_INCORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_RETRY)

    # NOT locked: Check still visible, input still enabled/editable.
    expect(_confirm(page)).to_be_visible()
    expect(inp).to_be_enabled()


def _seed_state(student, unit, element_state):
    """Seed UnitProgress.element_state DIRECTLY in the DB -- fixture SETUP (a
    precondition of the reload gesture under test), not a bypassed gesture."""
    from courses.models import UnitProgress

    progress, _ = UnitProgress.objects.get_or_create(student=student, unit=unit)
    progress.element_state = element_state
    progress.save(update_fields=["element_state"])


def _seed_tab1(unit, tab1_children):
    """One TabsElement on `unit` (tabs 'First'/'Second'); `tab1_children` is a
    list of concrete element objects placed, in order, nested under tab 1."""
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "First"},
                {"id": "t000002", "label": "Second"},
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=obj)
    for child in tab1_children:
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id="t000001"
        )
    return join


@pytest.mark.django_db(transaction=True)
def test_filltable_correct_value_persists_across_reload(page, live_server):
    """Real gesture: fill the correct value, Check, await the state POST,
    reload -> still locked/correct, Check gone, the value stays shown."""
    _student, unit = _new_unit("ftbl_persist")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_persist")
    page.goto(_unit_url(live_server, unit))

    inp = _answer_input(page)
    inp.fill("4")
    with page.expect_response(
        lambda r: "/state/" in r.url and r.request.method == "POST"
    ) as resp_info:
        _confirm(page).click()
    assert resp_info.value.ok

    page.reload()
    inp = _answer_input(page)
    expect(_confirm(page)).to_have_count(0)
    expect(inp).to_have_js_property("readOnly", True)
    expect(inp).to_have_value("4")
    expect(inp).to_have_class(_CORRECT)
    expect(_summary(page)).to_have_class(_SUCCESS)


@pytest.mark.django_db(transaction=True)
def test_filltable_wrong_value_persists_nothing(page, live_server):
    """A wrong Check makes NO state POST; reload -> fresh, editable, unlocked."""
    _student, unit = _new_unit("ftbl_wrong_nosave")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_wrong_nosave")
    page.goto(_unit_url(live_server, unit))

    saw_state_post = {"hit": False}
    page.on(
        "request",
        lambda r: saw_state_post.__setitem__(
            "hit", saw_state_post["hit"] or "/state/" in r.url
        ),
    )
    inp = _answer_input(page)
    inp.fill("9")
    _confirm(page).click()
    expect(_summary(page)).to_have_class(_RETRY)
    assert saw_state_post["hit"] is False

    page.reload()
    expect(_confirm(page)).to_be_visible()
    expect(_answer_input(page)).to_be_enabled()


@pytest.mark.django_db(transaction=True)
def test_filltable_stored_done_typesets_math_on_load(page, live_server):
    """.el--filltable is excluded from math.js's global renderInlineText list;
    on restore, filltable.js's OWN boot short-circuit must typeset the static
    cell's math before returning."""
    from courses.models import FillTableElement

    student, unit = _new_unit("ftbl_math_restore")
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": r"\(x<5\)"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    el.save()
    row = add_element(unit, el)
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    _login(page, live_server, "ftbl_math_restore")
    page.goto(_unit_url(live_server, unit))

    math_node = page.locator(".filltable .katex")
    expect(math_node).to_have_count(1)
    assert "\\(" not in page.locator(".filltable").inner_text()


# ---------------------------------------------------------------------------
# Editor half (Task 10): author image cells via the media picker, per-cell alt
# ---------------------------------------------------------------------------


def _make_pa_user(username):
    """Mirrors tests/test_e2e_gallery.py's helper: a Platform Admin, who can
    reach /manage/courses/.../build/unit/.../edit/."""
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.factories import make_verified_user

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _editor_context(page, live_server, username, slug):
    """Course + lesson unit + two course-scoped image assets, owned by a fresh
    Platform Admin. Does NOT navigate yet -- callers seed elements via the ORM
    first, then call _goto_editor, so the seeded element is present on first
    paint (no reload needed)."""
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import make_image_asset

    _make_pa_user(username)
    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    asset_a = make_image_asset(course, filename="a.png")
    asset_b = make_image_asset(course, filename="b.png")
    return unit, asset_a, asset_b


def _goto_editor(page, live_server, username, unit):
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/manage/courses/{unit.course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')


def _seed_filltable_for_images(unit):
    """A 1x3 grid: two static cells (to be converted to image cells by the
    test) plus one pre-existing, non-blank answer cell, so the submit guard
    (>=1 answer cell, none blank) is satisfied without the test having to
    drive that gesture too."""
    from courses.models import FillTableElement

    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "one"},
                    {"kind": "static", "html": "two"},
                    {"kind": "answer", "answer": "4"},
                ]
            ]
        }
    )
    el.save()
    return add_element(unit, el)


def _open_edit(page, element_pk):
    page.locator(f'.el-act-edit[data-element-id="{element_pk}"]').click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]")


@pytest.mark.django_db(transaction=True)
def test_author_two_image_cells_with_distinct_alts(page, live_server):
    """Convert two static cells to image cells via the REAL toggle -> pick ->
    alt gesture, with DISTINCT alts, save, reopen, and assert BOTH alts
    survive round-trip. A single shared-toolbar-alt bug would fail this (both
    cells would end up with the same, last-typed alt); a single-image test
    would pass vacuously."""
    unit, asset_a, asset_b = _editor_context(page, live_server, "ftbl_img", "ftbl-img")
    element = _seed_filltable_for_images(unit)
    _goto_editor(page, live_server, "ftbl_img", unit)
    _open_edit(page, element.pk)

    editor = page.locator("[data-filltable-editor]")
    grid = editor.locator("[data-table-grid]")
    cells = grid.locator("td:not([data-control])")

    def make_image_cell(cell, alt, asset_pk):
        cell.click()
        editor.locator("[data-image-toggle]").click()
        page.wait_for_selector(".picker-overlay", timeout=5000)
        page.locator(f".picker-overlay .asset-pick[data-asset-id='{asset_pk}']").click()
        editor.locator("[data-image-alt]").fill(alt)

    make_image_cell(cells.nth(0), "first graph", asset_a.pk)
    make_image_cell(cells.nth(1), "second graph", asset_b.pk)

    # Both converted cells now render as images with distinct alts, in-page,
    # before the save round-trip -- proves the JS side, not just the server.
    imgs = grid.locator("td[data-image]")
    assert imgs.count() == 2
    assert imgs.nth(0).get_attribute("data-alt") == "first graph"
    assert imgs.nth(1).get_attribute("data-alt") == "second graph"

    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]", state="detached")

    _open_edit(page, element.pk)
    imgs = page.locator("[data-table-grid] td[data-image]")
    assert imgs.count() == 2
    assert imgs.nth(0).get_attribute("data-alt") == "first graph"
    assert imgs.nth(1).get_attribute("data-alt") == "second graph"


@pytest.mark.django_db(transaction=True)
def test_image_cell_toggles_back_to_static_then_answer(page, live_server):
    """toggleAnswerCell's image-cell guard: one click on 'Answer cell' turns a
    freshly-converted image cell back to static (not straight to a corrupt
    answer cell carrying stale data-media/data-alt); a second click then goes
    static -> answer as normal."""
    unit, asset_a, _asset_b = _editor_context(
        page, live_server, "ftbl_img2", "ftbl-img2"
    )
    element = _seed_filltable_for_images(unit)
    _goto_editor(page, live_server, "ftbl_img2", unit)
    _open_edit(page, element.pk)

    editor = page.locator("[data-filltable-editor]")
    grid = editor.locator("[data-table-grid]")
    cell = grid.locator("td:not([data-control])").nth(0)

    cell.click()
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay", timeout=5000)
    page.locator(f".picker-overlay .asset-pick[data-asset-id='{asset_a.pk}']").click()
    editor.locator("[data-image-alt]").fill("graph")
    assert grid.locator("td[data-image]").count() == 1

    answer_toggle = editor.locator("[data-answer-toggle]")
    first_cell = grid.locator("td:not([data-control])").nth(0)

    answer_toggle.click()  # image -> static (one step)
    assert grid.locator("td[data-image]").count() == 0
    assert first_cell.get_attribute("data-media") is None

    answer_toggle.click()  # static -> answer
    assert first_cell.get_attribute("data-answer") is not None
    assert first_cell.get_attribute("data-media") is None
    assert first_cell.get_attribute("data-alt") is None


@pytest.mark.django_db(transaction=True)
def test_filltable_nested_in_tab_restores_after_reload(page, live_server):
    """Fill-in table is in NESTABLE_TYPE_KEYS -- nested inside a Tabs panel. The
    widget JS's root-scoped lookups and the server render must restore
    correctly inside a tab panel exactly as at top level."""
    from courses.models import Element
    from courses.models import FillTableElement

    student, unit = _new_unit("ftbl_tabs")
    el = FillTableElement(
        data={
            "cells": [
                [{"kind": "static", "html": "a"}, {"kind": "answer", "answer": "4"}]
            ]
        }
    )
    el.save()
    join = _seed_tab1(unit, [el])
    row = Element.objects.get(parent=join, content_type__model="filltableelement")
    _seed_state(student, unit, {str(row.pk): {"done": True}})
    _login(page, live_server, "ftbl_tabs")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    inp = page.locator('.filltable__input[data-r="0"][data-c="1"]')
    expect(inp).to_have_value("4")
    expect(inp).to_have_js_property("readOnly", True)
