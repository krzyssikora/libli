from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_stored_result_carries_annotated():
    from courses.views import _stored_result

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)
    bad = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="hint B"
    )

    # a minimal stand-in for QuestionResponse: latest_answer is what the student
    # submitted (the distractor), fraction is the frozen wrong score.
    class _Resp:
        latest_answer = [bad.pk]  # answer_from_json for choice -> set of pks
        fraction = Decimal("0.0000")

    res = _stored_result(q, _Resp())
    assert res.annotated == frozenset({bad.pk})  # annotated survives the rebuild
    assert res.correct is False


@pytest.mark.django_db
def test_choice_nudge_withheld_prelock_then_revealed(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ChoiceQuestionElement.objects.create(
        stem="<p>Pick</p>", multiple=False, marking_mode="A", max_attempts=2
    )
    Choice.objects.create(question=q, text="A", is_correct=True)
    bad = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="NUDGE-B"
    )
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"

    # Wrong, 1 attempt remaining -> withhold: the nudge must NOT render.
    body1 = client.post(
        url, {"choice": [str(bad.pk)]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "NUDGE-B" not in body1
    assert "question__reveal" not in body1

    # Wrong on the LAST attempt -> reveal: the nudge is now shown.
    body2 = client.post(
        url, {"choice": [str(bad.pk)]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "NUDGE-B" in body2


@pytest.mark.django_db
def test_choice_nudge_on_results_page(client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_login(client, "stu")
    course = CourseFactory(slug="rc")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    q = ChoiceQuestionElement.objects.create(stem="<p>Pick</p>", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True, order=0)
    bad = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="NUDGE-B", order=1
    )
    el = Element.objects.create(unit=unit, content_object=q)
    sub = QuizSubmission.objects.create(
        student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    # a wrong, locked response selecting the annotated distractor
    QuestionResponse.objects.create(
        submission=sub,
        element=el,
        attempt_count=1,
        latest_answer=[bad.pk],
        fraction=Decimal("0.0000"),
        locked=True,
    )
    url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    body = client.get(url).content.decode()
    assert "NUDGE-B" in body  # feedback rendered on the results reveal
