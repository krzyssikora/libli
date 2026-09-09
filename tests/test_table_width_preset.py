"""The per-table width preset: `full` (default) or `fit`.

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


def test_the_preset_vocabulary_is_exactly_full_and_fit():
    """Derived, not a count pin -- a third preset must be a deliberate edit here.

    See the ELEMENT_MODELS precedent: `len(...) == N` pins get bumped
    reflexively, so name the members instead.
    """
    assert TableElement.WIDTHS == {"full", "fit"}
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
