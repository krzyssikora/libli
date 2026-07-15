import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_choice_add_form_has_adaptive_feedback_wiring(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "choice-single", "unit": unit.pk},
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    # Two-tier option layout: primary line + subordinate feedback tier.
    assert "choice-row__main" in body
    assert "choice-row__feedback" in body
    # Data hooks editor.js reads to adapt the feedback prompt to the option's state.
    assert "data-fb-correct=" in body
    assert "data-fb-distractor=" in body
    # The feedback field carries a no-JS baseline placeholder.
    assert 'name="choices-0-feedback"' in body
    assert "placeholder=" in body
