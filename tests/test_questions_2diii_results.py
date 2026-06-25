# tests/test_questions_2diii_results.py
import pytest

from courses.models import ExtendedResponseQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _submit_quiz(client, *questions):
    """Log in a student, build a quiz unit holding `questions`, submit it, and return
    the decoded results-page body. Mirrors tests/test_questions_2d_results.py."""
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    for q in questions:
        add_element(unit, q)
    client.get(f"{base}/")  # materialize the QuizSubmission
    client.post(f"{base}/finish/")
    return client.get(f"{base}/results/").content.decode()


def test_all_review_quiz_shows_pending_footer(client):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Essay?", marking_mode="R", max_marks="5"
    )
    body = _submit_quiz(client, q)
    assert "result-summary__score\">—" in body  # [A]-only total empty (max_score 0.00 -> falsy)...
    assert "awaiting review" in body.lower()  # ...but the footer still renders.


def test_review_row_shows_up_to_marks(client):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Essay?", marking_mode="R", max_marks="3"
    )
    body = _submit_quiz(client, q)
    assert "Awaiting review" in body
    assert "up to" in body.lower() and "3" in body


def test_not_marked_excluded_from_pending(client):
    n = ExtendedResponseQuestionElement.objects.create(stem="N?", marking_mode="N")
    r = ExtendedResponseQuestionElement.objects.create(
        stem="R?", marking_mode="R", max_marks="2"
    )
    body = _submit_quiz(client, n, r)
    # footer counts only the [R]: singular "1 question awaiting review".
    assert "1 question awaiting review" in body.lower()


def test_unanswered_only_forbidden_no_false_check(client):
    # Single-question quiz: an [A] only-forbidden response never answered. The results
    # reveal must be the neutral guide (lists "banned", NO green ✓ anywhere on the
    # page).
    q = ExtendedResponseQuestionElement.objects.create(
        stem="OnlyForbidden",
        required_keywords="",
        forbidden_keywords="banned",
        marking_mode="A",
    )
    body = _submit_quiz(client, q)
    assert "banned" in body
    assert "✓" not in body


def test_answered_required_keyword_shows_checkmark_on_results(client):
    # Regression guard: the results row include wires `answered=row["answered"]` where
    # `_results_row` sets `answered = response is not None and
    # response.latest_answer is not None`. This test proves the `{% if answered %}`
    # branch of _reveal_extendedresponse.html renders the per-keyword ✓ breakdown.
    # If the wiring silently passed `answered=False` (the neutral-guide branch), the
    # ✓ assertion below would fail — the neutral guide never emits ✓ for required
    # keywords, only the `{% if answered %}` branch does.
    #
    # The answer is PARTIAL (one of two required keywords found), not fully correct:
    # a fully-correct row has its whole reveal suppressed now, so a partial answer is
    # what exercises the answered=True ✓/✗ breakdown on the results page.
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain alpha and beta.",
        required_keywords="alpha\nbeta",
        marking_mode="A",
        max_marks="1",
    )
    el = add_element(unit, q)
    # Materialise the QuizSubmission then POST an answer with only one keyword.
    client.get(f"{base}/")
    client.post(
        f"{base}/q/{el.pk}/answer/",
        {"answer": "alpha is important"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    client.post(f"{base}/finish/")
    body = client.get(f"{base}/results/").content.decode()
    # The answered=True branch renders a ✓ next to the found required keyword (alpha)
    # and a ✗ next to the missing one (beta). The neutral guide (answered=False) never
    # emits ✓, so this assertion distinguishes the two branches.
    assert "alpha" in body
    assert "✓" in body
