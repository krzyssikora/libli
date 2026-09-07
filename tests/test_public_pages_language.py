"""The renderer resolves tokens under the PAGE's language, not the thread's.

core/help.localized_doc_path falls back to the English base when a .pl.md file is
absent, so resolved == "en" while the active language is still "pl". Every other
test in the suite runs where the two agree, so without this file a build that
ignores the lang argument and calls translation.get_language() passes everything.
"""

from core.public_pages import _block_values
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


def test_inline_values_parity_assert_exists():
    """The block pass has an assert; the inline pass did not, so a half-done edit
    there was a KeyError rather than a clear failure."""
    from core.public_pages import INLINE_TOKENS
    from core.public_pages import _inline_values

    assert set(_inline_values(cfg())) == INLINE_TOKENS
