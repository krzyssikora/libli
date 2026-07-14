import pytest

from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import StepperElement
from courses.models import StepperStep
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError

pytestmark = pytest.mark.django_db


def _val(data):
    VALIDATORS["stepper"](data, "el1", {})


def test_stepper_nestable_and_serialized():
    # NESTABLE ⊆ SERIALIZERS invariant: both land in this task together.
    assert "stepper" in NESTABLE_TYPE_KEYS
    assert "stepper" in SERIALIZERS


def test_roundtrip_export_import():
    el = StepperElement.objects.create(prompt="Follow")
    StepperStep.objects.create(stepper=el, content="a")
    StepperStep.objects.create(stepper=el, content="b")
    _model, ser = SERIALIZERS["stepper"]
    payload = ser(el, {})
    assert payload == {"prompt": "Follow", "steps": ["a", "b"]}
    _val(payload)
    obj, children = BUILDERS["stepper"](payload, {})
    # generic loop saves returned children:
    for c in children:
        c.full_clean(exclude=["order"])
        c.save()
    assert obj.prompt == "Follow"
    assert [s.content for s in obj.steps.all()] == ["a", "b"]


def test_missing_prompt_defaults_blank():
    _val({"steps": ["a"]})  # no TransferError
    obj, _ = BUILDERS["stepper"]({"steps": ["a"]}, {})
    assert obj.prompt == ""


def test_missing_steps_is_clean_error():
    with pytest.raises(TransferError):
        _val({"prompt": "x"})


def test_blank_step_rejected():
    with pytest.raises(TransferError):
        _val({"prompt": "", "steps": ["   "]})


def test_over_long_prompt_rejected():
    with pytest.raises(TransferError):
        _val({"prompt": "x" * 501, "steps": ["a"]})


def test_over_max_steps_rejected():
    with pytest.raises(TransferError):
        _val({"prompt": "", "steps": [f"s{i}" for i in range(21)]})
