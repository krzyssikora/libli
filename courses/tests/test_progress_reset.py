import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import QuizSubmission
from courses.models import UnitProgress
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _seed(client):
    course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, obj)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    up = UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={str(row.pk): {"items": [1]}},
        seen_element_ids=[row.pk],
        completed=True,
    )
    client.force_login(student)
    return course, unit, student, up


def test_get_renders_the_interstitial_and_writes_nothing(client):
    course, unit, student, _up = _seed(client)
    UnitProgress.objects.filter(student=student, unit=unit).delete()
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    # GET is side-effect free: it must not spawn a row.
    assert not UnitProgress.objects.filter(student=student, unit=unit).exists()


def test_get_count_is_lessons_with_non_empty_state(client):
    course, unit, student, _up = _seed(client)
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.context["affected_count"] == 1


def test_get_count_zero_offers_no_destructive_action(client):
    course, unit, student, up = _seed(client)
    up.element_state = {}
    up.save()
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.context["affected_count"] == 0
    # Assert the BODY, not just the count: the name promises "offers no destructive
    # action", and a count assertion alone passes even if the template renders the
    # destructive form unconditionally.
    body = r.content.decode()
    assert "Nothing to clear here." in body
    # Do NOT assert `'type="submit"' not in body`: base.html emits it unconditionally
    # (the language switcher at :64 and the logout button at :136), so that negative
    # is false of a CORRECT page. `btn--danger` is safe -- it appears only in
    # app.css, never in base.html's markup -- and it already falsifies a template
    # that renders the destructive form unconditionally.
    assert "btn--danger" not in body


def test_post_clears_element_state(client):
    course, unit, student, _up = _seed(client)
    r = client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 302
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {}


def test_reset_does_not_touch_completion(client):
    # HARD INVARIANT. Completion is scroll-driven (an IntersectionObserver, not an act
    # of work) and feeds build_progress_matrix -> teacher analytics. A student revising
    # must not silently drag down what their teacher sees.
    course, unit, student, _up = _seed(client)
    client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.completed is True
    assert up.seen_element_ids != []


def test_reset_does_not_touch_graded_records(client):
    # HARD INVARIANT. Graded assessment history is not the student's to erase.
    course, unit, student, _up = _seed(client)
    sub = QuizSubmission.objects.create(student=student, unit=unit)
    client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert QuizSubmission.objects.filter(pk=sub.pk).exists()


def test_course_level_route_clears_every_unit(client):
    course, unit, student, _up = _seed(client)
    u2 = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="u2",
    )
    UnitProgress.objects.create(student=student, unit=u2, element_state={"9": {"x": 1}})
    r = client.post(reverse("courses:progress_reset_course", args=[course.slug]))
    assert r.status_code == 302
    assert UnitProgress.objects.get(student=student, unit=u2).element_state == {}


def test_reset_at_chapter_level_clears_its_units_only(client):
    # [S1] spec requirement: reset at unit / section / chapter, not just unit+course.
    # units_under's own unit tests are NOT the view -- this drives the real endpoint.
    course, unit, student, _up = _seed(client)
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    inside = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title="inside",
    )
    up_in = UnitProgress.objects.create(
        student=student, unit=inside, element_state={"1": {"items": [1]}}
    )
    r = client.post(reverse("courses:progress_reset", args=[course.slug, ch.pk]))
    assert r.status_code == 302
    up_in.refresh_from_db()
    assert up_in.element_state == {}
    # The top-level unit is OUTSIDE the chapter and must be untouched.
    assert UnitProgress.objects.get(student=student, unit=unit).element_state != {}


def test_reset_at_section_level_descends_to_its_units(client):
    course, _unit, student, _up = _seed(client)
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    sec = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.SECTION, parent=ch, title="s"
    )
    deep = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=sec,
        unit_type=ContentNode.UnitType.LESSON,
        title="deep",
    )
    up_deep = UnitProgress.objects.create(
        student=student, unit=deep, element_state={"1": {"items": [1]}}
    )
    client.post(reverse("courses:progress_reset", args=[course.slug, sec.pk]))
    up_deep.refresh_from_db()
    assert up_deep.element_state == {}


def test_student_a_cannot_reset_student_b(client):
    course, unit, student, _up = _seed(client)
    other = make_verified_user(username="other", email="other@school.edu")
    Enrollment.objects.create(student=other, course=course)
    other_up = UnitProgress.objects.create(
        student=other, unit=unit, element_state={"7": {"items": [1]}}
    )
    client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    other_up.refresh_from_db()
    assert other_up.element_state == {"7": {"items": [1]}}


def test_foreign_course_node_404s(client):
    # can_access_course authorizes against `slug`; NOTHING otherwise ties node_pk to
    # that course. Without get_node_or_404 this wipes state in another course.
    course, _unit, _student, _up = _seed(client)
    _c2, unit2 = make_course_with_unit()
    r = client.post(reverse("courses:progress_reset", args=[course.slug, unit2.pk]))
    assert r.status_code == 404


def test_foreign_next_falls_back_to_the_outline(client):
    course, unit, _student, _up = _seed(client)
    r = client.post(
        reverse("courses:progress_reset", args=[course.slug, unit.pk]),
        data={"next": "https://evil.example.com/x"},
    )
    assert r.status_code == 302
    assert r.url == reverse("courses:course_outline", args=[course.slug])


def test_foreign_next_on_the_GET_does_not_reach_the_cancel_href(client):
    # The GET half of the redirect guard: an unvalidated ?next= would render a
    # libli-hosted page whose Cancel button navigates off-site.
    course, unit, _student, _up = _seed(client)
    r = client.get(
        reverse("courses:progress_reset", args=[course.slug, unit.pk])
        + "?next=https://evil.example.com/x"
    )
    assert r.status_code == 200
    assert "evil.example.com" not in r.content.decode()
    assert r.context["cancel_url"] == reverse(
        "courses:course_outline", args=[course.slug]
    )


def test_local_next_is_honoured(client):
    course, unit, _student, _up = _seed(client)
    target = reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    r = client.post(
        reverse("courses:progress_reset", args=[course.slug, unit.pk]),
        data={"next": target},
    )
    assert r.status_code == 302 and r.url == target


def test_anonymous_is_redirected(client):
    course, unit = make_course_with_unit()
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 302 and "/login" in r.url


def test_stranger_denied(client):
    # PR #136 rule: the destructive endpoint's access gate is can_access_course.
    # An authenticated user who is neither enrolled nor the owner must be denied.
    course, unit, _student, _up = _seed(client)
    stranger = make_verified_user(username="stranger", email="stranger@school.edu")
    client.force_login(stranger)
    r = client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 403


def test_post_clears_done_selfcheck_state_and_lesson_restores_fresh(client):
    """[[student-practice-state-graded-selfchecks-restore]] Start-fresh must clear
    a graded self-check's {"done": true} blob too -- mirrors the MarkDone
    coverage above, extended through the lesson view to prove the WIDGET, not
    just the row, comes back fresh."""
    from courses import switchgrid
    from courses.models import SwitchGridElement

    course, unit = make_course_with_unit()
    token_stem, _n = switchgrid.parse_stem_multi("Pick {{choice}}")
    grid = SwitchGridElement.objects.create(
        prompt="",
        lines=[{"stem": token_stem, "cyclers": [{"options": ["a", "b"], "answer": 1}]}],
    )
    row = add_element(unit, grid)
    student = make_verified_user(username="gsc_reset", email="gsc_reset@school.edu")
    Enrollment.objects.create(student=student, course=course)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"done": True}}
    )
    client.force_login(student)

    r = client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 302
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {}

    body = client.get(
        reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    ).content.decode()
    assert 'data-state="{}"' in body
    assert "switchgrid--locked" not in body
    assert "switchgrid__confirm" in body
    assert "data-switchgrid-cycler" in body  # cycler actually rendered, fresh
