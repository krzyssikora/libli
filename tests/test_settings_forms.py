import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User
from core.forms import UserSettingsForm
from institution.forms import MAX_LOGO_BYTES
from institution.forms import InstitutionSettingsForm
from institution.models import Institution
from tests.factories import TEST_PASSWORD


def _base(**over):
    data = {"theme": "auto", "language": "en", "display_name": "X", "email": ""}
    data.update(over)
    return data


@pytest.mark.django_db
def test_clean_email_lowercases():
    u = User.objects.create_user(username="lc", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="Mixed@Case.EDU"), instance=u)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] == "mixed@case.edu"


@pytest.mark.django_db
def test_clean_email_blank_becomes_none():
    u = User.objects.create_user(
        username="bk", email="bk@school.edu", password=TEST_PASSWORD
    )
    form = UserSettingsForm(_base(email="   "), instance=u)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["email"] is None


@pytest.mark.django_db
def test_rejects_duplicate_user_email_path_a():
    # path (a): another User row already holds this email (model unique=True).
    User.objects.create_user(
        username="other", email="taken@school.edu", password=TEST_PASSWORD
    )
    u = User.objects.create_user(username="me", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="taken@school.edu"), instance=u)
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_rejects_verified_emailaddress_clash_path_b():
    # path (b): a *verified* allauth EmailAddress on another user (no User.email row).
    from allauth.account.models import EmailAddress

    other = User.objects.create_user(username="o2", password=TEST_PASSWORD)
    EmailAddress.objects.create(
        user=other, email="held@school.edu", verified=True, primary=True
    )
    u = User.objects.create_user(username="me2", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="held@school.edu"), instance=u)
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_rejects_verified_emailaddress_clash_is_case_insensitive():
    # path (b), mixed-case submission: the guard uses iexact, so a mixed-case
    # address must still clash with the stored lowercase verified EmailAddress.
    from allauth.account.models import EmailAddress

    other = User.objects.create_user(username="o3", password=TEST_PASSWORD)
    EmailAddress.objects.create(
        user=other, email="held@school.edu", verified=True, primary=True
    )
    u = User.objects.create_user(username="me3", password=TEST_PASSWORD)
    form = UserSettingsForm(_base(email="Held@School.EDU"), instance=u)
    assert not form.is_valid()
    assert "email" in form.errors


@pytest.mark.django_db
def test_unchanged_blank_email_is_not_in_changed_data():
    u = User.objects.create_user(
        username="nb", password=TEST_PASSWORD
    )  # email NULL at rest
    form = UserSettingsForm(_base(email=""), instance=u)
    assert form.is_valid(), form.errors
    assert "email" not in form.changed_data


# ---------------------------------------------------------------------------
# InstitutionSettingsForm tests
# ---------------------------------------------------------------------------


def _png_upload(name="logo.png", size_pad=0):
    """A real, Pillow-decodable PNG (optionally padded to exceed a size limit)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    data = buf.getvalue() + (b"\0" * size_pad)
    return SimpleUploadedFile(name, data, content_type="image/png")


def _inst_data(**over):
    data = {
        "name": "Greenfield School",
        "enabled_languages": ["en", "pl"],
        "default_language": "en",
        "default_theme": "auto",
        "signup_policy": "invite",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_institution_form_accepts_name_and_logo():
    inst = Institution.load()
    form = InstitutionSettingsForm(_inst_data(), {"logo": _png_upload()}, instance=inst)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_institution_form_requires_name():
    inst = Institution.load()
    form = InstitutionSettingsForm(_inst_data(name=""), instance=inst)
    assert not form.is_valid()
    assert "name" in form.errors


@pytest.mark.django_db
def test_clean_logo_rejects_oversized():
    inst = Institution.load()
    big = _png_upload(size_pad=MAX_LOGO_BYTES + 1)
    form = InstitutionSettingsForm(_inst_data(), {"logo": big}, instance=inst)
    assert not form.is_valid()
    assert "logo" in form.errors


@pytest.mark.django_db
def test_logo_clear_checkbox_does_not_raise():
    # No new file + clear set: clean_logo must short-circuit (no .size on False).
    inst = Institution.load()
    form = InstitutionSettingsForm(_inst_data(**{"logo-clear": "on"}), instance=inst)
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_non_image_upload_rejected_by_imagefield():
    inst = Institution.load()
    bogus = SimpleUploadedFile(
        "logo.png", b"not really an image", content_type="image/png"
    )
    form = InstitutionSettingsForm(_inst_data(), {"logo": bogus}, instance=inst)
    assert not form.is_valid()
    assert "logo" in form.errors
