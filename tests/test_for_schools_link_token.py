"""{libli:for_schools_link} -- present on the vendor box, absent everywhere else."""

import pytest
from django.test import override_settings

from core.public_pages import BLOCK_TOKENS
from core.public_pages import INLINE_TOKENS
from tests.test_public_pages import render


def test_is_a_block_token_and_not_an_inline_one():
    assert "for_schools_link" in BLOCK_TOKENS
    # The negative half matters: registered inline, the anchor would be
    # substituted as ESCAPED TEXT inside a run rather than as markup.
    assert "for_schools_link" not in INLINE_TOKENS


@override_settings(VENDOR_INSTANCE=False)
def test_renders_nothing_off_vendor():
    assert render("{libli:for_schools_link}\n").strip() == ""


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_renders_an_anchor_on_the_vendor_box():
    html = render("{libli:for_schools_link}\n")
    assert 'href="/for-schools/"' in html


@pytest.mark.django_db
@override_settings(VENDOR_INSTANCE=True)
def test_the_href_comes_from_reverse_not_a_hardcoded_path():
    """A hardcoded path would also escape test_every_root_relative_link_resolves,
    which only sees links present in the markdown."""
    import inspect

    from core import public_pages

    assert 'reverse("core:for_schools")' in inspect.getsource(public_pages)
