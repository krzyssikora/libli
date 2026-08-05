import re
from pathlib import Path

# Same pattern Task 5 / Task 6 use: courses/tests/ is two levels below the repo root.
REPO = Path(__file__).resolve().parents[2]
EDITOR_JS = REPO / "courses" / "static" / "courses" / "js" / "editor.js"


def _js_code_only(source):
    """JS source with comments stripped.

    Same helper as tests/test_imagezoom_render.py's `_js_code_only`, and for the
    same reason: that file's docstring records a source assertion once satisfied
    by a COMMENT quoting another module's code (a bare `, true)` regex matched
    the comment and a capture-phase guard passed with capture removed from the
    real call). The branch this task adds ships its own three-line comment
    block, so strip comments before scanning even though today's two assertions
    happen not to be comment-satisfiable.
    """
    no_block = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)//.*$", "", no_block)


def test_size_preset_branch_is_wired_into_the_delegated_handler():
    code = _js_code_only(EDITOR_JS.read_text(encoding="utf-8"))
    assert "data-size-preset" in code
    assert "data-preview-el" in code


def test_there_is_still_exactly_one_change_listener():
    """A source scan cannot inspect what an arbitrary listener is bound to, but
    it can insist there is still exactly one `change` listener registered — the
    delegated one on `root` at editor.js:462 — rather than a second listener
    bound inside a swapped `[data-scope]` pane that would die on the next
    `applyFragments` swap."""
    source = EDITOR_JS.read_text(encoding="utf-8")
    assert source.count('addEventListener("change"') == 1
