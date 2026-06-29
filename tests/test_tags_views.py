import pytest
from django.urls import reverse

from courses.models import Enrollment
from tags.models import Tag
from tags.models import UnitTag
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import TagFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _make_user(n=0):
    """Verified user — force_login works. UserFactory+force_login redirects to login
    because UserFactory uses skip_postgeneration_save (see test_notes_views.py note)."""
    return make_verified_user(
        username=f"taguser{n}", email=f"taguser{n}@test.example.com"
    )


def _enrolled_unit(user, **kw):
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    return ContentNodeFactory(course=course, **kw)


def test_tag_add_by_name_creates_link(client):
    user = _make_user(0)
    client.force_login(user)
    unit = _enrolled_unit(user)
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    resp = client.post(url, {"name": "exam"})
    assert resp.status_code == 302
    assert UnitTag.objects.filter(unit=unit, tag__author=user).count() == 1


def test_tag_add_by_multiple_tag_pks(client):
    user = _make_user(1)
    client.force_login(user)
    unit = _enrolled_unit(user)
    t1 = TagFactory(author=user)
    t2 = TagFactory(author=user)
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    client.post(url, {"tag_pk": [t1.pk, t2.pk]})
    assert UnitTag.objects.filter(unit=unit).count() == 2


def test_tag_add_empty_is_422(client):
    user = _make_user(2)
    client.force_login(user)
    unit = _enrolled_unit(user)
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    resp = client.post(url, {"name": "  "})
    assert resp.status_code == 422
    assert UnitTag.objects.filter(unit=unit).count() == 0


def test_tag_add_inaccessible_course_403(client):
    user = _make_user(3)
    client.force_login(user)
    unit = ContentNodeFactory(course=CourseFactory())  # not enrolled
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    assert client.post(url, {"name": "x"}).status_code == 403


def test_tag_add_foreign_tag_pk_404(client):
    user = _make_user(4)
    client.force_login(user)
    unit = _enrolled_unit(user)
    foreign = TagFactory()
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    assert client.post(url, {"tag_pk": [foreign.pk]}).status_code == 404


def test_tag_add_requires_login(client):
    unit = ContentNodeFactory()
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    resp = client.post(url, {"name": "x"})
    assert resp.status_code == 302 and "/login" in resp.url


def test_tag_remove_deletes_link(client):
    user = _make_user(5)
    client.force_login(user)
    unit = _enrolled_unit(user)
    from tags import services

    ut = services.tag_unit(user, unit, "exam")
    url = reverse("tags:tag_remove", args=[unit.course.slug, unit.pk])
    client.post(url, {"tag_pk": ut.tag_id})
    assert not UnitTag.objects.filter(unit=unit).exists()
    assert Tag.objects.filter(pk=ut.tag_id).exists()
