"""The seventh settings tab: audience + recipient addresses."""

import pytest
from django.urls import reverse

from support.constants import EXTRA_EMAILS_MAX
from support.models import SupportSettings
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def test_a_settings_get_with_no_row_renders_and_writes_nothing(client):
    """The read path must never touch extra_reporters on an unsaved fallback:
    an M2M access on an unsaved instance raises ValueError, and _settings_context
    builds EVERY panel on EVERY tab — so this would 500 a fresh install."""
    make_pa(client)
    response = client.get(reverse("institution:settings"))
    assert response.status_code == 200
    assert SupportSettings.objects.count() == 0


def test_a_pa_can_save_the_audience_and_addresses(client):
    make_pa(client)
    response = client.post(
        reverse("institution:settings_support"),
        {"audience": "teachers", "extra_emails": "One@X.test\n\nhelp@x.test\n"},
    )
    assert response.status_code == 302
    row = SupportSettings.load()
    assert row.audience == "teachers"
    assert row.extra_emails == ["one@x.test", "help@x.test"]  # lower-cased, blanks gone


def test_addresses_round_trip_one_per_line(client):
    """Mutant: leave `initial` as the raw JSON list — the PA then sees
    ['a@b.test'] in the textarea and the next save is rejected."""
    make_pa(client)
    client.post(
        reverse("institution:settings_support"),
        {"audience": "admins", "extra_emails": "a@b.test\nc@d.test"},
    )
    body = client.get(
        reverse("institution:settings"), {"tab": "support"}
    ).content.decode()
    assert "a@b.test\nc@d.test" in body or "a@b.test&#x0A;c@d.test" in body


def test_a_malformed_address_is_rejected(client):
    """count() == 0 is the assertion, not a detail: binding to load() would
    get_or_create the singleton BEFORE is_valid() runs, so an invalid POST would
    silently materialise the row."""
    make_pa(client)
    response = client.post(
        reverse("institution:settings_support"),
        {"audience": "admins", "extra_emails": "not-an-address"},
    )
    assert response.status_code == 200  # re-rendered with the bound form
    assert SupportSettings.objects.count() == 0


def test_too_many_addresses_are_rejected(client):
    make_pa(client)
    addresses = "\n".join(f"a{i}@x.test" for i in range(EXTRA_EMAILS_MAX + 1))
    client.post(
        reverse("institution:settings_support"),
        {"audience": "admins", "extra_emails": addresses},
    )
    assert SupportSettings.objects.count() == 0


def test_a_get_redirects_and_writes_no_row(client):
    """Mutant: drop the GET guard — the view then binds an empty QueryDict and
    re-renders the settings page covered in validation errors."""
    make_pa(client)
    response = client.get(reverse("institution:settings_support"))
    assert response.status_code == 302
    assert SupportSettings.objects.count() == 0


def test_the_support_tab_link_is_rendered(client):
    """Mutant: add "support" to TABS but leave _tabs.html alone — ?tab=support
    becomes valid while no link to it ever appears."""
    make_pa(client)
    body = client.get(reverse("institution:settings")).content.decode()
    assert "?tab=support" in body


def test_the_panel_names_the_platform_admins_who_receive_reports(client):
    pa = make_pa(client)
    pa.email = "chief@school.example"
    pa.save()
    body = client.get(reverse("institution:settings")).content.decode()
    assert "chief@school.example" in body


def test_a_teacher_cannot_save_the_support_tab(client):
    make_teacher(client)
    response = client.post(
        reverse("institution:settings_support"), {"audience": "all", "extra_emails": ""}
    )
    assert response.status_code == 403
