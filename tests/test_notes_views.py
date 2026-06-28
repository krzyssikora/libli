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


def test_edit_get_renders_standalone_form(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "before")
    client.force_login(me)
    resp = client.get(f"/notes/{note.pk}/edit/")
    assert resp.status_code == 200
    assert b"before" in resp.content


def test_edit_foreign_note_404(client):
    course = CourseFactory()
    unit = _lesson(course)
    note = services.create_note(_enrolled_user(course), unit, None, "x")
    client.force_login(_stranger("stranger_edit"))
    assert client.get(f"/notes/{note.pk}/edit/").status_code == 404
    assert client.post(f"/notes/{note.pk}/edit/", {"body": "y"}).status_code == 404


def test_edit_post_valid_redirects_to_lesson(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "before")
    client.force_login(me)
    resp = client.post(f"/notes/{note.pk}/edit/", {"body": "after"})
    assert resp.status_code == 302
    note.refresh_from_db()
    assert note.body == "after"


def test_edit_post_invalid_no_js_rerenders_standalone_with_rejected_text(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "before")
    client.force_login(me)
    resp = client.post(f"/notes/{note.pk}/edit/", {"body": "   "})
    assert resp.status_code == 422
    # standalone edit page re-rendered; the note was NOT changed
    note.refresh_from_db()
    assert note.body == "before"
    # the edit form (posting back to note_edit) is present so the user can retry
    assert f"/notes/{note.pk}/edit/".encode() in resp.content


def test_delete_get_shows_confirm_then_post_deletes(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "x")
    client.force_login(me)
    assert client.get(f"/notes/{note.pk}/delete/").status_code == 200
    resp = client.post(f"/notes/{note.pk}/delete/")
    assert resp.status_code == 302
    from notes.models import Note

    assert not Note.objects.filter(pk=note.pk).exists()


def test_delete_foreign_note_404(client):
    course = CourseFactory()
    unit = _lesson(course)
    note = services.create_note(_enrolled_user(course), unit, None, "x")
    client.force_login(_stranger("stranger_delete"))
    assert client.post(f"/notes/{note.pk}/delete/").status_code == 404


def test_outline_shows_note_badge_with_count_and_notes_link(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    services.create_note(me, unit, None, "a")
    services.create_note(me, unit, None, "b")
    client.force_login(me)
    resp = client.get(f"/courses/{course.slug}/")
    assert resp.status_code == 200
    assert b"badge--notes" in resp.content
    assert b"notes=1" in resp.content
    # Badge must be a sibling of the unit <a>, not nested inside it.
    # The unit link closes with </a> before the badge appears.
    content = resp.content.decode()
    badge_pos = content.find("badge--notes")
    unit_link_close = content.find("</a>", content.find("outline-unit"))
    assert badge_pos > unit_link_close, (
        "badge--notes appears inside the unit <a> (nested anchors) — "
        "expected it after the unit link's </a>"
    )
