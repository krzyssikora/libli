import pytest

from institution.forms import BrandingForm
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
