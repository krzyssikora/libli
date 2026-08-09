"""Table element course export/validate/import: registration + round-trip (Task 9)."""

import io

import pytest

from courses.models import TableElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.export import MediaIdMap
from courses.transfer.export import _element_mids
from courses.transfer.export import write_archive
from courses.transfer.importer import BUILDERS
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_course
from tests.factories import make_image_asset
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


# SERIALIZERS values are (model, fn) TUPLES - `SERIALIZERS["table"](...)` raises
# TypeError: 'tuple' object is not callable. Unpack the callable once, exactly as
# tests/test_filltable_transfer.py does (`SERIALIZERS["fill_table"][1](src, ids)`).
_ser_table_fn = SERIALIZERS["table"][1]
_ser_fill_table_fn = SERIALIZERS["fill_table"][1]


def _tbl(cells, **top):
    return {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": cells,
        **top,
    }


def _img(media, **kw):
    return {
        "kind": "image",
        "media": media,
        "alt": "",
        "size": "full",
        "halign": "left",
        "valign": "top",
        **kw,
    }


def test_format_version_is_pinned():
    # Renamed from test_format_version_is_bumped_for_cell_images: that name
    # claimed ownership of the number this feature bumped, but Task 9
    # (published on the node payload) has since bumped it again to 10.
    assert FORMAT_VERSION == 10


def test_ser_table_registers_the_asset_and_emits_a_string_local_id(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = TableElement.objects.create(
        data=TableElement.normalize_data(_tbl([[_img(asset.pk, size="medium")]]))
    )
    out = _ser_table_fn(el, MediaIdMap())
    cell = out["cells"][0][0]
    assert cell["media"] == "m1"  # local STRING id, not the int pk
    assert cell["size"] == "medium"  # the preset survives export
    assert cell["kind"] == "image"


def test_ser_table_does_not_mutate_el_data(tmp_path, settings):
    """dict(el.data) is a SHALLOW copy: assigning cell["media"] in place would
    replace real pks on the in-memory element, and duplicate-unit persists that."""
    settings.MEDIA_ROOT = str(tmp_path)
    asset = make_image_asset(make_course())
    el = TableElement.objects.create(
        data=TableElement.normalize_data(_tbl([[_img(asset.pk)]]))
    )
    _ser_table_fn(el, MediaIdMap())
    assert el.data["cells"][0][0]["media"] == asset.pk


def test_ser_table_survives_ragged_rows_and_non_dict_cells():
    """EXPORT-ONLY fixture: _ser_table must not raise and must not alter these
    bytes. The resulting archive is legitimately NOT importable (_val_table's
    _exact_keys and its non-dict-cell check reject it) — do NOT extend into a
    round-trip, or you will "fix" the validator and widen the import surface."""
    stored = {"cells": [[_cell("a"), "not-a-dict"], "not-a-row", [_cell("b")]]}
    out = _ser_table_fn(TableElement(data=stored), MediaIdMap())
    assert out["cells"][1] == "not-a-row"
    assert out["cells"][0][1] == "not-a-dict"
    assert out["cells"][0][0] == _cell("a")


def test_ser_table_degrades_an_unresolvable_pk_keeping_spans():
    """A cell's media is a bare int in a JSONField with NO FK protection, so a
    dangling pk is reachable and ids.register(assets[pk]) would KeyError, 500ing
    both export and duplicate-unit."""
    el = TableElement(data=_tbl([[_img(999999, colspan=2, header=True)]]))
    cell = _ser_table_fn(el, MediaIdMap())["cells"][0][0]
    assert cell == {
        "html": "",
        "halign": "left",
        "valign": "top",
        "colspan": 2,
        "header": True,
    }
    assert "kind" not in cell


def test_ser_table_materialises_size_full_when_absent(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    asset = make_image_asset(make_course())
    el = TableElement(
        data=_tbl(
            [[{"kind": "image", "media": asset.pk, "halign": "left", "valign": "top"}]]
        )
    )
    assert _ser_table_fn(el, MediaIdMap())["cells"][0][0]["size"] == "full"


def test_ser_table_handles_an_image_cell_with_no_media_key():
    """By this spec's own defensive argument, a stored {"kind": "image"} with no
    media is reachable — and subscripting would 500 export AND duplicate-unit."""
    el = TableElement(data=_tbl([[{"kind": "image", "halign": "left"}]]))
    cell = _ser_table_fn(el, MediaIdMap())["cells"][0][0]
    assert cell == {"html": "", "halign": "left", "valign": "top"}


def test_legacy_non_normalized_table_export_bytes_are_unchanged():
    """_ser_table must NOT call normalize_data: save() calls only _sanitized_data,
    so nothing guarantees a stored row is rectangular. Normalizing at export would
    rectangularise and inject defaults, silently altering archive bytes."""
    stored = {"cells": [[{"html": "a"}], [{"html": "b"}, {"html": "c"}]]}
    out = _ser_table_fn(TableElement(data=stored), MediaIdMap())
    assert out == stored  # ragged rows kept, no halign/valign injected
    assert "header_row" not in out  # absent top-level keys NOT invented


def test_element_mids_table_yields_image_local_ids():
    """Mirrors test_element_mids_fill_table_yields_image_local_ids. NOTE the branch
    tests isinstance(..., str): _element_mids runs on ALREADY SERIALIZED data, where
    media is a local string id. An isinstance(..., int) test — the natural guess,
    since the STORED value is a pk — returns [].

    What a missing branch costs is DIAGNOSTICS, not data: document["media"] and the
    zip entries come from media_ids.items(), the registry _ser_table writes via
    ids.register(). This mid list feeds only mid_refs / missing-image reporting."""
    assert list(_element_mids("table", _tbl([[_img("m3"), _cell("x")]]))) == ["m3"]


def test_val_table_accepts_an_image_cell_and_coerces_out_of_enum_size():
    """Coerce, not reject — matching _val_image, for a cosmetic field with a
    lossless default: `full` IS the pre-feature rendering. Scoped to IMAGE cells,
    unlike _val_image's unconditional setdefault (which would write size onto TEXT
    cells). Note this DOES materialise the key on image cells; that is intended."""
    data = _tbl([[_img("m1", size="enormous")]])
    VALIDATORS["table"](data, "el-1", {"m1": "image"})
    assert data["cells"][0][0]["size"] == "full"


def test_val_table_rejects_an_unknown_cell_kind():
    data = _tbl([[{**_img("m1"), "kind": "video"}]])
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "el-1", {"m1": "image"})


def test_val_table_rejects_an_unregistered_or_wrong_kind_media_ref():
    with pytest.raises(TransferError):
        VALIDATORS["table"](_tbl([[_img("m9")]]), "el-1", {"m1": "image"})
    with pytest.raises(TransferError):
        VALIDATORS["table"](_tbl([[_img("m1")]]), "el-1", {"m1": "video"})


def test_a_plain_all_text_table_archive_still_imports():
    """The alt check MUST carry an `is not None` guard: check_str rejects None, and
    the flat allowlist means _val_table walks TEXT cells too, which carry no alt.
    An unconditional check_str fails EVERY pre-feature archive."""
    VALIDATORS["table"](_tbl([[_cell("a"), _cell("b")]]), "el-1", {})


def test_val_table_rejects_an_over_long_alt():
    data = _tbl([[_img("m1", alt="x" * 256)]])
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "el-1", {"m1": "image"})


def test_build_table_remaps_before_normalizing(tmp_path, settings):
    """ORDERING IS LOAD-BEARING: reversed, the string local id has already failed
    _cell's isinstance(media, int) test and degraded the cell to an empty text cell —
    a silent, total loss of every imported cell image with no error."""
    settings.MEDIA_ROOT = str(tmp_path)
    asset = make_image_asset(make_course())
    el, _children = BUILDERS["table"](_tbl([[_img("m1", size="large")]]), {"m1": asset})
    cell = el.data["cells"][0][0]
    assert cell["media"] == asset.pk
    assert cell["size"] == "large"


def test_table_image_cell_round_trips_end_to_end(tmp_path, settings):
    """export -> validate -> import preserves the asset AND the preset."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = TableElement.objects.create(
        data=TableElement.normalize_data(_tbl([[_img(asset.pk, size="small")]]))
    )
    payload = _ser_table_fn(el, MediaIdMap())
    VALIDATORS["table"](payload, "el-1", {"m1": "image"})
    rebuilt, _children = BUILDERS["table"](payload, {"m1": asset})
    cell = rebuilt.data["cells"][0][0]
    assert cell["kind"] == "image" and cell["media"] == asset.pk
    assert cell["size"] == "small"


def test_filltable_image_cell_round_trips_size(tmp_path, settings):
    """_ser_fill_table builds an explicit out_cell literal WITHOUT `size`, so
    without this change every fill-table export — and therefore duplicate-unit,
    duplicate-ELEMENT (builder.duplicate_element -> _copy_below runs export
    in-process) and clipboard paste — silently reverts every image cell to `full`."""
    from courses.models import FillTableElement

    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = FillTableElement.objects.create(
        data=FillTableElement.normalize_data(
            {
                "prompt": "",
                "case_sensitive": False,
                "header_row": False,
                "header_col": False,
                "border": "grid",
                "cells": [[{"kind": "image", "media": asset.pk, "size": "large"}]],
            }
        )
    )
    payload = _ser_fill_table_fn(el, MediaIdMap())
    assert payload["cells"][0][0]["size"] == "large"


def test_out_of_enum_size_is_tolerated_by_val_fill_table():
    """_val_fill_table stays lenient and gains no symmetric rejection — its
    docstring commits it to being "intentionally more lenient than _val_table",
    leaving value-enum drift for normalize_data to repair. The strictness asymmetry
    between the two validators is intentional and pre-existing; do NOT "fix" it."""
    data = {
        "prompt": "",
        "case_sensitive": False,
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [
            [
                {
                    "kind": "image",
                    "media": "m1",
                    "alt": "",
                    "size": "enormous",
                    "halign": "left",
                    "valign": "top",
                }
            ]
        ],
    }
    VALIDATORS["fill_table"](data, "el-1", {"m1": "image"})  # must not raise


def test_a_300_char_alt_survives_the_round_trip(tmp_path, settings):
    """Truncated at save — by _sanitized_data, which is what save() actually calls,
    since save() never normalizes — and never rejected at import."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = TableElement(data=_tbl([[{**_img(asset.pk), "alt": "x" * 300}]]))
    el.save()
    assert len(el.data["cells"][0][0]["alt"]) == 255
    payload = _ser_table_fn(el, MediaIdMap())
    VALIDATORS["table"](payload, "el-1", {"m1": "image"})  # must not raise


def test_a_table_with_a_cell_image_passes_whole_archive_validation(tmp_path, settings):
    """The `refs` return is observable ONLY from validate_archive_document: it is
    what stops schema.py rejecting the bundled asset as "not referenced by any
    element".

    Every other test in this task calls VALIDATORS["table"](...) directly and so
    bypasses the caller that consumes the return - which is exactly why a missed
    `return refs` would otherwise ship green.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit")
    asset = make_image_asset(course)
    add_element(
        unit,
        TableElement.objects.create(
            data=TableElement.normalize_data(_tbl([[_img(asset.pk, size="medium")]]))
        ),
    )

    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        # Real signature: (zf, manifest, document, media_entries, *, kind,
        # target_course=None) - importer.py:389. A two-arg call TypeErrors, so
        # "must NOT raise" would fail on a correct build.
        validate_archive_document(
            zf, mani, doc, media, kind="course", target_course=None
        )


def test_spanning_table_imports_from_legacy_v4_declared_bundle(
    client, settings, tmp_path
):
    # Spec test #8: a bundle DECLARING format_version=4 but carrying a spanning
    # table imports through the full gate (4 <= FORMAT_VERSION=10) AND the spanning
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
