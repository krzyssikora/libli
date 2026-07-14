# tests/test_marking_choicegrid.py
import pytest
from django.http import QueryDict

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


def _post(**pairs):
    qd = QueryDict(mutable=True)
    for k, v in pairs.items():
        qd[k] = str(v)
    return qd


def test_build_answer_positional_with_blank_sentinel():
    q, t, f, r1, r2 = _grid()
    # answer row1 correctly, leave row2 blank
    ans = q.build_answer(_post(**{f"row_{r1.pk}": t.pk}))
    assert ans == [t.pk, ""]  # positional, blank sentinel is ""


def test_build_answer_drops_foreign_col():
    q, t, f, r1, r2 = _grid()
    ans = q.build_answer(_post(**{f"row_{r1.pk}": 999999, f"row_{r2.pk}": f.pk}))
    assert ans == ["", f.pk]  # forged col dropped -> ""


def test_mark_all_correct():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk, f.pk])
    assert mr.correct is True and mr.fraction == 1.0


def test_mark_partial():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk, t.pk])  # row2 wrong
    assert mr.correct is False and mr.fraction == 0.5


def test_mark_empty_all_wrong():
    q, t, f, r1, r2 = _grid()
    mr = q.mark(["", ""])
    assert mr.fraction == 0.0 and mr.correct is False


def test_mark_pads_short_stored_answer_no_indexerror():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk])  # a stale stored answer shorter than #rows
    assert mr.fraction == 0.5  # row2 padded to "" -> wrong, no IndexError


def test_reveal_shape():
    q, t, f, r1, r2 = _grid()
    mr = q.mark([t.pk, t.pk])
    rev = list(mr.reveal)
    assert rev[0]["is_correct"] is True and rev[0]["correct_label"] == "True"
    assert rev[1]["is_correct"] is False and rev[1]["correct_label"] == "False"
    assert rev[1]["chosen_label"] == "True"
