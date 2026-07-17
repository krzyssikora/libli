from courses.fillblank import parse
from courses.fillblank import render_inputs


def test_render_inputs_locked_emits_readonly_is_correct_and_size():
    token_stem, _answers = parse("City: {{Constantinople}}")
    out = str(render_inputs(token_stem, ["Constantinople"], locked=True))
    assert "readonly" in out
    assert "is-correct" in out
    assert 'value="Constantinople"' in out
    assert 'size="14"' in out  # len("Constantinople") == 14


def test_render_inputs_locked_size_floor_is_two():
    token_stem, _answers = parse("Letter: {{a}}")
    out = str(render_inputs(token_stem, ["a"], locked=True))
    assert 'size="2"' in out  # max(len("a"), 2) == 2


def test_render_inputs_unlocked_default_is_unchanged():
    token_stem, _answers = parse("City: {{Paris}}")
    out = str(render_inputs(token_stem, ["Paris"]))
    assert "readonly" not in out
    assert "is-correct" not in out
    assert 'size="' not in out
