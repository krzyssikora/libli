import pytest

from tests.factories import make_verified_user


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


@pytest.mark.django_db
def test_user_roles_anonymous_all_false(rf):
    from django.contrib.auth.models import AnonymousUser

    from core.context_processors import user_roles

    request = rf.get("/")
    request.user = AnonymousUser()
    assert user_roles(request) == {
        "is_student": False,
        "is_teacher": False,
        "is_course_admin": False,
        "is_platform_admin": False,
    }


@pytest.mark.django_db
def test_user_roles_reflects_group_membership(rf):
    from django.contrib.auth.models import Group

    from core.context_processors import user_roles
    from institution.roles import PLATFORM_ADMIN

    user = make_verified_user(username="pa", email="pa@school.edu")
    user.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    request = rf.get("/")
    request.user = user
    ctx = user_roles(request)
    assert ctx["is_platform_admin"] is True
    assert ctx["is_student"] is False
