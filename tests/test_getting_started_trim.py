"""The trim keeps the sign-in help and fixes the premise, without stranding the
/privacy/ link that another guard's non-vacuity check depends on."""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from core.public_pages import render_markdown
from core.public_pages import substitute_tokens
from tests.test_public_pages import cfg

ROOT = Path(settings.BASE_DIR, "docs", "public")
EN = (ROOT / "getting-started.md").read_text(encoding="utf-8")
PL = (ROOT / "getting-started.pl.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("text", [EN, PL])
def test_the_false_premise_is_gone(text):
    """Krzysztof hosts, one box per school -- the school does not run it itself."""
    assert "runs for itself" not in text
    assert "prowadzi u siebie" not in text


@pytest.mark.parametrize("text", [EN, PL])
def test_the_sign_in_help_survives(text):
    assert "/accounts/password/reset/" in text


def test_a_root_relative_privacy_link_survives_somewhere_in_shipped():
    """test_every_root_relative_link_resolves asserts
    {"/privacy/", "/accounts/password/reset/"} <= set(found) as an explicit
    non-vacuity check across the whole SHIPPED sweep. The paragraph carrying
    /privacy/ is the one being moved, so it must land somewhere."""
    everything = "".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in (
            "getting-started.md",
            "getting-started.pl.md",
            "for-schools.md",
            "for-schools.pl.md",
            "privacy.md",
            "privacy.pl.md",
        )
    )
    assert "/privacy/" in everything


@pytest.mark.parametrize("text", [EN, PL])
def test_the_cross_pointer_token_is_present_with_prose_above_it(text):
    assert "{libli:for_schools_link}" in text
    before = text.split("{libli:for_schools_link}")[0].rstrip().splitlines()[-1]
    assert not before.startswith("#")


@pytest.mark.parametrize("text", [EN, PL])
def test_the_demo_notice_token_still_has_prose_above_it(text):
    before = text.split("{libli:demo_notice}")[0].rstrip().splitlines()[-1]
    assert not before.startswith("#")


def _render_off_off(source, lang):
    """Off-vendor, non-demo: {libli:for_schools_link} and {libli:demo_notice}
    both resolve to "" -- the state of every school box, and of no other
    rendering path exercised elsewhere in this module."""
    with override_settings(VENDOR_INSTANCE=False):
        rendered = render_markdown(source)
        return substitute_tokens(rendered, cfg(demo_instance=False), lang)


_PROMISE_RE = re.compile(
    r"page\s+you\s+want|strona,?\s+kt[oó]rej\s+szukasz", re.IGNORECASE
)


@pytest.mark.parametrize(("text", "lang"), [(EN, "en"), (PL, "pl")])
def test_no_orphaned_lead_in_survives_when_both_tokens_are_empty(text, lang):
    """Kills two dangles that {libli:for_schools_link}="" and
    {libli:demo_notice}="" leave behind on every school box (and on libli.pl
    itself, where demo_instance is False):

    (a) a paragraph promising "the page you want" with no <a> anywhere in the
        paragraph that immediately follows it once the link token is gone --
        the same class of defect as the spec's own defect #1: a promised page
        that, off-vendor, does not even resolve (/for-schools/ 404s there).
    (b) a paragraph whose rendered text ends in a colon, run straight into the
        next, unrelated paragraph, because the sentence after the colon was
        the demo notice and it is now "".

    Neither existing guard sees this: test_no_block_token_has_a_heading_
    immediately_above_it only forbids a *heading* directly above a block
    token (prose sits between here, so it passes), and
    test_no_empty_paragraph_when_blocks_are_off only forbids a literal
    "<p></p>" (these lead-ins are not empty -- they are just stranded).
    """
    html = _render_off_off(text, lang)
    paragraphs = re.findall(r"<p>(.*?)</p>", html, re.DOTALL)

    for i, para in enumerate(paragraphs):
        if _PROMISE_RE.search(para):
            following = paragraphs[i + 1] if i + 1 < len(paragraphs) else ""
            nearby = para + following
            msg = f"{lang}: a promise with no link in it or the next para: {para!r}"
            assert "<a " in nearby or "<a>" in nearby, msg

    for para in paragraphs:
        stripped = para.strip()
        msg = f"{lang}: a paragraph dangling on a colon, nothing after: {stripped!r}"
        assert not stripped.endswith(":"), msg
