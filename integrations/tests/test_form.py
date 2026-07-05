import pytest

from integrations.forms import IntegrationsForm
from integrations.models import WebhookEndpoint

pytestmark = pytest.mark.django_db


def test_enable_requires_url_and_secret():
    ep = WebhookEndpoint.load()
    form = IntegrationsForm(
        data={"enabled": True, "url": "", "secret": ""}, instance=ep
    )
    assert not form.is_valid()


def test_rejects_non_http_scheme():
    ep = WebhookEndpoint.load()
    form = IntegrationsForm(
        data={"enabled": True, "url": "ftp://x/y", "secret": "s"}, instance=ep
    )
    assert not form.is_valid()
    assert "url" in form.errors


def test_blank_secret_preserves_existing():
    ep = WebhookEndpoint.load()
    ep.secret = "keepme"
    ep.save()
    form = IntegrationsForm(
        data={"enabled": True, "url": "https://r.example/h", "secret": ""},
        instance=ep,
    )
    assert form.is_valid(), form.errors
    form.save()
    ep.refresh_from_db()
    assert ep.secret == "keepme"


def test_new_secret_replaces():
    ep = WebhookEndpoint.load()
    ep.secret = "old"
    ep.save()
    form = IntegrationsForm(
        data={"enabled": True, "url": "https://r.example/h", "secret": "new"},
        instance=ep,
    )
    assert form.is_valid(), form.errors
    form.save()
    ep.refresh_from_db()
    assert ep.secret == "new"
