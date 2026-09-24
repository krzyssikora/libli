"""Lesson fill-blank feedback marks each blank in place (green/red) instead of
listing "Correct answer: X" under the question.

The list made a learner match each row back to its blank — and a correct row was a
bare tick with nothing beside it. In a LESSON the list is dropped; a QUIZ keeps it
(its feedback is built by courses.quiz.quiz_feedback_context and is untouched).

Transport: the live check answers with the WHOLE element (question.js / editor.js
swap the form body via data-question-inline, as choice already does), so the per-
blank classes land on the inputs; the no-JS and restore paths render them directly.
"""

import re

import pytest
from django.urls import reverse

from courses.fillblank import parse
from courses.fillblank import render_inputs
from courses.models import Blank
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillBlankQuestionElement
from courses.models import UnitProgress
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student

_BLANK_INPUT_RE = re.compile(r'<input[^>]*name="blank"[^>]*>')
_REVEAL = "Correct answer:"


def _blank_inputs(html):
    tags = _BLANK_INPUT_RE.findall(html)
    assert tags, "no <input name='blank'> rendered"
    return tags


def _assert_right(tag):
    assert "is-correct" in tag, f"a right blank must read as correct: {tag}"
    assert "is-incorrect" not in tag
    assert "aria-invalid" not in tag


def _assert_wrong(tag):
    assert "is-incorrect" in tag, f"a wrong blank must read as incorrect: {tag}"
    assert 'aria-invalid="true"' in tag, f"colour alone must not carry it: {tag}"


def _assert_plain(tag):
    assert "is-correct" not in tag and "is-incorrect" not in tag, tag
    assert "aria-invalid" not in tag


# ── render_inputs ────────────────────────────────────────────────────────────


def test_render_inputs_marks_each_blank_with_its_verdict():
    token_stem, _ = parse("{{a}} and {{b}} and {{c}}")
    html = render_inputs(token_stem, ["a", "x", ""], verdicts=[True, False, False])
    right, wrong, empty = _blank_inputs(html)
    _assert_right(right)
    _assert_wrong(wrong)
    _assert_wrong(empty)
    assert "readonly" not in html, "a partly-wrong answer must stay editable"


def test_render_inputs_without_verdicts_marks_nothing():
    token_stem, _ = parse("{{a}} and {{b}}")
    for tag in _blank_inputs(render_inputs(token_stem, ["a", "x"])):
        _assert_plain(tag)


# ── lesson paths ─────────────────────────────────────────────────────────────


def _enrolled(client):
    student = make_student(client, "fb_verdicts")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    return student, unit


def _make_fillblank(unit, author_stem, accepted):
    token_stem, _blanks = parse(author_stem)
    obj = FillBlankQuestionElement.objects.create(stem=token_stem)
    for i, acc in enumerate(accepted):
        Blank.objects.create(question=obj, order=i, accepted=acc)
    return Element.objects.create(unit=unit, content_object=obj)


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


_STEM = "{{paris}} on the {{seine}}."
_ACCEPTED = ["paris", "seine"]


@pytest.mark.django_db
def test_live_check_returns_the_element_with_painted_blanks(client):
    _student, unit = _enrolled(client)
    row = _make_fillblank(unit, _STEM, _ACCEPTED)
    body = client.post(
        _check_url(unit, row.pk),
        {"blank": ["paris", "thames"]},
        HTTP_X_REQUESTED_WITH="fetch",
    ).content.decode()
    # The whole element, flagged for question.js's form-body swap — a bare feedback
    # fragment carries no inputs to paint.
    assert "data-question-inline" in body
    right, wrong = _blank_inputs(body)
    _assert_right(right)
    _assert_wrong(wrong)
    assert "question__verdict is-incorrect" in body, "the verdict line stays"
    assert _REVEAL not in body, "a lesson no longer lists the correct answers"


@pytest.mark.django_db
def test_live_check_keeps_the_explanation(client):
    _student, unit = _enrolled(client)
    row = _make_fillblank(unit, _STEM, _ACCEPTED)
    row.content_object.explanation = "<p>Paris sits on the Seine.</p>"
    row.content_object.save()
    body = client.post(
        _check_url(unit, row.pk),
        {"blank": ["paris", "thames"]},
        HTTP_X_REQUESTED_WITH="fetch",
    ).content.decode()
    assert "Paris sits on the Seine." in body


@pytest.mark.django_db
def test_nojs_check_paints_blanks_and_drops_the_list(client):
    _student, unit = _enrolled(client)
    row = _make_fillblank(unit, _STEM, _ACCEPTED)
    body = client.post(
        _check_url(unit, row.pk), {"blank": ["paris", "thames"]}
    ).content.decode()
    right, wrong = _blank_inputs(body)
    _assert_right(right)
    _assert_wrong(wrong)
    assert _REVEAL not in body


@pytest.mark.django_db
def test_restore_paints_blanks_and_drops_the_list(client):
    student, unit = _enrolled(client)
    row = _make_fillblank(unit, _STEM, _ACCEPTED)
    UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={str(row.pk): {"answer": ["paris", "thames"]}},
    )
    body = client.get(_lesson_url(unit)).content.decode()
    right, wrong = _blank_inputs(body)
    _assert_right(right)
    _assert_wrong(wrong)
    assert _REVEAL not in body


@pytest.mark.django_db
def test_nojs_check_does_not_paint_a_sibling(client):
    # The no-JS re-render hands ONE page-level mark_result to every element; an
    # untouched sibling fill-blank must not inherit this question's verdicts.
    _student, unit = _enrolled(client)
    row_one = _make_fillblank(unit, "Cap is {{paris}}.", ["paris"])
    _make_fillblank(unit, "River is {{seine}}.", ["seine"])
    body = client.post(_check_url(unit, row_one.pk), {"blank": ["x"]}).content.decode()
    answered, sibling = _blank_inputs(body)
    _assert_wrong(answered)
    _assert_plain(sibling)


# ── editor try-it (lesson) ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_editor_try_returns_the_element_with_painted_blanks(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    row = _make_fillblank(unit, _STEM, _ACCEPTED)
    body = client.post(
        reverse(
            "courses:manage_element_try", kwargs={"slug": course.slug, "pk": row.pk}
        ),
        {"blank": ["paris", "thames"]},
        HTTP_X_REQUESTED_WITH="fetch",
    ).content.decode()
    assert "data-question-inline" in body
    right, wrong = _blank_inputs(body)
    _assert_right(right)
    _assert_wrong(wrong)
    assert _REVEAL not in body
    # The manage fragment must not ship the student endpoint.
    assert "/check/" not in body


# ── quiz is untouched ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_quiz_fillblank_still_lists_the_correct_answers(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    token_stem, _ = parse(_STEM)
    obj = FillBlankQuestionElement.objects.create(stem=token_stem, max_attempts=1)
    for i, acc in enumerate(_ACCEPTED):
        Blank.objects.create(question=obj, order=i, accepted=acc)
    row = Element.objects.create(unit=unit, content_object=obj)
    body = client.post(
        f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{row.pk}/answer/",
        {"blank": ["paris", "thames"]},
        HTTP_X_REQUESTED_WITH="fetch",
    ).content.decode()
    assert _REVEAL in body, "the quiz reveal is a separate redesign; keep it for now"
