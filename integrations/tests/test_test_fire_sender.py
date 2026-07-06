import json
import urllib.error
from unittest import mock

import pytest

from integrations import delivery
from integrations.models import WebhookDelivery
from integrations.models import WebhookEndpoint
from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.django_db


def _endpoint():
    ep = WebhookEndpoint.load()
    ep.enabled, ep.url, ep.secret = False, "https://r.example/hook", TEST_PASSWORD
    ep.save()
    return ep


def _ok_resp(status):
    resp = mock.MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: resp
    resp.__exit__ = lambda *a: False
    return resp


def test_success_signs_marks_test_and_persists_nothing():
    ep = _endpoint()
    opener = mock.MagicMock()
    opener.open.return_value = _ok_resp(202)
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        ok, status, detail = delivery.send_test_event(ep)
    assert ok is True and status == 202
    sent = opener.open.call_args.args[0]
    body = sent.data
    assert sent.headers["X-libli-signature"] == delivery.sign(ep.secret, body)
    assert sent.headers["X-libli-delivery"] == "test"
    assert sent.headers["X-libli-event"] == "result_finalized"
    assert json.loads(body)["test"] is True
    assert WebhookDelivery.objects.count() == 0


def test_http_error_reports_code():
    ep = _endpoint()
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.HTTPError(ep.url, 500, "err", None, None)
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        ok, status, detail = delivery.send_test_event(ep)
    assert ok is False and status == 500


def test_timeout_reports_none_status():
    ep = _endpoint()
    opener = mock.MagicMock()
    opener.open.side_effect = urllib.error.URLError("down")
    with mock.patch.object(delivery, "_build_opener", return_value=opener):
        ok, status, detail = delivery.send_test_event(ep)
    assert ok is False and status is None


def test_sample_payload_sentinels():
    p = delivery.SAMPLE_PAYLOAD
    assert p["test"] is True
    assert p["event"] == "result_finalized"
    assert p["student"]["external_id"] == "SAMPLE-STUDENT"
    assert p["group"]["id"] == 0 and p["unit"]["id"] == 0
    assert p["score"] == {"earned": "8.00", "max": "10.00", "percent": 80.0}
