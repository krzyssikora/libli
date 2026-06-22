"""Pure keyword scoring for the [A] extended-response type (Phase 2d-iii).

fraction = (R_found/R_total) * (1 - F_found/F_total), each factor 1.0 when its
list is empty. Whole-word/phrase match on normalize_text'd text (case-folded;
diacritics preserved). No DB, no randomness — referentially transparent."""

import re

from courses.marking import normalize_text


def _is_present(keyword, norm_answer):
    norm_kw = normalize_text(keyword)
    if not norm_kw:
        return False
    pattern = r"(?<!\w)" + re.escape(norm_kw) + r"(?!\w)"
    return bool(re.search(pattern, norm_answer))


def mark_keywords(answer, required, forbidden):
    norm_answer = normalize_text(answer)
    req_present = [_is_present(k, norm_answer) for k in required]
    forb_present = [_is_present(k, norm_answer) for k in forbidden]
    r_total, f_total = len(required), len(forbidden)
    r_found, f_found = sum(req_present), sum(forb_present)
    req_factor = (r_found / r_total) if r_total else 1.0
    forb_factor = (1 - f_found / f_total) if f_total else 1.0
    fraction = max(0.0, min(1.0, req_factor * forb_factor))
    reveal = tuple(
        {"keyword": k.strip(), "kind": "required", "found": p}
        for k, p in zip(required, req_present, strict=True)
    ) + tuple(
        {"keyword": k.strip(), "kind": "forbidden", "found": p}
        for k, p in zip(forbidden, forb_present, strict=True)
    )
    return fraction, reveal, fraction == 1.0
