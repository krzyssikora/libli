import pytest
from django.urls import reverse

from courses.models import Course
from tests.factories import SubjectFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _course_post(subjects):
    return {
        "title": "Mechanics",
        "slug": "",
        "subjects": [s.pk for s in subjects],
        "language": "en",
        "overview": "",
        "visibility": "assigned",
        "owner": "",
        "html_css": "",
        "html_js": "",
        "structure": "chapters",
    }


def test_course_create_persists_selected_subjects(client):
    make_pa(client, "pa_create")
    math = SubjectFactory(title_en="Math")
    art = SubjectFactory(title_en="Art")
    resp = client.post(
        reverse("courses:manage_course_create"), _course_post([math, art])
    )
    assert resp.status_code == 302
    course = Course.objects.get(title="Mechanics")
    assert set(course.subjects.values_list("pk", flat=True)) == {math.pk, art.pk}


def test_course_edit_persists_selected_subjects(client):
    pa = make_pa(client, "pa_edit")
    from tests.factories import CourseFactory

    course = CourseFactory(title="Optics", owner=pa)
    math = SubjectFactory(title_en="Math")
    data = _course_post([math])
    data["title"] = "Optics"
    data["slug"] = course.slug
    resp = client.post(
        reverse("courses:manage_course_edit", kwargs={"slug": course.slug}), data
    )
    assert resp.status_code == 302
    assert set(course.subjects.values_list("pk", flat=True)) == {math.pk}
