"""The plan rows reach the renderer through cfg, and a price edit is visible now.

substitute_tokens takes cfg as an argument and core/services.py documents the
bundle as the injectable single source of truth that NEVER writes -- so the
renderer must do no ORM query of its own, or every render of /privacy/ would pay
for it too.
"""

from decimal import Decimal

import pytest
from django.core.cache import cache

from core.services import _DEFAULTS
from core.services import get_site_config
from institution.models import Institution
from institution.models import PricingPlan


@pytest.mark.django_db
def test_bundle_carries_the_seeded_plans_in_order():
    plans = get_site_config()["pricing_plans"]
    assert [p["order"] for p in plans] == [1, 2, 3]
    assert plans[0]["pupils_min"] == 1
    assert plans[-1]["pupils_max"] == 800


@pytest.mark.django_db
def test_annual_price_is_a_decimal_not_a_preformatted_string():
    """Formatting stays in the renderer, which is the layer the parity test reads."""
    PricingPlan.objects.filter(order=1).update(annual_price=Decimal("4800.00"))
    cache.clear()
    assert get_site_config()["pricing_plans"][0]["annual_price"] == Decimal("4800.00")


@pytest.mark.django_db
def test_plans_survive_the_no_institution_row_path():
    """THE early-return trap. PricingPlan has no FK to Institution, and _build()
    returns dict(_DEFAULTS) early when there is no Institution row -- so a query
    placed after that branch hands back [] with the rows sitting unread in the
    database, and the page shows the no-prices fallback while priced plans exist.

    A price is set first because with all prices null the two builds are
    byte-identical downstream and this test could not discriminate.
    """
    PricingPlan.objects.filter(order=1).update(annual_price=Decimal("4800.00"))
    Institution.objects.all().delete()
    cache.clear()
    plans = get_site_config()["pricing_plans"]
    assert [p["order"] for p in plans] == [1, 2, 3]
    assert plans[0]["annual_price"] == Decimal("4800.00")


@pytest.mark.django_db
def test_defaults_carry_the_pricing_keys():
    assert _DEFAULTS["pricing_plans"] == []
    assert _DEFAULTS["currency"] == "PLN"
    assert _DEFAULTS["vat_note_en"] == ""
    assert _DEFAULTS["vat_note_pl"] == ""
    assert _DEFAULTS["storage_allowance_gb"] is None


@pytest.mark.django_db
def test_a_price_edit_invalidates_the_cache():
    """PRIME THE CACHE FIRST. tests/conftest.py's autouse _clear_site_cache calls
    cache.clear() before every test, so a test that edits and THEN reads finds an
    empty cache, rebuilds from the database, and sees the new price whether or not
    PricingPlan is in core/apps.py's signal tuple -- the mutant survives.
    """
    assert get_site_config()["pricing_plans"][0]["annual_price"] is None  # primes
    row = PricingPlan.objects.get(order=1)
    row.annual_price = Decimal("5100.00")
    row.save()
    assert get_site_config()["pricing_plans"][0]["annual_price"] == Decimal("5100.00")
