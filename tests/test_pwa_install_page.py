"""PWA C1: the public install guide (spec §8)."""

import pytest
from django.urls import reverse

from core.public_pages import DEMO_NOTICE_SLUGS
from core.public_pages import PAGES
from core.public_pages import VENDOR_ONLY_SLUGS
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_install_page_is_registered_and_neither_demo_nor_vendor_only():
    assert PAGES["install-app"].path == "public/install-app.md"
    assert "install-app" not in DEMO_NOTICE_SLUGS
    assert "install-app" not in VENDOR_ONLY_SLUGS


def test_install_page_renders_anonymously_in_both_languages(client):
    url = reverse("core:install_app")
    assert url == "/install-app/"
    en = client.get(url, headers={"accept-language": "en"})
    pl = client.get(url, headers={"accept-language": "pl"})
    assert en.status_code == pl.status_code == 200
    assert en.context["resolved_lang"] == "en"
    assert pl.context["resolved_lang"] == "pl"
    assert "Add to Home Screen" in en.content.decode()
    assert "Do ekranu początkowego" in pl.content.decode()


def test_public_footer_links_the_guide(client):
    body = client.get(reverse("core:privacy")).content.decode()
    assert f'href="{reverse("core:install_app")}"' in body


def test_landing_footer_links_the_guide(client):
    """Spec D11: the landing page has its own footer, not _public_footer.html.
    Scoped to that footer so a link elsewhere on the page cannot satisfy it."""
    body = client.get(reverse("landing")).content.decode()
    footer = body[body.index('<footer class="landing-footer">') :]
    footer = footer[: footer.index("</footer>")]
    assert f'href="{reverse("core:install_app")}"' in footer


def test_getting_started_links_the_guide(client):
    for lang in ("en", "pl"):
        body = client.get(
            reverse("core:getting_started"), headers={"accept-language": lang}
        ).content.decode()
        assert 'href="/install-app/"' in body, lang


def test_staff_help_index_links_the_guide(client):
    from django.contrib.auth.models import Group

    from institution.roles import TEACHER
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(username="help-probe", email="h@probe.example.com")
    user.groups.add(Group.objects.get(name=TEACHER))
    client.force_login(user)
    body = client.get(reverse("core:help_index")).content.decode()
    assert f'href="{reverse("core:install_app")}"' in body
