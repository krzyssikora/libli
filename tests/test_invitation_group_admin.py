from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import Invitation
from institution.roles import STUDENT
from institution.roles import TEACHER
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_verified_user


@pytest.fixture
def admin_client(client):
    user = make_verified_user(username="root", email="root@school.edu")
    user.is_superuser = True
    user.is_staff = True
    user.save()
    client.force_login(user)
    return client


def _label(g):
    return f"{g.name} — {g.course.title}"


def _post_data_from(resp):
    """Rebuild the change form's POST payload from the rendered form."""
    form = resp.context["adminform"].form
    data = {}
    for name in form.fields:
        value = form[name].value()
        if value is None:
            continue
        if name == "expires_at":
            local = timezone.localtime(value)
            data["expires_at_0"] = local.strftime("%Y-%m-%d")
            data["expires_at_1"] = local.strftime("%H:%M:%S")
        else:
            data[name] = value
    return data


@pytest.mark.django_db
def test_changelist_shows_role_and_group_with_course(admin_client):
    g = GroupFactory()
    Invitation.objects.create(email="a@school.edu", role=STUDENT, group=g)
    resp = admin_client.get(reverse("admin:accounts_invitation_changelist"))
    assert resp.status_code == 200
    assert _label(g) in resp.content.decode()
    assert "Student" in resp.content.decode()


@pytest.mark.django_db
def test_changelist_query_count_flat(admin_client):
    groups = [GroupFactory(course=CourseFactory()) for _ in range(5)]
    inviters = [UserFactory() for _ in range(5)]
    Invitation.objects.create(
        email="i0@school.edu", role=STUDENT, invited_by=inviters[0], group=groups[0]
    )
    url = reverse("admin:accounts_invitation_changelist")
    admin_client.get(url)  # warm-up
    with CaptureQueriesContext(connection) as before:
        admin_client.get(url)
    Invitation.objects.bulk_create(
        [
            Invitation(
                email=f"i{i}@school.edu",
                role=STUDENT,
                invited_by=inviters[i],
                group=groups[i],
                expires_at=timezone.now() + timedelta(days=7),
            )
            for i in range(1, 5)
        ]
    )
    with CaptureQueriesContext(connection) as after:
        admin_client.get(url)
    assert len(before.captured_queries) == len(after.captured_queries)


@pytest.mark.django_db
def test_change_form_offers_non_archived_groups_with_course_label(admin_client):
    active = GroupFactory()
    archived = GroupFactory(archived=True)
    inv = Invitation.objects.create(email="a@school.edu", role=STUDENT)
    html = admin_client.get(
        reverse("admin:accounts_invitation_change", args=[inv.pk])
    ).content.decode()
    assert _label(active) in html
    assert _label(archived) not in html


@pytest.mark.django_db
def test_change_form_keeps_current_archived_group(admin_client):
    g = GroupFactory(archived=True)
    other = GroupFactory(archived=True)
    inv = Invitation.objects.create(email="a@school.edu", role=STUDENT, group=g)
    url = reverse("admin:accounts_invitation_change", args=[inv.pk])
    resp = admin_client.get(url)
    html = resp.content.decode()
    assert _label(g) in html  # fails if include_pk is ignored
    assert _label(other) not in html
    resp = admin_client.post(url, _post_data_from(resp))
    assert resp.status_code == 302, resp.context["adminform"].form.errors
    inv.refresh_from_db()
    assert inv.group_id == g.pk


@pytest.mark.django_db
def test_admin_rejects_group_on_teacher(admin_client):
    g = GroupFactory()
    inv = Invitation.objects.create(email="a@school.edu", role=STUDENT)
    url = reverse("admin:accounts_invitation_change", args=[inv.pk])
    data = _post_data_from(admin_client.get(url))
    data["role"] = TEACHER
    data["group"] = g.pk
    resp = admin_client.post(url, data)
    assert resp.status_code == 200
    assert resp.context["adminform"].form.errors
    inv.refresh_from_db()
    assert inv.role == STUDENT
    assert inv.group_id is None
