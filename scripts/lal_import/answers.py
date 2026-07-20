"""Extract interactive-widget answer keys from a LAL file's inline scripts.

Each file writes its correct answers as `localStorage.setItem("KEY",
JSON.stringify({qid: [...], ...}))`. The object is a JS literal, NOT strict
JSON: it carries `//`/`/* */` comments and (for some keys) fractions like
`11/30`. This module parses the flat integer-list keys used by the switch,
one-choice and true/false widgets.
"""

import re

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"//[^\n]*")
_QID_INT_LIST = re.compile(r"(\d+)\s*:\s*\[([^\]]*)\]", re.DOTALL)
_INT = re.compile(r"-?\d+")


def _setitem_re(key):
    return re.compile(
        r"localStorage\.setItem\(\s*['\"]"
        + re.escape(key)
        + r"['\"]\s*,\s*JSON\.stringify\(\s*(\{.*?\})\s*\)\s*\)",
        re.DOTALL,
    )


def _strip_js_comments(s):
    return _COMMENT_LINE.sub("", _COMMENT_BLOCK.sub("", s))


def extract_int_map(html, key):
    """Return {qid: [int, ...]} for a flat-integer-list localStorage key
    (switch_answers, correct_choices, ...); {} if the key is absent."""
    m = _setitem_re(key).search(html)
    if not m:
        return {}
    body = _strip_js_comments(m.group(1))
    return {
        int(qm.group(1)): [int(v) for v in _INT.findall(qm.group(2))]
        for qm in _QID_INT_LIST.finditer(body)
    }
