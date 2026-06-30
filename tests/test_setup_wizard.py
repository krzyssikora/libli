"""Phase 5e — first-run setup wizard: flag, gate, steps, finish, gating."""

import pytest


@pytest.mark.django_db
def test_institution_onboarded_defaults_false():
    from institution.models import Institution

    assert Institution.load().onboarded is False


@pytest.mark.django_db
def test_site_config_exposes_onboarded():
    from core.services import get_site_config
    from core.services import invalidate_site_config
    from institution.models import Institution

    invalidate_site_config()
    assert get_site_config()["onboarded"] is False
    inst = Institution.load()
    inst.onboarded = True
    inst.save()  # post_save signal drops the cache
    assert get_site_config()["onboarded"] is True


@pytest.mark.django_db
def test_site_config_onboarded_false_when_no_row():
    # _build() returns _DEFAULTS when pk=1 is absent; onboarded must default False.
    from core.services import _DEFAULTS

    assert _DEFAULTS["onboarded"] is False


@pytest.mark.django_db
def test_mark_onboarded_flips_flag_idempotently():
    from core.services import mark_onboarded
    from institution.models import Institution

    mark_onboarded()
    assert Institution.load().onboarded is True
    mark_onboarded()  # idempotent
    assert Institution.load().onboarded is True


@pytest.mark.django_db
def test_branding_fields_partial_renders_standalone(client):
    # The extracted fields partial must render given a `form` (no <form> wrapper).
    from django.template.loader import render_to_string

    from institution.forms import BrandingForm
    from institution.models import Institution

    html = render_to_string(
        "institution/manage/_branding_fields.html",
        {"form": BrandingForm(instance=Institution.load())},
    )
    assert "<form" not in html  # fields only — no nested form
    assert 'name="name"' in html  # the institution-name field is present
