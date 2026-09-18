"""The per-table width preset: `full` (default), `fit` or `equal`.

WHY IT EXISTS. #314 made every display table shrink to fit so that two tables on
one page would agree about a shared column. Measured, that moved 240 of the
course's 265 tables across 136 of 148 units to fix a clash visible in about 15,
and it was reverted (#316). The width choice belongs to the author of the
individual table, not to the stylesheet.

THE DEFAULT IS LOAD-BEARING. Every one of the 265 existing tables was stored
before this key existed, and `save()` calls only `_sanitized_data`, never
`normalize_data` -- so those rows keep no `width` key until someone edits them.
`render()` normalises on the way out, which is what makes a legacy row render
identically to a table explicitly set to `full`. That equivalence is asserted
below on the rendered HTML, not on the dict, because the dict is not what the
browser sees.
"""

import pytest

from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _grid(rows=2, cols=2, **top):
    cells = [
        [{"html": f"r{r}c{c}", "halign": "left", "valign": "top"} for c in range(cols)]
        for r in range(rows)
    ]
    return {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": cells,
        **top,
    }


def test_the_preset_vocabulary_is_exactly_full_fit_and_equal():
    """Derived, not a count pin -- a third preset must be a deliberate edit here.

    See the ELEMENT_MODELS precedent: `len(...) == N` pins get bumped
    reflexively, so name the members instead.
    """
    assert TableElement.WIDTHS == {"full", "fit", "equal"}
    assert TableElement.DEFAULT_WIDTH == "full"
    assert TableElement.DEFAULT_WIDTH in TableElement.WIDTHS


def test_missing_width_normalises_to_full():
    """The legacy shape: 265 rows in the live course look exactly like this."""
    assert TableElement.normalize_data(_grid())["width"] == "full"


def test_fit_is_preserved():
    assert TableElement.normalize_data(_grid(width="fit"))["width"] == "fit"


@pytest.mark.parametrize("bogus", ["", "FIT", "auto", "100%", None, 0, [], {"a": 1}])
def test_an_unrecognised_width_falls_back_to_full(bogus):
    """Mirrors `border`'s handling. `auto` and `100%` are in here on purpose --
    they are the CSS values someone reaching for this would guess, and silently
    storing one would render an unstyled table."""
    assert TableElement.normalize_data(_grid(width=bogus))["width"] == "full"


def test_the_width_survives_a_save():
    """`save()` runs `_sanitized_data`, which must pass the key through -- it
    walks cells and leaves every other top-level key alone. Without this a table
    would revert to full the moment anyone edited a cell."""
    el = TableElement(data=TableElement.normalize_data(_grid(width="fit")))
    el.save()
    el.refresh_from_db()
    assert el.data["width"] == "fit"


def test_render_emits_the_width_class():
    assert "el--table--width-fit" in TableElement(data=_grid(width="fit")).render()
    assert "el--table--width-full" in TableElement(data=_grid(width="full")).render()


def test_a_legacy_table_renders_byte_identically_to_an_explicit_full():
    """The whole no-migration claim, asserted on the RENDERED HTML.

    A dict-level check would pass on a template that ignored `data.width`
    entirely, and would also pass if the template emitted an empty
    `el--table--width-` class for the legacy row. Comparing the two renderings
    is what makes "no existing table changes" true.
    """
    legacy = TableElement(data=_grid()).render()
    explicit = TableElement(data=_grid(width="full")).render()
    assert legacy == explicit
    assert "el--table--width-full" in legacy


def test_the_width_class_does_not_collide_with_the_border_class():
    """Both are `el--table--<something>` and both land on the same element."""
    html = TableElement(data=_grid(width="fit", border="none")).render()
    assert "el--table--border-none" in html
    assert "el--table--width-fit" in html


# --- `equal`: full width, every layout column the same share -----------------
#
# Why it exists: under `full`, auto table layout hands the surplus width out in
# proportion to each column's max-content, so a table whose first column holds
# "kat alpha ->" and whose others hold "30deg" gives column 1 almost half the
# table (prod unit 717). `fit` removes the surplus and reads dense. `equal`
# keeps the stretch but splits it evenly.


def test_equal_is_preserved():
    assert TableElement.normalize_data(_grid(width="equal"))["width"] == "equal"


def _col_widths(html):
    import re

    return re.findall(r'<col style="width: calc\(100% / (\d+)\)">', html)


def test_equal_emits_one_equal_col_per_column():
    html = TableElement(data=_grid(rows=2, cols=4, width="equal")).render()
    assert "el--table--width-equal" in html
    assert _col_widths(html) == ["4"] * 4


def test_equal_counts_layout_columns_not_cells_per_row():
    """A row made of one colspan=3 cell has ONE cell but spans three columns;
    counting cells in the first row would emit a single 100% col."""
    data = _grid(rows=1, cols=3, width="equal")
    data["cells"].insert(
        0, [{"html": "span", "halign": "left", "valign": "top", "colspan": 3}]
    )
    assert _col_widths(TableElement(data=data).render()) == ["3"] * 3


@pytest.mark.parametrize("width", ["full", "fit", None])
def test_only_equal_emits_a_colgroup(width):
    """full/fit/legacy must stay byte-identical to before `equal` existed."""
    data = _grid() if width is None else _grid(width=width)
    assert "<colgroup" not in TableElement(data=data).render()


def test_transfer_accepts_equal():
    from courses.transfer.payloads import _val_table

    data = TableElement.normalize_data(_grid())
    data["width"] = "equal"  # set AFTER normalising: exercise the validator alone
    _val_table(data, "e1", set())  # raises TransferError on an unknown preset
