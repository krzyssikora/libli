from django import template

from notes.models import NOTE_PALETTE_SIZE

register = template.Library()


@register.simple_tag
def note_colour(element_pk):
    """Stable per-block colour index: element pk modulo the palette size."""
    return int(element_pk) % NOTE_PALETTE_SIZE


@register.filter
def note_edited(note):
    """True when the note was changed after creation (> 1s tolerance)."""
    return (note.updated - note.created).total_seconds() > 1


@register.simple_tag
def notes_for_block(notes_by_element, element_pk):
    """The author's notes for one block (empty list when none / dict missing)."""
    if not notes_by_element:
        return []
    return notes_by_element.get(element_pk, [])


@register.simple_tag
def element_label(element):
    """Human label for the block a note is anchored to, for accessibility text.
    Uses the author's optional Element.title, else the content object's humanized
    class name (e.g. TextElement -> 'Text', ImageElement -> 'Image')."""
    if element is None:
        return ""
    if getattr(element, "title", ""):
        return element.title
    obj = element.content_object
    if obj is None:
        return ""
    return obj.__class__.__name__.replace("Element", "") or "Block"
