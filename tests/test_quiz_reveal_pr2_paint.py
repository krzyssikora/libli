"""Verdict painting in the Python-built drag / grid controls (spec 2026-09-25 §2.1)."""

import re

import pytest

from courses import dnd
from courses.fillblank import parse
from courses.templatetags.courses_extras import render_choice_grid
from courses.templatetags.courses_extras import render_drag_selects
from courses.templatetags.courses_extras import render_multigrid
from courses.verdicts import part_verdict
from tests.reveal_pr2_kit import GRID_KINDS
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import paint
from tests.reveal_pr2_kit import parts
from tests.reveal_pr2_kit import post

_SR_OK = '<span class="sr-only">correct</span>'
_SR_BAD = '<span class="sr-only">incorrect</span>'


def test_part_verdict_rules():
    assert part_verdict([True, False], 1, key=False) is False
    assert part_verdict([True], 3, key=False) is None  # shorter list: unpainted
    assert part_verdict(None, 0, key=False) is None
    assert part_verdict(None, 5, key=True) is True  # the key copy: all correct


def test_unpainted_select_is_byte_identical():
    # Master's markup, literally (the option label is translatable, so only the
    # structure around it is pinned). The existing render suites guard the rest.
    plain = str(dnd._render_select(["a", "b"], "a"))
    assert plain.startswith('<select name="slot" class="dnd__select"><option value="">')
    assert plain.endswith(
        '<option value="a" selected>a</option><option value="b">b</option></select>'
    )


def test_render_selects_paints_each_gap_with_both_cues():
    stem = parse("x {{a}} y {{b}}")[0]
    html = str(
        dnd.render_selects(stem, ["a", "b", "c"], ["a", "c"], verdicts=[True, False])
    )
    right, wrong = parts("dragfill", html)
    assert paint("dragfill", html) == ["correct", "incorrect"]
    assert "aria-invalid" not in right and right.endswith(_SR_OK)
    assert 'aria-invalid="true"' in wrong.split(">", 1)[0] and wrong.endswith(_SR_BAD)


def test_key_paints_every_gap_correct():
    stem = parse("x {{a}} y {{b}}")[0]
    html = str(dnd.render_selects(stem, ["a", "b"], ["a", "b"], key=True))
    assert paint("dragfill", html) == ["correct", "correct"]


def test_match_and_zone_rows_paint():
    class P:  # render_match_rows reads only .left
        def __init__(self, left):
            self.left = left

    rows = str(
        dnd.render_match_rows(
            [P("L1"), P("L2")], ["a", "b"], ["a", "b"], verdicts=[False, None]
        )
    )
    assert paint("matchpair", rows) == ["incorrect", None]
    zones = str(
        dnd.render_zone_selects(
            [object(), object()], ["a"], ["a", ""], verdicts=[True, False]
        )
    )
    assert paint("dragimage", zones) == ["correct", "incorrect"]


@pytest.mark.django_db
def test_drag_tag_forwards_verdicts_and_copy():
    kit = build("dragfill")
    q = kit.question
    assert paint(
        "dragfill",
        str(render_drag_selects(q, ["alphakey", "gammadis"], verdicts=[True, False])),
    ) == ["correct", "incorrect"]
    assert paint("dragfill", str(render_drag_selects(q, kit.key, copy="key"))) == [
        "correct",
        "correct",
    ]
    assert paint("dragfill", str(render_drag_selects(q))) == [None, None]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", GRID_KINDS)
def test_grid_rows_paint_with_both_cues(kind):
    kit = build(kind)
    q = kit.question
    tag = render_choice_grid if kind == "choicegrid" else render_multigrid
    values = q.build_answer(post(kit.half))
    html = str(tag(q, values, verdicts=[True, False]))
    right, wrong = parts(kind, html)
    assert paint(kind, html) == ["correct", "incorrect"]
    assert _SR_OK in right and "aria-invalid" not in right
    assert _SR_BAD in wrong
    inputs = [c for c in wrong.split("<input")[1:]]
    assert inputs and all('aria-invalid="true"' in c.split(">", 1)[0] for c in inputs)
    # aria-invalid goes LAST, so the pinned `value="<pk>" checked` substring survives.
    assert re.search(r'value="\d+" checked aria-invalid="true">', wrong)
    assert paint(kind, str(tag(q, kit.key, copy="key"))) == ["correct", "correct"]


def test_painted_select_keeps_its_name_prefix():
    # courses/tests/test_question_restore.py::_slot_options splits on this literal.
    html = str(dnd._render_select(["a"], "a", verdict=False))
    assert html.startswith(
        '<select name="slot" class="dnd__select is-incorrect" aria-invalid="true">'
    )


@pytest.mark.django_db
@pytest.mark.parametrize("kind", GRID_KINDS)
def test_unpainted_grid_row_markup_unchanged(kind):
    kit = build(kind)
    tag = render_choice_grid if kind == "choicegrid" else render_multigrid
    html = str(tag(kit.question, None))
    assert "<tr>" in html and "is-" not in html and "sr-only" not in html
    assert "aria-invalid" not in html
