# tests/test_save_multigrid.py
import pytest

from courses.builder import ElementFormInvalid
from courses.builder import save_element
from courses.models import Element
from courses.models import MultiGridQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _make_course_with_unit(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    return course, unit


def _post(unit, cols, rows, **extra):
    """cols: list[(temp_id, label)]; rows: list[(statement, [temp_ids])]."""
    data = {
        "unit_token": unit.updated.isoformat(),
        "unit": str(unit.pk),
        "stem": "Pick the truths",
        "explanation": "",
        "marking_mode": "A",
        "max_attempts": "0",
        "max_marks": "1",
        "columns-TOTAL_FORMS": str(len(cols)),
        "columns-INITIAL_FORMS": "0",
        "columns-MIN_NUM_FORMS": "0",
        "columns-MAX_NUM_FORMS": "1000",
        "rows-TOTAL_FORMS": str(len(rows)),
        "rows-INITIAL_FORMS": "0",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
    }
    for i, (tid, label) in enumerate(cols):
        data[f"columns-{i}-temp_id"] = tid
        data[f"columns-{i}-label"] = label
    for i, (stmt, tids) in enumerate(rows):
        data[f"rows-{i}-statement"] = stmt
        data[f"rows-{i}-correct_temp_ids"] = ",".join(tids)
    data.update(extra)
    return data


def test_save_creates_grid_with_m2m(client):
    course, unit = _make_course_with_unit(client)
    data = _post(
        unit,
        [("t1", "A"), ("t2", "B"), ("t3", "C")],
        [("r1", ["t1", "t3"]), ("r2", ["t2"])],
    )
    save_element(course, unit.pk, "multigridquestion", "new", data, {})
    q = MultiGridQuestionElement.objects.get()
    assert [c.label for c in q.columns.all()] == ["A", "B", "C"]
    r1, r2 = list(q.rows.all())
    assert {c.label for c in r1.correct_columns.all()} == {"A", "C"}
    assert {c.label for c in r2.correct_columns.all()} == {"B"}


def test_save_rejects_row_with_no_correct(client):
    course, unit = _make_course_with_unit(client)
    data = _post(unit, [("t1", "A")], [("r1", [])])
    with pytest.raises(ElementFormInvalid):
        save_element(course, unit.pk, "multigridquestion", "new", data, {})
    assert not MultiGridQuestionElement.objects.exists()  # atomic rollback


def test_edit_row_form_seeds_correct_temp_ids_from_m2m(client):
    # The temp-id linkage is client-only; on edit the row form must seed
    # correct_temp_ids from the saved correct_columns pks (guards the Matrix edit-drop
    # bug, generalised to a set). Column pk == its temp_id.
    from courses.element_forms import _MultiGridRowForm
    from courses.models import MultiGridColumn
    from courses.models import MultiGridRow

    q = MultiGridQuestionElement.objects.create(stem="s")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    MultiGridColumn.objects.create(question=q, label="C")
    row = MultiGridRow.objects.create(question=q, statement="x")
    row.correct_columns.set([a, b])
    initial = _MultiGridRowForm(instance=row).fields["correct_temp_ids"].initial
    assert set(initial.split(",")) == {str(a.pk), str(b.pk)}


def test_edit_delete_a_correct_column_repoints_and_errors_only_when_empty(client):
    # Delete one of a row's two correct columns in one submission -> succeeds, row keeps
    # the other. Delete the row's ONLY correct column -> ElementFormInvalid.
    course, unit = _make_course_with_unit(client)
    data = _post(unit, [("t1", "A"), ("t2", "B")], [("r1", ["t1", "t2"])])
    save_element(course, unit.pk, "multigridquestion", "new", data, {})
    q = MultiGridQuestionElement.objects.get()
    cols = list(q.columns.all())  # [A, B], pk == server temp_id on edit
    row = q.rows.get()
    join = Element.objects.get()
    unit.refresh_from_db()

    def _edit(delete_idx, row_correct):
        d = {
            "unit_token": unit.updated.isoformat(),
            "unit": str(unit.pk),
            "stem": "Pick the truths",
            "explanation": "",
            "marking_mode": "A",
            "max_attempts": "0",
            "max_marks": "1",
            "columns-TOTAL_FORMS": "2",
            "columns-INITIAL_FORMS": "2",
            "columns-MIN_NUM_FORMS": "0",
            "columns-MAX_NUM_FORMS": "1000",
            "columns-0-id": str(cols[0].pk),
            "columns-0-label": "A",
            "columns-0-temp_id": str(cols[0].pk),
            "columns-1-id": str(cols[1].pk),
            "columns-1-label": "B",
            "columns-1-temp_id": str(cols[1].pk),
            "rows-TOTAL_FORMS": "1",
            "rows-INITIAL_FORMS": "1",
            "rows-MIN_NUM_FORMS": "0",
            "rows-MAX_NUM_FORMS": "1000",
            "rows-0-id": str(row.pk),
            "rows-0-statement": "r1",
            "rows-0-correct_temp_ids": ",".join(str(cols[i].pk) for i in row_correct),
        }
        d[f"columns-{delete_idx}-DELETE"] = "on"
        return d

    # delete B (idx 1); row keeps A -> succeeds
    save_element(course, unit.pk, "multigridquestion", str(join.pk), _edit(1, [0]), {})
    q.refresh_from_db()
    assert q.columns.count() == 1
    assert {c.label for c in q.rows.get().correct_columns.all()} == {"A"}

    # now delete the surviving A (idx 0) leaving the row with zero -> invalid
    cols2 = list(q.columns.all())  # [A]
    row2 = q.rows.get()
    unit.refresh_from_db()
    bad = {
        "unit_token": unit.updated.isoformat(),
        "unit": str(unit.pk),
        "stem": "Pick the truths",
        "explanation": "",
        "marking_mode": "A",
        "max_attempts": "0",
        "max_marks": "1",
        "columns-TOTAL_FORMS": "1",
        "columns-INITIAL_FORMS": "1",
        "columns-MIN_NUM_FORMS": "0",
        "columns-MAX_NUM_FORMS": "1000",
        "columns-0-id": str(cols2[0].pk),
        "columns-0-label": "A",
        "columns-0-temp_id": str(cols2[0].pk),
        "columns-0-DELETE": "on",
        "rows-TOTAL_FORMS": "1",
        "rows-INITIAL_FORMS": "1",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
        "rows-0-id": str(row2.pk),
        "rows-0-statement": "r1",
        "rows-0-correct_temp_ids": str(cols2[0].pk),
    }
    with pytest.raises(ElementFormInvalid):
        save_element(course, unit.pk, "multigridquestion", str(join.pk), bad, {})
