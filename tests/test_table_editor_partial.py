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
