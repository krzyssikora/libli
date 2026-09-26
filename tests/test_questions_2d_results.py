# tests/test_questions_2d_results.py
import re

import pytest

from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.reveal_pr2_kit import key


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

    client.post(
        f"{base}/q/{el_c.pk}/answer/",
        {"slot": ["Paris"]},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    client.post(
        f"{base}/q/{el_w.pk}/answer/", {"slot": ["Oslo"]}, HTTP_X_REQUESTED_WITH="fetch"
    )
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    # A fully-correct row is terse: its whole reveal is suppressed (no ✓ list, no
    # token text) — there is nothing useful to add once you got it all right. Only
    # the wrong + unanswered rows reveal the accepted token, so "Madrid" (wrong) and
    # "Lisbon" (unanswered, reconstructed via mark(build_answer(QueryDict()))) appear
    # while "Paris" (correct) and the answer-correct tick never render.
    assert "answer-correct" not in body
    # PR 2 (spec 2026-09-25 §4): replaces `"Madrid" in body and "Lisbon" in body`
    # and `"Paris" not in body` -- each row renders the question (every select
    # lists the whole pool), so the key is read from each row's key copy.
    rows = body.split('class="quiz-results__item')[1:4]
    assert "data-answer-switch" not in rows[0] and "data-answer-key" not in rows[0]
    assert 'value="Madrid" selected' in key(rows[1])
    assert 'value="Lisbon" selected' in key(rows[2])


@pytest.mark.django_db
def test_results_matchpair_row_shows_left_label(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = MatchPairQuestionElement.objects.create(stem="<p>m</p>", marking_mode="A")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    add_element(unit, q)  # unanswered → still reveals
    client.get(f"{base}/")  # GET the quiz first → materializes the QuizSubmission (the
    # student flow; don't rely on quiz_finish create-if-absent)
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    # PR 2 (spec 2026-09-25 §4): replaces `"France" in body and "Paris" in body`
    # -- the row's key copy pairs the left label with the accepted token.
    assert re.search(
        r'France</span><select[^>]*>(?:(?!</select>).)*value="Paris" selected',
        key(body),
        re.S,
    )
