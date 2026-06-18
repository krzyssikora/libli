import re

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import translation

from institution.validators import is_valid_css_color
from institution.validators import validate_css_color
from tests.factories import make_verified_user


@pytest.mark.django_db
def test_home_url_name_resolves_and_path_unchanged():
    assert reverse("home") == "/home/"


@pytest.mark.django_db
def test_home_requires_login_anonymous_redirects(client):
    resp = client.get("/home/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_home_authenticated_returns_200(client):
    user = make_verified_user(username="alice", email="alice@school.edu")
    client.force_login(user)
    resp = client.get("/home/")
    assert resp.status_code == 200
    assert b"alice" in resp.content


def test_is_valid_css_color_accepts_hex_and_functions():
    assert is_valid_css_color("#147E78")
    assert is_valid_css_color("#abc")
    assert is_valid_css_color("  #147E78  ")  # surrounding whitespace stripped
    assert is_valid_css_color("rgb(20, 126, 120)")
    assert is_valid_css_color("rgba(20,126,120,0.5)")
    assert is_valid_css_color("hsl(176, 72%, 29%)")


def test_is_valid_css_color_rejects_injection_and_junk():
    for bad in ["red; }", "#fff;}body{x", "</style>", "url(x)", "", "147E78", "#12"]:
        assert not is_valid_css_color(bad)


def test_validate_css_color_raises_on_bad():
    with pytest.raises(ValidationError):
        validate_css_color("red; } body{display:none")
    # valid value does not raise
    validate_css_color("#147E78")


@pytest.mark.django_db
def test_brandcolor_full_clean_rejects_unsafe_value():
    from institution.models import BrandColor
    from institution.models import Institution

    inst = Institution.load()
    bc = BrandColor(institution=inst, key="primary", value="</style><script>")
    with pytest.raises(ValidationError):
        bc.full_clean()


@pytest.mark.django_db
def test_get_site_config_returns_defaults_bundle():
    from core.services import get_site_config

    cfg = get_site_config()
    assert cfg["name"]
    assert cfg["logo_url"] is None  # no logo uploaded
    assert cfg["primary"] == "#147E78"  # seeded default
    assert cfg["accent"] == "#C77B2A"
    assert cfg["enabled_languages"] == ["en", "pl"]
    assert cfg["default_language"] == "en"
    assert cfg["default_theme"] == "auto"


@pytest.mark.django_db
def test_get_site_config_is_cached_and_invalidated_on_save():
    from core.services import get_site_config
    from institution.models import BrandColor
    from institution.models import Institution

    assert get_site_config()["primary"] == "#147E78"
    BrandColor.objects.filter(key="primary").update(value="#222222")  # bypasses signals
    assert get_site_config()["primary"] == "#147E78"  # still cached
    # A real save fires the post_save signal → cache cleared.
    inst = Institution.load()
    bc = BrandColor.objects.get(institution=inst, key="primary")
    bc.value = "#333333"
    bc.save()
    assert get_site_config()["primary"] == "#333333"


@pytest.mark.django_db
def test_get_site_config_skips_invalid_stored_color():
    # A value that somehow bypassed validation is treated as absent (None).
    from core.services import get_site_config
    from institution.models import BrandColor

    BrandColor.objects.filter(key="primary").update(value="garbage; }")
    from django.core.cache import cache

    cache.clear()
    assert get_site_config()["primary"] is None


@pytest.mark.django_db
def test_ui_prefs_anonymous_default_theme_auto(rf):
    from django.contrib.auth.models import AnonymousUser

    from core.context_processors import ui_prefs

    request = rf.get("/")
    request.user = AnonymousUser()
    request.COOKIES = {}
    ctx = ui_prefs(request)
    assert ctx["theme_pref"] == "auto"
    assert ctx["data_theme"] == "light"  # auto -> light server projection


@pytest.mark.django_db
def test_ui_prefs_authenticated_uses_user_theme(rf):
    from core.context_processors import ui_prefs

    user = make_verified_user(username="bob", email="bob@school.edu")
    user.theme = "dark"
    user.save()
    request = rf.get("/")
    request.user = user
    request.COOKIES = {}
    ctx = ui_prefs(request)
    assert ctx["theme_pref"] == "dark"
    assert ctx["data_theme"] == "dark"


@pytest.mark.django_db
def test_ui_prefs_anonymous_cookie_wins_over_institution_default(rf):
    from django.contrib.auth.models import AnonymousUser

    from core.context_processors import ui_prefs

    request = rf.get("/")
    request.user = AnonymousUser()
    request.COOKIES = {"libli_theme": "dark"}
    ctx = ui_prefs(request)
    assert ctx["theme_pref"] == "dark"
    assert ctx["data_theme"] == "dark"


@pytest.mark.django_db
def test_institution_branding_exposes_bundle(rf):
    from core.context_processors import institution_branding

    ctx = institution_branding(rf.get("/"))
    assert ctx["site"]["name"]
    assert ctx["site"]["primary"] == "#147E78"


def test_tokens_css_has_colormix_derivation():
    from pathlib import Path

    from django.conf import settings

    tokens = (Path(settings.BASE_DIR) / "core/static/core/css/tokens.css").read_text(
        encoding="utf-8"
    )
    assert "--brand-primary: #147E78;" in tokens
    assert "color-mix(in srgb, var(--brand-primary)" in tokens
    assert '[data-theme="dark"]' in tokens
    assert "--surface-raised:" in tokens  # named literal the *-subtle mixes need


def test_static_css_resolves_via_finders():
    from django.contrib.staticfiles import finders

    for name in [
        "core/css/tokens.css",
        "core/css/reset.css",
        "core/css/app.css",
        "core/js/ui.js",
    ]:
        assert finders.find(name), f"missing static asset: {name}"


@pytest.mark.django_db
def test_brand_vars_emits_nothing_for_default_palette():
    from django.core.cache import cache
    from django.template import Context
    from django.template import Template

    cache.clear()
    out = Template("{% load branding %}{% brand_vars %}").render(Context({}))
    assert out.strip() == ""  # seeded colors equal defaults -> no override


@pytest.mark.django_db
def test_brand_vars_emits_style_for_overridden_palette():
    from django.core.cache import cache
    from django.template import Context
    from django.template import Template

    from institution.models import BrandColor

    bc = BrandColor.objects.get(key="primary")
    bc.value = "#3355FF"
    bc.save()  # fires invalidation
    cache.clear()
    out = Template("{% load branding %}{% brand_vars %}").render(Context({}))
    assert "<style>" in out and "--brand-primary: #3355FF" in out
    assert "--brand-accent" not in out  # accent still default -> not emitted


@pytest.mark.django_db
def test_brand_vars_skips_invalid_color():
    from django.core.cache import cache
    from django.template import Context
    from django.template import Template

    from institution.models import BrandColor

    BrandColor.objects.filter(key="primary").update(value="x; }</style>")
    cache.clear()
    out = Template("{% load branding %}{% brand_vars %}").render(Context({}))
    assert "</style>" not in out
    assert "--brand-primary" not in out  # invalid -> treated as absent


def test_override_helper_rejects_invalid_value_directly():
    # Directly exercises the tag's defense-in-depth re-validation branch
    # (get_site_config normally filters invalid colors before the tag, so this
    # path is otherwise untested).
    from core.services import PRIMARY_DEFAULT
    from core.templatetags.branding import _override

    assert _override("x; }</style>", PRIMARY_DEFAULT) is None
    assert _override("", PRIMARY_DEFAULT) is None
    assert (
        _override("#147e78", PRIMARY_DEFAULT) is None
    )  # default-equal (case-insensitive)
    assert _override("  #3355FF  ", PRIMARY_DEFAULT) == "#3355FF"  # stripped


@pytest.mark.django_db
def test_brand_vars_emits_both_overridden_vars():
    from django.core.cache import cache
    from django.template import Context
    from django.template import Template

    from institution.models import BrandColor

    BrandColor.objects.filter(key="primary").update(value="#3355FF")
    BrandColor.objects.filter(key="accent").update(value="#FF8800")
    cache.clear()
    out = Template("{% load branding %}{% brand_vars %}").render(Context({}))
    assert "--brand-primary: #3355FF" in out
    assert "--brand-accent: #FF8800" in out
    assert out.count("<style>") == 1  # single combined style block


@pytest.mark.django_db
def test_login_seeds_session_language_from_user(client):
    user = make_verified_user(username="pat", email="pat@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    # The user_logged_in receiver fires on force_login.
    assert client.session.get("_language") == "pl"


@pytest.mark.django_db
def test_login_with_disabled_language_falls_back_without_mutating(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]  # pl disabled
    inst.save()
    user = make_verified_user(username="ula", email="ula@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    assert client.session.get("_language") == "en"  # fell back to default
    user.refresh_from_db()
    assert user.language == "pl"  # stored choice NOT overwritten


@pytest.mark.django_db
def test_logout_clears_theme_cookie(client):
    user = make_verified_user(username="rob", email="rob@school.edu")
    client.force_login(user)
    client.cookies["libli_theme"] = "dark"
    client.post(reverse("account_logout"))
    # The cookie is expired (Max-Age=0) by the user_logged_out receiver.
    morsel = client.cookies.get("libli_theme")
    assert morsel is None or morsel.value == "" or morsel["max-age"] in (0, "0")


@pytest.mark.django_db
def test_seeder_keeps_anonymous_within_enabled_languages(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]
    inst.default_language = "en"
    inst.save()
    # Anonymous request advertising pl: seeder must NOT let pl activate.
    resp = client.get("/accounts/login/", HTTP_ACCEPT_LANGUAGE="pl")
    assert resp.status_code == 200
    assert translation.get_language() == "en"


@pytest.mark.django_db
def test_set_ui_language_anonymous_writes_session_and_redirects(client):
    resp = client.post(
        reverse("core:set_ui_language"), {"language": "pl", "next": "/accounts/login/"}
    )
    assert resp.status_code == 302
    assert resp["Location"] == "/accounts/login/"
    assert client.session.get("_language") == "pl"


@pytest.mark.django_db
def test_set_ui_language_rejects_disabled_and_unsafe_next(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]
    inst.save()
    resp = client.post(
        reverse("core:set_ui_language"),
        {"language": "pl", "next": "https://evil.test/x"},
    )
    # pl rejected (not enabled) -> session unchanged; unsafe next -> falls back to home.
    assert client.session.get("_language") in (None, "en")
    assert resp["Location"] == reverse("home")


@pytest.mark.django_db
def test_set_ui_language_authenticated_persists_user_language(client):
    user = make_verified_user(username="liz", email="liz@school.edu")
    client.force_login(user)
    client.post(reverse("core:set_ui_language"), {"language": "pl", "next": "/home/"})
    user.refresh_from_db()
    assert user.language == "pl"


@pytest.mark.django_db
def test_set_theme_requires_auth(client):
    resp = client.post(reverse("core:set_theme"), {"theme": "dark"})
    assert resp.status_code in (302, 403)  # login_required -> redirect (or 403)


@pytest.mark.django_db
def test_set_theme_persists_and_returns_204(client):
    user = make_verified_user(username="moe", email="moe@school.edu")
    client.force_login(user)
    resp = client.post(reverse("core:set_theme"), {"theme": "dark"})
    assert resp.status_code == 204
    user.refresh_from_db()
    assert user.theme == "dark"


@pytest.mark.django_db
def test_set_theme_rejects_invalid(client):
    user = make_verified_user(username="ned", email="ned@school.edu")
    client.force_login(user)
    resp = client.post(reverse("core:set_theme"), {"theme": "rainbow"})
    assert resp.status_code == 400
    user.refresh_from_db()
    assert user.theme == "auto"  # unchanged


@pytest.mark.django_db
def test_login_page_renders_shell_anonymous_no_account_menu(client):
    html = client.get("/accounts/login/").content.decode()
    # Entrance pages use auth-chrome (not the full-shell brand) — Task 2 redesign.
    assert "auth-chrome" in html
    assert "account-menu" not in html  # anonymous variant — no account menu
    # pre-paint script before any stylesheet link
    head = html[: html.index("</head>")]
    # "prefers-color-scheme" appears only inside the pre-paint script — use it to
    # assert the script precedes the first stylesheet link (the real no-flash check).
    script_idx = head.index("prefers-color-scheme")
    link_idx = head.index('rel="stylesheet"')
    assert script_idx < link_idx
    # inline brand <style> (if any) comes after tokens.css; tokens.css link present
    assert "core/css/tokens.css" in head


@pytest.mark.django_db
def test_html_has_theme_and_lang_attributes(client):
    html = client.get("/accounts/login/").content.decode()
    assert re.search(r"<html[^>]*data-theme=\"light\"", html)
    assert re.search(r"<html[^>]*data-theme-pref=\"auto\"", html)
    assert re.search(r"<html[^>]*lang=\"en\"", html)


@pytest.mark.django_db
def test_home_renders_shell_authenticated_with_account_menu(client):
    user = make_verified_user(username="ann", email="ann@school.edu")
    client.force_login(user)
    html = client.get("/home/").content.decode()
    assert "account-menu" in html
    assert "data-theme" in html


@pytest.mark.django_db
def test_dark_user_theme_attribute(client):
    user = make_verified_user(username="dee", email="dee@school.edu")
    user.theme = "dark"
    user.save()
    client.force_login(user)
    html = client.get("/home/").content.decode()
    assert 'data-theme="dark"' in html
    assert 'data-theme-pref="dark"' in html


@pytest.mark.django_db
def test_inline_brand_style_comes_after_tokens_css(client):
    # Load-bearing head order: an institution override must win over tokens.css.
    from institution.models import BrandColor

    bc = BrandColor.objects.get(key="primary")
    bc.value = "#3355FF"
    bc.save()
    head = client.get("/accounts/login/").content.decode()
    head = head[: head.index("</head>")]
    assert head.index("core/css/tokens.css") < head.index("--brand-primary: #3355FF")


@pytest.mark.django_db
def test_data_authenticated_attribute_matches_auth_state(client):
    # Pins the contract ui.js relies on to decide whether to POST set_theme.
    anon = client.get("/accounts/login/").content.decode()
    assert 'data-authenticated="0"' in anon
    user = make_verified_user(username="cam", email="cam@school.edu")
    client.force_login(user)
    authed = client.get("/home/").content.decode()
    assert 'data-authenticated="1"' in authed


@pytest.mark.django_db
def test_default_palette_emits_no_brand_style(client):
    # With seeded default colors, brand_vars emits nothing (no empty <style>).
    head = client.get("/accounts/login/").content.decode()
    head = head[: head.index("</head>")]
    assert "core/css/tokens.css" in head
    assert "--brand-primary:" not in head  # no override style for the default palette


@pytest.mark.django_db
def test_polish_shell_string_renders_when_pl_active(client):
    # A pl-preferring user logs in; the login receiver activates pl; the shell's
    # "Log out" renders in Polish from libli's own catalog.
    user = make_verified_user(username="zoe", email="zoe@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    html = client.get("/home/").content.decode()
    assert "Wyloguj" in html  # "Log out" in Polish
    # "Toggle theme" is libli-only (not in allauth's catalog), so this asserts
    # libli's own compiled pl catalog is wired and active.
    assert "Przełącz motyw" in html
