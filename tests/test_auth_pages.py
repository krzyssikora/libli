"""Unit/integration tests for the auth redesign (no Playwright — Django test client)."""

from pathlib import Path

import pytest
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site

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


@pytest.mark.django_db
def test_login_page_renders_bespoke_card(client):
    resp = client.get("/accounts/login/")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'class="auth-card"' in html
    assert "auth-card__wordmark" in html
    assert "Sign in to" in html  # title (institution name follows)
    assert 'name="login"' in html
    assert 'name="password"' in html
    assert 'name="csrfmiddlewaretoken"' in html
    assert "{{ form.as_p }}" not in html
    assert "form.as_p" not in html


@pytest.mark.django_db
def test_login_preserves_next_redirect(client):
    resp = client.get("/accounts/login/?next=/dashboard/")
    html = resp.content.decode()
    assert 'name="next"' in html
    assert "/dashboard/" in html


@pytest.mark.django_db
def test_login_title_uses_institution_name_not_libli(client):
    resp = client.get("/accounts/login/")
    html = resp.content.decode()
    # Default unconfigured institution name is "My Institution" (services._DEFAULTS).
    assert "My Institution" in html


def _seed_oidc_app():
    app = SocialApp.objects.create(
        provider="openid_connect",
        provider_id="testidp",
        name="Test IdP",
        client_id="cid",
        secret="sec",
    )
    app.sites.add(Site.objects.get_current())
    return app


@pytest.mark.django_db
def test_login_shows_sso_when_provider_configured(client):
    _seed_oidc_app()
    html = client.get("/accounts/login/").content.decode()
    assert "auth-sso" in html
    assert "auth-divider" in html
    assert "Continue with" in html


@pytest.mark.django_db
def test_login_hides_sso_when_no_provider(client):
    html = client.get("/accounts/login/").content.decode()
    assert "auth-sso" not in html
    assert "auth-divider" not in html
