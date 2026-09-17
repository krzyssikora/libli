"""Review-waiting wording in Polish (results-table spec O13, O14; T14): „sprawdzenie",
never „ocena", wherever a submission waits for a teacher. The graded msgids keep
„ocena": grading is what they mean."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

OLD = "na ocenę"


def _polish(client):
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()


def _soup(resp):
    assert resp.status_code == 200
    return BeautifulSoup(resp.content.decode(), "html.parser")


def _review_question(max_marks):
    return ExtendedResponseQuestionElement.objects.create(
        stem="<p>Esej?</p>",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )


def _finished_review_quiz(client, marks):
    """A student finishes, through the real quiz views, a quiz of REVIEW questions
    (one per entry of `marks`). Returns the unit."""
    user = make_login(client, "t14stu")
    _polish(client)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    for max_marks in marks:
        add_element(unit, _review_question(max_marks))
    quiz_kwargs = {"slug": unit.course.slug, "node_pk": unit.pk}
    # materialise the QuizSubmission
    client.get(reverse("courses:quiz_unit", kwargs=quiz_kwargs))
    client.post(reverse("courses:quiz_finish", kwargs=quiz_kwargs))
    return unit


@pytest.mark.parametrize(
    ("marks", "footer"),
    [
        (["1"], "1 pytanie oczekuje na sprawdzenie (do 1 dodatkowego punktu)"),
        (
            ["0.5", "0.5"],
            "2 pytania oczekują na sprawdzenie (do 1 dodatkowego punktu)",
        ),
        (["0.2"] * 5, "5 pytań oczekuje na sprawdzenie (do 1 dodatkowego punktu)"),
        (["2"], "1 pytanie oczekuje na sprawdzenie (do 2 dodatkowych punktów)"),
        (
            ["1", "1"],
            "2 pytania oczekują na sprawdzenie (do 2 dodatkowych punktów)",
        ),
        (["1"] * 5, "5 pytań oczekuje na sprawdzenie (do 5 dodatkowych punktów)"),
    ],
)
def test_rt_t14_quiz_results_badge_and_all_six_plural_forms(client, marks, footer):
    unit = _finished_review_quiz(client, marks)
    soup = _soup(
        client.get(
            reverse(
                "courses:quiz_results",
                kwargs={"slug": unit.course.slug, "node_pk": unit.pk},
            )
        )
    )
    meta = soup.select_one(".result-summary__meta").get_text(" ", strip=True)
    assert meta == footer
    badge = soup.select_one(".badge--review").get_text(" ", strip=True)
    assert badge.startswith("Oczekuje na sprawdzenie (")
    assert OLD not in soup.select_one("article.quiz-results").get_text(" ")


def test_rt_t14_course_results_awaiting_badge(client):
    unit = _finished_review_quiz(client, ["1"])
    soup = _soup(
        client.get(reverse("courses:course_results", kwargs={"slug": unit.course.slug}))
    )
    badge = soup.select_one("li.result-row .badge--review")
    assert badge.get_text(strip=True) == "Oczekuje na sprawdzenie"
    assert OLD not in soup.select_one("article.course-results").get_text(" ")


def test_rt_t14_teacher_pages_say_sprawdzenie(client):
    pa = make_pa(client, "t14pa")
    _polish(client)
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Esej"
    )
    add_element(quiz, _review_question("1"))
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    QuizSubmission.objects.create(
        student=pupil,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    queue = _soup(
        client.get(reverse("courses:manage_review_queue", kwargs={"slug": course.slug}))
    )
    heading = queue.select("section.manage > h2")[0].get_text(" ", strip=True)
    assert heading.startswith("Oczekuje na sprawdzenie")
    student_page = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    progress = _soup(client.get(f"{student_page}?mode=progress"))
    assert progress.select_one(".pill--awaiting").get_text(strip=True) == (
        "oczekuje na sprawdzenie"
    )
    answers = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student_quiz",
                kwargs={
                    "slug": course.slug,
                    "student_pk": pupil.pk,
                    "node_pk": quiz.pk,
                },
            )
        )
    )
    header_pill = answers.select_one(".answers__status .pill--awaiting")
    assert header_pill.get_text(strip=True) == "oczekuje na sprawdzenie"
    badge = answers.select_one(".answers__verdict .badge").get_text(" ", strip=True)
    assert badge == "Oczekuje na sprawdzenie (do 1 punktu)"
    for soup in (queue, progress, answers):
        assert OLD not in soup.select_one("section.manage").get_text(" ")


def test_rt_t14_question_feedback_says_przeslano_do_sprawdzenia():
    with translation.override("pl"):
        html = render_to_string(
            "courses/elements/_quiz_question_feedback.html", {"neutral": "review"}
        )
    verdict = BeautifulSoup(html, "html.parser").select_one(".question__verdict")
    assert verdict.get_text(strip=True) == "Przesłano do sprawdzenia"


def test_rt_t14_graded_wording_keeps_ocena():
    with translation.override("pl"):
        assert gettext("Quiz graded") == "Quiz oceniony"
        assert gettext("Your quiz was graded") == "Twój quiz został oceniony"
        assert gettext("submitted — not graded") == "przesłano — bez oceny"
