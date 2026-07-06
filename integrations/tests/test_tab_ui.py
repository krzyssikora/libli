import pytest
from django.urls import reverse

from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _tab(client):
    return client.get(reverse("institution:settings") + "?tab=integrations")


def test_tab_shows_guide_link_and_test_form(client):
    make_pa(client, "pa")
    body = _tab(client).content.decode()
    assert reverse("integrations:webhook_guide") in body
    assert reverse("institution:settings_integrations_test") in body


def test_test_button_disabled_when_unconfigured(client):
    make_pa(client, "pa")  # nothing saved
    body = _tab(client).content.decode()
    assert "data-test-fire" in body
    i = body.index("data-test-fire")
    snippet = body[i - 120 : i + 120]
    assert "disabled" in snippet


def test_test_button_enabled_when_configured(client):
    make_pa(client, "pa")
    ep = WebhookEndpoint.load()
    ep.url, ep.secret = "https://r.example/h", TEST_PASSWORD
    ep.save()
    body = _tab(client).content.decode()
    # the test-fire button is present without a disabled attribute
    assert "data-test-fire" in body
    marker = "data-test-fire"
    snippet = body[body.index(marker) - 120 : body.index(marker) + 20]
    assert "disabled" not in snippet
