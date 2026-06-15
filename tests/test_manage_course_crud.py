import pytest
from django.urls import reverse

from courses.forms import unique_course_slug
from courses.models import Course
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa


@pytest.mark.django_db
def test_course_list_requires_login(client):
    resp = client.get(reverse("courses:manage_course_list"))
    assert resp.status_code == 302  # redirect to login


@pytest.mark.django_db
def test_owner_sees_only_their_courses(client):
    owner = make_login(client, "owner")
    CourseFactory(title="Mine", owner=owner)
    CourseFactory(title="Theirs", owner=UserFactory())
    resp = client.get(reverse("courses:manage_course_list"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Mine" in body and "Theirs" not in body
    assert "New course" not in body  # non-PA owner has no create action


@pytest.mark.django_db
def test_platform_admin_sees_all_courses_and_new_button(client):
    make_pa(client, "pa")
    CourseFactory(title="Alpha", owner=UserFactory())
    CourseFactory(title="Beta", owner=None)
    resp = client.get(reverse("courses:manage_course_list"))
    body = resp.content.decode()
    assert "Alpha" in body and "Beta" in body
    assert "New course" in body
    # ordered by title
    assert body.index("Alpha") < body.index("Beta")


@pytest.mark.django_db
def test_unique_course_slug_dedup():
    CourseFactory(slug="algebra")
    CourseFactory(slug="algebra-2")
    assert unique_course_slug("Algebra") == "algebra-3"


@pytest.mark.django_db
def test_unique_course_slug_keeps_current_on_edit():
    c = CourseFactory(slug="algebra")
    assert unique_course_slug("Algebra", exclude_pk=c.pk) == "algebra"


@pytest.mark.django_db
def test_only_pa_can_create(client):
    make_login(client, "plain")
    resp = client.get(reverse("courses:manage_course_create"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_pa_creates_course_and_becomes_default_owner(client):
    pa = make_pa(client, "pa")
    resp = client.post(
        reverse("courses:manage_course_create"),
        {
            "title": "Algebra I",
            "slug": "algebra-i",
            "language": "en",
            "overview": "",
            "visibility": "assigned",
            "owner": pa.pk,
        },
    )
    assert resp.status_code == 302
    course = Course.objects.get(slug="algebra-i")
    assert course.owner_id == pa.pk


@pytest.mark.django_db
def test_owner_can_edit_but_not_create(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner, title="Old")
    # create is PA-only
    assert client.get(reverse("courses:manage_course_create")).status_code == 403
    # edit allowed for owner
    resp = client.post(
        reverse("courses:manage_course_edit", kwargs={"slug": "c1"}),
        {
            "title": "New",
            "slug": "c1",
            "language": "en",
            "overview": "",
            "visibility": "assigned",
            "owner": owner.pk,
        },
    )
    assert resp.status_code == 302
    course.refresh_from_db()
    assert course.title == "New"


@pytest.mark.django_db
def test_edit_slug_collision_is_form_error_not_500(client):
    make_pa(client, "pa")
    CourseFactory(slug="taken")
    course = CourseFactory(slug="mine")
    resp = client.post(
        reverse("courses:manage_course_edit", kwargs={"slug": "mine"}),
        {
            "title": "Mine",
            "slug": "taken",
            "language": "en",
            "overview": "",
            "visibility": "assigned",
            "owner": "",
        },
    )
    assert resp.status_code == 200  # re-rendered with errors
    assert b"already in use" in resp.content
    course.refresh_from_db()
    assert course.slug == "mine"


@pytest.mark.django_db
def test_delete_confirm_get_shows_counts(client):
    make_pa(client, "pa")
    course = CourseFactory(slug="c1")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    EnrollmentFactory(course=course)
    resp = client.get(reverse("courses:manage_course_delete", kwargs={"slug": "c1"}))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "enrollment" in body.lower()  # warning rendered when learner state exists


@pytest.mark.django_db
def test_owner_cannot_delete_only_pa(client):
    owner = make_login(client, "owner")
    CourseFactory(slug="c1", owner=owner)
    resp = client.get(reverse("courses:manage_course_delete", kwargs={"slug": "c1"}))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_pa_post_hard_deletes(client):
    make_pa(client, "pa")
    course = CourseFactory(slug="c1")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    resp = client.post(reverse("courses:manage_course_delete", kwargs={"slug": "c1"}))
    assert resp.status_code == 302
    assert not Course.objects.filter(slug="c1").exists()
