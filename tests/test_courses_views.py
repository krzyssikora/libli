import pytest
from decimal import Decimal
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
    assert "Done 0 of 0" in resp.content.decode()


@pytest.mark.django_db
def test_course_results_enrolled_renders_rows_and_drilldown(client):
    course = CourseFactory()
    user = make_login(client, "stud")
    EnrollmentFactory(student=user, course=course)
    unit = _quiz_with_auto_q(course)
    QuizSubmissionFactory(student=user, unit=unit, status="submitted",
                          score=Decimal("8.00"), max_score=Decimal("10.00"))
    resp = client.get(f"/courses/{course.slug}/results/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Done 1 of 1" in body
    assert "8 / 10" in body
    assert f"/courses/{course.slug}/u/{unit.pk}/quiz/results/" in body


@pytest.mark.django_db
def test_course_results_only_own_submissions(client):
    course = CourseFactory()
    me = make_login(client, "me")
    EnrollmentFactory(student=me, course=course)
    other = UserFactory()
    unit = _quiz_with_auto_q(course)
    QuizSubmissionFactory(student=other, unit=unit, status="submitted",
                          score=Decimal("9.00"), max_score=Decimal("10.00"))
    body = client.get(f"/courses/{course.slug}/results/").content.decode()
    assert "Done 0 of 1" in body   # I submitted nothing
    assert "9 / 10" not in body     # never leak another student's score


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
