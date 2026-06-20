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


def mark_slots(expected, pool, chosen):
    """Per-target marking shared by both DnD types. `expected` length is
    authoritative (n_targets). Membership AND matching are tested on the normalized
    form, so a chip whose raw form differs from the deduped survivor still matches and
    is never falsely rejected. chosen[i] missing/out-of-range/"" → unfilled (wrong)."""
    pool_norm = {normalize_text(p) for p in pool}
    chosen = list(chosen or [])
    n_correct = 0
    reveal = []
    for i, want in enumerate(expected):
        got = chosen[i] if i < len(chosen) else ""
        got = got or ""
        got_norm = normalize_text(got)
        is_member = got != "" and got_norm in pool_norm
        ok = is_member and got_norm == normalize_text(want)
        if ok:
            n_correct += 1
        reveal.append({"index": i, "correct": ok, "accepted": want})
    return n_correct, tuple(reveal)
