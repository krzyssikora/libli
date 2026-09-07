"""{libli:vat_note} -- per-language, escaped, block-level."""

from core.public_pages import BLOCK_TOKENS
from core.public_pages import INLINE_TOKENS
from tests.test_public_pages import render


def test_is_a_block_token():
    assert "vat_note" in BLOCK_TOKENS
    assert "vat_note" not in INLINE_TOKENS


def test_selects_the_note_for_the_pages_resolved_language():
    kw = {"vat_note_en": "EN tax", "vat_note_pl": "PL tax"}
    en = render("{libli:vat_note}\n", lang="en", **kw)
    pl = render("{libli:vat_note}\n", lang="pl", **kw)
    assert "EN tax" in en and "PL tax" not in en
    assert "PL tax" in pl and "EN tax" not in pl


def test_blank_note_renders_nothing_at_all():
    """Empty string, so the block substitution removes the enclosing <p> rather
    than leaving <p></p> on the page."""
    assert render("{libli:vat_note}\n", vat_note_en="").strip() == ""


def test_admin_markup_is_escaped_not_rendered():
    """Block values are inserted AFTER nh3, so they reach the browser
    unsanitised, and this is the one value on the page that is free
    admin-authored text."""
    html = render("{libli:vat_note}\n", vat_note_en="<b>bold</b>")
    assert "<b>" not in html
    assert "&lt;b&gt;" in html


def test_newlines_become_line_breaks():
    """Same treatment as controller_address: the inline pass has no _nl2br, so a
    two-line note would otherwise render as one run-on line."""
    html = render("{libli:vat_note}\n", vat_note_en="line one\nline two")
    assert "<br>" in html
