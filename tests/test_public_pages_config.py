import pytest

from core.services import _DEFAULTS
from core.services import get_site_config
from institution.models import Institution

NEW_KEYS = {
    "controller_name",
    "controller_address",
    "contact_email",
    "supervisory_authority",
    "demo_instance",
    "notification_retention_days",
}


def test_defaults_carry_every_new_key_with_the_right_values():
    assert NEW_KEYS <= set(_DEFAULTS)
    assert _DEFAULTS["demo_instance"] is False
    assert _DEFAULTS["notification_retention_days"] == 90
    for key in (
        "controller_name",
        "controller_address",
        "contact_email",
        "supervisory_authority",
    ):
        assert _DEFAULTS[key] == ""


@pytest.mark.django_db
def test_bundle_carries_every_new_key_with_an_institution_row():
    Institution.load()
    assert NEW_KEYS <= set(get_site_config())


@pytest.mark.django_db
def test_bundle_carries_every_new_key_with_NO_institution_row():
    # The public pages must render on a fresh install. _build() returns
    # dict(_DEFAULTS) here, so key parity between the two paths is load-bearing.
    Institution.objects.all().delete()
    from core.services import invalidate_site_config

    invalidate_site_config()
    assert NEW_KEYS <= set(get_site_config())


@pytest.mark.django_db
def test_retention_zero_survives_the_bundle():
    # The `inst.x or _DEFAULTS[x]` idiom every other line uses would rewrite
    # this to 90 -- inverting the meaning of "never purge".
    inst = Institution.load()
    inst.notification_retention_days = 0
    inst.save()
    assert get_site_config()["notification_retention_days"] == 0


@pytest.mark.django_db
def test_demo_instance_false_survives_the_bundle():
    inst = Institution.load()
    inst.demo_instance = False
    inst.save()
    assert get_site_config()["demo_instance"] is False


@pytest.mark.django_db
def test_demo_instance_true_reaches_the_bundle():
    inst = Institution.load()
    inst.demo_instance = True
    inst.save()
    assert get_site_config()["demo_instance"] is True
