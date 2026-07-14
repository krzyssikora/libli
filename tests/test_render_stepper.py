import pytest

from courses.models import StepperElement
from courses.models import StepperStep
from courses.templatetags.courses_manage_extras import element_summary

pytestmark = pytest.mark.django_db


def _stepper(prompt="", steps=("a", "b", "c")):
    el = StepperElement.objects.create(prompt=prompt)
    for c in steps:
        StepperStep.objects.create(stepper=el, content=c)
    return el


def test_no_step_span_is_server_hidden():
    html = _stepper().render()
    # Every step span is tagged and NONE carries a server-side hidden attribute.
    assert html.count("data-stepper-step") == 3
    # Crude but effective: no "hidden" token appears on a step span line.
    assert "stepper__step" in html
    for line in html.splitlines():
        if "stepper__step" in line:
            assert "hidden" not in line


def test_button_is_hidden_and_btn_small():
    html = _stepper().render()
    assert "data-stepper-next" in html
    assert "btn btn--small" in html
    # The button (only) is server-hidden.
    assert any("data-stepper-next" in ln and "hidden" in ln for ln in html.splitlines())


def test_prompt_only_when_present():
    assert "stepper__prompt" not in _stepper(prompt="").render()
    assert "stepper__prompt" in _stepper(prompt="Follow along").render()


def test_content_is_autoescaped():
    html = _stepper(steps=("<script>x</script>",)).render()
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_element_summary_uses_prompt_then_first_step():
    assert element_summary(_stepper(prompt="Intro")) == "Intro"
    assert element_summary(_stepper(prompt="", steps=("first",))) == "first"
