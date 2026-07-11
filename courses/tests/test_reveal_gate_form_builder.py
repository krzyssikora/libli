import pytest
from django.http import QueryDict

from courses import builder
from courses.builder import NESTABLE_TYPE_KEYS
from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import RevealGateElementForm
from courses.models import Element

pytestmark = pytest.mark.django_db


@pytest.fixture
def lesson_unit():
    """A LESSON-type unit belonging to a fresh course, for builder.save_element
    integration tests. No shared `lesson_unit` fixture exists in this project (the
    tabs/slidebreak builder tests live under top-level tests/ and build a
    (course, unit) pair inline via make_course_with_unit) -- define it locally here
    from the same factory."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


def test_form_registered():
    assert FORM_FOR_TYPE["revealgate"] is RevealGateElementForm


def test_form_valid_with_label():
    f = RevealGateElementForm(data={"label": "Show the answer"})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["label"] == "Show the answer"


def test_form_valid_blank_label():
    f = RevealGateElementForm(data={"label": ""})
    assert f.is_valid(), f.errors


def test_reveal_gate_is_nestable():
    assert "revealgate" in NESTABLE_TYPE_KEYS


def test_builder_creates_top_level_gate(lesson_unit):
    post = QueryDict(mutable=True)
    post["label"] = "Next"
    post["unit_token"] = lesson_unit.updated.isoformat()  # REQUIRED: _check_token
    builder.save_element(
        lesson_unit.course, lesson_unit.pk, "revealgate", "new", post, {}
    )
    row = Element.objects.get(unit=lesson_unit, content_type__model="revealgateelement")
    assert row.parent_id is None
    assert row.content_object.label == "Next"
