import pytest
from django.urls import reverse


def _pa_client(client):
    from django.contrib.auth.models import Group, Permission
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from tests.factories import TEST_PASSWORD

    pa = User.objects.create_user(
        username="pa", email="pa@school.edu", password=TEST_PASSWORD, is_staff=True
    )
    pa.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    for code in ("add_course", "change_course", "delete_course", "view_course"):
        pa.user_permissions.add(Permission.objects.get(codename=code))
    client.force_login(pa)
    return pa


@pytest.mark.django_db
def test_edit_page_shows_danger_zone_with_red_delete(client):
    from courses.models import Course

    pa = _pa_client(client)
    course = Course.objects.create(title="C", slug="c", owner=pa)
    body = client.get(reverse("courses:manage_course_edit", args=["c"])).content
    assert b"danger-zone" in body
    assert b"btn--danger" in body


@pytest.mark.django_db
def test_create_page_has_no_danger_zone(client):
    _pa_client(client)
    body = client.get(reverse("courses:manage_course_create")).content
    assert b"danger-zone" not in body
    assert b"btn--danger" not in body
