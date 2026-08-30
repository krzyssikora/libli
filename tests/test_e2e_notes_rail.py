"""Playwright e2e: the note handle costs zero vertical space in the rail state.

The affordance used to be a flow row whose height was FIXED per block regardless
of the block's own height, so a one-line paragraph carried ~29px of icon beneath
~26px of text — the "short paragraphs read as spread out" complaint. Where the
column can spare a lane (notes.css, the rail block) the handle leaves the flow
entirely and the rhythm falls back to the plain element margin.

Why an e2e and not a CSS-text assertion: the defect this guards is a LAYOUT
outcome produced by margin collapsing across the aside, and an earlier attempt
that zeroed the aside's margins looked correct in the stylesheet while measuring
32px — twice the intended gap. Only a real browser catches that.

The collapsed TOC state is opt-in (base.html reads localStorage), so this suite
sets that key itself; no other e2e exercises the collapsed shell.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e

# Wide enough for the rail's own gate (min-width: 1200px). Below it the handle
# stays in flow by design, and every assertion here would be measuring the
# fallback instead of the rail.
RAIL_VIEWPORT = {"width": 1400, "height": 950}

# Per-block geometry: the gap between consecutive elements, the aside's height,
# and whether the handle stays clear of the prose it annotates.
GEOMETRY = """
() => {
  const blocks = [...document.querySelectorAll('.lesson-block')];
  const gaps = [];
  for (let i = 0; i < blocks.length - 1; i++) {
    const a = blocks[i].querySelector('.el');
    const b = blocks[i + 1].querySelector('.el');
    if (a && b) gaps.push(Math.round(
      b.getBoundingClientRect().top - a.getBoundingClientRect().bottom));
  }
  const handles = blocks.map(b => {
    const h = b.querySelector('.block-notes__handle');
    const body = b.querySelector('.lesson-block__body');
    if (!h || !body) return null;
    // Measure the INK, not the handle's border box: the box is pinned by the
    // rail's fixed width, so content that overflows it (an inline count, say)
    // would be invisible to a box measurement while sitting over the prose.
    const ink = [...h.querySelectorAll('.block-notes__icon, .block-notes__count')]
      .map(e => e.getBoundingClientRect());
    return {
      inkLeft: Math.round(Math.min(...ink.map(r => r.left))),
      inkRight: Math.round(Math.max(...ink.map(r => r.right))),
      bodyRight: Math.round(body.getBoundingClientRect().right),
      blockRight: Math.round(b.getBoundingClientRect().right),
      clearsProse:
        Math.min(...ink.map(r => r.left)) >= body.getBoundingClientRect().right - 0.5,
      insideBlock:
        Math.max(...ink.map(r => r.right)) <= b.getBoundingClientRect().right + 0.5,
    };
  }).filter(Boolean);
  const el = document.querySelector('.lesson-block .el');
  return {
    gaps,
    handles,
    // The rhythm the page would have with NO affordance at all. Read from the
    // element rather than hard-coded so a future spacing change moves both.
    elMarginBottom: Math.round(parseFloat(getComputedStyle(el).marginBottom)),
    asideHeights: blocks
      .map(b => b.querySelector('.block-notes'))
      .filter(Boolean)
      .map(a => Math.round(a.getBoundingClientRect().height)),
  };
}
"""


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    # Mirrors the helper proven in tests/test_e2e_notes.py.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _build_lesson(slug, username):
    from courses.models import ContentNode
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import TextElement
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import CourseFactory
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug=slug)
    # published=True: 0057's model default is False and the student must reach
    # the unit at all (same fix as tests/test_e2e_notes.py).
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Rail",
        published=True,
    )
    # SHORT bodies deliberately: a one-line paragraph is the case where a fixed
    # affordance row costs more height than the text it annotates, so it is the
    # case that fails loudest if the handle returns to the flow.
    elements = [
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(
                body=f"<p>Short paragraph number {n}.</p>"
            ),
        )
        for n in range(5)
    ]
    student = make_verified_user(
        username=username, email=f"{username}@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    return course, unit, elements, student


def _open_collapsed(page, live_server, course, unit):
    page.set_viewport_size(RAIL_VIEWPORT)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    # The rail is gated on the collapsed shell, which base.html's pre-paint
    # restores from localStorage. Set it, then reload so the class is present
    # before first paint (setting it after load would leave <html> unclassed).
    page.evaluate("() => localStorage.setItem('libli_unit_tree_collapsed', '1')")
    page.reload()
    page.wait_for_selector(".block-notes__handle")


@pytest.mark.django_db(transaction=True)
def test_handle_costs_no_vertical_space_in_the_rail(page, live_server):
    course, unit, _, _ = _build_lesson("e2e-rail-space", "e2e_rail_space")
    _login(page, live_server, "e2e_rail_space")
    _open_collapsed(page, live_server, course, unit)

    geo = page.evaluate(GEOMETRY)

    assert geo["gaps"], "no consecutive blocks were measured"
    # THE ASSERTION. In the rail the affordance is out of flow, so consecutive
    # elements sit exactly one element-margin apart — the same rhythm the page
    # would have if the notes feature did not exist. Any value above this means
    # the handle (or the aside's margins) is back in the flow.
    assert geo["gaps"] == [geo["elMarginBottom"]] * len(geo["gaps"]), (
        f"blocks are {geo['gaps']} apart; the bare element rhythm is "
        f"{geo['elMarginBottom']}px, so the affordance is still taking space"
    )
    # The aside itself must collapse away — the handle is absolutely positioned
    # and the closed pop is display:none, so nothing in-flow is left.
    assert geo["asideHeights"] == [0] * len(geo["asideHeights"]), geo["asideHeights"]


@pytest.mark.django_db(transaction=True)
def test_handle_sits_in_its_lane_clear_of_the_prose(page, live_server):
    from notes.models import Note

    course, unit, elements, student = _build_lesson("e2e-rail-lane", "e2e_rail_lane")
    # A 2-digit count is the widest the handle ever gets. It is anchored on
    # `right`, so an overflowing count grows LEFTWARDS over the text — which is
    # what the fixed width in the rail block exists to prevent.
    for i in range(12):
        Note.objects.create(
            author=student, unit=unit, element=elements[0], body=f"note {i}"
        )
    _login(page, live_server, "e2e_rail_lane")
    _open_collapsed(page, live_server, course, unit)

    geo = page.evaluate(GEOMETRY)
    assert geo["handles"], "no handles were measured"
    assert all(h["clearsProse"] for h in geo["handles"]), geo["handles"]
    assert all(h["insideBlock"] for h in geo["handles"]), geo["handles"]


@pytest.mark.django_db(transaction=True)
def test_pop_still_opens_beside_the_block_from_the_rail(page, live_server):
    from notes.models import Note

    course, unit, elements, student = _build_lesson("e2e-rail-pop", "e2e_rail_pop")
    Note.objects.create(
        author=student, unit=unit, element=elements[0], body="anchored note"
    )
    _login(page, live_server, "e2e_rail_pop")
    _open_collapsed(page, live_server, course, unit)

    # Real gesture: click the summary, as a student would.
    page.locator(".block-notes__handle").first.click()
    page.wait_for_selector(".block-notes__panel[open] .block-notes__pop")

    pop = page.evaluate(
        """() => {
        const p = document.querySelector(
          '.block-notes__panel[open] .block-notes__pop');
        const r = p.getBoundingClientRect();
        return {onScreen: r.right <= window.innerWidth && r.left >= 0,
                cards: p.querySelectorAll('.note-card').length};
      }"""
    )
    # Positioning the ASIDE rather than the handle would re-parent the pop's
    # containing block onto a 2.75rem box, collapsing it into the lane.
    assert pop["onScreen"], "pop left the viewport"
    assert pop["cards"] == 1, pop
    page.wait_for_selector("text=anchored note")
