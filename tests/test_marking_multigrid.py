import pytest
from django.http import QueryDict
from courses.models import MultiGridQuestionElement, MultiGridColumn, MultiGridRow


def _grid():
    q = MultiGridQuestionElement.objects.create(stem="s", max_marks="1")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    c = MultiGridColumn.objects.create(question=q, label="C")
    r1 = MultiGridRow.objects.create(question=q, statement="r1")
    r1.correct_columns.set([a, c])
    r2 = MultiGridRow.objects.create(question=q, statement="r2")
    r2.correct_columns.set([b])
    return q, (a, b, c), (r1, r2)


@pytest.mark.django_db
def test_build_answer_reads_getlist_and_sorts():
    q, (a, b, c), (r1, r2) = _grid()
    post = QueryDict(mutable=True)
    post.update({})
    post.setlist(f"row_{r1.pk}", [str(c.pk), str(a.pk)])  # unsorted
    post.setlist(f"row_{r2.pk}", [])  # untouched
    ans = q.build_answer(post)
    assert ans == [[a.pk, c.pk], []]  # sorted, [] for untouched


@pytest.mark.django_db
def test_build_answer_drops_forged_ids():
    q, (a, b, c), (r1, r2) = _grid()
    post = QueryDict(mutable=True)
    post.setlist(f"row_{r1.pk}", [str(a.pk), "999999", "notanint"])
    ans = q.build_answer(post)
    assert ans[0] == [a.pk]


@pytest.mark.django_db
def test_mark_all_or_nothing_per_row():
    q, (a, b, c), (r1, r2) = _grid()
    # r1 exact, r2 exact -> fully correct
    res = q.mark([[a.pk, c.pk], [b.pk]])
    assert res.correct is True
    assert res.fraction == 1.0
    # r1 partial (missing c) -> row 0, r2 exact -> 1/2
    res = q.mark([[a.pk], [b.pk]])
    assert res.correct is False
    assert res.fraction == 0.5
    # r1 over-selected -> 0 for that row
    res = q.mark([[a.pk, b.pk, c.pk], [b.pk]])
    assert res.fraction == 0.5


@pytest.mark.django_db
def test_mark_empty_grid_is_zero():
    q, (a, b, c), (r1, r2) = _grid()
    res = q.mark([[], []])
    assert res.correct is False
    assert res.fraction == 0.0


@pytest.mark.django_db
def test_mark_reveal_labels_in_column_order():
    q, (a, b, c), (r1, r2) = _grid()
    res = q.mark([[c.pk, a.pk], []])
    item = res.reveal[0]
    assert item["statement"] == "r1"
    assert item["correct_labels"] == ["A", "C"]  # column order, not set order
    assert item["chosen_labels"] == ["A", "C"]
    assert item["is_correct"] is True


@pytest.mark.django_db
def test_mark_defends_against_type_and_length_drift():
    q, (a, b, c), (r1, r2) = _grid()
    # scalar / None entries coerced to []; short answer padded
    res = q.mark([None])  # too short + wrong type
    assert res.fraction == 0.0  # neither row correct, no crash
