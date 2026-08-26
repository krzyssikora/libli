"""Pairing stored tables with their legacy source.

Matching is on cell TEXT, because that is the only signal the two sides still
share -- and it is content-based rather than driven by the import manifest on
purpose: units 425 and 426 are a hand split of one imported unit and share a
title, and unit 1144 postdates the import entirely. A file->unit map misses
both.

Two text keys in the real data each name three source tables whose LaTeX
differs, and in both groups the difference is ONLY the highlighting (the row
rules are identical and the two unhighlighted members are byte-identical). So
the choice is binary, and `resolve` settles it without ever inventing emphasis.
"""

from collections import Counter
from collections import defaultdict

from courses.longdivision.convert import MARK_TOKEN


def index_by_key(sources):
    """text key -> the source tables carrying it."""
    idx = defaultdict(list)
    for s in sources:
        idx[s.key].append(s)
    return dict(idx)


def resolve(candidates, sibling_files):
    """One source table for a stored table, or None if it cannot be settled.

    `sibling_files` counts the source files that the SAME unit's unambiguous
    matches came from.
    """
    if len({c.latex for c in candidates}) == 1:
        return candidates[0]
    if sibling_files:
        modal = sibling_files.most_common(1)[0][0]
        hit = [c for c in candidates if c.file == modal]
        if hit:
            return hit[0]
    plain = [c for c in candidates if MARK_TOKEN not in c.latex]
    if len({c.latex for c in plain}) == 1:
        return plain[0]
    return None


def plan_unit(db_rows, index):
    """Split one unit's stored tables into (matched, ambiguous, unmatched).

    Two passes: the first settles every table with exactly one possible LaTeX
    and builds the file vote, the second uses that vote on the rest. Done in one
    pass the outcome would depend on row order -- a unit's ambiguous table
    could be resolved before its unambiguous siblings had voted.
    """
    known = [(db_id, index[key]) for db_id, key in db_rows if key in index]
    unmatched = [db_id for db_id, key in db_rows if key not in index]

    sibling_files = Counter(
        cands[0].file for _, cands in known if len({c.latex for c in cands}) == 1
    )

    matched, ambiguous = [], []
    for db_id, cands in known:
        picked = resolve(cands, sibling_files)
        if picked is None:
            ambiguous.append(db_id)
        else:
            matched.append((db_id, picked))
    return matched, ambiguous, unmatched
