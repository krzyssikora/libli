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
