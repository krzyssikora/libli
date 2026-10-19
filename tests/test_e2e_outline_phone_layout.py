"""Playwright e2e: the course outline's head and part headings fit a phone.

Three regressions seen on a real phone (Polish UI, the longest labels):
- every part heading reserved 7.5rem on its right for a "Start fresh" link it
  mostly did not have, so a short title's rollup chip wrapped onto a line of its
  own;
- a long title ("Wyrażenia algebraiczne") dropped onto its own line BELOW its
  chevron instead of wrapping beside it;
- the course title shared its line with "Expand all" and the other buttons piled
  up in ragged rows.
Desktop keeps the title and the buttons on one line. Marked e2e (run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

LONG = "Wyrażenia algebraiczne"
# Wider than a phone row even with nothing reserved: must wrap beside its chevron.
LONGER = "Zastosowania liczb rzeczywistych"
SAVED = "Zbiory liczbowe"
SHORT = ("Elementy logiki", "Funkcje")


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed():
    """Five parts, each part > chapter > lesson. Saved work in the first part's
    lesson renders its "Start fresh" link (and the course-level one); the other
    four parts have none."""
    from courses.models import Enrollment
    from courses.models import UnitProgress
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="phoneout", email="phoneout@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="matematyka")
    Enrollment.objects.create(student=user, course=course)
    parts = {}
    for title in (SAVED, SHORT[0], LONG, SHORT[1], LONGER):
        part = ContentNodeFactory(
            course=course, kind="part", unit_type=None, parent=None, title=title
        )
        chapter = ContentNodeFactory(
            course=course, kind="chapter", unit_type=None, parent=part
        )
        unit = ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=chapter
        )
        parts[title] = (part, unit)
    UnitProgress.objects.create(
        student=user, unit=parts[SAVED][1], element_state={"1": {"items": []}}
    )
    return course, {t: p for t, (p, _) in parts.items()}


def _open_outline(page, live_server, width):
    course, parts = _seed()
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill("phoneout")
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login" not in url)
    page.goto(f"{live_server.url}/courses/{course.slug}/")
    # The header switch POSTs the UI language and reloads; Polish has the longest
    # labels ("Zacznij od nowa", "Rozwiń wszystko").
    page.locator("form.lang-switch button[value='pl']").first.click()
    expect(page.locator(".outline__results")).to_contain_text("Moje wyniki")
    expect(page.locator("[data-outline-toggle-all]")).to_be_visible()
    return parts


def _head(page, part):
    sel = f"[data-node='{part.pk}'] > summary"
    box = lambda s: page.locator(f"{sel} {s}").bounding_box()  # noqa: E731
    return box(".outline-node__chevron"), box(".outline-node__title"), box(".rollup")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [360, 412])
def test_outline_fits_a_phone(page, live_server, width):
    parts = _open_outline(page, live_server, width)

    assert page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )

    # Every title starts on its chevron's line, beside it -- never below it.
    for title, part in parts.items():
        chevron, name, _ = _head(page, part)
        assert name["y"] < chevron["y"] + chevron["height"], (title, chevron, name)
        assert name["x"] >= chevron["x"] + chevron["width"], (title, chevron, name)

    # Without a "Start fresh" link nothing is reserved: the chip reaches the
    # row's end, and a short title keeps it on its own line.
    for title in (LONG, LONGER, *SHORT):
        _, name, chip = _head(page, parts[title])
        row = page.locator(f"[data-node='{parts[title].pk}'] > summary").bounding_box()
        assert chip["x"] + chip["width"] >= row["x"] + row["width"] - 2, (title, chip)
        if title in SHORT:
            assert chip["y"] < name["y"] + name["height"], (title, name, chip)

    # The course title has its line to itself; the buttons sit beneath it.
    h1 = page.locator(".outline__title").bounding_box()
    for i, btn in enumerate(page.locator(".outline__head > .btn").all()):
        box = btn.bounding_box()
        assert box["y"] >= h1["y"] + h1["height"] - 1, (i, h1, box)


@pytest.mark.django_db(transaction=True)
def test_outline_head_stays_on_one_line_on_desktop(page, live_server):
    """D1 puts the title alone in its column: the actions sit in the top row,
    right of the title column, bottom-aligned with the bar + label row, and above
    the resume card."""
    _open_outline(page, live_server, 1280)

    h1 = page.locator(".outline__title").bounding_box()
    progress = page.locator(".outline__progress").bounding_box()
    card = page.locator(".outline__head > .resume").bounding_box()
    expect(page.locator(".outline__actions > *")).to_have_count(3)
    actions = page.locator(".outline__actions").bounding_box()
    assert actions["x"] >= h1["x"] + h1["width"] - 1, (h1, actions)
    assert actions["y"] >= h1["y"] - 1, (h1, actions)
    # The bar and its label share ONE row (.outline__progress), so that row's
    # bottom is the bar row's bottom. Measured on the "⋯" summary (the tallest
    # action), not the actions box: a stretched box would end there too.
    bar_row_bottom = progress["y"] + progress["height"]
    summary = page.locator(".outline__actions summary").bounding_box()
    assert abs(summary["y"] + summary["height"] - bar_row_bottom) <= 2, (
        progress,
        summary,
    )
    assert actions["y"] + actions["height"] <= card["y"] + 0.5, (actions, card)
