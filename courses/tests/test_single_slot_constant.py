"""The single-slot id must have ONE home, not a literal per model.

`validate_nesting` hard-coded SpoilerElement.SLOT_ID for every single-slot
container, so a second single-slot container would validate only because both
classes happen to spell "only".

Do NOT pin this with `CalloutElement.SLOT_ID is SpoilerElement.SLOT_ID`: "only" is
identifier-shaped, so CPython interns it and two INDEPENDENT `SLOT_ID = "only"`
literals are the same object -- the `is` test is green under the exact divergence
it would be written to catch. The pin is source-level instead.
"""

import inspect
import re

from courses.models import SINGLE_SLOT_ID
from courses.models import SpoilerElement


def _executable_source(cls):
    """Class source with `#` comments and the docstring removed.

    Both must go: `comments-can-fail-tests` is a standing lesson here, and
    SpoilerElement's docstring already narrates its slot -- scanning it would fail a
    CORRECT implementation whose prose happens to quote the literal.
    """
    src = inspect.getsource(cls)
    doc = cls.__doc__
    if doc:
        src = src.replace(doc, "", 1)
    return re.sub(r"#.*", "", src)


def test_single_slot_id_value_is_unchanged():
    # A stored Element.tab_id value on every existing nested-spoiler child.
    assert SINGLE_SLOT_ID == "only"


def test_spoiler_does_not_respell_the_slot_literal():
    assert "SLOT_ID" in _executable_source(SpoilerElement)
    assert '"only"' not in _executable_source(SpoilerElement)
    assert "'only'" not in _executable_source(SpoilerElement)
