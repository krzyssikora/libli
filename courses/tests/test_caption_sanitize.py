"""The image-caption rich-text subset.

A caption is ONE line of prose that may carry emphasis and links -- not a body.
The tag set is deliberately narrower than `sanitize_html`'s and is kept in step
with the four buttons on `_rte_toolbar_caption.html` (B / I / U / link): a tag
the toolbar cannot produce has no business surviving a paste either.
"""

from courses.sanitize import sanitize_caption


def test_keeps_an_https_link_with_its_href():
    out = sanitize_caption('Photo: <a href="https://example.org/p">NASA</a>')
    assert '<a href="https://example.org/p">NASA</a>' in out


def test_keeps_a_mailto_link():
    out = sanitize_caption('<a href="mailto:a@b.example">write</a>')
    assert 'href="mailto:a@b.example"' in out


def test_drops_a_javascript_href_but_keeps_the_link_text():
    out = sanitize_caption('<a href="javascript:alert(1)">click</a>')
    assert "javascript" not in out
    assert "click" in out


def test_drops_a_data_href():
    out = sanitize_caption('<a href="data:text/html,<b>x</b>">click</a>')
    assert "data:" not in out


def test_keeps_the_emphasis_tags_the_toolbar_emits():
    # execCommand("bold"/"italic"/"underline") with styleWithCSS off emits
    # <b>/<i>/<u>; <strong>/<em> arrive from pasted or imported content.
    for tag in ("b", "i", "u", "strong", "em"):
        out = sanitize_caption(f"<{tag}>x</{tag}>")
        assert f"<{tag}>x</{tag}>" in out, f"{tag} was stripped: {out!r}"


def test_unwraps_a_heading_because_a_caption_is_not_a_body():
    out = sanitize_caption("<h2>Title</h2>")
    assert "<h2" not in out
    assert "Title" in out


def test_unwraps_a_list_because_a_caption_is_not_a_body():
    out = sanitize_caption("<ul><li>one</li><li>two</li></ul>")
    assert "<ul" not in out and "<li" not in out
    assert "one" in out and "two" in out


def test_a_block_boundary_becomes_a_br_so_words_cannot_silently_join():
    # The RTE surface emits a <div> per ENTER-separated line (it sets
    # defaultParagraphSeparator=div). `div` is NOT in the caption subset, so
    # without this normalisation nh3 would unwrap both and store "onetwo" --
    # silent corruption of the author's text, with nothing on screen to explain
    # it. The <br> is what makes the unwrap lossless.
    out = sanitize_caption("<div>one</div><div>two</div>")
    assert "<div" not in out
    assert out == "one<br>two"


def test_a_paragraph_boundary_becomes_a_br_too():
    assert sanitize_caption("<p>one</p><p>two</p>") == "one<br>two"


def test_a_single_block_leaves_no_trailing_br():
    assert sanitize_caption("<div>only</div>") == "only"


def test_an_authored_br_survives():
    assert sanitize_caption("one<br>two") == "one<br>two"


def test_drops_a_script_tag_and_its_contents():
    out = sanitize_caption("a<script>alert(1)</script>b")
    assert "script" not in out and "alert" not in out


def test_drops_an_event_handler_attribute():
    out = sanitize_caption('<a href="https://e.example" onclick="x()">t</a>')
    assert "onclick" not in out


def test_drops_a_colour_class_because_the_caption_toolbar_offers_no_colour():
    # Kept in step with the toolbar on purpose: offering no colour button while
    # silently preserving a pasted colour would make the subset undiscoverable.
    out = sanitize_caption('<span class="tc-red">x</span>')
    assert "tc-red" not in out


def test_collapses_a_caption_with_no_visible_content_to_empty():
    # `{% if el.figcaption %}` in imageelement.html is the only guard on the
    # <figcaption> element, so a truthy-but-blank value renders an empty box.
    for blank in ("", "<br>", "<div><br></div>", "<p>&nbsp;</p>"):
        assert sanitize_caption(blank) == "", f"{blank!r} survived"


def test_is_idempotent():
    once = sanitize_caption('a <b>b</b> <a href="https://e.example">c</a><div>d</div>')
    assert sanitize_caption(once) == once


def test_none_is_treated_as_empty():
    assert sanitize_caption(None) == ""
