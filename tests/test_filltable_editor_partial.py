import json
import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import FillTableElement
from tests.factories import make_course
from tests.factories import make_image_asset

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


def test_editor_renders_existing_image_cell():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "image", "media": asset.pk, "alt": "graph"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    el.save()
    html = _render(el)
    assert "data-image" in html
    assert asset.file.url in html  # thumbnail
    assert f'data-media="{asset.pk}"' in html  # hidden pk (NOT the asset __str__)
    assert 'data-alt="graph"' in html  # per-cell alt stored on the <td>, no <input>


def test_editor_toolbar_has_image_toggle_and_alt_input():
    html = _render(FillTableElement())
    assert "data-image-toggle" in html
    assert "data-image-alt" in html


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


def test_filltable_editor_answer_header_cell_is_th_without_contenteditable():
    el = FillTableElement(
        data=FillTableElement.normalize_data(
            {
                "cells": [
                    [
                        {"kind": "answer", "answer": "a", "header": True},
                        {"kind": "static", "html": ""},
                    ]
                ]
            }
        )
    )
    html = _render(el)
    assert "<th" in html and "data-answer" in html
    # An answer cell is an <input>; making its TH contenteditable would let the
    # static-content handlers fire on it.
    assert not re.search(r"<th[^>]*data-answer[^>]*contenteditable", html)


def test_resolved_grid_cells_resolves_the_submitted_image_not_the_stored_one():
    """resolved_grid_cells exists so that after a REJECTED save the editor
    re-renders the grid the author SUBMITTED (grid_data), not what is on disk
    (self.instance). Every other test in this file builds the form UNBOUND,
    where grid_data falls through to self.instance.normalized_data -- the same
    result the old `form.instance.resolved_cells` path gave, so none of them
    would notice resolved_grid_cells reverting to read the instance instead of
    grid_data. Pin the real contract: bind the form to a payload naming a
    DIFFERENT MediaAsset than the stored instance, force it invalid (no
    answer cell, so clean_data's "at least one answer cell" check fires and
    grid_data takes the submitted branch), and assert the submitted asset
    wins."""
    course = make_course()
    stored_asset = make_image_asset(course, "stored.png")
    submitted_asset = make_image_asset(course, "submitted.png")
    instance = FillTableElement(
        data=FillTableElement.normalize_data(
            {
                "cells": [
                    [
                        {"kind": "image", "media": stored_asset.pk, "alt": "stored"},
                        {"kind": "answer", "answer": "1"},
                    ]
                ]
            }
        )
    )
    instance.save()
    submitted = {
        "cells": [
            [
                {"kind": "image", "media": submitted_asset.pk, "alt": "submitted"},
                # No answer cell at all -> clean_data rejects with "Mark at
                # least one answer cell", so the form is invalid and grid_data
                # takes the SUBMITTED-payload branch rather than falling back
                # to self.instance.
                {"kind": "static", "html": ""},
            ]
        ]
    }
    form = FORM_FOR_TYPE["filltable"](
        data={"data": json.dumps(submitted)}, instance=instance, course=course
    )
    assert not form.is_valid(), form.errors  # must take the grid_data submitted-branch
    resolved = form.resolved_grid_cells
    assert resolved[0][0]["kind"] == "image"
    # submitted pk wins, not stored_asset
    assert resolved[0][0]["media"] == submitted_asset


def test_unresolvable_image_cell_drops_spans_in_both_render_and_editor():
    """resolved_cells (student render) and resolved_grid_cells (editor) share
    one fallback for an image cell whose media pk cannot be resolved: drop the
    cell to an empty static cell, and drop any colspan/rowspan/header it
    carried along with it (a spanning gap left un-spanned would misshape the
    grid). Pin this for BOTH paths so they cannot silently re-diverge -- see
    FillTableElement.resolve_image_cells."""
    course = make_course()
    dangling_pk = 999999  # not in the DB
    raw = {
        "cells": [
            [
                {
                    "kind": "image",
                    "media": dangling_pk,
                    "alt": "x",
                    "colspan": 2,
                    "rowspan": 2,
                    "header": True,
                },
                {"kind": "answer", "answer": "1"},
            ]
        ]
    }

    # Student render path: FillTableElement.resolved_cells.
    el = FillTableElement(data=raw)
    el.save()
    model_cell = el.resolved_cells[0][0]
    assert model_cell["kind"] == "static" and model_cell["html"] == ""
    assert "colspan" not in model_cell
    assert "rowspan" not in model_cell
    assert "header" not in model_cell

    # Editor path, rejected-save branch: FillTableElementForm.resolved_grid_cells.
    submitted = {
        "cells": [
            [
                {
                    "kind": "image",
                    "media": dangling_pk,
                    "alt": "x",
                    "colspan": 2,
                    "rowspan": 2,
                    "header": True,
                },
                # No answer cell -> clean_data rejects, form invalid, grid_data
                # takes the submitted branch (see test above).
                {"kind": "static", "html": ""},
            ]
        ]
    }
    form = FORM_FOR_TYPE["filltable"](
        data={"data": json.dumps(submitted)}, instance=FillTableElement(), course=course
    )
    assert not form.is_valid(), form.errors
    form_cell = form.resolved_grid_cells[0][0]
    assert form_cell["kind"] == "static" and form_cell["html"] == ""
    assert "colspan" not in form_cell
    assert "rowspan" not in form_cell
    assert "header" not in form_cell
