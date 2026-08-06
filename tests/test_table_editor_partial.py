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
    assert ".table-editor__toolbar[hidden]" not in css


def test_image_button_carries_both_pick_attributes():
    """data-pick-mode alone NEVER opens the picker: media_picker.js gates on
    closest("[data-pick-media]") and reads the asset kind from that attribute."""
    src = PARTIAL.read_text(encoding="utf-8")
    i = src.index("data-image-toggle")
    tag = src[src.rindex("<button", 0, i):src.index(">", i)]
    assert 'data-pick-media="image"' in tag
    assert 'data-pick-mode="cell"' in tag
    # Task 6 deliberately left this needle out of its own markup-disabled test (the
    # button did not exist yet) and promised it would be asserted HERE.
    assert "disabled" in tag


def test_per_cell_controls_are_hidden_named_and_unnamed():
    """`hidden` in MARKUP, not merely painted by JS — otherwise three cell-scoped
    controls render visible on every editor load until wire() runs. No `name`: the
    hidden data field is the sole authoritative input, and a badly chosen name can
    shadow a form property (the recorded form.action incident). aria-label because
    an icon-only .rte-btn and a bare <select> ship nameless to screen readers."""
    src = PARTIAL.read_text(encoding="utf-8")
    for attr in ("data-image-alt", "data-image-size", "data-image-remove"):
        i = src.index(attr)
        tag = src[src.rindex("<", 0, i):src.index(">", i)]
        assert "hidden" in tag, attr
        assert "name=" not in tag, attr
        assert "aria-label" in tag, attr


def test_size_select_iterates_the_model_choices_not_per_option_trans():
    """A bare {% trans "Full" %} resolves to the msgid owned by courses/forms.py
    (feminine "Pełna"), so the shipped select would render the wrong gender while a
    source-level test on the model constant still passed."""
    src = PARTIAL.read_text(encoding="utf-8")
    assert "form.cell_image_sizes" in src
    # Scope to the <option> REGION only. A window starting at `data-image-size` would
    # include the select's own title/aria-label {% trans %} calls, which
    # test_per_cell_controls_are_hidden_named_and_unnamed REQUIRES - the two assertions
    # would be mutually unsatisfiable.
    i = src.index("form.cell_image_sizes")
    # Search FORWARD from i: _edit_table.html already has a <select data-border> in the
    # controls strip ABOVE the toolbar, so a bare src.index("</select>") returns that
    # earlier closer, the slice runs backwards, and the assertion passes on "".
    seg = src[i:src.index("</select>", i)]
    assert "{% trans" not in seg


def test_grid_loop_reads_resolved_cells():
    """form.grid_data leaves cell.media an int, so the preview would emit src=""."""
    src = PARTIAL.read_text(encoding="utf-8")
    assert "form.resolved_grid_cells" in src
    assert "{% with d=form.grid_data %}" in src  # controls strip still needs `d`


def test_image_cell_branch_is_a_th_td_pair_with_full_attributes():
    src = PARTIAL.read_text(encoding="utf-8")
    for tag in ("<th data-image", "<td data-image"):
        i = src.index(tag)
        el = src[i:src.index(">", i)]
        assert 'data-media="{{ cell.media.pk }}"' in el, tag
        assert 'data-alt="{{ cell.alt }}"' in el, tag
        assert "data-size=\"{{ cell.size|default:'full' }}\"" in el, tag
        assert 'tabindex="0"' in el, tag
        assert "contenteditable" not in el, tag
        assert 'data-halign=' in el and 'data-valign=' in el, tag


def test_editor_preview_image_has_no_zoom_hook():
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-zoomable" not in src


def test_table_editor_js_registers_its_own_picker_hook():
    js = TABLE_JS.read_text(encoding="utf-8")
    assert "window.libliTablePickImage" in js
    # Both editor scripts load on every editor page, so a shared global means
    # whichever runs last wins and one editor's picker drives the other's callback.
    assert "libliFillTablePickImage" not in js
