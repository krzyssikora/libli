import pytest

from accounts.models import Invitation
from accounts.models import User
from accounts.services import InvitationError
from accounts.services import create_or_refresh_invitation
from accounts.services import invitation_feedback
from accounts.services import resend_invitation
from accounts.services import revoke_invitation
from institution.roles import COURSE_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER


@pytest.mark.django_db
def test_invitation_feedback_success_only_without_allowlist():
    # Empty allowlist = any domain allowed -> just the success line, no warning.
    msgs = invitation_feedback("anyone@anywhere.com")
    assert [level for level, _text in msgs] == ["success"]


@pytest.mark.django_db
def test_invitation_feedback_warns_on_out_of_allowlist_domain():
    from institution.models import Institution

    inst = Institution.load()
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    msgs = invitation_feedback("outsider@elsewhere.com")
    assert [level for level, _text in msgs] == ["success", "warning"]
    assert "elsewhere.com" in str(msgs[1][1])


@pytest.mark.django_db
def test_invitation_feedback_no_warning_for_in_allowlist_domain():
    from institution.models import Institution

    inst = Institution.load()
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    msgs = invitation_feedback("teacher@school.edu")
    assert [level for level, _text in msgs] == ["success"]


@pytest.mark.django_db
def test_create_new_invite_sets_role_and_inviter(
    django_capture_on_commit_callbacks, mailoutbox
):
    pa = User.objects.create_user(username="pa")
    # The new-row email is sent by the post_save signal via transaction.on_commit,
    # so capture+execute on_commit callbacks to observe exactly ONE email (not two).
    with django_capture_on_commit_callbacks(execute=True):
        inv, created = create_or_refresh_invitation(
            email="new@school.edu", role=TEACHER, invited_by=pa
        )
    assert created is True
    assert inv.role == TEACHER
    assert inv.invited_by == pa
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_existing_active_account_is_rejected(mailoutbox):
    User.objects.create_user(username="taken", email="taken@school.edu")
    with pytest.raises(InvitationError):
        create_or_refresh_invitation(
            email="taken@school.edu", role=STUDENT, invited_by=None
        )
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_existing_inactive_account_is_rejected(mailoutbox):
    User.objects.create_user(username="gone", email="gone@school.edu", is_active=False)
    with pytest.raises(InvitationError):
        create_or_refresh_invitation(
            email="gone@school.edu", role=STUDENT, invited_by=None
        )


@pytest.mark.django_db
def test_existing_account_check_precedes_pending_refresh(mailoutbox):
    # An email with BOTH a pending invite AND a registered account is rejected,
    # not refreshed.
    User.objects.create_user(username="dup", email="dup@school.edu")
    Invitation.objects.create(email="dup@school.edu", role=STUDENT)
    with pytest.raises(InvitationError):
        create_or_refresh_invitation(
            email="dup@school.edu", role=TEACHER, invited_by=None
        )


@pytest.mark.django_db
def test_pending_invite_is_refreshed_with_new_role(mailoutbox):
    pa = User.objects.create_user(username="pa2")
    first = Invitation.objects.create(email="p@school.edu", role=STUDENT)
    inv, created = create_or_refresh_invitation(
        email="p@school.edu", role=COURSE_ADMIN, invited_by=pa
    )
    assert created is False
    assert inv.pk == first.pk
    assert inv.role == COURSE_ADMIN
    assert inv.invited_by == pa
    assert len(mailoutbox) == 1  # refresh sends explicitly (not a create)


@pytest.mark.django_db
def test_revoke_deletes_the_row():
    inv = Invitation.objects.create(email="r@school.edu")
    revoke_invitation(inv)
    assert not Invitation.objects.filter(pk=inv.pk).exists()


@pytest.mark.django_db
def test_resend_refreshes_expiry_and_sends(mailoutbox):
    from django.utils import timezone

    inv = Invitation.objects.create(email="s@school.edu")
    near = timezone.now()
    inv.expires_at = near  # deliberately lower it to ~now
    inv.save(update_fields=["expires_at"])
    resend_invitation(inv)
    inv.refresh_from_db()
    assert inv.expires_at > near  # refreshed forward from the lowered value
    assert len(mailoutbox) == 1
