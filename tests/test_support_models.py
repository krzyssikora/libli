"""Model, storage and validator behaviour for the support app."""

import os

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from support.constants import REPORTER_LABEL_MAX_LENGTH
from support.models import IssueReport
from support.models import SupportSettings
from support.models import screenshot_upload_to
from support.storage import ScreenshotStorage
from support.validators import validate_screenshot_file

pytestmark = pytest.mark.django_db


def _png_bytes():
    """Smallest valid PNG (1x1) — real bytes, so ImageField's Pillow check passes."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_supportsettings_is_a_singleton():
    first = SupportSettings.load()
    first.audience = SupportSettings.Audience.ALL
    first.save()
    second = SupportSettings()
    second.save()
    assert SupportSettings.objects.count() == 1
    assert SupportSettings.load().pk == 1


def test_supportsettings_defaults_to_admins_only():
    assert SupportSettings().audience == SupportSettings.Audience.ADMINS


def test_storage_resolves_the_directory_on_every_access(tmp_path):
    """Two DIFFERENT override values in ONE process.

    A single override would pass even against a storage that froze the path on
    first access, because that first access happens inside the override.
    """
    storage = ScreenshotStorage()
    one = tmp_path / "one"
    two = tmp_path / "two"
    with override_settings(SUPPORT_SCREENSHOT_DIR=one):
        assert storage.location == os.path.abspath(one)
    with override_settings(SUPPORT_SCREENSHOT_DIR=two):
        assert storage.location == os.path.abspath(two)


def test_storage_url_raises_rather_than_emitting_a_media_link():
    with pytest.raises(NotImplementedError):
        ScreenshotStorage().url("screenshots/2026/08/x.png")


def test_upload_to_discards_the_client_filename():
    name = screenshot_upload_to(IssueReport(), "../../evil name.PNG")
    assert name.startswith("screenshots/")
    assert name.endswith(".png")  # lower-cased
    assert "evil" not in name
    assert ".." not in name


def test_upload_to_defaults_the_extension_when_there_is_none():
    assert screenshot_upload_to(IssueReport(), "myscreenshot").endswith(".png")


def test_upload_to_clamps_an_unlisted_extension():
    assert screenshot_upload_to(IssueReport(), "payload.php").endswith(".png")


def test_validator_accepts_a_file_well_under_the_ceiling():
    upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
    validate_screenshot_file(upload)  # must not raise


def test_the_ceiling_is_mib_not_bytes():
    """A tiny PNG kills the literal `max_bytes=5` mutant but not a ceiling set an
    order of magnitude too low (KiB for MiB), which is the same class of bug."""
    from courses.validators import MAX_IMAGE_MIB_CEILING
    from support.validators import MAX_SCREENSHOT_BYTES

    assert MAX_SCREENSHOT_BYTES == MAX_IMAGE_MIB_CEILING * 1024 * 1024
    four_mib = SimpleUploadedFile(
        "big.png", _png_bytes() + b"\0" * (4 * 1024 * 1024), content_type="image/png"
    )
    validate_screenshot_file(four_mib)  # must not raise


def test_validator_rejects_a_disallowed_extension():
    upload = SimpleUploadedFile("shot.txt", b"nope", content_type="text/plain")
    with pytest.raises(ValidationError):
        validate_screenshot_file(upload)


def test_reporter_label_is_truncated_not_overflowed():
    report = IssueReport.objects.create(reporter_label="x" * 500, description="hi")
    report.refresh_from_db()
    assert len(report.reporter_label) <= REPORTER_LABEL_MAX_LENGTH


def test_reporter_roles_truncates_on_a_comma_boundary():
    """Mutant: use a blind slice — it stores a trailing fragment like
    "Course Adm", which role_labels() then renders as a role nobody held."""
    long_name = "R" * 90
    roles = ",".join([long_name, long_name, long_name])  # 272 chars
    report = IssueReport.objects.create(reporter_roles=roles, description="hi")
    report.refresh_from_db()
    assert report.reporter_roles == f"{long_name},{long_name}"
    assert all(part == long_name for part in report.reporter_roles.split(","))


def test_a_screenshot_still_validates_after_narrowing_institution_extensions():
    """The whole reason support/validators.py exists rather than reusing
    courses.validators.validate_image_file. Mutant: use validate_image_file."""
    from django.core.cache import cache

    from institution.models import Institution

    inst = Institution.load()
    inst.allowed_image_extensions = ["jpg"]
    inst.save()
    cache.clear()  # the site-config bundle feeds validate_image_file
    upload = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
    validate_screenshot_file(upload)  # must still not raise


def test_deleting_a_report_deletes_its_screenshot(tmp_path):
    with override_settings(SUPPORT_SCREENSHOT_DIR=tmp_path):
        report = IssueReport.objects.create(description="hi")
        report.screenshot.save(
            "shot.png", SimpleUploadedFile("shot.png", _png_bytes()), save=True
        )
        path = report.screenshot.path
        assert os.path.exists(path)
        report.delete()
        assert not os.path.exists(path)
