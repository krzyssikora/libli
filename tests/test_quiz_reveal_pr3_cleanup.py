"""Spec 2026-09-25 §8 PR 3 clean-up: every question type is converted, the answer
lists of the converted types are gone, and every type still renders a wrong lesson
Check and a wrong locked quiz Check without error."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Enrollment
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr2_kit import KINDS as PR2_KINDS
from tests.reveal_pr2_kit import build as build_pr2
from tests.reveal_pr3_kit import ER_HALF
from tests.reveal_pr3_kit import choice
from tests.reveal_pr3_kit import extended

ELEMENTS = Path(settings.BASE_DIR) / "templates" / "courses" / "elements"
# The old list markup (every _reveal_* list's classes), minus extended response's
# keyword block and guide.
_LIST = re.compile(
    r"question__reveal(?!-keywords|-guide)[\w-]*|question__nudge|question__tick"
)


def _question_types():
    """Every concrete QuestionElement subclass -- DERIVED, never a pinned list."""
    out, todo = [], list(QuestionElement.__subclasses__())
    while todo:
        cls = todo.pop()
        todo += cls.__subclasses__()
        if not cls._meta.abstract:
            out.append(cls)
    return out


def test_every_question_type_is_converted():
    types = _question_types()
    assert len(types) >= 10
    assert [t.__name__ for t in types if not t.SUPPORTS_REVEAL] == []


def test_only_extended_response_keeps_an_answer_list():
    kept = {
        t.__name__: t.REVEAL_TEMPLATE for t in _question_types() if t.REVEAL_TEMPLATE
    }
    assert kept == {
        "ExtendedResponseQuestionElement": "courses/elements/_reveal_extendedresponse.html"  # noqa: E501
    }


def test_only_the_keyword_list_and_the_button_remain_on_disk():
    assert sorted(p.name for p in ELEMENTS.glob("_reveal_*.html")) == [
        "_reveal_button.html",
        "_reveal_extendedresponse.html",
    ]


def test_no_stylesheet_styles_the_deleted_lists():
    # The follow-up to the clean-up (plan P8): no markup emits these classes any
    # more, so a rule for one is dead weight. Extended response's keyword block and
    # guide (question__reveal-keywords / -guide) are excluded by _LIST.
    root = Path(settings.BASE_DIR)
    dead = re.compile(_LIST.pattern + r"|answer-correct|answer-wrong")
    sheets = sorted(root.glob("courses/static/**/*.css")) + sorted(
        root.glob("static/**/*.css")
    )
    assert sheets
    found = {
        str(p.relative_to(root)): sorted(set(dead.findall(p.read_text("utf-8"))))
        for p in sheets
    }
    assert {k: v for k, v in found.items() if v} == {}


def _simple(kind, **kw):
    """(question, wrong POST) for the five non-PR-2 types."""
    kw.setdefault("max_attempts", 1)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(stem=parse("{{11}} {{9}}")[0], **kw)
        Blank.objects.create(question=q, order=0, accepted="11")
        Blank.objects.create(question=q, order=1, accepted="9")
        return q, {"blank": ["11", "5"]}
    if kind == "shorttext":
        q = ShortTextQuestionElement.objects.create(stem="?", accepted="Paris", **kw)
        return q, {"answer": "Rome"}
    if kind == "shortnumeric":
        q = ShortNumericQuestionElement.objects.create(stem="?", value="3.14", **kw)
        return q, {"answer": "2"}
    if kind == "choice":
        kit = choice(**kw)
        return kit.question, kit.half
    return extended(**kw), ER_HALF


ALL_KINDS = PR2_KINDS + ("fillblank", "shorttext", "shortnumeric", "choice", "extended")


def _make(kind, **kw):
    if kind in PR2_KINDS:
        kw.setdefault("max_attempts", 1)
        kit = build_pr2(kind, **kw)
        return kit.question, kit.half
    return _simple(kind, **kw)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ALL_KINDS)
def test_wrong_locked_quiz_check_renders_without_a_list(client, kind):
    # Spec §8 PR 3 + §2.1: every type renders a wrong locked quiz Check, and no
    # _reveal_* markup except extended response's keyword block -- in the quiz and
    # on the results page.
    user = make_login(client, f"stu_{kind}")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q, wrong = _make(kind)
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, wrong, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "data-quiz-locked" in body
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    page = client.get(reverse("courses:quiz_unit", kwargs=kw)).content.decode()
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    results = client.get(reverse("courses:quiz_results", kwargs=kw))
    assert results.status_code == 200
    for html in (body, page, results.content.decode()):
        assert _LIST.findall(html) == []
    if kind == "extended":
        assert "question__reveal-keywords" in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ALL_KINDS)
def test_wrong_lesson_check_renders(client, kind):
    student = make_student(client, f"ls_{kind}")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    q, wrong = _make(kind, max_attempts=None)
    el = add_element(unit, q)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    fetched = client.post(url, wrong, HTTP_X_REQUESTED_WITH="fetch")
    nojs = client.post(url, wrong)
    assert fetched.status_code == 200 and nojs.status_code == 200
    for html in (fetched.content.decode(), nojs.content.decode()):
        assert _LIST.findall(html) == []
        assert 'name="reveal"' not in html  # D11
