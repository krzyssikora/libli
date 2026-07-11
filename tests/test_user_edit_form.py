# tests/test_user_edit_form.py
import pytest


def _form(instance, data, editing_self=False):
    from accounts.forms import UserEditForm

    return UserEditForm(data, instance=instance, editing_self=editing_self)


@pytest.mark.django_db
def test_saves_first_and_last_name():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="u1", password=TEST_PASSWORD)
    f = _form(u, {"first_name": "Ada", "last_name": "Byron", "role": ""})
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Ada", "Byron")


@pytest.mark.django_db
def test_sync_checkbox_absent_without_sso_app():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="u2", password=TEST_PASSWORD)
    f = _form(u, {"role": ""})
    assert "sync_name_from_sso" not in f.fields


@pytest.mark.django_db
def test_sync_checkbox_present_with_sso_app(db):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    make_oidc_app()
    u = User.objects.create_user(username="u3", password=TEST_PASSWORD)
    f = _form(u, {"role": ""})
    assert "sync_name_from_sso" in f.fields
    # Initial reflects NOT names_locked (an unlocked user syncs -> box checked).
    assert f.fields["sync_name_from_sso"].initial is True


@pytest.mark.django_db
def test_unchecking_sync_locks_names(db):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    make_oidc_app()
    u = User.objects.create_user(username="u4", password=TEST_PASSWORD)
    # Checkbox omitted from POST == unchecked.
    f = _form(u, {"first_name": "Man", "last_name": "Ual", "role": ""})
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert u.names_locked is True


@pytest.mark.django_db
def test_checking_sync_unlocks_names(db):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    make_oidc_app()
    u = User.objects.create_user(username="u5", password=TEST_PASSWORD)
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    f = _form(u, {"role": "", "sync_name_from_sso": "on"})
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert u.names_locked is False


@pytest.mark.django_db
def test_name_fields_editable_when_editing_self():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="u6", password=TEST_PASSWORD)
    f = _form(u, {"first_name": "Self", "last_name": "Edit", "role": ""}, editing_self=True)
    assert f.fields["first_name"].disabled is False
    assert f.fields["last_name"].disabled is False
    assert f.is_valid(), f.errors
    f.save()
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Self", "Edit")
