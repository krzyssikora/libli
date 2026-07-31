"""D8/D10 applied to the SOURCE side.

The four-case table from the spec, plus fail-closed on an unbalanced delimiter.
`\\(<span class="tc-red">x</span> + y\\)` is still delimiter-balanced, so
sanitize_cell stashes it WITH the span and _canon_math escapes it into the stored
LaTeX permanently. Both sanitisers are idempotent, so re-saving never heals it.
"""

from courses.fillblank import SENTINEL
from courses.recolour.regions import region_verdict

# Imported, never written as an escape: SENTINEL is U+FFFF, and the visually
# identical U+FFFD would make every sentinel test here silently vacuous.
S = SENTINEL


def test_no_region_no_refusal():
    assert (
        region_verdict('<span style="color: red;">x</span>', sentinel_tokens=False)
        is None
    )


def test_colour_wholly_inside_a_maths_region_is_refused():
    html = 'a \\(<span style="color: red;">x</span> + y\\) b'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_colour_straddling_a_maths_region_is_refused():
    html = 'a <span style="color: red;">b \\(x</span> + y\\) c'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_colour_strictly_enclosing_a_clean_region_is_allowed():
    # The span wraps the delimiters rather than splitting them, so the stashed
    # LaTeX is untouched.
    html = '<span style="color: red;">see \\(x+y\\) here</span>'
    assert region_verdict(html, sentinel_tokens=False) is None


def test_colour_enclosing_a_region_with_an_element_boundary_is_refused():
    # Such a region already round-trips lossily through sanitize_cell regardless
    # of colour, so colouring it is not a gesture the storage layer can support.
    html = '<span style="color: red;">see \\(x + <b>y</b>\\) here</span>'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_unbalanced_delimiter_fails_closed():
    html = '<span style="color: red;">x</span> and \\(y with no close'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_display_delimiters_are_regions_too():
    html = 'a \\[<span style="color: red;">x</span>\\] b'
    assert region_verdict(html, sentinel_tokens=False) is not None


def test_a_colour_span_ENCLOSING_a_blank_token_is_refused():
    # The asymmetry with maths, and the reason it exists: sanitize_stem_segments
    # SPLITS the stem on the token and sanitises each segment INDEPENDENTLY, so an
    # enclosing span is auto-closed by nh3 in the leading segment and the trailing
    # segment silently loses its colour. The maths carve-out must NOT be reused
    # here -- applying it made this exact case pass while the data was corrupt.
    html = f'<span style="color: red;">pick {S}0{S} now</span>'
    assert region_verdict(html, sentinel_tokens=True) is not None


def test_a_colour_span_STRADDLING_a_blank_token_is_refused():
    html = f'a <span style="color: red;">b {S}0{S}</span> c'
    assert region_verdict(html, sentinel_tokens=True) is not None


def test_a_colour_span_DISJOINT_from_a_blank_token_is_allowed():
    # Disjoint is the only safe relation, and it must stay allowed or every
    # coloured gate stem in the corpus would be refused for nothing.
    html = f'{S}0{S} <span style="color: red;">x</span>'
    assert region_verdict(html, sentinel_tokens=True) is None


def test_sentinel_token_is_ignored_for_non_stem_shapes():
    # An html/cell field never goes through sanitize_stem_segments, so a stray
    # sentinel character there is not a protected region.
    html = f'<span style="color: red;">pick {S}0{S} now</span>'
    assert region_verdict(html, sentinel_tokens=False) is None


def test_unmapped_colour_carriers_are_not_tested():
    # A purple span inside maths is dropped by the colouriser, exactly as the
    # PRE-slice-1 sanitiser dropped it, so the stored value is unchanged and
    # there is no new corruption to refuse.
    html = 'a \\(<span style="color: purple;">x</span> + y\\) b'
    assert region_verdict(html, sentinel_tokens=False) is None
