import pytest
from scripts.lal_import.ordering import (
    ordering_token, ordered_html_files, duplicate_token_warnings,
)

def test_token_leading_digits():
    assert ordering_token("005_zbiory.html") == 5

def test_token_after_alpha_prefix():
    assert ordering_token("wyr_alg_010_potegi.html") == 10
    assert ordering_token("f_lin_020_x.html") == 20

def test_token_missing_raises():
    with pytest.raises(ValueError):
        ordering_token("neolms.html")

def test_order_is_numeric_not_lexicographic():
    names = ["100_a.html", "020_b.html", "005_c.html"]
    assert ordered_html_files(names) == ["005_c.html", "020_b.html", "100_a.html"]

def test_duplicate_token_warns_but_still_orders():
    names = ["010_a.html", "010_b.html"]
    assert ordered_html_files(names) == ["010_a.html", "010_b.html"]
    warns = duplicate_token_warnings(names)
    assert len(warns) == 1
    assert warns[0]["kind"] == "duplicate_ordering_token"
    assert set(warns[0]["names"]) == {"010_a.html", "010_b.html"}
