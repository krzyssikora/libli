"""No print rule may hide a reveal gate.

Owner decision D8 (spec 2026-10-11-print-layout-for-units): gated content prints
exactly as the screen shows it, and an unconsumed gate -- a "Show more" button, a
fill gate's blanks + Confirm, a switch gate's cycler + Confirm, a gated fill-table
-- prints as the marker that more content waits behind it. A consumed gate hides
itself on screen ([hidden] / its own done state), so it is absent on paper too.

The previous rule here (`[data-reveal-gate]:not([data-filltablegate])` hidden in
print, with the gated fill-table carved out because its node IS the student's
work) is gone together with the print reveal it paired with.
"""

import re
from pathlib import Path

CSS = Path("core/static/core/css/app.css").read_text(encoding="utf-8")
COURSES_CSS = Path("courses/static/courses/css/courses.css").read_text(encoding="utf-8")


def _strip_comments(css):
    # A comment mentioning `[data-reveal-gate]` must not satisfy or falsify the
    # assertions below; only real rules count.
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _print_blocks(css):
    css = _strip_comments(css)
    out = []
    for m in re.finditer(r"@media print\s*\{", css):
        depth, j = 1, m.end()
        while depth and j < len(css):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        out.append(css[m.end() : j - 1])
    return "\n".join(out)


def test_no_print_rule_mentions_a_reveal_gate():
    for name, css in (("app.css", CSS), ("courses.css", COURSES_CSS)):
        assert "[data-reveal-gate]" not in _print_blocks(css), (
            f"{name}: a print rule targets [data-reveal-gate]; D8 prints gates "
            "as on screen"
        )


def test_no_print_rule_reveals_prehidden_blocks():
    for name, css in (("app.css", CSS), ("courses.css", COURSES_CSS)):
        assert ".reveal-armed" not in _print_blocks(css), (
            f"{name}: a print rule overrides the reveal-armed pre-hide"
        )
