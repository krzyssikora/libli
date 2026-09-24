"""e2e for inline {{answer}} boxes in a Fill-in table (spec 2026-09-24 §5-§7).
Drives the REAL editor (typing into contenteditable cells, saving) and the REAL
student gesture (typing, Check). Helpers are copied from test_e2e_filltable.py."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

_CORRECT = re.compile(r"\bfilltable__input--correct\b")
_INCORRECT = re.compile(r"\bfilltable__input--incorrect\b")


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# Helpers copied from tests/test_e2e_filltable.py (that file's idiom: local copies,
# no cross-test-module imports).


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _unit_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _make_pa_user(username):
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


def _editor_unit(username, slug):
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    _make_pa_user(username)
    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )


def _goto_editor(page, live_server, username, unit):
    _login(page, live_server, username)
    page.goto(
        f"{live_server.url}/manage/courses/{unit.course.slug}/build/unit/{unit.pk}/edit/"
    )
    page.wait_for_selector('[data-scope="editor"]')


def _open_edit(page, element_pk):
    page.locator(f'.el-act-edit[data-element-id="{element_pk}"]').click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]")


def _seed_static_table(unit):
    """2x1 all-static table: saveable at model level; the FORM would reject it
    until the author types a box -- which is exactly the gesture under test."""
    from courses.models import FillTableElement

    el = FillTableElement(
        data={
            "cells": [
                [{"kind": "static", "html": "a"}],
                [{"kind": "static", "html": "b"}],
            ]
        }
    )
    el.save()
    return add_element(unit, el)


def _type_into_cell(page, cell, text):
    cell.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.type(text)


@pytest.mark.django_db(transaction=True)
def test_author_types_boxes_student_checks_each(page, live_server):
    from tests.factories import EnrollmentFactory
    from tests.factories import make_verified_user

    unit = _editor_unit("ftgap_author", "ftgap")
    element = _seed_static_table(unit)
    _goto_editor(page, live_server, "ftgap_author", unit)
    _open_edit(page, element.pk)

    cells = page.locator("[data-edit-slot] [data-table-grid] td[contenteditable]")
    _type_into_cell(page, cells.nth(0), "{{9}} \\(\\pi\\)")
    _type_into_cell(page, cells.nth(1), "\\((x+2)^2+(y\\) {{-1}} \\()^2=\\) {{16}}")
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]", state="detached")

    # Re-open: the editor shows the markers again (not tokens), then save unchanged.
    _open_edit(page, element.pk)
    expect(cells.nth(0)).to_contain_text("{{9}}")
    page.locator("[data-edit-slot] .editor-form__actions button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-filltable-editor]", state="detached")

    student = make_verified_user(
        username="ftgap_student",
        email="ftgap_student@t.example.com",
        password=TEST_PASSWORD,
    )
    EnrollmentFactory(student=student, course=unit.course)
    page.context.clear_cookies()
    _login(page, live_server, "ftgap_student")
    page.goto(_unit_url(live_server, unit))

    table = page.locator(".filltable").first
    pi_box = table.locator(
        '.filltable__input--inline[data-r="0"][data-c="0"][data-g="0"]'
    )
    g0 = table.locator('.filltable__input--inline[data-r="1"][data-c="0"][data-g="0"]')
    g1 = table.locator('.filltable__input--inline[data-r="1"][data-c="0"][data-g="1"]')
    expect(table.locator(".katex").first).to_be_visible()  # maths beside the boxes

    width_before = g1.bounding_box()["width"]

    pi_box.fill("9")
    g0.fill("1")  # WRONG (box 0 -- the g === 0 trap)
    g1.fill("16")  # right
    table.locator(".filltable__confirm").click()
    expect(g0).to_have_class(_INCORRECT)
    expect(g1).to_have_class(_CORRECT)
    expect(pi_box).to_have_class(_CORRECT)

    g0.fill("-1")
    table.locator(".filltable__confirm").click()
    expect(g0).to_have_class(_CORRECT)
    expect(table.locator(".filltable__confirm")).to_be_hidden()  # locked

    # The live lock sets `disabled`; the done-state width release must not fire.
    assert abs(g1.bounding_box()["width"] - width_before) < 2
