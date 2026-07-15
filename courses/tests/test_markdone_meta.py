import pytest

from courses.models import MarkDoneElement
from courses.models import MarkDoneItem

pytestmark = pytest.mark.django_db


def test_element_summary_uses_prompt_or_first_item():
    from courses.templatetags.courses_manage_extras import element_summary

    el = MarkDoneElement.objects.create(prompt="")
    MarkDoneItem.objects.create(element=el, content="first thing")
    assert "first thing" in element_summary(el)


def test_has_math_detects_prompt_and_item():
    from courses.views import _element_has_math

    el = MarkDoneElement.objects.create(prompt="")
    MarkDoneItem.objects.create(element=el, content=r"value \(x^2\)")
    assert _element_has_math(el) is True
