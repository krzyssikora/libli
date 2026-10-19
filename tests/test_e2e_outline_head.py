"""Playwright e2e: the course head, the list header and the "⋯" menus (spec §3.1,
§3.3, §3.7). Geometry is read from the live layout at real phone and desktop
widths, with the Polish UI where the longest labels matter. Marked e2e (run with
-m e2e).
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

NO_HSCROLL = (
    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
)


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed(username, *, started=False, unit_type="lesson", root_unit=False):
    """Three parts, each part > chapter > unit, for an enrolled student.

    started=True saves practice work in the first part's unit, which renders the
    course "⋯" menu and the menus of part one and its chapter (and makes the
    resume state "resume", so the head shows the resume card). A fresh student
    gets the D2 start button instead.
    """
    from courses.models import Enrollment
    from courses.models import UnitProgress
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username=username, email=f"{username}@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Matematyka")
    Enrollment.objects.create(student=user, course=course)
    root = None
    if root_unit:
        root = ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=None, title="Intro"
        )
    parts, chapters, units = [], [], []
    for title in ("Zbiory liczbowe", "Wyrażenia algebraiczne", "Funkcje"):
        part = ContentNodeFactory(
            course=course, kind="part", unit_type=None, parent=None, title=title
        )
        chapter = ContentNodeFactory(
            course=course, kind="chapter", unit_type=None, parent=part
        )
        unit = ContentNodeFactory(
            course=course, kind="unit", unit_type=unit_type, parent=chapter
        )
        parts.append(part)
        chapters.append(chapter)
        units.append(unit)
    if started:
        UnitProgress.objects.create(
            student=user, unit=units[0], element_state={"1": {"items": []}}
        )
    return {
        "user": user,
        "course": course,
        "parts": parts,
        "chapters": chapters,
        "units": units,
        "root": root,
    }


def _open(page, live_server, username, slug, width, *, polish=True, query=""):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login" not in url)
    page.goto(f"{live_server.url}/courses/{slug}/")
    if polish:
        # The header switch POSTs the UI language and reloads; Polish has the
        # longest labels ("Moje notatki", "Zacznij od nowa").
        page.locator("form.lang-switch button[value='pl']").first.click()
        expect(page.locator(".outline__results")).to_contain_text("Moje wyniki")
    if query:
        # The switch redirects to request.path, dropping any query string.
        page.goto(f"{live_server.url}/courses/{slug}/{query}")


def _box(page, selector):
    box = page.locator(selector).bounding_box()
    assert box is not None, selector
    return box


def _bottom(box):
    return box["y"] + box["height"]


def _centre_y(box):
    return box["y"] + box["height"] / 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [360, 412])
def test_phone_head_stacks_in_dom_order(page, live_server, width):
    """Phone: one column in DOM order — title, bar + label, resume card, then the
    three actions on one row ("Moje wyniki" and "Moje notatki" share the width
    equally, "⋯" a fixed square)."""
    f = _seed(f"phead{width}", started=True)
    _open(page, live_server, f"phead{width}", f["course"].slug, width)

    assert page.evaluate(NO_HSCROLL)
    h1 = _box(page, ".outline__head > .outline__title")
    progress = _box(page, ".outline__head > .outline__progress")
    card = _box(page, ".outline__head > .resume")
    assert _bottom(h1) <= progress["y"] + 0.5, (h1, progress)
    assert _bottom(progress) <= card["y"] + 0.5, (progress, card)

    actions = page.locator(".outline__actions > *")
    expect(actions).to_have_count(3)
    boxes = [a.bounding_box() for a in actions.all()]
    for b in boxes:
        assert b["y"] >= _bottom(card) - 0.5, (card, b)
    centres = [_centre_y(b) for b in boxes]
    assert max(centres) - min(centres) <= 0.5, boxes  # baseline mutant: 1.0px

    results = _box(page, ".outline__actions > .outline__results")
    notes = _box(page, ".outline__actions > .outline__notes")
    assert abs(results["width"] - notes["width"]) <= 2, (results, notes)
    summary = _box(page, ".outline__actions summary.outline-menu__button")
    assert abs(summary["width"] - summary["height"]) <= 1, summary


@pytest.mark.django_db(transaction=True)
def test_start_button_is_auto_width_on_desktop_full_on_phone(page, live_server):
    """D2's start button: auto-width and left-aligned under the top row on
    desktop, full width on a phone. Mutant: drop `justify-self: start`."""
    f = _seed("startw")
    _open(page, live_server, "startw", f["course"].slug, 1280)

    head_width = page.evaluate(
        "() => { const h = document.querySelector('.outline__head');"
        "  const s = getComputedStyle(h);"
        "  return h.clientWidth - parseFloat(s.paddingLeft)"
        "    - parseFloat(s.paddingRight); }"
    )
    start = _box(page, ".outline__head > a.outline__start")
    h1 = _box(page, ".outline__head > .outline__title")
    assert start["width"] < head_width - 1, (start, head_width)
    assert abs(start["x"] - h1["x"]) <= 1, (start, h1)

    page.set_viewport_size({"width": 360, "height": 900})
    head_width = page.evaluate(
        "() => { const h = document.querySelector('.outline__head');"
        "  const s = getComputedStyle(h);"
        "  return h.clientWidth - parseFloat(s.paddingLeft)"
        "    - parseFloat(s.paddingRight); }"
    )
    start = _box(page, ".outline__head > a.outline__start")
    assert abs(start["width"] - head_width) <= 1, (start, head_width)


@pytest.mark.django_db(transaction=True)
def test_actions_align_to_title_without_a_progress_block(page, live_server):
    """An all-quiz course has no progress block (required_total == 0): the
    desktop actions then align to the title's bottom, not to an empty gap.
    Mutants: give the head a non-zero row-gap; drop the actions' align-self: end.
    Measured on a BUTTON, not the actions box: a stretched box ends on the
    title's bottom too, while its centred buttons do not."""
    f = _seed("quizhead", unit_type="quiz")
    _open(page, live_server, "quizhead", f["course"].slug, 1280)

    expect(page.locator(".outline__progress")).to_have_count(0)
    h1 = _box(page, ".outline__head > .outline__title")
    button = _box(page, ".outline__actions > .outline__results")
    assert abs(_bottom(button) - _bottom(h1)) <= 2, (h1, button)


@pytest.mark.django_db(transaction=True)
def test_toggle_hidden_rules_beat_display(page, live_server):
    """`.outline-list__head` and `.outline__toggle-all` carry explicit author
    display rules, which beat the UA `[hidden]` rule unless the `[hidden]`
    twins are declared. A course with no cards renders the header `hidden`, and
    the toggle stays `hidden` (no groups). Mutants, separately: delete
    `.outline__toggle-all[hidden]`; delete `.outline-list__head[hidden]`."""
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="flathead", email="flathead@test.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(title="Flat")
    Enrollment.objects.create(student=user, course=course)
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Only"
    )
    _open(page, live_server, "flathead", course.slug, 1280, polish=False)

    header = page.locator(".outline-list__head")
    expect(header).to_have_count(1)
    assert header.get_attribute("hidden") is not None
    assert header.evaluate("el => getComputedStyle(el).display") == "none"

    toggle = page.locator("[data-outline-toggle-all]")
    expect(toggle).to_have_count(1)
    assert toggle.evaluate("el => el.hidden") is True
    assert toggle.evaluate("el => getComputedStyle(el).display") == "none"


def _tag(user, unit, name="exam"):
    """Authored by the logged-in student, or the filter bar never renders."""
    from tags.models import Tag
    from tags.models import UnitTag

    tag = Tag.objects.create(author=user, name=name)
    UnitTag.objects.create(tag=tag, unit=unit)
    return tag


@pytest.mark.django_db(transaction=True)
def test_disabled_toggle_reads_inert_under_a_filter(page, live_server):
    """Under a tag filter the toggle is disabled: it must not offer a pointer
    cursor, and hovering it must not repaint it. Mutant: delete the
    `.outline__toggle-all:disabled` rules."""
    f = _seed("inert")
    tag = _tag(f["user"], f["units"][1])
    _open(page, live_server, "inert", f["course"].slug, 1280, query=f"?tags={tag.pk}")

    toggle = page.locator("[data-outline-toggle-all]")
    expect(toggle).to_be_visible()
    expect(toggle).to_be_disabled()
    style = (
        "el => { const s = getComputedStyle(el);"
        " return [s.color, s.textDecorationLine]; }"
    )
    assert toggle.evaluate("el => getComputedStyle(el).cursor") == "default"
    before = toggle.evaluate(style)
    toggle.hover()
    assert toggle.evaluate("el => el.matches(':hover')") is True
    assert toggle.evaluate(style) == before


@pytest.mark.django_db(transaction=True)
def test_menu_opens_out_of_flow_without_reflow(page, live_server):
    """Opening a "⋯" menu (course head and a card) changes no row's height and
    causes no horizontal scroll; the panel grows leftwards inside the viewport.
    Mutant: make `.outline-menu__panel` position: static."""
    f = _seed("menuflow", started=True)
    _open(page, live_server, "menuflow", f["course"].slug, 360)

    heights = (
        "() => Array.from(document.querySelectorAll("
        "  '.outline__head, .outline__actions, .outline-list__head,"
        "   .outline-node, summary.outline-node__head, .outline-unit'))"
        "  .map(el => el.getBoundingClientRect().height)"
    )
    before = page.evaluate(heights)
    viewport = page.evaluate("() => document.documentElement.clientWidth")

    for menu_sel in (
        ".outline__actions > details.outline-menu",
        f"#node-{f['parts'][0].pk} > details.outline-menu",
    ):
        page.locator(f"{menu_sel} > summary").click()
        panel = page.locator(f"{menu_sel} > .outline-menu__panel")
        expect(panel).to_be_visible()
        assert page.evaluate(heights) == before, menu_sel
        assert page.evaluate(NO_HSCROLL), menu_sel
        box = panel.bounding_box()
        assert box["x"] + box["width"] <= viewport, (menu_sel, box, viewport)
        page.locator(f"{menu_sel} > summary").click()  # close it again
        expect(panel).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_menu_targets_are_44px_on_a_phone(page, live_server):
    """D7: every "⋯" button and every open-menu item is at least 44px tall."""
    f = _seed("menu44", started=True)
    _open(page, live_server, "menu44", f["course"].slug, 360)

    menus = page.locator("details.outline-menu")
    # Course head, part one, its chapter: the loop below must not pass empty.
    expect(menus).to_have_count(3)
    for i in range(3):
        menu = menus.nth(i)
        summary = menu.locator("> summary")
        box = summary.bounding_box()
        assert box["height"] >= 44 and box["width"] >= 44, (i, box)
        summary.click()
        item = menu.locator(".outline-menu__item")
        expect(item).to_be_visible()
        assert item.bounding_box()["height"] >= 44, i
        summary.click()


@pytest.mark.django_db(transaction=True)
def test_menu_reset_link_reaches_the_confirm_page(page, live_server):
    """The card's "⋯" → "Zacznij od nowa" navigates to the reset confirmation.
    Mutant: change the reset link's href to `#`."""
    f = _seed("menureset", started=True)
    _open(page, live_server, "menureset", f["course"].slug, 360)

    part = f["parts"][0]
    page.locator(f"#node-{part.pk} > details.outline-menu > summary").click()
    link = page.locator(f"#node-{part.pk} > details.outline-menu a.outline-node__reset")
    expect(link).to_be_visible()
    link.click()
    page.wait_for_url(re.compile(rf"/courses/{f['course'].slug}/reset/{part.pk}/"))
    expect(page.locator("section.reset-confirm")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_filter_hiding_every_card_keeps_the_page_intact(page, live_server):
    """Review Focus 2: a tag filter that matches only a root-level unit hides
    every card. The page must not scroll sideways, and the list header still
    counts all three cards."""
    f = _seed("allhidden", root_unit=True)
    tag = _tag(f["user"], f["root"])
    _open(
        page, live_server, "allhidden", f["course"].slug, 360, query=f"?tags={tag.pk}"
    )

    cards = page.locator(".outline-node--card")
    expect(cards).to_have_count(3)
    for i in range(3):
        expect(cards.nth(i)).to_be_hidden()
    expect(page.locator(f"#node-{f['root'].pk}")).to_be_visible()
    assert page.evaluate(NO_HSCROLL)
    expect(page.locator(".outline-list__head")).to_be_visible()
    expect(page.locator(".outline-list__count")).to_have_text(re.compile(r"·\s*3$"))
    expect(page.locator(".outline__head > .outline__title")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_opening_a_menu_does_not_touch_the_stored_fold_state(page, live_server):
    """A "⋯" summary is not `summary.outline-node__head`: opening and closing a
    menu must not run the outline's persistence write. Starting from NO stored
    key makes this falsifiable — any write creates the key. Mutant: widen the
    click handler's `closest("summary.outline-node__head")` to
    `closest("summary")`."""
    f = _seed("menufold", started=True)
    _open(page, live_server, "menufold", f["course"].slug, 1280)
    expect(page.locator("[data-outline-toggle-all]")).to_be_visible()

    key = f"libli_outline_open:{f['course'].slug}"
    read = f"() => localStorage.getItem('{key}')"
    assert page.evaluate(read) is None

    summary = page.locator(
        f"#node-{f['chapters'][0].pk} > details.outline-menu > summary"
    )
    summary.click()
    expect(
        page.locator(f"#node-{f['chapters'][0].pk} .outline-menu__item")
    ).to_be_visible()
    summary.click()
    page.wait_for_timeout(200)  # let any scheduled setTimeout(write, 0) land
    assert page.evaluate(read) is None
