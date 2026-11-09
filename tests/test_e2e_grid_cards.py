"""e2e: grid questions as rows of outlined buttons (spec 2026-11-09 §3.4).

Colours are compared with the token as the browser resolves it, so neither the brand
colour nor the theme is hard-coded here. Layout assertions read real boxes.
"""

import os

import pytest
from playwright.sync_api import expect

from tests.e2e_pick import pick
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_verified_user
from tests.test_e2e_choice_cards import TRANSPARENT
from tests.test_e2e_choice_cards import WIDE_INLINE
from tests.test_e2e_choice_cards import _css
from tests.test_e2e_choice_cards import _login
from tests.test_e2e_choice_cards import _resolve
from tests.test_e2e_choice_cards import _token

pytestmark = pytest.mark.e2e

CHECK = "button[type='submit']:not([name='reveal'])"
KINDS = ["choicegrid", "multigrid"]
ROLE = {"choicegrid": "radio", "multigrid": "checkbox"}
DESKTOP = {"width": 1280, "height": 900}
LONG_LABELS = (
    "Strongly agree",
    "Agree",
    "Neither agree nor disagree",
    "Disagree",
    "Strongly disagree",
)
# Wider than the phone column on one line.
SENTENCE_LABEL = "This column label is a whole sentence that has to wrap on a phone"
FRACTION = r"Half is \(\dfrac{1}{2}\) of one"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _unit(username, unit_type="lesson"):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=f"e2e-{username}".replace("_", "-"), owner=user)
    Enrollment.objects.get_or_create(student=user, course=course)
    return ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="U"
    )


def _grid(kind, columns, statements, **kwargs):
    """The first column is the correct one in every row."""
    from courses.models import ChoiceGridQuestionElement
    from courses.models import GridColumn
    from courses.models import GridRow
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow

    if kind == "choicegrid":
        q = ChoiceGridQuestionElement.objects.create(stem="<p>Grid.</p>", **kwargs)
        cols = [
            GridColumn.objects.create(question=q, order=i, label=label)
            for i, label in enumerate(columns)
        ]
        for i, statement in enumerate(statements):
            GridRow.objects.create(
                question=q, order=i, statement=statement, correct_column=cols[0]
            )
        return q
    q = MultiGridQuestionElement.objects.create(stem="<p>Grid.</p>", **kwargs)
    cols = [
        MultiGridColumn.objects.create(question=q, order=i, label=label)
        for i, label in enumerate(columns)
    ]
    for i, statement in enumerate(statements):
        row = MultiGridRow.objects.create(question=q, order=i, statement=statement)
        row.correct_columns.add(cols[0])
    return q


def _open(page, live_server, username, unit):
    _login(page, live_server, username)
    suffix = "quiz/" if unit.unit_type == "quiz" else ""
    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/{suffix}")
    page.wait_for_selector("[data-question]")
    return page.locator("[data-question]").first


def _lesson(
    page,
    live_server,
    name,
    kind="choicegrid",
    columns=("Yes", "No"),
    statements=("Alpha", "Beta", "Gamma"),
    viewport=DESKTOP,
):
    page.set_viewport_size(viewport)
    unit = _unit(name)
    add_element(unit, _grid(kind, columns, statements, **attempts(0)))
    return _open(page, live_server, name, unit)


def _rows(q):
    return q.locator("[data-answer-yours] tbody tr")


def _input(q, row, column):
    return _rows(q).nth(row).locator("input").nth(column)


def _btn(q, row, column):
    return _rows(q).nth(row).locator(".gridbtn").nth(column)


def _stmt(q, row):
    return _rows(q).nth(row).locator("td").first


def _text(q, row):
    return _rows(q).nth(row).locator(".grid-stmt-text")


def _check_answers(q):
    q.locator(CHECK).click()
    q.locator(".grid-verdict").first.wait_for(timeout=6000)


def _answer_wrong(page, q, row=1):
    """A wrong pick in `row`, right picks above it; leaves the row painted and live."""
    for earlier in range(row):
        pick(_input(q, earlier, 0))
    pick(_input(q, row, 1))
    _check_answers(q)
    assert "is-incorrect" in _rows(q).nth(row).get_attribute("class")
    assert not _input(q, row, 1).is_disabled()
    page.mouse.move(0, 0)


def _bottom(box):
    return box["y"] + box["height"]


def _right(box):
    return box["x"] + box["width"]


def _wrapper(q, kind):
    return q.locator(f"[data-answer-yours] .{kind}-scroll")


def _assert_stacked_and_contained(page, q, kind):
    wrapper = _wrapper(q, kind)
    edge = _right(wrapper.bounding_box())
    for r in range(_rows(q).count()):
        statement = _bottom(_stmt(q, r).bounding_box())
        buttons = _rows(q).nth(r).locator(".gridbtn")
        for b in range(buttons.count()):
            box = buttons.nth(b).bounding_box()
            assert box["y"] >= statement - 0.5, (r, b, box, statement)
            assert _right(box) <= edge + 0.5, (r, b, box, edge)
    assert wrapper.evaluate("el => el.scrollWidth - el.clientWidth") <= 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_hover_outlines_a_live_button(page, live_server):
    q = _lesson(page, live_server, "gc_hover")
    button = _btn(q, 0, 1)
    assert _css(button, "borderTopColor") != _token(page, "--primary")
    button.hover()
    assert _css(button, "borderTopColor") == _token(page, "--primary")


def test_hover_leaves_painted_button_unchanged(page, live_server):
    q = _lesson(page, live_server, "gc_hoverp")
    _answer_wrong(page, q)
    painted = _btn(q, 1, 1)
    before = _css(painted, "borderTopColor")
    assert before == _token(page, "--danger")
    painted.hover()
    assert _css(painted, "borderTopColor") == before


def test_gridbtn_picks_and_paints(page, live_server):
    q = _lesson(page, live_server, "gc_pick")
    first, second = _btn(q, 0, 0), _btn(q, 0, 1)
    assert _css(first, "borderTopWidth") == "1px"
    assert _css(first, "borderTopColor") == _token(page, "--border-strong")
    assert _css(first, "color") == _token(page, "--text-secondary")
    assert _css(first, "backgroundColor") == TRANSPARENT
    assert _css(first, "fontWeight") == "400"

    pick(_input(q, 0, 0))
    assert _input(q, 0, 0).is_checked()
    page.mouse.move(0, 0)
    assert _css(first, "borderTopWidth") == "1px"
    assert _css(first, "borderTopColor") == _token(page, "--primary")
    assert _css(first, "backgroundColor") == _token(page, "--primary-subtle")
    assert _css(first, "color") == _token(page, "--text-primary")
    assert _css(first, "fontWeight") == "400"
    shadow = _css(first, "boxShadow")
    assert "inset" in shadow and _token(page, "--primary") in shadow, shadow

    pick(_input(q, 0, 1))
    page.mouse.move(0, 0)
    expect(_rows(q).nth(0).locator("input:checked")).to_have_count(1)
    assert _css(first, "boxShadow") == "none"
    assert _css(first, "borderTopColor") == _token(page, "--border-strong")
    assert _css(second, "borderTopColor") == _token(page, "--primary")


def test_keyboard_and_ring_on_gridbtn(page, live_server):
    q = _lesson(page, live_server, "gc_keys")
    on_first = "el => el === document.activeElement"
    for _ in range(60):
        page.keyboard.press("Tab")
        if _input(q, 0, 0).evaluate(on_first):
            break
    else:
        pytest.fail("Tab never reached the first row")

    page.keyboard.press("Space")
    assert _input(q, 0, 0).is_checked()
    page.keyboard.press("ArrowRight")
    assert _input(q, 0, 1).is_checked()
    button = _btn(q, 0, 1)
    assert _css(button, "outlineWidth") == "2px"
    assert _css(button, "outlineStyle") == "solid"
    assert _css(button, "outlineColor") == _token(page, "--primary")
    assert _css(button, "outlineOffset") == "2px"


def test_grid_answers_stays_transparent(page, live_server):
    q = _lesson(page, live_server, "gc_clear")
    pick(_input(q, 0, 0))
    page.mouse.move(0, 0)
    row = _rows(q).nth(0)
    assert _css(row.locator(".grid-answers-cell"), "backgroundColor") == TRANSPARENT
    assert _css(row.locator(".grid-answers"), "backgroundColor") == TRANSPARENT


@pytest.mark.parametrize("kind", KINDS)
def test_accessibility_tree(page, live_server, kind):
    q = _lesson(page, live_server, f"gc_a11y_{kind}", kind=kind)
    group = q.get_by_role("group", name="Alpha", exact=True)
    expect(group).to_have_count(1)
    expect(group.get_by_role(ROLE[kind], name="Yes", exact=True)).to_have_count(1)
    expect(group.get_by_role(ROLE[kind], name="No", exact=True)).to_have_count(1)

    _answer_wrong(page, q)
    painted = q.locator("[data-answer-yours]").get_by_role("group", name="Beta")
    expect(painted).to_have_count(1)
    expect(painted.get_by_role(ROLE[kind], name="No", exact=True)).to_have_count(1)


def test_live_painted_grid_new_pick_is_primary(page, live_server):
    q = _lesson(page, live_server, "gc_repick")
    _answer_wrong(page, q)
    pick(_input(q, 1, 0))
    page.mouse.move(0, 0)
    assert _input(q, 1, 0).is_checked()
    assert "is-incorrect" in _rows(q).nth(1).get_attribute("class")

    button = _btn(q, 1, 0)
    primary = _token(page, "--primary")
    danger = _token(page, "--danger")
    assert _css(button, "borderTopColor") == primary
    assert _css(button, "backgroundColor") == _token(page, "--primary-subtle")
    shadow = _css(button, "boxShadow")
    assert primary in shadow, shadow
    for prop in ("borderTopColor", "backgroundColor", "boxShadow", "color"):
        assert danger not in _css(button, prop), prop


def test_desktop_rhythm(page, live_server):
    q = _lesson(page, live_server, "gc_rhythm")
    upper = _btn(q, 0, 0).bounding_box()
    lower = _btn(q, 1, 0).bounding_box()
    assert round(lower["y"] - _bottom(upper), 2) == 6, (upper, lower)

    statement = _stmt(q, 0).bounding_box()
    assert abs(_bottom(statement) - _bottom(upper)) <= 4, (statement, upper)
    assert _right(statement) <= upper["x"], (statement, upper)
    assert upper["y"] < _bottom(statement), (statement, upper)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("width", [360, 860])
def test_stacked_at_360_and_mid_width(page, live_server, kind, width):
    viewport = {"width": width, "height": 900}
    q = _lesson(
        page,
        live_server,
        f"gc_stack_{kind}_{width}",
        kind=kind,
        columns=LONG_LABELS,
        viewport=viewport,
    )
    if width > 640:
        # The width this case is about: one button fits beside the 16rem statement
        # basis, and the whole run does not.
        room = _wrapper(q, kind).evaluate("el => el.clientWidth")
        widths = [_btn(q, 0, i).bounding_box()["width"] for i in range(5)]
        assert 256 + widths[0] + 8 <= room < 256 + sum(widths), (room, widths)
    _assert_stacked_and_contained(page, q, kind)


def test_stacked_rhythm_at_360(page, live_server):
    q = _lesson(page, live_server, "gc_srhythm", viewport={"width": 360, "height": 800})
    own = _btn(q, 0, 0).bounding_box()["y"] - _bottom(_text(q, 0).bounding_box())
    next_statement = _text(q, 1).bounding_box()["y"]
    gap_to_next = next_statement - _bottom(_btn(q, 0, 0).bounding_box())
    assert gap_to_next > own, (gap_to_next, own)


@pytest.mark.parametrize("kind", KINDS)
# 630 is the case the phone rule decides: at 390 the 16rem statement basis and the
# two buttons do not fit on one line anyway, and at 630 they do.
@pytest.mark.parametrize("width", [390, 630])
def test_short_labels_stack_at_390(page, live_server, kind, width):
    q = _lesson(
        page,
        live_server,
        f"gc_short_{kind}_{width}",
        kind=kind,
        columns=("P", "F"),
        viewport={"width": width, "height": 800},
    )
    _assert_stacked_and_contained(page, q, kind)


def test_long_label_wraps_at_360(page, live_server):
    q = _lesson(
        page,
        live_server,
        "gc_wrap",
        columns=(SENTENCE_LABEL, "No"),
        viewport={"width": 360, "height": 800},
    )
    long_button = _btn(q, 0, 0).bounding_box()
    short_button = _btn(q, 0, 1).bounding_box()
    assert long_button["height"] > 1.7 * short_button["height"], (
        long_button,
        short_button,
    )
    _assert_stacked_and_contained(page, q, "choicegrid")


def test_wide_statement_formula(page, live_server):
    q = _lesson(page, live_server, "gc_wide", statements=(WIDE_INLINE, "Beta"))
    q.locator(".grid-stmt-text .katex").wait_for()
    assert _right(_text(q, 0).bounding_box()) <= _btn(q, 0, 0).bounding_box()["x"]
    assert _text(q, 0).evaluate("el => el.scrollWidth > el.clientWidth")

    page.set_viewport_size({"width": 360, "height": 800})
    _answer_wrong(page, q, row=0)
    q.locator(".grid-stmt-text .katex").wait_for()
    wrapper = _wrapper(q, "choicegrid")
    assert wrapper.evaluate("el => el.scrollWidth <= el.clientWidth")
    assert _text(q, 0).evaluate("el => el.scrollWidth > el.clientWidth")
    box = wrapper.bounding_box()
    for b in range(2):
        assert _right(_btn(q, 0, b).bounding_box()) <= _right(box) + 0.5
    verdict = _rows(q).nth(0).locator(".grid-verdict").bounding_box()
    assert verdict["x"] >= box["x"] and _right(verdict) <= _right(box) + 0.5, verdict


def test_fraction_statement_no_vertical_scroll(page, live_server):
    q = _lesson(page, live_server, "gc_frac", statements=("Alpha", FRACTION))
    q.locator(".grid-stmt-text .katex").wait_for()
    excess = "el => el.scrollHeight - el.clientHeight"
    assert _wrapper(q, "choicegrid").evaluate(excess) <= 0
    # 3px: KaTeX overhang the 4px padding absorbs; a pixel diff found nothing clipped.
    assert _text(q, 1).evaluate(excess) <= 3
    assert _css(_text(q, 1), "overflowY") == "hidden"

    # A/B: without that padding the same measure exceeds the 3px bound.
    page.add_style_tag(content=".grid-stmt-text { padding-block: 0 !important; }")
    assert _text(q, 1).evaluate(excess) > 3


def test_click_on_formula_label_selects(page, live_server):
    q = _lesson(page, live_server, "gc_fclick", columns=(r"\(x^2\)", r"\(y^2\)"))
    formula = _btn(q, 0, 0).locator(".katex")
    formula.wait_for()
    box = formula.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    assert _input(q, 0, 0).is_checked()


def test_grid_in_two_columns_does_not_overflow(page, live_server):
    from courses.models import Element
    from courses.models import TwoColumnElement

    page.set_viewport_size(DESKTOP)
    unit = _unit("gc_twocol")
    container = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    join = add_element(unit, container)
    Element.objects.create(
        unit=unit,
        content_object=_grid(
            "choicegrid", LONG_LABELS, ("Alpha", "Beta"), **attempts(0)
        ),
        parent=join,
        tab_id=container.data["columns"][0]["id"],
    )
    q = _open(page, live_server, "gc_twocol", unit)

    column = q.locator("xpath=ancestor::div[contains(@class, 'twocolumn__column')]")
    edge = _right(column.bounding_box())
    assert _right(_rows(q).nth(0).locator(".grid-answers").bounding_box()) <= edge + 0.5
    boxes = [_btn(q, 0, i).bounding_box() for i in range(5)]
    assert len({round(b["y"]) for b in boxes}) > 1, boxes
    single_line = min(b["height"] for b in boxes)
    assert single_line < 40, boxes
    for box in boxes:
        assert box["height"] <= single_line + 1, boxes


def test_forced_colors_painted_button(browser, live_server):
    context = browser.new_context(forced_colors="active")
    page = context.new_page()
    q = _lesson(page, live_server, "gc_forced")
    pick(_input(q, 0, 0))
    page.mouse.move(0, 0)
    picked, unpicked = _btn(q, 0, 0), _btn(q, 0, 1)
    assert _css(picked, "backgroundColor") != _css(unpicked, "backgroundColor")
    assert _css(picked, "borderTopColor") != _css(unpicked, "borderTopColor")

    pick(_input(q, 1, 1))
    _check_answers(q)
    page.mouse.move(0, 0)
    assert "is-incorrect" in _rows(q).nth(1).get_attribute("class")
    painted = _btn(q, 1, 1)
    assert _css(painted, "backgroundColor") == _resolve(page, "Highlight")
    assert _css(painted, "color") == _resolve(page, "HighlightText")
    context.close()


def test_print_grid(page, live_server):
    q = _lesson(page, live_server, "gc_print")
    _answer_wrong(page, q)
    pick(_input(q, 2, 0))  # a plain Picked button beside the painted one
    page.mouse.move(0, 0)

    page.emulate_media(media="print")
    for button in (_btn(q, 1, 0), _btn(q, 1, 1), _btn(q, 2, 0)):
        assert _css(button, "borderTopWidth") == "1px"
        assert _css(button, "borderTopStyle") == "solid"
    for picked in (_btn(q, 1, 1), _btn(q, 2, 0)):
        assert _css(picked, "backgroundColor") != TRANSPARENT
        assert _css(picked, "webkitPrintColorAdjust") == "exact"
    for r in range(3):
        assert _css(_rows(q).nth(r), "breakInside") == "avoid"
        assert _css(_text(q, r), "overflowX") == "visible"
