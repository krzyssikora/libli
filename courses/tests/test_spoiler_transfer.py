import pytest

from courses.builder import NESTABLE_TYPE_KEYS
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError


def test_registered_in_all_three_and_nestable():
    assert "spoiler" in SERIALIZERS
    assert "spoiler" in VALIDATORS
    assert "spoiler" in BUILDERS
    # transfer key == form key, so no alias needed for resolve_scope
    assert "spoiler" in NESTABLE_TYPE_KEYS
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip():
    from courses.models import SpoilerElement

    model, ser = SERIALIZERS["spoiler"]
    assert model is SpoilerElement
    el = SpoilerElement.objects.create(label="Hint", body="<p>x</p>")
    payload = ser(el, {})
    assert payload == {"label": "Hint", "body": "<p>x</p>"}
    built, media = BUILDERS["spoiler"](payload, {})
    assert built.label == "Hint"
    assert "<p>x</p>" in built.body
    assert media == ()


def test_validator_is_strict():
    val = VALIDATORS["spoiler"]
    assert val({"label": "a", "body": "<p>x</p>"}, "e1", {}) == set()
    with pytest.raises(TransferError):
        val({"body": "<p>x</p>"}, "e1", {})
    with pytest.raises(TransferError):
        val({"label": "a", "body": "x", "extra": 1}, "e1", {})
    with pytest.raises(TransferError):
        val({"label": "a", "body": 5}, "e1", {})
    with pytest.raises(TransferError):
        val({"label": "x" * 121, "body": "x"}, "e1", {})
