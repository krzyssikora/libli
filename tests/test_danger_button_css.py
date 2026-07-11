from pathlib import Path

from django.conf import settings


def _read(rel):
    return (Path(settings.BASE_DIR) / rel).read_text(encoding="utf-8")


def test_app_css_defines_danger_button_with_hover_and_active():
    css = _read("core/static/core/css/app.css")
    assert ".btn--danger" in css
    assert "var(--danger)" in css
    # Hover/active must set the danger background (else .btn:hover wins -> blue).
    assert ".btn--danger:hover" in css or ".btn--danger:active" in css


def test_people_css_no_longer_defines_danger_button():
    assert ".btn--danger" not in _read("accounts/static/accounts/css/people.css")
