"""The module hardcodes a copy of auto-render's default delimiter list, because the
vendored file keeps it as a minified internal and exposes nothing on `window`. That
copy is version-coupled third-party data, so a KaTeX upgrade must redden here rather
than silently diverging."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "courses/static/courses/vendor/katex/contrib/auto-render.min.js"
MODULE = ROOT / "courses/static/courses/js/math_reflow.js"

# {left:"$$",right:"$$",display:!0}  — minified booleans, JS-escaped strings.
_TRIPLE = re.compile(
    r'\{left:"((?:[^"\\]|\\.)*)",right:"((?:[^"\\]|\\.)*)",display:(!0|!1)\}'
)


def _js_unescape(value):
    """Decode a JS double-quoted string body. `\\\\(` in source is the two-character
    string `\\(`; json.loads applies exactly the same escape rules."""
    return json.loads(f'"{value}"')


def _triples(source):
    return [
        (_js_unescape(m.group(1)), _js_unescape(m.group(2)), m.group(3) == "!0")
        for m in _TRIPLE.finditer(source)
    ]


def test_vendored_defaults_are_exactly_eight_triples():
    found = _triples(VENDOR.read_text(encoding="utf-8"))
    # Anti-vacuity: a regex that matched nothing would make every later
    # comparison pass over an empty list.
    assert len(found) == 8, found


def test_module_defaults_match_the_vendored_defaults_in_order():
    vendored = _triples(VENDOR.read_text(encoding="utf-8"))
    module_src = MODULE.read_text(encoding="utf-8")
    block = re.search(r"DEFAULT_DELIMITERS\s*=\s*(\[[\s\S]*?\]);", module_src)
    assert block, "DEFAULT_DELIMITERS array not found in math_reflow.js"
    mine = [
        (_js_unescape(m.group(1)), _js_unescape(m.group(2)), m.group(3) == "true")
        for m in re.finditer(
            r'\{\s*left:\s*"((?:[^"\\]|\\.)*)",\s*right:\s*"((?:[^"\\]|\\.)*)",'
            r"\s*display:\s*(true|false)\s*\}",
            block.group(1),
        )
    ]
    assert len(mine) == 8, mine
    assert mine == vendored
