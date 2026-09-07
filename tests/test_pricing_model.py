"""PricingPlan's shape, its database constraint, and the migration seed.

The constraint is a BACKSTOP for out-of-band writes. The admin-facing check is
the pricing form's clean() (Task 14) -- Django never calls full_clean() on
save(), so a model clean() here would be dead code.
"""

from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.db import transaction

from institution.models import Institution
from institution.models import PricingPlan


@pytest.mark.django_db
def test_migration_seeds_three_bands_priceless():
    """The shipped state: three gap-free monotonic bands, no prices."""
    rows = list(PricingPlan.objects.order_by("order"))
    assert [(r.order, r.pupils_min, r.pupils_max) for r in rows] == [
        (1, 1, 100),
        (2, 101, 300),
        (3, 301, 500),
    ]
    assert [r.annual_price for r in rows] == [None, None, None]
    assert [r.support_hours_per_term for r in rows] == [6, 8, 12]
    assert [r.courses_included for r in rows] == [3, 6, 12]
    assert [r.video_hours_included for r in rows] == [10, 20, 40]


@pytest.mark.django_db
def test_seeded_bands_are_gap_free_and_monotonic():
    """The seed must satisfy the form's own cross-row rules, or the settings tab
    rejects the shipped state on an operator's first save."""
    rows = list(PricingPlan.objects.order_by("order"))
    # strict=False: the pairwise walk is deliberately one shorter than rows.
    for lo, hi in zip(rows, rows[1:], strict=False):
        assert hi.pupils_min == lo.pupils_max + 1


@pytest.mark.django_db
def test_constraint_rejects_a_reversed_band():
    """Wrapped in atomic(): an IntegrityError poisons the surrounding pytest-django
    transaction, and any later ORM call would raise TransactionManagementError and
    read as an unrelated failure."""
    row = PricingPlan.objects.get(order=1)
    row.pupils_min, row.pupils_max = 300, 200
    with pytest.raises(IntegrityError), transaction.atomic():
        row.save()


@pytest.mark.django_db
def test_constraint_rejects_equal_bounds():
    """Kills the lte mutant: condition=Q(pupils_min__lte=F("pupils_max")) would
    ACCEPT min == max, a zero-pupil band. The hard-reversal case above (300, 200)
    cannot catch that widening -- 300 <= 200 is exactly as false as 300 < 200 --
    so this boundary case is the only thing that pins the constraint to a strict
    less-than."""
    row = PricingPlan.objects.get(order=1)
    row.pupils_min, row.pupils_max = 200, 200
    with pytest.raises(IntegrityError), transaction.atomic():
        row.save()


@pytest.mark.django_db
def test_institution_pricing_field_defaults():
    inst = Institution.load()
    assert inst.currency == "PLN"
    assert inst.vat_note_en == ""
    assert inst.vat_note_pl == ""
    assert inst.storage_allowance_gb is None


@pytest.mark.django_db
def test_annual_price_accepts_two_decimal_places():
    row = PricingPlan.objects.get(order=1)
    row.annual_price = Decimal("4800.00")
    row.save()
    assert PricingPlan.objects.get(order=1).annual_price == Decimal("4800.00")
