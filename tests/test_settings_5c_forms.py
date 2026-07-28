import io
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

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


def _png_file(name="logo.png", size=(4, 4), mode="RGB", fmt="PNG", noise=False):
    buf = io.BytesIO()
    if noise:
        image = Image.frombytes(mode, size, os.urandom(size[0] * size[1] * len(mode)))
    else:
        image = Image.new(mode, size)
    image.save(buf, fmt)
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type="image/png")


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


def test_branding_file_input_renders_field_scoped_hooks(db):
    """The generalized widget scopes its JS hooks per field so a second file field
    cannot cross-fire with the logo's."""
    html = str(BrandingForm(instance=Institution.load())["logo"])
    assert 'data-file-field="logo"' in html
    assert "data-file-input" in html
    assert "data-file-thumb" in html
    assert "data-logo-input" not in html


def test_branding_file_input_logo_copy_is_unchanged(db):
    """The refactor must not retire the five existing logo msgids."""
    html = str(BrandingForm(instance=Institution.load())["logo"])
    assert "Upload logo" in html
    assert "No logo yet" in html


# ── Favicon upload validation ──────────────────────────────────────────────


def _post(**overrides):
    data = _branding_data()
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "upload,message",
    [
        # Rule 1 -- bytes. A 512px NOISE png reliably exceeds 256 KB while staying
        # inside the dimension ceiling; a flat one would compress to a few KB.
        (
            lambda: _png_file("big.png", size=(512, 512), noise=True),
            "The favicon must be 256 KB or smaller.",
        ),
        # Rule 2 -- extension. NOT .svg: Django's validate_image_file_extension runs
        # before clean_favicon and rejects .svg with its own stock message, so a
        # .svg fixture never reaches rule 2. .gif is in Django's allowlist but not
        # ours.
        (
            lambda: _png_file("mark.gif", size=(256, 256)),
            "The favicon must be a .png file.",
        ),
        # Rule 3 -- decoded format. Must be .png-NAMED or rule 2 fires first.
        (
            lambda: _png_file("mark.png", size=(256, 256), fmt="ICO"),
            "The favicon must be a PNG image.",
        ),
        (
            lambda: _png_file("mark.png", size=(256, 256), fmt="JPEG"),
            "The favicon must be a PNG image.",
        ),
        # Rule 4 -- square.
        (
            lambda: _png_file("mark.png", size=(256, 200)),
            "The favicon must be square - crop it to equal width and height first.",
        ),
        # Rule 5 -- dimensions. The over-ceiling fixture must be FLAT (compresses to
        # a few KB) or rule 1 fires first.
        (
            lambda: _png_file("mark.png", size=(32, 32)),
            "The favicon must be between 192 and 512 pixels.",
        ),
        (
            lambda: _png_file("mark.png", size=(1024, 1024)),
            "The favicon must be between 192 and 512 pixels.",
        ),
        # Violates rules 1 AND 5 at once. This is the ONLY fixture that makes the
        # check ORDER observable: every other one breaks exactly one rule, so
        # reordering the checks changes no message at all.
        (
            lambda: _png_file("mark.png", size=(1024, 1024), noise=True),
            "The favicon must be 256 KB or smaller.",
        ),
    ],
)
def test_favicon_refusals(db, upload, message):
    form = BrandingForm(_post(), {"favicon": upload()}, instance=Institution.load())
    assert not form.is_valid()
    assert form.errors["favicon"] == [message]


@pytest.mark.parametrize("size", [(192, 192), (512, 512), (256, 256)])
def test_favicon_accepts_square_png_within_bounds(db, size):
    form = BrandingForm(
        _post(),
        {"favicon": _png_file("mark.png", size=size)},
        instance=Institution.load(),
    )
    assert form.is_valid(), form.errors


def test_favicon_accepts_uppercase_extension(db):
    form = BrandingForm(
        _post(),
        {"favicon": _png_file("MARK.PNG", size=(256, 256))},
        instance=Institution.load(),
    )
    assert form.is_valid(), form.errors


@pytest.mark.parametrize("name", ["mark.svg", "mark.html"])
def test_favicon_disguised_extensions_are_refused_by_django(db, name):
    """PNG bytes under a misleading name. Asserts only THAT the field errors --
    the message is Django's stock validate_image_file_extension text, not ours."""
    form = BrandingForm(
        _post(),
        {"favicon": _png_file(name, size=(256, 256))},
        instance=Institution.load(),
    )
    assert not form.is_valid()
    assert "favicon" in form.errors


def test_favicon_genuine_svg_is_refused_by_django(db):
    """The OTHER message-agnostic layer, and the one the stored-XSS argument rests
    on: real SVG bytes fail forms.ImageField.to_python (Pillow cannot open them)
    with invalid_image, before validate_image_file_extension or clean_favicon.

    _png_file cannot build this -- it always writes through Pillow -- so the bytes
    are raw.
    """
    upload = SimpleUploadedFile(
        "mark.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg"/>',
        content_type="image/svg+xml",
    )
    form = BrandingForm(_post(), {"favicon": upload}, instance=Institution.load())
    assert not form.is_valid()
    assert "favicon" in form.errors


def test_favicon_untouched_save_does_not_raise(db, settings, tmp_path):
    """The regression test for a 500 on EVERY subsequent Branding save.

    FileField.clean returns the existing FieldFile when the field is not touched,
    and a FieldFile has .size but NO .image -- so any value.image access explodes.
    """
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", _png_file("mark.png", size=(256, 256)), save=True)
    form = BrandingForm(_post(), {}, instance=Institution.load())
    assert form.is_valid(), form.errors


def test_favicon_clear_empties_the_field(db, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    inst = Institution.load()
    inst.favicon.save("mark.png", _png_file("mark.png", size=(256, 256)), save=True)
    form = BrandingForm(
        _post(**{"favicon-clear": "on"}), {}, instance=Institution.load()
    )
    assert form.is_valid(), form.errors
    form.save()
    assert not Institution.load().favicon
