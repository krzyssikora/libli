"""Shared helpers for the Fill-in table self-check element. Used by BOTH the
form's answer validation and the check view, so authoring and checking agree on
what counts as an alternative and what counts as blank."""


def split_alternatives(answer):
    """Split a stored answer string on '|' into trimmed, non-empty alternatives."""
    if not isinstance(answer, str):
        return []
    return [part.strip() for part in answer.split("|") if part.strip()]


def is_blank_answer(answer):
    """True iff the answer yields zero non-empty alternatives (blank or pipe-only)."""
    return not split_alternatives(answer)


def answer_cells(cells):
    """Yield (row_index, col_index, answer_string) for every answer cell, 0-based."""
    for r, row in enumerate(cells or []):
        if not isinstance(row, list):
            continue
        for c, cell in enumerate(row):
            if isinstance(cell, dict) and cell.get("kind") == "answer":
                yield r, c, cell.get("answer", "")
