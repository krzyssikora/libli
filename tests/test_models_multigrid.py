import pytest
from courses.models import ELEMENT_MODELS
from courses.models import MultiGridQuestionElement, MultiGridColumn, MultiGridRow


def test_multigrid_in_element_models():
    assert "multigridquestionelement" in ELEMENT_MODELS
    assert len(ELEMENT_MODELS) == 28
    assert ELEMENT_MODELS[-1] == "multigridquestionelement"


@pytest.mark.django_db
def test_row_owns_a_set_of_correct_columns():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    c = MultiGridColumn.objects.create(question=q, label="C")
    row = MultiGridRow.objects.create(question=q, statement="row1")
    row.correct_columns.set([a, c])
    assert {col.pk for col in row.correct_columns.all()} == {a.pk, c.pk}
    # deleting a column drops it from the row's set (no PROTECT)
    b_pk = b.pk
    c.delete()
    assert {col.pk for col in row.correct_columns.all()} == {a.pk}
    assert MultiGridColumn.objects.filter(pk=b_pk).exists()
