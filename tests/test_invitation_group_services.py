import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from accounts.models import Invitation
from accounts.services import InvitationError
from accounts.services import apply_invitation_group
from accounts.services import create_or_refresh_invitation
from courses.models import Enrollment
from grouping.models import GroupMembership
from institution.roles import STUDENT
from institution.roles import TEACHER
from notifications.models import Notification
from tests.factories import GroupFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_group_with_non_student_role_raises():
    g = GroupFactory()
    with pytest.raises(
        InvitationError,
        match=re.escape("A group can only be given to a Student invitation."),
    ):
        create_or_refresh_invitation(
            email="t@example.com", role=TEACHER, invited_by=None, group=g
        )
    assert Invitation.objects.count() == 0


@pytest.mark.django_db
def test_archived_group_raises():
    g = GroupFactory(archived=True)
    with pytest.raises(InvitationError, match=re.escape("This group is archived.")):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    assert Invitation.objects.count() == 0


@pytest.mark.django_db
def test_create_stores_group(django_capture_on_commit_callbacks, mailoutbox):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        inv, created = create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    assert created is True
    assert inv.group == g


@pytest.mark.django_db
def test_create_without_group_kwarg_has_no_group(
    django_capture_on_commit_callbacks, mailoutbox
):
    with django_capture_on_commit_callbacks(execute=True):
        inv, _ = create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None
        )
    assert inv.group is None


@pytest.mark.django_db
def test_refresh_replaces_group(django_capture_on_commit_callbacks, mailoutbox):
    g1, g2 = GroupFactory(), GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g1
        )
    inv, created = create_or_refresh_invitation(
        email="s@example.com", role=STUDENT, invited_by=None, group=g2
    )
    assert created is False
    inv.refresh_from_db()
    assert inv.group == g2


@pytest.mark.django_db
def test_refresh_explicit_none_clears_group(
    django_capture_on_commit_callbacks, mailoutbox
):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    inv, _ = create_or_refresh_invitation(
        email="s@example.com", role=STUDENT, invited_by=None, group=None
    )
    inv.refresh_from_db()
    assert inv.group is None


@pytest.mark.django_db
def test_refresh_without_group_kwarg_keeps_group(
    django_capture_on_commit_callbacks, mailoutbox
):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    inv, _ = create_or_refresh_invitation(
        email="s@example.com", role=STUDENT, invited_by=None
    )
    inv.refresh_from_db()
    assert inv.group == g


@pytest.mark.django_db
def test_refresh_without_group_kwarg_to_teacher_clears_group(
    django_capture_on_commit_callbacks, mailoutbox
):
    g = GroupFactory()
    with django_capture_on_commit_callbacks(execute=True):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=g
        )
    inv, _ = create_or_refresh_invitation(
        email="s@example.com", role=TEACHER, invited_by=None
    )
    inv.refresh_from_db()
    assert inv.group is None


@pytest.mark.django_db
def test_refresh_validation_runs_before_update():
    g1 = GroupFactory()
    pending = Invitation.objects.create(email="s@example.com", role=STUDENT, group=g1)
    archived = GroupFactory(archived=True)
    with pytest.raises(InvitationError):
        create_or_refresh_invitation(
            email="s@example.com", role=STUDENT, invited_by=None, group=archived
        )
    pending.refresh_from_db()
    assert pending.group == g1


def _pending(group, role=STUDENT):
    return Invitation.objects.create(email="p@example.com", role=role, group=group)


@pytest.mark.django_db
def test_apply_adds_student_and_enrols():
    g = GroupFactory()
    inv = _pending(g)
    user = UserFactory()
    apply_invitation_group(inv, user)
    assert GroupMembership.objects.filter(group=g, student=user).exists()
    assert Enrollment.objects.filter(
        student=user, course=g.course, source="group"
    ).exists()
    assert (
        Notification.objects.filter(
            recipient=user, kind=Notification.Kind.ENROLLED, actor__isnull=True
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_apply_noop_without_group():
    inv = _pending(None)
    user = UserFactory()
    apply_invitation_group(inv, user)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_apply_noop_for_non_student_row():
    g = GroupFactory()
    inv = _pending(g, role=TEACHER)
    user = UserFactory()
    apply_invitation_group(inv, user)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_apply_noop_for_archived_group():
    g = GroupFactory()
    inv = _pending(g)
    g.archived = True
    g.save()
    user = UserFactory()
    apply_invitation_group(inv, user)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_apply_noop_after_group_deleted():
    g = GroupFactory()
    inv = _pending(g)
    g.delete()
    user = UserFactory()
    apply_invitation_group(inv, user)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_apply_locks_group_row():
    g = GroupFactory()
    inv = _pending(g)
    user = UserFactory()
    with CaptureQueriesContext(connection) as ctx:
        apply_invitation_group(inv, user)
    pat = re.compile(rf'"grouping_group"\."id" = {g.pk}\b')
    hits = [
        q["sql"]
        for q in ctx.captured_queries
        if 'FROM "grouping_group"' in q["sql"] and pat.search(q["sql"])
    ]
    assert hits
    assert all("FOR UPDATE" in s for s in hits)
    assert not any('"courses_course"' in s for s in hits)
