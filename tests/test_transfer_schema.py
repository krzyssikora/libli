from django.conf import settings

from courses.color_bands import default_color_bands
from courses.color_bands import is_valid_stored
from courses.models import ELEMENT_MODELS
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError


def test_element_models_lists_all_30_concrete_element_models():
    assert len(ELEMENT_MODELS) == 30
    for name in (
        "extendedresponsequestionelement",
        "dragfillblankquestionelement",
        "matchpairquestionelement",
        "dragtoimagequestionelement",
        "tableelement",
        "galleryelement",
        "tabselement",
        "revealgateelement",
        "fillgateelement",
        "switchgateelement",
        "spoilerelement",
        "switchgridelement",
        "filltableelement",
        "multigridquestionelement",
        "twocolumnelement",
    ):
        assert name in ELEMENT_MODELS


def test_transfer_settings_constants():
    assert settings.TRANSFER_MAX_COMPRESSED_BYTES == 1 * 1024**3
    assert settings.TRANSFER_MAX_UNCOMPRESSED_BYTES == 1536 * 1024**2  # 1.5 GiB
    assert settings.TRANSFER_MAX_COURSE_JSON_BYTES == 10 * 1024**2
    assert settings.TRANSFER_MAX_MANIFEST_BYTES == 64 * 1024
    assert settings.TRANSFER_MAX_NODES == 5000
    assert settings.TRANSFER_MAX_ELEMENTS == 20000
    assert settings.TRANSFER_MAX_MEDIA_ENTRIES == 1000
    assert settings.TRANSFER_STAGING_MAX_AGE_HOURS == 6
    assert settings.TRANSFER_STAGING_DIR  # a path, not under MEDIA_ROOT
    assert str(settings.MEDIA_ROOT) not in str(settings.TRANSFER_STAGING_DIR)


def test_is_valid_stored_public_wrapper():
    assert is_valid_stored(
        [dict(b, label="") for b in default_color_bands()]
    ) or is_valid_stored(default_color_bands())
    assert not is_valid_stored([{"key": "junk"}])
    assert not is_valid_stored("not-a-list")


def test_transfer_error_carries_message():
    err = TransferError("boom")
    assert err.message == "boom"
    assert FORMAT_VERSION == 4
