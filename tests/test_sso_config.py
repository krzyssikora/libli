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


def _form(data, app=None):
    from accounts.forms import SsoForm

    return SsoForm(data, app=app)


@pytest.mark.django_db
def test_form_rejects_non_https_issuer():
    form = _form({"server_url": "http://idp.example.com", "enabled": False})
    assert not form.is_valid()
    assert "server_url" in form.errors


@pytest.mark.django_db
def test_form_normalizes_bare_domain_and_trailing_slash():
    form = _form({"server_url": "idp.example.test/", "enabled": False})
    assert form.is_valid(), form.errors
    assert form.cleaned_data["server_url"] == "https://idp.example.test"


@pytest.mark.django_db
def test_form_enable_requires_all_fields():
    form = _form(
        {
            "enabled": True,
            "name": "",
            "server_url": "",
            "client_id": "",
            "client_secret": "",
        }
    )
    assert not form.is_valid()
    for field in ("name", "server_url", "client_id", "client_secret"):
        assert field in form.errors


@pytest.mark.django_db
def test_form_enable_accepts_stored_secret_with_blank_field():
    app = make_oidc_app()  # has secret="secret"
    form = _form(
        {
            "enabled": True,
            "name": "X",
            "server_url": "https://idp.example.com",
            "client_id": "c",
            "client_secret": "",
        },
        app=app,
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_form_enable_without_secret_errors_on_secret_field():
    form = _form(
        {
            "enabled": True,
            "name": "X",
            "server_url": "https://idp.example.com",
            "client_id": "c",
            "client_secret": "",
        }
    )  # no app -> no stored secret
    assert not form.is_valid()
    assert "client_secret" in form.errors


@pytest.mark.django_db
def test_form_invalid_issuer_while_enabling_does_not_double_report():
    # non-https + enabled: only the https error on server_url, not a spurious "required"
    form = _form(
        {
            "enabled": True,
            "name": "X",
            "server_url": "http://idp.example.com",
            "client_id": "c",
            "client_secret": "s",
        }
    )
    assert not form.is_valid()
    assert len(form.errors["server_url"]) == 1


@pytest.mark.django_db
def test_form_disabled_partial_draft_is_valid():
    form = _form({"enabled": False, "name": "Draft"})
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_form_never_renders_stored_secret():
    from accounts.forms import SsoForm

    app = make_oidc_app()
    app.secret = "topsekretsentinel"  # distinctive value (not the word "secret",
    app.save()  # which is a substring of name="client_secret")
    form = SsoForm(app=app, initial={"name": app.name})
    assert "topsekretsentinel" not in str(form["client_secret"])


@pytest.mark.django_db
def test_sso_tab_requires_permission(client):
    from tests.factories import make_login

    make_login(client, "student")  # non-PA
    resp = client.get(reverse("institution:settings") + "?tab=sso")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_sso_tab_get_shows_redirect_uri(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:settings") + "?tab=sso")
    assert resp.status_code == 200
    assert b"/accounts/oidc/sso/login/callback/" in resp.content


@pytest.mark.django_db
def test_sso_post_valid_saves_and_redirects(client):
    from allauth.socialaccount.models import SocialApp

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:settings_sso"),
        {
            "enabled": "on",
            "name": "Acme",
            "server_url": "idp.example.test/",
            "client_id": "cid",
            "client_secret": "sek",
        },
    )
    assert resp.status_code == 302
    assert resp.url == reverse("institution:settings") + "?tab=sso"
    app = SocialApp.objects.get(provider="openid_connect")
    # end-to-end normalization proves the view passed cleaned_data, not POST:
    assert app.settings["server_url"] == "https://idp.example.test"


@pytest.mark.django_db
def test_sso_post_invalid_rerenders_without_saving(client):
    from allauth.socialaccount.models import SocialApp

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:settings_sso"),
        {
            "enabled": "on",
            "name": "",
            "server_url": "",
            "client_id": "",
            "client_secret": "",
        },
    )
    assert resp.status_code == 200
    assert SocialApp.objects.count() == 0  # nothing persisted on invalid


@pytest.mark.django_db
def test_sso_post_blank_disabled_is_noop(client):
    from allauth.socialaccount.models import SocialApp

    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(reverse("institution:settings_sso"), {"enabled": ""})
    assert resp.status_code == 302
    assert SocialApp.objects.count() == 0


@pytest.mark.django_db
def test_sso_action_get_redirects(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:settings_sso"))
    assert resp.status_code == 302
    assert resp.url == reverse("institution:settings") + "?tab=sso"


@pytest.mark.django_db
def test_sso_context_present_on_other_tab_invalid_post(client):
    # An invalid POST to the access tab still renders the always-present SSO panel.
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:settings_access"), {"signup_policy": "not-a-choice"}
    )
    assert resp.status_code == 200
    assert b"/accounts/oidc/sso/login/callback/" in resp.content


@pytest.mark.django_db
def test_landing_button_follows_toggle_for_anonymous_visitor(client):
    from accounts.sso_config import save_sso_config

    site = Site.objects.get_current()
    save_sso_config(
        name="Acme",
        server_url="https://idp.example.com",
        client_id="c",
        client_secret="s",
        enabled=True,
        site=site,
    )
    resp = client.get("/")  # anonymous -> landing renders
    assert resp.status_code == 200
    assert b"/accounts/oidc/sso/login/" in resp.content

    save_sso_config(
        name="Acme",
        server_url="https://idp.example.com",
        client_id="c",
        client_secret="",
        enabled=False,
        site=site,
    )
    resp = client.get("/")
    assert b"/accounts/oidc/sso/login/" not in resp.content


@pytest.mark.django_db
def test_login_page_button_follows_toggle(client):
    from accounts.sso_config import save_sso_config

    site = Site.objects.get_current()
    save_sso_config(
        name="Acme",
        server_url="https://idp.example.com",
        client_id="c",
        client_secret="s",
        enabled=True,
        site=site,
    )
    resp = client.get(reverse("account_login"))
    assert b"oidc/sso/login/" in resp.content  # get_providers is site-aware

    save_sso_config(
        name="Acme",
        server_url="https://idp.example.com",
        client_id="c",
        client_secret="",
        enabled=False,
        site=site,
    )
    resp = client.get(reverse("account_login"))
    assert b"oidc/sso/login/" not in resp.content
