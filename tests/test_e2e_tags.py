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


@pytest.mark.django_db(transaction=True)
def test_edit_link_survives_adding_a_tag(page, live_server):
    """The Edit link must survive tags.js's panel.replaceWith() swap.

    This is the ONLY test that can catch it: the swap happens with JS on only, so
    every server-side test passes while the link silently vanishes the first time
    the user tags a unit — during the exact workflow this feature exists for.
    """
    from tags.models import Tag
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="editor", email="editor@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Owned", owner=user)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    unit = ContentNodeFactory(
        course=course, parent=part, unit_type="lesson", title="Photosynthesis"
    )
    # Tags the author owns but has NOT put on this unit, so the open panel renders
    # <fieldset class="unit-tags__picker"> with real content. Without them the
    # picker is omitted entirely, the panel is narrow, and step 5's row assertion
    # would be vacuous — green even under the `flex-basis: auto` bug it guards.
    # A dozen is what a prolific author accumulates; it is not a pathological count.
    for i in range(12):
        Tag.objects.create(author=user, name=f"chapter-review-{i:02d}")

    _login(page, live_server, "editor")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/?panel=tags")

    # 1. The link is there to begin with — anchors the later assertion to a
    #    proven positive.
    expect(page.locator(".unit-strip__edit")).to_be_visible()

    # 2. Add a tag through the REAL form: a real fill and a real click on the real
    #    submit. Never page.evaluate — an e2e that bypasses the gesture ships
    #    broken UX green.
    page.locator(".unit-tags__add input[name='name']").fill("walkthrough")
    page.get_by_role("button", name="Add").click()

    # 3. Wait on a CONTENT condition on the swapped-in panel. tags.js swaps from
    #    an un-awaited fetch().then() and leaves behind no marker attribute,
    #    status node or URL change, so there is no deterministic anchor to wait
    #    on. Same idiom as the ADD block above. A bare timeout is NOT acceptable.
    expect(
        page.locator(".unit-tags__chips .tag-chip", has_text="walkthrough")
    ).to_be_visible()

    # 4. ONLY NOW assert the link survived. The ordering is load-bearing:
    #    asserting it before the swap completes would pass even if the swap went
    #    on to destroy it — green while broken.
    expect(page.locator(".unit-strip__edit")).to_be_visible()

    # 5. Surviving is not the same as being USABLE where it was designed to be.
    #    to_be_visible() stays green when .unit-strip's flex-wrap drops the button
    #    onto a second row, which is exactly what a `flex-basis: auto` on
    #    .unit-strip .unit-tags does once the picker fieldset's max-content exceeds
    #    the line — and the picker grows with the author's tag count, so it happens
    #    at desktop widths, not only when narrow. Assert the ROW instead.
    page.set_viewport_size({"width": 1280, "height": 900})
    link_box = page.locator(".unit-strip__edit").bounding_box()
    panel_box = page.locator(".unit-tags").bounding_box()
    assert link_box and panel_box, "both flex items must have a layout box"
    # Same row: tops within a few px. The two items are align-items: flex-start
    # siblings, so on one row they share a top edge exactly; a wrap puts the link a
    # full panel-height (tens of px) lower. 6px is loose enough for sub-pixel and
    # font-metric noise, far tighter than any wrap can be.
    assert abs(link_box["y"] - panel_box["y"]) <= 6, (
        f"the Edit link dropped off the tag panel's row — link y={link_box['y']}, "
        f"panel y={panel_box['y']}. Check `flex` on `.unit-strip .unit-tags`: a "
        f"basis of `auto` line-breaks on the picker's max-content."
    )
    # ...and to the RIGHT of the panel, not stacked over its left edge.
    assert link_box["x"] > panel_box["x"], (
        f"the Edit link must sit to the right of the tag panel — "
        f"link x={link_box['x']}, panel x={panel_box['x']}"
    )
