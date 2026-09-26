"""Extended response in the quiz answer reveal (spec 2026-09-25 §1.4, §2.1, §4, D7):
Show answer reveals its keyword block; no switch, no key copy, lessons unchanged."""

import pytest
from django.urls import reverse

from courses.models import ChoiceQuestionElement
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionResponse
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr3_kit import ER_HALF
from tests.reveal_pr3_kit import ER_RIGHT
from tests.reveal_pr3_kit import ER_WRONG
from tests.reveal_pr3_kit import KEYWORDS
from tests.reveal_pr3_kit import extended


def _quiz(client, username="stu"):
    user = make_login(client, username)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _fetch(client, unit, el, data):
    return client.post(_url(unit, el), data, HTTP_X_REQUESTED_WITH="fetch")


def _page(client, unit):
    return client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    ).content.decode()


def _results(client, unit):
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    return client.get(reverse("courses:quiz_results", kwargs=kw)).content.decode()


def _rows(html):
    return html.split('class="quiz-results__item')[1:]


def test_reveal_list_template_only_for_types_without_an_in_place_view():
    # P6: the keyword block is extended response's view; choice and every key-copy
    # type have an in-place view instead. Imported here so the rest of the file
    # collects (and reports real RED / GREEN) before the helper exists.
    from courses.quiz import reveal_list_template

    assert reveal_list_template(ExtendedResponseQuestionElement()) == (
        "courses/elements/_reveal_extendedresponse.html"
    )
    assert reveal_list_template(ChoiceQuestionElement()) is None
    assert reveal_list_template(FillBlankQuestionElement()) is None


@pytest.mark.django_db
def test_check_answers_whole_element_with_show_answer_no_keywords(client):
    unit = _quiz(client)
    el = add_element(unit, extended())
    body = _fetch(client, unit, el, ER_HALF).content.decode()
    assert "<form" in body and "data-question-inline" in body
    assert "Partly correct" in body and "2 attempts left" in body
    assert KEYWORDS not in body and "betakw" not in body  # no key before the lock
    assert ">alphakw only</textarea>" in body  # the student's text survives the swap
    assert 'name="reveal"' in body and "data-confirm" in body


@pytest.mark.django_db
def test_reveal_shows_the_keyword_block_and_uses_no_attempt(client):
    unit = _quiz(client)
    el = add_element(unit, extended())
    _fetch(client, unit, el, ER_HALF)
    body = _fetch(
        client, unit, el, {"reveal": "1", "answer": "ignored"}
    ).content.decode()
    assert KEYWORDS in body and "betakw" in body and "is-missing" in body
    assert "answer shown" in body and "Partly correct" in body
    assert ">alphakw only</textarea>" in body  # the stored answer, not the POST
    assert "data-answer-switch" not in body and "data-answer-key" not in body  # D7
    assert 'name="reveal"' not in body
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.revealed_at is not None and r.attempt_count == 1
    page = _page(client, unit)
    assert KEYWORDS in page and "answer shown" in page


@pytest.mark.django_db
def test_locked_on_last_attempt_shows_keywords_but_not_when_correct(client):
    unit = _quiz(client)
    wrong = add_element(unit, extended(max_attempts=1))
    right = add_element(unit, extended(max_attempts=1))
    assert KEYWORDS in _fetch(client, unit, wrong, ER_WRONG).content.decode()
    assert KEYWORDS not in _fetch(client, unit, right, ER_RIGHT).content.decode()


@pytest.mark.django_db
def test_nojs_reveal_and_previewer_and_editor(client):
    unit = _quiz(client)
    el = add_element(unit, extended())
    client.post(_url(unit, el), ER_WRONG)
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert KEYWORDS in page and "answer shown" in page
    # The enrolled path above DOES persist (test_reveal_shows_the_keyword_block_and
    # _uses_no_attempt pins its shape); this test's own subject is that the
    # PREVIEWER and EDITOR TRY-IT paths below add no further persistence.
    persisted_before_ephemeral = QuestionResponse.objects.count()
    client.logout()
    staff = make_login(client, "prev_er")
    staff.is_staff = True
    staff.save()
    punit = make_quiz_unit()
    pel = add_element(punit, extended())
    body = _fetch(client, punit, pel, {**ER_WRONG, "attempt": "1"}).content.decode()
    assert 'name="reveal"' in body and KEYWORDS not in body
    body = _fetch(
        client, punit, pel, {**ER_WRONG, "reveal": "1", "attempt": "1"}
    ).content.decode()
    assert KEYWORDS in body and "answer shown" in body
    client.logout()
    pa = make_pa(client, "pa_er")
    course = CourseFactory(owner=pa)
    qunit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz"
    )
    qel = add_element(qunit, extended())
    url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": qel.pk}
    )
    body = client.post(
        url, {**ER_WRONG, "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "<form" in body and 'name="reveal"' in body
    body = client.post(
        url, {**ER_WRONG, "reveal": "1", "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert KEYWORDS in body and body.count("data-question-feedback") == 1
    assert QuestionResponse.objects.count() == persisted_before_ephemeral


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_never_offer_reveal_or_keywords(client, mode):
    unit = _quiz(client)
    el = add_element(unit, extended(marking_mode=mode))
    body = _fetch(client, unit, el, ER_WRONG).content.decode()
    assert 'name="reveal"' not in body and KEYWORDS not in body
    row = _rows(_results(client, unit))[0]
    assert KEYWORDS not in row and "question__reveal-guide" not in row


@pytest.mark.django_db
def test_results_extended_rows_as_they_ended(client):
    unit = _quiz(client)
    revealed = add_element(unit, extended())
    add_element(unit, extended())  # unanswered
    correct = add_element(unit, extended())
    _fetch(client, unit, revealed, ER_HALF)
    _fetch(client, unit, revealed, {"reveal": "1"})
    _fetch(client, unit, correct, ER_RIGHT)
    rows = _rows(_results(client, unit))
    assert KEYWORDS in rows[0] and "answer shown" in rows[0]
    assert ">alphakw only</textarea>" in rows[0]
    # Spec §4 (PR 3): an unanswered extended-response row shows its keywords.
    assert "question__reveal-guide" in rows[1] and "kw--expected" in rows[1]
    assert KEYWORDS not in rows[2] and "question__reveal-guide" not in rows[2]  # P7
    for row in rows:
        assert "<form" not in row and 'type="submit"' not in row
        assert (
            "<textarea" in row
            and "disabled" in row.split("<textarea", 1)[1].split(">", 1)[0]
        )


@pytest.mark.django_db
def test_student_text_is_escaped_everywhere(client):
    # Review Focus 3.
    unit = _quiz(client)
    el = add_element(unit, extended())
    raw = {"answer": "<script>x()</script> &amp; alphakw"}
    body = _fetch(client, unit, el, raw).content.decode()
    assert "<script>x()" not in body and "&lt;script&gt;x()" in body
    assert "<script>x()" not in _page(client, unit)
    body = _fetch(client, unit, el, {"reveal": "1"}).content.decode()
    assert "<script>x()" not in body and "&lt;script&gt;x()" in body
    row = _rows(_results(client, unit))[0]
    assert "<script>x()" not in row and "&lt;script&gt;x()" in row


@pytest.mark.django_db
def test_lesson_check_is_unchanged(client):
    # D11 / §5a: lessons unchanged for extended response -- the fragment, its
    # keyword block, no Show answer; the form now carries data-question-inline (P5).
    student = make_student(client, "ls_er")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    el = add_element(unit, extended())
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    body = client.post(url, ER_WRONG, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "<form" not in body and KEYWORDS in body and 'name="reveal"' not in body
    page = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "data-question-inline" in page and 'name="reveal"' not in page
