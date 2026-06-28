import pytest
from django.http import Http404

from courses.models import ContentNode
from notes import services
from notes.models import NOTE_MAX_LEN
from notes.models import Note
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _lesson(course=None):
    return ContentNode.objects.create(
        course=course or CourseFactory(),
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="U",
    )


def _quiz(course=None):
    return ContentNode.objects.create(
        course=course or CourseFactory(),
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.QUIZ,
        title="Q",
    )


def test_normalize_strips_ends_normalizes_crlf_preserves_interior():
    assert services.normalize_body("  a\r\n\r\n b  ") == "a\n\n b"


def test_create_anchored_note():
    u = _lesson()
    el = ElementFactory(unit=u)
    author = UserFactory()
    note = services.create_note(author, u, el.pk, "hello")
    assert note.author == author and note.unit == u and note.element == el
    assert note.body == "hello"


def test_create_with_none_element_is_unanchored():
    u = _lesson()
    note = services.create_note(UserFactory(), u, None, "x")
    assert note.element is None


def test_create_with_stale_element_pk_falls_back_to_unanchored():
    u = _lesson()
    note = services.create_note(UserFactory(), u, 999999, "x")
    assert note.element is None


def test_create_with_element_from_other_unit_falls_back_to_unanchored():
    u1, u2 = _lesson(), _lesson()
    el_other = ElementFactory(unit=u2)
    note = services.create_note(UserFactory(), u1, el_other.pk, "x")
    assert note.element is None


def test_create_rejects_quiz_unit():
    q = _quiz()
    with pytest.raises(ValueError):
        services.create_note(UserFactory(), q, None, "x")


def test_create_rejects_empty_body():
    u = _lesson()
    with pytest.raises(ValueError):
        services.create_note(UserFactory(), u, None, "   ")


def test_create_rejects_over_cap_body():
    u = _lesson()
    with pytest.raises(ValueError):
        services.create_note(UserFactory(), u, None, "x" * (NOTE_MAX_LEN + 1))


def test_update_is_author_scoped():
    u = _lesson()
    note = services.create_note(UserFactory(), u, None, "x")
    services.update_note(note.author, note.pk, "y")
    note.refresh_from_db()
    assert note.body == "y"
    with pytest.raises(Http404):
        services.update_note(UserFactory(), note.pk, "z")


def test_delete_is_author_scoped():
    u = _lesson()
    note = services.create_note(UserFactory(), u, None, "x")
    with pytest.raises(Http404):
        services.delete_note(UserFactory(), note.pk)
    services.delete_note(note.author, note.pk)
    assert Note.objects.count() == 0
