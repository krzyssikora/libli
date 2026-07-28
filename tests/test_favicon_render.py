"""Favicon: model field, config bundle, head render, manifest and redirect routes."""

import io
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

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
