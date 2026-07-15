# tests/test_render_multigrid.py
import pytest
from django.template import Context, Template
from courses.models import MultiGridQuestionElement, MultiGridColumn, MultiGridRow


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
    html = Template(
        "{% load courses_extras %}{% render_multigrid el %}"
    ).render(Context({"el": q}))
    assert 'type="checkbox"' in html
    assert f'name="row_{r1.pk}"' in html
    assert f'value="{a.pk}"' in html
    assert "checked" not in html  # nothing submitted -> nothing checked


@pytest.mark.django_db
def test_render_multigrid_prechecks_submitted():
    q, (a, b), r1 = _grid()
    html = Template(
        "{% load courses_extras %}{% render_multigrid el sv %}"
    ).render(Context({"el": q, "sv": [[a.pk]]}))
    # the A cell is checked, the B cell is not
    assert f'value="{a.pk}" checked' in html
    assert f'value="{b.pk}" checked' not in html
