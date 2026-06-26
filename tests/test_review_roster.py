from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from courses import review as review_svc
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _review_q(unit, *, max_marks="10"):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Explain.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _auto_q(unit, *, max_marks="2"):
    q = ShortTextQuestionElement.objects.create(
        stem="2+2?",
        accepted="4",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _sub(unit, student, status):
    return QuizSubmission.objects.create(student=student, unit=unit, status=status)


def _enrolled(course, name):
    # display_name=name is REQUIRED: UserFactory defaults display_name to a random
    # Faker("name") (tests/factories.py:54), and the roster labels/sorts by
    # `display_name or username` — without this the name + order assertions below
    # would key off random names and be nondeterministic.
    u = UserFactory(username=name, display_name=name)
    EnrollmentFactory(student=u, course=course)
    return u


def _quiz_unit(course):
    return ContentNodeFactory(course=course, kind="unit", unit_type="quiz")


def test_roster_groups_submitted_in_progress_reviewed(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el = _review_q(unit, max_marks="10")
    ada = _enrolled(course, "ada")
    bob = _enrolled(course, "bob")
    cara = _enrolled(course, "cara")
    s_ada = _sub(unit, ada, QuizSubmission.Status.SUBMITTED)  # to review (unreviewed)
    _sub(unit, bob, QuizSubmission.Status.IN_PROGRESS)  # in progress
    s_cara = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)  # reviewed below
    QuestionResponse.objects.create(
        submission=s_cara,
        element=el,
        earned_marks=Decimal("8.00"),
        fraction=Decimal("0.8000"),
        reviewed_at=timezone.now(),
        locked=True,
    )
    roster = review_svc.roster_for_unit(pa, s_ada)
    groups = {r["display_name"]: r["group"] for r in roster["rows"]}
    assert groups == {"ada": "to_review", "bob": "in_progress", "cara": "reviewed"}
    assert roster["to_review_count"] == 1
    assert roster["in_progress_count"] == 1


def test_roster_reviewed_row_carries_marks(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el = _review_q(unit, max_marks="10")
    cara = _enrolled(course, "cara")
    s = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)
    QuestionResponse.objects.create(
        submission=s,
        element=el,
        earned_marks=Decimal("8.00"),
        fraction=Decimal("0.8000"),
        reviewed_at=timezone.now(),
        locked=True,
    )
    row = review_svc.roster_for_unit(pa, s)["rows"][0]
    assert row["group"] == "reviewed"
    assert row["earned"] == Decimal("8.00")
    assert row["max"] == Decimal("10")
    assert row["auto_marked"] is False


def test_roster_auto_only_quiz_goes_to_reviewed_with_no_marks(client):
    # A quiz with ZERO [R] elements: submission_review_state.fully_reviewed is False
    # (total==0) but it must NOT land in "to review" — route it to Reviewed, labelled
    # auto-marked, with no score (spec §4.2).
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _auto_q(unit, max_marks="2")  # auto only, no [R]
    cara = _enrolled(course, "cara")
    s = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)
    row = review_svc.roster_for_unit(pa, s)["rows"][0]
    assert row["group"] == "reviewed"
    assert row["auto_marked"] is True
    assert row["earned"] is None and row["max"] is None


def test_roster_is_scoped_and_current_flagged(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    other = CourseFactory(owner=UserFactory())
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    s_ada = _sub(unit, ada, QuizSubmission.Status.SUBMITTED)
    # A submission for a DIFFERENT course's unit must never appear.
    outsider = _enrolled(other, "zzz")
    _sub(_quiz_unit(other), outsider, QuizSubmission.Status.SUBMITTED)
    roster = review_svc.roster_for_unit(pa, s_ada)
    names = [r["display_name"] for r in roster["rows"]]
    assert names == ["ada"]
    assert roster["rows"][0]["is_current"] is True


def test_roster_flat_order_is_name_then_pk(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    # Insertion order deliberately NOT alphabetical; expect sorted by lower(name), pk.
    for name in ("Zoe", "amy", "Bob"):
        _sub(unit, _enrolled(course, name), QuizSubmission.Status.SUBMITTED)
    current = QuizSubmission.objects.filter(unit=unit).first()
    rows = review_svc.roster_for_unit(pa, current)["rows"]
    assert [r["display_name"] for r in rows] == ["amy", "Bob", "Zoe"]


def test_neighbours_prev_any_group_next_only_to_review(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    el = _review_q(unit, max_marks="10")
    # Flat order by name: amy(reviewed), bob(to_review), cara(to_review)
    amy = _enrolled(course, "amy")
    bob = _enrolled(course, "bob")
    cara = _enrolled(course, "cara")
    s_amy = _sub(unit, amy, QuizSubmission.Status.SUBMITTED)
    QuestionResponse.objects.create(
        submission=s_amy,
        element=el,
        earned_marks=Decimal("10"),
        fraction=Decimal("1.0000"),
        reviewed_at=timezone.now(),
        locked=True,
    )
    s_bob = _sub(unit, bob, QuizSubmission.Status.SUBMITTED)
    s_cara = _sub(unit, cara, QuizSubmission.Status.SUBMITTED)
    roster = review_svc.roster_for_unit(pa, s_bob)
    nb = review_svc.roster_neighbours(roster, s_bob)
    assert nb["prev"].pk == s_amy.pk  # prev = any group
    assert nb["next_to_review"].pk == s_cara.pk  # next to_review after bob


def test_neighbours_none_at_ends(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    amy = _enrolled(course, "amy")
    s_amy = _sub(unit, amy, QuizSubmission.Status.SUBMITTED)
    roster = review_svc.roster_for_unit(pa, s_amy)
    nb = review_svc.roster_neighbours(roster, s_amy)
    assert nb["prev"] is None  # first row
    assert nb["next_to_review"] is None  # no other to_review after it


def test_review_page_404s_for_in_progress_submission(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    s = _sub(unit, ada, QuizSubmission.Status.IN_PROGRESS)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": s.pk},
    )
    assert client.get(url).status_code == 404


def test_review_page_200_for_submitted(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    s = _sub(unit, ada, QuizSubmission.Status.SUBMITTED)
    url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": s.pk},
    )
    assert client.get(url).status_code == 200


def test_force_submit_redirects_to_review_when_review_pk_given(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    bob = _enrolled(course, "bob")
    in_prog = _sub(unit, ada, QuizSubmission.Status.IN_PROGRESS)
    current = _sub(unit, bob, QuizSubmission.Status.SUBMITTED)  # the page we came from
    url = reverse(
        "courses:manage_review_force_submit",
        kwargs={"slug": course.slug, "submission_pk": in_prog.pk},
    )
    resp = client.post(url, {"review_pk": current.pk})
    assert resp.status_code == 302
    assert resp.url == reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": current.pk},
    )
    # message still emitted (public API, not the private _messages attr)
    from django.contrib.messages import get_messages

    msgs = [str(m).lower() for m in get_messages(resp.wsgi_request)]
    assert any("submitted for" in m for m in msgs)
    in_prog.refresh_from_db()
    assert in_prog.status == QuizSubmission.Status.SUBMITTED


def test_force_submit_falls_back_to_queue_without_review_pk(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = _quiz_unit(course)
    _review_q(unit)
    ada = _enrolled(course, "ada")
    in_prog = _sub(unit, ada, QuizSubmission.Status.IN_PROGRESS)
    url = reverse(
        "courses:manage_review_force_submit",
        kwargs={"slug": course.slug, "submission_pk": in_prog.pk},
    )
    resp = client.post(url, {})
    assert resp.status_code == 302
    assert resp.url == reverse(
        "courses:manage_review_queue", kwargs={"slug": course.slug}
    )
