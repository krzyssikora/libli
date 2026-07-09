"""Table element course export/validate/import: registration + round-trip (Task 9)."""

import io

import pytest

from courses.models import TableElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.export import write_archive
from courses.transfer.importer import BUILDERS
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _cell(html="", h="left", v="top"):
    return {"html": html, "halign": h, "valign": v}


def test_table_registered_in_all_three_registries():
    assert "table" in SERIALIZERS and "table" in VALIDATORS and "table" in BUILDERS


def test_import_sanitises_cell_html():
    cell = {"html": "<script>x</script><b>y</b>", "halign": "left", "valign": "top"}
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[cell]],
    }
    el, _children = BUILDERS["table"](data, {})
    assert "<script>" not in el.data["cells"][0][0]["html"]
    assert "<b>y</b>" in el.data["cells"][0][0]["html"]


def test_validator_rejects_over_cap():
    big = {
        "border": "grid",
        "header_row": False,
        "header_col": False,
        "cells": [[{"html": "", "halign": "left", "valign": "top"}] for _ in range(51)],
    }
    # _val_table signature mirrors the others: (data, elid, media_kinds)
    with pytest.raises(TransferError):
        VALIDATORS["table"](big, "el1", {})


def test_export_import_round_trip_preserves_table(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    src = CourseFactory()
    unit = ContentNodeFactory(course=src, kind="unit", unit_type="lesson")
    original = TableElement.normalize_data(
        {
            "header_row": True,
            "header_col": True,
            "border": "rows",
            "cells": [
                [_cell("Corner"), _cell("Head1", h="center")],
                [_cell(r"\(x<5\)", h="right", v="bottom"), _cell("data")],
            ],
        }
    )
    add_element(unit, TableElement.objects.create(data=original))

    buf = io.BytesIO()
    write_archive(src, None, buf)
    buf.seek(0)

    owner = make_login(client, "table-importer")
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="course", target_course=None
        )
        dest = import_course(zf, mani, doc, media, owner)

    tables = [
        join.content_object
        for node in dest.nodes.all()
        for join in node.elements.all()
        if isinstance(join.content_object, TableElement)
    ]
    assert len(tables) == 1
    data = tables[0].data
    assert data["header_row"] is True
    assert data["header_col"] is True
    assert data["border"] == "rows"
    assert [len(r) for r in data["cells"]] == [2, 2]
    assert data["cells"][0][0]["html"] == "Corner"
    assert data["cells"][0][1]["html"] == "Head1"
    assert data["cells"][0][1]["halign"] == "center"
    assert data["cells"][1][0]["html"] == r"\(x&lt;5\)"
    assert data["cells"][1][0]["halign"] == "right"
    assert data["cells"][1][0]["valign"] == "bottom"
    assert data["cells"][1][1]["html"] == "data"
