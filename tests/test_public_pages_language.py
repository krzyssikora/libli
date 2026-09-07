"""The renderer resolves tokens under the PAGE's language, not the thread's.

core/help.localized_doc_path falls back to the English base when a .pl.md file is
absent, so resolved == "en" while the active language is still "pl". Every other
test in the suite runs where the two agree, so without this file a build that
ignores the lang argument and calls translation.get_language() passes everything.
"""

import pytest

from core.public_pages import _block_values
from core.public_pages import render_markdown
from core.public_pages import substitute_tokens
from tests.test_public_pages import cfg


def test_block_values_is_importable_and_covers_every_block_token():
    """The per-language assertions live in Task 6, where vat_note exists. At THIS
    task _block_values still returns only the two existing tokens, so asserting on
    vat_note here would KeyError and this task could never reach its PASS."""
    from core.public_pages import BLOCK_TOKENS

    assert set(_block_values(cfg(), "en")) == set(BLOCK_TOKENS)


def test_lang_is_required_not_defaulted():
    """A lang="en" default would keep all eight existing call sites green while
    silently pinning English into the content guards."""
    import inspect

    sig = inspect.signature(substitute_tokens)
    assert sig.parameters["lang"].default is inspect.Parameter.empty


def test_the_inline_pass_asserts_parity_rather_than_keyerroring(monkeypatch):
    """Kills the delete-the-assert mutant. The old body compared _inline_values to
    INLINE_TOKENS directly -- true before this task and after it, so it guarded
    nothing. Patching INLINE_TOKENS to hold a name _inline_values does not build
    makes the production assert the only thing standing between the caller and a
    bare KeyError -- and the source html contains no such token, so without the
    assert the call would return normally rather than KeyError, which is exactly
    what distinguishes the two builds."""
    from core import public_pages

    monkeypatch.setattr(
        public_pages, "INLINE_TOKENS", frozenset(public_pages.INLINE_TOKENS | {"nope"})
    )
    with pytest.raises(AssertionError):
        substitute_tokens(render_markdown("hi\n"), cfg(), "en")
