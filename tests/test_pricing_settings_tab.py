"""The Pricing tab: gated like the page, and validating like an admin surface.

The tab is gated for the same reason /for-schools/ is, only more strongly -- on a
school's box a school admin would otherwise edit OUR pupil bands and prices,
pre-seeded with our structural placeholders.
"""

import re

import pytest
from django.test import override_settings
from django.urls import reverse

from institution.models import PricingPlan
from tests.factories import make_pa


def _post_data(bands):
    """bands: [(min, max), ...] for orders 1..3."""
    data = {}
    for order, (lo, hi) in enumerate(bands, start=1):
        data[f"plan_{order}_pupils_min"] = lo
        data[f"plan_{order}_pupils_max"] = hi
        data[f"plan_{order}_annual_price"] = ""
        data[f"plan_{order}_support_hours_per_term"] = 6
        data[f"plan_{order}_courses_included"] = 3
        data[f"plan_{order}_video_hours_included"] = 10
    data["currency"] = "PLN"
    return data


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_the_tab_404s_on_a_school_box(client):
    make_pa(client)
    response = client.post(
        reverse("institution:settings_pricing"),
        _post_data([(1, 150), (151, 400), (401, 800)]),
    )
    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_the_tab_is_absent_from_the_settings_page_on_a_school_box(client):
    make_pa(client)
    body = client.get(reverse("institution:settings")).content.decode()
    assert "?tab=pricing" not in body
    assert "plan_1_pupils_min" not in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_tab_is_present_on_the_vendor_box(client):
    """Locks the `_tabs.html` tab LINK: it renders (and the panel markup is in
    the response) when VENDOR_INSTANCE is on. It does NOT lock per-request
    evaluation of `_tabs()` -- that guarantee belongs to
    test_the_pricing_panel_is_not_hidden_on_tab_pricing below. Proven by mutant
    testing: freezing `_tabs()` to a module-level tuple computed once at import
    does NOT redden this test (the tab link and the hidden panel markup both
    still render regardless of which tabs `_tabs()` returns at request time),
    while it DOES redden the other test (active_tab falls back to "branding",
    so the panel renders with `hidden` set)."""
    make_pa(client)
    body = client.get(reverse("institution:settings") + "?tab=pricing").content.decode()
    # BOTH, mirroring the flag-off test's two absences: without the link
    # assertion a build that renders the panel but forgets the _tabs.html include
    # stays green on this half.
    assert "?tab=pricing" in body
    assert "plan_1_pupils_min" in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_pricing_panel_is_not_hidden_on_tab_pricing(client):
    """A bare, unconditional `hidden` on the panel div renders it permanently
    closed: ?tab=pricing would show nothing, and _action's invalid-form
    re-render (which sets active_tab="pricing") would hand the admin a page with
    no VISIBLE errors. `"plan_1_pupils_min" in body` alone cannot catch this --
    that string is true of hidden markup too -- so this asserts directly on the
    data-tab="pricing" div's own hidden attribute."""
    make_pa(client)
    body = client.get(reverse("institution:settings") + "?tab=pricing").content.decode()
    match = re.search(r'<div data-tab="pricing"([^>]*)>', body)
    assert match, 'no data-tab="pricing" panel div in the response'
    assert "hidden" not in match.group(1), (
        "the pricing panel is hidden while ?tab=pricing is active"
    )


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_reversed_band_is_a_form_error_not_a_500(client):
    """THE regression this validation exists for. (1,150),(151,400),(401,300) has
    no gap and no overlap BETWEEN CONSECUTIVE ROWS, so a clean() carrying only the
    cross-row rules passes it -- and save() then hits the CheckConstraint, raising
    IntegrityError out of _action, which has no handler. An admin who types two
    numbers the wrong way round gets a 500.
    """
    make_pa(client)
    response = client.post(
        reverse("institution:settings_pricing"),
        _post_data([(1, 150), (151, 400), (401, 300)]),
    )
    assert response.status_code == 200  # re-rendered, not 302, not 500
    # The status alone is only a proxy: _action returns 200 exclusively on an
    # invalid form TODAY, and that coupling is invisible here. Assert the errors.
    assert response.context["pricing"].errors
    # response.context["pricing"].errors is a property of the FORM OBJECT, not
    # of the rendered page -- it stays true even if _pricing_tab.html renders
    # none of the six {{ row.*.errors }} calls, which would hand the admin a
    # 200 with no visible explanation (the same "no visible errors" outcome the
    # `hidden` trap describes, one layer deeper: the panel is open, but silent).
    # Assert the error text actually reaches the response body.
    assert "greater than the lower bound" in response.content.decode()


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize(
    "bands",
    [
        [(1, 150), (100, 400), (401, 800)],  # overlap
        [(1, 150), (200, 400), (401, 800)],  # gap
        [(1, 150), (401, 800), (151, 400)],  # non-monotonic
    ],
)
def test_cross_row_band_rules_are_rejected(client, bands):
    make_pa(client)
    response = client.post(reverse("institution:settings_pricing"), _post_data(bands))
    assert response.status_code == 200
    assert response.context["pricing"].errors


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_valid_save_persists_and_redirects(client):
    make_pa(client)
    data = _post_data([(1, 150), (151, 400), (401, 900)])
    data["plan_3_annual_price"] = "10800.00"
    response = client.post(reverse("institution:settings_pricing"), data)
    assert response.status_code == 302
    row = PricingPlan.objects.get(order=3)
    assert row.pupils_max == 900
    assert str(row.annual_price) == "10800.00"


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_no_django_template_comment_leaks_into_the_settings_page(client):
    """{# #} is single-line only; a two-line one renders as visible text. Shipped
    five times. _pricing_tab.html is the largest new template in this change, and
    /for-schools/ renders none of these templates."""
    make_pa(client)
    body = client.get(reverse("institution:settings") + "?tab=pricing").content.decode()
    assert "{#" not in body
