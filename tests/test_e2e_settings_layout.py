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


def _vendor_admin(page, live_server, settings, *, kits):
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
    if kits:
        course = small_course()
        provision_for_test(course, label="SP 12")
        provision_for_test(course, label=LONG_LABEL)
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
                tab = tabs.nth(i)
                assert tab.evaluate("t => t.getClientRects().length") == 1, where
                _assert_one_line(tab, f"{where}: tab")


@pytest.mark.django_db(transaction=True)
def test_active_tab_is_scrolled_into_view_on_a_phone(page, live_server, settings):
    _vendor_admin(page, live_server, settings, kits=False)
    _open(page, live_server, "?tab=demo", 420, 900)

    nav = page.locator(".settings__tabs")
    # The premise: at this width the row really overflows. Otherwise the last tab
    # is visible anyway and the assertion below proves nothing.
    assert nav.evaluate("n => n.scrollWidth > n.clientWidth")
    nav_box = nav.evaluate("n => n.getBoundingClientRect().toJSON()")
    tab_box = page.locator(".settings__tab.is-on").evaluate(
        "t => t.getBoundingClientRect().toJSON()"
    )
    assert tab_box["left"] >= nav_box["left"], (tab_box, nav_box)
    assert tab_box["right"] <= nav_box["right"], (tab_box, nav_box)


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
        assert open_rows.count() == 2, where
        for i in range(2):
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
