import pytest

from courses.models import ContentNode
from notes import services
from tests.factories import CourseFactory, ElementFactory, make_verified_user


pytestmark = pytest.mark.django_db


def _lesson(course=None):
    return ContentNode.objects.create(
        course=course or CourseFactory(),
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="U",
    )


def _stranger(username):
    # A verified user who can log in but has no access to / ownership of any note.
    # MUST be verified (mandatory email verification) AND created so force_login works:
    # a bare UserFactory()+force_login 302s to /accounts/login/ because UserFactory
    # uses skip_postgeneration_save (the hashed password the session stores never
    # matches the persisted one). make_verified_user avoids both traps.
    return make_verified_user(username=username, email=f"{username}@test.example.com")


def _enrolled_user(course):
    # Same verification/force_login requirement as _stranger, plus an enrollment.
    from courses.models import Enrollment

    n = (
        Enrollment.objects.count()
    )  # unique within a test (each call enrolls before next)
    user = make_verified_user(
        username=f"learner{n}", email=f"learner{n}@test.example.com"
    )
    Enrollment.objects.create(student=user, course=course, source="manual")
    return user


def test_lesson_page_shows_own_notes_not_others(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    services.create_note(me, unit, el.pk, "MY SECRET NOTE")
    other = _enrolled_user(course)
    services.create_note(other, unit, el.pk, "OTHER NOTE")
    client.force_login(me)
    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")
    assert resp.status_code == 200
    assert b"MY SECRET NOTE" in resp.content
    assert b"OTHER NOTE" not in resp.content


def test_lesson_page_shows_unanchored_area(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    services.create_note(me, unit, None, "ORPHAN NOTE")
    client.force_login(me)
    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")
    assert b"ORPHAN NOTE" in resp.content
