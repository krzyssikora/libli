"""The lock rule is ONE rule, and both quiz answer paths must apply it identically.

`quiz_answer` has two branches that each decide whether a question locks after an
attempt: the persisted branch (enrolled student, `courses/views.py`) and the
ephemeral branch (non-enrolled previewer, `courses/quiz.py`). They were introduced
as independent implementations of the same rule:

    locked iff correct, or (max_attempts is not None and attempt >= max_attempts)
    [N]/[R] always lock on first submit

Each side's own tests pin only its own side, so a one-sided change goes green --
exactly the twin-drift failure mode issue #169 exists for. This module is the
guard: it drives BOTH endpoints through the same matrix and requires the lock
outcome to agree. It is behavioural on purpose -- a source-level check could be
satisfied by inlining a divergent rule at one call site.
"""

import pytest

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionResponse
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

LOCKED_SENTINEL = b"data-quiz-locked"


def _question(unit, *, marking_mode, max_attempts):
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?",
        accepted="Paris",
        marking_mode=marking_mode,
        max_attempts=max_attempts,
    )
    return add_element(unit, q)


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _persisted_locked(client, *, marking_mode, max_attempts, answer, attempts):
    """Drive the ENROLLED path `attempts` times; return whether it ended locked."""
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    el = _question(unit, marking_mode=marking_mode, max_attempts=max_attempts)
    resp = None
    for _ in range(attempts):
        resp = client.post(
            _url(unit, el), {"answer": answer}, HTTP_X_REQUESTED_WITH="fetch"
        )
        assert resp.status_code == 200, resp.status_code
    return LOCKED_SENTINEL in resp.content


def _ephemeral_locked(client, *, marking_mode, max_attempts, answer, attempts):
    """Drive the PREVIEWER path at attempt=`attempts`; return whether it locked.

    The previewer branch is stateless, so the attempt number is supplied rather
    than accumulated -- that is the whole design, not a shortcut here.
    """
    user = make_login(client, "prev")
    user.is_staff = True  # access without enrollment; see courses/access.py
    user.save()
    unit = make_quiz_unit()
    el = _question(unit, marking_mode=marking_mode, max_attempts=max_attempts)
    resp = client.post(
        _url(unit, el),
        {"answer": answer, "attempt": str(attempts)},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200, resp.status_code
    return LOCKED_SENTINEL in resp.content


# (marking_mode, max_attempts, answer, attempts, expected_locked)
CASES = [
    ("A", 3, "London", 1, False),  # wrong, attempts remain -> withhold
    ("A", 3, "London", 2, False),  # wrong, still one left
    ("A", 3, "London", 3, True),  # wrong on the last attempt -> lock + reveal
    ("A", 3, "Paris", 1, True),  # correct -> locks immediately
    ("A", 1, "London", 1, True),  # model default: first wrong IS the last
    ("A", None, "London", 5, False),  # null max_attempts = UNLIMITED, never locks
    ("N", 3, "London", 1, True),  # [N] single submission
    ("R", 3, "London", 1, True),  # [R] single submission
]


@pytest.mark.django_db
@pytest.mark.parametrize("mode,max_attempts,answer,attempts,expected", CASES)
def test_persisted_path_lock_rule(
    client, mode, max_attempts, answer, attempts, expected
):
    assert (
        _persisted_locked(
            client,
            marking_mode=mode,
            max_attempts=max_attempts,
            answer=answer,
            attempts=attempts,
        )
        is expected
    )


@pytest.mark.django_db
@pytest.mark.parametrize("mode,max_attempts,answer,attempts,expected", CASES)
def test_ephemeral_path_lock_rule(
    client, mode, max_attempts, answer, attempts, expected
):
    assert (
        _ephemeral_locked(
            client,
            marking_mode=mode,
            max_attempts=max_attempts,
            answer=answer,
            attempts=attempts,
        )
        is expected
    )


@pytest.mark.django_db
@pytest.mark.parametrize("mode,max_attempts,answer,attempts,expected", CASES)
def test_both_paths_agree(client, mode, max_attempts, answer, attempts, expected):
    """The anti-drift guard: change one side's rule and this goes red."""
    persisted = _persisted_locked(
        client,
        marking_mode=mode,
        max_attempts=max_attempts,
        answer=answer,
        attempts=attempts,
    )
    ephemeral = _ephemeral_locked(
        client,
        marking_mode=mode,
        max_attempts=max_attempts,
        answer=answer,
        attempts=attempts,
    )
    assert persisted == ephemeral, (
        f"lock rule diverged for mode={mode} max_attempts={max_attempts} "
        f"attempts={attempts}: persisted={persisted} ephemeral={ephemeral}"
    )


def _reveal_setup(client, *, enrolled, kind, marking_mode="A", attempts=1):
    user = make_login(client, "rv_" + ("e" if enrolled else "p"))
    if not enrolled:
        user.is_staff = True
        user.save()
    unit = make_quiz_unit()
    if enrolled:
        EnrollmentFactory(student=user, course=unit.course)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(
            stem=parse("{{11}}")[0], marking_mode=marking_mode, max_attempts=3
        )
        Blank.objects.create(question=q, order=0, accepted="11")
        data = {"blank": ["5"]}
    else:
        q = ChoiceQuestionElement.objects.create(
            stem="?", marking_mode=marking_mode, max_attempts=3
        )
        Choice.objects.create(question=q, text="A", is_correct=True)
        wrong = Choice.objects.create(question=q, text="B", is_correct=False)
        data = {"choice": [str(wrong.pk)]}  # a real (wrong) attempt
    el = add_element(unit, q)
    for n in range(attempts):
        client.post(
            _url(unit, el),
            {**data, "attempt": str(n + 1)},
            HTTP_X_REQUESTED_WITH="fetch",
        )
    return unit, el, data


def _reveal(client, unit, el, data, made):
    return client.post(
        _url(unit, el),
        {**data, "reveal": "1", "attempt": str(made)},
        HTTP_X_REQUESTED_WITH="fetch",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kind,marking_mode,accepted",
    [
        ("fillblank", "A", True),
        ("fillblank", "N", False),
        # PR 3 (spec 2026-09-25 §8): replaces the ("choice", "A", False)
        # "unconverted type" case -- choice is now converted, so it becomes
        # eligible on both paths.
        ("choice", "A", True),
        ("choice", "N", False),  # choice keeps an ineligible leg (N/R never reveal)
    ],
)
def test_reveal_rule_parity(client, kind, marking_mode, accepted):
    unit, el, data = _reveal_setup(
        client, enrolled=True, kind=kind, marking_mode=marking_mode
    )
    enrolled = _reveal(client, unit, el, data, 1)
    client.logout()
    unit2, el2, data2 = _reveal_setup(
        client, enrolled=False, kind=kind, marking_mode=marking_mode
    )
    ephemeral = _reveal(client, unit2, el2, data2, 1)
    if accepted:
        assert enrolled.status_code == 200 and b"answer shown" in enrolled.content
        assert b"answer shown" in ephemeral.content
    else:
        # Enrolled: refused (409, or the locked response for N which locked on its
        # first submit). Ephemeral: the reveal is ignored -> a normal Check.
        assert enrolled.status_code == 409
        assert b"answer shown" not in ephemeral.content


@pytest.mark.django_db
def test_reveal_parity_no_attempt_yet(client):
    unit, el, data = _reveal_setup(client, enrolled=True, kind="fillblank", attempts=0)
    assert _reveal(client, unit, el, data, 0).status_code == 409
    assert (
        QuestionResponse.objects.filter(element=el, revealed_at__isnull=False).count()
        == 0
    )
    # The EPHEMERAL twin is deliberately not asserted: spec §3.3 floors the client
    # attempt count at 1 there, so its check is advisory (a pre-Check reveal passes).
