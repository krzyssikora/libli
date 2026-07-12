import pytest

from courses.builder import _NESTABLE_FORM_KEY_ALIASES
from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import SwitchGateElement
from courses.switchgate import SENTINEL_TOKEN
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError

pytestmark = pytest.mark.django_db


def test_registered_and_nestable():
    assert "switch_gate" in SERIALIZERS
    assert "switch_gate" in VALIDATORS
    assert "switch_gate" in BUILDERS
    assert "switch_gate" in NESTABLE_TYPE_KEYS
    assert _NESTABLE_FORM_KEY_ALIASES["switchgate"] == "switch_gate"
    # invariant guarded by the tabs transfer tests
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


def test_round_trip():
    model_cls, ser = SERIALIZERS["switch_gate"]
    assert model_cls is SwitchGateElement
    el = SwitchGateElement.objects.create(
        stem=SENTINEL_TOKEN, options=["a", "b", "c"], answer=2
    )
    payload = ser(el, set())  # real serializers take (concrete, media_ids)
    assert payload == {"stem": SENTINEL_TOKEN, "options": ["a", "b", "c"], "answer": 2}
    built, media = BUILDERS["switch_gate"](payload, {})
    assert built.stem == SENTINEL_TOKEN
    assert built.options == ["a", "b", "c"]
    assert built.answer == 2
    assert media == ()


# Validators signal rejection by RAISING TransferError (they do not append to a
# list and do not return an error collection); the media arg is a set().
def _rejects(data):
    with pytest.raises(TransferError):
        VALIDATORS["switch_gate"](data, "el1", set())


def _accepts(data):
    VALIDATORS["switch_gate"](data, "el1", set())  # must NOT raise


def test_validator_rejects_few_options():
    _rejects({"stem": SENTINEL_TOKEN, "options": ["a"], "answer": 0})


def test_validator_rejects_bad_answer():
    _rejects({"stem": SENTINEL_TOKEN, "options": ["a", "b"], "answer": 5})


def test_validator_rejects_missing_sentinel():
    _rejects({"stem": "no token", "options": ["a", "b"], "answer": 0})


def test_validator_accepts_valid():
    _accepts({"stem": SENTINEL_TOKEN, "options": ["a", "b"], "answer": 0})
