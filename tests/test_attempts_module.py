"""courses.attempts: one home for parsing, wording, counting and resetting."""

import pytest
from django.core.exceptions import ValidationError

from courses import attempts as A
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_quiz_unit

ZERO = "zero!"


def _parse(mode, raw):
    return A.parse_attempts(
        mode, raw, allowed_modes=A.QUESTION_MODES, zero_message=ZERO
    )


@pytest.mark.parametrize(
    "mode,raw,want",
    [
        ("inherit", "", ("inherit", None)),
        ("unlimited", "-1", ("unlimited", None)),  # hidden junk is harmless
        ("inherit", "abc", ("inherit", None)),
        ("unlimited", "99999", ("unlimited", None)),
        ("limited", "3", ("limited", 3)),
        ("limited", " 7 ", ("limited", 7)),
        ("limited", "32767", ("limited", 32767)),
    ],
)
def test_parse_accepts(mode, raw, want):
    assert _parse(mode, raw) == want


@pytest.mark.parametrize(
    "mode,raw,code,message",
    [
        ("", "3", "attempts_mode", A.MSG_CHOOSE),
        ("bogus", "3", "attempts_mode", A.MSG_CHOOSE),
        (None, "3", "attempts_mode", A.MSG_CHOOSE),
        ("limited", "", "attempts_limit", A.MSG_ENTER),
        ("limited", "  ", "attempts_limit", A.MSG_ENTER),
        ("limited", "abc", "attempts_limit", A.MSG_ENTER),
        ("limited", "2.5", "attempts_limit", A.MSG_ENTER),
        ("limited", "-1", "attempts_limit", A.MSG_ENTER),
        ("limited", "0", "attempts_limit", ZERO),
        ("limited", "00", "attempts_limit", ZERO),
        ("limited", "32768", "attempts_limit", A.MSG_CAP),
        ("limited", "9" * 50, "attempts_limit", A.MSG_CAP),
    ],
)
def test_parse_rejects(mode, raw, code, message):
    with pytest.raises(ValidationError) as exc:
        _parse(mode, raw)
    assert exc.value.code == code
    assert exc.value.messages == [str(message)]


def test_course_modes_reject_inherit():
    with pytest.raises(ValidationError):
        A.parse_attempts("inherit", "", allowed_modes=A.COURSE_MODES, zero_message=ZERO)


def test_inherit_labels():
    assert A.inherit_label("quiz", 3) == "Same as quiz (currently: 3)"
    assert A.inherit_label("course", None) == "Same as course (currently: unlimited)"


@pytest.mark.parametrize(
    "q,n,want",
    [
        (0, 3, "Settings saved. 3 questions now use the course setting."),
        (1, 0, "Settings saved. 1 quiz now uses the course setting."),
        (
            2,
            41,
            "Settings saved. 2 quizzes and 41 questions now use the course setting.",
        ),
        (0, 0, "Settings saved."),
    ],
)
def test_course_reset_message(q, n, want):
    assert A.course_reset_message(q, n) == want


def test_quiz_messages_and_labels():
    assert A.quiz_reset_message(0) == "Settings saved."
    assert (
        A.quiz_reset_message(1)
        == "Settings saved. 1 question now uses the quiz setting."
    )
    assert A.quiz_keep_label(5) == "Keep questions' own settings (5 questions)"
    assert (
        A.course_keep_label(0, 41)
        == "Keep specific settings (41 questions have their own)"
    )
    assert A.course_keep_label(1, 0) == "Keep specific settings (1 quiz has its own)"


def _q(unit, *, marking="A", own=None):
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", marking_mode=marking, **(own or {})
    )
    add_element(unit, q)
    return q


@pytest.mark.django_db
def test_counts_only_auto_overrides():
    unit = make_quiz_unit()
    _q(unit, own=attempts(3))
    _q(unit, own=attempts(None))
    _q(unit, marking="N", own=attempts(2))  # [N]: not counted
    _q(unit)  # inherit: not counted
    c = ChoiceQuestionElement.objects.create(stem="?", **attempts(4))
    add_element(unit, c)  # a second table
    assert A.count_question_overrides([unit.pk]) == 3


@pytest.mark.django_db
def test_quiz_reset_scope_and_count():
    unit = make_quiz_unit()
    other = make_quiz_unit(course=unit.course)
    a = _q(unit, own=attempts(3))
    n = _q(unit, marking="N", own=attempts(2))
    keep = _q(other, own=attempts(5))
    assert A.reset_quiz_overrides(unit) == 1  # [A] count, before the update
    for q in (a, n):
        q.refresh_from_db()
        assert (q.attempts_mode, q.attempts_limit) == ("inherit", None)
    keep.refresh_from_db()
    assert keep.attempts_limit == 5


@pytest.mark.django_db
def test_course_reset_scope_counts_and_bumps():
    course = CourseFactory()
    qa = make_quiz_unit(course=course, attempts_mode="limited", attempts_limit=2)
    qb = make_quiz_unit(course=course)  # inherit; only its questions override
    qc = make_quiz_unit(course=course)  # nothing to reset
    lesson = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        attempts_mode="limited",
        attempts_limit=5,
    )
    in_a = _q(qa, own=attempts(3))
    in_b1 = _q(qb, own=attempts(4))
    in_b2 = _q(qb, own=attempts(None))
    in_b_n = _q(qb, marking="N", own=attempts(2))
    in_lesson = _q(lesson, own=attempts(7))
    before = {u.pk: u.updated for u in (qa, qb, qc, lesson)}

    assert A.course_override_counts(course) == (1, 3)
    assert A.reset_course_overrides(course) == (1, 3)

    for q in (in_a, in_b1, in_b2, in_b_n):
        q.refresh_from_db()
        assert q.attempts_mode == "inherit"
    in_lesson.refresh_from_db()
    assert in_lesson.attempts_limit == 7  # P9
    after = {u.pk: u.updated for u in ContentNode.objects.filter(pk__in=before)}
    assert after[qa.pk] > before[qa.pk]
    assert after[qb.pk] > before[qb.pk]  # question-only reset: explicit bump
    assert after[qc.pk] == before[qc.pk]
    assert after[lesson.pk] == before[lesson.pk]
    lesson.refresh_from_db()
    assert lesson.attempts_limit == 5
