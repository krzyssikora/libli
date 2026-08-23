"""Telemetry allow-listing, bounds, rendering rows and page-URL link safety."""

import pytest
from django.contrib.sites.models import Site
from django.test import RequestFactory

from support.telemetry import TELEMETRY_CAPS
from support.telemetry import TELEMETRY_LABELS
from support.telemetry import safe_page_link
from support.telemetry import sanitise
from support.telemetry import telemetry_rows


@pytest.fixture(autouse=True)
def _clear_site_cache():
    """django.contrib.sites keeps a module-level SITE_CACHE. clear_site_cache
    fires on pre_save, but safe_page_link immediately re-populates it INSIDE the
    test transaction — so the rollback restores the row while the cache keeps
    "libli.example"/"localhost" for the rest of the pytest worker, poisoning any
    later test that reads Site.domain. The root conftest does not clear it."""
    yield
    Site.objects.clear_cache()


def _request(post=None, **meta):
    return RequestFactory().post("/report/", data=post or {}, **meta)


def test_unknown_keys_are_dropped():
    data = sanitise(_request({"viewport_w": "800", "evil": "payload"}))
    assert "evil" not in data
    assert data["viewport_w"] == 800


def test_over_long_strings_are_truncated():
    data = sanitise(_request({"timezone": "z" * 500}))
    assert len(data["timezone"]) == TELEMETRY_CAPS["timezone"]


def test_out_of_range_numbers_are_dropped_not_clamped():
    """A clamped 20000px viewport is a plausible-looking lie in a diagnostic
    record; an absent key is honestly absent."""
    data = sanitise(_request({"viewport_w": "999999", "viewport_h": "0"}))
    assert "viewport_w" not in data
    assert "viewport_h" not in data


def test_non_numeric_numbers_are_dropped():
    assert "viewport_w" not in sanitise(_request({"viewport_w": "wide"}))


def test_theme_accepts_only_the_two_real_values():
    assert sanitise(_request({"theme": "dark"}))["theme"] == "dark"
    assert "theme" not in sanitise(_request({"theme": "neon"}))


def test_server_facts_win_over_a_forged_payload():
    request = _request(
        {"user_agent": "forged", "accept_language": "forged"},
        HTTP_USER_AGENT="RealBrowser/1.0",
        HTTP_ACCEPT_LANGUAGE="pl",
    )
    data = sanitise(request)
    assert data["user_agent"] == "RealBrowser/1.0"
    assert data["accept_language"] == "pl"


def test_rows_follow_the_label_order_and_omit_dropped_keys():
    rows = telemetry_rows({"theme": "dark", "viewport_w": 800})
    keys = [key for key, _label, _value in rows]
    assert keys == [k for k in TELEMETRY_LABELS if k in {"theme", "viewport_w"}]
    assert len(rows) == 2


@pytest.mark.django_db
def test_safe_page_link_rejects_javascript_and_foreign_hosts():
    site = Site.objects.get_current()
    site.domain = "libli.example"
    site.save()
    assert safe_page_link("javascript:alert(1)") is None
    assert safe_page_link("https://evil.test/x") is None
    assert (
        safe_page_link("https://libli.example/units/3/")
        == "https://libli.example/units/3/"
    )


@pytest.mark.django_db
def test_safe_page_link_ignores_the_port_when_matching_the_site():
    site = Site.objects.get_current()
    site.domain = "localhost"
    site.save()
    assert safe_page_link("http://localhost:8000/home/") is not None
