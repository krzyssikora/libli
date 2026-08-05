"""Model-layer tests for TableElement/FillTableElement image cells (slice C2)."""

import pytest

from courses import tablecells
from courses.models import FillTableElement
from courses.models import TableElement


def _data(cell):
    return {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[cell]],
    }


def test_image_cell_normalizes_to_the_full_shape():
    nd = TableElement.normalize_data(
        _data(
            {
                "kind": "image",
                "media": 7,
                "alt": "a graph",
                "size": "medium",
                "halign": "center",
                "valign": "middle",
            }
        )
    )
    assert nd["cells"][0][0] == {
        "kind": "image",
        "media": 7,
        "alt": "a graph",
        "size": "medium",
        "halign": "center",
        "valign": "middle",
    }


def test_size_is_always_written_on_an_image_cell():
    """Absent size reads as the stored default, so every reader may subscript."""
    nd = TableElement.normalize_data(_data({"kind": "image", "media": 7}))
    assert nd["cells"][0][0]["size"] == "full"


def test_junk_size_coerces_to_full():
    for junk in ("enormous", "", None, 3, True):
        nd = TableElement.normalize_data(
            _data({"kind": "image", "media": 7, "size": junk})
        )
        assert nd["cells"][0][0]["size"] == "full", junk


@pytest.mark.parametrize("media", [None, "7", 7.0, True, False])
def test_invalid_media_degrades_to_a_kindless_text_cell(media):
    """Never raise, never render a broken <img>, and never leave a `kind` key."""
    nd = TableElement.normalize_data(
        _data({"kind": "image", "media": media, "halign": "right"})
    )
    cell = nd["cells"][0][0]
    assert cell == {"html": "", "halign": "right", "valign": "top"}
    assert "kind" not in cell


def test_alt_is_coerced_and_bounded_at_255():
    nd = TableElement.normalize_data(
        _data({"kind": "image", "media": 7, "alt": "x" * 300})
    )
    assert len(nd["cells"][0][0]["alt"]) == 255
    nd = TableElement.normalize_data(
        _data({"kind": "image", "media": 7, "alt": None})
    )
    assert nd["cells"][0][0]["alt"] == ""


def test_non_string_alt_never_becomes_the_literal_None():
    """str(alt) would store "None" — junk coerced into content."""
    nd = TableElement.normalize_data(
        _data({"kind": "image", "media": 7, "alt": {"a": 1}})
    )
    assert nd["cells"][0][0]["alt"] == ""


def test_image_cell_keeps_header_and_spans():
    nd = TableElement.normalize_data(
        _data(
            {"kind": "image", "media": 7, "header": True, "colspan": 2, "rowspan": 3}
        )
    )
    cell = nd["cells"][0][0]
    assert cell["header"] is True and cell["colspan"] == 2 and cell["rowspan"] == 3


def test_text_cells_gain_no_kind_key():
    """The byte-identity invariant: a text cell must serialize as it always did."""
    nd = TableElement.normalize_data(_data({"html": "<b>hi</b>"}))
    assert nd["cells"][0][0] == {
        "html": "<b>hi</b>",
        "halign": "left",
        "valign": "top",
    }


def test_sanitized_data_skips_image_cells_and_strips_alt():
    data = _data({"kind": "image", "media": 7, "alt": "  spaced  ", "size": "large"})
    out = TableElement._sanitized_data(TableElement.normalize_data(data))
    cell = out["cells"][0][0]
    assert cell["alt"] == "spaced"
    assert "html" not in cell
    assert cell["media"] == 7 and cell["size"] == "large"


def test_sanitized_data_survives_an_image_cell_with_no_alt_key():
    """_sanitized_data runs on RAW self.data from save(); a bare .strip() raises."""
    out = TableElement._sanitized_data(_data({"kind": "image", "media": 7}))
    assert out["cells"][0][0]["alt"] == ""


def test_sanitized_data_bounds_alt_at_255_directly():
    """save() calls ONLY _sanitized_data, never normalize_data, so the 255
    bound must hold here too -- not just in _cell (via normalize_data)."""
    out = TableElement._sanitized_data(
        _data({"kind": "image", "media": 7, "alt": "x" * 300})
    )
    assert len(out["cells"][0][0]["alt"]) == 255


def test_filltable_sanitized_data_bounds_alt_at_255_directly():
    data = {
        "prompt": "",
        "case_sensitive": False,
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": [[{"kind": "image", "media": 7, "alt": "x" * 300}]],
    }
    out = FillTableElement._sanitized_data(data)
    assert len(out["cells"][0][0]["alt"]) == 255


def test_filltable_image_cell_gains_size():
    nd = FillTableElement.normalize_data(
        {
            "prompt": "",
            "case_sensitive": False,
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": [[{"kind": "image", "media": 7, "size": "small"}]],
        }
    )
    assert nd["cells"][0][0]["size"] == "small"


def test_filltable_image_cell_size_defaults_and_coerces():
    base = {
        "prompt": "",
        "case_sensitive": False,
        "header_row": False,
        "header_col": False,
        "border": "grid",
    }
    nd = FillTableElement.normalize_data(
        {**base, "cells": [[{"kind": "image", "media": 7}]]}
    )
    assert nd["cells"][0][0]["size"] == "full"
    nd = FillTableElement.normalize_data(
        {**base, "cells": [[{"kind": "image", "media": 7, "size": "huge"}]]}
    )
    assert nd["cells"][0][0]["size"] == "full"


def test_size_tokens_and_defaults_are_named_once():
    assert TableElement.CellImageSize.values == ["small", "medium", "large", "full"]
    assert TableElement.DEFAULT_CELL_IMAGE_SIZE == "full"
    assert TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE == "medium"


def test_full_label_carries_the_image_size_gettext_context():
    """The spec's i18n pin, and the only part of the label story that can
    silently go wrong. The bare msgid "Full" is ALREADY taken by
    courses/forms.py's structure preset, whose Polish is "Pełna" (feminine);
    an image size is masculine ("Pełny"). Wrapping all four in pgettext_lazy
    would instead mint three brand-new msgids that ship untranslated, so the
    asymmetry is deliberate: bare _() for the first three, context only on
    Full.

    A source-level test because the rendered label is a lazy proxy - comparing str()
    under the default locale would pass either way.
    """
    import inspect
    import re

    src = inspect.getsource(TableElement.CellImageSize)
    assert re.search(
        r'FULL\s*=\s*"full",\s*pgettext_lazy\(\s*"image size",\s*"Full"\s*\)', src
    )
    for member in ("SMALL", "MEDIUM", "LARGE"):
        m = re.search(rf'{member}\s*=\s*"\w+",\s*(\S+)\(', src)
        assert m and m.group(1) == "_", member


def test_resolver_preserves_header_and_spans_on_an_unresolvable_pk():
    """INVERTS the old fill-table behaviour: export already carried spans through
    both branches ("losing the image must not silently un-span the cell"), so
    render now agrees with export."""
    cells = [[{"kind": "image", "media": 999999, "alt": "", "size": "full",
               "halign": "center", "valign": "middle",
               "header": True, "colspan": 2, "rowspan": 3}]]
    out = TableElement.resolve_image_cells(cells)
    cell = out[0][0]
    assert cell == {"html": "", "halign": "center", "valign": "middle",
                    "header": True, "colspan": 2, "rowspan": 3}
    assert "kind" not in cell


def test_filltable_resolver_preserves_spans_with_its_own_fallback_shape():
    cells = [[{"kind": "image", "media": 999999, "alt": "", "size": "full",
               "halign": "left", "valign": "top", "colspan": 2}]]
    cell = FillTableElement.resolve_image_cells(cells)[0][0]
    assert cell == {"kind": "static", "html": "", "halign": "left",
                    "valign": "top", "colspan": 2}


def test_resolver_defaults_alignment_on_a_cell_missing_those_keys():
    cell = TableElement.resolve_image_cells(
        [[{"kind": "image", "media": 999999}]]
    )[0][0]
    assert cell == {"html": "", "halign": "left", "valign": "top"}


def test_resolver_survives_an_image_cell_with_no_media_and_a_non_dict_cell():
    """Both are unreachable through today's callers (all normalise first), but the
    resolver keeps _ser_table's defensive posture rather than asserting a property the
    code does not have: a bare c["media"] would KeyError and 500 a lesson render."""
    out = TableElement.resolve_image_cells(
        [[{"kind": "image"}, "not-a-dict", {"html": "x"}]]
    )
    assert out[0][0] == {"html": "", "halign": "left", "valign": "top"}
    assert out[0][1] == "not-a-dict"
    assert out[0][2] == {"html": "x"}


def test_the_helper_actually_calls_the_injected_empty_cell():
    """One definition of the unresolved-asset behaviour, injected shape aside.

    Assert on the parsed AST, not a substring of the source: inspect.getsource
    includes the docstring, and the mandated docstring contains the literal
    `empty_cell(cell)` - so a substring check passes even if the body never calls
    the callable. Same trap as test_tablecells_has_no_module_level_imports guards
    against.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(tablecells.resolve_image_cells).lstrip())
    calls = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "empty_cell" in calls


def test_tablecells_has_no_module_level_imports():
    """A module-level MediaAsset import would be a circular import at app load.

    Assert on the parsed IMPORT NODES, not the bare identifier: the module docstring
    names MediaAsset twice, so `"MediaAsset" not in head` would fail against the
    CORRECT implementation. That is this repo's recorded "comments can fail tests"
    trap, and it has already bitten a source-scanning test here before.
    """
    import ast
    import pathlib

    src = pathlib.Path(tablecells.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))] == []


@pytest.mark.django_db
def test_resolved_cells_replaces_the_pk_with_the_asset(course_with_image):
    """Resolution only. The RENDER assertions belong to Task 4: at this point
    tableelement.html still emits {{ cell.html|safe }} on all five branches, and an
    image cell has no `html` key, so el.render() is empty and any
    `asset.file.url in html` assertion is impossible until _table_cell.html exists."""
    _course, asset = course_with_image
    el = TableElement.objects.create(data=TableElement.normalize_data(
        _data({"kind": "image", "media": asset.pk, "alt": "graph"})
    ))
    assert el.resolved_cells[0][0]["media"] == asset


@pytest.mark.django_db
def test_resolved_cells_can_be_merged_into_the_data_context(course_with_image):
    """The SHAPE render() must build: resolved cells INSIDE `data`, not replacing
    the context - the template reads data.border / data.header_row / data.cells.
    A bare {**normalize_data(...), "cells": ...} as the whole context would leave
    data.border empty and drop the header attributes.

    This is a shape check on the dict, NOT a pin on render() itself: it does not
    call el.render(), so leaving render() passing normalize_data(self.data)
    straight through keeps it green. The behavioural falsifier for Step 6 is
    Task 4's test_image_cell_renders_the_asset_with_preset_class_and_zoom_hook,
    which cannot exist until _table_cell.html does.
    """
    _course, asset = course_with_image
    el = TableElement.objects.create(data=TableElement.normalize_data(
        _data({"kind": "image", "media": asset.pk, "alt": "graph"})
    ))
    data = el.normalize_data(el.data)
    ctx_cells = {**data, "cells": el.resolved_cells}
    assert ctx_cells["border"] == "grid"          # top-level keys survive
    assert ctx_cells["cells"][0][0]["media"] == asset
