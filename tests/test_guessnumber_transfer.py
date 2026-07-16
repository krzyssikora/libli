"""Guess-the-number course export/validate/import: transfer trio (Task 10)."""

from decimal import Decimal

import pytest

from courses import fillblank
from courses import guessnumber
from courses.models import GuessNumberElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.importer import _build_guess_number
from courses.transfer.payloads import VALIDATORS
from courses.transfer.payloads import _val_guess_number
from courses.transfer.schema import TransferError

# Built, never typed: a literal U+FFFF is corrupted to U+FFFC on write.
STRAY_SENTINEL = fillblank.SENTINEL + "x"  # must NOT match _TOKEN_RE (digits only)


@pytest.fixture
def gn_element(db):
    return GuessNumberElement.objects.create(
        stem=guessnumber.SENTINEL_TOKEN,
        target=Decimal("40401.50"),
        tolerance=Decimal("0.5"),
        success_message="",
    )


@pytest.mark.django_db
def test_registered_in_all_three_registries():
    # Omit the BUILDERS entry and every archive containing the element fails at
    # import with nothing red to warn you; omit VALIDATORS and the payload is
    # never checked. tests/test_filltable_transfer.py asserts all three.
    assert "guess_number" in SERIALIZERS
    assert "guess_number" in VALIDATORS
    assert "guess_number" in BUILDERS


@pytest.mark.django_db
def test_decimals_export_as_strings(gn_element):
    payload = SERIALIZERS["guess_number"][1](gn_element, set())
    assert isinstance(payload["target"], str)
    assert isinstance(payload["tolerance"], str)


@pytest.mark.django_db
def test_round_trip_preserves_values(gn_element):
    # Compare Decimals, not literal strings: str() reflects how the Decimal
    # entered memory, so an in-memory create() serializes unquantized while a
    # DB-loaded row gives "0.00000000" (Postgres). See spec §7.1.
    gn_element.refresh_from_db()
    payload = SERIALIZERS["guess_number"][1](gn_element, set())
    assert Decimal(payload["target"]) == gn_element.target
    assert Decimal(payload["tolerance"]) == gn_element.tolerance


@pytest.mark.django_db
def test_export_validate_import_round_trip(gn_element):
    # The test above only serialises. Chain all three, or a serializer/builder
    # disagreement on decimal shape goes unnoticed (export uses str(), the form
    # uses format_target).
    gn_element.refresh_from_db()
    payload = SERIALIZERS["guess_number"][1](gn_element, set())
    _val_guess_number(payload, "e1", set())
    rebuilt, _children = _build_guess_number(payload, None)
    assert rebuilt.target == gn_element.target
    assert rebuilt.tolerance == gn_element.tolerance
    assert rebuilt.stem == gn_element.stem


def test_validator_rejects_missing_key():
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": guessnumber.SENTINEL_TOKEN, "target": "42", "tolerance": "0"},
            "e1",
            set(),
        )


def test_validator_rejects_unknown_key():
    with pytest.raises(TransferError):
        _val_guess_number(
            {
                "stem": guessnumber.SENTINEL_TOKEN,
                "target": "42",
                "tolerance": "0",
                "success_message": "",
                "extra": 1,
            },
            "e1",
            set(),
        )


def test_non_string_stem_is_transfer_error_not_500():
    # _check_token_stem runs _TOKEN_RE.finditer(stem) -> TypeError (500) on an
    # int. check_str must run FIRST.
    with pytest.raises(TransferError):
        _val_guess_number(
            {"stem": 42, "target": "42", "tolerance": "0", "success_message": ""},
            "e1",
            set(),
        )


def test_stray_sentinel_rejected():
    with pytest.raises(TransferError):
        _val_guess_number(
            {
                "stem": guessnumber.SENTINEL_TOKEN + STRAY_SENTINEL,
                "target": "42",
                "tolerance": "0",
                "success_message": "",
            },
            "e1",
            set(),
        )


def test_negative_tolerance_rejected():
    with pytest.raises(TransferError):
        _val_guess_number(
            {
                "stem": guessnumber.SENTINEL_TOKEN,
                "target": "42",
                "tolerance": "-1",
                "success_message": "",
            },
            "e1",
            set(),
        )


@pytest.mark.django_db
def test_builder_sanitises_the_imported_stem():
    # stem is deliberately out of the model's save(), so an unsanitised archive
    # stem would be stored verbatim and then mark_safe'd by render_stem.
    el, children = _build_guess_number(
        {
            "stem": "<script>x</script>" + guessnumber.SENTINEL_TOKEN,
            "target": "42",
            "tolerance": "0",
            "success_message": "",
        },
        None,  # assets
    )
    assert "<script>" not in el.stem
    assert children == ()
