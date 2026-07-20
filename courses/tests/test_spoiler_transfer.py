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
        {"id": "sp", "type": "spoiler", "parent": None, "tab": None, "data": {"label": "L", "body": ""}},
        {"id": "c1", "type": "text", "parent": "sp", "tab": slot, "data": {"body": "<p>x</p>"}},
    ]
    validate_nesting(ok)  # must not raise

    bad_slot = [
        {"id": "sp", "type": "spoiler", "parent": None, "tab": None, "data": {"label": "", "body": ""}},
        {"id": "c1", "type": "text", "parent": "sp", "tab": "wrong", "data": {"body": "x"}},
    ]
    with pytest.raises(TransferError):
        validate_nesting(bad_slot)

    depth2 = [
        {"id": "t", "type": "tabs", "parent": None, "tab": None, "data": {"tabs": [{"id": "t000001", "label": "T"}]}},
        {"id": "sp", "type": "spoiler", "parent": "t", "tab": "t000001", "data": {"label": "", "body": ""}},
        {"id": "c1", "type": "text", "parent": "sp", "tab": slot, "data": {"body": "x"}},
    ]
    with pytest.raises(TransferError):  # depth-2 child still rejected
        validate_nesting(depth2)
