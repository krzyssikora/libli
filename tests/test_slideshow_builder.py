import pytest

from courses.builder import save_element
from courses.models import SlideBreakElement
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_save_element_creates_slide_break():
    # a quiz unit; save_element takes (course, unit_pk, type_key, ref, post, files)
    unit = make_quiz_unit()
    post = {"unit_token": unit.updated.isoformat()}
    save_element(unit.course, unit.pk, "slidebreak", "new", post, {})
    assert any(
        isinstance(j.content_object, SlideBreakElement) for j in unit.elements.all()
    )
