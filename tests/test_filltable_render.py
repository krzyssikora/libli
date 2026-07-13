import pytest

from courses.models import FillTableElement

pytestmark = pytest.mark.django_db


def _render(cells, **kw):
    el = FillTableElement(data={"cells": cells, **kw})
    el.save()
    # attach to a unit so a join row exists and eid is real (mirror sibling
    # render test); for a pure-render check eid=0 is acceptable — render()
    # falls back to 0.
    return el.render()


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
