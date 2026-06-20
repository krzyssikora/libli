import pytest
from django.urls import reverse

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    Element,
    Enrollment,
)
from tests.factories import ContentNodeFactory, CourseFactory, make_login


@pytest.mark.django_db
def test_lesson_loads_katex_when_only_math_is_in_a_token(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    q = DragFillBlankQuestionElement.objects.create(stem="x ￿0￿", distractors="")
    DragBlank.objects.create(question=q, correct_token=r"\(x^2\)")
    Element.objects.create(unit=unit, content_object=q)
    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "katex" in body.lower()  # KaTeX assets loaded because a token carries math
