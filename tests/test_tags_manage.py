import pytest
from django.urls import reverse

from courses.models import Enrollment
from tags import services
from tags.models import Tag
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import TagFactory
from tests.factories import UserFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_rename_post_updates(client):
    # TagFactory uses UserFactory which is not verified; force_login of an unverified
    # user is blocked by allauth AccountMiddleware — create a verified author instead.
    user = make_verified_user(username="rename1", email="rename1@test.example.com")
    tag = TagFactory(author=user, name="exam")
    client.force_login(user)
    resp = client.post(reverse("tags:tag_rename", args=[tag.pk]), {"name": "Exam"})
    assert resp.status_code == 302
    tag.refresh_from_db()
    assert tag.name == "Exam"


def test_rename_collision_is_422(client):
    user = make_verified_user(
        username="collision1", email="collision1@test.example.com"
    )
    TagFactory(author=user, name="hard")
    tag = TagFactory(author=user, name="exam")
    client.force_login(user)
    resp = client.post(reverse("tags:tag_rename", args=[tag.pk]), {"name": "hard"})
    assert resp.status_code == 422
    tag.refresh_from_db()
    assert tag.name == "exam"


def test_recolor_invalid_key_422(client):
    user = make_verified_user(username="recolor1", email="recolor1@test.example.com")
    tag = TagFactory(author=user)
    client.force_login(user)
    resp = client.post(reverse("tags:tag_recolor", args=[tag.pk]), {"color": "nope"})
    assert resp.status_code == 422


def test_delete_post_removes_tag(client):
    user = make_verified_user(username="delete1", email="delete1@test.example.com")
    tag = TagFactory(author=user)
    client.force_login(user)
    resp = client.post(reverse("tags:tag_delete", args=[tag.pk]))
    assert resp.status_code == 302
    assert not Tag.objects.filter(pk=tag.pk).exists()


def test_delete_confirm_get_shows_accessible_count(client):
    user = make_verified_user(username="delcount1", email="delcount1@test.example.com")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    tag = TagFactory(author=user, name="exam")
    services.tag_unit(user, ContentNodeFactory(course=course), "exam")
    client.force_login(user)
    resp = client.get(reverse("tags:tag_delete", args=[tag.pk]))
    assert resp.status_code == 200
    assert b"1" in resp.content


def test_foreign_tag_manage_404(client):
    tag = TagFactory()
    intruder = make_verified_user(
        username="intruder1", email="intruder1@test.example.com"
    )
    client.force_login(intruder)
    url = reverse("tags:tag_rename", args=[tag.pk])
    assert client.post(url, {"name": "x"}).status_code == 404


def test_my_tags_lists_only_own(client):
    user = make_verified_user(username="mytags1", email="mytags1@test.example.com")
    TagFactory(author=user, name="mine")
    # The other-user's tag does not need force_login, so UserFactory is fine.
    TagFactory(author=UserFactory(), name="theirs")
    client.force_login(user)
    resp = client.get(reverse("tags:my_tags"))
    assert resp.status_code == 200
    assert b"mine" in resp.content
    assert b"theirs" not in resp.content
