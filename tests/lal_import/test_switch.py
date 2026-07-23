from bs4 import BeautifulSoup

from scripts.lal_import.mathsafe import escape_math_delimited
from scripts.lal_import.switch import SENTINEL
from scripts.lal_import.switch import strip_lead_prompt
from scripts.lal_import.switch import switch_line_stem_cyclers


def test_strip_lead_prompt_removes_wybierz_and_shifts_answer():
    opts = ["&gt;&gt; wybierz &gt;&gt;", r"\(-1\)", r"\(0\)", r"\(1\)"]
    new_opts, new_answer = strip_lead_prompt(opts, 2)
    assert new_opts == [r"\(-1\)", r"\(0\)", r"\(1\)"]
    assert new_answer == 1  # LAL index 2 ("0") -> libli index 1 after drop


def test_strip_lead_prompt_noop_when_no_prompt():
    opts = [r"\(\cup\)", r"\(\cap\)", r"\(\setminus\)"]
    assert strip_lead_prompt(opts, 2) == (opts, 2)


def _line(html):
    return BeautifulSoup(escape_math_delimited(html), "html.parser").find(
        class_="switch_line"
    )


def test_one_cycler_between_static_around():
    line = _line(
        '<div class="switch_line">'
        r'<div class="switch_around">\(A\)</div>'
        r'<div class="switch_value">\(\cup\)</div>'
        r'<div class="switch_value">\(\cap\)</div>'
        r'<div class="switch_around">\(B\)</div>'
        "</div>"
    )
    stem, cyclers = switch_line_stem_cyclers(line)
    assert cyclers == [{"options": [r"\(\cup\)", r"\(\cap\)"]}]
    token = SENTINEL + "0" + SENTINEL
    assert token in stem
    assert r"\(A\)" in stem and r"\(B\)" in stem
    # the cycler token sits between the two static operands
    assert stem.index(r"\(A\)") < stem.index(token) < stem.index(r"\(B\)")


def test_bare_text_is_static_and_button_is_skipped():
    line = _line(
        '<div class="switch_line">'
        r"Punkt \((6,1)\) "
        r'<div class="switch_value">>> wybierz >></div>'
        r'<div class="switch_value">należy</div>'
        r'<div class="switch_value">nie należy</div>'
        r'<div class="switch_show_next ks_button">zatwierdź</div>'
        "</div>"
    )
    stem, cyclers = switch_line_stem_cyclers(line)
    # `>` is escaped to the &gt; entity (sanitized-field convention, like &lt;).
    assert cyclers[0]["options"] == [
        "&gt;&gt; wybierz &gt;&gt;",
        "należy",
        "nie należy",
    ]
    assert "Punkt" in stem
    assert "zatwierdź" not in stem  # the confirm button is not part of the stem
    assert SENTINEL + "0" + SENTINEL in stem


def test_math_lt_kept_as_entity_in_options():
    # \(a<b\) is escaped to \(a&lt;b\) before parse; a sanitized option field keeps
    # the entity (matches table-cell/stem convention, not the autoescaped path).
    line = _line(
        '<div class="switch_line">'
        r'<div class="switch_value">\(a<b\)</div>'
        r'<div class="switch_value">\(a>b\)</div>'
        "</div>"
    )
    _, cyclers = switch_line_stem_cyclers(line)
    assert cyclers[0]["options"][0] == r"\(a&lt;b\)"
