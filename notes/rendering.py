from notes import services


def lesson_notes_context(author, unit, *, show=False):
    """Single source of the lesson page's notes context keys (used by the lesson
    view, the no-JS validation re-render, and check_answer re-render)."""
    grouped = services.notes_for_unit(author, unit)
    unanchored = grouped.pop(None, [])
    return {
        "notes_by_element": grouped,
        "unanchored_notes": unanchored,
        "notes_show": show,
    }
