import pytest


@pytest.mark.django_db
def test_names_locked_defaults_false_and_is_settable():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="nl", password=TEST_PASSWORD)
    assert u.names_locked is False
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    u.refresh_from_db()
    assert u.names_locked is True
