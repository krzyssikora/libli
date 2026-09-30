"""PWA C1: the standalone offline page (spec §4)."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import get_template
from django.urls import reverse

from institution.models import Institution
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

FAVICON_SVG = Path(settings.BASE_DIR) / "core/static/core/img/favicon/favicon.svg"


def test_offline_is_public_uncached_and_unindexed(client):
    r = client.get(reverse("core:offline"))
    assert r.status_code == 200
    assert r["Cache-Control"] == "no-store"
    assert r["X-Robots-Tag"] == "noindex"


def test_offline_page_never_shows_the_requesting_user(client):
    user = make_verified_user(
        username="offline-probe-user", email="offline-probe@probe.example.com"
    )
    client.force_login(user)
    body = client.get(reverse("core:offline")).content.decode()
    assert "offline-probe-user" not in body
    assert "offline-probe@probe.example.com" not in body
    assert "bell" not in body  # the notification bell's markup
    assert "data-account-menu" not in body


def test_offline_page_loads_nothing_from_static(client):
    body = client.get(reverse("core:offline")).content.decode()
    assert "/static/" not in body
    assert not re.search(r"<(script|link)[^>]+(src|href)=", body)


def test_offline_page_shows_the_current_name(client):
    inst = Institution.load()
    Institution.objects.filter(pk=inst.pk).update(name="Szkoła Testowa")
    assert "Szkoła Testowa" in client.get(reverse("core:offline")).content.decode()


def test_offline_template_is_self_contained():
    source = get_template("core/offline.html").template.source
    assert "{% include" not in source
    assert "{% extends" not in source


def test_offline_mark_matches_the_favicon():
    """The inlined libli mark must not drift from the shipped favicon."""
    source = get_template("core/offline.html").template.source
    for line in FAVICON_SVG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(("<rect", "<circle")):
            assert line in source, line


def test_offline_button_uses_the_primary_only_as_a_border(client):
    body = client.get(reverse("core:offline")).content.decode()
    assert "border-color: #147E78" in body or "border-color:#147E78" in body
    assert "location.reload()" in body
    assert 'addEventListener("online"' in body
