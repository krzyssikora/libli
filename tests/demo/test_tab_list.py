from datetime import timedelta

import pytest
from django.utils import timezone

from demo.models import DemoKit
from demo.services import revoke_kit
from tests.demo.fixtures import small_course
from tests.demo.helpers import provision_for_test
from tests.demo.tab_helpers import demo_tab_url
from tests.demo.tab_helpers import row_ids
from tests.demo.tab_helpers import soup


def test_the_tab_is_absent_on_a_school_box(pa_client):
    """P3, panel half. Flag off: no link, no panel, and ?tab=demo falls back to
    branding with a 200 — a hidden tab is not a 404."""
    response = pa_client.get(demo_tab_url())
    body = response.content.decode()

    assert response.status_code == 200
    assert response.context["active_tab"] == "branding"
    assert "?tab=demo" not in body
    assert "data-demo-list" not in body


def test_the_tab_is_present_and_open_on_the_vendor_box(pa_client, vendor):
    response = pa_client.get(demo_tab_url())
    page = soup(response)

    assert response.context["active_tab"] == "demo"
    assert page.select_one('a[href$="?tab=demo"]') is not None
    panel = page.select_one('div[data-tab="demo"]')
    assert panel is not None and not panel.has_attr("hidden")
    assert panel.select_one("[data-demo-list]") is not None


def test_the_panel_renders_nothing_on_another_tab(pa_client, vendor):
    """Spec §4.1: the hidden panel on other tabs renders nothing against the None
    context, and builds no kit list."""
    response = pa_client.get(demo_tab_url().replace("tab=demo", "tab=branding"))

    assert response.context["demo_kits"] is None
    assert "data-demo-list" not in response.content.decode()


def test_the_list_shows_open_kits_newest_first_and_all_adds_closed(pa_client, vendor):
    """P11."""
    course = small_course()
    oldest = provision_for_test(course, label="Alpha")
    middle = provision_for_test(course, label="Beta")
    newest = provision_for_test(course, label="Gamma")
    DemoKit.objects.filter(pk=middle.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    revoke_kit(oldest)

    default = pa_client.get(demo_tab_url())
    assert row_ids(default) == [newest.pk, middle.pk]

    everything = pa_client.get(demo_tab_url(show_all=True))
    assert row_ids(everything) == [newest.pk, middle.pk, oldest.pk]
    closed_row = soup(everything).select_one(f'tr[data-demo-kit="{oldest.pk}"]')
    assert "—" in closed_row.get_text()  # the teacher FK was nulled by the purge


def test_status_display_covers_every_status_key():
    from demo.models import STATUS_DISPLAY

    keys = {"active", "pending_purge"} | {
        f"closed_{value}" for value in DemoKit.ClosedReason.values
    }
    assert set(STATUS_DISPLAY) == keys


@pytest.mark.parametrize("value", ["0", "yes", "true"])
def test_only_the_literal_one_shows_closed_kits(pa_client, vendor, value):
    course = small_course()
    closed = provision_for_test(course, label="Closed")
    revoke_kit(closed)

    response = pa_client.get(demo_tab_url() + f"&all={value}")
    assert row_ids(response) == []
