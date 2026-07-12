import pytest

from courses import switchgate


def test_parse_stem_replaces_single_marker():
    assert switchgate.parse_stem("pick {{choice}} now") == "pick ￿0￿ now"


def test_parse_stem_rejects_zero_markers():
    with pytest.raises(switchgate.SwitchGateError):
        switchgate.parse_stem("no marker here")


def test_parse_stem_rejects_two_markers():
    with pytest.raises(switchgate.SwitchGateError):
        switchgate.parse_stem("{{choice}} and {{choice}}")


def test_to_author_stem_roundtrips():
    token = switchgate.parse_stem("a {{choice}} b")
    assert switchgate.to_author_stem(token) == "a {{choice}} b"


def test_render_stem_splices_widget():
    out = switchgate.render_stem("a ￿0￿ b", "<WIDGET>")
    assert out == "a <WIDGET> b"
