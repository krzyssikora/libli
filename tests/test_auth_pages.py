"""Unit/integration tests for the auth redesign (no Playwright — Django test client)."""

from pathlib import Path

import pytest

from institution.models import Institution
from tests._sso import make_oidc_app

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


@pytest.mark.django_db
def test_login_shows_sso_when_provider_configured(client):
    make_oidc_app()
    html = client.get("/accounts/login/").content.decode()
    assert "auth-sso" in html
    assert "auth-divider" in html
    assert "Continue with" in html
    assert "/accounts/oidc/testidp/login/" in html


@pytest.mark.django_db
def test_login_hides_sso_when_no_provider(client):
    html = client.get("/accounts/login/").content.decode()
    assert "auth-sso" not in html
    assert "auth-divider" not in html


def _set_signup_open():
    # Mirror tests/test_surfaces.py:20-22 EXACTLY: the singleton accessor is
    # Institution.load() (NOT objects.get_or_create), and .save() fires the
    # invalidate_site_config signal that busts the cache — get_site_config is
    # NOT functools-memoized, so there is no .cache_clear() to call.
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()  # fires invalidate_site_config


@pytest.mark.django_db
def test_signup_renders_card_no_as_p(client):
    _set_signup_open()
    resp = client.get("/accounts/signup/")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'class="auth-card"' in html
    assert "form.as_p" not in html
    assert 'name="csrfmiddlewaretoken"' in html


def test_accept_invite_template_has_no_as_p():
    tpl = ROOT / "templates" / "accounts" / "accept_invite.html"
    body = tpl.read_text(encoding="utf-8")
    assert "form.as_p" not in body
    assert "auth-card" in body


@pytest.mark.django_db
def test_password_reset_renders_card(client):
    html = client.get("/accounts/password/reset/").content.decode()
    assert 'class="auth-card"' in html
    assert "form.as_p" not in html


def test_sso_not_provisioned_template_is_card():
    tpl = ROOT / "templates" / "accounts" / "sso_not_provisioned.html"
    body = tpl.read_text(encoding="utf-8")
    assert "auth-card" in body
    assert '{% extends "allauth/layouts/entrance.html" %}' in body


@pytest.mark.django_db
def test_account_inactive_inherits_centered_layout(client):
    # account_inactive extends allauth/layouts/entrance.html DIRECTLY (verified)
    # — proves the override point (entrance.html) catches it. Render via a REAL
    # request so context processors (languages/site/theme) + csrf populate.
    resp = client.get("/accounts/inactive/")
    assert resp.status_code == 200
    assert b"auth-main" in resp.content  # main_class from our override


@pytest.mark.django_db
def test_logout_stays_full_shell(client, django_user_model):
    # Bucket B (manage chain): logout keeps the app shell, NOT the centered card.
    # GET /accounts/logout/ renders confirm page (ACCOUNT_LOGOUT_ON_GET defaults False).
    user = django_user_model.objects.create_user(
        username="bob", password="logout-test-pw"
    )
    client.force_login(user)
    resp = client.get("/accounts/logout/")
    assert resp.status_code == 200
    assert b"app-header" in resp.content
    assert b"auth-main" not in resp.content


def test_password_change_template_is_card_no_as_p():
    body = (ROOT / "templates" / "account" / "password_change.html").read_text(
        encoding="utf-8"
    )
    assert 'class="card"' in body
    assert "form.as_p" not in body
    # must re-render the form, not pull empty parent content
    assert "block.super" not in body


def test_entrance_template_has_no_multiline_django_comment():
    # Django strips {# #} comments only when single-line; a multi-line {# #} is NOT
    # recognized and renders as literal text. Guard the entrance override against it.
    import re

    body = (ROOT / "templates" / "allauth" / "layouts" / "entrance.html").read_text(
        encoding="utf-8"
    )
    multiline = re.search(r"\{#(?:[^#]|#(?!\}))*\n(?:[^#]|#(?!\}))*#\}", body)
    assert multiline is None, (
        "multi-line {# #} renders as visible text; use single-line"
    )


@pytest.mark.django_db
def test_entrance_comment_does_not_leak_into_rendered_page(client):
    # The entrance override's header comment must not appear in rendered output of
    # any page in the entrance chain (regression: a multi-line {# #} leaked at the top).
    html = client.get("/accounts/login/").content.decode()
    assert "Overrides allauth" not in html
