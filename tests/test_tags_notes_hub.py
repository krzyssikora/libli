import pytest
from django.urls import reverse

from courses.models import Enrollment
from notes import services
from tags import services as tag_services
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import TagFactory
from tests.factories import UnitTagFactory
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


# ---- Task 2: tags_by_course ----


def test_tags_by_course_groups_distinct_tags_accessible_only():
    me = _user(6)
    c1 = CourseFactory(title="Alpha")
    c2 = CourseFactory(title="Beta")
    _enroll(me, c1)
    _enroll(me, c2)
    u1a = _lesson(c1)
    u1b = _lesson(c1)
    u2 = _lesson(c2)
    t1 = TagFactory(author=me, name="exam")
    t2 = TagFactory(author=me, name="hard")
    UnitTagFactory(tag=t1, unit=u1a)
    UnitTagFactory(tag=t1, unit=u1b)  # same tag twice in c1 -> distinct
    UnitTagFactory(tag=t2, unit=u1a)
    UnitTagFactory(tag=t1, unit=u2)
    out = tag_services.tags_by_course(me)
    # exact list (not set) so a dedup regression (e.g. [t1, t1, t2]) fails; order is
    # deterministic by Lower(name): "exam" (t1) < "hard" (t2).
    assert list(out[c1]) == [t1, t2]
    assert list(out[c2]) == [t1]


def test_tags_by_course_excludes_inaccessible_and_other_authors():
    me = _user(7)
    other = _user(8)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    mine = TagFactory(author=me, name="mine")
    theirs = TagFactory(author=other, name="theirs")
    UnitTagFactory(tag=mine, unit=unit)
    UnitTagFactory(tag=theirs, unit=unit)
    inaccessible = _lesson(CourseFactory())  # me not enrolled
    UnitTagFactory(tag=TagFactory(author=me, name="lost"), unit=inaccessible)
    out = tag_services.tags_by_course(me)
    assert list(out[course]) == [mine]
    assert all(c == course for c in out)  # inaccessible course absent


# ---- Task 3: overview page ----


def test_overview_union_sorted_notes_link_and_chip_href(client):
    me = _user(9)
    c_notes = CourseFactory(title="Zed notes-only")
    c_tags = CourseFactory(title="Alpha tags-only")
    c_both = CourseFactory(title="Mid both")
    c_none = CourseFactory(title="None")
    for c in (c_notes, c_tags, c_both, c_none):
        _enroll(me, c)
    services.create_note(me, _lesson(c_notes), None, "n")
    services.create_note(me, _lesson(c_both), None, "n")
    t = TagFactory(author=me, name="exam", color="teal")
    UnitTagFactory(tag=t, unit=_lesson(c_tags))
    UnitTagFactory(tag=TagFactory(author=me, name="k"), unit=_lesson(c_both))
    client.force_login(me)
    resp = client.get(reverse("notes:overview"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # union {notes, tags, both} present, "None" course absent
    assert "Zed notes-only" in body and "Alpha tags-only" in body and "Mid both" in body
    assert reverse("courses:course_outline", args=[c_none.slug]) not in body
    # alphabetical by title: Alpha < Mid < Zed
    assert (
        body.index("Alpha tags-only")
        < body.index("Mid both")
        < body.index("Zed notes-only")
    )
    # notes link only for note-bearing courses
    assert reverse("notes:course_notes", args=[c_notes.slug]) in body
    assert reverse("notes:course_notes", args=[c_tags.slug]) not in body
    # tag chip href = course_outline?tags=<pk>
    tags_outline_url = reverse("courses:course_outline", args=[c_tags.slug])
    assert f"{tags_outline_url}?tags={t.pk}" in body
    # tab bar: By course active
    assert "tnhub__tab" in body and "is-on" in body


def test_overview_empty_state(client):
    me = _user(10)
    client.force_login(me)
    resp = client.get(reverse("notes:overview"))
    assert resp.status_code == 200
    assert "tnhub__card" not in resp.content.decode()


# ---- Task 4: manage tags tab ----


def test_my_tags_renders_hub_tabs_manage_active(client):
    me = _user(11)
    client.force_login(me)
    resp = client.get(reverse("tags:my_tags"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'class="tnhub__tabs"' in body
    assert reverse("notes:overview") in body
    # The active (is-on) tab is Manage tags, linking to my_tags. Locate it by its
    # anchor, not by a bare index of "/tags/" (base.html's nav link to /tags/,
    # renamed in Task 6, would collide with that index).
    import re

    active = re.search(r'<a class="tnhub__tab is-on"[^>]*href="([^"]+)"', body)
    assert active is not None
    assert active.group(1) == reverse("tags:my_tags")


# ---- Task 5: per-course notes index ----


def test_course_notes_access_gate(client):
    me = _user(12)
    course = CourseFactory()  # not enrolled
    unit = _lesson(course)
    services.create_note(me, unit, None, "n")
    client.force_login(me)
    # inaccessible existing course -> 403
    url = reverse("notes:course_notes", args=[course.slug])
    assert client.get(url).status_code == 403
    # nonexistent slug -> 404
    missing_url = reverse("notes:course_notes", args=["nope-xyz"])
    assert client.get(missing_url).status_code == 404
    _enroll(me, course)
    assert client.get(url).status_code == 200


def test_course_notes_shows_own_notes_ordered_with_gotolesson(client):
    me = _user(13)
    course = CourseFactory()
    _enroll(me, course)
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    n = services.create_note(me, unit, el.pk, "MY REVISION NOTE")
    other = _user(14)
    _enroll(other, course)
    services.create_note(other, unit, el.pk, "OTHER NOTE")
    client.force_login(me)
    resp = client.get(reverse("notes:course_notes", args=[course.slug]))
    body = resp.content.decode()
    assert "MY REVISION NOTE" in body
    assert "OTHER NOTE" not in body  # author scoping
    lesson_url = reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    assert f"{lesson_url}?notes=1#note-{n.pk}" in body
    # read-only: no edit/delete controls
    assert "note-action--edit" not in body and "note-action--delete" not in body


def test_course_notes_empty_state(client):
    me = _user(15)
    course = CourseFactory()
    _enroll(me, course)
    _lesson(course)
    client.force_login(me)
    resp = client.get(reverse("notes:course_notes", args=[course.slug]))
    assert resp.status_code == 200
    assert "course-notes__unit" not in resp.content.decode()


# ---- Task 6: entry points ----


def test_nav_has_tags_and_notes_link(client):
    me = _user(16)
    client.force_login(me)
    resp = client.get(reverse("notes:overview"))
    body = resp.content.decode()
    assert reverse("notes:overview") in body
    assert "Tags &amp; notes" in body or "Tags & notes" in body
    # old label gone from nav
    assert 'app-nav__link" href="' + reverse("tags:my_tags") not in body


def test_outline_has_my_notes_link(client):
    me = _user(17)
    course = CourseFactory()
    _enroll(me, course)
    client.force_login(me)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 200
    assert reverse("notes:course_notes", args=[course.slug]) in resp.content.decode()


# ---- Task 7: i18n ----

from django.utils import translation  # noqa: E402


@pytest.mark.parametrize(
    "msgid,expected_pl",
    [
        ("Tags & notes", "Tagi i notatki"),
        ("By course", "Według kursu"),
        ("Manage tags", "Zarządzaj tagami"),
        ("My notes", "Moje notatki"),
        ("Go to lesson", "Przejdź do lekcji"),
        ("No notes in this course yet.", "Brak notatek w tym kursie."),
        ("General", "Ogólne"),
        (
            "You haven't added any notes or tags yet.",
            "Nie masz jeszcze żadnych notatek ani tagów.",
        ),
        # Pre-existing strings the e2e clamp-label test depends on — verify the
        # catalog value:
        ("Show more", "Pokaż więcej"),
        ("Show less", "Pokaż mniej"),
    ],
)
def test_new_strings_have_polish(msgid, expected_pl):
    with translation.override("pl"):
        from django.utils.translation import gettext

        assert gettext(msgid) == expected_pl
