import pytest
from django.urls import reverse

from institution.models import Institution
from institution.models import PublicPage

URLS = ["core:privacy", "core:getting_started"]


@pytest.mark.django_db
@pytest.mark.parametrize("name", URLS)
def test_anonymous_gets_200(client, name):
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("name", URLS)
def test_anonymous_gets_200_in_polish(client, name):
    session = client.session
    session["_language"] = "pl"
    session.save()
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("name", URLS)
def test_renders_with_no_institution_row(client, name):
    from core.services import invalidate_site_config

    Institution.objects.all().delete()
    invalidate_site_config()
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.django_db
def test_a_table_reaches_the_response_as_a_real_element(client):
    # RESPONSE-level, not sanitiser-level: every sanitiser test stays green
    # through a double-escaping bug. This one does not.
    PublicPage.objects.create(
        slug="privacy",
        language="en",
        body_markdown="# T\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n",
    )
    body = client.get(reverse("core:privacy")).content.decode()
    assert "<table>" in body
    assert "&lt;table&gt;" not in body


@pytest.mark.django_db
def test_script_in_an_override_does_not_reach_the_response(client):
    PublicPage.objects.create(
        slug="privacy",
        language="en",
        body_markdown="# T\n\n<script>alert(1)</script>\n",
    )
    body = client.get(reverse("core:privacy")).content.decode()
    assert "<script>alert(1)</script>" not in body


@pytest.mark.django_db
def test_controller_name_from_settings_reaches_the_page(client):
    inst = Institution.load()
    inst.controller_name = "Greenfield School Trust"
    inst.save()
    body = client.get(reverse("core:privacy")).content.decode()
    assert "Greenfield School Trust" in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    "slug,name",
    [("privacy", "core:privacy"), ("getting-started", "core:getting_started")],
)
def test_page_emits_its_real_description_title_and_one_h1(client, slug, name):
    from core.public_pages import PAGES

    body = client.get(reverse(name)).content.decode()
    # Non-empty, and the RIGHT description: `'name="description"' in body`
    # passes on content="" and on the wrong context key.
    assert str(PAGES[slug].description)[:40] in body
    # Assert on the COMPOSED element, not the bare string: the shipped markdown
    # opens with "# Privacy notice", so `str(title) in body` is already true via
    # the <h1> and stays green with head_title deleted or the key misnamed.
    assert f"<title>{PAGES[slug].title} ·" in body
    assert body.count("<h1>") == 1  # base.html has none; the markdown owns it


@pytest.mark.django_db
def test_body_is_marked_with_the_resolved_language(client):
    # Assert on the ARTICLE: base.html:4 already emits <html lang="pl">, so a
    # bare `'lang="pl"' in body` is green even with the attribute deleted.
    session = client.session
    session["_language"] = "pl"
    session.save()
    body = client.get(reverse("core:privacy")).content.decode()
    assert '<article class="public-page" lang="pl">' in body


@pytest.mark.django_db
def test_an_english_fallback_body_is_marked_en_inside_a_pl_page(client, monkeypatch):
    # The real fallback case: English prose served inside <html lang="pl">.
    import core.public_pages as pp

    monkeypatch.setattr(pp, "localized_doc_path", lambda base, code: base)
    session = client.session
    session["_language"] = "pl"
    session.save()
    body = client.get(reverse("core:privacy")).content.decode()
    assert '<article class="public-page" lang="en">' in body
    assert '<html lang="pl"' in body
