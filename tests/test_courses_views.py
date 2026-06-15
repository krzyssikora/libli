import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login

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
def test_quiz_unit_renders_placeholder(client):
    user = make_login(client, "quizreader")
    course = CourseFactory(slug="qc")
    EnrollmentFactory(student=user, course=course)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "qc", "node_pk": quiz.pk})
    )
    assert resp.status_code == 200
    assert "Phase 2" in resp.content.decode()
