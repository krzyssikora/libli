import pytest

from courses.models import FillGateElement

pytestmark = pytest.mark.django_db


def test_canonical_answers_first_alternative_per_blank():
    el = FillGateElement(answers=[["color", "colour"], ["x"]])
    assert el.canonical_answers == ["color", "x"]


def test_canonical_answers_handles_empty_shapes():
    assert FillGateElement(answers=[]).canonical_answers == []
    assert FillGateElement(answers=[[]]).canonical_answers == [""]
    assert FillGateElement(answers=None).canonical_answers == []
