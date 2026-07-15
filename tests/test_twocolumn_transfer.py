import pytest

from courses.transfer.export import SERIALIZERS
from courses.transfer.export import walk_unit_joins
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.payloads import validate_nesting
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit


def test_two_column_registered_in_all_registries():
    assert "two_column" in SERIALIZERS
    assert "two_column" in VALIDATORS
    assert "two_column" in BUILDERS


def test_validator_enforces_bounds_and_id_shape():
    good = {"columns": [{"id": "c000001"}, {"id": "c000002"}]}
    VALIDATORS["two_column"](good, "e1", set())  # no raise
    for bad in (
        {"columns": [{"id": "c000001"}]},  # < 2
        {"columns": [{"id": f"c00000{n}"} for n in range(5)]},  # > 4
        {"columns": [{"id": "BAD"}, {"id": "c000002"}]},  # id shape
    ):
        with pytest.raises(TransferError):
            VALIDATORS["two_column"](bad, "e1", set())


def test_validate_nesting_accepts_two_column_parent():
    elements = [
        {
            "id": "p",
            "type": "two_column",
            "parent": None,
            "tab": "",
            "data": {"columns": [{"id": "c000001"}, {"id": "c000002"}]},
        },
        {
            "id": "k",
            "type": "text",
            "parent": "p",
            "tab": "c000001",
            "data": {"body": "hi"},
        },
    ]
    validate_nesting(elements)  # no raise


def test_validate_nesting_rejects_unknown_column():
    elements = [
        {
            "id": "p",
            "type": "two_column",
            "parent": None,
            "tab": "",
            "data": {"columns": [{"id": "c000001"}, {"id": "c000002"}]},
        },
        {
            "id": "k",
            "type": "text",
            "parent": "p",
            "tab": "cffffff",
            "data": {"body": "hi"},
        },
    ]
    with pytest.raises(TransferError):
        validate_nesting(elements)


@pytest.mark.django_db
def test_export_walk_yields_two_column_children():
    from courses.models import Element
    from courses.models import TextElement
    from courses.models import TwoColumnElement

    course, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    Element.objects.create(
        unit=unit,
        parent=join,
        tab_id=cid,
        content_object=TextElement.objects.create(body="K"),
    )
    joins_by_unit = {unit.pk: [join]}
    yielded = list(walk_unit_joins(unit.pk, joins_by_unit))
    # parent + child both yielded, child carries the column id
    assert any(p is join and t == cid for (_, p, t) in yielded)
