"""Style-presence guards for the Matrix (choice-grid) question.

Mirrors tests/test_table_css.py / test_callout_css.py: the CSS classes are wired
to markup only by name (the student table comes from the render_choice_grid tag,
the editor rows from choicegrid.js clones), so nothing but a name match ties them
together. Pin the contract in both the student and editor stylesheets, and prove
the rendered student table + template wrapper carry the expected class hooks.
"""

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


def test_courses_css_defines_choicegrid_student_surface():
    css = COURSES_CSS.read_text(encoding="utf-8")
    for cls in [
        ".choicegrid-scroll",
        ".choicegrid",
        ".choicegrid__stmt",
        ".choicegrid thead th",
    ]:
        assert cls in css, f"missing choicegrid student rule: {cls}"
    # Selected/live cell states must use the brand token + feedback vocabulary,
    # not a hardcoded colour.
    assert "accent-color: var(--primary)" in css
    assert ".choicegrid tbody td:has(input:checked)" in css
    assert "var(--primary-subtle)" in css
    # Reveal reuses the shared answer verdict vocabulary, scoped to the grid.
    assert ".question__reveal--grid" in css


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
