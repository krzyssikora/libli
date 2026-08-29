import pytest

from core.public_pages import render_public_page
from institution.models import PublicPage
from tests.test_public_pages import cfg


@pytest.mark.django_db
def test_repo_template_is_served_when_no_override():
    html, lang = render_public_page("privacy", "en", cfg())
    assert lang == "en"
    assert "<h1>" in html


@pytest.mark.django_db
def test_override_beats_the_repo_template():
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="# Mine\n")
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<h1>Mine</h1>" in html


@pytest.mark.django_db
def test_blank_override_row_is_treated_as_no_override():
    # Assert POSITIVELY that the repo template was served. The mutant here is
    # `if row:` instead of `if row and row.body_markdown.strip():`, under which
    # source == "   " and markdown renders "" -- so a mere `"<h1>Mine</h1>" not
    # in html` is green on BOTH builds. Requiring real template content is what
    # makes it red.
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="   ")
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<h1>" in html
    assert "Privacy" in html  # the shipped notice's own heading text


@pytest.mark.django_db
def test_deleting_the_override_falls_back_to_the_template():
    row = PublicPage.objects.create(
        slug="privacy", language="en", body_markdown="# Mine\n"
    )
    row.delete()
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<h1>Mine</h1>" not in html


@pytest.mark.django_db
def test_regional_request_hits_the_bare_code_override_row():
    PublicPage.objects.create(slug="privacy", language="pl", body_markdown="# Moje\n")
    html, lang = render_public_page("privacy", "pl-PL", cfg())
    assert "<h1>Moje</h1>" in html
    assert lang == "pl"


@pytest.mark.django_db
def test_an_en_only_override_does_not_leak_into_pl():
    PublicPage.objects.create(slug="privacy", language="en", body_markdown="# EnOnly\n")
    html, _lang = render_public_page("privacy", "pl", cfg())
    assert "EnOnly" not in html


@pytest.mark.django_db
def test_resolved_lang_is_en_when_the_base_path_comes_back(monkeypatch):
    # localized_doc_path returns a PATH, not a language, and silently returns the
    # English base when the sibling is absent. resolved_lang is derived from
    # WHICH path came back -- pinned here because the derivation is not obvious.
    import core.public_pages as pp

    monkeypatch.setattr(pp, "localized_doc_path", lambda base, code: base)
    _html, lang = render_public_page("privacy", "pl", cfg())
    assert lang == "en"


@pytest.mark.django_db
def test_resolved_lang_is_the_code_when_a_sibling_comes_back(monkeypatch):
    # The other half of the same derivation: mutant "return code unconditionally"
    # passes the test above only if this one also exists.
    import core.public_pages as pp

    monkeypatch.setattr(
        pp,
        "localized_doc_path",
        lambda base, code: base.removesuffix(".md") + f".{code}.md",
    )
    _html, lang = render_public_page("privacy", "pl", cfg())
    assert lang == "pl"


@pytest.mark.django_db
def test_pl_request_serves_the_pl_sibling():
    # End-to-end against the real shipped files (Task 6 creates privacy.pl.md).
    html, lang = render_public_page("privacy", "pl", cfg())
    assert lang == "pl"
    assert html != ""


@pytest.mark.django_db
def test_missing_file_renders_an_empty_body_not_a_500(monkeypatch):
    import core.public_pages as pp

    monkeypatch.setitem(
        pp.PAGES,
        "privacy",
        pp.Page("privacy", "public/does-not-exist.md", "T", "D"),
    )
    html, lang = render_public_page("privacy", "en", cfg())
    assert html == ""
    assert lang == "en"


@pytest.mark.django_db
def test_repo_file_branch_is_sanitised_too(tmp_path, monkeypatch):
    """The spec's mutant is "sanitise only the override branch". Task 2's test
    calls render_markdown directly and Task 9's uses an override row, so
    NEITHER exercises the repo-file branch -- this one does."""
    import core.public_pages as pp

    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "privacy.md").write_text(
        "# T\n\n<script>alert(1)</script>\n", encoding="utf-8"
    )
    monkeypatch.setattr(pp, "DOCS_ROOT", tmp_path)
    html, _lang = render_public_page("privacy", "en", cfg())
    assert "<script" not in html
    assert "alert(1)" not in html


def test_the_file_read_pins_utf8():
    """Platform-independent guard. On Linux CI the preferred encoding is already
    UTF-8, so dropping encoding="utf-8" still decodes the Polish file and a
    behavioural test stays green -- the mutant would only die on a cp1250 dev
    machine. Assert on the source instead; this is the authoritative check."""
    import inspect

    from core.public_pages import render_public_page as fn

    assert 'encoding="utf-8"' in inspect.getsource(fn)


@pytest.mark.django_db
def test_output_is_marked_safe():
    from django.utils.safestring import SafeString

    html, _lang = render_public_page("privacy", "en", cfg())
    assert isinstance(html, SafeString)
