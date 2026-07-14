import pytest

from courses.models import ELEMENT_MODELS
from courses.models import Element
from courses.models import StepperElement
from courses.models import StepperStep

pytestmark = pytest.mark.django_db


def test_stepper_in_element_models():
    assert "stepperelement" in ELEMENT_MODELS


def test_steps_relation_and_ordering():
    el = StepperElement.objects.create(prompt="Follow along")
    s0 = StepperStep.objects.create(stepper=el, content=r"2^4\cdot 2^6=")
    s1 = StepperStep.objects.create(stepper=el, content=r"2^{4+6}=")
    s2 = StepperStep.objects.create(stepper=el, content=r"2^{10}")
    assert list(el.steps.all()) == [s0, s1, s2]
    assert [s.order for s in el.steps.all()] == [0, 1, 2]


def test_prompt_and_content_are_stripped_on_save():
    el = StepperElement.objects.create(prompt="  Hi  ")
    assert el.prompt == "Hi"
    s = StepperStep.objects.create(stepper=el, content="  x  ")
    assert s.content == "x"


def test_deleting_element_cascades_to_steps_and_joinrow():
    from tests.factories import ContentNodeFactory

    unit = ContentNodeFactory(kind="unit", parent=None)
    el = StepperElement.objects.create(prompt="")
    StepperStep.objects.create(stepper=el, content="a")
    Element.objects.create(unit=unit, content_object=el)
    el_pk = el.pk
    el.delete()
    assert not StepperStep.objects.filter(stepper_id=el_pk).exists()
    assert not Element.objects.filter(object_id=el_pk).exists()


def test_constants():
    assert StepperElement.MIN_STEPS == 1
    assert StepperElement.MAX_STEPS == 20
    assert StepperElement.MAX_LEN == 500
