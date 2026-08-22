"""The dedicated roster page for individually-granted reporters."""

import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.core.cache import cache
from django.urls import reverse

from institution.roles import PLATFORM_ADMIN
from institution.roles import TEACHER
from institution.roles import seed_roles
from support.models import SupportSettings
from support.policy import can_report
from tests.factories import UserFactory
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _teacher(username):
    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=TEACHER))
    return user


def test_the_first_ever_save_creates_the_row_and_grants_immediately(client):
    make_pa(client)
    teacher = _teacher("grantme")
    assert SupportSettings.objects.count() == 0
    assert can_report(teacher) is False
    response = client.post(
        reverse("support:reporters"), {"extra_reporters": [teacher.pk]}
    )
    assert response.status_code == 302
    assert SupportSettings.objects.count() == 1
    assert can_report(teacher) is True


def test_an_inactive_existing_grant_survives_a_save_that_adds_someone_else(client):
    """Mutant: scope the roster queryset to active non-PA users alone — the
    absent user is then dropped by save_m2m and the grant is silently revoked."""
    make_pa(client)
    keep = _teacher("keepme")
    row = SupportSettings.load()
    row.extra_reporters.add(keep)
    keep.is_active = False
    keep.save()
    newcomer = _teacher("newcomer")
    client.post(
        reverse("support:reporters"),
        {"extra_reporters": [keep.pk, newcomer.pk]},
    )
    assert set(SupportSettings.load().extra_reporters.values_list("pk", flat=True)) == {
        keep.pk,
        newcomer.pk,
    }


def test_an_already_selected_user_outside_the_base_roster_is_still_rendered(client):
    make_pa(client)
    promoted = _teacher("promoted")
    SupportSettings.load().extra_reporters.add(promoted)
    promoted.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    body = client.get(reverse("support:reporters")).content.decode()
    # Assert on the pk, not the username: UserFactory sets display_name from
    # Faker and User.__str__ returns display_name or username, so
    # CheckboxSelectMultiple renders the Faker name and the username never
    # appears — the test would fail on a correct build.
    assert f'value="{promoted.pk}"' in body


def test_an_out_of_roster_grant_is_marked_for_the_muted_note(client):
    """The spec requires these to render "checked, with a muted note explaining
    why they are listed". Mutant: drop the create_option override — the grant
    still renders, but indistinguishable from an ordinary roster member."""
    make_pa(client)
    ordinary = _teacher("ordinary")
    stale_grant = _teacher("deactivated")
    row = SupportSettings.load()
    row.extra_reporters.add(ordinary, stale_grant)
    stale_grant.is_active = False
    stale_grant.save()
    body = client.get(reverse("support:reporters")).content.decode()
    assert body.count("data-out-of-roster") == 1
    # The spec asks for a NOTE the PA can read, not just a test hook.
    assert "still allowed to report" in body


def test_a_teacher_cannot_open_or_save_the_page(client):
    make_teacher(client)
    assert client.get(reverse("support:reporters")).status_code == 403
    assert client.post(reverse("support:reporters"), {}).status_code == 403
