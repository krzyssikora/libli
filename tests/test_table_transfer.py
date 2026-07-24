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


def _span_cell(html="", h="left", v="top", **extra):
    return {"html": html, "halign": h, "valign": v, **extra}


def test_val_table_accepts_spanning_ragged_table():
    # Ragged rows + colspan/rowspan/header: rejected today, must be accepted.
    data = TableElement.normalize_data(
        {
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": [
                [_span_cell("A", colspan=2, header=True)],  # 1 cell, width 2
                [_span_cell("B"), _span_cell("C", rowspan=2)],  # 2 cells
                [_span_cell("D")],  # 1 cell (C spans down)
            ],
        }
    )
    assert VALIDATORS["table"](data, "e1", {}) == set()


def test_val_table_rectangular_header_no_spans_accepted():
    # C1 regression: a non-spanning, uniform table whose only optional key is
    # per-cell header:True must validate (today's _exact_keys rejects "header").
    data = TableElement.normalize_data(
        {
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": [
                [_span_cell("H1", header=True), _span_cell("H2", header=True)],
                [_span_cell("a"), _span_cell("b")],
            ],
        }
    )
    assert VALIDATORS["table"](data, "e1", {}) == set()


def test_val_table_spanning_over_max_cols_rejected():
    row = [_span_cell("x", colspan=TableElement.MAX_COLS)] + [_span_cell("y")]
    data = {"header_row": False, "header_col": False, "border": "grid", "cells": [row]}
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_non_dict_cell_rejected_no_raw_exception():
    # Guard: a non-dict cell is rejected as TransferError, never a raw exception.
    # Uses an int cell (5): without the isinstance guard, `set(5)` raises a raw
    # TypeError (int not iterable) BEFORE the unknown-key check -> RED (falsified
    # in Step 4b). Passes before AND after the fix (today via _exact_keys'
    # isinstance guard). A string cell would NOT work here: set("x") is iterable
    # and the unknown-key check would still raise TransferError, masking the guard.
    data = {"header_row": False, "header_col": False, "border": "grid", "cells": [[5]]}
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_unknown_cell_key_rejected():
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[_span_cell("x", bogus=1)]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_non_str_html_rejected():
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[{"html": 123, "halign": "left", "valign": "top"}]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_out_of_enum_alignment_rejected():
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[{"html": "", "halign": "sideways", "valign": "top"}]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_tolerates_bogus_optional_and_absent_core():
    # Mirror-the-model leniency: bogus optional span + a cell missing core keys
    # are accepted (the model coerces them). colspan:0 makes NO cell span, so
    # this is a rectangular 1x2 grid.
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[{"colspan": 0}, {}]],
    }
    assert VALIDATORS["table"](data, "e1", {}) == set()


def test_val_table_non_spanning_ragged_still_rejected():
    data = {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[_span_cell("a"), _span_cell("b")], [_span_cell("c")]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_spanning_table_round_trip_preserves_data(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    src = CourseFactory()
    unit = ContentNodeFactory(course=src, kind="unit", unit_type="lesson")
    original = TableElement.normalize_data(
        {
            "header_row": True,
            "header_col": False,
            "border": "grid",
            "cells": [
                [_span_cell("Title", h="center", colspan=2, header=True)],
                [_span_cell("L", rowspan=2), _span_cell("r1")],
                [_span_cell("r2")],
            ],
        }
    )
    saved = TableElement.objects.create(data=original)
    add_element(unit, saved)

    buf = io.BytesIO()  # `io` is imported at the module top
    write_archive(src, None, buf)
    buf.seek(0)
    owner = make_login(client, "span-importer")
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
    # Byte-identity against the SAVED source (import applies normalize+sanitize;
    # the saved source is already normalized+sanitized, so they must be equal).
    assert tables[0].data == saved.data


def test_spanning_table_imports_from_legacy_v4_declared_bundle(
    client, settings, tmp_path
):
    # Spec test #8: a bundle DECLARING format_version=4 but carrying a spanning
    # table imports through the full gate (4 <= FORMAT_VERSION=5) AND the spanning
    # branch — proving span handling keys on span-key presence, not the version.
    # Build a real archive via write_archive (emits v5), then downgrade the
    # manifest's declared version to 4 and re-drive it through the importer.
    import json
    import zipfile

    settings.MEDIA_ROOT = tmp_path
    src = CourseFactory()
    unit = ContentNodeFactory(course=src, kind="unit", unit_type="lesson")
    data = TableElement.normalize_data(
        {
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": [[_span_cell("x", colspan=2)], [_span_cell("a"), _span_cell("b")]],
        }
    )
    add_element(unit, TableElement.objects.create(data=data))

    import io

    src_buf = io.BytesIO()
    write_archive(src, None, src_buf)
    src_buf.seek(0)

    out = io.BytesIO()
    with zipfile.ZipFile(src_buf) as zin, zipfile.ZipFile(out, "w") as zout:
        for name in zin.namelist():
            raw = zin.read(name)
            if name == "manifest.json":
                m = json.loads(raw)
                m["format_version"] = 4
                raw = json.dumps(m).encode()
            zout.writestr(name, raw)
    out.seek(0)

    owner = make_login(client, "v4-importer")
    with open_archive(out, expected_kind="course") as (zf, mani, doc, media):
        assert mani["format_version"] == 4
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
    assert len(tables) == 1  # v4 bundle with spans imported via the spanning branch
