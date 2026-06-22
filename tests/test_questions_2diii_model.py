# tests/test_questions_2diii_model.py
import pytest
from django.db.models import QuerySet
from django.http import QueryDict

from courses.models import EXTENDED_RESPONSE_MAX_CHARS
from courses.models import QuestionResponse
from tests.factories import ExtendedResponseQuestionElementFactory

pytestmark = pytest.mark.django_db


def test_mark_full_credit():
    q = ExtendedResponseQuestionElementFactory(
        required_keywords="alpha\nbeta", forbidden_keywords=""
    )
    res = q.mark("alpha and beta")
    assert res.correct is True
    assert res.fraction == 1.0
    assert res.reveal[0]["keyword"] == "alpha"


def test_mark_partial_with_forbidden():
    q = ExtendedResponseQuestionElementFactory(
        required_keywords="alpha", forbidden_keywords="bad"
    )
    res = q.mark("alpha bad")
    assert res.fraction == 0.0
    assert res.correct is False


def test_build_answer_caps_length():
    q = ExtendedResponseQuestionElementFactory()
    post = QueryDict(mutable=True)
    post["answer"] = "x" * (EXTENDED_RESPONSE_MAX_CHARS + 50)
    assert len(q.build_answer(post)) == EXTENDED_RESPONSE_MAX_CHARS


def test_feedback_context_marks_answered():
    q = ExtendedResponseQuestionElementFactory(required_keywords="alpha")
    ctx = q.feedback_context(q.mark("alpha"))
    assert ctx["answered"] is True
    assert ctx["reveal_template"] == "courses/elements/_reveal_extendedresponse.html"


def test_seam_columns_default_null():
    f = QuestionResponse._meta.get_field("reviewed_at")
    assert f.null is True
    f2 = QuestionResponse._meta.get_field("reviewed_by")
    assert f2.null is True


def test_elements_generic_relation_present():
    q = ExtendedResponseQuestionElementFactory()
    assert isinstance(q.elements.all(), QuerySet)
