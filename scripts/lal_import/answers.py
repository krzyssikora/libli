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
# qid -> a one-level-nested list `[[...], [...]]`: the outer capture holds the
# inner `[...]` row groups (and any whitespace/commas between them).
_QID_NESTED_LIST = re.compile(
    r"(\d+)\s*:\s*\[((?:[^\[\]]*\[[^\[\]]*\])*[^\[\]]*)\]", re.DOTALL
)
_ROW_LIST = re.compile(r"\[([^\[\]]*)\]")
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


def extract_nested_int_map(html, key):
    """Return {qid: [[int, ...], ...]} for a localStorage key whose value is a
    list of integer-list rows (multiple_many_correct_answers: one 0/1 mask row
    per grid row); {} if the key is absent."""
    m = _setitem_re(key).search(html)
    if not m:
        return {}
    body = _strip_js_comments(m.group(1))
    out = {}
    for qm in _QID_NESTED_LIST.finditer(body):
        rows = [
            [int(v) for v in _INT.findall(rm.group(1))]
            for rm in _ROW_LIST.finditer(qm.group(2))
        ]
        out[int(qm.group(1))] = rows
    return out


def _raw_item(tok):
    """Normalize one JS array item to its canonical answer string: a quoted
    string keeps its inner text; a number/fraction keeps its literal form."""
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0]:
        return tok[1:-1]
    return tok


def extract_str_map(html, key):
    """Return {qid: [str, ...]} for a flat localStorage key whose items are
    decimals / fractions / quoted strings (table_answers, answers_fill_next);
    {} if absent. Values are kept in their literal JS form (11/30 stays "11/30")."""
    m = _setitem_re(key).search(html)
    if not m:
        return {}
    body = _strip_js_comments(m.group(1))
    out = {}
    for qm in _QID_INT_LIST.finditer(body):
        items = [_raw_item(t) for t in qm.group(2).split(",")]
        out[int(qm.group(1))] = [it for it in items if it != ""]
    return out
