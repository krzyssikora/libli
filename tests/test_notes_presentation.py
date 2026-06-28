import datetime

import pytest

from notes.forms import NoteForm
from notes.models import NOTE_MAX_LEN
from notes.models import NOTE_PALETTE_SIZE
from notes.templatetags.notes_extras import note_colour
from notes.templatetags.notes_extras import note_edited
from notes.templatetags.notes_extras import notes_for_block

pytestmark = pytest.mark.django_db


def test_form_normalizes_and_accepts():
    form = NoteForm(data={"body": "  hi\r\nthere  "})
    assert form.is_valid()
    assert form.cleaned_data["body"] == "hi\nthere"


def test_form_rejects_empty_after_strip():
    assert not NoteForm(data={"body": "   "}).is_valid()


def test_form_rejects_over_cap():
    assert not NoteForm(data={"body": "x" * (NOTE_MAX_LEN + 1)}).is_valid()


def test_note_colour_is_pk_modulo_palette():
    assert note_colour(NOTE_PALETTE_SIZE + 3) == 3


def test_notes_for_block_returns_list_or_empty():
    assert notes_for_block({5: ["a"]}, 5) == ["a"]
    assert notes_for_block({5: ["a"]}, 99) == []
    assert notes_for_block(None, 5) == []


class _N:
    def __init__(self, delta):
        self.created = datetime.datetime(2026, 1, 1, 0, 0, 0)
        self.updated = self.created + datetime.timedelta(seconds=delta)


def test_note_edited_true_only_when_updated_after_created():
    assert note_edited(_N(0)) is False
    assert note_edited(_N(5)) is True
