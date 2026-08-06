import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import TableElement

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
EDITOR_HTML = ROOT / "templates/courses/manage/editor/editor.html"
TABLE_JS = ROOT / "courses/static/courses/js/table_editor.js"
PARTIAL = ROOT / "templates/courses/manage/editor/_edit_table.html"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"


def _render(instance):
    form = FORM_FOR_TYPE["table"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_table.html", {"form": form, "type_key": "table"}
    )


def test_new_table_renders_default_2x2_grid():
    html = _render(TableElement())  # data == {} -> normalises to 2x2
    assert "data-table-editor" in html
    assert html.count("contenteditable") >= 4


def test_existing_table_reflects_stored_border_and_headers():
    el = TableElement(
        data=TableElement.normalize_data(
            {"border": "rows", "header_row": True, "cells": [[{"html": "hi"}]]}
        )
    )
    html = _render(el)
    assert "hi" in html
    assert 'value="rows"' in html or "selected" in html  # border reflected


def _sprite_symbols():
    return set(
        re.findall(r'<symbol id="([\w-]+)"', EDITOR_HTML.read_text(encoding="utf-8"))
    )


def test_toolbar_icons_resolve_to_sprite_symbols():
    """The toolbar is icon-only, so a typo'd #ed-* href renders a blank button
    with no visible fallback. Pin every reference to a defined symbol."""
    refs = set(re.findall(r'use href="#(ed-[\w-]+)"', _render(TableElement())))
    assert refs, "expected the table toolbar to use sprite icons, not glyphs"
    assert refs <= _sprite_symbols()


def test_grid_handle_icons_resolve_to_sprite_symbols():
    """Same contract for the handles table_editor.js injects client-side."""
    used = set(re.findall(r'"(ed-[\w-]+)"', TABLE_JS.read_text(encoding="utf-8")))
    assert used, "expected table_editor.js to reference ed-* sprite symbols"
    assert used <= _sprite_symbols()


def test_editor_grid_emits_spans_for_a_spanning_table():
    el = TableElement(
        data=TableElement.normalize_data(
            {"cells": [[{"colspan": 3, "rowspan": 2, "html": "m"}], [{}, {}]]}
        )
    )
    html = _render(el)
    assert 'colspan="3"' in html
    assert 'rowspan="2"' in html


def test_editor_grid_emits_th_for_a_header_cell():
    el = TableElement(
        data=TableElement.normalize_data(
            {"cells": [[{"header": True, "html": "h"}, {}]]}
        )
    )
    html = _render(el)
    assert "<th" in html
    # a header cell in the plain table is still editable
    assert re.search(r"<th[^>]*contenteditable", html)


def test_editor_grid_of_a_plain_table_has_no_span_attributes():
    html = _render(TableElement())
    assert "colspan" not in html
    assert "rowspan" not in html
    assert "<th" not in html


def test_editor_grid_does_not_promote_header_row_or_col_cells_to_th():
    """The riskiest byte-identity case, and the one the default 2x2 misses.

    If the EDITOR promoted header_row/header_col cells to <th>, serialize()
    would start writing header:true for cells that never carried it -- breaking
    byte-identity for every existing header-row table in the corpus. Only a
    cell's OWN header flag may produce a <th> here."""
    el = TableElement(
        data=TableElement.normalize_data(
            {"header_row": True, "header_col": True, "cells": [[{}, {}], [{}, {}]]}
        )
    )
    html = _render(el)
    # "<th" carries the whole signal. Do NOT also assert `"header" not in html`:
    # the border preset renders <option value="header"> unconditionally, so that
    # substring is present in every render, before and after this change.
    assert "<th" not in html


def test_table_editor_exposes_merge_split_and_header_controls():
    html = _render(TableElement())
    for attr in ("data-merge", "data-split", "data-header-toggle"):
        assert attr in html
    # Client-built markup cannot call {% trans %}, so every string rides on a
    # data-msg-* attribute (the established convention in this editor).
    for msg in (
        "data-msg-merge-confirm",
        "data-msg-merge-too-big",
        "data-msg-header-locked",
        "data-msg-range-selected",
        "data-msg-merge",
        "data-msg-header",
        "data-msg-range-cleared",
    ):
        assert msg in html
    assert 'aria-live="polite"' in html


def test_toolbar_is_not_hidden():
    """Discoverability: an author opening a table saw a bare grid and no controls,
    with nothing signalling that clicking a cell reveals eighteen of them."""
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-table-toolbar hidden" not in src
    assert "data-table-toolbar" in src


def test_cell_scoped_buttons_carry_disabled_in_markup():
    """Between page load and wire(), and permanently if JS never runs, these would
    otherwise render ENABLED with nothing focused. The e2e assertion cannot see
    this window because wire() has already run by the time Playwright looks."""
    src = PARTIAL.read_text(encoding="utf-8")
    # NOTE: `data-image-toggle` is deliberately ABSENT from this list. _edit_table.html
    # has no image button until Task 7 creates it, so including it here would raise
    # ValueError: substring not found and make this task's PASS unreachable. Task 7
    # asserts it. (This partial's count at the end of Task 6 is therefore TEN
    # cell-scoped buttons: 4 [data-cmd] + 3 halign + 3 valign.)
    for needle in ['data-cmd="bold"', 'data-cmd="italic"', 'data-cmd="underline"',
                   'data-cmd="math"',
                   'data-halign="left"', 'data-halign="center"',
                   'data-halign="right"', 'data-valign="top"',
                   'data-valign="middle"', 'data-valign="bottom"']:
        i = src.index(needle)
        tag = src[src.rindex("<button", 0, i):src.index(">", i)]
        assert "disabled" in tag, needle


def test_rte_swatches_partial_is_untouched():
    """It is included by SIX toolbars whose editors have no disabled mechanism;
    adding `disabled` there would permanently disable colour authoring in the
    text, callout, spoiler and generic RTE editors."""
    import pathlib

    from django.conf import settings

    p = (pathlib.Path(settings.BASE_DIR)
         / "templates/courses/manage/editor/_rte_swatches.html")
    assert "disabled" not in p.read_text(encoding="utf-8")


def test_editor_css_drops_the_dead_toolbar_hidden_rule():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    assert ".table-editor__toolbar[hidden] { display: none; }" not in css
