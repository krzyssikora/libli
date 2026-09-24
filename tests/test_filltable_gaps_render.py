import re

import pytest

from courses.models import Element
from courses.models import FillTableElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

S = "\uffff"


def _el(cells, **kw):
    el = FillTableElement(data={"cells": cells, **kw})
    el.save()
    return el


def _render(el, done=False):
    if not done:
        return el.render(element=None, state=None)
    _course, unit = make_course_with_unit()
    row = Element.objects.create(unit=unit, content_object=el)
    return el.render(element=row, state={row.pk: {"done": True}})


TWO_GAPS = [
    [
        {
            "kind": "static",
            "html": r"\(y\) " + f"{S}0{S} and {S}1{S}",
            "gaps": [["ZQXanswerone"], ["ZQXanswertwo", "ZQXalt"]],
        }
    ]
]


def test_inline_inputs_rendered_with_rcg():
    html = _render(_el(TWO_GAPS))
    inputs = re.findall(r"<input[^>]*filltable__input--inline[^>]*>", html)
    assert len(inputs) == 2
    assert 'data-r="0" data-c="0" data-g="0"' in inputs[0]
    assert 'data-g="1"' in inputs[1]
    assert "box 2" in inputs[1]
    assert r"\(y\) " in html
    assert S not in html


def test_single_gap_label_has_no_box_number():
    html = _render(_el([[{"kind": "static", "html": f"{S}0{S}", "gaps": [["9"]]}]]))
    label = re.search(
        r'aria-label="([^"]*)"', html.split("filltable__input--inline")[1]
    )
    assert label.group(1) == "Answer, row 1, column 1"


def test_answers_never_reach_the_page():
    html = _render(_el(TWO_GAPS))
    assert "ZQX" not in html


def test_done_state_shows_first_alternative_locked():
    html = _render(_el(TWO_GAPS), done=True)
    inputs = re.findall(r"<input[^>]*filltable__input--inline[^>]*>", html)
    assert 'value="ZQXanswerone"' in inputs[0]
    assert "readonly" in inputs[0]
    assert "filltable__input--correct" in inputs[0]
    assert f'size="{len("ZQXanswerone")}"' in inputs[0]
    assert "ZQXanswertwo" in inputs[1] and "ZQXalt" not in inputs[1]


def test_done_state_value_is_escaped():
    el = _el([[{"kind": "static", "html": f"{S}0{S}", "gaps": [['a<b"c']]}]])
    html = _render(el, done=True)
    assert 'value="a&lt;b&quot;c"' in html
    assert 'a<b"c' not in html


def test_cell_without_gaps_renders_no_gap_input():
    html = _render(
        _el(
            [
                [
                    {"kind": "static", "html": "a" + f"{S}0{S}"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        )
    )
    assert "data-g=" not in html
