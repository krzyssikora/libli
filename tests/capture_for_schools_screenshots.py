"""Produce the images the design pass judges for /for-schools/ at phone width.

Not an assertion test -- run it on its own; the assertions live in
tests/test_for_schools_page.py, tests/test_pricing_token.py and
tests/test_public_pages_css.py (the scroll-wrapper CSS rule and its ordering).

    uv run pytest tests/capture_for_schools_screenshots.py -m e2e

/for-schools/ is anonymous (core/views_public.py: no login_required), so theme
is set the way tests/test_e2e_error_pages.py sets it for its own anonymous
pages -- the libli_theme COOKIE, not User.theme. _resolve_theme_pref in
core/context_processors.py only reaches User.theme for an authenticated user;
here request.user is AnonymousUser, so the cookie is the correct and only
lever.

Two page states, each shot in both themes:

* fallback-{light,dark}.png -- every PricingPlan.annual_price is NULL, which
  is what this branch actually ships (migration 0012 seeds three rows with no
  price). The renderer falls back to a paragraph and emits no table at all.
* table-{light,dark}.png -- a fixture prices the three seeded rows so the
  table branch renders instead.

Plus the A/B pair that is the actual point of this task. Task 13's tests
(tests/test_public_pages_css.py) prove only that
`.public-page__scroll table { width: max-content; min-width: 100%; }` EXISTS
in app.css and is ordered after `.public-page table` -- a source-order
assertion. It cannot prove the scroller ENGAGES at phone width. A single
with-the-rule screenshot "shows only that something was drawn, never that it
fixed the thing it was added for" (tests/capture_tabs_panel_rule_screenshots.py's
own words for the same trap). So:

* table-scroll-on.png  -- the table as shipped: the rule is live.
* table-scroll-off.png -- same build, same seeded page, `page.add_style_tag`
  restores `.public-page__scroll table` to `width: 100%` (the value it would
  fall through to from the earlier `.public-page table` rule if the Task 13
  rule were absent). The pair differs in that ONE declaration.

The suppression is done with add_style_tag rather than by reverting the file
so that both halves of the pair come from the SAME build and the same seeded
page -- exactly the reasoning in the tabs precedent.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from institution.models import PricingPlan

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)

PHONE_VIEWPORT = {"width": 390, "height": 844}

# The exact declaration under test, restored to what the page would fall
# through to WITHOUT it. Must stay in step with the rule in app.css -- if the
# selector there is edited and this is not, the -off shot silently becomes a
# duplicate of the -on shot and the A/B proves nothing.
SCROLL_RULE_OFF = """
.public-page__scroll table { width: 100%; }
"""


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# pupils_min/max, support hours, courses and video allowance for orders 1/2/3,
# copied verbatim from institution/migrations/0012_..._pricing_fields.py's
# seed_plans -- so a row rebuilt here is byte-identical in shape to the one
# the migration seeds, whether or not that row currently exists.
_PLAN_SHAPE = {
    1: {
        "pupils_min": 1,
        "pupils_max": 100,
        "support_hours_per_term": 6,
        "courses_included": 3,
        "video_hours_included": 10,
    },
    2: {
        "pupils_min": 101,
        "pupils_max": 300,
        "support_hours_per_term": 8,
        "courses_included": 6,
        "video_hours_included": 20,
    },
    3: {
        "pupils_min": 301,
        "pupils_max": 500,
        "support_hours_per_term": 12,
        "courses_included": 12,
        "video_hours_included": 40,
    },
}


@pytest.fixture
def priced_plans(db):
    """Prices the three seeded rows -- orders 1/2/3, never 4/5/6.

    Not a plain .update(): pyproject.toml's addopts sets no --nomigrations, so
    RunPython(seed_plans, ...) runs once against a freshly migrated test
    database and rows 1/2/3 exist for the FIRST transactional test in the
    session -- but live_server (which every test in this module needs)
    forces `transaction=True`, and pytest-django's TransactionTestCase
    teardown TRUNCATEs every table after each test without re-running data
    migrations. So by the second or third transactional test in this file,
    orders 1/2/3 no longer exist and a bare
    `PricingPlan.objects.filter(order=N).update(...)` is a silent no-op (0
    rows matched) -- the table branch then never renders and the capture
    times out waiting for it. update_or_create with the migration's exact
    field shape (above) is idempotent either way: it updates in place when
    the row survived, and rebuilds an identical row when it did not --
    always exactly orders 1/2/3, never a gapped 4/5/6 set.
    """
    for order, price in ((1, "4800.00"), (2, "7200.00"), (3, "10800.00")):
        PricingPlan.objects.update_or_create(
            order=order, defaults={**_PLAN_SHAPE[order], "annual_price": price}
        )
    return PricingPlan.objects.order_by("order")


def _goto_for_schools(page, live_server, theme):
    # Anonymous: _resolve_theme_pref reads the libli_theme cookie SERVER-side
    # and renders data-theme accordingly -- there is no logged-in user whose
    # User.theme could win instead.
    page.context.add_cookies(
        [{"name": "libli_theme", "value": theme, "url": live_server.url}]
    )
    page.set_viewport_size(PHONE_VIEWPORT)
    page.goto(f"{live_server.url}{reverse('core:for_schools')}")
    page.wait_for_selector("article.public-page")


@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_fallback(page, live_server, theme):
    """No priced plans: the state this branch actually ships in."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _goto_for_schools(page, live_server, theme)
    # Prove this is the fallback branch, not an accidental table render.
    assert page.locator(".public-page__scroll").count() == 0
    page.screenshot(path=str(OUT_DIR / f"fallback-{theme}.png"), full_page=True)


@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_table(page, live_server, theme, priced_plans):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _goto_for_schools(page, live_server, theme)
    page.wait_for_selector(".public-page__scroll table")
    page.screenshot(path=str(OUT_DIR / f"table-{theme}.png"), full_page=True)


@override_settings(VENDOR_INSTANCE=True)
def test_capture_scroll_ab(page, live_server, priced_plans):
    """The A/B pair. One theme is enough: it isolates one CSS declaration,
    not a colour."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _goto_for_schools(page, live_server, "light")
    page.wait_for_selector(".public-page__scroll table")
    scroller = page.locator(".public-page__scroll").first

    # A half: the rule as shipped.
    scroller.screenshot(path=str(OUT_DIR / "table-scroll-on.png"))

    # B half: same build, same page, one declaration suppressed.
    page.add_style_tag(content=SCROLL_RULE_OFF)
    scroller.screenshot(path=str(OUT_DIR / "table-scroll-off.png"))
