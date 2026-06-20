"""Drag-and-drop substrate shared by drag-fill-blanks and match-pairs.

The pool, the per-target marker, and the no-JS <select> renderers all live here so
the two question types (and Phase 2d-ii) cannot diverge. The pool is built ONCE by
build_pool() and used by BOTH render and mark, so they never disagree on membership.
"""

from courses.marking import normalize_text
from courses.models import _accepted_lines


def build_pool(question):
    """Deterministic, de-duplicated token pool. Source order is correct tokens
    (gap/right) first, then distractors in author order; the FIRST occurrence of each
    normalize_text key wins (so which raw form survives a collision is deterministic);
    the final list is sorted by normalize_text (presentational only — correctness is
    by text, so order never affects scoring)."""
    raw = list(question.expected_tokens()) + _accepted_lines(question.distractors)
    seen = set()
    deduped = []
    for tok in raw:
        key = normalize_text(tok)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tok)
    return sorted(deduped, key=normalize_text)
