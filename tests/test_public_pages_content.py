import re

import pytest

from core.help import DOCS_ROOT
from core.public_pages import PAGES
from core.public_pages import render_markdown
from core.public_pages import substitute_tokens
from tests.test_public_pages import cfg

SHIPPED = [
    "public/privacy.md",
    "public/privacy.pl.md",
    "public/getting-started.md",
    "public/getting-started.pl.md",
]


@pytest.mark.parametrize("rel", SHIPPED)
def test_shipped_file_exists_and_is_utf8(rel):
    assert (DOCS_ROOT / rel).read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("rel", SHIPPED)
def test_demo_notice_is_placed_where_the_block_regex_matches(rel):
    # Misplaced (indented, in a list, mid-sentence) the token silently renders as
    # literal text, swallowing the do-not-enter-real-pupil-data warning.
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    assert "{libli:demo_notice}" in source
    html = substitute_tokens(render_markdown(source), cfg(demo_instance=True))
    assert "public-page__notice" in html
    assert "{libli:demo_notice}" not in html


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_block_token_has_a_heading_immediately_above_it(rel):
    # The block pass deletes the paragraph and nothing else, so a heading above
    # it would be orphaned on every non-demo deployment.
    lines = (DOCS_ROOT / rel).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if "{libli:demo_notice}" in line or "{libli:controller_address}" in line:
            above = [x for x in lines[:i] if x.strip()]
            assert not (above and above[-1].lstrip().startswith("#")), (
                f"{rel}: heading immediately above {line.strip()}"
            )


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_token_survives_inside_an_attribute(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    html = substitute_tokens(render_markdown(source), cfg(demo_instance=True))
    for tag in re.findall(r"<[^>]+>", html):
        assert "{libli:" not in tag, f"{rel}: token inside {tag}"


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_unresolved_token_remains_in_either_configuration(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    for demo in (True, False):
        html = substitute_tokens(render_markdown(source), cfg(demo_instance=demo))
        assert "{libli:" not in html, f"{rel}: unresolved token (demo={demo})"


@pytest.mark.parametrize("rel", SHIPPED)
def test_no_empty_paragraph_when_blocks_are_off(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    html = substitute_tokens(render_markdown(source), cfg(demo_instance=False))
    assert "<p></p>" not in html


@pytest.mark.parametrize("rel", SHIPPED)
def test_exactly_one_h1(rel):
    source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
    html = substitute_tokens(render_markdown(source), cfg())
    assert html.count("<h1>") == 1


def test_every_root_relative_link_resolves():
    """Markdown cannot reverse a URL, so the shipped files hardcode /privacy/ and
    /accounts/password/reset/ as literal paths. Nothing else notices when one of
    those routes is renamed or removed, and these are the surfaces a stranger
    and a locked-out user land on -- so resolve() every root-relative href.

    Swept across all four files at once, not parametrised: only the two
    getting-started files carry such a link today, so a per-file non-empty
    assertion would be red on a correct build.
    """
    from django.urls import Resolver404
    from django.urls import resolve

    found = {}
    for rel in SHIPPED:
        source = (DOCS_ROOT / rel).read_text(encoding="utf-8")
        html = substitute_tokens(render_markdown(source), cfg())
        for href in re.findall(r'href="(/[^"]*)"', html):
            found.setdefault(href, rel)

    # Non-vacuity: if the link syntax or the sanitiser ever stopped emitting
    # these hrefs, the loop below would pass over an empty set.
    assert {"/privacy/", "/accounts/password/reset/"} <= set(found), found

    for href, rel in found.items():
        path = href.split("?")[0].split("#")[0]
        try:
            resolve(path)
        except Resolver404:
            raise AssertionError(f"{rel}: {href} does not resolve") from None


def test_every_registered_page_has_both_language_files():
    for page in PAGES.values():
        assert (DOCS_ROOT / page.path).exists()
        pl = page.path.removesuffix(".md") + ".pl.md"
        assert (DOCS_ROOT / pl).exists()
