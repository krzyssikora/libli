from django.utils.safestring import mark_safe

from courses import fillblank
from courses import switchgrid


def _tok(i):
    return fillblank.SENTINEL + str(i) + fillblank.SENTINEL


def test_parse_multi_replaces_each_marker_in_order():
    stem, count = switchgrid.parse_stem_multi("3 {{choice}} 3 {{choice}} 9")
    assert stem == f"3 {_tok(0)} 3 {_tok(1)} 9"
    assert count == 2


def test_parse_multi_zero_markers_is_static_line():
    stem, count = switchgrid.parse_stem_multi("just static")
    assert stem == "just static"
    assert count == 0


def test_to_author_stem_multi_is_inverse():
    token_stem = f"a {_tok(0)} b {_tok(1)} c"
    assert switchgrid.to_author_stem_multi(token_stem) == "a {{choice}} b {{choice}} c"


def test_render_stem_multi_splices_widgets():
    token_stem = f"x {_tok(0)} y {_tok(1)} z"
    out = switchgrid.render_stem_multi(
        token_stem, {0: mark_safe("<b>W0</b>"), 1: mark_safe("<i>W1</i>")}
    )
    assert out == "x <b>W0</b> y <i>W1</i> z"


def test_render_stem_multi_missing_index_degrades_to_empty():
    token_stem = f"x {_tok(0)} y {_tok(1)} z"
    # index 1 missing
    out = switchgrid.render_stem_multi(token_stem, {0: mark_safe("W0")})
    assert out == "x W0 y  z"  # no KeyError; missing widget -> empty


def test_count_markers():
    assert switchgrid.count_markers(f"a {_tok(0)} b {_tok(1)} c") == 2
    assert switchgrid.count_markers("static") == 0


def test_sanitize_stem_segments_neutralizes_script_but_keeps_tokens():
    dirty = f"<script>x</script>ok {_tok(0)} <b>b</b>"
    out = switchgrid.sanitize_stem_segments(dirty)
    assert "<script>" not in out
    assert _tok(0) in out  # sentinel token preserved
    assert "ok" in out
