"""Regression guard for the auth redesign layout (mirrors test_settings_styles.py).

Asserts auth.css defines the bespoke .auth-* vocabulary, that the entrance override
extends base.html and re-skins the chrome, and that the extra_body bridge survives.
"""

from pathlib import Path

from django.template.loader import render_to_string

ROOT = Path(__file__).resolve().parent.parent
AUTH_CSS = ROOT / "core" / "static" / "core" / "css" / "auth.css"
ENTRANCE = ROOT / "templates" / "allauth" / "layouts" / "entrance.html"


def test_auth_css_defines_card_vocabulary():
    css = AUTH_CSS.read_text(encoding="utf-8")
    for cls in (
        ".auth-main",
        ".auth-card",
        ".auth-card__wordmark",
        ".auth-card__title",
        ".auth-label",
        ".auth-input",
        ".auth-divider",
        ".auth-sso",
        ".auth-foot",
        ".auth-error",
        ".auth-chrome",
    ):
        assert cls in css, f"auth.css must style {cls}"


def test_auth_css_is_token_only_no_raw_hex():
    import re

    css = AUTH_CSS.read_text(encoding="utf-8")
    # The Google-logo conic-gradient is the one allowed brand-fixed exception.
    scanned = "\n".join(l for l in css.splitlines() if "conic-gradient" not in l)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", scanned), "auth.css must use tokens, not raw hex"


def test_entrance_override_extends_base_and_reskins():
    body = ENTRANCE.read_text(encoding="utf-8")
    assert '{% extends "base.html" %}' in body
    assert "auth-main" in body  # main_class
    assert "auth-chrome" in body  # header reskin
    assert "core/css/auth.css" in body  # loads auth.css via extra_css
    # Must NOT redeclare an empty content block (children fill base.html's directly).
    assert "{% block content %}" not in body


def test_extra_body_bridge_renders_through():
    # A template extending the entrance chain must surface its extra_body content.
    # (tests/templates is on TEMPLATES DIRS via config/settings/test.py, Step 5.)
    out = render_to_string("_extra_body_probe.html")
    assert "EXTRA_BODY_PROBE_MARKER" in out
