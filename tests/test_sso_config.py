"""Phase 5d — SSO configuration service, form, view, and surface-gating tests."""

import pytest
from django.contrib.sites.models import Site
from django.urls import reverse

from tests._sso import make_oidc_app


def test_effective_provider_id_none_tolerant():
    from accounts.sso_config import effective_provider_id

    assert effective_provider_id(None) == "sso"


def test_redirect_uri_resolves_with_zero_rows(rf):
    from accounts.sso_config import redirect_uri

    req = rf.get("/manage/settings/")
    assert redirect_uri(req, None).endswith("/accounts/oidc/sso/login/callback/")


def test_both_oidc_routes_resolve_with_zero_rows():
    # Landing button (openid_connect_login) + callback both import-time parametrized.
    assert reverse("openid_connect_login", kwargs={"provider_id": "sso"}).endswith(
        "/login/"
    )
    assert reverse("openid_connect_callback", kwargs={"provider_id": "sso"}).endswith(
        "/login/callback/"
    )


@pytest.mark.django_db
def test_load_sso_app_returns_none_when_unconfigured():
    from accounts.sso_config import load_sso_app

    assert load_sso_app() is None


@pytest.mark.django_db
def test_load_sso_app_returns_the_oidc_row():
    from accounts.sso_config import load_sso_app

    app = make_oidc_app()
    assert load_sso_app().pk == app.pk


@pytest.mark.django_db
def test_is_enabled_reflects_site_membership():
    from accounts.sso_config import is_enabled
    from accounts.sso_config import load_sso_app

    site = Site.objects.get_current()
    assert is_enabled(load_sso_app(), site) is False  # no row
    app = make_oidc_app()  # make_oidc_app attaches the current Site
    assert is_enabled(app, site) is True
    app.sites.remove(site)
    assert is_enabled(load_sso_app(), site) is False


@pytest.mark.django_db
def test_effective_provider_id_uses_stored_slug():
    from accounts.sso_config import effective_provider_id

    app = make_oidc_app()  # provider_id="testidp"
    assert effective_provider_id(app) == "testidp"
