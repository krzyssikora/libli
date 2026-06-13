from institution.models import BrandColor
from institution.models import Institution


def test_load_creates_and_returns_singleton():
    first = Institution.load()
    second = Institution.load()
    assert first.pk == second.pk == 1
    assert Institution.objects.count() == 1


def test_saving_always_uses_pk_1():
    inst = Institution(name="Greenfield")
    inst.save()
    assert inst.pk == 1
    assert Institution.objects.count() == 1  # never inserts a duplicate row


def test_defaults():
    inst = Institution.load()
    assert inst.signup_policy == "invite"
    assert inst.default_theme == "auto"
    assert inst.default_language == "en"
    assert inst.enabled_languages == ["en", "pl"]
    assert inst.allowed_email_domains == []


def test_brand_colors_are_extensible():
    # Use non-default keys: primary/accent get seeded by the data migration added
    # later in this task (Step 6), so re-creating them here would violate the
    # (institution, key) uniqueness. The seeded-colors assertion lives in Step 7.
    inst = Institution.load()
    BrandColor.objects.create(institution=inst, key="surface", value="#F4F1EA")
    BrandColor.objects.create(
        institution=inst, key="highlight", value="#E76F51"
    )  # future colors, no schema change
    keys = set(inst.brand_colors.values_list("key", flat=True))
    assert {"surface", "highlight"} <= keys
    assert inst.brand_colors.get(key="surface").value == "#F4F1EA"


def test_default_brand_colors_seeded():
    # Seeded by migration 0002_seed_branding when the test DB is built.
    inst = Institution.load()
    keys = set(inst.brand_colors.values_list("key", flat=True))
    assert {"primary", "accent"} <= keys
    assert inst.brand_colors.get(key="primary").value == "#147E78"
