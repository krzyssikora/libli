"""middle_truncate: the server-side half of asset-name visibility (spec §1).

The filter caps a rendered filename at `budget` characters while preserving the
TAIL -- the numeric suffix and extension are what distinguish
`przykladowa_parabola_0_1.png` from `..._0_2.png`, and an end-truncating filter
would cut off exactly the discriminating part.
"""

from django.utils.safestring import SafeString

from courses.templatetags.courses_manage_extras import middle_truncate


def test_value_shorter_than_budget_is_unchanged():
    assert middle_truncate("short.png") == "short.png"


def test_value_at_exactly_budget_is_unchanged():
    value = "a" * 28 + ".png"  # 32 chars
    assert len(value) == 32
    assert middle_truncate(value) == value


def test_over_budget_keeps_head_ellipsis_and_tail():
    value = "przykladowa_bardzo_dluga_nazwa_wersja_0_2.png"
    result = middle_truncate(value)
    assert result == value[:17] + "…" + value[-14:]  # head = 32 - 1 - 14
    assert "…" in result


def test_over_budget_result_length_equals_budget():
    value = "x" * 100 + ".png"
    assert len(middle_truncate(value)) == 32


def test_budget_16_is_the_first_middle_truncating_budget():
    value = "y" * 40
    result = middle_truncate(value, 16)
    assert len(result) == 16
    assert result == "y" + "…" + "y" * 14


def test_budget_15_falls_back_to_end_truncation():
    value = "y" * 40
    result = middle_truncate(value, 15)
    assert len(result) == 15
    assert result == "y" * 14 + "…"


def test_budget_1_returns_a_single_character():
    assert middle_truncate("abcdef", 1) == "a"


def test_negative_budget_is_clamped_to_empty():
    assert middle_truncate("abcdef", -5) == ""


def test_string_budget_from_a_template_is_coerced():
    # Django hands filter args through as parsed, so {{ x|middle_truncate:"16" }}
    # delivers a str and max("16", 0) would raise TypeError.
    value = "z" * 40
    assert middle_truncate(value, "16") == middle_truncate(value, 16)


def test_value_with_no_extension():
    value = "n" * 50
    result = middle_truncate(value)
    assert len(result) == 32
    assert result.endswith("n" * 14)


def test_non_ascii_value():
    value = "żółw_" * 12  # 60 code points; contains non-ASCII code points
    result = middle_truncate(value)
    assert len(result) == 32
    assert result.endswith(value[-14:])


def test_value_shorter_than_tail_with_small_budget_reaches_the_fallback():
    # At the DEFAULT budget this exits at the first guard and proves nothing.
    assert middle_truncate("ab.png", 5) == "ab.p" + "…"


def test_returns_a_plain_str_not_a_safestring():
    # display_name falls back to original_filename, which is attacker-controlled.
    # A mark_safe() "fix" here would be a stored XSS, and every other case in
    # this file uses innocuous ASCII that would survive it. Both CONSTRUCTED
    # returns are checked -- on a short value this would only re-prove that the
    # input was a plain str.
    assert not isinstance(middle_truncate("q" * 100 + ".png"), SafeString)
    assert not isinstance(middle_truncate("q" * 100, 15), SafeString)
