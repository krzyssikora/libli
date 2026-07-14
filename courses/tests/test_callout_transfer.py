import pytest

from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import CalloutElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError


def test_callout_registered_in_all_three_registries():
    assert "callout" in SERIALIZERS
    assert "callout" in VALIDATORS
    assert "callout" in BUILDERS


def test_callout_is_nestable_and_invariant_holds():
    # transfer key == form key, so no alias needed
    assert "callout" in NESTABLE_TYPE_KEYS
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip_preserves_fields():
    el = CalloutElement.objects.create(
        kind="warning", heading="Careful", body="<p>hi</p>"
    )
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):  # unused by callout
            return None

    data = ser(el, _Ids())
    assert data == {"kind": "warning", "heading": "Careful", "body": "<p>hi</p>"}
    # validator accepts it
    VALIDATORS["callout"](data, "e1", set())
    # builder reconstructs
    rebuilt, _refs = BUILDERS["callout"](data, {})
    assert rebuilt.kind == "warning"
    assert rebuilt.heading == "Careful"
    assert "hi" in rebuilt.body


def test_validator_rejects_bad_kind():
    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"kind": "bogus", "heading": "", "body": ""}, "e1", set())


def test_validator_rejects_missing_and_extra_keys():
    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"kind": "note", "body": ""}, "e1", set())  # no heading
    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "note", "heading": "", "body": "", "x": 1}, "e1", set()
        )


def test_validator_rejects_overlong_heading():
    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "note", "heading": "z" * 121, "body": ""}, "e1", set()
        )
