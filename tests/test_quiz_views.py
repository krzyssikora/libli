import pytest
from django.http import Http404

from courses.access import get_node_or_404
from tests.factories import ContentNodeFactory, make_quiz_unit


@pytest.mark.django_db
def test_require_quiz_404s_lesson():
    lesson = ContentNodeFactory(unit_type="lesson")
    with pytest.raises(Http404):
        get_node_or_404(lesson.pk, lesson.course.slug, require_unit=True, require_quiz=True)


@pytest.mark.django_db
def test_require_quiz_passes_quiz():
    quiz = make_quiz_unit()
    node = get_node_or_404(quiz.pk, quiz.course.slug, require_unit=True, require_quiz=True)
    assert node.pk == quiz.pk
