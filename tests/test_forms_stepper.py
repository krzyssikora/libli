import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import StepperElementForm
from courses.element_forms import build_stepper_formset

pytestmark = pytest.mark.django_db


def test_registered():
    assert FORM_FOR_TYPE["stepper"] is StepperElementForm


def test_formset_has_content_field():
    fs = build_stepper_formset(data=None, files=None, instance=None)
    assert "content" in fs.empty_form.fields


def _mgmt(n, initial=0):
    return {
        "steps-TOTAL_FORMS": str(n),
        "steps-INITIAL_FORMS": str(initial),
        "steps-MIN_NUM_FORMS": "0",
        "steps-MAX_NUM_FORMS": "1000",
    }


def test_formset_rejects_zero_nonblank_steps():
    data = {**_mgmt(1), "steps-0-content": "   "}
    fs = build_stepper_formset(data=data, files=None, instance=None)
    assert not fs.is_valid()


def test_formset_accepts_one_step_and_drops_blank_extras():
    data = {**_mgmt(2), "steps-0-content": "x", "steps-1-content": "  "}
    fs = build_stepper_formset(data=data, files=None, instance=None)
    assert fs.is_valid(), fs.non_form_errors()


def test_formset_rejects_over_max_steps():
    data = _mgmt(21)
    for i in range(21):
        data[f"steps-{i}-content"] = f"s{i}"
    fs = build_stepper_formset(data=data, files=None, instance=None)
    assert not fs.is_valid()
