import pytest
from bs4 import BeautifulSoup

from courses.models import CalloutElement
from courses.models import Element
from courses.models import FillTableElement
from tests.factories import make_course
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db

_CELLS_WITH_ANSWER = [
    [{"kind": "static", "html": "x"}, {"kind": "answer", "answer": "4"}],
]


def _render(cells, **kw):
    el = FillTableElement(data={"cells": cells, **kw})
    el.save()
    # attach to a unit so a join row exists and eid is real (mirror sibling
    # render test); for a pure-render check eid=0 is acceptable — render()
    # falls back to 0.
    return el.render()


def test_gated_table_marks_the_root_div():
    html = _render(_CELLS_WITH_ANSWER, gate=True)
    assert "data-reveal-gate" in html
    assert "data-filltablegate" in html


def test_ungated_table_has_no_gate_attributes():
    html = _render(_CELLS_WITH_ANSWER)
    assert "data-reveal-gate" not in html
    assert "data-filltablegate" not in html


def test_gate_marker_is_on_the_same_node_as_data_state():
    # reveal.js::storedOpen reads dataset.state off the node it matched via
    # [data-reveal-gate]. If the marker lands on the inner .el--filltable div
    # instead, storedOpen reads undefined -> the gate never restores and the
    # revealed content is hidden forever.
    html = _render(_CELLS_WITH_ANSWER, gate=True)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("[data-reveal-gate][data-filltablegate]")
    assert node is not None
    assert node.has_attr("data-state")
    assert "filltable" in node.get("class", [])


def _render_callout_with_filltable_child(gate):
    """Render a CalloutElement whose only child is a fill-table.

    resolved_children() groups by `parent` alone, so no tab_id is needed.
    """
    _course, unit = make_course_with_unit()
    callout = CalloutElement.objects.create()
    parent_row = Element.objects.create(unit=unit, content_object=callout)
    child = FillTableElement(data={"cells": _CELLS_WITH_ANSWER, "gate": gate})
    child.save()
    Element.objects.create(unit=unit, content_object=child, parent=parent_row)
    return callout.render(
        element=parent_row, state={}, slug=unit.course.slug, node_pk=unit.pk
    )


def test_gated_filltable_is_a_direct_child_of_the_callout_child_wrapper():
    # The pre-hide CSS is
    # `.callout__children > .callout__child:has(> [data-reveal-gate])`.
    # One extra wrapper div between .callout__child and .filltable disarms it
    # silently -- the gate still works on click, but nothing is hidden to begin
    # with, so the student sees the answer before earning it.
    soup = BeautifulSoup(_render_callout_with_filltable_child(gate=True), "html.parser")
    child = soup.select_one(".callout__children > .callout__child")
    assert child is not None
    marked = soup.select_one("[data-reveal-gate]")
    assert marked is not None
    assert marked.parent is child, (
        "the gate marker is not a DIRECT child of .callout__child"
    )
    assert "filltable" in marked.get("class", [])


def test_answer_cell_input_carries_zero_based_indices_and_no_answer():
    html = _render(
        [[{"kind": "static", "html": "t"}, {"kind": "answer", "answer": "secret"}]]
    )
    assert 'data-r="0"' in html and 'data-c="1"' in html
    assert "secret" not in html  # answer NEVER reaches the client
    assert 'value="secret"' not in html


def test_static_cell_math_left_raw_for_client_typeset():
    html = _render(
        [[{"kind": "static", "html": r"\(x<5\)"}, {"kind": "answer", "answer": "1"}]]
    )
    # sanitize_cell's _canon_math canonicalises the math span's "<" to "&lt;"
    # at save() (see tests/test_filltable_model.py::test_save_preserves_math_
    # in_static_cell); the template emits the already-sanitised html |safe,
    # so the single-escaped form is what reaches the client for KaTeX.
    assert r"\(x&lt;5\)" in html


def test_root_has_check_url_and_summary_msgs():
    html = _render(
        [[{"kind": "answer", "answer": "1"}, {"kind": "static", "html": "b"}]]
    )
    assert "filltable-check" in html  # data-check-url reversed
    assert "data-success-msg" in html and "data-retry-msg" in html


def test_prompt_rendered_escaped_when_present():
    html = _render([[{"kind": "answer", "answer": "1"}]], prompt="Fill <it> in")
    assert "Fill &lt;it&gt; in" in html  # escaped, not |safe


def test_image_cell_renders_img_with_url_and_alt():
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
    html = el.render()
    assert asset.file.url in html
    assert 'alt="graph"' in html
    assert "filltable__img" in html


def test_image_cell_unresolved_renders_no_broken_img():
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "image", "media": 999999, "alt": "x"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    el.save()
    html = el.render()
    assert "filltable__img" not in html  # degraded to empty static, no <img>


def test_done_render_keeps_image_and_canonicalises_answer():
    # mine.done path must resolve image cells too (uses canonical_cells)
    course = make_course()
    asset = make_image_asset(course, "g.png")
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "image", "media": asset.pk, "alt": "g"},
                    {"kind": "answer", "answer": "4 | four"},
                ]
            ]
        }
    )
    el.save()
    # canonical_cells is the done-path grid; assert the image cell is resolved there
    done_cells = el.canonical_cells
    assert done_cells[0][0]["kind"] == "image"
    assert done_cells[0][0]["media"].pk == asset.pk  # resolved, not an int
    assert done_cells[0][1]["answer"] == "4"  # first alternative
