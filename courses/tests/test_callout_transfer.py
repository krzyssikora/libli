import pytest

from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import CalloutElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError


def test_callout_registered_in_all_three_registries():
    assert "callout" in SERIALIZERS
    assert "callout" in VALIDATORS
    assert "callout" in BUILDERS


def test_callout_is_nestable_and_invariant_holds():
    # transfer key == form key, so no alias needed
    assert "callout" in NESTABLE_TYPE_KEYS
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip_preserves_fields():
    el = CalloutElement.objects.create(
        kind="warning", heading="Careful", body="<p>hi</p>"
    )
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):  # unused by callout
            return None

    data = ser(el, _Ids())
    assert data == {"kind": "warning", "heading": "Careful", "body": "<p>hi</p>"}
    # validator accepts it
    VALIDATORS["callout"](data, "e1", set())
    # builder reconstructs
    rebuilt, _refs = BUILDERS["callout"](data, {})
    assert rebuilt.kind == "warning"
    assert rebuilt.heading == "Careful"
    assert "hi" in rebuilt.body


def test_validator_rejects_bad_kind():
    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"kind": "bogus", "heading": "", "body": ""}, "e1", set())


def test_validator_rejects_missing_and_extra_keys():
    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"kind": "note", "body": ""}, "e1", set())  # no heading
    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "note", "heading": "", "body": "", "x": 1}, "e1", set()
        )


def test_validator_rejects_overlong_heading():
    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "note", "heading": "z" * 121, "body": ""}, "e1", set()
        )


def test_import_rejects_a_depth_4_callout_archive():
    """D3a, a DECIDED break: a depth-4 callout was legal before this slice, so an
    archive containing one becomes unimportable. Measured exposure: 0 rows.
    """
    from courses.transfer.payloads import validate_nesting
    from courses.transfer.schema import TransferError

    elements = [
        {"id": "a", "type": "spoiler", "parent": None, "tab": "", "data": {}},
        {"id": "b", "type": "spoiler", "parent": "a", "tab": "only", "data": {}},
        {"id": "c", "type": "spoiler", "parent": "b", "tab": "only", "data": {}},
        {"id": "d", "type": "callout", "parent": "c", "tab": "only", "data": {}},
    ]
    with pytest.raises(TransferError):
        validate_nesting(elements)


@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_export_emits_a_table_inside_a_callout():
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import TableElement
    from courses.transfer import export as _export
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example", body="<p>intro</p>")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "CELL-MARKER"}]]}
        ),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    _manifest, document, _media, _problems = _export.build_export(course)
    # Assert STRUCTURALLY, not on str(document): the child must appear in the element
    # list wired to its parent with tab == the single slot id. (`_ser_table` returns
    # `dict(el.data)` verbatim, so a stringified assertion would also pass with a
    # wrong data key -- see the "cells" vs "rows" trap.)
    # build_export emits a FLAT document: {"nodes", "elements", "media", ...}.
    # There is no "units" key (export.py:766-784).
    elements = document["elements"]
    child = next(e for e in elements if e["type"] == "table")
    parent = next(e for e in elements if e["type"] == "callout")
    assert child["parent"] == parent["id"]
    assert child["tab"] == CalloutElement.SLOT_ID
    assert "CELL-MARKER" in str(child["data"])


@pytest.mark.django_db
def test_duplicate_unit_preserves_a_table_inside_a_callout():
    """Same missing emit() arm; duplicate_unit is the far more common gesture."""
    from courses import builder as _builder
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import TableElement
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "DUP-MARKER"}]]}
        ),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    new_node = _builder.duplicate_unit(course, unit.pk, token=unit.updated.isoformat())
    copied = Element.objects.filter(unit=new_node, parent__isnull=False)
    assert any(
        "DUP-MARKER" in str(getattr(e.content_object, "data", "")) for e in copied
    ), "the callout's child was dropped by the duplicate"


@pytest.mark.django_db
def test_duplicate_element_preserves_a_table_inside_a_callout():
    """Same missing emit() arm, reached through duplicate_element instead of
    duplicate_unit: master's element-clipboard duplicate_element -> _copy_below
    -> build_element_export routes through the very same walk_unit_joins emit()
    ladder this branch adds a callout arm to."""
    from courses import builder as _builder
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import TableElement
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "DUP-MARKER"}]]}
        ),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    _unit, new_join = _builder.duplicate_element(
        course, join.pk, unit.updated.isoformat()
    )
    child = new_join.children.get()
    assert "DUP-MARKER" in str(child.content_object.data), (
        "the callout's child was dropped by the duplicate"
    )


@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_round_trip_preserves_the_task_kind():
    el = CalloutElement.objects.create(kind="task", heading="", body="<p>hi</p>")
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):  # unused by callout
            return None

    data = ser(el, _Ids())
    assert data["kind"] == "task"
    VALIDATORS["callout"](data, "e1", set())
    rebuilt, _refs = BUILDERS["callout"](data, {})
    assert rebuilt.kind == "task"
