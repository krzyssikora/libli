"""The key copy's one BeautifulSoup pass (spec 2026-09-25 §2.2)."""

from courses.keycopy import neutralise_key_copy


def test_names_stripped_controls_disabled():
    out = neutralise_key_copy(
        '<input type="text" name="blank" value="9">'
        '<select name="slot"><option>a</option></select>'
        '<input type="radio" name="row_5" value="3" checked>'
        '<textarea name="answer"></textarea>'
    )
    assert "name=" not in out
    assert out.count("disabled") == 4
    assert 'data-slot=""' in out  # dnd.js reads the slot select without a name


def test_ids_suffixed_internal_refs_rewritten_external_untouched():
    out = neutralise_key_copy(
        '<label for="b0">x</label><input id="b0" name="blank">'
        '<span aria-describedby="b0 hint-outside"></span>'
    )
    assert 'id="b0-key"' in out
    assert 'for="b0-key"' in out
    assert 'aria-describedby="b0-key hint-outside"' in out


def test_embeds_removed():
    out = neutralise_key_copy(
        '<p>x</p><iframe src="https://g"></iframe><embed><object></object>'
    )
    assert "<iframe" not in out and "<embed" not in out and "<object" not in out
    assert "<p>x</p>" in out


def test_latex_and_entities_round_trip():
    src = '<p>\\(a&lt;b\\) &amp; c</p><input name="blank" value="x">'
    out = neutralise_key_copy(src)
    assert "<p>\\(a&lt;b\\) &amp; c</p>" in out


def test_key_copy_escapes_value():
    out = neutralise_key_copy('<input name="answer" value="a&lt;b">')
    assert 'value="a&lt;b"' in out
