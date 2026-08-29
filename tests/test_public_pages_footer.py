import pytest
from django.urls import reverse

from tests.factories import make_verified_user


@pytest.mark.django_db
def test_landing_footer_links_both_pages_and_drops_the_en_pl_span(client):
    body = client.get(reverse("landing")).content.decode()
    assert reverse("core:privacy") in body
    assert reverse("core:getting_started") in body
    # The span duplicated the header switcher, which is already live for
    # anonymous visitors. It must be gone, not merely hidden.
    assert "EN / PL" not in body


@pytest.mark.django_db
def test_entrance_pages_carry_both_links(client):
    body = client.get(reverse("account_login")).content.decode()
    assert reverse("core:privacy") in body
    assert reverse("core:getting_started") in body


@pytest.mark.django_db
def test_authenticated_home_renders_no_footer(client):
    user = make_verified_user()
    client.force_login(user)
    body = client.get(reverse("home")).content.decode()
    assert reverse("core:privacy") not in body


@pytest.mark.django_db
def test_public_pages_carry_the_footer(client):
    body = client.get(reverse("core:privacy")).content.decode()
    assert reverse("core:getting_started") in body
