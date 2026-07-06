import pytest
from django.urls import reverse

from tests.factories import make_login
from tests.factories import make_pa


@pytest.mark.django_db
def test_guide_is_public_and_renders_english(client):
    resp = client.get(reverse("integrations:webhook_guide"), HTTP_ACCEPT_LANGUAGE="en")
    assert resp.status_code == 200  # no login required
    body = resp.content.decode()
    assert "Verifying the signature" in body
    assert "<pre>" in body  # a rendered fenced code block


@pytest.mark.django_db
def test_guide_renders_polish_when_language_is_pl(client):
    resp = client.get(reverse("integrations:webhook_guide"), HTTP_ACCEPT_LANGUAGE="pl")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Weryfikacja podpisu" in body  # the PL heading
    assert "Verifying the signature" not in body


@pytest.mark.django_db
def test_pa_sees_guide_link_in_admin_nav(client):
    make_pa(client, "pa")
    resp = client.get(reverse("courses:my_courses"))
    body = resp.content.decode()
    href = reverse("integrations:webhook_guide")
    # the Admin-dropdown entry (distinct from the settings-tab body link)
    assert f'class="menu__item" href="{href}"' in body


@pytest.mark.django_db
def test_non_pa_does_not_see_guide_link(client):
    make_login(client, "joe")  # ordinary authenticated user
    resp = client.get(reverse("courses:my_courses"))
    href = reverse("integrations:webhook_guide")
    assert href not in resp.content.decode()
