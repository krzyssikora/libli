"""e2e: single and multiple choice options as outlined cards (spec 2026-11-09).

Every colour is compared with the token as the browser resolves it, through a probe
element, so neither the brand colour nor the theme is hard-coded here.
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.e2e_pick import pick
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

CHECK = "button[type='submit']:not([name='reveal'])"
TRANSPARENT = "rgba(0, 0, 0, 0)"
TICK, CROSS, PLUS = "✓", "✗", "＋"
WIDE = "+".join(f"a_{{{i}}}" for i in range(50))
WIDE_INLINE = rf"\({{{WIDE}}}\)"
WIDE_DISPLAY = rf"\[{WIDE}\]"
# A correct with feedback, B correct, C distractor with feedback, D distractor.
MATRIX = [
    ("A", True, "need A"),
    ("B", True, ""),
    ("C", False, "trap C"),
    ("D", False, ""),
]
A, B, C, D = range(4)


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _options(n, correct=(0,)):
    return [(f"Option {i}", i in correct, "") for i in range(n)]


def _user(username, platform_admin):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    if platform_admin:
        from django.contrib.auth.models import Group

        from institution.roles import PLATFORM_ADMIN
        from institution.roles import seed_roles

        seed_roles()
        user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _seed(user, slug, unit_type, questions):
    """`questions` is a list of (multiple, options, question kwargs)."""
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=user)
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="U"
    )
    for multiple, options, kwargs in questions:
        q = ChoiceQuestionElement.objects.create(
            stem="<p>Pick.</p>", multiple=multiple, **kwargs
        )
        for order, (text, is_correct, feedback) in enumerate(options):
            Choice.objects.create(
                question=q,
                text=text,
                is_correct=is_correct,
                feedback=feedback,
                order=order,
            )
        add_element(unit, q)
    return unit


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _open(page, live_server, username, unit):
    _login(page, live_server, username)
    suffix = "quiz/" if unit.unit_type == "quiz" else ""
    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/{suffix}")
    page.wait_for_selector("[data-question]")


def _lesson(page, live_server, name, *questions):
    user = _user(name, platform_admin=True)
    unit = _seed(user, f"e2e-{name}", "lesson", [(m, o, {}) for m, o in questions])
    _open(page, live_server, name, unit)


def _quiz(page, live_server, name, multiple, options, max_attempts=3):
    user = _user(name, platform_admin=False)
    kwargs = attempts(max_attempts)
    unit = _seed(user, f"e2e-{name}", "quiz", [(multiple, options, kwargs)])
    _open(page, live_server, name, unit)


def _question(page, index=0):
    return page.locator("[data-question]").nth(index)


def _card(question, index):
    return question.locator(".question__choice").nth(index)


def _input(question, index):
    return _card(question, index).locator("input")


def _check(question):
    question.locator(CHECK).click()


def _css(locator, prop):
    return locator.evaluate("(el, p) => getComputedStyle(el)[p]", prop)


def _resolve(page, value):
    """A CSS colour as this page's browser computes it."""
    return page.evaluate(
        "(v) => { const p = document.createElement('i');"
        " p.style.forcedColorAdjust = 'none'; p.style.color = v;"
        " document.body.append(p); const c = getComputedStyle(p).color;"
        " p.remove(); return c; }",
        value,
    )


def _token(page, name):
    return _resolve(page, f"var({name})")


def _assert_card(page, card, line, fill, *, inset, style="solid"):
    colour = _token(page, line)
    assert _css(card, "borderTopWidth") == "1px"
    assert _css(card, "borderTopStyle") == style
    assert _css(card, "borderTopColor") == colour
    assert _css(card, "backgroundColor") == _token(page, fill)
    shadow = _css(card, "boxShadow")
    if inset:
        assert "inset" in shadow and colour in shadow, shadow
    else:
        assert shadow == "none"


def _assert_marker(page, card, glyph, token):
    marker = card.locator(".question__choice-marker")
    assert marker.text_content().strip() == glyph
    assert _css(marker, "color") == _token(page, token)


def _assert_text_ink(page, card):
    text = card.locator(".question__choice-text")
    assert _css(text, "color") == _token(page, "--text-primary")
    assert _css(text, "fontWeight") == "400"


def test_no_visible_input_and_thin_outline(page, live_server):
    _lesson(page, live_server, "cc_outline", (False, _options(3)))
    q = _question(page)
    box = _input(q, 0).bounding_box()
    assert (box["width"], box["height"]) == (1, 1)
    assert _css(_input(q, 0), "clip") == "rect(0px, 0px, 0px, 0px)"
    card = _card(q, 0)
    assert _css(card, "borderTopWidth") == "1px"
    assert _css(card, "borderTopStyle") == "solid"
    assert _css(card, "borderTopColor") == _token(page, "--border-strong")


def test_click_selects_and_paints_picked(page, live_server):
    _lesson(page, live_server, "cc_pick", (False, _options(3)))
    q = _question(page)
    pick(_input(q, 0))
    assert "inset" in _css(_card(q, 0), "boxShadow")
    assert _css(_card(q, 0), "backgroundColor") == _token(page, "--primary-subtle")
    assert _css(_card(q, 0), "borderTopColor") == _token(page, "--primary")

    pick(_input(q, 1))
    expect(q.locator("input:checked")).to_have_count(1)
    assert _input(q, 1).is_checked()
    assert _css(_card(q, 0), "boxShadow") == "none"


def test_untick_returns_to_unpicked_look(page, live_server):
    _lesson(page, live_server, "cc_untick", (True, _options(3)))
    q = _question(page)
    pick(_input(q, 0))
    pick(_input(q, 0))
    assert not _input(q, 0).is_checked()
    page.mouse.move(0, 0)
    card = _card(q, 0)
    assert _css(card, "borderTopColor") == _token(page, "--border-strong")
    assert _css(card, "backgroundColor") == TRANSPARENT
    assert _css(card, "boxShadow") == "none"


def _tab_to(page, target):
    for _ in range(60):
        page.keyboard.press("Tab")
        if target.evaluate("el => el === document.activeElement"):
            return
    pytest.fail("Tab never reached the option group")


def test_keyboard_changes_pick_and_shows_ring(page, live_server):
    _lesson(page, live_server, "cc_keys", (False, _options(3)))
    q = _question(page)
    _tab_to(page, _input(q, 0))

    page.keyboard.press("ArrowDown")
    assert _input(q, 1).is_checked()
    card = _card(q, 1)
    assert _css(card, "outlineWidth") == "2px"
    assert _css(card, "outlineStyle") == "solid"
    assert _css(card, "outlineColor") == _token(page, "--primary")
    assert _css(card, "outlineOffset") == "2px"


def test_submitted_values_unchanged(page, live_server):
    _lesson(page, live_server, "cc_submit", (True, _options(4, correct=(0, 1))))
    q = _question(page)
    picks = [_input(q, 0), _input(q, 3)]
    expected = {box.get_attribute("value") for box in picks}
    for box in picks:
        pick(box)

    with page.expect_request(lambda r: r.method == "POST") as posted:
        _check(q)
    body = posted.value.post_data_buffer.decode("utf-8")
    sent = set(re.findall(r'name="choice"\r\n\r\n(\d+)', body))
    assert sent == expected, body


def test_after_check_colours_quiz(page, live_server):
    options = [
        ("Right picked", True, ""),
        ("Right missed", True, ""),
        ("Wrong picked", False, ""),
        ("Wrong left", False, ""),
    ]
    _quiz(page, live_server, "cc_quiz", True, options, max_attempts=1)
    q = _question(page)
    pick(_input(q, 0))
    pick(_input(q, 2))
    _check(q)
    q.locator(".question__choice--missed").wait_for(timeout=6000)

    _assert_card(page, _card(q, 0), "--success", "--success-subtle", inset=True)
    _assert_marker(page, _card(q, 0), TICK, "--success")
    _assert_card(page, _card(q, 2), "--danger", "--danger-subtle", inset=True)
    _assert_marker(page, _card(q, 2), CROSS, "--danger")
    _assert_card(
        page, _card(q, 1), "--warning", "--warning-subtle", inset=False, style="dashed"
    )
    _assert_marker(page, _card(q, 1), PLUS, "--tc-orange")
    for index in (0, 1, 2):
        _assert_text_ink(page, _card(q, index))

    # A click on a locked card changes nothing. force=True only because a disabled
    # input makes Playwright refuse the click; this does not prove clickability.
    before = [_input(q, i).is_checked() for i in range(4)]
    q.locator(".question__choice-text").nth(3).click(force=True)
    assert [_input(q, i).is_checked() for i in range(4)] == before


def test_after_check_colours_lesson(page, live_server):
    _lesson(
        page,
        live_server,
        "cc_lesson",
        (True, _options(3, correct=(0, 1))),
        (False, _options(3)),
    )
    solved, wrong = _question(page, 0), _question(page, 1)
    pick(_input(solved, 0))
    pick(_input(solved, 1))
    _check(solved)
    solved.locator(".question__verdict.is-correct").wait_for(timeout=6000)
    _assert_card(page, _card(solved, 0), "--success", "--success-subtle", inset=True)
    _assert_marker(page, _card(solved, 0), TICK, "--success")

    pick(_input(wrong, 1))
    _check(wrong)
    wrong.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    _assert_card(page, _card(wrong, 1), "--danger", "--danger-subtle", inset=True)
    _assert_marker(page, _card(wrong, 1), CROSS, "--danger")


def test_matrix_pick_amber_and_unpick_red(page, live_server):
    _lesson(page, live_server, "cc_matrix", (True, MATRIX))
    q = _question(page)
    pick(_input(q, C))
    _check(q)
    q.locator(".question__choice--missed").wait_for(timeout=6000)

    pick(_input(q, A))
    pick(_input(q, C))
    assert _input(q, A).is_checked() and not _input(q, C).is_checked()
    page.mouse.move(0, 0)
    _assert_card(page, _card(q, A), "--warning", "--warning-subtle", inset=True)
    _assert_card(page, _card(q, C), "--danger", "--danger-subtle", inset=False)


def test_lesson_verdict_survives_reload(page, live_server):
    _lesson(page, live_server, "cc_reload", (False, _options(3)))
    q = _question(page)
    pick(_input(q, 0))
    _check(q)
    q.locator(".question__verdict.is-correct").wait_for(timeout=6000)

    page.reload()
    page.wait_for_selector("[data-question]")
    q = _question(page)
    assert _input(q, 0).is_checked()
    _assert_card(page, _card(q, 0), "--success", "--success-subtle", inset=True)


def test_hover_outlines_a_live_card(page, live_server):
    _lesson(page, live_server, "cc_hover", (False, _options(3)))
    q = _question(page)
    _card(q, 1).hover()
    assert _css(_card(q, 1), "borderTopColor") == _token(page, "--primary")


def test_hover_leaves_verdict_and_locked_cards_unchanged(page, live_server):
    _lesson(page, live_server, "cc_hoverv", (True, MATRIX), (False, _options(2)))
    live, solved = _question(page, 0), _question(page, 1)
    pick(_input(live, C))
    _check(live)
    live.locator(".question__choice--wrong").wait_for(timeout=6000)
    pick(_input(solved, 0))
    _check(solved)
    solved.locator(".question__verdict.is-correct").wait_for(timeout=6000)
    # The verdict card holds a live input; the locked card has no verdict class.
    pick(_input(live, C))
    assert not _input(live, C).is_checked()
    assert _input(solved, 1).is_disabled()

    for card in (_card(live, C), _card(solved, 1)):
        page.mouse.move(0, 0)
        before = _css(card, "borderTopColor")
        card.hover()
        assert _css(card, "borderTopColor") == before


def test_marker_sits_on_first_line_above_feedback(page, live_server):
    page.set_viewport_size({"width": 640, "height": 800})
    long_text = "Long distractor text that wraps. " * 14
    options = [("A", True, ""), (long_text.strip(), False, "trap note")]
    _lesson(page, live_server, "cc_marker", (True, options))
    q = _question(page)
    pick(_input(q, 1))
    _check(q)
    q.locator(".question__choice--wrong").wait_for(timeout=6000)

    card = _card(q, 1).bounding_box()
    marker = _card(q, 1).locator(".question__choice-marker").bounding_box()
    text = _card(q, 1).locator(".question__choice-text").bounding_box()
    note = _card(q, 1).locator(".question__choice-feedback").bounding_box()
    assert text["height"] > 2 * marker["height"], "the fixture must wrap"
    assert abs(marker["y"] - (card["y"] + 10)) <= 3, (marker, card)
    assert marker["y"] + marker["height"] <= note["y"]
    assert marker["x"] + marker["width"] <= card["x"] + card["width"]
    assert marker["x"] >= text["x"] + text["width"] - 1


def test_wide_maths_stays_in_card_at_360(page, live_server):
    page.set_viewport_size({"width": 360, "height": 740})
    options = [
        (WIDE_INLINE, False, ""),
        (WIDE_DISPLAY, False, ""),
        (r"Normal \(x^2\) text", True, ""),
    ]
    _lesson(page, live_server, "cc_wide", (False, options))
    q = _question(page)
    pick(_input(q, 0))
    _check(q)
    q.locator(".question__choice--wrong").wait_for(timeout=6000)
    expect(q.locator(".question__choice-text .katex")).to_have_count(3)

    for index in range(3):
        card = _card(q, index).bounding_box()
        text = _card(q, index).locator(".question__choice-text").bounding_box()
        assert card["x"] + card["width"] <= 360
        assert text["x"] >= card["x"]
        assert text["x"] + text["width"] <= card["x"] + card["width"] + 0.5
    box = _card(q, 0).bounding_box()
    marker = _card(q, 0).locator(".question__choice-marker").bounding_box()
    assert box["x"] <= marker["x"]
    assert marker["x"] + marker["width"] <= box["x"] + box["width"]

    wide = _card(q, 0).locator(".question__choice-text")
    assert wide.evaluate("el => el.scrollWidth > el.clientWidth"), "must scroll"
    normal = _card(q, 2).locator(".question__choice-text")
    assert normal.evaluate("el => el.scrollHeight <= el.clientHeight")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "the page scrolls sideways"
    )


def test_forced_colors_picked_differs(browser, live_server):
    ctx = browser.new_context(forced_colors="active")
    page = ctx.new_page()
    _lesson(page, live_server, "cc_forced", (False, _options(3)))
    q = _question(page)
    pick(_input(q, 1))
    assert _css(_card(q, 1), "backgroundColor") != _css(_card(q, 0), "backgroundColor")
    assert _css(_card(q, 1), "borderTopColor") != _css(_card(q, 0), "borderTopColor")

    _check(q)
    q.locator(".question__choice--wrong").wait_for(timeout=6000)
    highlight_text = _resolve(page, "HighlightText")
    card = _card(q, 1)
    assert _css(card.locator(".question__choice-marker"), "color") == highlight_text
    assert _css(card.locator(".question__choice-text"), "color") == highlight_text
    ctx.close()


def test_dark_and_custom_brand_resolve_from_tokens(page, live_server):
    from core.services import invalidate_site_config
    from institution.models import Institution

    custom = "#AA2288"
    custom_rgb = "rgb(170, 34, 136)"
    Institution.load().brand_colors.update_or_create(
        key="primary", defaults={"value": custom}
    )
    invalidate_site_config()
    try:
        _lesson(page, live_server, "cc_brand", (False, _options(3)))
        q = _question(page)
        pick(_input(q, 0))
        card = _card(q, 0)

        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        assert _css(card, "borderTopColor") == _token(page, "--primary")
        assert _css(card, "borderTopColor") != custom_rgb

        page.evaluate("document.documentElement.dataset.theme = 'light'")
        assert _css(card, "borderTopColor") == custom_rgb
    finally:
        # The bundle is cached per process and outlives this test's rows.
        invalidate_site_config()


def test_print_keeps_outlines_and_tints(page, live_server):
    options = list(MATRIX)
    options[C] = ("C", False, WIDE_INLINE)
    options[D] = (WIDE_INLINE, False, "")
    _lesson(page, live_server, "cc_print", (True, options))
    q = _question(page)
    pick(_input(q, C))
    _check(q)
    q.locator(".question__choice--wrong").wait_for(timeout=6000)
    pick(_input(q, D))  # a Picked card with no verdict class

    page.emulate_media(media="print")
    for index in (C, D):
        card = _card(q, index)
        assert _css(card, "borderTopWidth") == "1px"
        assert _css(card, "borderTopStyle") == "solid"
        assert _css(card, "backgroundColor") != TRANSPARENT
        assert _css(card, "webkitPrintColorAdjust") == "exact"
    for index in range(4):
        assert _css(_card(q, index), "breakInside") == "avoid"
    assert _css(_card(q, D).locator(".question__choice-text"), "overflowX") == "visible"
    note = _card(q, C).locator(".question__choice-feedback")
    assert _css(note, "overflowX") == "visible"


def test_print_drops_the_focus_ring_from_a_card(page, live_server):
    _lesson(page, live_server, "cc_printring", (False, _options(3)))
    q = _question(page)
    _tab_to(page, _input(q, 0))
    card = _card(q, 0)
    assert _css(card, "outlineStyle") == "solid"

    page.emulate_media(media="print")
    assert _css(card, "outlineStyle") == "none"


def test_forced_colors_hovered_pick_keeps_highlight_border(browser, live_server):
    ctx = browser.new_context(forced_colors="active")
    page = ctx.new_page()
    _lesson(page, live_server, "cc_forcedhover", (False, _options(3)))
    q = _question(page)
    pick(_input(q, 1))
    card = _card(q, 1)
    card.hover()
    assert card.evaluate("el => el.matches(':hover')")
    assert _css(card, "borderTopColor") == _resolve(page, "Highlight")
    ctx.close()


def _assert_hint(page, question):
    hint = question.locator(".question__hint")
    assert _css(hint, "fontSize") == "14px"
    assert _css(hint, "color") == _token(page, "--text-secondary")
    gap = hint.evaluate(
        "el => el.getBoundingClientRect().top"
        " - el.previousElementSibling.getBoundingClientRect().bottom"
    )
    assert gap == pytest.approx(4, abs=0.5)


def test_hint_style_in_a_question_and_on_results(page, live_server):
    _quiz(page, live_server, "cc_hint", True, _options(3))
    _assert_hint(page, _question(page))

    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=8000)
    _assert_hint(page, page.locator(".quiz-results__item").first)
