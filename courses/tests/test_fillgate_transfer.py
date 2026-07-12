import pytest

from courses.builder import _NESTABLE_FORM_KEY_ALIASES
from courses.builder import NESTABLE_TYPE_KEYS
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS


def test_registered_and_nestable():
    assert "fill_gate" in SERIALIZERS
    assert "fill_gate" in VALIDATORS
    assert "fill_gate" in BUILDERS
    assert "fill_gate" in NESTABLE_TYPE_KEYS
    assert _NESTABLE_FORM_KEY_ALIASES["fillgate"] == "fill_gate"
    # invariant guarded by the tabs transfer tests
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip():
    from courses.models import FillGateElement

    model, ser = SERIALIZERS["fill_gate"]
    assert model is FillGateElement
    el = FillGateElement.objects.create(stem="s ￿0￿", answers=[["a", "b"]])
    payload = ser(el, {})
    assert payload == {"stem": "s ￿0￿", "answers": [["a", "b"]]}
    built, media = BUILDERS["fill_gate"](payload, {})
    assert built.stem == el.stem and built.answers == [["a", "b"]]
