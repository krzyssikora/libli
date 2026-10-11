"""Shared helpers for tests that inspect @media print rules in the stylesheets."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "core/static/core/css/app.css"
COURSES_CSS = ROOT / "courses/static/courses/css/courses.css"


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def print_blocks(css):
    """Comment-free text of every `@media print { ... }` block in `css`, joined.

    Brace-depth scan, so nested rules and several blocks per file are handled;
    a regex up to the first `}` would stop inside the block."""
    css = strip_comments(css)
    out = []
    for m in re.finditer(r"@media print\s*\{", css):
        depth, j = 1, m.end()
        while depth and j < len(css):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        out.append(css[m.end() : j - 1])
    return "\n".join(out)


def rule_selectors(block, decl_regex):
    """Selectors of every rule in `block` whose declarations match decl_regex."""
    sels = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", strip_comments(block)):
        if re.search(decl_regex, m.group(2)):
            sels += [s.strip() for s in m.group(1).split(",")]
    return sels


def all_print_css():
    """Every print block of app.css and courses.css, joined."""
    return "\n".join(
        print_blocks(p.read_text(encoding="utf-8")) for p in (APP_CSS, COURSES_CSS)
    )
