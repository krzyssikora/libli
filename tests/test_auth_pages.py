"""Unit/integration tests for the auth redesign (no Playwright — Django test client)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_TPL = ROOT / "templates" / "base.html"


def test_base_html_exposes_reskin_blocks():
    body = BASE_TPL.read_text(encoding="utf-8")
    for block in (
        "{% block header %}",
        "{% block body_class %}",
        "{% block main_class %}",
        "{% block extra_head %}",
        "{% block extra_body %}",
    ):
        assert block in body, f"base.html must declare {block}"
    # The header block must wrap the existing app-header (not replace it).
    assert "app-header" in body
