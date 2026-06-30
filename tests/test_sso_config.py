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


@pytest.mark.django_db
def test_save_creates_canonical_row():
    from accounts.sso_config import save_sso_config

    app = save_sso_config(
        name="Acme IdP",
        server_url="https://idp.example.com",
        client_id="cid",
        client_secret="sek",
        enabled=True,
        site=Site.objects.get_current(),
    )
    assert app.provider == "openid_connect"
    assert app.provider_id == "sso"
    assert app.settings["server_url"] == "https://idp.example.com"
    assert app.client_id == "cid"
    assert app.secret == "sek"
    assert app.sites.filter(pk=Site.objects.get_current().pk).exists()


@pytest.mark.django_db
def test_save_keeps_secret_when_blank_replaces_when_typed():
    from accounts.sso_config import save_sso_config

    site = Site.objects.get_current()
    save_sso_config(
        name="A",
        server_url="https://i.example",
        client_id="c",
        client_secret="orig",
        enabled=True,
        site=site,
    )
    # blank secret keeps it
    app = save_sso_config(
        name="A",
        server_url="https://i.example",
        client_id="c",
        client_secret="",
        enabled=True,
        site=site,
    )
    assert app.secret == "orig"
    # typed secret replaces it
    app = save_sso_config(
        name="A",
        server_url="https://i.example",
        client_id="c",
        client_secret="new",
        enabled=True,
        site=site,
    )
    assert app.secret == "new"


@pytest.mark.django_db
def test_disable_removes_site_keeps_credentials():
    from accounts.sso_config import is_enabled
    from accounts.sso_config import save_sso_config

    site = Site.objects.get_current()
    save_sso_config(
        name="A",
        server_url="https://i.example",
        client_id="c",
        client_secret="sek",
        enabled=True,
        site=site,
    )
    app = save_sso_config(
        name="A",
        server_url="https://i.example",
        client_id="c",
        client_secret="",
        enabled=False,
        site=site,
    )
    assert is_enabled(app, site) is False
    assert app.secret == "sek"  # credentials preserved on disable


@pytest.mark.django_db
def test_blank_disabled_save_is_noop():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import save_sso_config

    result = save_sso_config(
        name="",
        server_url="",
        client_id="",
        client_secret="",
        enabled=False,
        site=Site.objects.get_current(),
    )
    assert result is None
    assert SocialApp.objects.count() == 0


@pytest.mark.django_db
def test_disabled_draft_with_one_field_persists():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import save_sso_config

    app = save_sso_config(
        name="Draft",
        server_url="",
        client_id="",
        client_secret="",
        enabled=False,
        site=Site.objects.get_current(),
    )
    assert app is not None
    assert SocialApp.objects.count() == 1
    assert app.name == "Draft"


@pytest.mark.django_db
def test_legacy_blank_slug_row_adopted_and_canonicalized():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import save_sso_config

    legacy = SocialApp.objects.create(
        provider="openid_connect", provider_id="", name="Legacy", client_id="c"
    )
    app = save_sso_config(
        name="L",
        server_url="https://i.example",
        client_id="c",
        client_secret="s",
        enabled=True,
        site=Site.objects.get_current(),
    )
    assert app.pk == legacy.pk  # adopted, not duplicated
    assert app.provider_id == "sso"  # blank canonicalized
    assert SocialApp.objects.count() == 1


@pytest.mark.django_db
def test_legacy_nonblank_slug_preserved():
    from allauth.socialaccount.models import SocialApp

    from accounts.sso_config import effective_provider_id
    from accounts.sso_config import save_sso_config

    SocialApp.objects.create(
        provider="openid_connect", provider_id="google", name="G", client_id="c"
    )
    app = save_sso_config(
        name="G",
        server_url="https://i.example",
        client_id="c",
        client_secret="s",
        enabled=True,
        site=Site.objects.get_current(),
    )
    assert app.provider_id == "google"  # non-blank slug preserved
    assert effective_provider_id(app) == "google"
    assert SocialApp.objects.count() == 1
