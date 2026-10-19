"""Playwright e2e: the outline's part cards, depth-1 rows, status rings and type
scale (spec §3.2, §3.4, §3.5, §3.8). Geometry and computed style are read from the
live layout at phone (360/412), tablet (700) and desktop (1280) widths, with the
Polish UI where the longest labels matter. Marked e2e (run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

NO_HSCROLL = (
    "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
)

# Step 1b baseline: the resume card's quiz chip, computed on the Task 5 build
# (56cd8942), whose chip rules are byte-identical to master d5c2f52a's
# (`.badge` + `.unit-kind-chip`, neither touched by this branch before Task 6).
RESUME_CHIP_BASELINE = {
    "light": {"color": "rgb(90, 84, 74)", "transform": "none"},
    "dark": {"color": "rgb(189, 182, 168)", "transform": "none"},
}


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# --- seeding -----------------------------------------------------------------


def _build(username, spec):
    """Seed an enrolled student and a course from a small tree spec.

    A container is ``(kind, title, [children])``; a unit is ``(unit_type, title)``
    or ``(unit_type, title, opts)`` with opts keys ``completed`` (a completed
    UnitProgress), ``state`` (saved practice work) and ``optional`` (a
    non-obligatory lesson). Returns (user, course, {title: node}).
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
    nodes = {}

    def add(item, parent):
        if item[0] in ("part", "chapter", "section"):
            kind, title, children = item
            node = ContentNodeFactory(
                course=course, kind=kind, unit_type=None, parent=parent, title=title
            )
            nodes[title] = node
            for child in children:
                add(child, node)
            return
        unit_type, title = item[0], item[1]
        opts = item[2] if len(item) > 2 else {}
        extra = {"obligatory": False} if opts.get("optional") else {}
        node = ContentNodeFactory(
            course=course,
            kind="unit",
            unit_type=unit_type,
            parent=parent,
            title=title,
            **extra,
        )
        nodes[title] = node
        if opts.get("completed") or opts.get("state"):
            UnitProgress.objects.create(
                student=user,
                unit=node,
                completed=bool(opts.get("completed")),
                element_state={"1": {"items": []}} if opts.get("state") else {},
            )

    for item in spec:
        add(item, None)
    return user, course, nodes


def _open(page, live_server, username, slug, width, *, fragment=""):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login" not in url)
    page.goto(f"{live_server.url}/courses/{slug}/")
    # The header switch POSTs the UI language and reloads; Polish has the
    # longest labels ("0 z 100 lekcji", "Zacznij od nowa").
    page.locator("form.lang-switch button[value='pl']").first.click()
    expect(page.locator(".outline__results")).to_contain_text("Moje wyniki")
    if fragment:
        page.goto(f"{live_server.url}/courses/{slug}/{fragment}")


def _expand_all(page):
    toggle = page.locator("[data-outline-toggle-all]")
    expect(toggle).to_be_visible()
    toggle.click()
    expect(toggle).to_have_text("Zwiń wszystko")


# --- geometry ----------------------------------------------------------------


def _box(page, selector):
    box = page.locator(selector).bounding_box()
    assert box is not None, selector
    return box


def _bottom(box):
    return box["y"] + box["height"]


def _right(box):
    return box["x"] + box["width"]


def _overlap_v(a, b):
    return a["y"] < _bottom(b) and b["y"] < _bottom(a)


def _head(pk):
    return f"[data-node='{pk}'] > summary"


def _style(page, selector, prop):
    return page.evaluate(
        "([sel, prop]) => getComputedStyle(document.querySelector(sel))[prop]",
        [selector, prop],
    )


def _line_height(page, selector):
    return float(_style(page, selector, "lineHeight").removesuffix("px"))


def _probe_colour(page, value):
    """A CSS colour value resolved to rgb(), on an element forced colours leave
    alone — so a system colour (CanvasText, Highlight) reads as what it paints."""
    return page.evaluate(
        "v => { const d = document.createElement('div');"
        "  d.style.cssText = 'forced-color-adjust:none;color:' + v;"
        "  document.body.appendChild(d);"
        "  const c = getComputedStyle(d).color; d.remove(); return c; }",
        value,
    )


def _three_parts(username, *, started=False, long_title=None):
    lesson = ("lesson", "Lekcja 1", {"state": True}) if started else ("lesson", "L1")
    first = long_title or "Zbiory liczbowe"
    return _build(
        username,
        [
            ("part", first, [("chapter", "Rozdział 1", [lesson, ("lesson", "L1b")])]),
            ("part", "Funkcje", [("chapter", "Rozdział 2", [("lesson", "L2")])]),
            ("part", "Ciągi", [("chapter", "Rozdział 3", [("lesson", "L3")])]),
        ],
    )


# --- phone -------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [360, 412])
def test_cards_fit_a_phone(page, live_server, width):
    """Phone card head: the title starts on the badge's line, right of it; the
    bar + count row sits below the title, inside the card, with a real width;
    every head and unit row is >= 44px tall (D7)."""
    _, course, n = _three_parts(
        f"cphone{width}", long_title="Zastosowania liczb rzeczywistych w praktyce"
    )
    _open(page, live_server, f"cphone{width}", course.slug, width)
    _expand_all(page)

    assert page.evaluate(NO_HSCROLL)
    for title in ("Zastosowania liczb rzeczywistych w praktyce", "Funkcje", "Ciągi"):
        pk = n[title].pk
        card = _box(page, f"#node-{pk}")
        badge = _box(page, f"{_head(pk)} .outline-card__num")
        name = _box(page, f"{_head(pk)} > .outline-node__title")
        meta = _box(page, f"{_head(pk)} .outline-card__meta")
        bar = _box(page, f"{_head(pk)} .outline-card__bar")
        assert name["x"] >= _right(badge) - 0.5, (title, badge, name)
        assert _overlap_v(badge, name), (title, badge, name)
        assert meta["y"] >= _bottom(name) - 0.5, (title, name, meta)
        assert bar["width"] > 0, (title, bar)
        assert bar["x"] >= card["x"] and _right(bar) <= _right(card), (card, bar)

    rows = page.locator(
        "summary.outline-node__head, div.outline-node__head, a.outline-unit"
    )
    heights = [b["height"] for b in (r.bounding_box() for r in rows.all()) if b]
    assert heights and min(heights) >= 44 - 0.5, heights


@pytest.mark.django_db(transaction=True)
def test_menu_space_is_reserved_only_where_a_menu_exists(page, live_server):
    """Spec §6 phone row. A menu-less card head reserves nothing: its chevron
    reaches the content-box edge AND its end padding equals its start padding
    (the second half is what reddens the drop-:has() mutant — a reservation on
    every head keeps the content-box half green). A card with a menu keeps its
    chevron >= 44px clear of the row end, and the "⋯" overlaps neither the
    chevron nor the count. Mutants: drop the :has() qualifier; delete the rule."""
    _, course, n = _three_parts("creserve", started=True)
    _open(page, live_server, "creserve", course.slug, 360)

    bare = n["Funkcje"].pk
    row = _box(page, _head(bare))
    chevron = _box(page, f"{_head(bare)} > .outline-node__chevron")
    pad_end = float(_style(page, _head(bare), "paddingRight").removesuffix("px"))
    pad_start = float(_style(page, _head(bare), "paddingLeft").removesuffix("px"))
    assert abs(_right(chevron) - (_right(row) - pad_end)) <= 2, (row, chevron, pad_end)
    assert pad_end == pad_start, (pad_start, pad_end)

    menu_pk = n["Zbiory liczbowe"].pk
    row = _box(page, _head(menu_pk))
    chevron = _box(page, f"{_head(menu_pk)} > .outline-node__chevron")
    count = _box(page, f"{_head(menu_pk)} .outline-card__countcell")
    menu = _box(page, f"#node-{menu_pk} > .outline-menu > summary")
    assert _right(chevron) <= _right(row) - 44, (row, chevron)
    for other in (chevron, count):
        overlaps = (
            menu["x"] < _right(other)
            and other["x"] < _right(menu)
            and _overlap_v(menu, other)
        )
        assert not overlaps, (menu, other)


@pytest.mark.django_db(transaction=True)
def test_long_count_stays_in_the_a11y_tree_on_a_phone(page, live_server):
    _, course, n = _three_parts("ca11y")
    _open(page, live_server, "ca11y", course.slug, 360)

    head = _head(n["Funkcje"].pk)
    long_sel = f"{head} .outline-count__long"
    assert _style(page, long_sel, "display") != "none"
    assert _box(page, long_sel)["width"] <= 1
    expect(page.locator(f"{head} .outline-count__short")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_row_short_count_is_visible_on_desktop(page, live_server):
    """Mutant: drop the card scope from the >= 641px short-count rule."""
    _, course, n = _three_parts("cdesk")
    _open(page, live_server, "cdesk", course.slug, 1280)

    card = _head(n["Funkcje"].pk)
    row = _head(n["Rozdział 2"].pk)
    expect(page.locator(f"{row} .outline-count__short")).to_be_visible()
    expect(page.locator(f"{card} .outline-count__short")).to_be_hidden()
    expect(page.locator(f"{card} .outline-count__long")).to_be_visible()
    expect(page.locator(f"{card} .outline-count__long")).to_have_text("0 z 1 lekcji")


def _rgb(css):
    """A computed colour -- rgb()/rgba() or Chrome's color(srgb ...) for color-mix
    -- as 0-255 floats."""
    import re

    nums = [float(x) for x in re.findall(r"[\d.]+", css)]
    if css.startswith("color("):
        return [v * 255 for v in nums[:3]]
    return nums[:3]


def _contrast(a, b):
    def lum(c):
        c = [v / 255 for v in c]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _row_with_chip(username):
    return _build(
        username,
        [
            (
                "part",
                "Zbiory liczbowe",
                [
                    (
                        "chapter",
                        "Liczby rzeczywiste i ich własności",
                        [
                            ("lesson", "L1"),
                            ("lesson", "L2"),
                            ("lesson", "Extra", {"optional": True, "completed": True}),
                        ],
                    )
                ],
            )
        ],
    )


@pytest.mark.django_db(transaction=True)
def test_empty_course_bar_track_is_visible(page, live_server):
    """A new student's course bar has no fill, so the track IS the bar. Mutant:
    put the track back on --border-subtle (1.08:1 on the light page)."""
    _, course, _ = _three_parts("cbartrack")
    _open(page, live_server, "cbartrack", course.slug, 1280)

    expect(page.locator(".outline__bar")).to_be_visible()
    track = _rgb(_style(page, ".outline__bar", "backgroundColor"))
    base = _rgb(_style(page, "body", "backgroundColor"))
    assert _contrast(track, base) >= 1.5, (track, base)


@pytest.mark.django_db(transaction=True)
def test_row_meta_drops_under_the_title_on_a_phone(page, live_server):
    """At 360px a row with a count AND "+1 dodatkowe" gave the title ~95px. The
    meta now takes its own line; the title keeps the row's width and the chevron
    its first line. Mutant: drop the phone grid rule for depth-1 heads."""
    _, course, n = _row_with_chip("crowmeta")
    _open(page, live_server, "crowmeta", course.slug, 360)

    head = _head(n["Liczby rzeczywiste i ich własności"].pk)
    title_sel = f"{head} > .outline-node__title"
    title = _box(page, title_sel)
    summary = _box(page, head)
    meta = _box(page, f"{head} > .outline-row__meta")
    chevron = _box(page, f"{head} > .outline-node__chevron")
    expect(page.locator(f"{head} .rollup--additional")).to_be_visible()
    assert title["width"] >= summary["width"] * 0.6, (title, summary)
    assert meta["y"] >= _bottom(title) - 1, (meta, title)
    assert abs(meta["x"] - title["x"]) <= 1, (meta, title)
    first_line = {"y": title["y"], "height": _line_height(page, title_sel)}
    assert _overlap_v(chevron, first_line), (chevron, first_line)
    assert page.evaluate(NO_HSCROLL)


@pytest.mark.django_db(transaction=True)
def test_row_meta_stays_beside_the_title_on_desktop(page, live_server):
    """Wide screens keep the one-line row: the wrapper is display: contents, so
    the count and chip sit on the title's line. Mutant: drop that base rule."""
    _, course, n = _row_with_chip("crowdesk")
    _open(page, live_server, "crowdesk", course.slug, 1280)

    head = _head(n["Liczby rzeczywiste i ich własności"].pk)
    assert _style(page, f"{head} > .outline-row__meta", "display") == "contents"
    title_sel = f"{head} > .outline-node__title"
    title = _box(page, title_sel)
    first_line = {"y": title["y"], "height": _line_height(page, title_sel)}
    chip = _box(page, f"{head} .rollup--additional")
    assert _overlap_v(chip, first_line), (chip, first_line)


# --- tablet ------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_all_quiz_card_head_is_one_row_on_a_tablet(page, live_server):
    """No meta row on an all-quiz card: no empty band, no row-gap."""
    _, course, n = _build(
        "cquiz",
        [
            (
                "part",
                "Powtórka",
                [("chapter", "Testy", [("quiz", "Q1"), ("quiz", "Q2")])],
            )
        ],
    )
    _open(page, live_server, "cquiz", course.slug, 700)

    head = _head(n["Powtórka"].pk)
    expect(page.locator(f"{head} .outline-card__meta")).to_have_count(0)
    badge = _box(page, f"{head} .outline-card__num")
    name = _box(page, f"{head} > .outline-node__title")
    chevron = _box(page, f"{head} > .outline-node__chevron")
    assert _overlap_v(badge, name) and _overlap_v(chevron, name), (badge, name, chevron)
    summary = _box(page, head)
    pads = sum(
        float(_style(page, head, p).removesuffix("px"))
        for p in ("paddingTop", "paddingBottom")
    )
    inner = summary["height"] - pads
    assert inner <= max(badge["height"], name["height"]) + 1, (summary, pads, name)


@pytest.mark.django_db(transaction=True)
def test_tablet_card_head_is_two_rows(page, live_server):
    """700px: the two-row grid keeps the title column >= 60% of the card's inner
    width, and a three-digit long count stays on one line."""
    lessons = [("lesson", f"Lekcja {i}") for i in range(100)]
    _, course, n = _build(
        "ctablet", [("part", "Liczby", [("chapter", "Wszystko", lessons)])]
    )
    _open(page, live_server, "ctablet", course.slug, 700)

    pk = n["Liczby"].pk
    head = _head(pk)
    card_inner = page.evaluate(
        "sel => { const el = document.querySelector(sel);"
        "  const s = getComputedStyle(el);"
        "  return el.clientWidth - parseFloat(s.paddingLeft)"
        "    - parseFloat(s.paddingRight); }",
        f"#node-{pk}",
    )
    name = _box(page, f"{head} > .outline-node__title")
    assert name["width"] >= 0.6 * card_inner, (name, card_inner)
    meta = _box(page, f"{head} .outline-card__meta")
    assert meta["y"] >= _bottom(name) - 0.5, (name, meta)
    long_sel = f"{head} .outline-count__long"
    expect(page.locator(long_sel)).to_have_text("0 z 100 lekcji")
    rects = page.evaluate(
        "sel => document.querySelector(sel).getClientRects().length", long_sel
    )
    assert rects == 1, rects


# --- desktop -----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_desktop_card_head_is_one_line(page, live_server):
    """1280, short titles: badge, title, bar (the fixed 12.5rem track), count
    and chevron share one line; two menu-less cards line their chevrons up."""
    _, course, n = _three_parts("cline")
    _open(page, live_server, "cline", course.slug, 1280)

    head = _head(n["Funkcje"].pk)
    name = _box(page, f"{head} > .outline-node__title")
    parts = {
        s: _box(page, f"{head} {s}")
        for s in (
            ".outline-card__num",
            ".outline-card__bar",
            ".outline-count__long",
            "> .outline-node__chevron",
        )
    }
    for sel, box in parts.items():
        assert _overlap_v(box, name), (sel, box, name)
    assert abs(parts[".outline-card__bar"]["width"] - 200) <= 0.5, parts
    other = _box(page, f"{_head(n['Ciągi'].pk)} > .outline-node__chevron")
    assert abs(other["x"] - parts["> .outline-node__chevron"]["x"]) <= 0.5


@pytest.mark.django_db(transaction=True)
def test_long_title_wraps_with_badge_on_first_line(page, live_server):
    long_title = " ".join(["Zastosowania liczb rzeczywistych i ich własności"] * 4)
    _, course, n = _three_parts("cwrap", long_title=long_title)
    _open(page, live_server, "cwrap", course.slug, 1280)

    head = _head(n[long_title].pk)
    title_sel = f"{head} > .outline-node__title"
    name = _box(page, title_sel)
    line = _line_height(page, title_sel)
    assert name["height"] >= 1.8 * line, (name, line)  # it really wraps
    first_line = {"y": name["y"], "height": line}
    for sel in (".outline-card__num", "> .outline-node__chevron"):
        box = _box(page, f"{head} {sel}")
        centre = box["y"] + box["height"] / 2
        assert name["y"] <= centre <= name["y"] + line, (sel, box, first_line)


@pytest.mark.django_db(transaction=True)
def test_chip_card_keeps_its_chevron_on_the_first_row(page, live_server):
    """The "+N dodatkowe" chip shares the count's cell, so it adds no track and
    never pushes the chevron off the title's first line."""
    _, course, n = _build(
        "cchip",
        [
            (
                "part",
                "Zbiory liczbowe",
                [
                    (
                        "chapter",
                        "Rozdział 1",
                        [
                            ("lesson", "L1"),
                            ("lesson", "Extra", {"optional": True, "completed": True}),
                        ],
                    )
                ],
            )
        ],
    )
    _open(page, live_server, "cchip", course.slug, 1280)

    head = _head(n["Zbiory liczbowe"].pk)
    expect(page.locator(f"{head} .rollup--additional")).to_be_visible()
    title_sel = f"{head} > .outline-node__title"
    name = _box(page, title_sel)
    first_line = {"y": name["y"], "height": _line_height(page, title_sel)}
    chevron = _box(page, f"{head} > .outline-node__chevron")
    chip = _box(page, f"{head} .rollup--additional")
    assert _overlap_v(chevron, first_line), (chevron, first_line)
    assert _overlap_v(chip, first_line), (chip, first_line)


# --- behaviour inside cards --------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_tapping_a_chapter_unfolds_it_inside_the_card(page, live_server):
    """D5: the chapter's lessons open in place, inside the raised card."""
    _, course, n = _three_parts("cunfold")
    _open(page, live_server, "cunfold", course.slug, 360)

    pk = n["Zbiory liczbowe"].pk
    assert _style(page, f"#node-{pk}", "backgroundColor") not in (
        "rgba(0, 0, 0, 0)",
        "transparent",
    )
    page.locator(f"{_head(n['Rozdział 1'].pk)} .outline-node__title").click()
    unit = page.locator(f"#node-{n['L1b'].pk}")
    expect(unit).to_be_visible()
    card = _box(page, f"#node-{pk}")
    row = unit.bounding_box()
    assert row["x"] >= card["x"] and _right(row) <= _right(card), (card, row)
    assert row["y"] >= card["y"] and _bottom(row) <= _bottom(card), (card, row)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [360, 1280])
def test_last_card_menu_is_not_clipped(page, live_server, width):
    """The last card's open menu spills below the card, fully painted. Mutant:
    overflow: hidden on the card."""
    _, course, n = _build(
        f"clast{width}",
        [
            ("part", "Zbiory liczbowe", [("chapter", "R1", [("lesson", "L1")])]),
            (
                "part",
                "Funkcje",
                [("chapter", "R2", [("lesson", "L2", {"state": True})])],
            ),
        ],
    )
    _open(page, live_server, f"clast{width}", course.slug, width)

    pk = n["Funkcje"].pk
    # A CLOSED last card: its open panel has nothing below it inside the card.
    page.locator(f"{_head(pk)} > .outline-node__title").click()
    page.wait_for_function(
        "pk => !document.querySelector(`[data-node='${pk}']`).open", arg=str(pk)
    )
    page.locator(f"#node-{pk} > .outline-menu > summary").click()
    panel = page.locator(f"#node-{pk} > .outline-menu .outline-menu__panel")
    expect(panel).to_be_visible()
    panel.scroll_into_view_if_needed()
    box = panel.bounding_box()
    card = _box(page, f"#node-{pk}")
    assert _bottom(box) > _bottom(card), (card, box)
    # The panel's own lower edge, below the card, is painted by the panel.
    hit = page.evaluate(
        "([x, y]) => !!document.elementFromPoint(x, y)"
        "  ?.closest('.outline-menu__panel')",
        [box["x"] + box["width"] / 2, _bottom(box) - 3],
    )
    assert hit, box
    assert page.evaluate(NO_HSCROLL)


@pytest.mark.django_db(transaction=True)
def test_card_list_has_no_guide_rule_but_chapters_do(page, live_server):
    _, course, n = _three_parts("cguide")
    _open(page, live_server, "cguide", course.slug, 1280)
    _expand_all(page)

    card_ul = f"[data-node='{n['Funkcje'].pk}'] > ul"
    assert _style(page, card_ul, "borderLeftWidth") == "0px"
    assert _style(page, card_ul, "paddingLeft") == "0px"
    chapter_ul = f"[data-node='{n['Rozdział 2'].pk}'] > ul"
    assert _style(page, chapter_ul, "borderLeftWidth") == "1px"
    assert _style(page, chapter_ul, "paddingLeft") != "0px"


@pytest.mark.django_db(transaction=True)
def test_section_card_title_is_not_micro_type(page, live_server):
    """A course whose roots are sections gets normal card titles. Mutant: drop
    the card-title override's resets."""
    _, course, n = _build(
        "csection", [("section", "Sekcja główna", [("lesson", "L1")])]
    )
    _open(page, live_server, "csection", course.slug, 1280)

    sel = f"{_head(n['Sekcja główna'].pk)} > .outline-node__title"
    assert _style(page, sel, "fontSize") == "20px"
    assert _style(page, sel, "fontWeight") == "600"
    assert _style(page, sel, "textTransform") == "none"
    assert _style(page, sel, "letterSpacing") == "normal"
    assert _style(page, sel, "color") == _probe_colour(page, "var(--text-primary)")


@pytest.mark.django_db(transaction=True)
def test_type_scale_superseded_t17(page, live_server):
    """§3.8: a depth-1 chapter row is 15px/500; a depth-2 section keeps its 12px
    uppercase micro-type; the chapter's own list keeps the guide rule."""
    _, course, n = _build(
        "ctype",
        [
            (
                "part",
                "Część",
                [("chapter", "Rozdział", [("section", "Sekcja", [("lesson", "L")])])],
            )
        ],
    )
    _open(page, live_server, "ctype", course.slug, 1280)
    _expand_all(page)

    chapter = f"{_head(n['Rozdział'].pk)} > .outline-node__title"
    assert _style(page, chapter, "fontSize") == "15px"
    assert _style(page, chapter, "fontWeight") == "500"
    section = f"{_head(n['Sekcja'].pk)} > .outline-node__title"
    assert _style(page, section, "fontSize") == "12px"
    assert _style(page, section, "textTransform") == "uppercase"
    guide = f"[data-node='{n['Rozdział'].pk}'] > ul"
    assert _style(page, guide, "borderLeftWidth") == "1px"


@pytest.mark.django_db(transaction=True)
def test_resume_card_quiz_chip_keeps_its_style(page, live_server):
    """The quiz chip restyle is scoped to outline rows: the resume card's chip
    keeps master's colour and case (Step 1b baseline). Mutant: drop the
    `.outline-unit` scope from the quiz-chip rule."""
    _, course, n = _build(
        "cchipstyle",
        [
            (
                "part",
                "Część",
                [
                    (
                        "chapter",
                        "R",
                        [("lesson", "L", {"completed": True}), ("quiz", "Q")],
                    )
                ],
            )
        ],
    )
    _open(page, live_server, "cchipstyle", course.slug, 1280)

    chip = ".resume .unit-kind-chip--quiz"
    expect(page.locator(chip)).to_be_visible()
    for theme in ("light", "dark"):
        page.evaluate(
            "t => document.documentElement.setAttribute('data-theme', t)", theme
        )
        got = {
            "color": _style(page, chip, "color"),
            "transform": _style(page, chip, "textTransform"),
        }
        assert got == RESUME_CHIP_BASELINE[theme], (theme, got)
    # Liveness: the outline row's own chip IS restyled, so the scope is real.
    row_chip = f"#node-{n['Q'].pk} .outline-unit .unit-kind-chip--quiz"
    page.locator(_head(n["R"].pk)).click()
    assert _style(page, row_chip, "textTransform") == "uppercase"


@pytest.mark.django_db(transaction=True)
def test_root_unit_rows_sit_between_cards(page, live_server):
    """Review Focus 1: loose root units render as plain rows between cards,
    unnumbered; a run of them sits flush and gets --space-6 before the card."""
    _, course, n = _build(
        "croot",
        [
            ("lesson", "Wprowadzenie"),
            ("lesson", "Jak korzystać"),
            ("part", "Zbiory liczbowe", [("chapter", "R1", [("lesson", "L1")])]),
            ("part", "Funkcje", [("chapter", "R2", [("lesson", "L2")])]),
        ],
    )
    _open(page, live_server, "croot", course.slug, 1280)

    first = _box(page, f"#node-{n['Wprowadzenie'].pk}")
    second = _box(page, f"#node-{n['Jak korzystać'].pk}")
    card1 = _box(page, f"#node-{n['Zbiory liczbowe'].pk}")
    card2 = _box(page, f"#node-{n['Funkcje'].pk}")
    assert second["y"] - _bottom(first) < 4, (first, second)
    assert abs(card1["y"] - _bottom(second) - 24) <= 1, (second, card1)
    assert abs(card2["y"] - _bottom(card1) - 24) <= 1, (card1, card2)
    expect(
        page.locator(f"#node-{n['Wprowadzenie'].pk} .outline-card__num")
    ).to_have_count(0)
    expect(
        page.locator(f"{_head(n['Zbiory liczbowe'].pk)} .outline-card__num")
    ).to_have_text("1")
    unit_title = f"#node-{n['Wprowadzenie'].pk} .outline-unit__title"
    assert _style(page, unit_title, "fontSize") == "15px"
    assert _style(page, f"#node-{n['Wprowadzenie'].pk}", "backgroundColor") in (
        "rgba(0, 0, 0, 0)",
        "transparent",
    )


@pytest.mark.django_db(transaction=True)
def test_unbreakable_card_title_fits_a_phone(page, live_server):
    """Review Focus 4. Mutant: the phone title track `1fr` instead of
    `minmax(0, 1fr)`."""
    word = "Konstantynopolitańczykowianeczkowskiegoprzeciwdziałaniowości"
    assert len(word) >= 60
    _, course, n = _three_parts("cunbreak", long_title=word)
    _open(page, live_server, "cunbreak", course.slug, 360)

    assert page.evaluate(NO_HSCROLL)
    pk = n[word].pk
    card = _box(page, f"#node-{pk}")
    name = _box(page, f"{_head(pk)} > .outline-node__title")
    assert _right(name) <= _right(card), (card, name)


@pytest.mark.django_db(transaction=True)
def test_math_card_title_fits_a_phone(page, live_server):
    """Review Focus 3: KaTeX renders after load and must not overflow the card.
    The formula is wider than the phone title column, so it fits only by wrapping
    at its top-level relations. Mutant: `white-space: nowrap` on the card title."""
    title = r"Wzory \(a^2+b^2=c^2+d^2=e^2+f^2=g^2+h^2=k^2+m^2\) w zadaniach"
    _, course, n = _three_parts("cmath", long_title=title)
    _open(page, live_server, "cmath", course.slug, 360)

    pk = n[title].pk
    katex = page.locator(f"{_head(pk)} .katex")
    katex.first.wait_for(state="attached", timeout=5000)
    assert page.evaluate(NO_HSCROLL)
    card = _box(page, f"#node-{pk}")
    name = _box(page, f"{_head(pk)} > .outline-node__title")
    maths = katex.first.bounding_box()
    assert _right(name) <= _right(card), (card, name)
    assert _right(maths) <= _right(card), (card, maths)


@pytest.mark.django_db(transaction=True)
def test_rings_differ_under_forced_colors(page, live_server):
    """§3.8 forced colours: track CanvasText, arc and done circle Highlight, tick
    Canvas — so the three states stay apart. Mutant: delete the ring rules."""
    _, course, n = _build(
        "cforced",
        [
            (
                "part",
                "Część",
                [
                    ("chapter", "Gotowe", [("lesson", "A", {"completed": True})]),
                    (
                        "chapter",
                        "W toku",
                        [("lesson", "B", {"completed": True}), ("lesson", "C")],
                    ),
                    ("chapter", "Nowe", [("lesson", "D")]),
                ],
            )
        ],
    )
    _open(page, live_server, "cforced", course.slug, 1280)
    page.emulate_media(forced_colors="active")

    def ring(chapter, part, prop):
        return _style(page, f"{_head(n[chapter].pk)} .outline-ring__{part}", prop)

    canvas_text = _probe_colour(page, "CanvasText")
    highlight = _probe_colour(page, "Highlight")
    canvas = _probe_colour(page, "Canvas")
    assert highlight != canvas_text
    assert ring("Nowe", "track", "stroke") == canvas_text
    assert ring("W toku", "track", "stroke") == canvas_text
    assert ring("W toku", "arc", "stroke") == highlight
    assert ring("Gotowe", "fill", "fill") == highlight
    assert ring("Gotowe", "tick", "stroke") == canvas


@pytest.mark.django_db(transaction=True)
def test_expand_all_toggles_cards_and_chapters(page, live_server):
    """Regression guard. Mutant: the toggle handler skips data-depth="0"."""
    _, course, n = _three_parts("cexpand")
    _open(page, live_server, "cexpand", course.slug, 1280)

    groups = (
        "() => [...document.querySelectorAll('.outline-node__group')].map(d => d.open)"
    )
    toggle = page.locator("[data-outline-toggle-all]")
    expect(toggle).to_have_text("Rozwiń wszystko")
    toggle.click()
    expect(toggle).to_have_text("Zwiń wszystko")
    assert all(page.evaluate(groups))
    toggle.click()
    expect(toggle).to_have_text("Rozwiń wszystko")
    assert not any(page.evaluate(groups))


@pytest.mark.django_db(transaction=True)
def test_deep_link_rings_a_non_current_chapter(page, live_server):
    """`#node-<chapter>` lands the :target ring on a chapter that is NOT the
    highlighted row, so is-current cannot satisfy it. Mutant: drop the
    `> .outline-node__group > .outline-node__head` :target selector."""
    _, course, n = _build(
        "cdeep",
        [
            (
                "part",
                "Część",
                [
                    ("chapter", "Bieżący", [("lesson", "A", {"state": True})]),
                    ("chapter", "Cel", [("lesson", "B")]),
                ],
            )
        ],
    )
    _open(
        page, live_server, "cdeep", course.slug, 1280, fragment=f"#node-{n['Cel'].pk}"
    )

    target = _head(n["Cel"].pk)
    expect(page.locator(f"{_head(n['Bieżący'].pk)}.is-current")).to_have_count(1)
    expect(page.locator(f"{target}.is-current")).to_have_count(0)
    shadow = _style(page, target, "boxShadow")
    assert shadow != "none" and "0px 0px 0px 2px" in shadow, shadow


@pytest.mark.django_db(transaction=True)
def test_tag_filter_hides_and_restores_a_card(page, live_server):
    """Regression guard. Mutant: delete `.outline-node[hidden] { display: none; }`."""
    from tags.models import Tag
    from tags.models import UnitTag

    user, course, n = _three_parts("ctags")
    tag = Tag.objects.create(author=user, name="egzamin")
    UnitTag.objects.create(tag=tag, unit=n["L2"])
    _open(page, live_server, "ctags", course.slug, 1280)

    chip = page.locator(f"a.tag-chip[data-tag-id='{tag.pk}']")
    chip.click()
    expect(page.locator(f"#node-{n['Zbiory liczbowe'].pk}")).to_be_hidden()
    expect(page.locator(f"#node-{n['Funkcje'].pk}")).to_be_visible()
    chip.click()
    expect(page.locator(f"#node-{n['Zbiory liczbowe'].pk}")).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_unit_row_tag_icon_stays_on_the_title_row_on_a_phone(page, live_server):
    long_title = " ".join(["Zastosowania liczb rzeczywistych i ich własności"] * 3)
    _, course, n = _build(
        "ctagrow",
        [("part", "Zbiory", [("chapter", "Rozdział 1", [("lesson", long_title)])])],
    )
    _open(page, live_server, "ctagrow", course.slug, 360)
    _expand_all(page)
    li = f"#node-{n[long_title].pk}"
    link = _box(page, f"{li} > a.outline-unit")
    tags = _box(page, f"{li} > .outline-unit__edit-tags")
    assert link["height"] >= 1.8 * _line_height(page, f"{li} .outline-unit__title")
    assert _overlap_v(tags, link), (tags, link)
