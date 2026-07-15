"""Playwright e2e for the Mark-done checklist. Marked e2e (run with -m e2e).

Drives the REAL checkbox gesture end-to-end (a page.evaluate shortcut that bypasses
the real click is forbidden in this repo) and waits for the auto-save POST to the
`.../markdone/` endpoint to complete before reloading, so persistence is proven on a
fresh server render — not just an optimistic client toggle.

Harness mirrors tests/test_e2e_stepper.py (fixtures, HTML-form login, seed helpers);
the tab-nesting seed mirrors courses/tests/test_markdone_render.py."""

import os

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_common(username, slug):
    """An enrolled student on a fresh lesson unit. Returns (course, unit)."""
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _markdone(prompt="Prep", items=("one", "two")):
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem

    el = MarkDoneElement.objects.create(prompt=prompt)
    made = [MarkDoneItem.objects.create(element=el, content=c) for c in items]
    return el, made


def _lesson_url(live_server, course, unit):
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def test_tick_persists_across_reload(live_server, page):
    """Real click on the first checkbox -> auto-save POST to .../markdone/ -> reload:
    the box stays checked and its row keeps the `on` class (server-rendered state)."""
    from courses.models import Element

    course, unit = _seed_common("mdstu", "markdone-e2e")
    el, (i1, i2) = _markdone()
    Element.objects.create(unit=unit, content_object=el)

    _login(page, live_server, "mdstu")
    page.goto(_lesson_url(live_server, course, unit))
    page.wait_for_selector("[data-markdone]")

    first = page.locator(".markdone__item input[type='checkbox']").first
    assert not first.is_checked()

    # REAL click (not page.evaluate); wait for the save POST to finish before reloading.
    with page.expect_response(
        lambda r: "/markdone/" in r.url and r.request.method == "POST"
    ) as resp_info:
        first.check()
    assert resp_info.value.ok

    page.reload()
    page.wait_for_selector("[data-markdone]")
    reloaded = page.locator(".markdone__item input[type='checkbox']").first
    assert reloaded.is_checked()
    row = page.locator(".markdone__item").first
    assert "on" in (row.get_attribute("class") or "")


def test_nested_in_tabs_tick_persists(live_server, page):
    """A checklist nested inside a Tabs element: tick, reload, still checked + `on`.
    Seeds the tab child exactly like courses/tests/test_markdone_render.py."""
    from courses.models import Element
    from courses.models import TabsElement

    course, unit = _seed_common("mdtab", "markdone-tabs-e2e")
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    parent = Element.objects.create(unit=unit, content_object=tabs)
    el, (i1, i2) = _markdone()
    Element.objects.create(
        unit=unit, content_object=el, parent=parent, tab_id="t000001"
    )

    _login(page, live_server, "mdtab")
    page.goto(_lesson_url(live_server, course, unit))
    page.wait_for_selector("[data-markdone]")

    first = page.locator(".markdone__item input[type='checkbox']").first
    assert not first.is_checked()

    with page.expect_response(
        lambda r: "/markdone/" in r.url and r.request.method == "POST"
    ) as resp_info:
        first.check()
    assert resp_info.value.ok

    page.reload()
    page.wait_for_selector("[data-markdone]")
    reloaded = page.locator(".markdone__item input[type='checkbox']").first
    assert reloaded.is_checked()
    row = page.locator(".markdone__item").first
    assert "on" in (row.get_attribute("class") or "")
