import pytest

from courses import validators as cv
from institution.forms import AccessForm
from institution.forms import BrandingForm
from institution.forms import UploadsForm
from institution.forms import normalize_hex
from institution.models import BrandColor
from institution.models import Institution


def _branding_data(**over):
    data = {
        "name": "Greenfield",
        "enabled_languages": ["en", "pl"],
        "default_language": "en",
        "default_theme": "auto",
        "primary": "#123ABC",
        "accent": "#abcdef",
    }
    data.update(over)
    return data


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("#abc", "#aabbcc"),
        ("#AABBCC", "#aabbcc"),
        ("#147E78", "#147e78"),
        ("rgb(1,2,3)", None),
        ("nonsense", None),
        ("", None),
    ],
)
def test_normalize_hex(raw, expected):
    assert normalize_hex(raw) == expected


@pytest.mark.django_db
def test_branding_form_saves_colours_lowercased():
    inst = Institution.load()
    form = BrandingForm(_branding_data(primary="#123ABC"), instance=inst)
    assert form.is_valid(), form.errors
    form.save()
    assert BrandColor.objects.get(institution=inst, key="primary").value == "#123abc"
    assert BrandColor.objects.get(institution=inst, key="accent").value == "#abcdef"


@pytest.mark.django_db
def test_branding_form_rejects_non_hex_colour():
    inst = Institution.load()
    form = BrandingForm(_branding_data(primary="rgb(1,2,3)"), instance=inst)
    assert not form.is_valid()
    assert "primary" in form.errors


@pytest.mark.django_db
def test_branding_form_seeds_from_existing_brandcolor():
    inst = Institution.load()
    # use update_or_create: seed migration 0002 pre-creates primary/accent rows
    BrandColor.objects.update_or_create(
        institution=inst, key="primary", defaults={"value": "#fff"}
    )
    form = BrandingForm(instance=inst)  # unbound GET render
    assert form.initial["primary"] == "#ffffff"  # #fff expanded + lowercased


@pytest.mark.django_db
def test_branding_form_seeds_default_when_no_row():
    from core.services import PRIMARY_DEFAULT

    inst = Institution.load()
    form = BrandingForm(instance=inst)
    assert form.initial["primary"] == PRIMARY_DEFAULT.lower()


@pytest.mark.django_db
def test_branding_form_uppercase_stored_row_still_saves():
    # A pre-existing uppercase 6-hex row must seed AND a name-only save must succeed.
    inst = Institution.load()
    # use update_or_create: seed migration 0002 pre-creates primary/accent rows
    BrandColor.objects.update_or_create(
        institution=inst, key="primary", defaults={"value": "#AABBCC"}
    )
    seed = BrandingForm(instance=inst).initial
    form = BrandingForm(
        _branding_data(name="Renamed", primary=seed["primary"], accent=seed["accent"]),
        instance=inst,
    )
    assert form.is_valid(), form.errors
    form.save()
    assert Institution.load().name == "Renamed"


@pytest.mark.django_db
def test_access_form_normalizes_domains():
    inst = Institution.load()
    raw = "  @School.EDU \nschool.edu\nmail.example.com\n"
    form = AccessForm(
        {"signup_policy": "open", "allowed_email_domains": raw},
        instance=inst,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["allowed_email_domains"] == [
        "school.edu",
        "mail.example.com",
    ]


@pytest.mark.django_db
def test_access_form_accepts_subdomains():
    inst = Institution.load()
    form = AccessForm(
        {"signup_policy": "invite", "allowed_email_domains": "mail.example.com"},
        instance=inst,
    )
    assert form.is_valid(), form.errors


@pytest.mark.django_db
def test_access_form_rejects_garbage_domain():
    inst = Institution.load()
    form = AccessForm(
        {"signup_policy": "invite", "allowed_email_domains": "not a domain"},
        instance=inst,
    )
    assert not form.is_valid()
    assert "allowed_email_domains" in form.errors


@pytest.mark.django_db
def test_access_form_blank_allowlist_is_empty_list():
    inst = Institution.load()
    form = AccessForm(
        {"signup_policy": "invite", "allowed_email_domains": "  \n "},
        instance=inst,
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["allowed_email_domains"] == []


@pytest.mark.django_db
def test_access_form_seeds_textarea_from_list():
    inst = Institution.load()
    inst.allowed_email_domains = ["a.com", "b.org"]
    inst.save()
    form = AccessForm(instance=inst)
    assert form.initial["allowed_email_domains"] == "a.com\nb.org"


def _uploads_data(**over):
    data = {
        "allowed_image_extensions": ["png", "jpg"],
        "allowed_video_extensions": ["mp4"],
        "max_image_mib": "3",
        "max_video_mib": "100",
    }
    data.update(over)
    return data


@pytest.mark.django_db
def test_uploads_form_saves_subset():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(), instance=inst)
    assert form.is_valid(), form.errors
    form.save()
    inst.refresh_from_db()
    assert inst.allowed_image_extensions == ["png", "jpg"]
    assert inst.max_image_mib == 3


@pytest.mark.django_db
def test_uploads_form_rejects_out_of_safe_set():
    inst = Institution.load()
    form = UploadsForm(
        _uploads_data(allowed_image_extensions=["png", "svg"]), instance=inst
    )
    assert not form.is_valid()
    assert "allowed_image_extensions" in form.errors


@pytest.mark.django_db
def test_uploads_form_requires_at_least_one_per_kind():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(allowed_image_extensions=[]), instance=inst)
    assert not form.is_valid()
    assert "allowed_image_extensions" in form.errors


@pytest.mark.django_db
def test_uploads_form_rejects_over_ceiling():
    inst = Institution.load()
    form = UploadsForm(
        _uploads_data(max_image_mib=str(cv.MAX_IMAGE_MIB_CEILING + 1)), instance=inst
    )
    assert not form.is_valid()
    assert "max_image_mib" in form.errors


@pytest.mark.django_db
def test_uploads_form_rejects_zero_cap():
    inst = Institution.load()
    form = UploadsForm(_uploads_data(max_image_mib="0"), instance=inst)
    assert not form.is_valid()
    assert "max_image_mib" in form.errors


# ── Logo remove tests (Phase 5c UX gap fix) ────────────────────────────────


def _png_file(name="logo.png"):
    import io

    from django.core.files.base import ContentFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, "PNG")
    return ContentFile(buf.getvalue(), name=name)


@pytest.mark.django_db
def test_branding_form_logo_clear_removes_logo():
    """Submitting logo-clear=on with valid branding data clears an existing logo."""
    inst = Institution.load()
    inst.logo.save("test-logo.png", _png_file(), save=True)
    assert bool(inst.logo)

    data = _branding_data(**{"logo-clear": "on"})
    form = BrandingForm(data, files={}, instance=inst)
    assert form.is_valid(), form.errors
    form.save()

    inst.refresh_from_db()
    assert not inst.logo


@pytest.mark.django_db
def test_branding_form_logo_renders_thumbnail_and_remove_when_logo_set():
    """When a logo is set, the logo field renders a thumbnail and remove checkbox."""
    inst = Institution.load()
    inst.logo.save("test-logo-render.png", _png_file(), save=True)

    form = BrandingForm(instance=inst)
    html = str(form["logo"])

    assert 'name="logo-clear"' in html
    assert "<img" in html


@pytest.mark.django_db
def test_branding_form_logo_no_remove_when_no_logo():
    """When no logo is set, the rendered logo field omits the remove checkbox."""
    inst = Institution.load()
    inst.logo = None
    inst.save()

    form = BrandingForm(instance=inst)
    html = str(form["logo"])

    assert 'name="logo-clear"' not in html
