import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from institution.validators import is_valid_css_color
from institution.validators import validate_css_color
from tests.factories import make_verified_user


@pytest.fixture(autouse=True)
def _clear_site_cache():
    # Defined here in Task 1 ON PURPOSE (forward reference) so every later task's
    # tests inherit it. It is a harmless no-op until Task 3 adds the cached
    # site-config, which uses LocMemCache (NOT transaction-scoped) — without this a
    # BrandColor set in one test would leak into the next.
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


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
