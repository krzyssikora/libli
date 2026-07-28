"""Favicon: model field, config bundle, head render, manifest and redirect routes."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

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
