from pathlib import Path

import pytest
from django.conf import settings

from courses.lal_loader.media import get_or_create_asset
from courses.lal_loader.media import resolve_source
from courses.models import MediaAsset
from courses.validators import validate_embed_url
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def test_mediaasset_has_content_hash_field():
    course = CourseFactory()
    a = MediaAsset.objects.create(
        course=course,
        kind="image",
        original_filename="x.png",
        content_hash="a" * 64,
    )
    a.refresh_from_db()
    assert a.content_hash == "a" * 64


def test_content_hash_is_indexed():
    field = MediaAsset._meta.get_field("content_hash")
    assert field.db_index is True


def test_edpuzzle_and_lumi_allowlisted():
    hosts = {h.lower() for h in settings.ALLOWED_EMBED_DOMAINS}
    assert "edpuzzle.com" in hosts
    assert "app.lumi.education" in hosts


def test_edpuzzle_embed_url_validates():
    # Should NOT raise now that the host is allowlisted.
    validate_embed_url("https://edpuzzle.com/embed/media/63fdefbfd6b9684157f590c5")


def test_resolve_source_joins_root_dir_src(tmp_path):
    p = resolve_source(tmp_path, "001_x", "static/a.png")
    assert p == Path(tmp_path) / "001_x" / "static" / "a.png"


def test_dedup_reuses_asset_for_identical_bytes(tmp_path):
    course = CourseFactory()
    f = tmp_path / "a.png"
    f.write_bytes(b"PNGBYTES")
    g = tmp_path / "b.png"
    g.write_bytes(b"PNGBYTES")  # same bytes, different name
    a1 = get_or_create_asset(course, "image", f)
    a2 = get_or_create_asset(course, "image", g)
    assert a1.pk == a2.pk  # deduped by content, not name
    assert a1.content_hash and len(a1.content_hash) == 64


def test_different_bytes_make_different_assets(tmp_path):
    course = CourseFactory()
    f = tmp_path / "a.png"
    f.write_bytes(b"ONE")
    g = tmp_path / "a.png2"
    g.write_bytes(b"TWO")
    assert (
        get_or_create_asset(course, "image", f).pk
        != get_or_create_asset(course, "image", g).pk
    )
