import pytest

from courses.builder import ElementFormInvalid
from courses.builder import save_element
from courses.models import ChoiceGridQuestionElement
from courses.models import Element
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _post(unit, **extra):
    # Mirror the wire shape the editor posts: management-form counts + column/row rows.
    data = {
        "unit_token": unit.updated.isoformat(),
        "unit": str(unit.pk),
        "stem": "Pick the truths",
        "explanation": "",
        "marking_mode": "A",  # MarkingMode.AUTO == "A" (single char), NOT "AUTO"
        "max_attempts": "0",
        "max_marks": "1",
        # columns formset
        "columns-TOTAL_FORMS": "2",
        "columns-INITIAL_FORMS": "0",
        "columns-MIN_NUM_FORMS": "0",
        "columns-MAX_NUM_FORMS": "1000",
        "columns-0-label": "True",
        "columns-0-temp_id": "c1",
        "columns-1-label": "False",
        "columns-1-temp_id": "c2",
        # rows formset
        "rows-TOTAL_FORMS": "2",
        "rows-INITIAL_FORMS": "0",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
        "rows-0-statement": "2+2=4",
        "rows-0-correct_temp_id": "c1",
        "rows-1-statement": "5 is even",
        "rows-1-correct_temp_id": "c2",
    }
    data.update(extra)
    return data


def _make_course_with_unit(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    return course, unit


def test_create_resolves_temp_ids(client):
    course, unit = _make_course_with_unit(client)
    save_element(course, unit.pk, "choicegridquestion", "new", _post(unit), {})
    q = ChoiceGridQuestionElement.objects.get()
    assert [c.label for c in q.columns.all()] == ["True", "False"]
    rows = list(q.rows.all())
    assert rows[0].correct_column.label == "True"
    assert rows[1].correct_column.label == "False"


def test_row_pointing_at_unknown_temp_id_is_422(client):
    course, unit = _make_course_with_unit(client)
    bad = _post(unit)
    bad["rows-1-correct_temp_id"] = "nope"
    with pytest.raises(ElementFormInvalid):
        save_element(course, unit.pk, "choicegridquestion", "new", bad, {})
    assert not ChoiceGridQuestionElement.objects.exists()  # atomic rollback


def test_edit_delete_column_and_repoint_same_submission(client):
    # Create a True/False grid, then in ONE edit submission delete the "False" column
    # and re-point its row onto "True". Must succeed (PROTECT ordering: rows re-pointed
    # BEFORE the column is deleted), not raise ProtectedError.
    course, unit = _make_course_with_unit(client)
    save_element(course, unit.pk, "choicegridquestion", "new", _post(unit), {})
    q = ChoiceGridQuestionElement.objects.get()
    cols = list(q.columns.all())  # [True(c1), False(c2)]
    rows = list(q.rows.all())  # row2 -> False(c2)
    join = Element.objects.get()  # the Element join row (element_ref for edit)
    unit.refresh_from_db()
    edit = {
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
        "columns-0-label": "True",
        "columns-0-temp_id": "c1",
        "columns-1-id": str(cols[1].pk),
        "columns-1-label": "False",
        "columns-1-temp_id": "c2",
        "columns-1-DELETE": "on",  # delete the False column
        "rows-TOTAL_FORMS": "2",
        "rows-INITIAL_FORMS": "2",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
        "rows-0-id": str(rows[0].pk),
        "rows-0-statement": "2+2=4",
        "rows-0-correct_temp_id": "c1",
        "rows-1-id": str(rows[1].pk),
        "rows-1-statement": "5 is even",
        "rows-1-correct_temp_id": "c1",  # re-pointed onto the surviving column
    }
    save_element(course, unit.pk, "choicegridquestion", str(join.pk), edit, {})
    q.refresh_from_db()
    assert q.columns.count() == 1
    assert all(r.correct_column.label == "True" for r in q.rows.all())


def test_edit_forms_seed_temp_ids_from_pk(client):
    # The temp-id column<->row linkage is client-only and NOT persisted; on an edit GET
    # the forms must seed temp_id from the column pk and correct_temp_id from the saved
    # correct_column_id so the selection survives the round-trip.
    from courses.element_forms import _GridColumnForm
    from courses.element_forms import _GridRowForm
    from courses.models import GridColumn
    from courses.models import GridRow

    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    GridColumn.objects.create(question=q, label="False")
    r = GridRow.objects.create(question=q, statement="x", correct_column=t)

    assert _GridColumnForm(instance=t).fields["temp_id"].initial == str(t.pk)
    assert _GridRowForm(instance=r).fields["correct_temp_id"].initial == str(t.pk)


def test_edit_unchanged_preserves_correct_columns(client):
    # A no-op edit posting the pk-based temp-ids the edit form now renders must preserve
    # every row's correct_column — proving the linkage reconstructs on the edit path.
    course, unit = _make_course_with_unit(client)
    save_element(course, unit.pk, "choicegridquestion", "new", _post(unit), {})
    q = ChoiceGridQuestionElement.objects.get()
    cols = list(q.columns.all())
    rows = list(q.rows.all())
    join = Element.objects.get()
    unit.refresh_from_db()
    edit = {
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
        "columns-0-label": "True",
        "columns-0-temp_id": str(cols[0].pk),
        "columns-1-id": str(cols[1].pk),
        "columns-1-label": "False",
        "columns-1-temp_id": str(cols[1].pk),
        "rows-TOTAL_FORMS": "2",
        "rows-INITIAL_FORMS": "2",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
        "rows-0-id": str(rows[0].pk),
        "rows-0-statement": "2+2=4",
        "rows-0-correct_temp_id": str(cols[0].pk),
        "rows-1-id": str(rows[1].pk),
        "rows-1-statement": "5 is even",
        "rows-1-correct_temp_id": str(cols[1].pk),
    }
    save_element(course, unit.pk, "choicegridquestion", str(join.pk), edit, {})
    q.refresh_from_db()
    rows2 = list(q.rows.all())
    assert rows2[0].correct_column.label == "True"
    assert rows2[1].correct_column.label == "False"
