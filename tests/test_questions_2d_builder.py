import pytest

from courses import builder
from courses.models import DragBlank, DragFillBlankQuestionElement, Element
from tests.factories import ContentNodeFactory, CourseFactory, make_pa


def _post(unit, **extra):
    base = {"unit_token": unit.updated.isoformat(), "unit": str(unit.pk)}
    base.update(extra)
    return base


@pytest.mark.django_db
def test_save_dragfill_creates_dragblanks(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    builder.save_element(
        course, unit.pk, "dragfillblankquestion", "new",
        _post(unit, stem="A {{Paris}} B {{Madrid}}", distractors="Rome", marking_mode="A"),
        {},
    )
    q = DragFillBlankQuestionElement.objects.get()
    assert [b.correct_token for b in q.dragblanks.all()] == ["Paris", "Madrid"]
    assert Element.objects.filter(content_type__model="dragfillblankquestionelement").count() == 1


@pytest.mark.django_db
def test_edit_dragfill_rebuilds_dragblanks_no_stale(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    builder.save_element(course, unit.pk, "dragfillblankquestion", "new",
                         _post(unit, stem="{{Paris}} {{Madrid}}", distractors=""), {})
    el = Element.objects.get()
    unit.refresh_from_db()
    builder.save_element(course, unit.pk, "dragfillblankquestion", str(el.pk),
                         _post(unit, stem="{{Lisbon}}", distractors=""), {})
    q = DragFillBlankQuestionElement.objects.get()
    assert [b.correct_token for b in q.dragblanks.all()] == ["Lisbon"]  # no stale rows
    assert DragBlank.objects.count() == 1
