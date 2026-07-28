"""Favicon: model field, config bundle, head render, manifest and redirect routes."""

import io
import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from core.services import PRIMARY_DEFAULT
from core.services import get_site_config
from core.services import invalidate_site_config
from institution.models import Institution

pytestmark = pytest.mark.django_db


def png_bytes(size=(256, 256), mode="RGB", fmt="PNG"):
    buf = io.BytesIO()
    Image.new(mode, size, (10, 20, 30)).save(buf, fmt)
    return buf.getvalue()


def png_upload(name="mark.png", size=(256, 256), mode="RGB", fmt="PNG"):
    return SimpleUploadedFile(
        name, png_bytes(size, mode, fmt), content_type="image/png"
    )


def test_institution_accepts_a_favicon(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    inst.refresh_from_db()
    assert inst.favicon.name.startswith("branding/")
    assert inst.favicon.width == 256


def test_bundle_favicon_keys_default_to_none():
    cfg = get_site_config()
    assert cfg["favicon_url"] is None
    assert cfg["favicon_size"] is None


def test_bundle_exposes_url_and_size_for_an_upload(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    cfg = get_site_config()
    assert cfg["favicon_url"].endswith(".png")
    assert cfg["favicon_size"] == "256x256"


def test_bundle_favicon_size_is_none_when_the_file_is_missing(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    # Delete via .path -- the stored name is relative to MEDIA_ROOT, so joining it
    # onto tmp_path by hand silently no-ops and the test would assert nothing.
    Path(inst.favicon.path).unlink()
    invalidate_site_config()
    assert get_site_config()["favicon_size"] is None


def test_bundle_favicon_size_is_none_for_an_unreadable_header(settings, tmp_path):
    """get_image_dimensions returns (None, None) WITHOUT raising for content that is
    not a decodable image header -- so the try/except is not enough on its own and
    the manifest would otherwise ship the literal string "NonexNone".

    Truncation is NOT sufficient to reach this: a half-truncated PNG still reports
    its real size, because PNG dimensions live in the first chunk.
    """
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    with open(inst.favicon.path, "wb") as handle:
        handle.write(b"not an image")
    invalidate_site_config()
    assert get_site_config()["favicon_size"] is None


def test_saving_the_institution_invalidates_the_new_bundle_keys(settings, tmp_path):
    """The existing post_save signal must cover the new keys.

    Primed deliberately: tests/conftest.py::_clear_site_cache empties the cache per
    test, so a first read AFTER the save is always a cold rebuild and would pass
    with the signal disconnected. Reading first is what makes this an invalidation
    test rather than a build test -- and note there is no explicit
    invalidate_site_config() call here.
    """
    settings.MEDIA_ROOT = tmp_path
    assert get_site_config()["favicon_url"] is None
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    assert get_site_config()["favicon_url"] is not None

    # And back again on a clear -- the bundle layer of the "clearing restores the
    # default" promise, between the model test (Task 5) and the e2e (Task 10).
    inst.favicon.delete(save=True)
    assert get_site_config()["favicon_url"] is None
    assert get_site_config()["favicon_size"] is None


def test_manifest_is_public_and_well_formed(client):
    response = client.get(reverse("core:webmanifest"))
    assert response.status_code == 200
    assert response["Content-Type"] == "application/manifest+json"
    data = json.loads(response.content)
    assert data["name"] == Institution.load().name
    assert data["start_url"] == "/"
    assert data["display"] == "standalone"
    assert data["background_color"] == "#F4F1EA"
    assert data["theme_color"] == PRIMARY_DEFAULT


@pytest.mark.parametrize("bad", [None, "javascript:alert(1)"])
def test_manifest_theme_color_falls_back(client, monkeypatch, bad):
    """The manifest counterpart of the head-tag fallback test.

    It must CONSTRUCT the bad value: migration 0002_seed_branding seeds
    primary="#147E78", and _DEFAULTS["primary"] is PRIMARY_DEFAULT too, so on a
    real install cfg["primary"] already equals PRIMARY_DEFAULT -- an unpatched
    assertion would pass with effective_primary() deleted and prove nothing.
    """
    from core import views

    monkeypatch.setattr(
        views, "get_site_config", lambda: {**get_site_config(), "primary": bad}
    )
    data = json.loads(client.get(reverse("core:webmanifest")).content)
    assert data["theme_color"] == PRIMARY_DEFAULT
    sizes = {icon.get("sizes") for icon in data["icons"]}
    assert sizes == {"192x192", "512x512"}
    assert all(icon["type"] == "image/png" for icon in data["icons"])
    assert any(icon.get("purpose") == "maskable" for icon in data["icons"])


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Libli", "Libli"),
        ("My Institution", "My"),
        ("Szkola Podstawowa", "Szkola"),
        # The ONLY case that exercises .rstrip(): name[:12] is "Szkola  Pods",
        # so rsplit yields "Szkola " with a trailing space. Every other case
        # here is byte-identical with and without the call.
        ("Szkola  Podstawowa", "Szkola"),
        # The spec's literal, with the non-ASCII character: it is the multi-byte
        # boundary case, and Python slices by codepoint so it truncates identically.
        ("Międzynarodowe Liceum", "Międzynarodo"),
        ("Jan-Kochanowski Liceum", "Jan-Kochanow"),
        ("   ", "My"),
    ],
)
def test_short_name_boundaries(name, expected):
    from core.views import _short_name

    assert _short_name(name) == expected


def test_manifest_with_an_override_has_one_icon(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    data = json.loads(client.get(reverse("core:webmanifest")).content)
    assert len(data["icons"]) == 1
    assert data["icons"][0]["sizes"] == "256x256"
    assert data["icons"][0]["type"] == "image/png"


def test_manifest_omits_sizes_when_the_size_is_unknown(client, monkeypatch):
    """The counterpart of the head-link test in Task 9. Omitted, not "any": the
    spec's own argument is that "any" on a raster is the declaration that risks
    non-installability, so substituting it where the size is unknown is the worst
    of both."""
    from core import views

    monkeypatch.setattr(
        views,
        "get_site_config",
        lambda: {
            **get_site_config(),
            "favicon_url": "/media/b/m.png",
            "favicon_size": None,
        },
    )
    data = json.loads(client.get(reverse("core:webmanifest")).content)
    assert len(data["icons"]) == 1
    assert "sizes" not in data["icons"][0]


def test_favicon_ico_redirects_to_the_static_asset_by_default(client):
    response = client.get(reverse("core:favicon_ico"))
    assert response.status_code == 302
    assert response["Location"].endswith("favicon.ico")
    assert "Cache-Control" not in response


def test_favicon_ico_redirects_to_the_override(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    response = client.get(reverse("core:favicon_ico"))
    assert response.status_code == 302
    assert "/media/branding/" in response["Location"]


def test_head_has_the_default_icon_links(client):
    body = client.get("/").content.decode()
    assert 'type="image/svg+xml"' in body
    assert "favicon.ico" in body
    assert "apple-touch-icon" in body
    assert 'rel="manifest"' in body
    assert 'name="theme-color"' in body


def test_svg_link_precedes_the_ico_link_and_declares_sizes_any(client):
    """Order and sizes="any" are load-bearing: a vector link with no sizes, against
    an ICO declaring exactly the 16/32 a tab wants, is the combination that makes
    Chromium ignore the SVG. A containment assertion passes regardless of order,
    so assert the INDEXES."""
    body = client.get("/").content.decode()
    svg_at = body.index("favicon.svg")
    ico_at = body.index("favicon.ico")
    assert svg_at < ico_at
    assert 'sizes="any"' in body


def test_override_replaces_the_static_icons(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", png_upload(), save=True)
    body = client.get("/").content.decode()
    assert "/media/branding/" in body
    assert "favicon.svg" not in body
    assert "favicon.ico" not in body
    assert 'sizes="256x256"' in body


def test_override_without_a_known_size_omits_the_sizes_attribute(client, monkeypatch):
    from core.templatetags import branding

    monkeypatch.setattr(
        branding,
        "get_site_config",
        lambda: {
            **get_site_config(),
            "favicon_url": "/media/branding/m.png",
            "favicon_size": None,
        },
    )
    body = client.get("/").content.decode()
    # Assert the WHOLE element. A prefix slice is vacuous here: the tag emits
    # sizes AFTER href, so everything before the URL is always ' rel="icon"
    # href="' -- measured identical with and without the omission.
    assert '<link rel="icon" href="/media/branding/m.png" type="image/png">' in body


def test_media_url_is_escaped_as_an_attribute(client, monkeypatch):
    """The falsification for choosing format_html over mark_safe.

    It must be CONSTRUCTED this way: an upload cannot reach it (get_valid_filename
    strips these characters) and neither can setting .name directly
    (FileSystemStorage.url percent-encodes them) -- under either, format_html and
    mark_safe produce byte-identical output and the test is vacuous.
    """
    from core.templatetags import branding

    monkeypatch.setattr(
        branding,
        "get_site_config",
        lambda: {
            **get_site_config(),
            "favicon_url": '/media/x"y<z>&.png',
            "favicon_size": None,
        },
    )
    body = client.get("/").content.decode()
    # Assert the escaped href as ONE string: bare "&quot;"/"&lt;" occur all over a
    # full page render, so on their own they prove nothing about this element.
    assert 'href="/media/x&quot;y&lt;z&gt;&amp;.png"' in body
    assert '"y<z>&' not in body


def test_theme_color_falls_back_when_the_primary_is_absent_or_malformed(
    client, monkeypatch
):
    from core.templatetags import branding

    for bad in (None, "javascript:alert(1)"):
        monkeypatch.setattr(
            branding,
            "get_site_config",
            lambda bad=bad: {**get_site_config(), "primary": bad},
        )
        body = client.get("/").content.decode()
        assert f'content="{PRIMARY_DEFAULT}"' in body


def test_404_page_carries_the_icon_links(client):
    """403/404 extend base.html, but they render through Django's error handlers
    rather than a normal view -- worth measuring rather than inferring."""
    response = client.get("/definitely-not-a-real-url/")
    assert response.status_code == 404
    assert 'rel="icon"' in response.content.decode()


def test_500_template_takes_no_static_or_config_dependency():
    """500.html renders with an empty Context() when the DB may be down. Its own
    comment forbids depending on collected static, which can itself cause a 500."""
    source = (Path(__file__).resolve().parent.parent / "templates/500.html").read_text(
        encoding="utf-8"
    )
    assert "favicon" not in source
    assert "/static/" not in source
    assert "{% static" not in source
    assert "favicon_links" not in source
