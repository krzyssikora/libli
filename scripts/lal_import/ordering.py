"""Deterministic ordering of a part folder's .html files by their numeric token."""

import re
from collections import defaultdict

_DIGITS = re.compile(r"\d+")


def ordering_token(filename):
    """Integer value of the first maximal run of digits in the filename.

    Raises ValueError when the filename has no digit run (the parser fails loud
    rather than ordering silently wrong).
    """
    m = _DIGITS.search(filename)
    if m is None:
        raise ValueError(f"no ordering token (digit run) in filename: {filename!r}")
    return int(m.group())


def sort_key(filename):
    """(token, filename): numeric primary key, lexicographic tie-break."""
    return (ordering_token(filename), filename)


def ordered_html_files(names):
    return sorted(names, key=sort_key)


def duplicate_token_warnings(names):
    """One warning record per set of files sharing an ordering token."""
    by_token = defaultdict(list)
    for n in names:
        by_token[ordering_token(n)].append(n)
    out = []
    for token, group in by_token.items():
        if len(group) > 1:
            out.append({
                "kind": "duplicate_ordering_token",
                "reason": f"{len(group)} files share ordering token {token}",
                "names": sorted(group),
            })
    return out
