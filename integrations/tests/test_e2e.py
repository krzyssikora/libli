import pytest
from django.urls import reverse
from django.utils import translation

pytestmark = pytest.mark.django_db


def test_status_label_translates_pl():
    from integrations.models import WebhookDelivery

    with translation.override("pl"):
        label = str(WebhookDelivery.Status.PENDING.label)
    assert label == "Oczekuje"


def test_pa_configures_endpoint_and_panel_renders(client):
    from integrations.models import WebhookDelivery
    from tests.factories import make_pa

    make_pa(client, "pa")
    # Configure via the real form POST.
    client.post(
        reverse("institution:settings_integrations"),
        {"enabled": "on", "url": "https://r.example/h", "secret": "shh"},
    )
    # A delivery exists → the panel lists it.
    WebhookDelivery.objects.create(dedupe_key="1:", payload={"event": "x"})
    resp = client.get(reverse("institution:settings") + "?tab=integrations")
    assert resp.status_code == 200
    assert b"Recent deliveries" in resp.content or b"Ostatnie" in resp.content
