"""The "For schools" link, over every surface, both directions.

There are TWO footers: templates/core/_public_footer.html (included by
public_page.html AND allauth/layouts/entrance.html) and a DUPLICATED link block
in templates/core/landing.html. tests/test_public_pages_footer.py already asserts
them separately for exactly this reason -- someone editing "the footer" misses
the landing page, which is where an anonymous school visitor actually arrives.
"""

import pytest
from django.test import override_settings
from django.urls import reverse

SURFACES = ["/", "/privacy/", "/accounts/login/"]


@pytest.mark.django_db
@pytest.mark.parametrize("path", SURFACES)
@override_settings(VENDOR_INSTANCE=True)
def test_link_present_on_every_surface_on_the_vendor_box(client, path):
    response = client.get(path)
    # Without this, a surface that redirects would fail the body assertion
    # below for a misleading reason (the link is missing because the page
    # never rendered, not because the guard is wrong).
    assert response.status_code == 200
    body = response.content.decode()
    assert reverse("core:for_schools") in body


@pytest.mark.django_db
@pytest.mark.parametrize("path", SURFACES)
@override_settings(VENDOR_INSTANCE=False)
def test_link_absent_on_every_surface_on_a_school_box(client, path):
    response = client.get(path)
    # Without this, a surface that redirects passes the absence assertion
    # below for the wrong reason -- an empty/redirect body trivially contains
    # no link, whether or not the guard actually works.
    assert response.status_code == 200
    body = response.content.decode()
    assert "/for-schools/" not in body


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_context_processor_exposes_the_flag(client):
    response = client.get("/")
    assert response.context["vendor_instance"] is True
