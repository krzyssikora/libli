"""The archive-side half of the lesson-only rule (spec §6.3 authority 4).

`validate_nesting` gains `unit_types=None` and refuses a nestable QUESTION whose
own unit is a quiz. Without the tests below, deleting that clause outright would
leave the rest of this task green -- every other transfer test passes no
`unit_types` at all and so never reaches it.

Two deliberate design points these tests pin:

* the clause sits AFTER the existing `NESTABLE_TYPE_KEYS` clause, so "not nestable
  at all" still wins over "not nestable HERE";
* the lookup is `el["unit"]` -- the CHILD's own unit. `validate_nesting` never
  checks that a child and its parent share a unit, so a crafted archive can make
  the two disagree, and the child's unit is the one the row is actually created in.

The first four tests take NO database on purpose: `validate_nesting` is pure
dict-walking, and `unit_types` maps archive-internal node ids to the raw strings
`schema.py` already validated against ("lesson"/"quiz") -- an archive unit_type
never becomes a `ContentNode`.
"""

import io

import pytest

from courses.models import CalloutElement
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.transfer.export import write_archive
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.payloads import validate_nesting
from courses.transfer.schema import TransferError
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login


def _tabs_el(eid="e1", unit="n1"):
    """Copied from tests/test_tabs_transfer.py:113 and given a "unit" key.

    Those helpers emit no `"unit"`, because every caller there passes no
    `unit_types` and the new clause short-circuits on `unit_types is not None`
    before ever reading it. A straight paste raises `KeyError: 'unit'` the moment
    `unit_types` is non-None.
    """
    return {
        "id": eid,
        "type": "tabs",
        "unit": unit,
        "data": {"tabs": [{"id": "taaaaaa", "label": "A"}]},
        "parent": None,
        "tab": "",
    }


def _child(eid="e2", parent="e1", tab="taaaaaa", type_="choice", unit="n1"):
    return {
        "id": eid,
        "type": type_,
        "unit": unit,
        "data": {},
        "parent": parent,
        "tab": tab,
    }


def test_a_question_nested_in_a_quiz_unit_is_rejected():
    with pytest.raises(TransferError):
        validate_nesting([_tabs_el(), _child()], unit_types={"n1": "quiz"})


def test_the_same_nesting_in_a_lesson_unit_is_accepted():
    validate_nesting([_tabs_el(), _child()], unit_types={"n1": "lesson"})


def test_the_childs_own_unit_governs_not_the_parents():
    """el["unit"], deliberately -- validate_nesting never checks that a child and
    its parent share a unit, so a crafted archive can make them disagree."""
    els = [_tabs_el(unit="n_lesson"), _child(unit="n_quiz")]
    with pytest.raises(TransferError):
        validate_nesting(els, unit_types={"n_lesson": "lesson", "n_quiz": "quiz"})


def test_a_non_nestable_type_reports_the_existing_message_first():
    """Ordering: "not nestable at all" wins over "not nestable HERE".

    validate_nesting has no reason keys -- every clause raises through _err() with
    a translated message -- so this matches on the EXISTING msgid, not on a
    paste_allowed key.
    """
    with pytest.raises(TransferError, match="may not be nested"):
        validate_nesting(
            [_tabs_el(), _child(type_="drag_fill_blank")], unit_types={"n1": "quiz"}
        )


def _round_trip(client, course):
    """Export -> validate -> import, modelled on tests/test_tabs_transfer.py:265.

    Goes through `validate_archive_document`, which is what calls
    `validate_document` -> `validate_nesting`: dropping "choice" from
    NESTABLE_TYPE_KEYS makes this step raise, not the import step.
    """
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    owner = make_login(client, "nested-question-importer")
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="course", target_course=None
        )
        return import_course(zf, mani, doc, media, owner)


@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_a_choice_nested_in_a_lesson_callout_survives_export_and_import(client):
    """`choice` is the only newly nestable type with CHILD ROWS of its own, and
    both duplicate_element and the paste flow run through these serializers -- so
    duplicating a callout is the first thing an author does after nesting one.
    """
    course, unit = make_course_with_unit()
    callout = add_element(unit, CalloutElement.objects.create(kind="example"))
    question = ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False)
    Choice.objects.create(
        question=question, text="right", is_correct=True, feedback="yes"
    )
    Choice.objects.create(
        question=question, text="wrong", is_correct=False, feedback="no"
    )
    Element.objects.create(
        unit=unit,
        content_object=question,
        parent=callout,
        tab_id=CalloutElement.SLOT_ID,
    )

    _imported_course = _round_trip(client, course)

    imported_q = ChoiceQuestionElement.objects.exclude(pk=question.pk).get()
    imported_join = Element.objects.get(
        content_type__model="choicequestionelement", object_id=imported_q.pk
    )
    imported_parent = imported_join.parent
    assert imported_parent is not None, "the nested choice lost its parent"
    # The concrete type of the PARENT too: a container that came back as something
    # else would still satisfy a bare `parent is not None`.
    assert isinstance(imported_parent.content_object, CalloutElement)
    assert imported_parent.pk != callout.pk  # the COPY, not the original row
    assert imported_join.tab_id == CalloutElement.SLOT_ID
    assert imported_q.stem == "Pick one."
    assert imported_q.multiple is False
    assert [
        (c.text, c.is_correct, c.feedback)
        for c in imported_q.choices.order_by("order", "pk")
    ] == [("right", True, "yes"), ("wrong", False, "no")]
