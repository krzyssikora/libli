"""normalize_body repairs two structural defects the LAL import stored.

Both come from html5ever re-parsing a `<p>` the importer wrapped around block
content: `<p><li>..</li></p>` re-parses as `<p></p><li>..</li>`, and any other
block inside a `<p>` leaves the same zero-height `<p></p>` in front of it.

* An ORPHAN `<li>` (no `<ul>`/`<ol>` parent) renders its marker outside the
  content box -- hanging left of the lesson column and clipped at the editor
  surface's edge -- and the list buttons cannot toggle it (Chromium's
  insertUnorderedList turns it into `text<br>` instead).
* An EMPTY `<p></p>` has no height but still triggers the block-spacing rule
  `> p + :is(p, div, ...) { margin-top }`, so centring a bare-text body (which
  wraps it in a `<div>`) made a blank line appear above it.
"""

import pytest

from courses.sanitize import normalize_body
from courses.sanitize import sanitize_html


@pytest.mark.parametrize(
    "raw",
    [
        "<p></p>jak to zrobić?<p></p>",
        "<p>\n   </p>jak to zrobić?",
        '<p class="ta-center"></p>jak to zrobić?',
    ],
)
def test_empty_paragraphs_are_dropped(raw):
    assert normalize_body(raw) == "jak to zrobić?"


def test_paragraph_with_content_is_kept():
    body = "<p><br></p><p>a</p><p><strong></strong>b</p>"
    assert normalize_body(body) == sanitize_html(body)


def test_orphan_li_run_is_wrapped_in_one_ul():
    raw = "<p></p><li>\n a\n</li>\n<li>b</li>\n<p>dalej</p>"
    assert normalize_body(raw) == "<ul><li>\n a\n</li>\n<li>b</li></ul>\n<p>dalej</p>"


def test_orphan_runs_separated_by_a_block_become_two_lists():
    raw = "<li>a</li><p>x</p><li>b</li>"
    assert normalize_body(raw) == "<ul><li>a</li></ul><p>x</p><ul><li>b</li></ul>"


def test_orphan_li_inside_a_div_is_wrapped_in_place():
    assert normalize_body("<div><li>a</li></div>") == "<div><ul><li>a</li></ul></div>"


def test_proper_lists_are_untouched():
    body = "<ol><li>a<ul><li>b</li></ul></li></ol>"
    assert normalize_body(body) == body


def test_orphan_li_maths_and_entities_survive_the_rewrap():
    raw = "<li>\\(a &lt; b\\) &amp; c&nbsp;d</li>"
    out = normalize_body(raw)
    assert out.startswith("<ul><li>") and out.endswith("</li></ul>")
    # Exactly what sanitize_html stores for the same <li> inside a real <ul>.
    assert out == sanitize_html("<ul>" + raw + "</ul>")


@pytest.mark.parametrize(
    "raw",
    [
        "<p></p>jak<p></p>",
        "<p></p><li>a</li><li>b</li>",
        '<pre class="ta-center">x</pre>',
        "<p>zwykły <strong>tekst</strong></p>",
    ],
)
def test_idempotent(raw):
    once = normalize_body(raw)
    assert normalize_body(once) == once


@pytest.mark.parametrize("align", ["ta-center", "ta-right", "ta-left"])
def test_code_block_alignment_survives_save(align):
    # The RTE's align buttons work on a <pre> exactly as on a <p>; the class was
    # stripped on save because `pre` was missing from ALIGN_CLASS_TAGS.
    body = f'<pre class="{align}">x = 1</pre>'
    assert normalize_body(body) == body


def test_ol_start_survives_save():
    # A numbered list continued after an image (or split by the author, as the LAL
    # source does in 16 files) must keep counting from where it left off.
    body = '<ol start="3"><li>c</li></ol>'
    assert normalize_body(body) == body


@pytest.mark.parametrize("bad", ["0", "-1", "x", "3; color:red", "1e3", "12345", ""])
def test_ol_start_must_be_a_small_positive_integer(bad):
    assert normalize_body(f'<ol start="{bad}"><li>c</li></ol>') == "<ol><li>c</li></ol>"


def test_start_is_only_kept_on_ol():
    assert normalize_body('<ul start="2"><li>c</li></ul>') == "<ul><li>c</li></ul>"


def test_list_for_chooses_each_runs_list():
    from courses.sanitize import tidy_structure

    seen = []

    def list_for(run_html):
        seen.append(run_html)
        return ("ol", '<ol start="2">') if "b" in run_html else ("ul", "<ul>")

    out = tidy_structure("<li>a</li><p>x</p><li>b</li>\n", list_for=list_for)
    assert out == '<ul><li>a</li></ul><p>x</p><ol start="2"><li>b</li></ol>\n'
    assert seen == ["<li>a</li>", "<li>b</li>"]
