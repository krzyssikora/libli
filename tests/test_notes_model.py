import pytest
from django.core.exceptions import ValidationError

from courses.models import ContentNode
from notes.models import NOTE_MAX_LEN
from notes.models import Note
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _lesson_unit(course=None):
    course = course or CourseFactory()
    return ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="U",
    )


def test_note_orders_by_created_then_pk():
    unit = _lesson_unit()
    a = Note.objects.create(author=UserFactory(), unit=unit, body="a")
    b = Note.objects.create(author=a.author, unit=unit, body="b")
    assert list(Note.objects.all()) == [a, b]


def test_deleting_element_sets_note_element_null_preserving_note():
    unit = _lesson_unit()
    el = ElementFactory(unit=unit)
    note = Note.objects.create(author=UserFactory(), unit=unit, element=el, body="x")
    el.delete()
    note.refresh_from_db()
    assert note.element is None
    assert note.unit_id == unit.pk


def test_deleting_unit_cascades_notes():
    unit = _lesson_unit()
    Note.objects.create(author=UserFactory(), unit=unit, body="x")
    unit.delete()
    assert Note.objects.count() == 0


def test_full_clean_rejects_over_cap_body():
    unit = _lesson_unit()
    note = Note(author=UserFactory(), unit=unit, body="x" * (NOTE_MAX_LEN + 1))
    with pytest.raises(ValidationError):
        note.full_clean()
