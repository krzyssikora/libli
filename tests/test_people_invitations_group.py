import re
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.forms import SendInvitationForm
from accounts.forms import SendStudentInvitationForm
from accounts.models import Invitation
from institution.roles import ROLE_CHOICES
from institution.roles import STUDENT
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.test_people_invitations_tab import make_pa

NON_STUDENT = [value for value, _label in ROLE_CHOICES if value != STUDENT]


def _form(**data):
    return SendStudentInvitationForm(data)


@pytest.mark.django_db
def test_group_optional():
    form = _form(email="a@school.edu", role=STUDENT)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["group"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("role", NON_STUDENT)
def test_group_with_teacher_errors_on_group(role):
    g = GroupFactory()
    form = _form(email="a@school.edu", role=role, group=g.pk)
    assert not form.is_valid()
    assert "group" in form.errors


@pytest.mark.django_db
def test_invalid_role_with_group_only_role_error():
    g = GroupFactory()
    form = _form(email="a@school.edu", role="Nope", group=g.pk)
    assert not form.is_valid()
    assert "role" in form.errors
    assert "group" not in form.errors


@pytest.mark.django_db
def test_archived_group_not_offered():
    g = GroupFactory(archived=True)
    form = _form(email="a@school.edu", role=STUDENT, group=g.pk)
    assert not form.is_valid()
    assert "group" in form.errors


@pytest.mark.django_db
def test_option_label_has_course_title():
    g = GroupFactory()
    form = SendStudentInvitationForm()
    assert form.fields["group"].label_from_instance(g) == f"{g.name} — {g.course.title}"


def test_setup_wizard_form_has_no_group_field():
    assert "group" not in SendInvitationForm().fields


@pytest.mark.django_db
def test_setup_wizard_team_step_renders_without_group(client):
    make_pa(client)
    GroupFactory()
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "team"}))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="email"' in html
    assert 'name="group"' not in html


@pytest.mark.django_db
def test_get_shows_same_named_groups_with_course(client):
    make_pa(client)
    GroupFactory(name="3A", course=CourseFactory(title="Alpha"))
    GroupFactory(name="3A", course=CourseFactory(title="Beta"))
    resp = client.get(reverse("accounts:people_invitations"))
    html = resp.content.decode()
    assert "3A — Alpha" in html
    assert "3A — Beta" in html


@pytest.mark.django_db
def test_send_with_group_saves_it(client):
    make_pa(client)
    g = GroupFactory()
    resp = client.post(
        reverse("accounts:invitation_send"),
        {"email": "kid@school.edu", "role": STUDENT, "group": g.pk},
    )
    assert resp.status_code == 302
    assert Invitation.objects.get(email="kid@school.edu").group == g


def _row(html, email):
    for tr in re.findall(r"<tr>.*?</tr>", html, re.S):
        if email in tr:
            return tr
    raise AssertionError(f"no row for {email}")


@pytest.mark.django_db
def test_list_shows_group_and_course(client):
    pa = make_pa(client)
    g = GroupFactory(name="3A", course=CourseFactory(title="Alpha"))
    Invitation.objects.create(
        email="k@school.edu", role=STUDENT, invited_by=pa, group=g
    )
    html = client.get(reverse("accounts:people_invitations")).content.decode()
    assert "3A — Alpha" in _row(html, "k@school.edu")


@pytest.mark.django_db
def test_list_marks_archived_group_on_pending_row_only(client):
    pa = make_pa(client)
    g = GroupFactory(archived=True)
    Invitation.objects.create(
        email="pending@school.edu", role=STUDENT, invited_by=pa, group=g
    )
    Invitation.objects.create(
        email="done@school.edu",
        role=STUDENT,
        invited_by=pa,
        group=g,
        accepted_at=timezone.now(),
    )
    expired = Invitation.objects.create(
        email="expired@school.edu", role=STUDENT, invited_by=pa, group=g
    )
    Invitation.objects.filter(pk=expired.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    html = client.get(reverse("accounts:people_invitations")).content.decode()
    assert "(archived)" in _row(html, "pending@school.edu")
    assert "(archived)" not in _row(html, "done@school.edu")
    assert "(archived)" not in _row(html, "expired@school.edu")


@pytest.mark.django_db
def test_list_query_count_flat(client):
    make_pa(client)
    courses = [CourseFactory() for _ in range(5)]
    groups = [GroupFactory(course=c) for c in courses]
    inviters = [UserFactory() for _ in range(5)]
    Invitation.objects.create(
        email="i0@school.edu", role=STUDENT, invited_by=inviters[0], group=groups[0]
    )
    url = reverse("accounts:people_invitations")
    client.get(url)  # warm-up
    with CaptureQueriesContext(connection) as before:
        client.get(url)
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
        client.get(url)
    assert len(before.captured_queries) == len(after.captured_queries)
