"""PWA C1: pwa.js inclusion, the Install app item and the [hidden] rule."""

import re
from pathlib import Path

import pytest
from django.conf import settings as dj_settings
from django.urls import reverse

from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db

APP_CSS = Path(dj_settings.BASE_DIR) / "core/static/core/css/app.css"


def test_pwa_js_included_only_when_enabled(client, settings):
    settings.PWA_ENABLED = True
    settings.PWA_KILL_SWITCH = False
    assert "core/js/pwa.js" in client.get(reverse("account_login")).content.decode()
    settings.PWA_KILL_SWITCH = True
    assert "core/js/pwa.js" not in client.get(reverse("account_login")).content.decode()
    settings.PWA_ENABLED = False
    settings.PWA_KILL_SWITCH = False
    assert "core/js/pwa.js" not in client.get(reverse("account_login")).content.decode()
    settings.PWA_KILL_SWITCH = True
    assert "core/js/pwa.js" not in client.get(reverse("account_login")).content.decode()


def test_account_menu_links_the_install_guide(client):
    client.force_login(
        make_verified_user(username="menu-probe", email="m@probe.example.com")
    )
    body = client.get(reverse("home")).content.decode()
    m = re.search(r'<a class="menu__item" href="([^"]+)" data-install-app>', body)
    assert m and m.group(1) == reverse("core:install_app")


def test_install_item_renders_with_the_worker_off(client, settings):
    settings.PWA_ENABLED = False
    client.force_login(
        make_verified_user(username="menu-off", email="o@probe.example.com")
    )
    assert "data-install-app" in client.get(reverse("home")).content.decode()


def test_menu_item_hidden_attribute_is_honoured():
    """.menu__item sets display:block, which beats the UA [hidden] rule."""
    css = APP_CSS.read_text(encoding="utf-8")
    assert re.search(r"\.menu__item\[hidden\]\s*\{\s*display:\s*none;\s*\}", css)


def test_pwa_js_prevents_the_prompt_before_anything_else():
    js = (Path(dj_settings.BASE_DIR) / "core/static/core/js/pwa.js").read_text(
        encoding="utf-8"
    )
    listener = js[js.index('"beforeinstallprompt"') :]
    assert listener.index("preventDefault()") < listener.index("return")
