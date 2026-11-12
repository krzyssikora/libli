"""Pure partitioning of a unit's elements into slides (slideshow mode).

A unit paginates when it contains at least one slide-break element. This helper
splits the ordered Element join-rows on each break, dropping empty groups so a
leading/trailing/consecutive break never yields an empty slide. It returns the
same join-row objects (never unwrapped to content_object) so the caller's render,
data-element-id, and progress paths keep working unchanged."""

from courses.models import SlideBreakElement


def partition_into_slides(elements):
    """Split ordered Element join-rows into a list of non-empty slide groups.

    Breaks are consumed (never emitted). Zero breaks -> one slide with everything
    (or [] if `elements` is empty). Only-breaks -> [] (no content slides)."""
    slides = []
    current = []
    for el in elements:
        if isinstance(el.content_object, SlideBreakElement):
            if current:
                slides.append(current)
                current = []
        else:
            current.append(el)
    if current:
        slides.append(current)
    return slides


def preview_slide_marks(elements):
    """Slide numbers for the editor's live-preview break markers, derived with the
    SAME rule as partition_into_slides so the preview never promises a slide students
    do not get (leading, doubled and trailing breaks make no slide).

    Returns {"total": slides, "lead": bool, "breaks": {pk: n | None}}: `breaks` maps
    each break's pk to the slide it opens, or None when it opens none; `lead` is True
    when the unit paginates but slide 1 has no break above it, so the preview needs a
    marker of its own at the top."""
    breaks = {}
    pending = []  # breaks seen since the last content element
    total = 0
    for el in elements:
        if isinstance(el.content_object, SlideBreakElement):
            pending.append(el.pk)
            continue
        if pending or total == 0:
            total += 1
            if pending:
                breaks[pending.pop()] = total
        breaks.update(dict.fromkeys(pending))
        pending = []
    breaks.update(dict.fromkeys(pending))
    lead = bool(breaks) and total > 0 and 1 not in breaks.values()
    return {"total": total, "lead": lead, "breaks": breaks}
