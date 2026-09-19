"""Institution settings layout, measured in a real browser — the only place CSS
can be seen. The owner's hard rules: the page itself never scrolls sideways, and
no tab label, login, date or kit-row button ever spans two lines (tables scroll
inside their card instead). Marked e2e (run with -m e2e)."""

import os

import pytest
from django.urls import reverse

pytestmark = pytest.mark.e2e

VIEWPORTS = ((1280, 900), (420, 900))
ALL_TABS = 10  # 8 institution tabs + Pricing and Demo access on a vendor instance
LONG_LABEL = "Szkoła Podstawowa nr 12 im. Marii Skłodowskiej-Curie w Krakowie"
# No space anywhere: only the Label cell's overflow-wrap: anywhere lets it wrap.
UNBROKEN_LABEL = "Szkoła" + "x" * 60
OPEN_LABELS = ("SP 12", LONG_LABEL, UNBROKEN_LABEL)

# Height of an element's TEXT (a Range over its contents), not of its box: a
# table cell is as tall as its row and a button carries padding, so the box height
# says nothing about how many lines the text took. One line measures about one
# line-height; a second line pushes it past 1.6x.
_TEXT_BOX_JS = """el => {
  const cs = getComputedStyle(el);
  let lineHeight = parseFloat(cs.lineHeight);
  if (Number.isNaN(lineHeight)) lineHeight = parseFloat(cs.fontSize) * 1.2;
  const range = document.createRange();
  range.selectNodeContents(el);
  return {
    text: el.textContent.trim(),
    height: range.getBoundingClientRect().height,
    lineHeight: lineHeight,
    top: el.getBoundingClientRect().top,
  };
}"""

_BOX_JS = "el => el.getBoundingClientRect().toJSON()"

_REM_JS = "() => parseFloat(getComputedStyle(document.documentElement).fontSize)"

# Set the scroller's scrollLeft, then let one frame paint before measuring.
_SCROLL_TO_JS = """(el, x) => new Promise(done => {
  el.scrollLeft = x;
  requestAnimationFrame(() => done(el.scrollLeft));
})"""


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username, password):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login/" not in url)


def _vendor_admin(page, live_server, settings, *, kits, language="en"):
    from django.contrib.auth.models import Group

    from demo.services import revoke_kit
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.demo.fixtures import small_course
    from tests.demo.helpers import provision_for_test
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    settings.VENDOR_INSTANCE = True
    seed_roles()
    admin = make_verified_user(
        username="layout_pa", email="layout_pa@t.example.com", password=TEST_PASSWORD
    )
    admin.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    # Before the login: the login signal is what puts User.language in the session.
    admin.language = language
    admin.save(update_fields=["language"])
    if kits:
        course = small_course()
        for label in OPEN_LABELS:
            provision_for_test(course, label=label)
        revoke_kit(provision_for_test(course, label="Closed kit"))
    _login(page, live_server, "layout_pa", TEST_PASSWORD)


def _ensure_pricing_plans():
    """Migration 0012 seeds three bands, but a transactional test's flush wipes
    them for every later test in the session — and an empty table has no inputs
    for the sizing assertion to measure."""
    from institution.models import PricingPlan

    for order, (low, high) in enumerate(((1, 100), (101, 300), (301, 500)), 1):
        PricingPlan.objects.get_or_create(
            order=order,
            defaults={
                "pupils_min": low,
                "pupils_max": high,
                "support_hours_per_term": 6,
                "courses_included": 15,
                "video_hours_included": 10,
            },
        )


def _open(page, live_server, query, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{live_server.url}{reverse('institution:settings')}{query}")
    # Inter loads with font-display: swap; every width measured here shifts when
    # it swaps in (the desktop tab row has only ~17px of slack).
    page.evaluate("() => document.fonts.ready.then(() => true)")


def _assert_one_line(locator, what):
    box = locator.evaluate(_TEXT_BOX_JS)
    assert box["height"] < 1.6 * box["lineHeight"], f"{what} wraps: {box}"
    return box


@pytest.mark.django_db(transaction=True)
def test_page_never_scrolls_sideways_and_tabs_stay_on_one_line(
    page, live_server, settings
):
    _vendor_admin(page, live_server, settings, kits=True)
    _ensure_pricing_plans()
    for width, height in VIEWPORTS:
        for query in ("?tab=demo&all=1", "?tab=pricing", "?tab=branding"):
            _open(page, live_server, query, width, height)
            where = f"{query} at {width}px"

            page_width, viewport = page.evaluate(
                "() => [document.documentElement.scrollWidth, window.innerWidth]"
            )
            assert page_width <= viewport, f"{where}: page is {page_width}px wide"

            tabs = page.locator(".settings__tab")
            assert tabs.count() == ALL_TABS, where
            for i in range(ALL_TABS):
                _assert_one_line(tabs.nth(i), f"{where}: tab")


# Every tab's box, the clipping wrapper's box, and the divider's, in one read.
_TAB_ROW_JS = """wrap => ({
  wrap: wrap.getBoundingClientRect().toJSON(),
  clips: getComputedStyle(wrap).overflowX,
  tabs: [...wrap.querySelectorAll(".settings__tab")].map(t => ({
    text: t.textContent.trim(),
    box: t.getBoundingClientRect().toJSON(),
  })),
  divider: (() => {
    const group = wrap.querySelector(".settings__tabs-vendor");
    if (!group) return null;
    const cs = getComputedStyle(group, "::before");
    const g = group.getBoundingClientRect();
    return {content: cs.content, left: g.left + parseFloat(cs.left),
            width: parseFloat(cs.width)};
  })(),
})"""


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("language", ["en", "pl"])
def test_every_tab_is_fully_visible_without_scrolling(
    page, live_server, settings, language
):
    """The row wraps instead of scrolling: a scrolled row hid its last tab behind
    Shift+wheel, which a laptop touchpad user could not reach (Polish, 1280px)."""
    _vendor_admin(page, live_server, settings, kits=False, language=language)
    for width, height in VIEWPORTS:
        _open(page, live_server, "?tab=branding", width, height)
        where = f"{language} at {width}px"
        row = page.locator(".settings__tabs-wrap").evaluate(_TAB_ROW_JS)
        assert len(row["tabs"]) == ALL_TABS, where
        wrap = row["wrap"]
        for tab in row["tabs"]:
            box = tab["box"]
            assert box["left"] >= wrap["left"] - 0.5, (where, tab, wrap)
            assert box["right"] <= wrap["right"] + 0.5, (where, tab, wrap)
            assert box["bottom"] <= wrap["bottom"] + 0.5, (where, tab, wrap)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("language", ["en", "pl"])
def test_tab_row_is_as_wide_as_the_form_below(page, live_server, settings, language):
    _vendor_admin(page, live_server, settings, kits=False, language=language)
    _open(page, live_server, "?tab=branding", 1280, 900)
    wrap = page.locator(".settings__tabs-wrap").evaluate(_BOX_JS)
    form = page.locator("[data-tab='branding'] > .settings__form").first
    form_box = form.evaluate(_BOX_JS)
    assert abs(wrap["left"] - form_box["left"]) <= 1, (wrap, form_box)
    assert abs(wrap["width"] - form_box["width"]) <= 1, (wrap, form_box)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("language", ["en", "pl"])
def test_vendor_divider_never_starts_a_row(page, live_server, settings, language):
    """Pricing and Demo access wrap as one unit, and the rule before them shows
    only between two tabs on the same row, never dangling at a row's start."""
    _vendor_admin(page, live_server, settings, kits=False, language=language)
    for width, height in VIEWPORTS:
        _open(page, live_server, "?tab=branding", width, height)
        where = f"{language} at {width}px"
        row = page.locator(".settings__tabs-wrap").evaluate(_TAB_ROW_JS)
        tabs, wrap, divider = row["tabs"], row["wrap"], row["divider"]
        pricing, demo = tabs[8]["box"], tabs[9]["box"]
        assert abs(pricing["top"] - demo["top"]) <= 1, (where, pricing, demo)
        assert divider and divider["content"] != "none", (where, divider)
        if pricing["left"] - wrap["left"] < 1:
            # Pricing opens a row: the rule must lie outside the box, AND the box
            # must clip it; outside an unclipped box it still paints.
            assert divider["left"] + divider["width"] <= wrap["left"], (where, row)
            assert row["clips"] in ("hidden", "clip"), (where, row)
        else:
            # Mid-row: the rule sits in the gap after the tab before it.
            before = tabs[7]["box"]
            assert abs(before["top"] - pricing["top"]) <= 1, (where, row)
            assert before["right"] <= divider["left"], (where, row)
            assert divider["left"] + divider["width"] <= pricing["left"], (where, row)


@pytest.mark.django_db(transaction=True)
def test_kit_rows_keep_actions_side_by_side_and_tokens_on_one_line(
    page, live_server, settings
):
    _vendor_admin(page, live_server, settings, kits=True)
    for width, height in VIEWPORTS:
        _open(page, live_server, "?tab=demo&all=1", width, height)
        where = f"demo at {width}px"

        # Column positions of the cells measured below, pinned by their headers
        # (textContent: the headers are uppercased by CSS only).
        headers = page.locator("[data-demo-list] thead th").evaluate_all(
            "ths => ths.map(th => th.textContent.trim())"
        )
        assert headers[4:7] == ["Teacher login", "Created", "Expires"], headers

        open_rows = page.locator("tr[data-demo-kit]:has(form[data-demo-extend])")
        assert open_rows.count() == len(OPEN_LABELS), where
        for i in range(len(OPEN_LABELS)):
            row = open_rows.nth(i)
            extend = _assert_one_line(
                row.locator("form[data-demo-extend] button"), f"{where}: Extend"
            )
            revoke = _assert_one_line(
                row.locator("form[data-demo-revoke] button"), f"{where}: Revoke"
            )
            assert abs(extend["top"] - revoke["top"]) <= 1, (where, extend, revoke)

            cells = row.locator("td")
            for column in (4, 5, 6):
                _assert_one_line(cells.nth(column), f"{where}: {headers[column]}")


@pytest.mark.django_db(transaction=True)
def test_pricing_table_stays_inside_its_card(page, live_server, settings):
    _vendor_admin(page, live_server, settings, kits=False)
    _ensure_pricing_plans()
    panel = "[data-tab='pricing']"
    right_edge = "el => el.getBoundingClientRect().right"

    _open(page, live_server, "?tab=pricing", 1280, 900)
    # The premise: the band rows (and so their inputs) are really rendered.
    assert page.locator(f"{panel} tbody input").count() == 18
    table = page.locator(f"{panel} .settings__table").evaluate(right_edge)
    card = page.locator(f"{panel} .settings__form").evaluate(right_edge)
    assert table <= card, f"at 1280px the table ends at {table}, its card at {card}"
    # The wide card's ordinary fields keep the 48rem form measure.
    currency = page.locator(f"{panel} input[name='currency']").evaluate(
        "el => el.getBoundingClientRect().width"
    )
    measure = page.evaluate(
        "() => 48 * parseFloat(getComputedStyle(document.documentElement).fontSize)"
    )
    assert currency <= measure, f"at 1280px Currency is {currency}px, cap {measure}px"

    _open(page, live_server, "?tab=pricing", 420, 900)
    scroller = page.locator(f"{panel} .settings__table").evaluate(
        "t => getComputedStyle(t.parentElement).overflowX"
    )
    assert scroller in ("auto", "scroll"), scroller
    card = page.locator(f"{panel} .settings__form").evaluate(right_edge)
    viewport = page.evaluate("() => window.innerWidth")
    assert card <= viewport, f"at 420px the card ends at {card}"


@pytest.mark.django_db(transaction=True)
def test_demo_cards_share_one_width_and_the_create_form_is_a_grid(
    page, live_server, settings
):
    _vendor_admin(page, live_server, settings, kits=False)
    create = page.locator("form[data-demo-create]")
    course = create.locator(".settings__field:has(#id_course)")
    label = create.locator(".settings__field:has(#id_label)")

    _open(page, live_server, "?tab=demo&all=1", 1280, 900)
    create_width = create.evaluate(_BOX_JS)["width"]
    list_width = page.locator("[data-demo-list]").evaluate(_BOX_JS)["width"]
    assert abs(create_width - list_width) <= 1, (
        f"at 1280px the create card is {create_width}px, the kit list {list_width}px"
    )
    course_box, label_box = course.evaluate(_BOX_JS), label.evaluate(_BOX_JS)
    assert abs(course_box["top"] - label_box["top"]) <= 1, (
        "at 1280px Course and Label are not side by side",
        course_box,
        label_box,
    )

    _open(page, live_server, "?tab=demo&all=1", 420, 900)
    course_box, label_box = course.evaluate(_BOX_JS), label.evaluate(_BOX_JS)
    assert label_box["top"] >= course_box["bottom"], (
        "at 420px Label is not below Course",
        course_box,
        label_box,
    )

    # Only the Demo tab drops the 48rem measure; the other tabs keep it.
    _open(page, live_server, "?tab=branding", 1280, 900)
    branding = page.locator("[data-tab='branding'] > .settings__form").first
    branding_width = branding.evaluate(_BOX_JS)["width"]
    measure = 48 * page.evaluate(_REM_JS)
    assert branding_width <= measure, (
        f"at 1280px the Branding form is {branding_width}px, cap {measure}px"
    )


# True when the topmost element at the centre of `el` (or at `x`, if given) is
# `el` or inside it: nothing paints over that point and takes the hit instead.
# elementFromPoint sees only the viewport, so the PAGE is first scrolled
# vertically to the element (never scrollIntoView: it could move the table's
# scrollLeft too). A vertical page scroll leaves x unchanged.
_HIT_JS = """(el, x) => {
  const before = el.getBoundingClientRect();
  window.scrollBy(0, before.top - window.innerHeight / 2);
  const r = el.getBoundingClientRect();
  const cx = x ?? (r.left + r.right) / 2;
  const hit = document.elementFromPoint(cx, (r.top + r.bottom) / 2);
  return el.contains(hit);
}"""

_FIRST_OPEN_ROW = "tr[data-demo-kit]:has(form[data-demo-extend])"


@pytest.mark.django_db(transaction=True)
def test_kit_actions_stay_visible_at_both_scroll_ends(page, live_server, settings):
    """Desktop only: at <=640px the Actions column is not pinned (see the next test)."""
    _vendor_admin(page, live_server, settings, kits=True)
    _open(page, live_server, "?tab=demo&all=1", 1280, 900)
    scroller = page.locator("[data-demo-list] .settings__table-scroll")
    scroll_width, client_width = scroller.evaluate(
        "s => [s.scrollWidth, s.clientWidth]"
    )
    # The premise: the table really scrolls. Otherwise both ends are the same
    # view, and a Revoke that is visible there proves nothing about the pin.
    assert scroll_width > client_width, (scroll_width, client_width)
    first_open_row = page.locator(_FIRST_OPEN_ROW).first
    revoke = first_open_row.locator("form[data-demo-revoke] button")

    # Paint, which no hit test can see. The wrapper's right-edge shade is
    # pointer-events: none, so it would lie over the buttons without taking a hit.
    shade = page.locator("[data-demo-list] .settings__kits-scroll").evaluate(
        "w => getComputedStyle(w, '::after').content"
    )
    assert shade == "none", f"at 1280px the kit table's right-edge shade is {shade}"
    # A see-through pinned cell would show the scrolled cells through it.
    cell_fill = first_open_row.locator("td.settings__col-actions").evaluate(
        "td => getComputedStyle(td).backgroundColor"
    )
    card_fill = page.locator("[data-demo-list]").evaluate(
        "card => getComputedStyle(card).backgroundColor"
    )
    assert cell_fill not in ("rgba(0, 0, 0, 0)", "transparent"), cell_fill
    assert cell_fill == card_fill, (
        f"at 1280px the pinned Actions cell is {cell_fill}, its card {card_fill}"
    )

    for end, x in (("left", 0), ("right", scroll_width)):
        scrolled = scroller.evaluate(_SCROLL_TO_JS, x)
        where = f"at 1280px scrolled to the {end} end ({scrolled})"
        assert (scrolled == 0) == (end == "left"), where
        box, button = scroller.evaluate(_BOX_JS), revoke.evaluate(_BOX_JS)
        assert button["left"] >= box["left"], (where, button, box)
        assert button["right"] <= box["right"], (where, button, box)
        # Stacking only: a scrolled cell layered over the button would take the
        # hit. Paint (a shade, a see-through cell) is guarded above, not here.
        assert revoke.evaluate(_HIT_JS), f"{where}: Revoke is covered at its centre"


@pytest.mark.django_db(transaction=True)
def test_kit_actions_scroll_with_their_row_on_a_phone(page, live_server, settings):
    """At 420px a pinned Actions column (~250px) covered two thirds of the table,
    hiding the kit a Revoke acts on. On a phone it scrolls like every column."""
    _vendor_admin(page, live_server, settings, kits=True)
    _open(page, live_server, "?tab=demo&all=1", 420, 900)
    scroller = page.locator("[data-demo-list] .settings__table-scroll")
    scroll_width, client_width = scroller.evaluate(
        "s => [s.scrollWidth, s.clientWidth]"
    )
    # The premise: the table really scrolls here, so scrollLeft = 0 is one end of
    # a longer row and not the whole table in view.
    assert scroll_width > client_width, (scroll_width, client_width)
    assert scroller.evaluate(_SCROLL_TO_JS, 0) == 0
    row = page.locator(_FIRST_OPEN_ROW).first
    label = row.locator("td.settings__cell-label")
    box, cell = scroller.evaluate(_BOX_JS), label.evaluate(_BOX_JS)
    assert cell["left"] >= box["left"], ("at 420px the Label cell", cell, box)
    assert cell["right"] <= box["right"], ("at 420px the Label cell", cell, box)
    # Its right end is where a pinned column would lie over it.
    assert label.evaluate(_HIT_JS, cell["right"] - 2), (
        "at 420px the Label cell is covered near its right edge"
    )
    position = row.locator("td.settings__col-actions").evaluate(
        "td => getComputedStyle(td).position"
    )
    assert position == "static", f"at 420px the Actions cell is {position}"


# The table's width may grow by less than this when the unbroken label goes back in.
_LABEL_SLACK_PX = 16

# The scroller's scrollWidth with the cell's real label, then with a one-character
# label in its place. That kit's teacher login is just as long (it is slugified
# from the label) and stays in both measurements, so only the Label cell's own
# wrapping can account for a difference.
_WIDTH_WITH_AND_WITHOUT_LABEL_JS = """td => {
  const scroller = td.closest('.settings__table-scroll');
  const text = td.textContent;
  const withLabel = scroller.scrollWidth;
  td.textContent = 'x';
  const withoutLabel = scroller.scrollWidth;
  td.textContent = text;
  return [withLabel, withoutLabel];
}"""


@pytest.mark.django_db(transaction=True)
def test_an_unbroken_label_wraps_inside_its_cell(page, live_server, settings):
    _vendor_admin(page, live_server, settings, kits=True)
    for width, height in VIEWPORTS:
        _open(page, live_server, "?tab=demo&all=1", width, height)
        where = f"demo at {width}px"
        cell = page.locator("td.settings__cell-label", has_text=UNBROKEN_LABEL)
        cap = 18 * page.evaluate(_REM_JS)
        cell_width = cell.evaluate(_BOX_JS)["width"]
        with_label, without_label = cell.evaluate(_WIDTH_WITH_AND_WITHOUT_LABEL_JS)
        assert cell_width <= cap, (
            f"{where}: the unbroken label's cell is {cell_width}px wide, cap {cap}px"
        )
        assert with_label <= without_label + _LABEL_SLACK_PX, (
            f"{where}: the unbroken label widens the table from {without_label}px"
            f" to {with_label}px"
        )
