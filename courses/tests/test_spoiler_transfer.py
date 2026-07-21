import pytest

from courses.builder import NESTABLE_TYPE_KEYS
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError


def test_registered_in_all_three_and_nestable():
    assert "spoiler" in SERIALIZERS
    assert "spoiler" in VALIDATORS
    assert "spoiler" in BUILDERS
    # transfer key == form key, so no alias needed for resolve_scope
    assert "spoiler" in NESTABLE_TYPE_KEYS
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip():
    from courses.models import SpoilerElement

    model, ser = SERIALIZERS["spoiler"]
    assert model is SpoilerElement
    el = SpoilerElement.objects.create(label="Hint", body="<p>x</p>")
    payload = ser(el, {})
    assert payload == {"label": "Hint", "body": "<p>x</p>"}
    built, media = BUILDERS["spoiler"](payload, {})
    assert built.label == "Hint"
    assert "<p>x</p>" in built.body
    assert media == ()


def test_validator_is_strict():
    val = VALIDATORS["spoiler"]
    assert val({"label": "a", "body": "<p>x</p>"}, "e1", {}) == set()
    with pytest.raises(TransferError):
        val({"body": "<p>x</p>"}, "e1", {})
    with pytest.raises(TransferError):
        val({"label": "a", "body": "x", "extra": 1}, "e1", {})
    with pytest.raises(TransferError):
        val({"label": "a", "body": 5}, "e1", {})
    with pytest.raises(TransferError):
        val({"label": "x" * 121, "body": "x"}, "e1", {})


@pytest.mark.django_db
def test_walk_unit_joins_expands_spoiler_children():
    from courses.models import Element, SpoilerElement, TextElement
    from courses.transfer.export import walk_unit_joins
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="L")
    join = Element.objects.create(unit=unit, content_object=sp)
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>c</p>"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    joins_by_unit = {unit.pk: [join]}  # only top-level joins
    yielded = list(walk_unit_joins(unit.pk, joins_by_unit))
    assert (join, None, "") in yielded
    assert (child, join, SpoilerElement.SLOT_ID) in yielded


def test_validate_nesting_accepts_spoiler_slot_and_rejects_depth2():
    from courses.transfer.payloads import validate_nesting
    from courses.transfer.schema import TransferError
    from courses.models import SpoilerElement

    slot = SpoilerElement.SLOT_ID
    ok = [
        {
            "id": "sp",
            "type": "spoiler",
            "parent": None,
            "tab": None,
            "data": {"label": "L", "body": ""},
        },
        {
            "id": "c1",
            "type": "text",
            "parent": "sp",
            "tab": slot,
            "data": {"body": "<p>x</p>"},
        },
    ]
    validate_nesting(ok)  # must not raise

    bad_slot = [
        {
            "id": "sp",
            "type": "spoiler",
            "parent": None,
            "tab": None,
            "data": {"label": "", "body": ""},
        },
        {
            "id": "c1",
            "type": "text",
            "parent": "sp",
            "tab": "wrong",
            "data": {"body": "x"},
        },
    ]
    with pytest.raises(TransferError):
        validate_nesting(bad_slot)

    depth2 = [
        {
            "id": "t",
            "type": "tabs",
            "parent": None,
            "tab": None,
            "data": {"tabs": [{"id": "t000001", "label": "T"}]},
        },
        {
            "id": "sp",
            "type": "spoiler",
            "parent": "t",
            "tab": "t000001",
            "data": {"label": "", "body": ""},
        },
        {
            "id": "c1",
            "type": "text",
            "parent": "sp",
            "tab": slot,
            "data": {"body": "x"},
        },
    ]
    with pytest.raises(TransferError):  # depth-2 child still rejected
        validate_nesting(depth2)


def test_validate_nesting_rejects_container_spoiler_child():
    # reveal_gate is now an allowed spoiler child (Task 1 widening); a native
    # container (tabs) stays rejected -- retargeted from the old reveal_gate case.
    from courses.transfer.payloads import validate_nesting
    from courses.transfer.schema import TransferError
    from courses.models import SpoilerElement

    slot = SpoilerElement.SLOT_ID
    bad = [
        {
            "id": "sp",
            "type": "spoiler",
            "parent": None,
            "tab": None,
            "data": {"label": "L", "body": ""},
        },
        {"id": "c1", "type": "tabs", "parent": "sp", "tab": slot, "data": {"tabs": []}},
    ]
    with pytest.raises(TransferError):
        validate_nesting(bad)


@pytest.mark.django_db
def test_round_trip_interactive_spoiler_children():
    # A spoiler containing a switch_gate child and a fill_blank child survives an
    # export (write_archive, unit-rooted subtree) -> import (import_subtree) round
    # trip into a fresh course, and validate_nesting still rejects a tabs-in-spoiler
    # archive (belt-and-suspenders with the test above).
    import io

    from courses.fillblank import SENTINEL
    from courses.models import Blank
    from courses.models import Course
    from courses.models import Element
    from courses.models import FillBlankQuestionElement
    from courses.models import SpoilerElement
    from courses.models import SwitchGateElement
    from courses.transfer.export import write_archive
    from courses.transfer.importer import import_subtree
    from courses.transfer.importer import open_archive
    from courses.transfer.importer import validate_archive_document
    from tests.factories import UserFactory
    from tests.factories import make_course_with_unit

    source, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="Hint")
    join = Element.objects.create(unit=unit, content_object=sp)
    Element.objects.create(
        unit=unit,
        content_object=SwitchGateElement.objects.create(
            stem=f"s {SENTINEL}0{SENTINEL}", options=["a", "b"], answer=0
        ),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    fb = FillBlankQuestionElement.objects.create(stem=f"x = {SENTINEL}0{SENTINEL}")
    Blank.objects.create(question=fb, accepted="0", order=0)
    Element.objects.create(
        unit=unit,
        content_object=fb,
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
        order=1,
    )

    buf = io.BytesIO()
    write_archive(source, unit, buf)
    buf.seek(0)

    target = Course.objects.create(title="Target", slug="target")
    importer = UserFactory()
    with open_archive(buf, expected_kind="subtree") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="subtree", target_course=target
        )
        grafted = import_subtree(zf, mani, doc, media, target, None, importer)

    new_sp_join = Element.objects.filter(
        unit_id=grafted.pk, content_type__model="spoilerelement"
    ).first()
    assert new_sp_join is not None
    new_sp = new_sp_join.content_object
    kids = new_sp.resolved_children()
    kinds = sorted(type(k.content_object).__name__ for k in kids)
    assert kinds == ["FillBlankQuestionElement", "SwitchGateElement"]
