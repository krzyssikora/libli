"""Model-layer tests for TableElement/FillTableElement image cells (slice C2)."""

import pytest

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
