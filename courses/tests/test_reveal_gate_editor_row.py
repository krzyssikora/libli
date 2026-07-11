import pytest
from django.http import QueryDict
from django.template.loader import render_to_string

from courses import builder
from courses.models import ContentNode
from courses.models import Element

pytestmark = pytest.mark.django_db


@pytest.fixture
def lesson_unit():
    """A LESSON-type unit belonging to a fresh course. Mirrors the local fixture in
    test_reveal_gate_form_builder.py -- no shared `lesson_unit` fixture exists in this
    project, so it's defined locally from the same factory."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def quiz_unit():
    """A QUIZ-type unit, for the "inactive in quizzes" flag test."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    unit.unit_type = ContentNode.UnitType.QUIZ
    unit.save()
    return unit


def _make_gate_join(unit, label="Show more"):
    post = QueryDict(mutable=True)
    post["label"] = label
    post["unit_token"] = unit.updated.isoformat()  # REQUIRED: _check_token
    builder.save_element(unit.course, unit.pk, "revealgate", "new", post, {})
    unit.refresh_from_db()
    return Element.objects.get(unit=unit, content_type__model="revealgateelement")


def _render_row(el_join, unit):
    # The real _element_row.html reads `obj` (the content_object) for the
    # label; the caller passes it explicitly.
    return render_to_string(
        "courses/manage/editor/_element_row.html",
        {"el": el_join, "obj": el_join.content_object, "unit": unit},
    )


def test_row_shows_label_and_edit_control(lesson_unit):
    join = _make_gate_join(lesson_unit)
    html = _render_row(join, lesson_unit)
    assert "Show more" in html
    assert "data-add-type" not in html  # it's a row, not a palette card
    assert "el-row" in html
    # standard edit affordance present (the real editable-row marker)
    assert "el-act-edit" in html
    assert "inactive in quizzes" not in html.lower()


def test_row_quiz_inactive_flag(quiz_unit):
    join = _make_gate_join(quiz_unit)
    html = _render_row(join, quiz_unit)
    assert "inactive in quizzes" in html.lower()
