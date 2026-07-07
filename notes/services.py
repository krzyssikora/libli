"""Author-scoped CRUD services for personal lesson notes."""

from collections import defaultdict

from django.db.models import Count
from django.shortcuts import get_object_or_404

from courses.models import ContentNode
from notes.models import NOTE_MAX_LEN
from notes.models import Note


def normalize_body(raw):
    """Strip leading/trailing whitespace and normalize CRLF→LF; interior preserved."""
    return (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _clean_body(raw):
    body = normalize_body(raw)
    if not body:
        raise ValueError("Note body must not be empty.")
    if len(body) > NOTE_MAX_LEN:
        raise ValueError("Note body too long.")
    return body


def create_note(author, unit, element_pk_or_none, body):
    """Create a note on a validated lesson `unit`. Defensive lessons-only guard
    (explicit raise, not assert). Stale/foreign element pk ⇒ unanchored fallback."""
    if unit.unit_type != ContentNode.UnitType.LESSON:
        raise ValueError("Notes may only be created on lesson units.")
    body = _clean_body(body)
    element = None
    if element_pk_or_none:
        element = unit.elements.filter(pk=element_pk_or_none).first()
    return Note.objects.create(author=author, unit=unit, element=element, body=body)


def update_note(author, note_pk, body):
    note = get_object_or_404(Note, pk=note_pk, author=author)
    note.body = _clean_body(body)
    note.save(update_fields=["body", "updated"])
    return note


def delete_note(author, note_pk):
    note = get_object_or_404(Note, pk=note_pk, author=author)
    note.delete()


def notes_for_unit(author, unit):
    """Author's notes in `unit`, grouped by element_id (None = unanchored)."""
    grouped = defaultdict(list)
    qs = (
        Note.objects.filter(author=author, unit=unit)
        .select_related("element")
        .order_by("created", "pk")
    )
    for note in qs:
        grouped[note.element_id].append(note)
    return dict(grouped)


def note_counts_for_outline(author, course):
    """{unit_pk: count} of the author's notes per LESSON unit in the course."""
    rows = (
        Note.objects.filter(
            author=author,
            unit__course=course,
            unit__unit_type=ContentNode.UnitType.LESSON,
        )
        .values("unit_id")
        .annotate(n=Count("pk"))
    )
    return {r["unit_id"]: r["n"] for r in rows}
