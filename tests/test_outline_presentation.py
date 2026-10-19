import pytest
from django.urls import reverse

from courses.rollups import _progress_width
from courses.rollups import build_outline
from courses.views import ARC_FLOOR_PCT
from courses.views import _outline_presentation
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_login
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _user(name="stu"):
    return make_verified_user(username=name, email=f"{name}@test.example.com")


def _unit(course, parent=None, order=0, **kw):
    kw.setdefault("unit_type", "lesson")
    return ContentNodeFactory(
        course=course, parent=parent, kind="unit", order=order, **kw
    )


def _part(course, parent=None, order=0):
    return ContentNodeFactory(
        course=course, parent=parent, kind="container", order=order
    )


def _complete(user, *units):
    for u in units:
        UnitProgressFactory(student=user, unit=u, completed=True)


def _find(tree, node):
    for d in tree:
        if d["node"].pk == node.pk:
            return d
        hit = _find(d["children"], node)
        if hit:
            return hit
    return None


def _build(course, user):
    return build_outline(course, user, drafts="hide")


def _resume(unit, state):
    return {"node": unit, "state": state, "ancestors": []}


def test_course_totals_and_width_come_from_the_rollups():
    course = CourseFactory()
    user = _user()
    part = _part(course)
    units = [_unit(course, part, i) for i in range(4)]
    _complete(user, units[0])
    p = _outline_presentation(_build(course, user), None)
    assert (p["course_done"], p["course_total"]) == (1, 4)
    assert p["course_progress_width"] == _progress_width(1, 4)
    assert p["arc_floor_pct"] == ARC_FLOOR_PCT == 9


def test_course_width_is_none_when_nothing_done_and_100_only_when_complete():
    course = CourseFactory()
    user = _user()
    part = _part(course)
    units = [_unit(course, part, i) for i in range(4)]
    p = _outline_presentation(_build(course, user), None)
    assert p["course_progress_width"] is None
    _complete(user, *units)
    p = _outline_presentation(_build(course, user), None)
    assert p["course_progress_width"] == 100


def test_course_width_39_of_40_is_not_100():
    course = CourseFactory()
    user = _user()
    part = _part(course)
    units = [_unit(course, part, i) for i in range(40)]
    _complete(user, *units[:39])
    p = _outline_presentation(_build(course, user), None)
    assert p["course_progress_width"] == _progress_width(39, 40) != 100


def test_cards_are_numbered_over_root_containers_only():
    course = CourseFactory()
    user = _user()
    _unit(course, order=0)
    p1 = _part(course, order=1)
    _unit(course, p1)
    _unit(course, order=2)
    p2 = _part(course, order=3)
    _unit(course, p2)
    tree = _build(course, user)
    p = _outline_presentation(tree, None)
    assert [d.get("card_number") for d in tree] == [None, 1, None, 2]
    assert p["section_count"] == 2


def test_root_units_are_not_numbered_and_can_be_current():
    course = CourseFactory()
    user = _user()
    u0 = _unit(course, order=0)
    p1 = _part(course, order=1)
    _unit(course, p1)
    tree = _build(course, user)
    p = _outline_presentation(tree, _resume(u0, "next"))
    assert p["current_row_pk"] == u0.pk
    assert "card_number" not in tree[0]


@pytest.mark.parametrize(
    "shape", ["under_depth1_container", "depth1_unit", "root_unit"]
)
def test_current_row_pk_for_each_target_shape(shape):
    course = CourseFactory()
    user = _user()
    root_unit = _unit(course, order=0)
    part = _part(course, order=1)
    chapter = _part(course, part, 0)
    deep = _unit(course, chapter, 0)
    d1_unit = _unit(course, part, 1)
    tree = _build(course, user)
    target, expected = {
        "under_depth1_container": (deep, chapter.pk),
        "depth1_unit": (d1_unit, d1_unit.pk),
        "root_unit": (root_unit, root_unit.pk),
    }[shape]
    for state in ("resume", "next", "gap"):
        p = _outline_presentation(tree, _resume(target, state))
        assert p["current_row_pk"] == expected


@pytest.mark.parametrize("state", ["start", None])
def test_no_current_row_in_start_or_without_resume(state):
    course = CourseFactory()
    user = _user()
    part = _part(course)
    u = _unit(course, part)
    tree = _build(course, user)
    resume = _resume(u, state) if state else None
    assert _outline_presentation(tree, resume)["current_row_pk"] is None


def test_container_ring_precedence():
    course = CourseFactory()
    user = _user()
    quiz_part = _part(course, order=0)
    _unit(course, quiz_part, unit_type="quiz")
    done_part = _part(course, order=1)
    done_units = [_unit(course, done_part, i) for i in range(2)]
    big_part = _part(course, order=2)
    big_units = [_unit(course, big_part, i) for i in range(40)]
    idle_part = _part(course, order=3)
    for i in range(2):
        _unit(course, idle_part, i)
    state_part = _part(course, order=4)
    state_units = [_unit(course, state_part, i) for i in range(2)]
    _complete(user, *done_units, big_units[0])
    UnitProgressFactory(
        student=user, unit=state_units[0], element_state={"k": {"v": 1}}
    )
    tree = _build(course, user)
    _outline_presentation(tree, None)
    assert [d["ring"] for d in tree] == [None, "done", "progress", "none", "progress"]


def test_resume_state_current_row_with_nothing_done_is_in_progress():
    course = CourseFactory()
    user = _user()
    part = _part(course)
    chapter = _part(course, part, 0)
    units = [_unit(course, chapter, i) for i in range(2)]
    tree = _build(course, user)
    _outline_presentation(tree, _resume(units[0], "resume"))
    assert _find(tree, chapter)["ring"] == "progress"
    tree = _build(course, user)
    _outline_presentation(tree, _resume(units[0], "next"))
    assert _find(tree, chapter)["ring"] == "none"


def test_done_chapter_with_open_quiz_target_stays_done_and_current():
    course = CourseFactory()
    user = _user()
    part = _part(course)
    chapter = _part(course, part, 0)
    lessons = [_unit(course, chapter, i) for i in range(2)]
    quiz = _unit(course, chapter, 2, unit_type="quiz")
    _complete(user, *lessons)
    tree = _build(course, user)
    p = _outline_presentation(tree, _resume(quiz, "resume"))
    assert _find(tree, chapter)["ring"] == "done"
    assert p["current_row_pk"] == chapter.pk


def test_arc_floor_applies_to_every_in_progress_arc():
    course = CourseFactory()
    user = _user()
    small = _part(course, order=0)
    small_units = [_unit(course, small, i) for i in range(40)]
    half = _part(course, order=1)
    half_units = [_unit(course, half, i) for i in range(40)]
    _complete(user, small_units[0], *half_units[:20])
    tree = _build(course, user)
    _outline_presentation(tree, None)
    assert tree[0]["progress_width"] == _progress_width(1, 40)
    assert tree[0]["arc_pct"] == 9
    assert tree[1]["progress_width"] == _progress_width(20, 40)
    assert tree[1]["arc_pct"] == 50
    assert isinstance(tree[0]["arc_pct"], int)


def test_unit_rings():
    course = CourseFactory()
    user = _user()
    part = _part(course)
    chapter = _part(course, part, 0)
    quiz = _unit(course, part, 1, unit_type="quiz")
    done = _unit(course, part, 2)
    started = _unit(course, part, 3)
    target = _unit(course, chapter, 0)
    other = _unit(course, chapter, 1)
    untyped = _unit(course, chapter, 2, unit_type=None)
    UnitProgressFactory(
        student=user, unit=done, completed=True, element_state={"k": {"v": 1}}
    )
    UnitProgressFactory(student=user, unit=started, element_state={"k": {"v": 1}})
    tree = _build(course, user)
    _outline_presentation(tree, _resume(target, "resume"))
    assert _find(tree, quiz)["ring"] is None
    assert _find(tree, done)["ring"] == "done"
    assert _find(tree, started)["ring"] == "progress"
    assert _find(tree, target)["ring"] == "progress"
    assert _find(tree, other)["ring"] == "none"
    assert _find(tree, untyped)["ring"] == "none"
    tree = _build(course, user)
    _outline_presentation(tree, _resume(target, "next"))
    assert _find(tree, target)["ring"] == "none"


def test_view_puts_the_presentation_keys_in_context(client):
    course = CourseFactory()
    user = make_login(client, "ctxstu")
    EnrollmentFactory(student=user, course=course)
    part = _part(course)
    _unit(course, part)
    r = client.get(reverse("courses:course_outline", kwargs={"slug": course.slug}))
    assert r.status_code == 200
    for key in (
        "course_done",
        "course_total",
        "course_progress_width",
        "section_count",
        "current_row_pk",
        "arc_floor_pct",
    ):
        assert key in r.context
    assert r.context["section_count"] == 1
