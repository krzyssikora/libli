"""The restore's file list. A missing field here means a restore silently
drops files -- the database references them, nothing fetches them, and the
gap surfaces only when a pupil opens the lesson.

Every file-bearing field in the project must appear. test_every_filefield_is_covered
is the drift guard: add a FileField to any model and it goes red until the
command is taught about it.
"""

from io import StringIO

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import models

pytestmark = pytest.mark.django_db


@pytest.fixture
def image_asset(course_with_image):
    """One MediaAsset with a real file on disk.

    Built on the existing `course_with_image` fixture (tests/conftest.py) rather
    than a new one: it already redirects MEDIA_ROOT to tmp_path, which
    make_image_asset needs because it writes real bytes. There is no bare
    `image_asset` fixture in the project -- `course_with_image` returns a
    (course, asset) tuple, and this unpacks it.
    """
    _course, asset = course_with_image
    return asset


def _run():
    out = StringIO()
    call_command("list_referenced_files", stdout=out)
    return [line.split("\t") for line in out.getvalue().splitlines()]


def test_media_asset_file_is_listed(image_asset):
    rows = _run()
    assert ["media", image_asset.file.name] in rows


def test_blank_fields_are_skipped(image_asset):
    image_asset.thumb = ""
    image_asset.web = ""
    image_asset.save(update_fields=["thumb", "web"])
    paths = [path for _, path in _run()]
    assert "" not in paths


def test_paths_are_relative_and_forward_slashed(image_asset):
    for volume, path in _run():
        assert volume in {"media", "support_screenshots"}
        assert not path.startswith("/")
        assert "\\" not in path


def test_every_filefield_is_covered():
    """Drift guard. The command enumerates a fixed list of (model, field)
    pairs; this asserts that list is the WHOLE set of FileFields in the
    project, so a new one cannot be silently omitted.

    Mutant: add a FileField to any model without updating SOURCES -> RED.
    """
    from courses.management.commands.list_referenced_files import SOURCES

    declared = {(model_label, field) for model_label, field in SOURCES}
    actual = set()
    for model in apps.get_models():
        if model._meta.app_label in {"admin", "auth", "contenttypes", "sessions"}:
            continue
        for field in model._meta.get_fields():
            if isinstance(field, models.FileField):
                actual.add((model._meta.label_lower, field.name))
    assert declared == actual, (
        f"missing: {actual - declared}; stale: {declared - actual}"
    )
