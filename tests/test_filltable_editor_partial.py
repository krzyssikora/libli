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
PARTIAL = ROOT / "templates/courses/manage/editor/_edit_filltable.html"
FILL_JS = FILLTABLE_JS


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


# non-blank: the guard keeps `gate` on
_GATE_CELLS = [[{"kind": "answer", "answer": "1"}]]


def test_partial_has_gate_checkbox_unchecked_by_default():
    html = _render(FillTableElement(data={"cells": _GATE_CELLS}))
    assert "data-gate" in html
    assert "data-gate checked" not in html


def test_partial_gate_checkbox_is_checked_for_a_gated_element():
    html = _render(FillTableElement(data={"cells": _GATE_CELLS, "gate": True}))
    assert "data-gate checked" in html


def test_editor_js_serializes_the_gate_flag():
    src = FILLTABLE_JS.read_text(encoding="utf-8")
    assert 'querySelector("[data-gate]")' in src
    assert "gate: !!(gate && gate.checked)" in src
    assert 'gate.addEventListener("change", serialize)' in src


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


def test_editor_grid_does_not_promote_header_row_or_col_cells_to_th():
    """Fill-table mirror of test_table_editor_partial's same-named test.

    Unlike colspan/rowspan -- which TableElement._span floors to None below
    2, so a stray span can never reach storage -- a stray `header` flag is
    NOT neutralised anywhere in the model. If the editor template promoted
    header_row/header_col cells to <th>, serialize() would start writing
    header:true for cells that never carried it, and that WOULD reach the DB
    and break byte-identity for every existing header-row fill table in the
    corpus. Only a cell's OWN header flag may produce a <th> here."""
    el = FillTableElement(
        data=FillTableElement.normalize_data(
            {"header_row": True, "header_col": True, "cells": [[{}, {}], [{}, {}]]}
        )
    )
    html = _render(el)
    # "<th" carries the whole signal -- do NOT also assert `"header" not in
    # html`, mirroring the plain-table test's own comment: the border preset
    # renders <option value="header"> unconditionally, so that substring is
    # present in every render regardless of this behaviour.
    assert "<th" not in html


def test_filltable_editor_exposes_merge_split_and_header_controls():
    """Cheap render-level check that Task 16's toolbar actually shipped --
    the twin of test_table_editor_exposes_merge_split_and_header_controls in
    tests/test_table_editor_partial.py."""
    html = _render(FillTableElement())
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


def test_unresolvable_image_cell_keeps_spans_in_both_render_and_editor():
    """An unresolvable image cell keeps its header/colspan/rowspan (slice C2).

    Inverted from the original drop-spans behaviour: _ser_fill_table has always
    carried these through BOTH branches, with the comment "losing the image must
    not silently un-span the cell and shift the grid". Export and render
    disagreed; render now agrees with export. Neither layout was measured — this
    is decided on consistency with export plus the fact that 15 of 312 tables
    span, so the case is live.
    """
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
    assert model_cell["colspan"] == 2
    assert model_cell["rowspan"] == 2
    assert model_cell["header"] is True

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
    assert form_cell["colspan"] == 2
    assert form_cell["rowspan"] == 2
    assert form_cell["header"] is True


def test_foreign_course_image_cell_does_not_resolve_in_the_editor():
    """A rejected save carrying ANOTHER course's image pk must not re-render
    that asset's URL.

    The payload is deliberately valid in every OTHER respect -- it carries a
    real answer cell -- so clean_data's earlier guards (caps, answer-cell
    presence, blank-answer) all pass and it reaches the img_ids course check,
    which is the rule that actually rejects it. Getting this wrong is easy: a
    payload with no answer cell is rejected by "Mark at least one answer cell"
    long before any media validation runs, and the test would then pass while
    exercising a different rejection path than its name claims."""
    mine = make_course()
    theirs = make_course()
    foreign = make_image_asset(theirs, filename="theirs.png")

    submitted = {
        "cells": [
            [
                {"kind": "image", "media": foreign.pk, "alt": "x"},
                {"kind": "answer", "answer": "1"},
            ]
        ]
    }
    form = FORM_FOR_TYPE["filltable"](
        data={"data": json.dumps(submitted)}, instance=FillTableElement(), course=mine
    )
    assert not form.is_valid(), form.errors
    # Pin WHY it was rejected, so the test cannot silently start passing for an
    # unrelated reason (an earlier guard firing) after a future edit.
    assert "not an image in this course" in str(form.errors)
    cell = form.resolved_grid_cells[0][0]
    # Falls into the EXISTING unresolved branch: empty static cell.
    assert cell["kind"] == "static" and cell["html"] == ""
    # The decisive assertion: the foreign asset's URL is nowhere in the output.
    assert foreign.file.url not in json.dumps(form.resolved_grid_cells, default=str)


def test_wrong_kind_media_does_not_resolve_in_the_editor():
    """clean_data requires an IMAGE in this course. An in-course asset of the
    wrong kind is rejected at save, so the resolver must not resolve it either
    -- otherwise the editor emits a video's URL inside an <img>. As above, the
    payload carries a real answer cell so the rejection comes from the media
    check and not from an earlier guard."""
    course = make_course()
    video = make_image_asset(course, filename="clip.png", kind="video")

    submitted = {
        "cells": [
            [
                {"kind": "image", "media": video.pk, "alt": "x"},
                {"kind": "answer", "answer": "1"},
            ]
        ]
    }
    form = FORM_FOR_TYPE["filltable"](
        data={"data": json.dumps(submitted)}, instance=FillTableElement(), course=course
    )
    assert not form.is_valid(), form.errors
    assert "not an image in this course" in str(form.errors)
    cell = form.resolved_grid_cells[0][0]
    assert cell["kind"] == "static" and cell["html"] == ""
    assert video.file.url not in json.dumps(form.resolved_grid_cells, default=str)


def test_filltable_toolbar_is_not_hidden():
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-table-toolbar hidden" not in src
    assert "data-table-toolbar" in src


def test_filltable_cell_scoped_buttons_carry_disabled_in_markup():
    """Twelve here, versus ten in _edit_table.html at this task: this partial
    already has both [data-image-toggle] and [data-answer-toggle]. Both were
    explicit decisions in the spec's predicate table, so both are asserted."""
    src = PARTIAL.read_text(encoding="utf-8")
    for needle in [
        'data-cmd="bold"',
        'data-cmd="italic"',
        'data-cmd="underline"',
        'data-cmd="math"',
        "data-image-toggle",
        "data-answer-toggle",
        'data-halign="left"',
        'data-halign="center"',
        'data-halign="right"',
        'data-valign="top"',
        'data-valign="middle"',
        'data-valign="bottom"',
    ]:
        i = src.index(needle)
        tag = src[src.rindex("<button", 0, i) : src.index(">", i)]
        assert "disabled" in tag, needle


def test_image_branches_carry_data_size_and_the_preview_modifier():
    src = PARTIAL.read_text(encoding="utf-8")
    assert src.count("data-size=\"{{ cell.size|default:'full' }}\"") == 2  # th + td
    assert src.count("filltable-editor__img--{{ cell.size|default:'full' }}") == 2


def test_size_select_is_present_beside_the_alt_input():
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-image-size" in src
    assert "form.cell_image_sizes" in src


def test_filltable_per_cell_controls_are_hidden_named_and_unnamed():
    """Mirrors the plain table's test_per_cell_controls_are_hidden_named_and_unnamed.
    A presence check alone is not enough: a select without markup `hidden` renders
    visible on every fill-table editor load until wire() runs, and Task 9's
    fill-table e2e asserts visibility only AFTER the image cell is clicked, so it
    would stay green."""
    src = PARTIAL.read_text(encoding="utf-8")
    for attr in ("data-image-alt", "data-image-size"):
        i = src.index(attr)
        tag = src[src.rindex("<", 0, i) : src.index(">", i)]
        assert "hidden" in tag, attr
        assert "name=" not in tag, attr
        assert "aria-label" in tag, attr
    # maxlength is half of the spec's "255 at both ends" decision, which is what
    # keeps an authorable table re-importable. Task 7 Step 3 adds it here;
    # nothing else pins it.
    i = src.index("data-image-alt")
    assert 'maxlength="255"' in src[src.rindex("<", 0, i) : src.index(">", i)]


def test_serialize_image_branch_emits_size():
    js = FILL_JS.read_text(encoding="utf-8")
    seg = js[js.index('kind: "image"') : js.index('kind: "image"') + 400]
    assert "size:" in seg


def test_toggle_answer_cell_clears_data_size():
    """A stale data-size would linger on the static cell and be inherited by a
    later reconversion."""
    js = FILL_JS.read_text(encoding="utf-8")
    seg = js[js.index("function toggleAnswerCell") :]
    seg = seg[: seg.index("\n    }")]
    assert "data-size" in seg or "dataset.size" in seg


@pytest.mark.django_db
def test_form_and_model_preserve_a_submitted_size(tmp_path, settings):
    """Pins the FORM + MODEL path only: a payload carrying `size` survives
    clean_data, normalize_data and save().

    It hand-builds its JSON and posts it, so it never runs JS - it is green with
    or without `size:` in serialize() and with or without `data-size` in the
    template. Those two JS sites are pinned by the source-level tests above and,
    behaviourally, by Task 9's fill-table e2e. Do not point a serialize() mutant
    at this test.
    """
    from courses.element_forms import FillTableElementForm

    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course, filename="a.png")
    payload = {
        "data": json.dumps(
            {
                "prompt": "",
                "case_sensitive": False,
                "header_row": False,
                "header_col": False,
                "border": "grid",
                # An ANSWER CELL IS MANDATORY: FillTableElementForm.clean_data raises
                # "Mark at least one answer cell (use the "Answer cell" button)." when
                # answer_cells(cells) is empty, so an image-only payload can NEVER
                # validate and this test — the pin for the slice's highest-frequency
                # defect — could never pass.
                "cells": [
                    [
                        {
                            "kind": "image",
                            "media": asset.pk,
                            "alt": "",
                            "size": "large",
                            "halign": "left",
                            "valign": "top",
                        },
                        {
                            "kind": "answer",
                            "answer": "x",
                            "halign": "left",
                            "valign": "top",
                        },
                    ]
                ],
            }
        )
    }
    form = FillTableElementForm(data=payload, course=course)
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.data["cells"][0][0]["size"] == "large"
