import pytest
from django.urls import reverse

from courses import quiz
from courses.models import Enrollment
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import DragToImageQuestionElementFactory
from tests.factories import DragZoneFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_resume_routing_uses_default_branch():
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="A", order=0)
    # answer_to_json(answer) takes ONE arg (no question); answer_from_json/rehydrate
    # take (question, latest_answer) — do not conflate.
    payload = ["A", ""]
    assert quiz.answer_to_json(payload) == payload
    assert quiz.answer_from_json(q, payload) == payload
    sel, vals = quiz.rehydrate(q, payload)
    assert sel == set() and vals == payload


def test_results_row_rebuilds_reveal_for_unanswered():
    # mark(build_answer(empty)) must yield a per-zone reveal without error
    q = DragToImageQuestionElementFactory()
    DragZoneFactory(question=q, correct_label="A", order=0)
    DragZoneFactory(question=q, correct_label="B", order=1)
    from django.http import QueryDict

    r = q.mark(q.build_answer(QueryDict()))
    assert len(r.reveal) == 2 and all("accepted" in d for d in r.reveal)


def test_lesson_loads_katex_when_math_in_zone_label(client):
    """KaTeX branch: math only in correct_label (not stem) genuinely exercises the
    DragToImageQuestionElement isinstance branch in _question_has_math."""
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    q = DragToImageQuestionElementFactory(stem="plain stem", distractors="")
    DragZoneFactory(question=q, correct_label=r"\(x^2\)", order=0)
    add_element(unit, q)
    body = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "katex" in body.lower()


def test_lesson_has_questions_includes_dragtoimage(client):
    """CT gate: has_questions is truthy when the only question is a DragToImage."""
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    q = DragToImageQuestionElementFactory(stem="Identify the parts", distractors="")
    DragZoneFactory(question=q, correct_label="A", order=0)
    add_element(unit, q)
    # We can't inspect ctx directly via the test client; assert the response is 200
    # and that the question appears in the page (proxy for has_questions being True
    # — if CT gate were broken the question block would still render, but this test
    # is the contract-level check for the gate being wired).
    response = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert response.status_code == 200
    assert response.context["has_questions"]
