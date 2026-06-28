import pytest

from courses.models import ContentNode
from notes import services
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import make_verified_user

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


from notes.models import NOTE_MAX_LEN  # noqa: E402


def test_create_note_no_js_redirects_prg(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    client.force_login(me)
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": "hello"},
    )
    assert resp.status_code == 302
    assert f"/courses/{course.slug}/u/{unit.pk}/" in resp["Location"]
    assert "notes=1" in resp["Location"]


def test_create_note_fragment_returns_card(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    client.force_login(me)
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": "frag note"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 201
    assert b"frag note" in resp.content


def test_create_note_invalid_no_js_422_repopulates_rejected_text(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    client.force_login(me)
    # over-cap body is rejected; the no-JS re-render must echo the rejected text
    # back into the offending block's composer so the user can fix it.
    rejected = "z" * (NOTE_MAX_LEN + 1)
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": rejected},
    )
    assert resp.status_code == 422
    # the rejected text is repopulated in the composer textarea
    assert rejected.encode() in resp.content
    # nothing persisted
    from notes.models import Note

    assert Note.objects.count() == 0


def test_create_note_inaccessible_course_403(client):
    course = CourseFactory()
    unit = _lesson(course)
    outsider = _stranger("outsider")  # verified, but not enrolled/staff/owner
    client.force_login(outsider)
    resp = client.post(f"/courses/{course.slug}/u/{unit.pk}/notes/add/", {"body": "x"})
    assert resp.status_code == 403


def test_create_note_on_quiz_unit_404(client):
    course = CourseFactory()
    quiz = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.QUIZ,
        title="Q",
    )
    me = _enrolled_user(course)
    client.force_login(me)
    resp = client.post(f"/courses/{course.slug}/u/{quiz.pk}/notes/add/", {"body": "x"})
    assert resp.status_code == 404
