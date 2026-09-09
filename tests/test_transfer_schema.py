from django.conf import settings

from courses.color_bands import default_color_bands
from courses.color_bands import is_valid_stored
from courses.models import ELEMENT_MODELS
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError


def test_element_models_lists_every_concrete_element_type():
    """DERIVED, never hand-counted. ELEMENT_MODELS feeds limit_choices_to on
    Element.content_type, and element_save does NOT full_clean the join row -- so a
    type missing from the list is created happily and then fails every route that
    DOES full_clean it: editor copy, editor paste, duplicate_unit, course import.

    Replaces a `len(ELEMENT_MODELS) == 32` pin, which was the wrong shape twice over.
    It stayed GREEN when the Divider shipped a model with no list entry, because the
    count never moved -- the omission it existed to catch. And it reddened this file
    plus two unrelated ones the moment the entry was added. The set comparison catches
    both directions and needs no edit when a type lands.
    """
    from django.apps import apps

    from courses.models import ElementBase

    concrete = {
        m._meta.model_name
        for m in apps.get_app_config("courses").get_models()
        if issubclass(m, ElementBase)
    }
    assert concrete == set(ELEMENT_MODELS)

    # kept from the pinned version: names whose absence has burned us before
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
        "guessnumberelement",
    ):
        assert name in ELEMENT_MODELS


def test_transfer_settings_constants():
    assert settings.TRANSFER_MAX_COMPRESSED_BYTES == 1 * 1024**3
    assert settings.TRANSFER_MAX_UNCOMPRESSED_BYTES == 1536 * 1024**2  # 1.5 GiB
    assert settings.TRANSFER_MAX_COURSE_JSON_BYTES == 64 * 1024**2
    assert settings.TRANSFER_MAX_MANIFEST_BYTES == 64 * 1024
    assert settings.TRANSFER_MAX_NODES == 5000
    assert settings.TRANSFER_MAX_ELEMENTS == 100000
    assert settings.TRANSFER_MAX_MEDIA_ENTRIES == 5000
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
    assert FORMAT_VERSION == 15
