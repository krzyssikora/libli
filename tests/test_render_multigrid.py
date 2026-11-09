# tests/test_render_multigrid.py
from types import SimpleNamespace

import pytest
from django.template import Context
from django.template import Template

from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow


def _grid():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    r1 = MultiGridRow.objects.create(question=q, statement="r1")
    r1.correct_columns.set([a])
    return q, (a, b), r1


@pytest.mark.django_db
def test_render_multigrid_checkboxes_and_names():
    q, (a, b), r1 = _grid()
    html = Template("{% load courses_extras %}{% render_multigrid el %}").render(
        Context({"el": q})
    )
    assert 'type="checkbox"' in html
    assert f'name="row_{r1.pk}"' in html
    assert f'value="{a.pk}"' in html
    assert "checked" not in html  # nothing submitted -> nothing checked


@pytest.mark.django_db
def test_render_multigrid_prechecks_submitted():
    q, (a, b), r1 = _grid()
    html = Template("{% load courses_extras %}{% render_multigrid el sv %}").render(
        Context({"el": q, "sv": [[a.pk]]})
    )
    # the A cell is checked, the B cell is not
    assert f'value="{a.pk}" checked' in html
    assert f'value="{b.pk}" checked' not in html


def _mg(el, sv=None, verdicts=None, copy=""):
    return Template(
        "{% load courses_extras %}{% render_multigrid el sv verdicts copy %}"
    ).render(Context({"el": el, "sv": sv, "verdicts": verdicts, "copy": copy}))


@pytest.mark.django_db
def test_no_header_and_label_in_every_button():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    MultiGridColumn.objects.create(question=q, label="A & B")
    MultiGridRow.objects.create(question=q, statement="r1")
    MultiGridRow.objects.create(question=q, statement="r2")
    html = _mg(q)
    assert "<thead" not in html
    assert html.count('class="gridbtn">A &amp; B</span>') == 2


@pytest.mark.django_db
def test_inputs_unchanged():
    q, (a, b), r1 = _grid()
    html = _mg(q, [[a.pk]])
    assert f'name="row_{r1.pk}" value="{a.pk}" checked' in html


@pytest.mark.django_db
def test_group_named_by_statement():
    q, (a, b), r1 = _grid()
    html = _mg(q)
    assert f'id="multigrid-stmt-{r1.pk}"' in html
    assert f'role="group" aria-labelledby="multigrid-stmt-{r1.pk}"' in html
    assert '<span class="grid-stmt-text">r1</span>' in html


@pytest.mark.django_db
def test_grid_types_with_equal_row_pks_have_distinct_ids():
    from courses.models import ChoiceGridQuestionElement
    from courses.models import GridColumn
    from courses.models import GridRow

    cq = ChoiceGridQuestionElement.objects.create(stem="s")
    gc = GridColumn.objects.create(question=cq, label="T")
    gr = GridRow.objects.create(pk=777, question=cq, statement="x", correct_column=gc)
    mq = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    MultiGridColumn.objects.create(question=mq, label="T")
    MultiGridRow.objects.create(pk=gr.pk, question=mq, statement="x")
    a = Template("{% load courses_extras %}{% render_choice_grid el %}").render(
        Context({"el": cq})
    )
    b = _mg(mq)
    assert f"choicegrid-stmt-{gr.pk}" in a and f"multigrid-stmt-{gr.pk}" in b


@pytest.mark.django_db
def test_verdict_glyph_only_on_painted_rows():
    q, (a, b), r1 = _grid()
    r2 = MultiGridRow.objects.create(question=q, statement="r2")
    r2.correct_columns.set([b])
    html = _mg(q, [[b.pk], []], [False, None])
    assert html.count('class="grid-verdict"') == 1
    assert "✗" in html
    assert "✓" not in html


@pytest.mark.django_db
def test_key_copy_suffixes_ids():
    from courses.keycopy import neutralise_key_copy

    q, (a, b), r1 = _grid()
    key = neutralise_key_copy(_mg(q, copy="key"))
    assert f'id="multigrid-stmt-{r1.pk}-key"' in key
    assert f'aria-labelledby="multigrid-stmt-{r1.pk}-key"' in key
    assert 'name="row_' not in key


@pytest.mark.django_db
@pytest.mark.parametrize(
    "extra",
    [{"mode": "results"}, {"mode": "lesson", "element": SimpleNamespace(pk=1)}],
    ids=["results", "lesson"],
)
def test_multigrid_hint_once_with_key_copy(extra):
    from django.template.loader import render_to_string

    q, (a, _b), _r1 = _grid()
    body = render_to_string(
        "courses/elements/multigridquestionelement.html",
        {
            "el": q,
            "key_copy_html": q.render_key_copy([[a.pk]]),
            "submitted_values": None,
            **extra,
        },
    )
    assert "data-answer-key" in body
    assert body.count("question__hint") == 1


@pytest.mark.django_db
def test_empty_grid_renders():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    html = _mg(q)
    assert "<tbody></tbody>" in html and "gridbtn" not in html
    MultiGridRow.objects.create(question=q, statement="lonely")
    html = _mg(q)
    assert "lonely" in html
    assert "grid-answers" not in html and 'role="group"' not in html
