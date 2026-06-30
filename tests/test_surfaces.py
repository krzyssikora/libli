import pytest
from django.urls import reverse

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


@pytest.mark.django_db
def test_user_settings_requires_login(client):
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_user_settings_get_renders(client):
    user = make_verified_user(username="settingsuser", email="setu@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 200
    assert b"settingsuser" in resp.content  # read-only username shown (distinctive)


@pytest.mark.django_db
def test_user_settings_post_persists_and_resyncs(client):
    user = make_verified_user(username="su2", email="su2@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            "theme": "dark",
            "language": "pl",
            "display_name": "Sue",
            "username": "hacker",
            "email": "su2@school.edu",
        },
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.theme == "dark"
    assert user.language == "pl"
    assert user.display_name == "Sue"
    assert user.username == "su2"  # username NOT editable (absent from the form)
    assert client.session["_language"] == "pl"
    assert resp.cookies["libli_theme"].value == "dark"


@pytest.mark.django_db
def test_user_settings_rejects_disabled_language(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]  # pl disabled
    inst.save()
    user = make_verified_user(username="su3", email="su3@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            "theme": "auto",
            "language": "pl",
            "display_name": "",
            "email": "su3@school.edu",
        },
    )
    assert resp.status_code == 200  # re-render with errors, no redirect
    user.refresh_from_db()
    assert user.language == "en"  # unchanged (default)


def _make_platform_admin(username, email):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()  # idempotent; assigns institution.change_institution to PA group
    user = make_verified_user(username=username, email=email)
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


@pytest.mark.django_db
def test_institution_settings_anonymous_redirects(client):
    resp = client.get("/settings/institution/")  # legacy URL, retired name in 5c
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_institution_settings_non_pa_forbidden(client):
    user = make_verified_user(username="nopa", email="nopa@school.edu")
    client.force_login(user)
    resp = client.get("/settings/institution/")  # legacy URL, retired name in 5c
    assert resp.status_code == 403


@pytest.mark.django_db
def test_institution_settings_redirects_to_manage_settings(client):
    # 5c cutover: the legacy URL name still resolves but now 302-redirects a PA to
    # the new /manage/settings/ surface (institution:settings).
    user = _make_platform_admin("redir", "redir@school.edu")
    client.force_login(user)
    resp = client.get("/settings/institution/")  # legacy URL, retired name in 5c
    assert resp.status_code == 302
    assert resp["Location"] == reverse("institution:settings")


@pytest.mark.django_db
def test_account_menu_has_settings_link(client):
    user = make_verified_user(username="m1", email="m1@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert reverse("core:user_settings").encode() in resp.content
    # non-PA: no institution-settings link
    assert reverse("institution:settings").encode() not in resp.content


@pytest.mark.django_db
def test_account_menu_shows_institution_settings_for_pa(client):
    from core.services import mark_onboarded

    user = _make_platform_admin("m2", "m2@school.edu")
    client.force_login(user)
    mark_onboarded()  # configured install: PA sees the home page, not the wizard
    resp = client.get(reverse("home"))
    assert reverse("institution:settings").encode() in resp.content


def _make_in_group(username, email, group_name):
    from django.contrib.auth.models import Group

    user = make_verified_user(username=username, email=email)
    user.groups.add(Group.objects.get_or_create(name=group_name)[0])
    return user


@pytest.mark.django_db
def test_dashboard_student_sees_learning_not_admin(client):
    from institution.roles import STUDENT

    user = _make_in_group("st", "st@school.edu", STUDENT)
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert b'data-section="learning"' in resp.content
    assert b'data-section="admin"' not in resp.content


@pytest.mark.django_db
def test_dashboard_platform_admin_sees_admin_section(client):
    from core.services import mark_onboarded

    user = _make_platform_admin("da", "da@school.edu")
    client.force_login(user)
    mark_onboarded()  # configured install: PA sees the home page, not the wizard
    resp = client.get(reverse("home"))
    assert b'data-section="admin"' in resp.content
    assert reverse("institution:settings").encode() in resp.content


@pytest.mark.django_db
def test_dashboard_no_group_sees_generic(client):
    user = make_verified_user(username="ng", email="ng@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    assert b'data-section="generic"' in resp.content


@pytest.mark.django_db
def test_dashboard_lists_enrolled_courses(client):
    from courses.models import Course
    from courses.models import Enrollment

    user = make_verified_user(username="enr", email="enr@school.edu")
    course = Course.objects.create(title="Algebra I", slug="algebra-i")
    Enrollment.objects.create(student=user, course=course)
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert resp.status_code == 200
    # The enrolled course is listed and links to its outline.
    assert b"Algebra I" in resp.content
    assert (
        reverse("courses:course_outline", kwargs={"slug": "algebra-i"}).encode()
        in resp.content
    )
    # The empty-state placeholder is gone once a course exists.
    assert b"No courses yet." not in resp.content


@pytest.mark.django_db
def test_dashboard_shows_manage_link_for_owner(client):
    from courses.models import Course

    user = make_verified_user(username="own", email="own@school.edu")
    Course.objects.create(title="Owned", slug="owned", owner=user)
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert reverse("courses:manage_course_list").encode() in resp.content


@pytest.mark.django_db
def test_dashboard_no_manage_link_for_plain_user(client):
    user = make_verified_user(username="plain", email="plain@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert reverse("courses:manage_course_list").encode() not in resp.content


@pytest.mark.django_db
def test_nav_has_courses_link_when_authenticated(client):
    user = make_verified_user(username="navc", email="navc@school.edu")
    client.force_login(user)
    resp = client.get(reverse("home"))
    assert reverse("courses:my_courses").encode() in resp.content


@pytest.mark.django_db
def test_landing_anonymous_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"data-account-menu" not in resp.content  # anonymous variant
    assert reverse("account_login").encode() in resp.content  # hero CTA


@pytest.mark.django_db
def test_landing_authenticated_redirects_home(client):
    user = make_verified_user(username="ld", email="ld@school.edu")
    client.force_login(user)
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp["Location"] == reverse("home")


@pytest.mark.django_db
def test_landing_hides_header_cta(rf):
    from django.contrib.auth.models import AnonymousUser
    from django.urls import resolve

    from core.context_processors import ui_prefs

    request = rf.get("/")
    request.user = AnonymousUser()
    request.COOKIES = {}
    request.resolver_match = resolve("/")  # view_name == "landing"
    assert ui_prefs(request)["hide_auth_cta"] is True


@pytest.mark.django_db
def test_landing_signup_cta_only_when_open(client):
    from institution.models import Institution

    # default policy = invite -> no create-account CTA
    resp = client.get("/")
    assert reverse("account_signup").encode() not in resp.content
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()  # fires invalidate_site_config
    resp = client.get("/")
    assert reverse("account_signup").encode() in resp.content


@pytest.mark.django_db
def test_landing_sso_button_visibility_and_url(client):
    # no OIDC app -> no SSO button
    assert b"/accounts/oidc/" not in client.get("/").content
    from tests._sso import make_oidc_app

    make_oidc_app()  # provider_id="testidp"
    body = client.get("/").content
    assert b"/accounts/oidc/testidp/login/" in body


@pytest.mark.django_db
def test_reclamp_resets_disabled_session_language(client):
    from institution.models import Institution

    user = make_verified_user(username="rc", email="rc@school.edu")
    user.language = "pl"
    user.save()
    client.force_login(user)
    # Pin the session language explicitly so the test isolates the re-clamp branch and
    # does not depend on login-receiver timing.
    session = client.session
    session["_language"] = "pl"
    session.save()
    assert client.session["_language"] == "pl"
    inst = Institution.load()
    inst.enabled_languages = ["en"]  # disable pl
    inst.default_language = "en"
    inst.save()
    client.get(reverse("home"))  # seeder observes pl-disabled -> resets to en
    assert client.session["_language"] == "en"
    user.refresh_from_db()
    assert user.language == "pl"  # stored choice NOT mutated


@pytest.mark.django_db
def test_404_renders_branded(client):
    resp = client.get("/this-path-does-not-exist/")
    assert resp.status_code == 404
    assert b"libli" in resp.content  # shell brand present


@pytest.mark.django_db
def test_500_template_is_self_contained():
    from django.template.loader import render_to_string

    from core.services import ACCENT_DEFAULT
    from core.services import PRIMARY_DEFAULT

    html = render_to_string("500.html").lower()  # NO request/context
    assert "app-header" not in html  # does NOT extend the shell
    # Drift guard, case-insensitive so a lowercase-hex formatter doesn't break it.
    assert PRIMARY_DEFAULT.lower() in html
    assert ACCENT_DEFAULT.lower() in html
    # Source guard: no request-dependent tags (they'd render empty here but break the
    # real empty-context 500 handler).
    from pathlib import Path

    from django.conf import settings

    src = (Path(settings.BASE_DIR) / "templates/500.html").read_text(encoding="utf-8")
    for tag in ("{% url", "{% trans", "{% static", "{% blocktrans"):
        assert tag not in src


@pytest.mark.django_db
def test_user_settings_email_change_syncs_single_primary(client):
    from allauth.account.models import EmailAddress

    user = make_verified_user(username="ec", email="ec-old@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            "theme": "auto",
            "language": "en",
            "display_name": "E",
            "email": "ec-new@school.edu",
        },
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.email == "ec-new@school.edu"
    primaries = EmailAddress.objects.filter(user=user, primary=True)
    assert primaries.count() == 1
    assert primaries.first().email == "ec-new@school.edu"


@pytest.mark.django_db
def test_user_settings_clearing_email_deletes_rows(client):
    from allauth.account.models import EmailAddress

    user = make_verified_user(username="cl", email="cl@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "auto", "language": "en", "display_name": "C", "email": ""},
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.email is None
    assert EmailAddress.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_user_settings_sso_badge_context_present(client):
    from allauth.socialaccount.models import SocialAccount

    from tests._sso import make_oidc_app

    app = (
        make_oidc_app()
    )  # provider="openid_connect", provider_id="testidp", name="Test IdP"
    user = make_verified_user(username="ss", email="ss@school.edu")
    SocialAccount.objects.create(
        user=user,
        provider=app.provider_id,
        uid="sub-ss",
        extra_data={"email": "ss@idp.edu"},
    )
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 200
    assert resp.context["sso_account"] is not None
    assert resp.context["sso_provider_label"] == "Test IdP"


@pytest.mark.django_db
def test_user_settings_no_sso_account(client):
    user = make_verified_user(username="ns", email="ns@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.context["sso_account"] is None


@pytest.mark.django_db
def test_user_settings_post_omitting_email_clears_it(client):
    # IMPORTANT semantics: a ModelForm field absent from POST is treated as blank.
    # The real template ALWAYS renders the email input, so a browser submit includes
    # it; but a POST that omits `email` clears it (changed_data fires, rows deleted).
    # This test PINS that behavior so it's intentional, not a surprise.
    from allauth.account.models import EmailAddress

    user = make_verified_user(username="oe", email="oe@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "auto", "language": "en", "display_name": "O"},  # no email key
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.email is None
    assert EmailAddress.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_user_settings_renders_controls_not_select(client):
    import re

    user = make_verified_user(username="rc2", email="rc2@school.edu")
    client.force_login(user)
    body = client.get(reverse("core:user_settings")).content
    assert b"<select" not in body  # no raw dropdowns
    assert b'class="seg"' in body  # language segmented control
    assert b'class="tile"' in body  # theme tiles
    assert b"core/css/settings.css" in body
    # the model default theme ("auto") must render as the *checked* tile on first GET
    # (guards against field.value being unmatched -> no selected control)
    assert re.search(r'value="auto"[^>]*checked', body.decode())


@pytest.mark.django_db
def test_user_settings_badge_connected_string(client):
    from allauth.socialaccount.models import SocialAccount

    from tests._sso import make_oidc_app

    app = make_oidc_app()
    user = make_verified_user(username="bc", email="bc@school.edu")
    SocialAccount.objects.create(
        user=user,
        provider=app.provider_id,
        uid="sub-bc",
        extra_data={"email": "bc@idp.edu"},
    )
    client.force_login(user)
    body = client.get(reverse("core:user_settings")).content
    assert b"bc@idp.edu" in body  # extra_data email rendered in the badge
