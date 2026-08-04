"""Source-level invariant: editor.js must read a form's action ATTRIBUTE.

`form.action` is not the action URL when the form contains a control named
"action". HTMLFormElement's named-property getter is [LegacyOverrideBuiltIns], so
the control wins and the property evaluates to the input element; `fetch(form.action)`
then requests the string "[object HTMLInputElement]" resolved against the current
page. The clipboard's select and cancel forms both carry
`<input type="hidden" name="action" value="select|cancel">`, so before this guard
existed, clicking ⊹ in a real browser 404'd and the element was never marked.

Nothing server-side can see this: every view test posts with the Django test client
and never executes editor.js, so the whole feature's suite stayed green while the
gesture did nothing. Found by driving Chromium; kept honest here.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITOR_JS = ROOT / "courses" / "static" / "courses" / "js" / "editor.js"
ROW_CONTROLS = (
    ROOT / "templates" / "courses" / "manage" / "editor" / "_element_row_controls.html"
)

# ANY `.action` property read, in code. Deliberately not `\w*[Ff]orm\.action`: the
# variable holding the form is not always named for it — `f.action` is live house
# style in this repo already (courses/static/courses/js/quiz.js:89), and
# `e.target.action` is the other obvious spelling. A guard keyed on the identifier
# would pass while the defect was reintroduced under a shorter name.
# A bare `.action` is viable HERE specifically: editor.js's only other mentions of
# `.action` are the two comments explaining this very trap, and comments are stripped
# below — so the rule's own documentation cannot fail the rule. If a legitimate
# `.action` read ever lands in this file, narrow to the call sites rather than to the
# identifier shape.
PROPERTY_READ = re.compile(r"\.action\b")


def _code_only(source):
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in without_block.splitlines())


def test_a_data_op_form_really_does_carry_a_control_named_action():
    # Non-vacuity: the guard below only matters while some intercepted form shadows
    # the property. If the clipboard ever renames this field, this test reds and the
    # next reader learns the constraint may be relaxed rather than silently keeping a
    # rule whose reason has evaporated.
    markup = ROW_CONTROLS.read_text(encoding="utf-8")
    assert 'data-op="element-clip"' in markup
    assert 'name="action"' in markup


def test_editor_js_never_reads_the_action_property():
    code = _code_only(EDITOR_JS.read_text(encoding="utf-8"))
    hits = [line.strip() for line in code.splitlines() if PROPERTY_READ.search(line)]
    assert not hits, (
        "editor.js reads an `action` PROPERTY at "
        f"{hits} — a hidden <input name='action'> shadows it and the POST goes to "
        '"[object HTMLInputElement]". Use getAttribute("action"). (If this is a '
        "legitimate non-form `.action`, narrow PROPERTY_READ to the call sites.)"
    )


def test_editor_js_posts_to_the_action_attribute():
    code = _code_only(EDITOR_JS.read_text(encoding="utf-8"))
    assert 'form.getAttribute("action")' in code, (
        "editor.js's post() must resolve the URL via the action attribute"
    )
