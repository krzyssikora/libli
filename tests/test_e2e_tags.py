"""Playwright e2e for Phase 4b personal tags: add → filter → untag → delete.

Real browser gestures only — no page.evaluate shortcuts (prior project lesson:
an e2e that bypasses the real gesture ships broken UX green).

Marked `e2e` (excluded by default; run with -m e2e).
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


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_tag_filter_untag_delete_via_ui(page, live_server):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="tagger", email="tagger@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Bio")
    Enrollment.objects.create(student=user, course=course)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    unit = ContentNodeFactory(
        course=course, parent=part, unit_type="lesson", title="Photosynthesis"
    )
    # A second, deliberately untagged unit: filtering by a tag must HIDE it (and
    # collapse its now-empty part). Guards the [hidden]-vs-display:flex CSS gotcha —
    # without .outline-node[hidden]{display:none} the row stays visible despite the
    # attribute, so this is the assertion that actually proves the filter works.
    ContentNodeFactory(
        course=course, parent=part, unit_type="lesson", title="Respiration"
    )

    _login(page, live_server, "tagger")

    # ── ADD ──────────────────────────────────────────────────────────────────
    # Navigate to the unit page with ?panel=tags so the <details class="unit-tags">
    # element is rendered with the open attribute.
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/?panel=tags")
    page.locator(".unit-tags__add input[name='name']").fill("exam")
    page.get_by_role("button", name="Add").click()
    # With JS on, wirePanels() intercepts the form submit, POSTs with
    # X-Requested-With: fetch, and swaps the .unit-tags panel fragment in-place
    # (Task 11). The chip appears inside .unit-tags__chips. Playwright auto-waits.
    expect(page.locator(".unit-tags__chips .tag-chip", has_text="exam")).to_be_visible()

    # ── FILTER ───────────────────────────────────────────────────────────────
    # The course outline now renders an "exam" filter chip (the user has at
    # least one unit tagged in this course). Clicking it applies applyFilter()
    # client-side — no page reload. The Photosynthesis unit must remain visible.
    page.goto(f"{live_server.url}/courses/{course.slug}/")
    photosynthesis = page.locator("li[data-unit]", has_text="Photosynthesis")
    respiration = page.locator("li[data-unit]", has_text="Respiration")
    expect(respiration).to_be_visible()  # everything visible before filtering
    page.locator("[data-tags-filter] a.tag-chip", has_text="exam").click()
    # to_be_hidden() checks computed visibility (display:none), not just the
    # [hidden] attribute — so it fails if the CSS override regresses.
    expect(photosynthesis).to_be_visible()
    expect(respiration).to_be_hidden()
    # Clearing the filter (toggle the chip off) brings the untagged unit back.
    page.locator("[data-tags-filter] a.tag-chip", has_text="exam").click()
    expect(respiration).to_be_visible()

    # ── UNTAG ────────────────────────────────────────────────────────────────
    # Return to the unit page (panel open). The Remove button has
    # aria-label="Remove tag exam" (from the blocktrans template). With JS on,
    # wirePanels() POSTs the remove form as a fetch and replaces the panel.
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/?panel=tags")
    page.get_by_role("button", name="Remove tag exam").click()
    # Wait for the JS fragment swap: the "exam" chip disappears from the panel.
    chips = page.locator(".unit-tags__chips .tag-chip", has_text="exam")
    expect(chips).to_have_count(0)

    # ── DELETE ───────────────────────────────────────────────────────────────
    # The tag still exists on My tags (0 units attached). The 🗑 link has
    # aria-label="Delete exam". With JS on, wireDeleteConfirm() intercepts the
    # click and swaps in a <span class="tag-delete-confirm"> containing a form
    # with a "Yes" submit button (text from MSG.msgYes = {% trans 'Yes' %}).
    # Clicking "Yes" submits that form (full POST — not fetch); the server
    # redirects back to /tags/ and the tag-section is gone.
    page.goto(f"{live_server.url}/tags/")
    page.get_by_role("link", name="Delete exam").click()
    page.get_by_role("button", name="Yes").click()
    expect(page.locator(".tag-section", has_text="exam")).to_have_count(0)
