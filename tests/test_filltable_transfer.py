"""Fill-in table course export/validate/import: registration + round-trip (Task 8)."""

import pytest

from courses.builder import _NESTABLE_FORM_KEY_ALIASES
from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import FillTableElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.export import MediaIdMap
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError
from tests.factories import make_course
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def test_registered_and_nestable():
    assert "fill_table" in SERIALIZERS
    assert "fill_table" in VALIDATORS
    assert "fill_table" in BUILDERS
    assert "fill_table" in NESTABLE_TYPE_KEYS
    # form key ("filltable") diverges from the transfer key ("fill_table"),
    # so resolve_scope needs the alias to reach NESTABLE_TYPE_KEYS
    assert _NESTABLE_FORM_KEY_ALIASES["filltable"] == "fill_table"
    # invariant guarded by the tabs transfer tests
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


def test_fill_table_is_nestable_via_resolve_scope():
    # Prove nesting is actually allowed through the real resolve_scope() path
    # (form key "filltable"), which exercises the form-key alias.
    from courses import builder
    from courses.models import Element
    from courses.models import TabsElement
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    parent_join, resolved_tab = builder.resolve_scope(
        unit, str(join.pk), tab_id, "filltable"
    )
    assert parent_join == join
    assert resolved_tab == tab_id


def test_round_trip_preserves_cells_and_flags():
    src = FillTableElement(
        data={
            "case_sensitive": True,
            "prompt": "go",
            "cells": [
                [
                    {"kind": "static", "html": "<b>t</b>"},
                    {"kind": "answer", "answer": "4"},
                ]
            ],
        }
    )
    src.save()
    payload = SERIALIZERS["fill_table"][1](src, set())
    VALIDATORS["fill_table"](
        payload, "e1", set()
    )  # validator: (data, elid, media_kinds)
    obj, _children = BUILDERS["fill_table"](payload, {})
    nd = obj.normalize_data(obj.data)
    assert nd["cells"][0][1] == {
        "kind": "answer",
        "answer": "4",
        "halign": "left",
        "valign": "top",
    }
    assert nd["case_sensitive"] is True and nd["prompt"] == "go"


@pytest.mark.parametrize(
    "bad",
    [
        "notadict",
        {"cells": "notalist"},
        {"cells": ["notarow"]},
        {"cells": [["notacell"]]},
    ],
)
def test_validator_rejects_gross_corruption(bad):
    # Call the validator DIRECTLY (not via validate_element_data, whose dispatcher
    # signature is (el, media_kinds) and which pre-guards non-dict). The direct call
    # also exercises _val_fill_table's own non-dict guard on the "notadict" case.
    with pytest.raises(TransferError):
        VALIDATORS["fill_table"](bad, "e1", set())


@pytest.mark.parametrize(
    "ok",
    [
        {
            "cells": [
                [{"kind": "answer", "answer": "1"}],
                [{"kind": "static", "html": "x"}, {"kind": "static", "html": "y"}],
            ]
        },  # ragged
        {"cells": [[{"kind": "weird"}]]},  # unknown kind
        {"cells": [[{"kind": "static", "html": "a"}]]},  # zero answer cells
        {
            "border": "dashed",
            "cells": [[{"kind": "answer", "answer": "1"}]],
        },  # bad border
    ],
)
def test_validator_accepts_tolerable_drift(ok):
    VALIDATORS["fill_table"](ok, "e1", set())  # must not raise


def test_image_cell_round_trip_preserves_asset_and_alt():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    src = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "image", "media": asset.pk, "alt": "graph"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    src.save()

    ids = MediaIdMap()
    payload = SERIALIZERS["fill_table"][1](src, ids)
    # export must register the asset and emit a STRING local id, not the int pk
    local_id = payload["cells"][0][0]["media"]
    assert isinstance(local_id, str)
    assert payload["cells"][0][0]["alt"] == "graph"
    assert ids.items() == [(local_id, asset)]

    # validate: media_kinds maps local id -> kind; validator must not raise and must
    # return a ref set containing the local id
    media_kinds = {local_id: "image"}
    refs = VALIDATORS["fill_table"](payload, "e1", media_kinds)
    assert local_id in refs

    # import: assets maps local id -> a (possibly new) MediaAsset
    new_course = make_course()
    dest_asset = make_image_asset(new_course, "g2.png")
    obj, _children = BUILDERS["fill_table"](payload, {local_id: dest_asset})
    cell = obj.data["cells"][0][0]
    assert cell["kind"] == "image" and cell["media"] == dest_asset.pk
    assert cell["alt"] == "graph"


def test_export_does_not_mutate_source_data():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    src = FillTableElement(
        data={"cells": [[{"kind": "image", "media": asset.pk, "alt": "g"}]]}
    )
    src.save()
    SERIALIZERS["fill_table"][1](src, MediaIdMap())
    # still the int pk, un-clobbered
    assert src.data["cells"][0][0]["media"] == asset.pk


def test_validator_image_cell_missing_media_key_raises_clean():
    payload = {"cells": [[{"kind": "image", "alt": "x"}]]}  # no media key
    with pytest.raises(TransferError):
        VALIDATORS["fill_table"](payload, "e1", {})


def test_validator_image_cell_unregistered_media_raises():
    payload = {"cells": [[{"kind": "image", "media": "m9", "alt": "x"}]]}
    with pytest.raises(TransferError):
        VALIDATORS["fill_table"](payload, "e1", {})  # m9 not in media_kinds
