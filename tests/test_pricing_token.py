"""{libli:pricing_plans} -- the table, the fourth tier, and the shipped fallback."""

import re
from decimal import Decimal

from core.public_pages import BLOCK_TOKENS
from core.public_pages import INLINE_TOKENS
from core.public_pages import _block_values
from tests.test_public_pages import cfg
from tests.test_public_pages import render


def _plans(*prices):
    """Three bands matching the migration seed, priced as given."""
    rows = [(1, 1, 150, 6, 3, 10), (2, 151, 400, 8, 6, 20), (3, 401, 800, 12, 12, 40)]
    return [
        {
            "order": o,
            "pupils_min": lo,
            "pupils_max": hi,
            "annual_price": p,
            "support_hours_per_term": h,
            "courses_included": c,
            "video_hours_included": v,
        }
        # strict=True: always three of each, so a mismatch is a bug, not a trim.
        for (o, lo, hi, h, c, v), p in zip(rows, prices, strict=True)
    ]


def test_token_is_a_block_token_and_not_an_inline_one():
    """Block tokens are absent from the inline map precisely so a misplaced one
    renders literally instead of as escaped markup."""
    assert "pricing_plans" in BLOCK_TOKENS
    assert "pricing_plans" not in INLINE_TOKENS


def test_empty_plan_list_renders_the_fallback_not_a_table():
    """_DEFAULTS and BASE_CFG both carry [], so this is the state every direct
    substitute_tokens unit test runs under. Ruled out: a lone by-arrangement row,
    and a header-only empty <table>."""
    html = render("{libli:pricing_plans}\n", pricing_plans=[])
    assert "<table" not in html
    assert "on request" in html


def test_all_prices_null_renders_the_same_fallback():
    """The shipped state on merge."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "<table" not in html
    assert "on request" in html


def test_fallback_uses_the_existing_contact_fallback_when_email_is_blank():
    """Reuses _inline_values' string rather than inventing a second one for the
    same question."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "the person who runs this site" in html


def test_priced_plans_render_a_table_with_a_scroll_wrapper():
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), Decimal("7200"), Decimal("10800")),
    )
    assert 'class="public-page__scroll"' in html
    assert "<table" in html


def test_amounts_use_a_nonbreaking_thousands_separator_and_no_symbol():
    html = render(
        "{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("10800"), None, None)
    )
    assert "10 800.00" in html
    # Split on the first row end: the renderer emits <table><tr>header</tr>...
    # with no <thead>/<tbody>, so those are not available as landmarks.
    assert "PLN" not in html.split("</tr>", 1)[1]  # currency lives in the header only


def test_currency_appears_in_the_column_header():
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), None, None),
        currency="EUR",
    )
    assert "EUR" in html.split("</tr>", 1)[0]  # the header row


def test_by_arrangement_is_scoped_to_the_null_priced_row():
    """A bare `"by arrangement" in html` is green on a build where the null price
    renders blank, None or 0.00 -- because the renderer emits that phrase
    unconditionally in the fourth tier."""
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), None, Decimal("10800")),
    )
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    band2 = next(r for r in rows if "151" in r and "400" in r)
    band1 = next(r for r in rows if "1" in r and "150" in r)
    assert "arrangement" in band2
    assert "4 800.00" in band1
    assert "arrangement" not in band1


def test_the_fourth_tier_interpolates_the_last_bands_ceiling():
    """A static "Larger schools" would leave a visible gap above 800."""
    html = render(
        "{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("4800"), None, None)
    )
    assert "801" in html


def test_allowance_sentence_is_absent_when_the_field_is_null():
    """The shipped default."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "GB" not in html


def test_allowance_sentence_appears_when_the_field_is_set():
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(None, None, None),
        storage_allowance_gb=50,
    )
    assert "50 GB" in html


def test_allowance_sentence_appears_in_the_TABLE_branch_too():
    """_plans_html appends `allowance` at TWO separate return statements, so a
    build that drops it from the priced branch stays green on the fallback test
    above while the shipped page loses the sentence the moment a price is set."""
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), None, None),
        storage_allowance_gb=50,
    )
    assert 'class="public-page__scroll"' in html
    assert "50 GB" in html


def test_block_value_is_never_bare_inline_content():
    """_block_re swallows the enclosing <p>, so a bare string lands between block
    elements. Nothing in the existing guards catches it."""
    for lang in ("en", "pl"):
        value = _block_values(cfg(pricing_plans=[]), lang)["pricing_plans"]
        assert value.startswith("<p") or value.startswith("<div")
