"""Phase 5e — first-run setup wizard: flag, gate, steps, finish, gating."""

import pytest
from django.urls import reverse


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


# Task 3 — wizard skeleton (STEPS, frame, welcome, skip, routes, gating)


@pytest.mark.django_db
def test_welcome_requires_pa(client):
    from tests.factories import make_login

    make_login(client, "student")  # non-PA
    resp = client.get(reverse("institution:setup"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_welcome_renders_for_pa(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:setup"))
    assert resp.status_code == 200
    assert b"Step 1 of 5" in resp.content


@pytest.mark.django_db
def test_unknown_step_redirects_to_welcome(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "nope"}))
    assert resp.status_code == 302
    assert resp.url == reverse("institution:setup")


@pytest.mark.django_db
def test_skip_sets_session_and_redirects_home(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(reverse("institution:setup_skip"))
    assert resp.status_code == 302
    assert resp.url == reverse("home")
    assert client.session.get("setup_skipped") is True


# Task 4 — home login gate


@pytest.mark.django_db
def test_home_redirects_unonboarded_pa_to_wizard(client):
    from core.services import invalidate_site_config
    from tests.factories import make_pa

    make_pa(client)  # fresh Institution -> onboarded False
    invalidate_site_config()
    resp = client.get(reverse("home"))
    assert resp.status_code == 302
    assert resp.url == reverse("institution:setup")


@pytest.mark.django_db
def test_home_renders_for_onboarded_pa(client):
    from core.services import mark_onboarded
    from tests.factories import make_pa

    make_pa(client)
    mark_onboarded()
    resp = client.get(reverse("home"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_home_renders_for_pa_who_skipped_this_session(client):
    from core.services import invalidate_site_config
    from tests.factories import make_pa

    make_pa(client)
    client.post(reverse("institution:setup_skip"))  # sets session flag
    invalidate_site_config()
    resp = client.get(reverse("home"))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_home_does_not_redirect_non_pa(client):
    from tests.factories import make_login

    make_login(client, "student")  # no institution.change_institution
    resp = client.get(reverse("home"))
    assert resp.status_code == 200


# Task 5 — Identity & Access ModelForm steps


@pytest.mark.django_db
def test_identity_get_shows_current_name(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "identity"}))
    assert resp.status_code == 200
    assert b'name="name"' in resp.content


@pytest.mark.django_db
def test_identity_next_saves_and_advances_to_access(client):
    from institution.models import Institution
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        {
            "action": "next",
            "name": "Acme Academy",
            "enabled_languages": ["en", "pl"],
            "default_language": "en",
            "default_theme": "auto",
            "primary": "#147e78",
            "accent": "#c77b2a",
        },
    )
    assert resp.status_code == 302
    assert resp.url == reverse("institution:setup_step", kwargs={"step": "access"})
    assert Institution.load().name == "Acme Academy"


@pytest.mark.django_db
def test_identity_skip_advances_without_saving(client):
    from institution.models import Institution
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "identity"}),
        {"action": "skip"},
    )
    assert resp.status_code == 302
    assert resp.url == reverse("institution:setup_step", kwargs={"step": "access"})
    assert Institution.load().name == "My Institution"  # unchanged


@pytest.mark.django_db
def test_access_next_saves_signup_policy_and_advances_to_team(client):
    from institution.models import Institution
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "access"}),
        {
            "action": "next",
            "signup_policy": "open",
            "allowed_email_domains": "school.edu",
        },
    )
    assert resp.status_code == 302
    assert resp.url == reverse("institution:setup_step", kwargs={"step": "team"})
    assert Institution.load().signup_policy == "open"


# Task 6 — Team step (invite + pending list + Next-advances + error/domain warning)


@pytest.mark.django_db
def test_team_invite_lists_pending(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "team"}),
        {"action": "invite", "email": "newkid@school.edu", "role": "Student"},
        follow=True,
    )
    assert resp.status_code == 200
    assert b"newkid@school.edu" in resp.content


@pytest.mark.django_db
def test_team_pending_excludes_accepted_and_expired(client):
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import Invitation
    from tests.factories import make_pa

    make_pa(client)
    Invitation.objects.create(email="pending@school.edu", role="Student")
    accepted = Invitation.objects.create(email="accepted@school.edu", role="Student")
    accepted.accepted_at = timezone.now()
    accepted.save()
    expired = Invitation.objects.create(email="expired@school.edu", role="Student")
    expired.expires_at = timezone.now() - timedelta(days=1)
    expired.save()
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "team"}))
    assert b"pending@school.edu" in resp.content
    assert b"accepted@school.edu" not in resp.content
    assert b"expired@school.edu" not in resp.content


@pytest.mark.django_db
def test_team_invite_existing_account_shows_error(client):
    from accounts.models import User
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_pa

    make_pa(client)
    User.objects.create_user(
        username="taken", email="taken@school.edu", password=TEST_PASSWORD
    )
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "team"}),
        {"action": "invite", "email": "taken@school.edu", "role": "Student"},
    )
    assert resp.status_code == 200  # re-render, not 500
    assert b"already" in resp.content.lower()  # InvitationError message on the field


@pytest.mark.django_db
def test_team_next_advances_without_validating(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "team"}),
        {"action": "next"},  # empty email must not block advancing
    )
    assert resp.status_code == 302
    assert resp.url == reverse("institution:setup_step", kwargs={"step": "sso"})


@pytest.mark.django_db
def test_team_invite_warns_on_out_of_allowlist_domain(client):
    from institution.models import Institution
    from tests.factories import make_pa

    make_pa(client)
    inst = Institution.load()
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "team"}),
        {"action": "invite", "email": "outsider@elsewhere.com", "role": "Student"},
        follow=True,
    )
    assert b"elsewhere.com" in resp.content  # domain-mismatch warning surfaced


# Task 7 — SSO step + Finish


@pytest.mark.django_db
def test_sso_get_shows_redirect_uri(client):
    from tests.factories import make_pa

    make_pa(client)
    resp = client.get(reverse("institution:setup_step", kwargs={"step": "sso"}))
    assert resp.status_code == 200
    assert b"/accounts/oidc/sso/login/callback/" in resp.content


@pytest.mark.django_db
def test_finish_blank_sso_onboards_and_redirects_home(client):
    from allauth.socialaccount.models import SocialApp

    from institution.models import Institution
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "sso"}),
        {
            "action": "finish",
            "enabled": "",
            "name": "",
            "server_url": "",
            "client_id": "",
            "client_secret": "",
        },
    )
    assert resp.status_code == 302
    assert resp.url == reverse("home")
    assert Institution.load().onboarded is True
    assert SocialApp.objects.count() == 0  # blank SSO no-ops


@pytest.mark.django_db
def test_finish_saves_sso_then_onboards(client):
    from allauth.socialaccount.models import SocialApp

    from institution.models import Institution
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "sso"}),
        {
            "action": "finish",
            "enabled": "on",
            "name": "Acme",
            "server_url": "idp.example.test/",
            "client_id": "cid",
            "client_secret": "sek",
        },
    )
    assert resp.status_code == 302
    assert resp.url == reverse("home")
    assert Institution.load().onboarded is True
    app = SocialApp.objects.get(provider="openid_connect")
    assert app.settings["server_url"] == "https://idp.example.test"


@pytest.mark.django_db
def test_sso_skip_onboards_without_saving(client):
    from allauth.socialaccount.models import SocialApp

    from institution.models import Institution
    from tests.factories import make_pa

    make_pa(client)
    resp = client.post(
        reverse("institution:setup_step", kwargs={"step": "sso"}),
        {"action": "skip"},
    )
    assert resp.status_code == 302
    assert resp.url == reverse("home")
    assert Institution.load().onboarded is True
    assert SocialApp.objects.count() == 0


@pytest.mark.django_db
def test_finish_clears_skip_session_flag(client):
    from tests.factories import make_pa

    make_pa(client)
    client.post(reverse("institution:setup_skip"))
    assert client.session.get("setup_skipped") is True
    client.post(
        reverse("institution:setup_step", kwargs={"step": "sso"}),
        {
            "action": "finish",
            "enabled": "",
            "name": "",
            "server_url": "",
            "client_id": "",
            "client_secret": "",
        },
    )
    assert client.session.get("setup_skipped") is None
