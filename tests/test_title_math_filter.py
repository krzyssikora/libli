"""strip_math_delimiters: the plain-text half of LaTeX-in-titles (spec §4).

Unit tests here; the eleven per-(file, line) wiring assertions live in Task 2
of the same file.
"""

from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy

from courses.templatetags.courses_extras import strip_math_delimiters


def test_strips_an_inline_pair():
    assert strip_math_delimiters(r"\(x^2\)") == "x^2"


def test_strips_a_display_pair():
    assert strip_math_delimiters(r"\[a\]") == "a"


def test_strips_both_kinds_in_one_title():
    assert strip_math_delimiters(r"Solve \(x\) then \[y\]") == "Solve x then y"


def test_a_title_with_no_delimiters_keeps_its_content():
    assert strip_math_delimiters("Rozwiaz rownanie") == "Rozwiaz rownanie"


def test_an_unmatched_opener_is_removed_too():
    # Naive left-to-right replacement, REGARDLESS of pairing (spec §4).
    assert strip_math_delimiters(r"\(x") == "x"


def test_a_stray_closer_is_removed_too():
    assert strip_math_delimiters(r"x\)") == "x"


def test_none_renders_as_the_string_none():
    # Matches Django's own default rendering of None in a template. A filter
    # that raised would take down the whole page render (spec §Error handling).
    assert strip_math_delimiters(None) == "None"


def test_a_lazy_proxy_resolves_to_its_text():
    assert strip_math_delimiters(gettext_lazy("Review")) == "Review"


def test_an_int_renders_as_its_digits():
    assert strip_math_delimiters(7) == "7"


def test_returns_a_plain_str_not_safestring_when_delimiters_present():
    out = strip_math_delimiters(mark_safe(r"\(x\)"))
    assert type(out) is str


def test_the_strip_openers_agree_with_the_detector():
    """THE FORK GUARD. _MATH_DELIMS is a deliberate, minimal fork: the filter needs
    the two CLOSERS, which has_math_delimiters does not expose, so it cannot simply
    delegate the way titles_have_math does.

    What must never drift is the OPENERS. If a third opener is ever added to
    has_math_delimiters, every gate would arm for it while the filter left the raw
    delimiter sitting in a title= attribute and in <title> -- and nothing else in
    this suite would go red. Task 3 pins the detection side; this pins the strip
    side.
    """
    from courses.htmlsandbox import has_math_delimiters
    from courses.templatetags.courses_extras import _MATH_DELIMS

    openers = [d for d in _MATH_DELIMS if has_math_delimiters(d)]
    assert openers, "no _MATH_DELIMS entry is recognised by has_math_delimiters"
    # Anything the detector recognises, the filter must remove -- so a title made
    # of every opener strips to nothing the detector would still flag.
    assert not has_math_delimiters(strip_math_delimiters("".join(_MATH_DELIMS)))


def test_returns_a_plain_str_not_safestring_on_the_no_delimiter_path():
    """The tempting optimisation -- return the input untouched when it holds no
    delimiter -- would pass a SafeString straight through and silently lose
    autoescaping in a title= attribute. SafeString.__str__ returns self, so even
    a str() coercion does not strip the safe marker."""
    out = strip_math_delimiters(mark_safe("Plain title"))
    assert out == "Plain title"
    assert type(out) is str
