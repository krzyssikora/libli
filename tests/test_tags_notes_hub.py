import pytest

from courses.models import Enrollment
from notes import services
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _user(n=0):
    return make_verified_user(username=f"hub{n}", email=f"hub{n}@test.example.com")


def _enroll(user, course):
    Enrollment.objects.create(student=user, course=course, source="manual")


def _lesson(course, title="U"):
    return ContentNodeFactory(course=course, title=title)  # lesson unit by default


# ---- Task 1: notes services ----


def test_note_counts_by_course_counts_accessible_lessons():
    me = _user(1)
    c1 = CourseFactory(title="Alpha")
    c2 = CourseFactory(title="Beta")
    _enroll(me, c1)
    _enroll(me, c2)
    u1 = _lesson(c1)
    u2 = _lesson(c2)
    services.create_note(me, u1, None, "a")
    services.create_note(me, u1, None, "b")
    services.create_note(me, u2, None, "c")
    counts = services.note_counts_by_course(me)
    assert counts == {c1.pk: 2, c2.pk: 1}


def test_note_counts_by_course_excludes_inaccessible():
    me = _user(2)
    other_course = CourseFactory()  # not enrolled, not owner
    u = _lesson(other_course)
    # service create bypasses access on purpose
    services.create_note(me, u, None, "secret")
    assert services.note_counts_by_course(me) == {}


def test_course_notes_orders_by_element_order_reorder_stable():
    me = _user(3)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    e1 = ElementFactory(unit=unit)
    e2 = ElementFactory(unit=unit)
    assert e1.order < e2.order
    services.create_note(me, unit, e2.pk, "on-e2")
    services.create_note(me, unit, e1.pk, "on-e1")
    rows = services.course_notes(me, course)
    assert len(rows) == 1
    groups = rows[0]["groups"]
    assert [g[0].pk for g in groups] == [e1.pk, e2.pk]  # by Element.order, not creation
    # reorder: make e1 come AFTER e2
    e1.order = e2.order + 5
    e1.save(update_fields=["order"])
    rows = services.course_notes(me, course)
    assert [g[0].pk for g in rows[0]["groups"]] == [e2.pk, e1.pk]


def test_course_notes_unanchored_bucket_last_and_intrablock_order():
    me = _user(4)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    e1 = ElementFactory(unit=unit)
    n1 = services.create_note(me, unit, e1.pk, "first")
    n2 = services.create_note(me, unit, e1.pk, "second")
    services.create_note(me, unit, None, "unanchored")
    groups = services.course_notes(me, course)[0]["groups"]
    assert groups[0][0] == e1
    assert [n.pk for n in groups[0][1]] == [n1.pk, n2.pk]  # created, pk
    assert groups[-1][0] is None
    assert groups[-1][1][0].body == "unanchored"


def test_course_notes_units_in_outline_order_skip_empty():
    me = _user(5)
    course = CourseFactory()
    _enroll(me, course)
    u1 = _lesson(course, "First")
    _u2 = _lesson(course, "Second")  # no notes -> omitted
    u3 = _lesson(course, "Third")
    services.create_note(me, u3, None, "z")
    services.create_note(me, u1, None, "a")
    rows = services.course_notes(me, course)
    assert [r["unit"].pk for r in rows] == [u1.pk, u3.pk]
