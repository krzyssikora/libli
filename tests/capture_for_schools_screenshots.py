"""Produce the images the design pass judges for /for-schools/, phone + desktop.

Not an assertion test -- run it on its own; the assertions live in
tests/test_for_schools_page.py and tests/test_pricing_token.py.

    uv run pytest tests/capture_for_schools_screenshots.py -m e2e

/for-schools/ is anonymous (core/views_public.py: no login_required), so theme
is set the way tests/test_e2e_error_pages.py sets it for its own anonymous
pages -- the libli_theme COOKIE, not User.theme. _resolve_theme_pref in
core/context_processors.py only reaches User.theme for an authenticated user;
here request.user is AnonymousUser, so the cookie is the correct and only
lever. Language is set the way tests/test_for_schools_page.py sets it for the
django test client -- an Accept-Language header, via
page.set_extra_http_headers -- because there is no logged-in User.language
either, and core.middleware.SessionLocaleMiddleware falls back to exactly that
header when no session key is present.

Two page states, each shot at phone width AND a desktop width, in both
themes, in both languages -- sixteen images total:

* fallback-{phone,desktop}-{light,dark}-{en,pl}.png -- every
  PricingPlan.annual_price is NULL, which is what this branch actually ships
  (migration 0012 seeds three rows with no price). The renderer falls back to
  a paragraph and emits no cards at all.
* cards-{phone,desktop}-{light,dark}-{en,pl}.png -- a fixture prices the three
  seeded rows so the pricing-cards branch renders instead. The desktop shot is
  the one that proves the three plans actually sit side by side; the phone
  shot is the one that proves they stack legibly. The Polish shots are the
  ones that matter most: the English labels ("Support", "Courses") are short
  enough to hide a wrap that the longer Polish ones ("Wsparcie") exposed.
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

VIEWPORTS = {
    "phone": {"width": 390, "height": 844},
    "desktop": {"width": 1280, "height": 900},
}


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
        "courses_included": 15,
        "video_hours_included": 10,
    },
    2: {
        "pupils_min": 101,
        "pupils_max": 300,
        "support_hours_per_term": 8,
        "courses_included": 20,
        "video_hours_included": 20,
    },
    3: {
        "pupils_min": 301,
        "pupils_max": 500,
        "support_hours_per_term": 12,
        "courses_included": 25,
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
    rows matched) -- the cards branch then never renders and the capture
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


def _goto_for_schools(page, live_server, theme, viewport, lang):
    # Anonymous: _resolve_theme_pref reads the libli_theme cookie SERVER-side
    # and renders data-theme accordingly -- there is no logged-in user whose
    # User.theme could win instead.
    page.context.add_cookies(
        [{"name": "libli_theme", "value": theme, "url": live_server.url}]
    )
    # Anonymous again: no User.language either, so the language lever is the
    # same one tests/test_for_schools_page.py drives the django test client
    # with -- Accept-Language -- set on the CONTEXT so it rides along on every
    # request this page makes, the same way the theme cookie does.
    page.set_extra_http_headers({"Accept-Language": lang})
    page.set_viewport_size(VIEWPORTS[viewport])
    page.goto(f"{live_server.url}{reverse('core:for_schools')}")
    page.wait_for_selector("article.public-page")


@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("lang", ["en", "pl"])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("viewport", ["phone", "desktop"])
def test_capture_fallback(page, live_server, viewport, theme, lang):
    """No priced plans: the state this branch actually ships in."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _goto_for_schools(page, live_server, theme, viewport, lang)
    # Prove this is the fallback branch, not an accidental cards render.
    assert page.locator(".pricing-cards").count() == 0
    page.screenshot(
        path=str(OUT_DIR / f"fallback-{viewport}-{theme}-{lang}.png"), full_page=True
    )


@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("lang", ["en", "pl"])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("viewport", ["phone", "desktop"])
def test_capture_cards(page, live_server, viewport, theme, lang, priced_plans):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _goto_for_schools(page, live_server, theme, viewport, lang)
    page.wait_for_selector(".pricing-cards")
    assert page.locator(".pricing-cards__item").count() == 3
    page.screenshot(
        path=str(OUT_DIR / f"cards-{viewport}-{theme}-{lang}.png"), full_page=True
    )
