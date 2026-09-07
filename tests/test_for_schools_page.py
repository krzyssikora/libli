"""Guards that need the route, the markdown and the tokens together."""

import re

import pytest
from django.test import override_settings
from django.urls import reverse

from institution.models import Institution
from institution.models import PricingPlan
from institution.models import PublicPage

AMOUNTS = re.compile('<p class="pricing-cards__price">([\\d\\u00a0]+\\.\\d{2})</p>')


@pytest.fixture
def priced_plans(db):
    """UPDATES the migration-seeded rows; never creates.

    pyproject.toml's addopts sets no --nomigrations, so RunPython(seed, ...) runs
    against every test database and orders 1/2/3 already exist -- create(order=1)
    raises IntegrityError on the unique `order`. Creating 4/5/6 instead would
    silently make a six-row, gapped, non-monotonic band set that breaks the
    three-row invariant and shifts the fourth tier's label.
    """
    for order, price in ((1, "4800.00"), (2, "7200.00"), (3, "10800.00")):
        PricingPlan.objects.filter(order=order).update(annual_price=price)
    return PricingPlan.objects.order_by("order")


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_english_and_polish_show_identical_figures(client, priced_plans):
    """THE guard that justifies the whole token approach.

    Assert the Polish page actually resolved as Polish FIRST: localized_doc_path
    falls back to the English base when for-schools.pl.md is absent, so a naive
    version compares English against English and is green with no Polish page at
    all -- the exact adjacent-thing shape.
    """
    en = client.get(reverse("core:for_schools"), headers={"accept-language": "en"})
    pl = client.get(reverse("core:for_schools"), headers={"accept-language": "pl"})
    assert pl.context["resolved_lang"] == "pl"

    en_amounts = AMOUNTS.findall(en.content.decode())
    pl_amounts = AMOUNTS.findall(pl.content.decode())
    assert len(en_amounts) >= 3, "non-vacuity: no amounts extracted"
    assert en_amounts == pl_amounts


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_polish_support_bound_label_is_not_the_settings_tab_word(client, priced_plans):
    """Kills the mutant where the card's "Support" bound label shares a msgid
    with the unrelated settings-tab "Support" link (locale/pl: "Zgłoszenia",
    i.e. Reports/Tickets). If _plans_html ever goes back to a bare
    gettext("Support") the Polish cards would carry that domain-specific
    translation instead of a word for support hours -- wrong on the vendor's
    own sales page.
    """
    pl = client.get(reverse("core:for_schools"), headers={"accept-language": "pl"})
    assert pl.context["resolved_lang"] == "pl"
    body = pl.content.decode()

    # The label sits inside <strong>, immediately before the value, in each
    # card's bounds list: <li><strong>{label}:</strong> {value}</li>.
    labels = re.findall(r"<strong>(.*?)</strong>", body)
    assert "Wsparcie:" in labels
    assert not any("Zgłoszenia" in label for label in labels)


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_page_renders_on_a_genuinely_fresh_install(client, priced_plans):
    """Task 3 covers the early-return trap at the BUNDLE layer; this covers the
    PAGE. The renderer touches contact_email, currency, storage_allowance_gb and
    both vat_note_* keys, so a key missing from the no-Institution branch is a 500
    on the first thing a new box does."""
    Institution.objects.all().delete()
    response = client.get(reverse("core:for_schools"))
    assert response.status_code == 200
    # the CARDS, not the fallback paragraph
    assert 'class="pricing-cards"' in response.content.decode()


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_row_order_survives_editing_a_middle_band(client, priced_plans):
    PricingPlan.objects.filter(order=2).update(annual_price="7300.00")
    body = client.get(reverse("core:for_schools")).content.decode()
    amounts = AMOUNTS.findall(body)
    assert amounts == ["4 800.00", "7 300.00", "10 800.00"]


def test_the_explicit_order_by_is_pinned_at_the_source():
    """Named honestly: with Meta.ordering present, dropping the explicit
    .order_by leaves the rendered-order test green, so a behavioural test cannot
    kill that mutant. Pin it the way
    test_demo_instance_is_a_bare_read_not_a_coalesced_one pins its rule."""
    import inspect

    from core import services

    assert 'order_by("order")' in inspect.getsource(services._pricing_plans)


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("lang", ["en", "pl"])
def test_anonymous_access_to_all_three_public_pages(client, lang):
    for name in ("core:privacy", "core:getting_started", "core:for_schools"):
        response = client.get(reverse(name), headers={"accept-language": lang})
        assert response.status_code == 200


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_a_publicpage_override_still_wins_for_the_new_page(client):
    PublicPage.objects.create(
        slug="for-schools", language="en", body_markdown="# Overridden\n\nBody.\n"
    )
    body = client.get(reverse("core:for_schools")).content.decode()
    assert "Overridden" in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
@pytest.mark.parametrize("path", ["/", "/for-schools/"])
def test_no_django_template_comment_leaks(client, path):
    """The settings-page surface is covered in Task 14; these are the other two
    the change touches (landing.html is edited, /for-schools/ is new)."""
    assert "{#" not in client.get(path).content.decode()
