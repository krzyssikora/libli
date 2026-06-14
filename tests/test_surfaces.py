import pytest


@pytest.mark.django_db
def test_site_config_includes_signup_policy_default():
    from core.services import get_site_config

    assert get_site_config()["signup_policy"] == "invite"


@pytest.mark.django_db
def test_site_config_signup_policy_reflects_save():
    from core.services import get_site_config
    from institution.models import Institution

    assert get_site_config()["signup_policy"] == "invite"
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()  # fires invalidate_site_config
    assert get_site_config()["signup_policy"] == "open"
