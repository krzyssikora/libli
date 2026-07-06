from unittest import mock

import pytest
from django.urls import reverse

from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

URL = "institution:settings_integrations_test"


def _configure(enabled=False):
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = enabled, "https://r.example/hook", TEST_PASSWORD
    ep.save()


def test_pa_test_fire_success(client):
    make_pa(client, "pa")
    _configure(enabled=False)  # disabled but configured → must still send
    with mock.patch(
        "institution.views_manage.send_test_event", return_value=(True, 200, "")
    ) as m:
        resp = client.post(reverse(URL))
    assert resp.status_code == 302
    assert m.called  # enabled flag is NOT required to test


def test_unconfigured_does_not_send(client):
    make_pa(client, "pa")  # no endpoint saved → blank url/secret
    with mock.patch("institution.views_manage.send_test_event") as m:
        resp = client.post(reverse(URL))
    assert resp.status_code == 302
    assert not m.called


def test_non_pa_rejected(client):
    make_login(client, "joe")
    _configure()
    with mock.patch("institution.views_manage.send_test_event") as m:
        resp = client.post(reverse(URL))
    assert resp.status_code in (302, 403)
    assert not m.called


def test_get_redirects(client):
    make_pa(client, "pa")
    resp = client.get(reverse(URL))
    assert resp.status_code == 302
