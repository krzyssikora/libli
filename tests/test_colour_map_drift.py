"""The palette is defined twice — Python for the backfill, JS for the editor — because
the JS has no build step and cannot import Python. This holds the two copies together.

It compares the canonical slot tables (triple -> slot), NOT the raw literals: the two
languages legitimately accept different input forms (bs4 hands Python `color: red;`
from a style attribute; the DOM hands JS `rgb(255, 0, 0)`) over the same slots.
"""

import json
import re
from pathlib import Path

from courses.colour import SLOTS

JS = Path(__file__).resolve().parent.parent / "courses/static/courses/js/text_colour.js"


def test_js_and_python_slot_tables_agree():
    source = JS.read_text(encoding="utf-8")
    match = re.search(r"var MAP = (\[[^;]*?\]);", source, re.DOTALL)
    assert match, (
        "text_colour.js must expose the slot table as a single JS array literal "
        "assigned to `var MAP` — the test extracts it verbatim, so refactoring it "
        "into computed form is a deliberate break, not an accident"
    )
    raw = match.group(1)
    raw = re.sub(r"//[^\n]*", "", raw)  # strip line comments
    raw = re.sub(r",(\s*[\]}])", r"\1", raw)  # tolerate trailing commas
    raw = raw.replace("rgb:", '"rgb":').replace("slot:", '"slot":')
    entries = json.loads(raw)

    js_table = {tuple(entry["rgb"]): entry["slot"] for entry in entries}
    assert js_table == SLOTS, (
        "JS and Python slot tables disagree\n"
        f"  only in JS:     {sorted(set(js_table) - set(SLOTS))}\n"
        f"  only in Python: {sorted(set(SLOTS) - set(js_table))}"
    )


def test_css_tokens_are_in_the_python_slot_table():
    """There are THREE copies of every hex: tokens.css, colour.py and
    text_colour.js. The test above binds the last two. Without this one, changing a
    --tc-* token to satisfy a future surface leaves the other two stale with a green
    suite, and slotFor() silently stops recognising the colour the page renders."""
    from courses.colour import normalise_colour

    tokens = (
        Path(__file__).resolve().parent.parent / "core/static/core/css/tokens.css"
    ).read_text(encoding="utf-8")
    seen = 0
    for slot in ("red", "blue", "green", "orange"):
        for value in re.findall(rf"--tc-{slot}:\s*(#[0-9A-Fa-f]{{6}})", tokens):
            assert SLOTS.get(normalise_colour(value)) == slot, (
                f"tokens.css --tc-{slot} is {value}, which colour.py does not map "
                f"to {slot!r} — update _PALETTE and text_colour.js MAP together"
            )
            seen += 1
    # 4 slots x 3 occurrence sets: :root, [data-theme="dark"], and the
    # @media print override that restates the light values for printing.
    assert seen == 12, f"expected 4 slots x 3 blocks in tokens.css, found {seen}"
