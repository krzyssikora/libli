import pytest

from accounts.models import Invitation
from accounts.models import User
from courses.models import Enrollment
from grouping.models import GroupMembership
from institution.roles import TEACHER
from tests.factories import GroupFactory


@pytest.fixture
def oidc_app(db):
    from tests._sso import make_oidc_app

    return make_oidc_app()


def _adapter():
    from accounts.adapters import SocialAccountAdapter

    return SocialAccountAdapter()


def _save(oidc_app, inv, username="ssokid"):
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    request = make_request()
    sl = make_sociallogin(oidc_app, request, inv.email, username=username)
    sl._libli_invitation = inv
    return _adapter().save_user(request, sl)


@pytest.mark.django_db
def test_sso_accept_with_group_enrols(oidc_app):
    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)
    user = _save(oidc_app, inv)
    assert GroupMembership.objects.filter(group=g, student=user).exists()
    assert Enrollment.objects.filter(
        student=user, course=g.course, source="group"
    ).exists()


@pytest.mark.django_db
def test_sso_accept_without_group_no_membership(oidc_app):
    inv = Invitation.objects.create(email="kid@school.edu")
    user = _save(oidc_app, inv)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_sso_accept_archived_group_account_only(oidc_app):
    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)
    g.archived = True
    g.save()
    user = _save(oidc_app, inv)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_sso_accept_deleted_group_account_only(oidc_app):
    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)
    g.delete()
    user = _save(oidc_app, inv)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_sso_accept_non_student_row_with_group_no_membership(oidc_app):
    g = GroupFactory()
    inv = Invitation.objects.create(email="t@school.edu", role=TEACHER, group=g)
    user = _save(oidc_app, inv)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_sso_uses_locked_row_not_stale_stash(oidc_app):
    g1, g2 = GroupFactory(), GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g1)
    Invitation.objects.filter(pk=inv.pk).update(group=g2)
    user = _save(oidc_app, inv)
    assert GroupMembership.objects.filter(group=g2, student=user).exists()
    assert not GroupMembership.objects.filter(group=g1, student=user).exists()


@pytest.mark.django_db
def test_sso_locked_row_group_cleared_no_membership(oidc_app):
    g1 = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g1)
    Invitation.objects.filter(pk=inv.pk).update(group=None)
    user = _save(oidc_app, inv)
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_sso_helper_failure_rolls_back_everything(oidc_app, monkeypatch):
    from allauth.socialaccount.models import SocialAccount

    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)

    def boom(invitation, user):
        raise RuntimeError("boom")

    monkeypatch.setattr("accounts.services.apply_invitation_group", boom)
    with pytest.raises(RuntimeError):
        _save(oidc_app, inv)
    assert not User.objects.filter(username="ssokid").exists()
    assert not SocialAccount.objects.filter(uid="sub-ssokid").exists()
    inv.refresh_from_db()
    assert inv.accepted_at is None
