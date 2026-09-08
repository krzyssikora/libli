"""The vendor page exists only on the vendor box."""

import pytest
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=False)
def test_404s_on_a_school_box(client):
    """404 rather than 403 or an empty 200: the page genuinely does not exist
    there, and a school must never see our price list."""
    assert client.get(reverse("core:for_schools")).status_code == 404


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_renders_anonymously_on_the_vendor_box(client):
    response = client.get(reverse("core:for_schools"))
    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_renders_in_polish(client):
    response = client.get(
        reverse("core:for_schools"), headers={"accept-language": "pl"}
    )
    assert response.status_code == 200


def test_demo_notice_slugs_lives_in_production_code_and_excludes_for_schools():
    """_page_overrides() (production) cannot import a set from tests/, and SHIPPED
    holds markdown PATHS while _page_overrides iterates SLUGS -- so the canonical
    set is slugs, defined beside PAGES."""
    from core.public_pages import DEMO_NOTICE_SLUGS
    from core.public_pages import VENDOR_ONLY_SLUGS

    # TWO sets, deliberately separate -- see the definition comment. Asserting
    # both here also stops the second being flagged F401.
    assert DEMO_NOTICE_SLUGS == {"privacy", "getting-started"}
    assert VENDOR_ONLY_SLUGS == {"for-schools"}
