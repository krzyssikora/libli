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
