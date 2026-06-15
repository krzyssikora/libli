import pytest
from django.urls import reverse

from tests.factories import CourseFactory
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
