"""Style-presence guards for the Matrix (choice-grid) question.

Mirrors tests/test_table_css.py / test_callout_css.py: the CSS classes are wired
to markup only by name (the student table comes from the render_choice_grid tag,
the editor rows from choicegrid.js clones), so nothing but a name match ties them
together. Pin the contract in both the student and editor stylesheets, and prove
the rendered student table + template wrapper carry the expected class hooks.
"""

import re
from pathlib import Path

import pytest
from django.template import Context
from django.template import Template
from django.template.loader import render_to_string

from courses.models import ChoiceGridQuestionElement
from courses.models import GridColumn
from courses.models import GridRow

ROOT = Path(__file__).resolve().parent.parent
COURSES_CSS = ROOT / "courses/static/courses/css/courses.css"
EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"


def _css():
    source = COURSES_CSS.read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)


def _block_spans(css, at_rule):
    """(start of at_rule, index after its closing brace) for each occurrence."""
    spans, start = [], css.find(at_rule)
    while start != -1:
        i, depth = css.index("{", start) + 1, 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        spans.append((start, i))
        start = css.find(at_rule, i)
    return spans


def _blocks(css, at_rule):
    return [css[start:end] for start, end in _block_spans(css, at_rule)]


def _without_blocks(css, at_rule):
    for start, end in reversed(_block_spans(css, at_rule)):
        css = css[:start] + css[end:]
    return css


def _rules(css):
    """(selector list, body) of every innermost rule."""
    return [
        (selector.strip(), body)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def _rule_body(css, selector):
    bodies = [
        body
        for selectors, body in _rules(css)
        if selector in [s.strip() for s in selectors.split(",")]
    ]
    assert bodies, f"no rule for {selector}"
    return "".join(bodies)


def test_courses_css_defines_choicegrid_student_surface():
    css = COURSES_CSS.read_text(encoding="utf-8")
    for cls in [
        ".choicegrid-scroll",
        ".choicegrid",
        ".choicegrid__stmt",
    ]:
        assert cls in css, f"missing choicegrid student rule: {cls}"
    # Picked buttons use the brand token, not a hardcoded colour.
    assert "var(--primary-subtle)" in css
    assert "table-layout: fixed" in css
    # The whole-cell tint is gone: the button alone carries the pick.
    assert "td:has(input:checked)" not in css


def test_grid_inputs_are_hidden_outside_supports():
    """Grid buttons need no :has() for their picked state, so unlike the option
    cards their inputs are hidden unconditionally."""
    outside = _without_blocks(_css(), "@supports")
    assert "clip: rect(0 0 0 0)" in _rule_body(outside, ".grid-answers input")


@pytest.mark.parametrize(
    "row, token",
    [("tr.is-correct", "var(--success)"), ("tr.is-incorrect", "var(--danger)")],
)
def test_verdict_paint_is_only_the_server_rendered_pick(row, token):
    # Outside forced-colors, which repeats these selectors with system colours.
    css = _without_blocks(_css(), "@media (forced-colors")
    bodies = [
        body
        for selector, body in _rules(css)
        if row in selector and "input[checked]:checked + .gridbtn" in selector
    ]
    assert bodies, f"no verdict rule for {row}"
    assert all(token in body for body in bodies), bodies


def test_gridbtn_hover_lives_inside_hover_media():
    css = _css()
    outside = [s for s, _ in _rules(_without_blocks(css, "@media (hover: hover)"))]
    assert not [s for s in outside if "gridbtn" in s and ":hover" in s]
    inside = "".join(_blocks(css, "@media (hover: hover)"))
    assert [s for s, _ in _rules(inside) if "gridbtn" in s and ":hover" in s]


def test_editor_css_defines_choicegrid_editor_surface():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    for cls in [
        ".choicegrid-cols",
        ".choicegrid-rows",
        ".choicegrid-col",
        ".choicegrid-row",
        ".choicegrid-row__correct",
        ".choicegrid-col__del",
        ".choicegrid-row__del",
        ".choicegrid-editor__col-controls",
    ]:
        assert cls in css, f"missing choicegrid editor rule: {cls}"


@pytest.mark.django_db
def test_rendered_grid_carries_class_hooks():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    GridColumn.objects.create(question=q, label="False")
    GridRow.objects.create(question=q, statement="2+2=4", correct_column=t)
    html = Template("{% load courses_extras %}{% render_choice_grid el %}").render(
        Context({"el": q})
    )
    assert 'class="choicegrid"' in html
    assert 'class="choicegrid__stmt"' in html


@pytest.mark.django_db
def test_student_template_wraps_grid_in_scroll_container():
    """A wide grid must scroll inside its own box, never the page body."""
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    GridRow.objects.create(question=q, statement="a", correct_column=t)
    html = render_to_string(
        "courses/elements/choicegridquestionelement.html", {"el": q}
    )
    assert "choicegrid-scroll" in html
