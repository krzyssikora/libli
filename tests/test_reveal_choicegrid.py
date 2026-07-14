from django.template.loader import render_to_string

from courses.marking import MarkResult


def test_reveal_correct_row_shows_tick_only():
    reveal = (
        {
            "statement": "2+2=4",
            "correct_label": "True",
            "chosen_label": "True",
            "is_correct": True,
        },
    )
    html = render_to_string(
        "courses/elements/_reveal_choicegrid.html",
        {"mark_result": MarkResult(True, 1.0, reveal)},
    )
    assert "2+2=4" in html and "✓" in html


def test_reveal_wrong_row_reveals_correct_label():
    reveal = (
        {
            "statement": "5 is even",
            "correct_label": "False",
            "chosen_label": "True",
            "is_correct": False,
        },
    )
    html = render_to_string(
        "courses/elements/_reveal_choicegrid.html",
        {"mark_result": MarkResult(False, 0.0, reveal)},
    )
    assert "False" in html  # correct column revealed for the wrong row


def test_reveal_omits_explanation():
    # el.explanation is rendered by the containing feedback/results partials, NOT by
    # this reveal include (matching every other _reveal_*.html); rendering it here too
    # would double it. So it must NOT appear here even when el is in context.
    from types import SimpleNamespace

    reveal = (
        {
            "statement": "s",
            "correct_label": "True",
            "chosen_label": None,
            "is_correct": True,
        },
    )
    html = render_to_string(
        "courses/elements/_reveal_choicegrid.html",
        {
            "mark_result": MarkResult(True, 1.0, reveal),
            "el": SimpleNamespace(explanation="Because arithmetic."),
        },
    )
    assert "Because arithmetic." not in html
