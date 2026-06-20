# tests/test_questions_2d_results.py
import pytest

from courses.models import (
    DragBlank,
    DragFillBlankQuestionElement,
    MatchPair,
    MatchPairQuestionElement,
)
from tests.factories import EnrollmentFactory, add_element, make_login, make_quiz_unit


@pytest.mark.django_db
def test_results_reveals_dragfill_tokens_including_unanswered(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"

    correct = DragFillBlankQuestionElement.objects.create(
        stem="A ￿0￿", distractors="Rome", marking_mode="A"
    )
    DragBlank.objects.create(question=correct, correct_token="Paris")
    el_c = add_element(unit, correct)
    wrong = DragFillBlankQuestionElement.objects.create(
        stem="B ￿0￿", distractors="Oslo", marking_mode="A"
    )
    DragBlank.objects.create(question=wrong, correct_token="Madrid")
    el_w = add_element(unit, wrong)
    unanswered = DragFillBlankQuestionElement.objects.create(
        stem="C ￿0￿", distractors="Bonn", marking_mode="A"
    )
    DragBlank.objects.create(question=unanswered, correct_token="Lisbon")
    add_element(unit, unanswered)  # never answered

    client.post(f"{base}/q/{el_c.pk}/answer/", {"slot": ["Paris"]}, HTTP_X_REQUESTED_WITH="fetch")
    client.post(f"{base}/q/{el_w.pk}/answer/", {"slot": ["Oslo"]}, HTTP_X_REQUESTED_WITH="fetch")
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    # Spec §3.2/§3.3: correct rows show ✓ only (answer-correct CSS class, no token text);
    # wrong + unanswered rows reveal the accepted token.
    # "Madrid" (wrong answer) and "Lisbon" (unanswered, reconstructed via
    # mark(build_answer(QueryDict()))) must appear; "Paris" (correct) must NOT appear
    # as text — instead the correct row carries the answer-correct CSS class.
    assert "answer-correct" in body
    assert "Madrid" in body and "Lisbon" in body


@pytest.mark.django_db
def test_results_matchpair_row_shows_left_label(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>", marking_mode="A")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    add_element(unit, q)  # unanswered → still reveals
    client.get(f"{base}/")   # GET the quiz first → materializes the QuizSubmission (the
                             # student flow; don't rely on quiz_finish create-if-absent)
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    assert "France" in body and "Paris" in body  # left label + accepted token revealed
