"""Playwright e2e for the Tags & notes hub: revision loop + standalone clamp.

Real browser gestures only — no page.evaluate shortcuts (prior project lesson:
an e2e that bypasses the real gesture ships broken UX green).

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest

from courses.models import Enrollment
from notes import services
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Playwright's sync API runs an event loop, which trips Django's async-safety
    # guard on every ORM call (see test_e2e_notes.py / test_e2e_smoke.py).
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed(long_body=False):
    user = make_verified_user(username="e2estud", email="e2estud@test.example.com")
    course = CourseFactory(title="Revision Course")
    Enrollment.objects.create(student=user, course=course, source="manual")
    unit = ContentNodeFactory(course=course, title="Lesson One")
    el = ElementFactory(unit=unit)
    body = ("A very long revision note. " * 60) if long_body else "MY REVISION NOTE"
    note = services.create_note(user, unit, el.pk, body)
    return user, course, unit, note


def _login(page, live_server, username):
    # Form-scoped to avoid the header's language/theme submit buttons
    # (per test_e2e_notes.py).
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_e2e_revision_loop(page, live_server):
    user, course, unit, note = _seed()
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}/tags-and-notes/")
    page.click(".tnhub__card-notes")  # the card's "N notes" link -> per-course index
    assert "MY REVISION NOTE" in page.content()
    page.click(".note-card__gotolesson a")
    page.wait_for_url(f"**/u/{unit.pk}/**")
    # the note is rendered on the lesson (annotated block expanded via ?notes=1)
    assert f"note-{note.pk}" in page.content()


@pytest.mark.django_db(transaction=True)
def test_e2e_tabs_stay_put_across_switch(page, live_server):
    """Heading + tab bar must not move when switching between the two tabs.

    Regression: the tabs are two separate pages; mismatched container geometry
    (centering/max-width) and a lead paragraph on only one page shifted the
    <h1> and tab bar between views, so they didn't read as real tabs.
    """
    user, course, unit, note = _seed()
    _login(page, live_server, user.username)

    def positions():
        h1 = page.locator("h1").first.bounding_box()
        tabs = page.locator(".tnhub__tabs").bounding_box()
        return h1, tabs

    page.goto(f"{live_server.url}/tags-and-notes/")  # By course
    h1_a, tabs_a = positions()
    page.click(".tnhub__tab:has-text('Manage tags')")
    page.wait_for_url("**/tags/")
    h1_b, tabs_b = positions()

    assert (h1_a["x"], h1_a["y"]) == (h1_b["x"], h1_b["y"])
    assert (tabs_a["x"], tabs_a["y"]) == (tabs_b["x"], tabs_b["y"])


@pytest.mark.django_db(transaction=True)
def test_e2e_standalone_clamp_activates(page, live_server):
    user, course, unit, note = _seed(long_body=True)
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/notes/")
    more = page.locator(".note-card__more")
    more.wait_for(state="visible")
    assert more.count() == 1
    body = page.locator(".note-card__body").first
    assert "note-card__body--clamp" in (body.get_attribute("class") or "")
    more.click()
    assert "note-card__body--clamp" not in (body.get_attribute("class") or "")


@pytest.mark.django_db(transaction=True)
def test_e2e_standalone_clamp_label_localizes(page, live_server):
    """Drive the real PL language switch, then assert the clamp toggle localizes."""
    user, course, unit, note = _seed(long_body=True)
    _login(page, live_server, user.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/notes/")
    # Header language form (test_e2e_smoke.py): posts next=<current path>,
    # reloads in PL.
    page.click("button[name='language'][value='pl']")
    page.wait_for_load_state("networkidle")
    more = page.locator(".note-card__more")
    more.wait_for(state="visible")
    # "Show more" -> "Pokaż więcej" (Task 7's i18n gate verifies this
    # against the catalog).
    assert more.inner_text().strip() == "Pokaż więcej"
