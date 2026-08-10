"""Render-level guards for the formset row contract.

Two traps, both of which produce an assertion that cannot fail:
  * `data-fsrow` is a strict PREFIX of `data-fsrows`, `data-fsrows-list` and
    `data-fsrow-remove` — so a substring count matches the wrapper alone.
  * the <template> blueprint reproduces the loop body verbatim, and bs4 exposes
    <template> content as ordinary children — so a parsed `select()` picks up
    blueprint rows even when the list renders none.
Every assertion below therefore scopes to [data-fsrows-list] with the template
decomposed first.
"""

import pytest
from bs4 import BeautifulSoup

from tests.helpers_editor_rows import rendered_rows

pytestmark = pytest.mark.django_db


def test_matchpair_renders_exactly_the_formset_rows(open_matchpair_editor):
    """A saved 2-pair question renders 2 saved + extra=2 blank = 4 rows."""
    html = open_matchpair_editor(saved_pairs=2)
    assert len(rendered_rows(html)) == 4


def test_matchpair_blueprint_carries_the_prefix_token(open_matchpair_editor):
    """Match gains its first <template>; without this it has no test that it exists."""
    html = open_matchpair_editor(saved_pairs=2)
    soup = BeautifulSoup(html, "html.parser")
    tmpl = soup.select_one("[data-fsrows-template]")
    assert tmpl is not None, "match template must ship a blueprint"
    assert "pairs-__prefix__-left" in tmpl.decode_contents()


def test_matchpair_progressive_enhancement(open_matchpair_editor):
    """(a) JS-only controls ship hidden; (b) the DELETE label does not.
    This is the ONLY guard on the no-JS story."""
    html = open_matchpair_editor(saved_pairs=2)
    soup = BeautifulSoup(html, "html.parser")
    for tmpl in soup.select("template"):
        tmpl.decompose()
    add = soup.select_one("[data-fsrows-add]")
    assert add is not None and add.has_attr("hidden")
    row = soup.select_one("[data-fsrows-list] [data-fsrow-item]")
    assert row.select_one("[data-fsrow-remove]").has_attr("hidden")
    assert not row.select_one("[data-fsrow-del]").has_attr("hidden")


def test_matchpair_bounds(open_matchpair_editor):
    """Match's minimum is a bare `len(kept) < 1` in BaseMatchPairFormSet with no
    named constant, so this is a documented literal-vs-literal exception."""
    html = open_matchpair_editor(saved_pairs=2)
    soup = BeautifulSoup(html, "html.parser")
    wrap = soup.select_one("[data-fsrows]")
    assert wrap["data-fsrows"] == "pairs"
    assert wrap["data-fsrows-min"] == "1"
    assert not wrap.has_attr("data-fsrows-max")
    assert wrap.get("data-fsrows-atmin")
    assert wrap.get("data-fsrows-confirm")
