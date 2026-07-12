import pytest

from courses.models import SpoilerElement
from courses.templatetags.courses_manage_extras import element_summary

pytestmark = pytest.mark.django_db


def test_summary_uses_label():
    el = SpoilerElement.objects.create(label="Show solution", body="<p>x</p>")
    assert element_summary(el) == "Show solution"


def test_summary_falls_back_to_reveal_not_class_name():
    el = SpoilerElement.objects.create(label="", body="<p>x</p>")
    summary = str(element_summary(el))
    assert summary == "Reveal"  # EN catalog default
    assert summary != "SpoilerElement"  # never the raw class name
