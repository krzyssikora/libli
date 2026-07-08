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
