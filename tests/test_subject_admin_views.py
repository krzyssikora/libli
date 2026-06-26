import pytest
from django.urls import reverse

from courses.models import Course
from courses.models import Subject
from tests.factories import SubjectFactory
from tests.factories import make_login
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


def test_pa_can_list_subjects(client):
    make_pa(client, "pa_list")
    SubjectFactory(title_en="Math")
    resp = client.get(reverse("courses:manage_subject_list"))
    assert resp.status_code == 200
    assert "Math" in resp.content.decode()


def test_pa_can_create_subject(client):
    make_pa(client, "pa_new")
    resp = client.post(
        reverse("courses:manage_subject_create"),
        {"title_en": "Biology", "title_pl": "Biologia", "slug": ""},
    )
    assert resp.status_code == 302
    assert Subject.objects.filter(title_en="Biology").exists()


def test_pa_can_edit_subject(client):
    make_pa(client, "pa_ed")
    s = SubjectFactory(title_en="Maths")
    resp = client.post(
        reverse("courses:manage_subject_edit", kwargs={"slug": s.slug}),
        {"title_en": "Mathematics", "title_pl": "", "slug": ""},
    )
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.title_en == "Mathematics"


def test_delete_unlinks_without_orphaning_course(client):
    make_pa(client, "pa_del")
    from tests.factories import CourseFactory

    s = SubjectFactory(title_en="Temp")
    course = CourseFactory(subjects=[s])
    resp = client.post(
        reverse("courses:manage_subject_delete", kwargs={"slug": s.slug})
    )
    assert resp.status_code == 302
    assert not Subject.objects.filter(pk=s.pk).exists()
    course.refresh_from_db()  # course survives, just loses the subject
    assert course.subjects.count() == 0


def test_course_admin_cannot_create_subject(client):
    from django.contrib.auth.models import Group

    from institution.roles import COURSE_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_login(client, "ca1")
    user.groups.add(Group.objects.get(name=COURSE_ADMIN))  # CA lacks add_subject
    resp = client.post(
        reverse("courses:manage_subject_create"),
        {"title_en": "X", "title_pl": "", "slug": ""},
    )
    assert resp.status_code == 403


def test_student_cannot_list_subjects(client):
    make_login(client, "stu1")
    resp = client.get(reverse("courses:manage_subject_list"))
    assert resp.status_code == 403


def test_list_shows_usage_count(client):
    make_pa(client, "pa_count")
    from tests.factories import CourseFactory

    s = SubjectFactory(title_en="Math")
    CourseFactory(subjects=[s])
    CourseFactory(subjects=[s])
    resp = client.get(reverse("courses:manage_subject_list"))
    body = resp.content.decode()
    assert "used by 2 courses" in body  # the count phrase, not a bare "2" anywhere


def test_nav_shows_subjects_link_for_pa(client):
    make_pa(client, "pa_nav")
    resp = client.get(reverse("courses:manage_subject_list"))
    assert reverse("courses:manage_subject_list") in resp.content.decode()


def test_nav_hides_subjects_link_for_student(client):
    make_login(client, "stu_nav")
    resp = client.get(reverse("courses:my_courses"))
    assert reverse("courses:manage_subject_list") not in resp.content.decode()


def test_usage_count_plural_pl(client):
    make_pa(client, "pa_pl")
    from tests.factories import CourseFactory

    s = SubjectFactory(title_en="Math")
    for _ in range(5):
        CourseFactory(subjects=[s])
    # Set session language key so SessionLocaleMiddleware activates Polish.
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()
    resp = client.get(reverse("courses:manage_subject_list"))
    body = resp.content.decode()
    assert "kurs" in body.lower()  # PL plural form rendered (not English "courses")
