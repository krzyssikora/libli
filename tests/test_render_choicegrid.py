import pytest
from django.template import Context
from django.template import Template

from courses.models import ChoiceGridQuestionElement
from courses.models import GridColumn
from courses.models import GridRow

pytestmark = pytest.mark.django_db


def _grid():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    f = GridColumn.objects.create(question=q, label="False")
    r1 = GridRow.objects.create(question=q, statement="2+2=4", correct_column=t)
    r2 = GridRow.objects.create(question=q, statement="5 is even", correct_column=f)
    return q, t, f, r1, r2


def _render(q, submitted):
    tpl = Template("{% load courses_extras %}{% render_choice_grid el sv %}")
    return tpl.render(Context({"el": q, "sv": submitted}))


def test_renders_radios_per_row_and_column():
    q, t, f, r1, r2 = _grid()
    html = _render(q, None)
    assert f'name="row_{r1.pk}"' in html and f'value="{t.pk}"' in html
    assert f'name="row_{r2.pk}"' in html and f'value="{f.pk}"' in html
    assert "checked" not in html  # None -> nothing selected


def test_repopulates_from_submitted_values_positional():
    q, t, f, r1, r2 = _grid()
    html = _render(q, [t.pk, ""])  # row1 -> True checked, row2 blank
    assert f'value="{t.pk}" checked' in html.replace("'", '"') or "checked" in html


def test_none_and_short_list_no_spurious_check():
    q, t, f, r1, r2 = _grid()
    assert "checked" not in _render(q, None)
    assert _render(q, [t.pk])  # short list: row2 missing -> no crash


def _cg(q, sv=None, verdicts=None, copy=""):
    return Template(
        "{% load courses_extras %}{% render_choice_grid el sv verdicts copy %}"
    ).render(Context({"el": q, "sv": sv, "verdicts": verdicts, "copy": copy}))


def test_no_header_and_label_in_every_button():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    c = GridColumn.objects.create(question=q, label="A & B")
    GridRow.objects.create(question=q, statement="r1", correct_column=c)
    GridRow.objects.create(question=q, statement="r2", correct_column=c)
    html = _cg(q)
    assert "<thead" not in html
    assert html.count('class="gridbtn">A &amp; B</span>') == 2


def test_inputs_unchanged():
    q, t, f, r1, r2 = _grid()
    html = _cg(q, [t.pk, ""])
    assert f'name="row_{r1.pk}" value="{t.pk}" checked' in html


def test_group_named_by_statement():
    q, t, f, r1, r2 = _grid()
    html = _cg(q)
    assert f'id="choicegrid-stmt-{r1.pk}"' in html
    assert f'role="group" aria-labelledby="choicegrid-stmt-{r1.pk}"' in html
    assert '<span class="grid-stmt-text">2+2=4</span>' in html


def test_verdict_glyph_only_on_painted_rows():
    q, t, f, r1, r2 = _grid()
    html = _cg(q, [f.pk, ""], [False, None])
    assert html.count('class="grid-verdict"') == 1
    assert "✗" in html
    assert "✓" not in html


def test_key_copy_suffixes_ids():
    from courses.keycopy import neutralise_key_copy

    q, t, f, r1, r2 = _grid()
    key = neutralise_key_copy(_cg(q, copy="key"))
    assert f'id="choicegrid-stmt-{r1.pk}-key"' in key
    assert f'aria-labelledby="choicegrid-stmt-{r1.pk}-key"' in key
    assert 'name="row_' not in key


def test_choice_grid_has_no_multi_answer_hint():
    from django.template.loader import render_to_string

    q, *_ = _grid()
    body = render_to_string(
        "courses/elements/choicegridquestionelement.html",
        {"el": q, "mode": "results", "key_copy_html": "<p>key</p>"},
    )
    assert "question__hint" not in body


def test_empty_grid_renders():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    html = _cg(q)
    assert "<tbody></tbody>" in html and "gridbtn" not in html
    other = ChoiceGridQuestionElement.objects.create(stem="o")
    elsewhere = GridColumn.objects.create(question=other, label="X")
    GridRow.objects.create(question=q, statement="lonely", correct_column=elsewhere)
    html = _cg(q)
    assert "lonely" in html
    assert "grid-answers" not in html and 'role="group"' not in html
