from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

PASSWORD = "Sup3r!pass9"


@pytest.mark.django_db
def test_my_courses_lists_only_enrollments(client):
    user = make_login(client, "stu")
    mine = CourseFactory(title="Mine")
    CourseFactory(title="NotMine")
    EnrollmentFactory(student=user, course=mine)
    resp = client.get(reverse("courses:my_courses"))
    assert resp.status_code == 200
    assert "Mine" in resp.content.decode()
    assert "NotMine" not in resp.content.decode()


@pytest.mark.django_db
def test_outline_403_for_non_enrolled(client):
    make_login(client, "stranger")
    course = CourseFactory(slug="c1")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    resp = client.get(reverse("courses:course_outline", kwargs={"slug": "c1"}))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_outline_renders_for_enrolled(client):
    user = make_login(client, "stu2")
    course = CourseFactory(slug="c2")
    EnrollmentFactory(student=user, course=course)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="Lesson A")
    resp = client.get(reverse("courses:course_outline", kwargs={"slug": "c2"}))
    assert resp.status_code == 200
    assert "Lesson A" in resp.content.decode()


@pytest.mark.django_db
def test_lesson_unit_renders_elements_in_order(client):
    from courses.models import Element
    from courses.models import TextElement

    user = make_login(client, "reader")
    course = CourseFactory(slug="lc")
    EnrollmentFactory(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    t1 = TextElement.objects.create(body="<p>First</p>")
    t2 = TextElement.objects.create(body="<p>Second</p>")
    Element.objects.create(unit=unit, content_object=t1)
    Element.objects.create(unit=unit, content_object=t2)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "lc", "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "First" in body and "Second" in body
    assert body.index("First") < body.index("Second")
    assert 'data-element-id="' in body


@pytest.mark.django_db
def test_lesson_route_404_on_slug_mismatch_idor(client):
    user = make_login(client, "idor")
    a = CourseFactory(slug="a")
    b = CourseFactory(slug="b")
    EnrollmentFactory(student=user, course=a)
    b_unit = ContentNodeFactory(course=b, kind="unit", unit_type="lesson")
    # pair a slug the user CAN access with b's node -> 404, not 403
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "a", "node_pk": b_unit.pk})
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_lesson_unit_redirects_quiz_to_quiz_view(client):
    user = make_login(client, "quizreader")
    course = CourseFactory(slug="qc")
    EnrollmentFactory(student=user, course=course)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "qc", "node_pk": quiz.pk})
    )
    assert resp.status_code == 302
    assert resp.url.endswith("/quiz/")


@pytest.mark.django_db
def test_outline_quiz_link_reaches_live_quiz(client):
    """End-to-end: following the outline link (lesson_unit URL) for a quiz unit
    ultimately reaches the live quiz page (not a placeholder), proving the
    entry-point gap cannot silently reappear."""
    user = make_login(client, "navstu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Q?", accepted="A")
    add_element(unit, q)
    outline_url = reverse(
        "courses:lesson_unit",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk},
    )
    resp = client.get(outline_url, follow=True)
    assert resp.status_code == 200
    assert b"Finish quiz" in resp.content


# ---------------------------------------------------------------------------
# course_results view tests (Task 4)
# ---------------------------------------------------------------------------


def _quiz_with_auto_q(course, max_marks=Decimal("10")):
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None)
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=max_marks
    )
    Element.objects.create(unit=unit, content_object=q)
    return unit


@pytest.mark.django_db
def test_course_results_requires_login(client):
    course = CourseFactory()
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 302
    assert "login" in resp.url


@pytest.mark.django_db
def test_course_results_403_for_outsider(client):
    course = CourseFactory()  # owner None, not open
    make_login(client, "outsider")  # not enrolled, not staff, not owner
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_course_results_staff_preview_empty(client):
    course = CourseFactory()
    user = make_login(client, "staff1")
    user.is_staff = True
    user.save()
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 200
    assert "0 / 0" in resp.content.decode()


@pytest.mark.django_db
def test_course_results_enrolled_renders_rows_and_drilldown(client):
    course = CourseFactory()
    user = make_login(client, "stud")
    EnrollmentFactory(student=user, course=course)
    unit = _quiz_with_auto_q(course)
    QuizSubmissionFactory(
        student=user,
        unit=unit,
        status="submitted",
        score=Decimal("8.00"),
        max_score=Decimal("10.00"),
    )
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "1 / 1" in body
    assert "8 / 10" in body
    assert f"/courses/{course.slug}/u/{unit.pk}/quiz/results/" in body


@pytest.mark.django_db
def test_course_results_only_own_submissions(client):
    course = CourseFactory()
    me = make_login(client, "me")
    EnrollmentFactory(student=me, course=course)
    other = UserFactory()
    unit = _quiz_with_auto_q(course)
    QuizSubmissionFactory(
        student=other,
        unit=unit,
        status="submitted",
        score=Decimal("9.00"),
        max_score=Decimal("10.00"),
    )
    body = client.get(f"/courses/{course.slug}/results/").content.decode()
    assert "0 / 1" in body  # I submitted nothing
    assert "9 / 10" not in body  # never leak another student's score


# ---------------------------------------------------------------------------
# My results link tests (Task 5)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_outline_has_my_results_link(client):
    course = CourseFactory()
    user = make_login(client, "s1")
    EnrollmentFactory(student=user, course=course)
    body = client.get(f"/courses/{course.slug}/").content.decode()
    assert f"/courses/{course.slug}/results/" in body


@pytest.mark.django_db
def test_my_courses_has_my_results_link(client):
    course = CourseFactory()
    user = make_login(client, "s2")
    EnrollmentFactory(student=user, course=course)
    body = client.get("/courses/").content.decode()
    assert f"/courses/{course.slug}/results/" in body


# ---------------------------------------------------------------------------
# unit_nav context tests (Task 3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_lesson_unit_context_has_unit_nav(client):
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0
    )
    l1 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        obligatory=True,
    )
    l2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        obligatory=True,
    )
    user = make_login(client, "navstu")
    EnrollmentFactory(student=user, course=course)

    resp = client.get(f"/courses/{course.slug}/u/{l1.pk}/")
    assert resp.status_code == 200
    nav = resp.context["unit_nav"]
    assert nav["current_pk"] == l1.pk
    assert nav["next"].pk == l2.pk
    assert nav["prev"] is None


@pytest.mark.django_db
def test_quiz_unit_context_has_unit_nav(client):
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0
    )
    quiz1 = make_quiz_unit(course=course, parent=part, order=0, obligatory=True)
    quiz2 = make_quiz_unit(course=course, parent=part, order=1, obligatory=True)
    user = make_login(client, "quiznavstu")
    EnrollmentFactory(student=user, course=course)

    # First quiz: no prev, next = quiz2
    resp = client.get(f"/courses/{course.slug}/u/{quiz1.pk}/quiz/")
    assert resp.status_code == 200
    nav = resp.context["unit_nav"]
    assert nav["current_pk"] == quiz1.pk
    assert nav["prev"] is None
    assert nav["next"].pk == quiz2.pk

    # Second quiz: prev = quiz1, no next
    resp2 = client.get(f"/courses/{course.slug}/u/{quiz2.pk}/quiz/")
    assert resp2.status_code == 200
    nav2 = resp2.context["unit_nav"]
    assert nav2["current_pk"] == quiz2.pk
    assert nav2["prev"].pk == quiz1.pk
    assert nav2["next"] is None


@pytest.mark.django_db
def test_check_answer_nojs_rerender_includes_unit_nav(client):
    course = CourseFactory()
    part = ContentNodeFactory(
        course=course, kind="part", parent=None, unit_type=None, order=0
    )
    l1 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        obligatory=True,
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        obligatory=True,
    )
    q = ShortTextQuestionElement.objects.create(
        stem="2+2?", accepted="4", marking_mode="A", max_marks=1
    )
    el = Element.objects.create(unit=l1, content_object=q)
    user = make_login(client, "njs")
    EnrollmentFactory(student=user, course=course)

    # No X-Requested-With header → full-page no-JS re-render
    resp = client.post(
        f"/courses/{course.slug}/u/{l1.pk}/q/{el.pk}/check/", {"answer": "5"}
    )
    assert resp.status_code == 200
    assert resp.context["unit_nav"]["current_pk"] == l1.pk
    # Shell HTML assertions (C1 pin — no-JS re-render must include the shell).
    html = resp.content.decode()
    assert "unit-shell" in html and "unit-tree" in html and "unit-foot__row" in html


@pytest.mark.django_db
def test_outline_passes_a_resume_target_for_an_enrolled_student(client):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "res1")
    course = CourseFactory(slug="res-course")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    EnrollmentFactory(student=user, course=course)
    r = client.get(reverse("courses:course_outline", kwargs={"slug": "res-course"}))
    assert r.status_code == 200
    assert r.context["resume"]["node"].pk == unit.pk


@pytest.mark.django_db
def test_outline_offers_no_resume_target_to_a_non_enrolled_viewer(client):
    """can_access_course also admits authors/teachers/staff previewing a course they
    are not taking; a "Start the course" CTA would be noise for them. This is also
    the guard that pins the WIRING -- calling build_resume unconditionally.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import make_login

    user = make_login(client, "res2")
    course = CourseFactory(slug="res-course-2", owner=user)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    r = client.get(reverse("courses:course_outline", kwargs={"slug": "res-course-2"}))
    assert r.status_code == 200
    assert r.context["resume"] is None
    # The context assertion alone would still pass if the template later grew a
    # fallback card, and it never exercises the {% if resume %} guard. This test is
    # what pins the WIRING (it replaces the abandoned view-level query test), so it
    # must assert on the rendered DOM as well.
    from bs4 import BeautifulSoup

    assert BeautifulSoup(r.content, "html.parser").select_one("a.resume") is None


@pytest.mark.django_db
def test_tag_filter_does_not_move_the_resume_target(client):
    """The target is computed independently of the active tag filter. Mutant:
    filtering `leaves` on tag_hidden. The failure would be INVISIBLE -- the card
    still renders, just pointing somewhere else.

    Tag has `author` (not owner), NO course field at all (course scoping runs
    through UnitTag -> ContentNode), and `color` must come from TAG_PALETTE
    (teal/amber/indigo/rose/green/violet/slate/cyan -- "blue" is not a member).
    Use the shipped factories rather than Tag.objects.create.
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import TagFactory
    from tests.factories import UnitTagFactory
    from tests.factories import make_login

    user = make_login(client, "tf")
    course = CourseFactory(slug="tf")
    target = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=0)
    other = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=1)
    EnrollmentFactory(student=user, course=course)
    tag = TagFactory(author=user, name="t", color="teal")
    UnitTagFactory(tag=tag, unit=other)

    r = client.get(
        reverse("courses:course_outline", kwargs={"slug": "tf"}), {"tags": tag.pk}
    )
    # Guard the guard: course_outline drops any ?tags= pk not in course_tag_ids, so
    # if the tag did not reach tags_for_outline the filter is silently inert and the
    # test would pass for the wrong reason.
    assert r.context["active_tag_ids"] == [tag.pk]
    assert r.context["resume"]["node"].pk == target.pk
