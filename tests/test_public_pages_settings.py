import pytest
from django.urls import reverse
from django.urls import reverse_lazy

from institution.models import Institution
from institution.models import PublicPage
from tests.factories import make_verified_user

PANEL = reverse_lazy("institution:settings") + "?tab=public-pages"


def _admin():
    from django.contrib.auth.models import Permission

    user = make_verified_user()
    user.user_permissions.add(Permission.objects.get(codename="change_institution"))
    return user


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name", ["institution:settings_public_pages", "institution:settings_page_overrides"]
)
def test_requires_the_permission(client, name):
    client.force_login(make_verified_user())
    assert client.post(reverse(name), {}).status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name", ["institution:settings_public_pages", "institution:settings_page_overrides"]
)
def test_get_redirects_rather_than_rendering(client, name):
    client.force_login(_admin())
    assert client.get(reverse(name)).status_code == 302


@pytest.mark.django_db
def test_panel_renders_one_textarea_per_page_per_language(client):
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    for slug in ("privacy", "getting-started"):
        for lang in ("en", "pl"):
            assert f'name="override-{slug}-{lang}"' in body
    # EXACT count: a presence check does not kill "iterate settings.LANGUAGES",
    # which is a superset and would render extra textareas while staying green.
    assert body.count('name="override-') == 4


@pytest.mark.django_db
def test_regional_enabled_language_is_normalised_and_deduped(client):
    inst = Institution.load()
    inst.enabled_languages = ["pl", "pl-PL"]
    inst.save()
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert body.count('name="override-privacy-pl"') == 1
    assert 'name="override-privacy-pl-PL"' not in body


@pytest.mark.django_db
def test_saving_writes_a_row_and_blanking_deletes_it(client):
    client.force_login(_admin())
    url = reverse("institution:settings_page_overrides")
    client.post(url, {"override-privacy-en": "# Mine\n"})
    assert PublicPage.objects.filter(slug="privacy", language="en").exists()
    client.post(url, {"override-privacy-en": "   "})
    assert not PublicPage.objects.filter(slug="privacy", language="en").exists()


@pytest.mark.django_db
def test_override_save_emits_a_success_message(client):
    # _action owns messages.success and this view cannot reuse it, so without an
    # explicit call the one action publishing live legal text confirms nothing.
    from django.contrib.messages import get_messages

    client.force_login(_admin())
    response = client.post(
        reverse("institution:settings_page_overrides"),
        {"override-privacy-en": "# Mine\n"},
    )
    assert [str(m) for m in get_messages(response.wsgi_request)]


@pytest.mark.django_db
def test_hyphenated_slug_is_not_split_on_the_hyphen(client):
    client.force_login(_admin())
    client.post(
        reverse("institution:settings_page_overrides"),
        {"override-getting-started-en": "# G\n"},
    )
    assert PublicPage.objects.filter(slug="getting-started", language="en").exists()
    assert not PublicPage.objects.filter(slug="getting").exists()


@pytest.mark.django_db
def test_a_stale_language_row_is_listed_and_deletable(client):
    PublicPage.objects.create(slug="privacy", language="de", body_markdown="# D\n")
    inst = Institution.load()
    inst.enabled_languages = ["en", "pl"]
    inst.save()
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert 'name="override-privacy-de"' in body
    client.post(
        reverse("institution:settings_page_overrides"), {"override-privacy-de": ""}
    )
    assert not PublicPage.objects.filter(slug="privacy", language="de").exists()


@pytest.mark.django_db
def test_a_row_with_an_unregistered_slug_survives_a_save(client):
    # The union is qualified to slugs still in PAGES. Without that, the
    # delete-when-blank rule would silently destroy a row the spec calls inert.
    PublicPage.objects.create(slug="retired", language="en", body_markdown="# R\n")
    client.force_login(_admin())
    client.post(reverse("institution:settings_page_overrides"), {})
    assert PublicPage.objects.filter(slug="retired").exists()


@pytest.mark.django_db
def test_partial_override_warning(client):
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="# Mine\n")
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert "some but not all" in body


@pytest.mark.django_db
def test_missing_demo_notice_warning(client):
    inst = Institution.load()
    inst.demo_instance = True
    inst.save()
    PublicPage.objects.create(
        slug="privacy", language="en", body_markdown="# No token here\n"
    )
    client.force_login(_admin())
    body = client.get(PANEL).content.decode()
    assert "demonstration warning" in body


@pytest.mark.django_db
def test_saving_the_identity_form_updates_the_page(client):
    client.force_login(_admin())
    client.post(
        reverse("institution:settings_public_pages"),
        {
            "controller_name": "Trust X",
            "controller_address": "",
            "contact_email": "",
            "supervisory_authority": "",
        },
    )
    assert Institution.load().controller_name == "Trust X"


@pytest.mark.django_db
def test_invalid_identity_form_rerenders_without_a_type_error(client):
    # _action splats **{ctx_key: form}; "public-pages" is not a valid identifier.
    client.force_login(_admin())
    resp = client.post(
        reverse("institution:settings_public_pages"), {"contact_email": "not-an-email"}
    )
    assert resp.status_code == 200
