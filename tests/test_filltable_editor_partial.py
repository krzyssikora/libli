import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import FillTableElement

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
EDITOR_HTML = ROOT / "templates/courses/manage/editor/editor.html"
FILLTABLE_JS = ROOT / "courses/static/courses/js/filltable_editor.js"


def _render(instance):
    form = FORM_FOR_TYPE["filltable"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_filltable.html",
        {"form": form, "type_key": "filltable"},
    )


def test_new_filltable_renders_default_2x2_grid():
    html = _render(FillTableElement())  # data == {} -> normalises to 2x2
    assert "data-filltable-editor" in html
    assert html.count("contenteditable") >= 4


def test_partial_has_hidden_data_field():
    html = _render(FillTableElement())
    assert 'name="data"' in html


def test_partial_has_case_sensitive_checkbox():
    html = _render(FillTableElement())
    assert "data-case-sensitive" in html


def test_partial_has_prompt_field():
    html = _render(
        FillTableElement(
            data=FillTableElement.normalize_data({"prompt": "Fill in the blanks"})
        )
    )
    assert "data-prompt" in html
    assert "Fill in the blanks" in html


def test_partial_has_answer_toggle_button():
    html = _render(FillTableElement())
    assert "data-answer-toggle" in html


def test_partial_renders_answer_cells_with_shaded_input():
    el = FillTableElement(
        data=FillTableElement.normalize_data(
            {"cells": [[{"kind": "answer", "answer": "cat"}, {"html": "static"}]]}
        )
    )
    html = _render(el)
    assert "data-answer" in html
    assert 'class="filltable-editor__answer"' in html
    assert 'value="cat"' in html


def test_partial_has_js_i18n_message_attrs():
    html = _render(FillTableElement())
    assert "data-msg-answer-placeholder" in html
    assert "data-msg-answer-blank" in html
    assert "data-msg-no-answer" in html


def _sprite_symbols():
    return set(
        re.findall(r'<symbol id="([\w-]+)"', EDITOR_HTML.read_text(encoding="utf-8"))
    )


def test_toolbar_icons_resolve_to_sprite_symbols():
    """The toolbar is icon-only, so a typo'd #ed-* href renders a blank button
    with no visible fallback. Pin every reference to a defined symbol."""
    refs = set(re.findall(r'use href="#(ed-[\w-]+)"', _render(FillTableElement())))
    assert refs, "expected the filltable toolbar to use sprite icons, not glyphs"
    assert refs <= _sprite_symbols()


def test_grid_handle_icons_resolve_to_sprite_symbols():
    """Same contract for the handles filltable_editor.js injects client-side."""
    used = set(re.findall(r'"(ed-[\w-]+)"', FILLTABLE_JS.read_text(encoding="utf-8")))
    assert used, "expected filltable_editor.js to reference ed-* sprite symbols"
    assert used <= _sprite_symbols()
