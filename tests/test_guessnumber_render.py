from decimal import Decimal

import pytest

from courses import guessnumber
from courses.models import GuessNumberElement
from courses.templatetags.courses_extras import render_guess_number


@pytest.mark.django_db
def test_renders_contract_hooks():
    el = GuessNumberElement.objects.create(
        stem="x" + guessnumber.SENTINEL_TOKEN + "y", target=Decimal("42")
    )
    html = render_guess_number(el, 7)
    assert 'class="guessnumber"' in html and "data-guessnumber" in html
    assert 'data-element-pk="7"' in html
    assert "/element/7/guessnumber-check/" in html  # data-check-url
    assert "<form" not in html  # no form: implicit submission would
    assert 'type="submit"' not in html  # reload and wipe reveal-gate state
    assert 'type="button"' in html
    assert 'type="text"' in html  # NOT type=number: kills "40401,5"
    assert "data-guess-input" in html
    assert "data-guess-check" in html and "hidden" in html
    assert "data-guess-live" in html and 'aria-live="polite"' in html
    assert "data-guess-hint" in html
    assert "data-guess-success" in html
    assert "data-msg-high" in html and "data-msg-low" in html


@pytest.mark.django_db
def test_blank_success_message_falls_back_to_correct():
    el = GuessNumberElement.objects.create(
        stem=guessnumber.SENTINEL_TOKEN, target=Decimal("42")
    )
    assert "Correct!" in render_guess_number(el, 1)


@pytest.mark.django_db
def test_empty_block_markup_success_message_also_falls_back():
    # The RTE posts <p><br></p> when an author types and deletes — truthy, and
    # it survives sanitize_html, so a `if not success_message` test lets it
    # through and renders an empty box.
    el = GuessNumberElement.objects.create(
        stem=guessnumber.SENTINEL_TOKEN,
        target=Decimal("42"),
        success_message="<p><br></p>",
    )
    assert "Correct!" in render_guess_number(el, 1)


@pytest.mark.django_db
def test_success_message_html_is_preserved_not_escaped():
    el = GuessNumberElement.objects.create(
        stem=guessnumber.SENTINEL_TOKEN,
        target=Decimal("42"),
        success_message="<p>Tak</p>",
    )
    html = render_guess_number(el, 1)
    assert "<p>Tak</p>" in html and "&lt;p&gt;" not in html


@pytest.mark.django_db
def test_spliced_widget_contains_no_block_level_start_tag():
    # sanitize_html allows <p>; the HTML PARSER auto-closes an open <p> on a
    # <form>/<div> start tag, hoisting the widget and all following prose out of
    # the paragraph. That is parser behaviour — string slicing cannot see it, so
    # assert on the spliced fragment's tags instead of its position.
    el = GuessNumberElement.objects.create(
        stem="<p>201 = " + guessnumber.SENTINEL_TOKEN + " done</p>",
        target=Decimal("42"),
    )
    html = render_guess_number(el, 1)
    start = html.index("<input data-guess-input")
    end = html.index("</button>", start)
    spliced = html[start:end]
    for block in ("<form", "<div", "<p"):
        assert block not in spliced


@pytest.mark.django_db
def test_parsed_dom_keeps_the_input_inside_the_paragraph():
    # The same trap, checked through a real parser rather than string offsets.
    from html.parser import HTMLParser

    el = GuessNumberElement.objects.create(
        stem="<p>201 = " + guessnumber.SENTINEL_TOKEN + " done</p>",
        target=Decimal("42"),
    )

    class Depth(HTMLParser):
        stack, depth_at_input = [], None

        def handle_starttag(self, tag, attrs):
            if tag == "input" and any(a[0] == "data-guess-input" for a in attrs):
                Depth.depth_at_input = list(self.stack)
            elif tag not in ("input", "br"):
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()

    p = Depth()
    p.feed(render_guess_number(el, 1))
    assert "p" in (Depth.depth_at_input or [])  # still inside the paragraph
