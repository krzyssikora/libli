from scripts.lal_import.quiz import parse_quiz

CHOICE_QUIZ = r"""
<p>Dany jest zbiór \(A=\{3,4,7\}\).</p>
[x] \(3\in A\)
[ ] \(6\in A\) {{selected: czy 6 jest elementem \(A\)?}}
[x] \(\{3,7\}\subset A\)
"""

NUMERIC_QUIZ = r"""
<p>Ile elementów ma \(A\cap B\)?</p>
= 2
"""


def test_choice_bracket_shape_is_multiselect():
    qs, flags = parse_quiz(CHOICE_QUIZ)
    assert len(qs) == 1
    q = qs[0]
    assert q["type"] == "choice"
    assert q["multiple"] is True
    assert [c["is_correct"] for c in q["choices"]] == [True, False, True]


def test_choice_feedback_extracted():
    qs, _ = parse_quiz(CHOICE_QUIZ)
    fb = qs[0]["choices"][1]["feedback"]
    assert "6 jest elementem" in fb


def test_stem_math_escaped_exactly():
    qs, _ = parse_quiz(r"<p>Dla \(a<b\) zachodzi</p>" + "\n= 1\n")
    assert qs[0]["stem"] == r"<p>Dla \(a&lt;b\) zachodzi</p>"


def test_numeric_answer():
    qs, _ = parse_quiz(NUMERIC_QUIZ)
    assert qs[0]["type"] == "numeric"
    assert qs[0]["value"] == "2"
    assert qs[0]["tolerance"] == "0"


def test_radio_bracket_is_single_select():
    qs, _ = parse_quiz("<p>Q</p>\n(x) a\n( ) b\n")
    assert qs[0]["multiple"] is False


def test_mixed_zadanie_flagged_and_emits_flagged_element():
    qs, flags = parse_quiz("<p>Q</p>\n[x] a\n= 5\n")
    assert any(f["kind"] == "mixed_zadanie" for f in flags)
    assert any(q.get("flagged") for q in qs)  # a flagged element, not silent drop


def test_quiz_stem_media_flagged_and_emits_flagged_element():
    qs, flags = parse_quiz('<p>Q</p><img src="x.png"/>\n= 1\n')
    assert any(f["kind"] == "quiz_stem_media" for f in flags)
    assert any(q.get("flagged") for q in qs)


def test_unknown_hint_flagged():
    qs, flags = parse_quiz("<p>Q</p>\n[ ] a {{unselected: no}}\n")
    assert any(f["kind"] == "unknown_hint" for f in flags)


def test_two_questions_segmented_without_comments():
    qs, _ = parse_quiz("<p>Q1</p>\n= 1\n<p>Q2</p>\n= 2\n")
    assert len(qs) == 2
    assert qs[0]["value"] == "1" and qs[1]["value"] == "2"


def test_zadanie_comment_is_a_boundary_not_unmatched_dsl():
    # bs4 Comment nodes stringify to their inner text (no <!-- markers), so they
    # must be detected structurally — never string-matched — and never flagged.
    html = "<!-- Zadanie 1 -->\n<p>Q1</p>\n= 1\n<!-- Zadanie 2 -->\n<p>Q2</p>\n= 2\n"
    qs, flags = parse_quiz(html)
    assert not any(f["kind"] == "unmatched_dsl" for f in flags)
    assert [q["value"] for q in qs] == ["1", "2"]


def test_choice_math_stored_literal_for_autoescape():
    # C1: choice option math must be stored with a LITERAL '<' (bs4 NavigableString
    # decodes it), so the autoescaped choice template renders it correctly.
    qs, _ = parse_quiz(r"<p>Q</p>" + "\n[x] \\(y<z\\)\n")
    assert qs[0]["choices"][0]["text"] == r"\(y<z\)"  # literal <, not &lt;
