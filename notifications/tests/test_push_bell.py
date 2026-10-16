import pytest
from django.urls import reverse

from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import push_settings

pytestmark = pytest.mark.django_db


def _html(client):
    logged_in_user(client)
    return client.get(reverse("core:user_settings")).content.decode()


def test_invite_absent_on_a_dark_box(client):
    assert "data-push-invite" not in _html(client)


def test_invite_rendered_hidden_when_configured(client, settings):
    push_settings(settings)
    html = _html(client)
    start = html.index("data-push-invite")
    tag = html[html.rindex("<", 0, start) : html.index(">", start)]
    assert " hidden" in tag
    assert "data-push-invite-on" in html and "data-push-invite-dismiss" in html


def test_invite_present_with_an_empty_panel(client, settings):
    push_settings(settings)
    html = _html(client)
    assert "You have no notifications yet." in html
    assert "data-push-invite" in html
