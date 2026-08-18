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
    assert data == {
        "kind": "warning",
        "heading": "Careful",
        "body": "<p>hi</p>",
        "numbered": True,
    }
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


@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_the_serializer_emits_numbered():
    el = CalloutElement.objects.create(
        kind="warning", heading="Careful", numbered=False, body="<p>hi</p>"
    )
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):
            return None

    assert ser(el, _Ids())["numbered"] is False


def test_a_pre_v13_payload_imports_with_the_per_kind_default():
    """Legacy archives have no `numbered` key. The validator seeds it from the kind,
    matching the backfill migration exactly, so an archive exported before this
    feature and a database migrated by it agree.

    Mutant: drop the setdefault -> _exact_keys raises TransferError.
    """
    for kind, expected in (("example", True), ("note", False), ("tip", False)):
        data = {"kind": kind, "heading": "", "body": "<p>x</p>"}
        VALIDATORS["callout"](data, "e1", set())
        assert data["numbered"] is expected


def test_a_payload_with_no_kind_still_fails_cleanly():
    """The setdefault runs BEFORE _exact_keys, so it may see an absent or non-string
    `kind`. It must be total: a missing kind must still produce the validator's
    TransferError, never a KeyError; a list kind must not raise TypeError:
    unhashable.
    """
    from courses.transfer.schema import TransferError

    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"heading": "", "body": "<p>x</p>"}, "e1", set())
    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"kind": [], "heading": "", "body": ""}, "e1", set())


def test_numbered_must_be_a_bool():
    from courses.transfer.schema import TransferError

    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "example", "heading": "", "body": "", "numbered": "yes"},
            "e1",
            set(),
        )


@pytest.mark.django_db  # _clean_save writes to the DB
def test_the_builder_round_trips_numbered_false():
    """Mutant: drop `numbered=` from _build_callout -> comes back True."""
    data = {"kind": "example", "heading": "", "body": "<p>x</p>", "numbered": False}
    VALIDATORS["callout"](data, "e1", set())
    concrete, _media = BUILDERS["callout"](data, {})
    assert concrete.numbered is False


@pytest.mark.django_db  # this module marks per-test; there is NO module pytestmark
def test_duplicating_an_unnumbered_callout_keeps_it_unnumbered():
    """Duplicate and paste round-trip through build_element_export -> graft_elements,
    which runs NO validator. Mutant: drop `numbered=` from _build_callout -> the copy
    comes back numbered. This is the consequence a user hits first."""
    from courses import builder
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="example", numbered=False, body="<p>x</p>")
    join = add_element(unit, el)
    unit.refresh_from_db()

    _unit, new_join = builder.duplicate_element(
        course, join.pk, unit.updated.isoformat()
    )
    assert new_join.content_object.numbered is False
