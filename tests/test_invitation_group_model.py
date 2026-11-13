import pytest
from django.core.exceptions import ValidationError

from accounts.models import Invitation
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER
from tests.factories import GroupFactory


@pytest.mark.django_db
def test_group_is_optional():
    assert Invitation.objects.create(email="a@x.edu").group is None


@pytest.mark.django_db
def test_deleting_group_nulls_invitation_group():
    g = GroupFactory()
    inv = Invitation.objects.create(email="a@x.edu", group=g)
    g.delete()
    inv.refresh_from_db()
    assert inv.group is None


@pytest.mark.django_db
@pytest.mark.parametrize("role", [TEACHER, COURSE_ADMIN, PLATFORM_ADMIN])
def test_full_clean_rejects_group_on_non_student(role):
    g = GroupFactory()
    with pytest.raises(ValidationError) as exc:
        Invitation(email="a@x.edu", role=role, group=g).full_clean()
    assert "group" in exc.value.message_dict


@pytest.mark.django_db
def test_full_clean_accepts_group_on_student():
    g = GroupFactory()
    Invitation(email="a@x.edu", role=STUDENT, group=g).full_clean()


@pytest.mark.django_db(transaction=True)
def test_group_column_present_after_migration_tests():
    # Guards the restore in test_subject_migrations / test_geogebra_migration:
    # they migrate courses below grouping.0005, which unapplies accounts.0007.
    g = GroupFactory()
    inv = Invitation.objects.create(email="a@x.edu", group=g)
    assert Invitation.objects.get(pk=inv.pk).group_id == g.pk
