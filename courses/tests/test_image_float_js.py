import re
from pathlib import Path

EDITOR_JS = Path(__file__).resolve().parents[2] / "courses/static/courses/js/editor.js"


def _code():
    src = EDITOR_JS.read_text(encoding="utf-8")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"(?m)//.*$", "", src)


def test_float_branch_lives_in_the_one_delegated_handler():
    code = _code()
    assert "data-float-right" in code
    assert "el--image--float" in code
    assert EDITOR_JS.read_text(encoding="utf-8").count('addEventListener("change"') == 1


def test_the_size_handler_finds_its_box_inside_its_own_editor():
    # Not by data-for-element: that is "" for EVERY unsaved image on the create flow.
    assert 'closest(".el-editor--image")' in _code()
