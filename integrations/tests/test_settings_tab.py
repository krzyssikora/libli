import pytest
from django.urls import reverse

from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_integrations_tab_renders_for_pa(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings") + "?tab=integrations")
    assert resp.status_code == 200
    # the config form action is present (tab panel rendered)
    assert reverse("institution:settings_integrations").encode() in resp.content
    # the nav entry is present (tab reachable), not just the panel
    assert b"?tab=integrations" in resp.content


def test_non_pa_cannot_post(client):
    make_login(client, "joe")  # ordinary user
    resp = client.post(
        reverse("institution:settings_integrations"),
        {"enabled": "", "url": "", "secret": ""},
    )
    assert resp.status_code in (302, 403)
    assert WebhookEndpoint.objects.filter(enabled=True).count() == 0


def test_pa_saves_endpoint(client):
    make_pa(client, "pa")
    resp = client.post(
        reverse("institution:settings_integrations"),
        {"enabled": "on", "url": "https://r.example/h", "secret": TEST_PASSWORD},
    )
    assert resp.status_code == 302
    ep = WebhookEndpoint.load()
    assert ep.enabled is True
    assert ep.url == "https://r.example/h"
