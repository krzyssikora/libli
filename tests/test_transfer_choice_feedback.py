import io

import pytest

from courses.transfer.export import _ser_choice
from courses.transfer.payloads import _val_choice
from courses.transfer.schema import TransferError


@pytest.mark.django_db
def test_export_includes_feedback():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False, feedback="nope")

    data = _ser_choice(q, {})
    assert data["choices"] == [
        {"text": "A", "is_correct": True, "feedback": ""},
        {"text": "B", "is_correct": False, "feedback": "nope"},
    ]


def _choice_payload(choices):
    return {
        "stem": "q",
        "explanation": "",
        "marking_mode": "A",
        "max_attempts": 1,
        "max_marks": "1.00",
        "multiple": False,
        "choices": choices,
    }


def test_val_choice_accepts_legacy_without_feedback():
    # v<=3 archives have no feedback key; the setdefault shim adds "" so exact-keys ok.
    # NOTE: >=2 choices with exactly one correct — _val_choice runs `len(choices) < 2`
    # and correct-count guards BEFORE the per-choice shim loop, so a single-choice
    # payload would raise there and never exercise the shim.
    data = _choice_payload(
        [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}]
    )
    _val_choice(data, "el1", {})  # must not raise
    assert data["choices"][0]["feedback"] == ""
    assert data["choices"][1]["feedback"] == ""


def test_val_choice_rejects_overlong_feedback():
    # >=2 valid choices so the raise originates from the feedback length check, NOT the
    # `len(choices) < 2` guard (which would make the test pass for the wrong reason).
    data = _choice_payload(
        [
            {"text": "A", "is_correct": True},
            {"text": "B", "is_correct": False, "feedback": "x" * 501},
        ]
    )
    with pytest.raises(TransferError):
        _val_choice(data, "el1", {})


@pytest.mark.django_db
def test_choice_feedback_survives_round_trip():
    # Exercises _build_choice on import: a distractor's feedback must survive
    # export -> archive -> import.
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import Element
    from courses.transfer.export import write_archive
    from tests.factories import UserFactory
    from tests.test_transfer_import import _import_zip

    course = Course.objects.create(title="RT", slug="rt-choice", language="en")
    unit = ContentNode.objects.create(
        course=course, kind="unit", title="U", unit_type="quiz"
    )
    q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False, feedback="keep me")
    Element.objects.create(unit=unit, content_object=q)

    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)

    imported = _import_zip(buf, UserFactory())
    imported_choice = Choice.objects.filter(
        question__elements__unit__course=imported, text="B"
    ).get()
    assert imported_choice.feedback == "keep me"
