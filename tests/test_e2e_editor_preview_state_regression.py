"""Playwright e2e REGRESSION guard: the shared window.libliState helper
(courses/static/courses/js/state.js) must be loaded by the authoring editor
template (templates/courses/manage/editor/editor.html), not just by the
student-facing templates/courses/lesson_unit.html.

editor.html loads fillgate.js / switchgate.js / switchgrid.js / filltable.js /
guessnumber.js, and each of those files self-inits (`initXxx(document)`) at
script-parse time -- which runs on the editor's OWN initial page load, over
whatever preview the server already rendered. Each widget's `initOne` now
dereferences `window.libliState.storedFlag(...)` FIRST, before doing anything
else. Without the state.js include, that throws
`TypeError: Cannot read properties of undefined (reading 'storedFlag')`
before the widget gets a chance to arm its Confirm button (switchgate.js's
initOne un-hides `.switchgate__confirm` only AFTER the storedFlag check).

So: seed a unit with a lone SwitchGateElement (no reveal-gate, no other
new-family widget -- isolates this file's regression from the others), open
the editor for it as a Platform Admin, and assert (a) no pageerror fires and
(b) the preview's Confirm button is actually armed (visible, not [hidden]).
Both assertions independently prove the theory: without state.js on the page
this test is RED (pageerror captured, Confirm still hidden); with it restored
it is GREEN.

Mirrors the editor login/seed/URL helpers in tests/test_e2e_editor_ws3.py and
tests/test_e2e_switchgrid.py's editor-add section, and the SwitchGateElement
builder in tests/test_e2e_switchgate.py."""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
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


def _seed_authoring_unit(pa, slug):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _switchgate(author_stem, options, answer):
    """Build a SwitchGateElement from author `{{choice}}` markup (mirrors
    tests/test_e2e_switchgate.py's helper -- the raw sentinel token is never
    pasted directly here)."""
    from courses import switchgate
    from courses.models import SwitchGateElement

    return SwitchGateElement.objects.create(
        stem=switchgate.parse_stem(author_stem), options=list(options), answer=answer
    )


@pytest.mark.django_db(transaction=True)
def test_editor_preview_switchgate_arms_without_pageerror(page, live_server):
    """CRITICAL regression guard: state.js must load on the editor page.

    Without it, switchgate.js's initOne throws reading window.libliState
    before it can un-hide .switchgate__confirm -- RED: pageerror captured AND
    Confirm stays [hidden]. With state.js loaded, initOne completes and arms
    the button -- GREEN: no pageerror, Confirm visible."""
    pa = _make_pa_user("edstate_a")
    course, unit = _seed_authoring_unit(pa, "edstate-a")
    add_element(unit, _switchgate("Pick: {{choice}}", ["Alpha", "Bravo"], answer=1))

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    _login(page, live_server, "edstate_a")
    page.goto(_editor_url(live_server, course, unit))
    page.wait_for_selector('[data-scope="preview"] [data-switchgate]')

    assert errors == [], f"unexpected pageerror(s): {errors}"
    confirm = page.locator('[data-scope="preview"] .switchgate__confirm')
    expect(confirm).to_be_visible()
