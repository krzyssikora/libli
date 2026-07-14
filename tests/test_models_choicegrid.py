import pytest

from courses.models import ELEMENT_MODELS
from courses.models import ChoiceGridQuestionElement
from courses.models import GridColumn
from courses.models import GridRow

pytestmark = pytest.mark.django_db


def test_choicegrid_in_element_models():
    # ELEMENT_MODELS is a list of lowercase MODEL-NAME STRINGS (consumed by
    # Element.content_type limit_choices_to={"model__in": ELEMENT_MODELS}), NOT classes.
    assert "choicegridquestionelement" in ELEMENT_MODELS


def test_grid_relations_and_ordering():
    q = ChoiceGridQuestionElement.objects.create(stem="Pick the truths")
    c_true = GridColumn.objects.create(question=q, label="True")
    c_false = GridColumn.objects.create(question=q, label="False")
    r1 = GridRow.objects.create(question=q, statement="2+2=4", correct_column=c_true)
    r2 = GridRow.objects.create(
        question=q, statement="5 is even", correct_column=c_false
    )
    assert list(q.columns.all()) == [c_true, c_false]
    assert list(q.rows.all()) == [r1, r2]
    assert r1.correct_column_id == c_true.pk


def test_protect_blocks_deleting_referenced_column():
    from django.db.models import ProtectedError

    q = ChoiceGridQuestionElement.objects.create(stem="s")
    c = GridColumn.objects.create(question=q, label="True")
    GridRow.objects.create(question=q, statement="x", correct_column=c)
    with pytest.raises(ProtectedError):
        c.delete()
