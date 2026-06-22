import pytest

from courses import quiz as quizmod
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionResponse
from courses.views import _results_row
from courses.views import build_lesson_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

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


def test_resume_routing_stays_on_default_branch():
    q = ExtendedResponseQuestionElement.objects.create(
        stem="x", required_keywords="alpha", marking_mode="A"
    )
    assert quizmod.answer_to_json("alpha text") == "alpha text"
    assert quizmod.answer_from_json(q, "alpha text") == "alpha text"
    assert quizmod.rehydrate(q, "alpha text") == (set(), "alpha text")


def test_quiz_auto_scores_partial(client):
    # End-to-end [A] scoring through the real quiz_answer view (I4).
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.",
        required_keywords="alpha\nbeta",
        marking_mode="A",
        max_marks="2",
    )
    el = add_element(unit, q)
    client.get(f"{base}/")  # materialize the QuizSubmission (student flow)
    client.post(
        f"{base}/q/{el.pk}/answer/",
        {"answer": "alpha only"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    r = QuestionResponse.objects.get(element_id=el.pk)
    assert float(r.fraction) == 0.5  # 1 of 2 required keywords found


def test_review_mode_records_unscored_and_shows_card(client):
    # 2c's _quiz_question_feedback.html renders the neutral card type-agnostically.
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = ExtendedResponseQuestionElement.objects.create(stem="Essay?", marking_mode="R")
    el = add_element(unit, q)
    client.get(f"{base}/")
    resp = client.post(
        f"{base}/q/{el.pk}/answer/",
        {"answer": "my essay"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert b"Submitted for review" in resp.content
    r = QuestionResponse.objects.get(element_id=el.pk)
    assert r.fraction is None and r.reviewed_at is None  # recorded, unscored, pending


def test_results_row_answered_false_when_no_response():
    q = ExtendedResponseQuestionElement.objects.create(
        stem="x", required_keywords="alpha", marking_mode="A"
    )
    assert _results_row(q, None)["answered"] is False
