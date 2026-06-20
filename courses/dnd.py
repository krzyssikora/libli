"""Drag-and-drop substrate shared by drag-fill-blanks and match-pairs.

The pool, the per-target marker, and the no-JS <select> renderers all live here so
the two question types (and Phase 2d-ii) cannot diverge. The pool is built ONCE by
build_pool() and used by BOTH render and mark, so they never disagree on membership.
"""

from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from courses.fillblank import _TOKEN_RE
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


def _render_select(pool, chosen):
    """One <select name="slot">: a leading empty placeholder then one option per pool
    token. Pre-select the pool option whose NORMALIZED form equals the (normalized)
    `chosen` — membership/pre-selection are normalize-aware, exactly like mark_slots
    (§3.1), so a stored raw form that differs from the deduped survivor of a
    normalize-collision still pre-selects correctly (render and mark never disagree).
    If no normalized match exists (deleted/forged token, or chosen empty), the
    placeholder is selected (resumes as unfilled, not the first token).
    `build_pool` dedups by normalize_text, so at most one pool option matches."""
    chosen_norm = normalize_text(chosen or "")
    matched = chosen_norm != "" and any(normalize_text(t) == chosen_norm for t in pool)
    # Only explicitly mark the placeholder selected when a non-empty, non-pool value was
    # submitted (resume-after-submission case). When chosen is empty/None the browser
    # naturally selects the first option, so we leave the attribute off.
    has_non_empty_unchosen = (chosen or "") != "" and not matched
    placeholder_sel = mark_safe(" selected") if has_non_empty_unchosen else mark_safe("")
    opts = [format_html('<option value=""{}>{}</option>', placeholder_sel, _("— choose —"))]
    for tok in pool:
        sel = (
            mark_safe(" selected")
            if (matched and normalize_text(tok) == chosen_norm)
            else mark_safe("")
        )
        opts.append(format_html('<option value="{}"{}>{}</option>', tok, sel, tok))
    return format_html(
        '<select name="slot" class="dnd__select">{}</select>', mark_safe("".join(opts))
    )


def render_selects(token_stem, pool, chosen=None):
    """Drag-fill: split the token-stem and splice a <select> per gap. Text segments are
    trusted sanitized HTML; only the server-built <select>s are inserted (escaped)."""
    chosen = list(chosen or [])
    parts = _TOKEN_RE.split(token_stem or "")
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)  # trusted sanitized HTML segment
        else:
            n = int(part)
            val = chosen[n] if 0 <= n < len(chosen) else ""
            out.append(str(_render_select(pool, val)))
    return mark_safe("".join(out))  # noqa: S308 — segments sanitized; options escaped


def render_match_rows(pairs, pool, chosen=None):
    """Match-pairs: an <ol> of (left label, <select>) rows in pairs order."""
    chosen = list(chosen or [])
    rows = []
    for i, pair in enumerate(pairs):
        val = chosen[i] if i < len(chosen) else ""
        rows.append(
            format_html(
                '<li class="dnd__row"><span class="dnd__left">{}</span>{}</li>',
                pair.left,
                _render_select(pool, val),
            )
        )
    return format_html('<ol class="dnd__rows">{}</ol>', mark_safe("".join(rows)))
