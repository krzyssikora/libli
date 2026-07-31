"""The colouriser is NOT span-only, and that is the whole point of these tests.

142 of the 588 palette-coloured elements in the corpus sit on <strong>/<p>/<li>/
<u>/<figcaption>/<i>. A span-only implementation delivers nothing for ~21% of
occurrences AND scores ~100% on the acceptance gate, because its output is
byte-identical to the key. Every carrier case below asserts value != key.
"""

from courses.colour import slot_for_style
from courses.recolour.colouriser import colourise
from courses.recolour.colouriser import has_palette_colour
from courses.recolour.colouriser import roundtrip_is_lossless
from courses.recolour.colouriser import strip_spans


def test_slot_for_style_maps_the_four_slots():
    assert slot_for_style("color: red") == "red"
    assert slot_for_style("color:#1F61AD") == "blue"
    assert slot_for_style("color: rgb(63, 107, 36)") == "green"
    assert slot_for_style("color: orange") == "orange"


def test_slot_for_style_rejects_non_palette_and_background():
    # An unanchored `color:` search matches background-color: -- the corpus has both.
    assert slot_for_style("background-color: red") is None
    assert slot_for_style("color: purple") is None
    assert slot_for_style("") is None
    assert slot_for_style(None) is None


def test_strip_spans_unwraps_every_span_not_only_coloured_ones():
    # The pre-slice-1 sanitiser removed ALL spans (span was never in ALLOWED_TAGS).
    # 687 of the corpus's 1197 spans carry no colour at all -- 299 myequation,
    # 142 bare. A key that unwraps only coloured spans matches nothing for those.
    src = (
        '<p><span class="myequation">a</span>'
        '<span style="color: red;">b</span>'
        "<span>c</span></p>"
    )
    assert strip_spans(src) == "<p>abc</p>"


def test_strip_spans_keeps_non_span_markup_byte_for_byte():
    src = '<p>x <strong class="bold">y</strong> <a href="/z/">z</a></p>'
    assert strip_spans(src) == src


def test_span_carrier_gets_the_class_and_loses_the_style():
    out, n = colourise('<span style="color: red;">x</span>')
    assert out == '<span class="tc-red">x</span>'
    assert n == 1


def test_strong_carrier_keeps_the_element_and_gains_the_class():
    # strong is in TC_CLASS_TAGS, so the class rides the element itself.
    # 117 of the 142 non-span carriers are <strong>.
    out, n = colourise('<strong style="color: blue;">x</strong>')
    assert out == '<strong class="tc-blue">x</strong>'
    assert n == 1
    assert out != strip_spans('<strong style="color: blue;">x</strong>')


def test_block_carrier_moves_the_class_onto_a_wrapping_span():
    # p/li/figcaption cannot carry tc-* (the sanitiser would strip it), so the
    # colour moves onto a NEW span around the children.
    out, n = colourise('<p style="color: green;">x <b>y</b></p>')
    assert out == '<p><span class="tc-green">x <b>y</b></span></p>'
    assert n == 1


def test_figcaption_carrier_degrades_without_error():
    # figcaption is not in ALLOWED_TAGS at all: the sanitiser will unwrap the
    # figcaption later, and the colour survives on the inner span.
    out, n = colourise('<figcaption style="color: orange;">cap</figcaption>')
    assert out == '<figcaption><span class="tc-orange">cap</span></figcaption>'
    assert n == 1


def test_unmapped_colour_is_dropped_not_restored():
    # black/gray/magenta/purple/yellow/hex = 109 elements (16%), explicitly
    # accepted as lost: "the colours used in matematyka do not have to reflect
    # the originals, some of them may be skipped".
    out, n = colourise('<span style="color: purple;">x</span>')
    assert out == "x"
    assert n == 0


def test_background_colour_is_not_a_text_colour():
    out, n = colourise('<span style="background-color: red;">x</span>')
    assert out == "x"
    assert n == 0


def test_colourless_spans_are_unwrapped_in_the_value_too():
    # Once span is allowed, nh3 no longer removes them, so writing them back
    # would ship <span class=""> litter into content that is currently clean.
    out, n = colourise(
        '<p><span class="myequation">a</span><span style="color: red;">b</span></p>'
    )
    assert out == '<p>a<span class="tc-red">b</span></p>'
    assert n == 1


def test_two_carriers_in_one_fragment_both_count():
    out, n = colourise(
        'jeśli ( <span style="color: red;">założenie</span> ) to '
        '( <span style="color: blue;">teza</span> )'
    )
    assert out == (
        'jeśli ( <span class="tc-red">założenie</span> ) to '
        '( <span class="tc-blue">teza</span> )'
    )
    assert n == 2


def test_existing_class_is_kept_beside_the_colour_class():
    out, _n = colourise('<strong class="bold" style="color: red;">x</strong>')
    assert out == '<strong class="bold tc-red">x</strong>'


def test_has_palette_colour_distinguishes_the_two_cases():
    assert has_palette_colour('<span style="color: red;">x</span>')
    assert not has_palette_colour('<span style="color: purple;">x</span>')
    assert not has_palette_colour("<p>plain</p>")


def test_roundtrip_is_lossless_on_ordinary_markup():
    # MEASURED: 0 of 319 colour-bearing corpus values differ under a bs4
    # round-trip. This guard turns a future corpus change from silent
    # corruption into a reported skip.
    assert roundtrip_is_lossless('<p>a &lt; b <span style="color: red;">c</span></p>')


def test_entities_survive_the_round_trip():
    # Recorded repo trap: str(NavigableString) DECODES entities while str(Tag)
    # RE-ESCAPES them. decode_contents() is the serialisation that round-trips.
    src = "<p>a &amp; b &lt; c</p>"
    assert strip_spans(src) == src
