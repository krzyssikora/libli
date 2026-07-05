import pytest

from integrations.forms import IntegrationsForm
from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD

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
        data={"enabled": True, "url": "ftp://x/y", "secret": TEST_PASSWORD},
        instance=ep,
    )
    assert not form.is_valid()
    assert "url" in form.errors


def test_blank_secret_preserves_existing():
    ep = WebhookEndpoint.load()
    ep.secret = TEST_PASSWORD
    ep.save()
    form = IntegrationsForm(
        data={"enabled": True, "url": "https://r.example/h", "secret": ""},
        instance=ep,
    )
    assert form.is_valid(), form.errors
    form.save()
    ep.refresh_from_db()
    assert ep.secret == TEST_PASSWORD


def test_new_secret_replaces():
    new_secret = TEST_PASSWORD + "-rotated"
    ep = WebhookEndpoint.load()
    ep.secret = TEST_PASSWORD
    ep.save()
    form = IntegrationsForm(
        data={"enabled": True, "url": "https://r.example/h", "secret": new_secret},
        instance=ep,
    )
    assert form.is_valid(), form.errors
    form.save()
    ep.refresh_from_db()
    assert ep.secret == new_secret
