"""Playwright e2e: the unit title never collides with the Mark done / Start fresh row.

.lesson-unit__head is a flex row with the title at `flex: 1; min-width: 0` and the
action pill at `flex: none`. At phone width the title column is squeezed to ~98px
while the buttons keep their size; a long word cannot wrap below its own width, so
the heading's glyphs overflow the box and paint UNDERNEATH the buttons.

Box geometry alone does not catch this — the boxes stay 16px apart while the text
overlaps — so the assertion is on TEXT overflow (scrollWidth vs clientWidth) plus a
check that the actions have wrapped onto their own line at phone width.

Marked e2e (excluded from the default run; run with -m e2e).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

PHONE = {"width": 390, "height": 780}
LONG_TITLE = "Przedziały liczbowe i działania na przedziałach — część 1"


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
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import MarkDoneElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title=LONG_TITLE
    )
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>Treść.</p>")
    )
    # KEEPS THE "Start fresh" LINK RENDERED. The link is gated on the unit containing a
    # state-bearing element type; without this row the head row drops to two
    # children and this module silently stops guarding the crowded three-item case
    # it exists for. MarkDone over a question: no child rows, no answer setup, and
    # markdone.js's boot pass is read-only (it POSTs only on click), so it adds no
    # network traffic to a layout test.
    Element.objects.create(
        unit=unit, content_object=MarkDoneElement.objects.create(prompt="P")
    )
    return course, unit


MEASURE = """
() => {
  const head = document.querySelector('.lesson-unit__head');
  const title = head.querySelector('.lesson-unit__title');
  const done = head.querySelector('.unit-done');
  const reset = head.querySelector('.lesson-unit__reset');
  const t = title.getBoundingClientRect();
  const d = done.getBoundingClientRect();
  const r = reset ? reset.getBoundingClientRect() : null;
  return {
    text_overflow: title.scrollWidth - title.clientWidth,
    title_bottom: Math.round(t.bottom),
    title_width: Math.round(t.width),
    done_top: Math.round(d.top),
    done_left: Math.round(d.left),
    has_reset: !!reset,
    reset_top: r ? Math.round(r.top) : null,
    reset_left: r ? Math.round(r.left) : null,
  };
}
"""


@pytest.mark.django_db(transaction=True)
def test_long_title_does_not_overflow_under_the_action_buttons(page, live_server):
    course, unit = _seed("head_phone", "head-phone")
    _login(page, live_server, "head_phone")
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".lesson-unit__head")

    m = page.evaluate(MEASURE)

    assert m["text_overflow"] <= 1, (
        f"the heading's text overflows its box by {m['text_overflow']}px, so the "
        f"glyphs paint outside it (title box {m['title_width']}px wide) — this is "
        "what makes the buttons appear to sit on top of the title"
    )
    # At phone width the actions must have wrapped below the title, not sit beside
    # it in a crushed column.
    assert m["done_top"] >= m["title_bottom"] - 1, (
        f"actions still share the title's line at {PHONE['width']}px "
        f"(title bottom {m['title_bottom']}, actions top {m['done_top']})"
    )
    assert m["has_reset"], (
        "the reset link vanished -- _seed's MarkDoneElement is what keeps it"
    )
    assert m["reset_top"] >= m["title_bottom"] - 1, (
        f"the reset link still shares the title's line at {PHONE['width']}px "
        f"(title bottom {m['title_bottom']}, reset top {m['reset_top']})"
    )


@pytest.mark.django_db(transaction=True)
def test_desktop_keeps_the_actions_beside_the_title(page, live_server):
    """The wrap is a narrow-screen concession — desktop layout must not change."""
    course, unit = _seed("head_desk", "head-desk")
    _login(page, live_server, "head_desk")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".lesson-unit__head")

    m = page.evaluate(MEASURE)
    assert m["text_overflow"] <= 1
    assert m["done_top"] < m["title_bottom"], (
        "on desktop the actions should still sit on the title's line"
    )
    assert m["has_reset"], (
        "the reset link vanished -- _seed's MarkDoneElement is what keeps it"
    )
    assert m["reset_top"] < m["title_bottom"], (
        "on desktop the reset link should still sit on the title's line"
    )
