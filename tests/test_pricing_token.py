"""{libli:pricing_plans} -- the cards, the open tier, and the shipped fallback."""

import re
from decimal import Decimal

from core.public_pages import BLOCK_TOKENS
from core.public_pages import INLINE_TOKENS
from core.public_pages import _block_values
from tests.test_public_pages import cfg
from tests.test_public_pages import render


def _plans(*prices):
    """Three bands matching the migration seed, priced as given."""
    rows = [(1, 1, 100, 6, 15, 10), (2, 101, 300, 8, 20, 20), (3, 301, 500, 12, 25, 40)]
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


def _card(html, needle):
    """The single <li class="pricing-cards__item"> whose text contains `needle`.

    Non-greedy up to the FIRST "</ul></li>": the card's own markup nests a
    second <ul> (the bounds list), each with plain <li>...</li> children, so a
    naive `(.*?)</li>` would stop at the first inner </li> instead of the
    card's own closing tag. Only the outer card's own close is preceded by the
    bounds list's closing </ul>, so this is the one sequence a non-greedy match
    can key on safely.
    """
    cards = re.findall(r'<li class="pricing-cards__item">(.*?)</ul></li>', html, re.S)
    return next(c for c in cards if needle in c)


def test_token_is_a_block_token_and_not_an_inline_one():
    """Block tokens are absent from the inline map precisely so a misplaced one
    renders literally instead of as escaped markup."""
    assert "pricing_plans" in BLOCK_TOKENS
    assert "pricing_plans" not in INLINE_TOKENS


def test_empty_plan_list_renders_the_fallback_not_a_table():
    """_DEFAULTS and BASE_CFG both carry [], so this is the state every direct
    substitute_tokens unit test runs under. Ruled out: a lone by-arrangement
    card, and an empty card list."""
    html = render("{libli:pricing_plans}\n", pricing_plans=[])
    assert "pricing-cards" not in html
    assert "on request" in html


def test_all_prices_null_renders_the_same_fallback():
    """The shipped state on merge."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "pricing-cards" not in html
    assert "on request" in html


def test_fallback_uses_the_existing_contact_fallback_when_email_is_blank():
    """Reuses _inline_values' string rather than inventing a second one for the
    same question."""
    html = render("{libli:pricing_plans}\n", pricing_plans=_plans(None, None, None))
    assert "the person who runs this site" in html


def test_priced_plans_render_a_card_per_plan():
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), Decimal("7200"), Decimal("10800")),
    )
    assert 'class="pricing-cards"' in html
    assert html.count('class="pricing-cards__item"') == 3


def test_amounts_use_a_nonbreaking_thousands_separator_and_omit_decimals_when_whole():
    """A whole-number price (every seeded plan, in practice) never carries
    the old always-two-decimals ".00" tail."""
    html = render(
        "{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("10800"), None, None)
    )
    assert "10 800 PLN" in html
    assert "10 800.00" not in html  # no comma separator, no stray decimals
    assert ".00" not in html


def test_amounts_keep_decimals_when_the_price_has_a_fractional_part():
    """The half of the no-decimals rule most likely to be missed: truncating
    unconditionally would render a stored 4800.50 as 4800 -- a wrong price."""
    html = render(
        "{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("4800.50"), None, None)
    )
    assert "4 800.50 PLN" in html


def test_currency_is_interpolated_from_cfg_not_hardcoded():
    """Each priced card carries its own currency now that the old intro
    sentence (the only place it used to appear) is gone. Overriding cfg's
    currency and finding the DEFAULT ("PLN") nowhere in the output is what
    rules out a hardcoded literal."""
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), Decimal("7200"), Decimal("10800")),
        currency="EUR",
    )
    assert "PLN" not in html
    assert html.count("EUR") == 3  # once per priced card, nowhere else


def test_by_arrangement_is_scoped_to_the_null_priced_card():
    """A bare `"by arrangement" in html` is green on a build where the null
    price renders blank, None or 0.00 -- because the renderer emits that
    phrase unconditionally in the open tier's own line too."""
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), None, Decimal("10800")),
    )
    band2 = _card(html, "101–300")
    band1 = _card(html, "1–100")
    assert "arrangement" in band2
    assert "4 800 PLN" in band1
    assert "arrangement" not in band1


def test_the_open_tier_interpolates_the_last_bands_ceiling():
    """A static "Larger schools" would leave a visible gap above 500."""
    html = render(
        "{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("4800"), None, None)
    )
    assert "501" in html


def test_the_open_tier_is_not_a_fourth_card():
    """A school cannot pick this tier, so it must not render as a fourth
    <li class="pricing-cards__item">."""
    html = render(
        "{libli:pricing_plans}\n", pricing_plans=_plans(Decimal("4800"), None, None)
    )
    assert html.count('class="pricing-cards__item"') == 3
    assert 'class="pricing-cards__above"' in html


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


def test_allowance_sentence_appears_in_the_CARDS_branch_too():
    """_plans_html appends `allowance` at TWO separate return statements, so a
    build that drops it from the priced branch stays green on the fallback test
    above while the shipped page loses the sentence the moment a price is set.
    """
    html = render(
        "{libli:pricing_plans}\n",
        pricing_plans=_plans(Decimal("4800"), None, None),
        storage_allowance_gb=50,
    )
    assert 'class="pricing-cards"' in html
    assert "50 GB" in html


def test_block_value_is_never_bare_inline_content():
    """_block_re swallows the enclosing <p>, so a bare string lands between block
    elements. Nothing in the existing guards catches it."""
    for lang in ("en", "pl"):
        value = _block_values(cfg(pricing_plans=[]), lang)["pricing_plans"]
        assert value.startswith("<p")
