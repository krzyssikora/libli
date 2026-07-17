"""Playwright e2e for the practice-state substrate. Marked e2e (run with -m e2e).

Drives the REAL checkbox gesture (a page.evaluate shortcut is forbidden in this repo)
and waits for the auto-save POST to `.../state/` to COMPLETE before reloading, so
persistence is proven on a fresh server render -- not an optimistic client toggle.

Harness mirrors tests/test_e2e_markdone.py (login + seed helpers)."""

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


def _seed(username, slug):
    """An enrolled student on a lesson holding one checklist with TWO items."""
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
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
    el = MarkDoneElement.objects.create(prompt="Prep")
    for c in ("one", "two"):
        MarkDoneItem.objects.create(element=el, content=c)
    Element.objects.create(unit=unit, content_object=el)
    return course, unit


def _lesson_url(live_server, course, unit):
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _is_save(r):
    return "/state/" in r.url and r.request.method == "POST"


def test_tick_survives_a_reload(live_server, page):
    """The whole feature, end to end: a real click, a real reload."""
    course, unit = _seed("psstu", "practice-state-e2e")
    _login(page, live_server, "psstu")
    page.goto(_lesson_url(live_server, course, unit))
    page.wait_for_selector("[data-markdone]")

    first = page.locator(".markdone__item input[type='checkbox']").first
    assert not first.is_checked()
    # Wait for the SAVE to complete, not for the `on` class: markdone.js toggles `on`
    # SYNCHRONOUSLY before fetch(), so a wait_for_function on it resolves instantly and
    # the reload races the in-flight POST (keepalive guarantees the request is SENT,
    # not that the server committed it).
    with page.expect_response(_is_save) as resp:
        first.check()
    assert resp.value.ok

    page.reload()
    page.wait_for_selector("[data-markdone]")
    assert page.locator(".markdone__item input[type='checkbox']").first.is_checked()


def test_two_ticks_both_reach_the_server(live_server, page):
    """Two real ticks in succession -> both survive a reload.

    SCOPE, stated honestly: this does NOT police the `seq` last-write-wins guard, and
    must not claim to. Two earlier drafts did:
      - a post-reload assertion is guard-agnostic (paint() fires no `change` event, so
        the client never re-POSTs; the server holds [A, B] from B's request either way);
      - a pre-reload assertion only diverges when A's echo arrives AFTER B's, which
        does not happen in the ordinary in-order case -- and Playwright's check()
        actionability waits mean A's response usually lands before the second click
        even fires, so no burst occurs at all.
    The guard's real coverage is test_markdone_scripts.py's source assertions
    (`var mine = ++seq;` / `if (mine !== seq) return;`). A deterministic reorder e2e
    (page.route delaying the first response past the second) is DEFERRED -- it is worth
    doing if this ever regresses in the wild.
    What this DOES prove end-to-end: two successive REAL ticks each reach the server,
    and the second does not lose the first, on a fresh server render.
    (NB these are two ITEMS of ONE element -- two writes to the same element_state key.
    Multi-ELEMENT accumulation across keys is a different property, proven by
    test_concurrent_two_element_save_does_not_clobber in Task 5.)
    """
    course, unit = _seed("psburst", "practice-state-burst-e2e")
    _login(page, live_server, "psburst")
    page.goto(_lesson_url(live_server, course, unit))
    page.wait_for_selector("[data-markdone]")

    boxes = page.locator(".markdone__item input[type='checkbox']")
    with page.expect_response(_is_save) as r1:
        boxes.nth(0).check()
    assert r1.value.ok
    with page.expect_response(_is_save) as r2:
        boxes.nth(1).check()
    assert r2.value.ok

    page.reload()
    page.wait_for_selector("[data-markdone]")
    reloaded = page.locator(".markdone__item input[type='checkbox']")
    assert reloaded.nth(0).is_checked() and reloaded.nth(1).is_checked()


def test_reset_clears_the_ticks(live_server, page):
    course, unit = _seed("psreset", "practice-state-reset-e2e")
    _login(page, live_server, "psreset")
    url = _lesson_url(live_server, course, unit)
    page.goto(url)
    page.wait_for_selector("[data-markdone]")

    with page.expect_response(_is_save) as resp:
        page.locator(".markdone__item input[type='checkbox']").first.check()
    assert resp.value.ok

    reset_path = reverse(
        "courses:progress_reset", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{reset_path}")
    page.get_by_role("button", name="Start fresh").click()

    page.goto(url)
    page.wait_for_selector("[data-markdone]")
    assert not page.locator(".markdone__item input[type='checkbox']").first.is_checked()
