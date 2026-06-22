import pytest

from courses.models import ExtendedResponseQuestionElement
from courses.views import build_lesson_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import add_element

pytestmark = pytest.mark.django_db


def test_lesson_with_only_extended_response_has_questions():
    # add_element (tests/factories.py) attaches a concrete element to a unit via the
    # Element GFK join-row — the same helper tests/test_questions_2d_results.py uses.
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.", required_keywords="alpha", marking_mode="A"
    )
    add_element(unit, q)
    ctx = build_lesson_context(unit, UserFactory())
    assert ctx["has_questions"] is True
