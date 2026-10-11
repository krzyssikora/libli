"""css_string: the inside of a CSS double-quoted string, safe inside <style>.

Spec 2026-10-11-print-layout-for-units §2. The escape set is CLOSED: exactly
\\ " ' < > & and the C0 controls + DEL; everything else passes through.
"""

import pytest
from django.utils.safestring import SafeString
from django.utils.translation import gettext_lazy

from courses.templatetags.courses_extras import css_string


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ('"', "\\22 "),
        ("'", "\\27 "),
        ("\\", "\\5c "),
        ("<", "\\3c "),
        (">", "\\3e "),
        ("&", "\\26 "),
        ("\n", "\\a "),
        ("\r", "\\d "),
        ("\x00", "\\0 "),
        ("\x1f", "\\1f "),
        ("\x7f", "\\7f "),
    ],
)
def test_each_escaped_character(raw, escaped):
    assert css_string(raw) == escaped


def test_everything_else_passes_through():
    s = "Zażółć gęślą jaźń (f(x)) ·…"
    assert css_string(s) == s


def test_style_close_tag_has_no_literal_angle_bracket():
    out = css_string("</style><script>")
    assert "<" not in out and ">" not in out
    assert out == "\\3c /style\\3e \\3c script\\3e "


def test_returns_safestring():
    assert isinstance(css_string("x"), SafeString)


def test_none_is_empty_string():
    assert css_string(None) == ""


def test_lazy_string_is_stringified():
    assert css_string(gettext_lazy("Page")) == "Page"


def test_non_string_does_not_raise():
    assert css_string(42) == "42"
