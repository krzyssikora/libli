# Phase 4a — Personal Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any user who can access a lesson attach private, plain-text notes to individual content blocks, manage them while reading (desktop gutter / mobile accordion), and find annotated units via outline count badges.

**Architecture:** A new `notes` Django app (parallels `grouping`) owns the `Note` model, a service choke-point, forms, views, templates, CSS/JS. Notes anchor to a `courses.Element` join-row (within-page) and a `courses.ContentNode` unit (stable page anchor). The `courses` app integrates additively: the lesson view passes the author's notes into context and the lesson template injects a per-block notes region around each `<section data-element-id>`; the outline view passes per-unit counts to a badge partial. CRUD works with no JS (standard POST forms, Post/Redirect/Get); JS is pure enhancement (fragment swaps, hover association).

**Tech Stack:** Python 3.13 + uv, Django 5.2, PostgreSQL, pytest + factory_boy, Playwright (e2e), token-driven CSS (no framework), vanilla JS.

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff`, `uv run pytest`, `uv run python manage.py`. CI runs `uv run ruff format --check` — run `uv run ruff format` (not just `ruff check`) at the end of every task.
- **Spec is authoritative:** `docs/superpowers/specs/2026-06-28-phase-4a-notes-design.md`. This plan implements it; on any conflict, the spec wins.
- **Lessons only:** notes attach only to units with `unit_type == lesson`. Enforced in the `note_add` view via `get_node_or_404(..., require_lesson=True)` AND defensively in `create_note` via an explicit `raise` (never a bare `assert` — stripped under `python -O`).
- **Privacy/scope:** every note is private to its `author`. Create reuses the consumption access gate (`can_access_course`); edit/delete are author-scoped (foreign `note_pk` → 404, never 403/leak).
- **Body:** plain text, normalized (strip ends, CRLF→LF, preserve interior whitespace), capped at **5000** Unicode code points measured identically in form and service; rejected if empty after stripping. HTML-escaped on output; never stored/rendered as HTML.
- **No dual render:** one canonical markup per note/composer (one edit form, one delete form, one `<textarea name=...>` per note); desktop gutter vs mobile accordion is a CSS restyle only.
- **Progressive enhancement:** all CRUD works without JS; association visuals + fragment swaps are enhancement only.
- **i18n:** every user-facing string (incl. `aria-label`s) wrapped for translation; EN source + PL translation in `locale/`. `uv run python manage.py makemessages -l pl -l en` then compile; clear any `#, fuzzy` and `#~` (a test forbids them). Polish inflects by gender/animacy — verify each new msgid's PL.
- **Accessibility:** icon-only controls carry translatable `aria-label`s; counts exposed textually; association never colour-only (each gutter card names its block); controls are real `<button>`/`<a>` and keyboard-focusable.
- **Commits:** one commit per task (or per TDD cycle). Conventional-commit style, scope `4a`.

## File Structure

**New `notes` app:**
- `notes/__init__.py`, `notes/apps.py` — app config.
- `notes/models.py` — `Note` model + `NOTE_MAX_LEN`, `NOTE_PALETTE_SIZE` constants.
- `notes/services.py` — `normalize_body`, `create_note`, `update_note`, `delete_note`, `notes_for_unit`, `note_counts_for_outline`.
- `notes/forms.py` — `NoteForm`.
- `notes/rendering.py` — `lesson_notes_context` (single-sources the lesson notes context keys).
- `notes/views.py` — `note_add`, `note_edit`, `note_delete`.
- `notes/urls.py` — `app_name = "notes"` + routes.
- `notes/templatetags/notes_extras.py` — `note_colour`, `note_edited`, `notes_for_block`.
- `notes/templates/notes/` — `_block_notes.html`, `_note_card.html`, `_composer.html`, `_unanchored.html`, `_outline_badge.html`, `edit_page.html`, `confirm_delete.html`, `result_page.html`.
- `notes/static/notes/css/notes.css`, `notes/static/notes/js/notes.js`.
- `notes/migrations/0001_initial.py`.

**Modified `courses` files:**
- `courses/views.py` — add `full_lesson_render_context`; route `lesson_unit` + `check_answer` no-JS renders through it; `course_outline` passes note counts.
- `templates/courses/_lesson_article.html` — inject per-block notes region + unanchored area.
- `templates/courses/_outline_node.html` — inject badge partial.
- `templates/courses/lesson_unit.html` — link notes CSS/JS.
- `templates/courses/outline.html` — link notes CSS.

**Config / tests:**
- `config/settings/base.py` — add `"notes"` to `INSTALLED_APPS`.
- `config/urls.py` — `path("", include("notes.urls"))`.
- `tests/factories.py` — `NoteFactory`.
- `tests/test_notes_model.py`, `tests/test_notes_services.py`, `tests/test_notes_views.py`, `tests/test_e2e_notes.py`.
- `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`.

---

### Task 1: `notes` app scaffold — `Note` model, migration, factory, registration

**Files:**
- Create: `notes/__init__.py`, `notes/apps.py`, `notes/models.py`, `notes/migrations/__init__.py`
- Modify: `config/settings/base.py` (INSTALLED_APPS), `config/urls.py` (placeholder include via Task 6 — skip here)
- Modify: `tests/factories.py`
- Test: `tests/test_notes_model.py`

**Interfaces:**
- Produces: `notes.models.Note` (fields `author`, `unit`, `element`, `body`, `created`, `updated`); module constants `NOTE_MAX_LEN = 5000`, `NOTE_PALETTE_SIZE = 8`; `tests.factories.NoteFactory`.

- [ ] **Step 1: Create the app package and config**

Create `notes/__init__.py` (empty) and `notes/migrations/__init__.py` (empty).

Create `notes/apps.py`:

```python
from django.apps import AppConfig


class NotesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "notes"
```

- [ ] **Step 2: Register the app**

In `config/settings/base.py`, add `"notes",` to `INSTALLED_APPS` immediately after `"grouping",`:

```python
    "courses",
    "grouping",
    "notes",
```

- [ ] **Step 3: Write the `Note` model**

Create `notes/models.py`:

```python
from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models

NOTE_MAX_LEN = 5000
NOTE_PALETTE_SIZE = 8


class Note(models.Model):
    """A private, plain-text note one user attaches to a content block in a lesson.

    `unit` is the stable page anchor (survives block deletion); `element` is the
    within-page anchor (NULL ⇒ unanchored/orphaned).
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    unit = models.ForeignKey(
        "courses.ContentNode",
        on_delete=models.CASCADE,
        related_name="notes",
        limit_choices_to={"kind": "unit"},
    )
    element = models.ForeignKey(
        "courses.Element",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notes",
    )
    body = models.TextField(validators=[MaxLengthValidator(NOTE_MAX_LEN)])
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created", "pk"]
        indexes = [
            models.Index(fields=["author", "unit"]),
            models.Index(fields=["author", "element"]),
        ]

    def __str__(self):
        return f"Note #{self.pk} by {self.author_id} on unit {self.unit_id}"
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations notes`
Expected: creates `notes/migrations/0001_initial.py`. Open it and confirm `dependencies` includes `('courses', '0026_course_color_bands')` and `migrations.swappable_dependency(settings.AUTH_USER_MODEL)`. (Django infers these; if `courses` shows an older migration, that is fine as long as it resolves — but verify `0026` is present or later.)

- [ ] **Step 5: Add the factories (`ElementFactory` + `NoteFactory`)**

`tests/factories.py` already has `ContentNodeFactory` (defaults to a **lesson** unit: `kind="unit"`, `unit_type="lesson"`), `make_quiz_unit(...)` (a quiz unit), `add_element(unit, obj)`, and `UserFactory`. It does **not** have an `ElementFactory` — downstream tasks rely on one, so define it here.

At the top of `tests/factories.py` (which uses one import per line — `from courses.models import Element`, `from courses.models import ShortTextQuestionElement`, etc.), add two new import lines alongside them: `from courses.models import TextElement` and `from notes.models import Note`.

Add both factories near the other courses factories:

```python
class ElementFactory(factory.django.DjangoModelFactory):
    """An Element join-row in a (lesson) unit, backed by a fresh TextElement.
    Mirrors the proven QuestionResponseFactory pattern of creating the concrete
    content object then attaching it via the GFK."""

    class Meta:
        model = Element

    unit = factory.SubFactory(ContentNodeFactory)  # lesson unit by default
    content_object = factory.LazyFunction(
        lambda: TextElement.objects.create(body="<p>block</p>")
    )


class NoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Note

    author = factory.SubFactory(UserFactory)
    unit = factory.SubFactory(ContentNodeFactory)  # lesson unit by default
    body = factory.Sequence(lambda n: f"note body {n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Spec §4: the factory must not be a backdoor past the 5000-char cap.
        from notes.models import NOTE_MAX_LEN

        body = kwargs.get("body", "")
        if len(body) > NOTE_MAX_LEN:
            raise ValueError("NoteFactory body exceeds NOTE_MAX_LEN")
        return super()._create(model_class, *args, **kwargs)
```

> `Element.objects.create(unit=..., content_object=obj)` is the exact idiom `add_element` and `QuestionResponseFactory` already use, so the `content_object` GFK kwarg is valid. `ElementFactory(unit=u)` overrides the default unit; `ElementFactory()` creates its own lesson unit.

- [ ] **Step 6: Write the failing model tests**

Create `tests/test_notes_model.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from notes.models import NOTE_MAX_LEN, Note
from tests.factories import (
    CourseFactory,
    ElementFactory,
    UserFactory,
)
from courses.models import ContentNode


pytestmark = pytest.mark.django_db


def _lesson_unit(course=None):
    course = course or CourseFactory()
    return ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON, title="U",
    )


def test_note_orders_by_created_then_pk():
    unit = _lesson_unit()
    a = Note.objects.create(author=UserFactory(), unit=unit, body="a")
    b = Note.objects.create(author=a.author, unit=unit, body="b")
    assert list(Note.objects.all()) == [a, b]


def test_deleting_element_sets_note_element_null_preserving_note():
    unit = _lesson_unit()
    el = ElementFactory(unit=unit)
    note = Note.objects.create(author=UserFactory(), unit=unit, element=el, body="x")
    el.delete()
    note.refresh_from_db()
    assert note.element is None
    assert note.unit_id == unit.pk


def test_deleting_unit_cascades_notes():
    unit = _lesson_unit()
    Note.objects.create(author=UserFactory(), unit=unit, body="x")
    unit.delete()
    assert Note.objects.count() == 0


def test_full_clean_rejects_over_cap_body():
    unit = _lesson_unit()
    note = Note(author=UserFactory(), unit=unit, body="x" * (NOTE_MAX_LEN + 1))
    with pytest.raises(ValidationError):
        note.full_clean()
```

> The `_lesson_unit()` helper above builds a lesson unit explicitly; you may equivalently use `ContentNodeFactory()` (already defaults to a lesson unit). `ElementFactory` was defined in Step 5.

- [ ] **Step 7: Run migration + tests**

Run: `uv run python manage.py migrate` then `uv run pytest tests/test_notes_model.py -v`
Expected: all PASS.

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check notes tests/test_notes_model.py
uv run ruff format notes tests/factories.py tests/test_notes_model.py
git add notes config/settings/base.py tests/factories.py tests/test_notes_model.py
git commit -m "feat(4a): notes app scaffold + Note model, migration, factory"
```

---

### Task 2: Services — body normalization + create / update / delete

**Files:**
- Create: `notes/services.py`
- Test: `tests/test_notes_services.py`

**Interfaces:**
- Consumes: `notes.models.Note`, `NOTE_MAX_LEN`; `courses.models.ContentNode` (`unit_type`, `UnitType.LESSON`).
- Produces:
  - `normalize_body(raw: str) -> str` — strip ends, CRLF→LF, preserve interior.
  - `create_note(author, unit, element_pk_or_none, body) -> Note` — receives a **validated lesson `unit` object**; raises `ValueError` if `unit.unit_type != lesson` or if body invalid (empty / over-cap).
  - `update_note(author, note_pk, body) -> Note` — author-scoped (`Http404` on foreign pk); same body rules.
  - `delete_note(author, note_pk) -> None` — author-scoped (`Http404` on foreign pk).

- [ ] **Step 1: Write failing service tests**

Create `tests/test_notes_services.py`:

```python
import pytest
from django.http import Http404

from courses.models import ContentNode
from notes import services
from notes.models import NOTE_MAX_LEN, Note
from tests.factories import CourseFactory, ElementFactory, UserFactory


pytestmark = pytest.mark.django_db


def _lesson(course=None):
    return ContentNode.objects.create(
        course=course or CourseFactory(), kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON, title="U",
    )


def _quiz(course=None):
    return ContentNode.objects.create(
        course=course or CourseFactory(), kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.QUIZ, title="Q",
    )


def test_normalize_strips_ends_normalizes_crlf_preserves_interior():
    assert services.normalize_body("  a\r\n\r\n b  ") == "a\n\n b"


def test_create_anchored_note():
    u = _lesson()
    el = ElementFactory(unit=u)
    author = UserFactory()
    note = services.create_note(author, u, el.pk, "hello")
    assert note.author == author and note.unit == u and note.element == el
    assert note.body == "hello"


def test_create_with_none_element_is_unanchored():
    u = _lesson()
    note = services.create_note(UserFactory(), u, None, "x")
    assert note.element is None


def test_create_with_stale_element_pk_falls_back_to_unanchored():
    u = _lesson()
    note = services.create_note(UserFactory(), u, 999999, "x")
    assert note.element is None


def test_create_with_element_from_other_unit_falls_back_to_unanchored():
    u1, u2 = _lesson(), _lesson()
    el_other = ElementFactory(unit=u2)
    note = services.create_note(UserFactory(), u1, el_other.pk, "x")
    assert note.element is None


def test_create_rejects_quiz_unit():
    q = _quiz()
    with pytest.raises(ValueError):
        services.create_note(UserFactory(), q, None, "x")


def test_create_rejects_empty_body():
    u = _lesson()
    with pytest.raises(ValueError):
        services.create_note(UserFactory(), u, None, "   ")


def test_create_rejects_over_cap_body():
    u = _lesson()
    with pytest.raises(ValueError):
        services.create_note(UserFactory(), u, None, "x" * (NOTE_MAX_LEN + 1))


def test_update_is_author_scoped():
    u = _lesson()
    note = services.create_note(UserFactory(), u, None, "x")
    services.update_note(note.author, note.pk, "y")
    note.refresh_from_db()
    assert note.body == "y"
    with pytest.raises(Http404):
        services.update_note(UserFactory(), note.pk, "z")


def test_delete_is_author_scoped():
    u = _lesson()
    note = services.create_note(UserFactory(), u, None, "x")
    with pytest.raises(Http404):
        services.delete_note(UserFactory(), note.pk)
    services.delete_note(note.author, note.pk)
    assert Note.objects.count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_notes_services.py -v`
Expected: FAIL (module `notes.services` has no such attributes).

- [ ] **Step 3: Implement the services**

Create `notes/services.py`:

```python
from django.shortcuts import get_object_or_404

from courses.models import ContentNode
from notes.models import NOTE_MAX_LEN, Note


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
    return Note.objects.create(
        author=author, unit=unit, element=element, body=body
    )


def update_note(author, note_pk, body):
    note = get_object_or_404(Note, pk=note_pk, author=author)
    note.body = _clean_body(body)
    note.save(update_fields=["body", "updated"])
    return note


def delete_note(author, note_pk):
    note = get_object_or_404(Note, pk=note_pk, author=author)
    note.delete()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_notes_services.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check notes/services.py tests/test_notes_services.py
uv run ruff format notes/services.py tests/test_notes_services.py
git add notes/services.py tests/test_notes_services.py
git commit -m "feat(4a): note CRUD services (normalize, create, update, delete)"
```

---

### Task 3: Services — `notes_for_unit` + `note_counts_for_outline`

**Files:**
- Modify: `notes/services.py`
- Test: `tests/test_notes_services.py`

**Interfaces:**
- Produces:
  - `notes_for_unit(author, unit) -> dict[int | None, list[Note]]` — author's notes in the unit, grouped by `element_id` (key `None` = unanchored), each list ordered by `created, pk`.
  - `note_counts_for_outline(author, course) -> dict[int, int]` — `{unit_pk: count}` of the author's notes per **lesson** unit only (omits non-lesson units entirely; counts include unanchored).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_notes_services.py`:

```python
def test_notes_for_unit_groups_by_element_with_none_bucket():
    u = _lesson()
    el = ElementFactory(unit=u)
    author = UserFactory()
    n1 = services.create_note(author, u, el.pk, "a")
    n2 = services.create_note(author, u, None, "orphan")
    # another user's note must not appear
    services.create_note(UserFactory(), u, el.pk, "other")
    grouped = services.notes_for_unit(author, u)
    assert grouped[el.pk] == [n1]
    assert grouped[None] == [n2]


def test_outline_counts_only_lesson_units_for_author():
    course = CourseFactory()
    lesson = _lesson(course)
    quiz = _quiz(course)
    author = UserFactory()
    services.create_note(author, lesson, None, "a")
    services.create_note(author, lesson, None, "b")
    # dormant note on a (now) quiz unit must NOT be counted
    Note.objects.create(author=author, unit=quiz, body="dormant")
    # another user's note must not be counted
    services.create_note(UserFactory(), lesson, None, "x")
    counts = services.note_counts_for_outline(author, course)
    assert counts == {lesson.pk: 2}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_notes_services.py -k "notes_for_unit or outline_counts" -v`
Expected: FAIL (attributes missing).

- [ ] **Step 3: Implement**

Append to `notes/services.py`:

```python
from collections import defaultdict

from django.db.models import Count


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
```

> NOTE: `notes_for_unit` keys are `element_id` (an int or `None`), matching the test's `grouped[el.pk]` / `grouped[None]`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_notes_services.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check notes/services.py
uv run ruff format notes/services.py tests/test_notes_services.py
git add notes/services.py tests/test_notes_services.py
git commit -m "feat(4a): note query services (notes_for_unit, outline counts)"
```

---

### Task 4: `NoteForm` + presentation template tags

**Files:**
- Create: `notes/forms.py`, `notes/templatetags/__init__.py`, `notes/templatetags/notes_extras.py`
- Test: `tests/test_notes_presentation.py`

**Interfaces:**
- Consumes: `notes.services.normalize_body`, `NOTE_MAX_LEN`, `NOTE_PALETTE_SIZE`.
- Produces:
  - `notes.forms.NoteForm` — single field `body`; `clean_body` normalizes (via `services.normalize_body`), rejects empty + over-cap; on success `cleaned_data["body"]` is the normalized string.
  - templatetag `note_colour(element_pk) -> int` (`element_pk % NOTE_PALETTE_SIZE`).
  - templatefilter `note_edited(note) -> bool` (`(note.updated - note.created).total_seconds() > 1`).
  - simple_tag `notes_for_block(notes_by_element, element_pk) -> list` (`notes_by_element.get(element_pk, [])`).

- [ ] **Step 1: Write failing tests**

Create `tests/test_notes_presentation.py`:

```python
import datetime

import pytest

from notes.forms import NoteForm
from notes.models import NOTE_MAX_LEN, NOTE_PALETTE_SIZE
from notes.templatetags.notes_extras import note_colour, note_edited, notes_for_block


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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_notes_presentation.py -v`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement the form**

Create `notes/forms.py`:

```python
from django import forms
from django.utils.translation import gettext_lazy as _

from notes import services
from notes.models import NOTE_MAX_LEN


class NoteForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": NOTE_MAX_LEN}),
        label=_("Note"),
        strip=False,  # we normalize ourselves; do not let Django pre-strip
    )

    def clean_body(self):
        body = services.normalize_body(self.cleaned_data.get("body", ""))
        if not body:
            raise forms.ValidationError(_("A note cannot be empty."))
        if len(body) > NOTE_MAX_LEN:
            raise forms.ValidationError(_("This note is too long (max 5000 characters)."))
        return body
```

- [ ] **Step 4: Implement the template tags**

Create `notes/templatetags/__init__.py` (empty) and `notes/templatetags/notes_extras.py`:

```python
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
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_notes_presentation.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check notes/forms.py notes/templatetags
uv run ruff format notes/forms.py notes/templatetags tests/test_notes_presentation.py
git add notes/forms.py notes/templatetags tests/test_notes_presentation.py
git commit -m "feat(4a): NoteForm + presentation template tags"
```

---

### Task 5: Lesson read-integration — context helper, partials, template injection

**Files:**
- Create: `notes/rendering.py`, `notes/templates/notes/_block_notes.html`, `notes/templates/notes/_note_card.html`, `notes/templates/notes/_composer.html`, `notes/templates/notes/_unanchored.html`
- Modify: `courses/views.py` (add `full_lesson_render_context`; route `lesson_unit` + `check_answer` through it), `templates/courses/_lesson_article.html`
- Test: `tests/test_notes_views.py`

**Interfaces:**
- Consumes: `notes.services.notes_for_unit`; `courses.views.build_lesson_context`, `build_unit_nav`.
- Produces:
  - `notes.rendering.lesson_notes_context(author, unit, *, show=False) -> dict` with keys `notes_by_element` (`{element_id: [Note]}`, no `None` key), `unanchored_notes` (`[Note]`), `notes_show` (bool).
  - `courses.views.full_lesson_render_context(node, user, *, notes_show=False) -> dict` — `build_lesson_context` + `unit_nav` + feedback defaults + the notes-context keys. **All `lesson_unit.html` renders go through this.**
  - URL names `notes:note_add`, `notes:note_edit`, `notes:note_delete` are **all** referenced by the partials rendered on the lesson page (`_composer.html` reverses `note_add`; `_note_card.html` reverses `note_edit`/`note_delete`). Rendering the lesson page in this task's tests would otherwise raise `NoReverseMatch` (and `notes/urls.py` would fail to import if a referenced view attr is missing). **This task therefore unconditionally creates all three routes plus placeholder view functions** (Step 1); Tasks 6–7 replace the placeholders with real bodies.

- [ ] **Step 1: Create `notes/urls.py` (all three routes) + placeholder `notes/views.py` + project include**

This is mandatory, not optional — the lesson page rendered in Step 6's tests reverses all three names.

Create `notes/urls.py`:

```python
from django.urls import path

from notes import views

app_name = "notes"

urlpatterns = [
    path(
        "courses/<slug:slug>/u/<int:node_pk>/notes/add/",
        views.note_add,
        name="note_add",
    ),
    path("notes/<int:note_pk>/edit/", views.note_edit, name="note_edit"),
    path("notes/<int:note_pk>/delete/", views.note_delete, name="note_delete"),
]
```

Create a placeholder `notes/views.py` so every referenced view attribute exists (real bodies land in Tasks 6–7):

```python
from django.http import HttpResponseNotAllowed


def note_add(request, slug, node_pk):  # replaced in Task 6
    return HttpResponseNotAllowed(["POST"])


def note_edit(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])


def note_delete(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])
```

In `config/urls.py`, add after the grouping include:

```python
    path("", include("notes.urls")),
```

- [ ] **Step 2: Write `lesson_notes_context`**

Create `notes/rendering.py`:

```python
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
```

- [ ] **Step 3: Add `full_lesson_render_context` and route lesson renders through it**

In `courses/views.py`, add this function near `build_lesson_context`:

```python
def full_lesson_render_context(node, user, *, notes_show=False):
    """Full context for rendering courses/lesson_unit.html: lesson context +
    unit nav + feedback defaults + the author's notes. Single-sourced so every
    render site (lesson_unit GET, check_answer re-render, notes no-JS re-render)
    stays consistent."""
    from notes.rendering import lesson_notes_context  # lazy: avoid import cycle

    ctx = build_lesson_context(node, user)
    ctx["unit_nav"] = build_unit_nav(node.course, user, node)
    ctx.update(
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    )
    ctx.update(lesson_notes_context(user, node, show=notes_show))
    return ctx
```

Replace the body of `lesson_unit` (after the quiz redirect) so it uses the helper:

```python
    ctx = full_lesson_render_context(
        node, request.user, notes_show=bool(request.GET.get("notes"))
    )
    return render(request, "courses/lesson_unit.html", ctx)
```

In `check_answer`, change the no-JS re-render branch to start from the helper, then override feedback keys (so notes always render alongside feedback):

```python
    ctx = full_lesson_render_context(node, request.user)
    selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
    submitted = None if isinstance(answer, (set, frozenset)) else answer
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=selected,
        submitted_values=submitted,
        mark_result=result,
    )
    return render(request, "courses/lesson_unit.html", ctx)
```

- [ ] **Step 4: Create the notes partials**

Create `notes/templates/notes/_note_card.html`:

```html
{% load i18n notes_extras %}
<article class="note-card" id="note-{{ note.pk }}"
         {% if note.element_id %}data-anchor-element="{{ note.element_id }}"
         data-colour="{% note_colour note.element_id %}"{% endif %}>
  {% if note.element_id %}
    {% element_label note.element as blk %}
    <p class="note-card__on visually-hidden">{% blocktrans %}on: {{ blk }}{% endblocktrans %}</p>
  {% endif %}
  <p class="note-card__body">{{ note.body|linebreaksbr }}</p>
  <p class="note-card__meta">
    {% if note|note_edited %}{% blocktrans with when=note.updated|timesince %}edited {{ when }} ago{% endblocktrans %}{% else %}{% blocktrans with when=note.updated|timesince %}added {{ when }} ago{% endblocktrans %}{% endif %}
  </p>
  <div class="note-card__actions">
    <a class="note-action note-action--edit"
       href="{% url 'notes:note_edit' note_pk=note.pk %}"
       aria-label="{% trans 'Edit note' %}">✏️</a>
    <a class="note-action note-action--delete"
       href="{% url 'notes:note_delete' note_pk=note.pk %}"
       aria-label="{% trans 'Delete note' %}">🗑</a>
  </div>
</article>
```

> The `note_edit` / `note_delete` URL names reversed above already exist after Step 1 (all three routes + placeholder views are created there), so rendering `_note_card.html` in this task's tests will not `NoReverseMatch`.

Create `notes/templates/notes/_composer.html`. It serves **both** create (action → `note_add`) and edit (action → `note_edit`): the caller passes `edit_pk` when editing. This keeps a single composer template while pointing each submit at the correct endpoint (closes the "edit form posts to note_add" hazard):

```html
{% load i18n %}
<form class="note-composer" method="post"
      action="{% if edit_pk %}{% url 'notes:note_edit' note_pk=edit_pk %}{% else %}{% url 'notes:note_add' slug=course.slug node_pk=unit.pk %}{% endif %}">
  {% csrf_token %}
  {% if not edit_pk %}<input type="hidden" name="element" value="{{ element_pk|default_if_none:'' }}">{% endif %}
  <textarea class="note-composer__input" name="body" rows="3" maxlength="5000"
            aria-label="{% trans 'Write a note' %}">{{ body_value|default:'' }}</textarea>
  {% if body_error %}<p class="note-composer__error" role="alert">{{ body_error }}</p>{% endif %}
  <div class="note-composer__actions">
    <button type="submit" class="btn btn--sm">{% trans "Save" %}</button>
  </div>
</form>
```

Create `notes/templates/notes/_block_notes.html`:

```html
{% load i18n notes_extras %}
{% notes_for_block notes_by_element element.pk as block_notes %}
{% comment %}note_error (set by the no-JS create-failure path, Task 6) re-opens THIS
block's composer with the rejected text + error when its element_pk matches. Compared
as strings: element.pk is an int and the view stores the posted value as a string.{% endcomment %}
<aside class="block-notes" data-anchor-element="{{ element.pk }}"
       data-colour="{% note_colour element.pk %}">
  {% if note_error and note_error.element_pk|stringformat:"s" == element.pk|stringformat:"s" %}
  <details class="block-notes__panel" open>
    <summary class="block-notes__handle">
      <span aria-hidden="true">📝</span>
      {% if block_notes %}
        <span class="block-notes__count">{% blocktrans count n=block_notes|length %}{{ n }} note{% plural %}{{ n }} notes{% endblocktrans %}</span>
      {% else %}
        <span class="block-notes__count">{% trans "Add note" %}</span>
      {% endif %}
    </summary>
    <div class="block-notes__list">
      {% for note in block_notes %}{% include "notes/_note_card.html" with note=note course=course %}{% endfor %}
    </div>
    {% include "notes/_composer.html" with element_pk=element.pk unit=unit course=course body_value=note_error.body body_error=note_error.message %}
  </details>
  {% else %}
  <details class="block-notes__panel"{% if notes_show and block_notes %} open{% endif %}>
    <summary class="block-notes__handle">
      <span aria-hidden="true">📝</span>
      {% if block_notes %}
        <span class="block-notes__count">{% blocktrans count n=block_notes|length %}{{ n }} note{% plural %}{{ n }} notes{% endblocktrans %}</span>
      {% else %}
        <span class="block-notes__count">{% trans "Add note" %}</span>
      {% endif %}
    </summary>
    <div class="block-notes__list">
      {% for note in block_notes %}{% include "notes/_note_card.html" with note=note course=course %}{% endfor %}
    </div>
    {% include "notes/_composer.html" with element_pk=element.pk unit=unit course=course %}
  </details>
  {% endif %}
</aside>
```

> The two `<details>` branches differ only in: the error branch forces `open` and passes `body_value`/`body_error` into the composer. `note_error` is set ONLY by the no-JS create-failure path (Task 6); on a normal render it is absent and the `{% else %}` branch runs.

Create `notes/templates/notes/_unanchored.html`:

```html
{% load i18n %}
{% if unanchored_notes %}
<section class="unanchored-notes">
  <details{% if notes_show %} open{% endif %}>
    <summary class="unanchored-notes__handle">
      <span aria-hidden="true">⚠</span>
      {% blocktrans count n=unanchored_notes|length %}{{ n }} note whose block was removed{% plural %}{{ n }} notes whose block was removed{% endblocktrans %}
    </summary>
    <div class="unanchored-notes__list">
      {% for note in unanchored_notes %}{% include "notes/_note_card.html" with note=note course=course %}{% endfor %}
    </div>
  </details>
</section>
{% endif %}
```

- [ ] **Step 5: Inject notes into the lesson article**

In `templates/courses/_lesson_article.html`, replace the element loop (lines 23–25) with:

```html
  {% for el in elements %}
    <section data-element-id="{{ el.pk }}" class="lesson-block">
      <div class="lesson-block__body">{% render_element el feedback_for_pk=feedback_for_pk selected_ids=selected_ids submitted_values=submitted_values mark_result=mark_result %}</div>
      {% include "notes/_block_notes.html" with element=el notes_by_element=notes_by_element unit=unit course=course notes_show=notes_show %}
    </section>
  {% endfor %}
  {% include "notes/_unanchored.html" with unanchored_notes=unanchored_notes course=course notes_show=notes_show %}
```

- [ ] **Step 6: Write failing view/display tests**

Create `tests/test_notes_views.py`:

```python
import pytest

from courses.models import ContentNode
from notes import services
from tests.factories import CourseFactory, ElementFactory, UserFactory, TEST_PASSWORD


pytestmark = pytest.mark.django_db


def _lesson(course=None):
    return ContentNode.objects.create(
        course=course or CourseFactory(), kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON, title="U",
    )


def _enrolled_user(course):
    from courses.models import Enrollment
    user = UserFactory()
    Enrollment.objects.create(student=user, course=course, source="manual")
    return user


def test_lesson_page_shows_own_notes_not_others(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    services.create_note(me, unit, el.pk, "MY SECRET NOTE")
    other = _enrolled_user(course)
    services.create_note(other, unit, el.pk, "OTHER NOTE")
    client.force_login(me)
    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")
    assert resp.status_code == 200
    assert b"MY SECRET NOTE" in resp.content
    assert b"OTHER NOTE" not in resp.content


def test_lesson_page_shows_unanchored_area(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    services.create_note(me, unit, None, "ORPHAN NOTE")
    client.force_login(me)
    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")
    assert b"ORPHAN NOTE" in resp.content
```

> NOTE: confirm the exact `Enrollment` field names/`source` value used elsewhere (`grep` `Enrollment.objects.create` in `tests/`); the e2e map shows `source="group"`/`"manual"`. Adjust `_enrolled_user` to match. If lesson access for the course owner is simpler, use `CourseFactory(owner=me)` instead of enrollment.

- [ ] **Step 7: Run to verify failure, then make it pass**

Run: `uv run pytest tests/test_notes_views.py -v`
Expected: FAIL first (templates / context missing), then PASS after Steps 2–5 are in place. Iterate until green.

- [ ] **Step 8: Confirm the notes DOM does not collide with `data-element-id` consumers**

**Important:** the notes markup must NOT reuse `data-element-id`. The `<section>` keeps `data-element-id="{{ el.pk }}"` (that is the content element progress.js tracks); the notes `<aside>` and `<article class="note-card">` use **`data-anchor-element`** instead (Step 4 templates already do this). This matters because:
- `courses/static/courses/js/progress.js` does a **global** `document.querySelectorAll("[data-element-id]")` and marks each as a *seen* content element — if notes carried `data-element-id`, auto-completion would mis-fire.
- `tests/test_e2e_courses.py` locates `[data-element-id="<pk>"]` and would hit a Playwright **strict-mode** violation (multiple matches) if a note shared the value.

Verify no notes element carries `data-element-id`, and that the wrapper change is safe for in-element scripts:

```bash
uv run python - <<'PY'
import pathlib, re
roots = ["courses/static/courses/js", "courses/static/courses/css", "core/static/core/css"]
pat = re.compile(r"data-element-id|section|\.lesson\b|render_element|querySelector")
for r in roots:
    for f in pathlib.Path(r).rglob("*"):
        if f.suffix in {".js", ".css"}:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if pat.search(line):
                    print(f"{f}:{i}: {line.strip()}")
PY
```

`progress.js` observes the `[data-element-id]` **sections** (now `.lesson-block`); since the wrapper `.lesson-block__body` lives *inside* the section and the notes use `data-anchor-element`, progress.js is unaffected. `question.js`/`dnd.js`/`math.js` operate inside the rendered element — verify any `>`-combinator or `:first-child` selector tolerates the new `.lesson-block__body` wrapper. The wrapper is **mandatory** (Task 9's gutter grid assigns `.lesson-block__body` to column 1) — do **not** skip it.

- [ ] **Step 9: Run the broader suite + the existing courses e2e to catch regressions**

Run: `uv run pytest tests/ -k "lesson or check_answer or outline or quiz" -v`
Expected: PASS (the refactor must not break existing lesson/quiz-answer tests). Then run the existing courses e2e that uses `[data-element-id]`: `uv run pytest tests/test_e2e_courses.py -m e2e -v` — it must still pass (no strict-mode multiple-match from the notes DOM).

- [ ] **Step 10: Lint + commit**

```bash
uv run ruff check notes config/urls.py courses/views.py
uv run ruff format notes courses/views.py tests/test_notes_views.py
git add notes config/urls.py courses/views.py templates/courses/_lesson_article.html tests/test_notes_views.py
git commit -m "feat(4a): render notes on the lesson page (gutter/accordion markup + context)"
```

---

### Task 6: `note_add` view — create flow (fragment, no-JS PRG, 422, gating, fallback)

**Files:**
- Modify: `notes/views.py` (replace placeholder `note_add`)
- Test: `tests/test_notes_views.py`

**Interfaces:**
- Consumes: `courses.access.get_node_or_404`, `can_access_course`; `courses.views.full_lesson_render_context`; `notes.services.create_note`; `notes.forms.NoteForm`.
- Produces: `note_add(request, slug, node_pk)` —
  - GET (or any non-POST) ⇒ **404** via `raise Http404` (hides the endpoint; consistent with the Step 3 code).
  - Gate: `get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)` then `can_access_course` else `PermissionDenied`.
  - Valid + fragment (`X-Requested-With: fetch`) ⇒ render `_note_card.html`, 201.
  - Valid + no-JS ⇒ 302 redirect to `…/u/<node_pk>/?notes=1#note-<pk>`.
  - Invalid + fragment ⇒ render `_composer.html` (repopulated + error), 422.
  - Invalid + no-JS ⇒ re-render `courses/lesson_unit.html` (full context + error bound to `element_pk`), 422.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_notes_views.py`:

```python
from django.contrib.auth.models import Group as AuthGroup  # noqa: E402

from notes.models import NOTE_MAX_LEN  # noqa: E402


def test_create_note_no_js_redirects_prg(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    client.force_login(me)
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": "hello"},
    )
    assert resp.status_code == 302
    assert f"/courses/{course.slug}/u/{unit.pk}/" in resp["Location"]
    assert "notes=1" in resp["Location"]


def test_create_note_fragment_returns_card(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    client.force_login(me)
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": "frag note"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 201
    assert b"frag note" in resp.content


def test_create_note_invalid_no_js_422_repopulates_rejected_text(client):
    course = CourseFactory()
    unit = _lesson(course)
    el = ElementFactory(unit=unit)
    me = _enrolled_user(course)
    client.force_login(me)
    # over-cap body is rejected; the no-JS re-render must echo the rejected text
    # back into the offending block's composer so the user can fix it.
    rejected = "z" * (NOTE_MAX_LEN + 1)
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": rejected},
    )
    assert resp.status_code == 422
    # the rejected text is repopulated in the composer textarea
    assert rejected.encode() in resp.content
    # nothing persisted
    from notes.models import Note
    assert Note.objects.count() == 0


def test_create_note_inaccessible_course_403(client):
    course = CourseFactory()
    unit = _lesson(course)
    outsider = UserFactory()  # not enrolled, not staff, not owner
    client.force_login(outsider)
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/", {"body": "x"}
    )
    assert resp.status_code == 403


def test_create_note_on_quiz_unit_404(client):
    course = CourseFactory()
    quiz = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.QUIZ, title="Q",
    )
    me = _enrolled_user(course)
    client.force_login(me)
    resp = client.post(
        f"/courses/{course.slug}/u/{quiz.pk}/notes/add/", {"body": "x"}
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_notes_views.py -k create_note -v`
Expected: FAIL (placeholder returns 405).

- [ ] **Step 3: Implement `note_add` (keep the edit/delete placeholders)**

Replace `notes/views.py` with the content below. **Crucially, keep the `note_edit`/`note_delete` placeholder functions** — `notes/urls.py` (Task 5) imports all three, so dropping them would raise `AttributeError` at URLconf load and break every request/test until Task 7. Task 7 replaces the two placeholders with real bodies.

```python
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse

from courses.access import can_access_course, get_node_or_404
from courses.views import full_lesson_render_context
from notes import services
from notes.forms import NoteForm


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def note_edit(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])


def note_delete(request, note_pk):  # replaced in Task 7
    return HttpResponseNotAllowed(["GET", "POST"])


@login_required
def note_add(request, slug, node_pk):
    if request.method != "POST":
        raise Http404  # hide the endpoint before any gate runs
    unit = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    if not can_access_course(request.user, unit.course):
        raise PermissionDenied
    element_pk = request.POST.get("element") or None
    form = NoteForm(request.POST)
    if form.is_valid():
        note = services.create_note(
            request.user, unit, element_pk, form.cleaned_data["body"]
        )
        if _wants_fragment(request):
            return render(
                request,
                "notes/_note_card.html",
                {"note": note, "course": unit.course},
                status=201,
            )
        url = reverse(
            "courses:lesson_unit", kwargs={"slug": slug, "node_pk": node_pk}
        )
        return redirect(f"{url}?notes=1#note-{note.pk}")
    # invalid
    body_error = form.errors.get("body", [""])[0]
    if _wants_fragment(request):
        return render(
            request,
            "notes/_composer.html",
            {
                "element_pk": element_pk,
                "unit": unit,
                "course": unit.course,
                "body_value": request.POST.get("body", ""),
                "body_error": body_error,
            },
            status=422,
        )
    ctx = full_lesson_render_context(unit, request.user, notes_show=True)
    ctx["note_error"] = {"element_pk": element_pk, "body": request.POST.get("body", ""),
                         "message": body_error}
    return render(request, "courses/lesson_unit.html", ctx, status=422)
```

> The `_block_notes.html` partial (Task 5, Step 4) already reads `note_error` and, when `note_error.element_pk` matches the block (string compare), forces `<details open>` and passes `body_value`/`body_error` into the composer. So this view only needs to set `ctx["note_error"]` as shown; the `test_create_note_invalid_no_js_422_repopulates_rejected_text` test (Step 1) verifies the rejected text actually appears. If that test fails, confirm the Task 5 `_block_notes.html` `{% if note_error … %}` branch is present and the string comparison matches.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_notes_views.py -k create_note -v`
Expected: all PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check notes/views.py
uv run ruff format notes/views.py tests/test_notes_views.py
git add notes/views.py templates/courses notes/templates tests/test_notes_views.py
git commit -m "feat(4a): note_add view (create: fragment, no-JS PRG, 422, gating)"
```

---

### Task 7: `note_edit` + `note_delete` views + standalone pages

**Files:**
- Modify: `notes/views.py`, `notes/urls.py`
- Create: `notes/templates/notes/edit_page.html`, `notes/templates/notes/confirm_delete.html`, `notes/templates/notes/result_page.html`
- Test: `tests/test_notes_views.py`

**Interfaces:**
- Consumes: `notes.services.update_note`, `delete_note`; `notes.models.Note`; `courses.access.can_access_course`; `courses.views.full_lesson_render_context`.
- Produces:
  - `note_edit(request, note_pk)` — author-scoped (`get_object_or_404(Note, pk, author=request.user)`).
    - GET ⇒ standalone populated edit form (`edit_page.html`), 200 (no access gate).
    - POST valid + has course access ⇒ 302 to `…/u/<unit>/?notes=1#note-<pk>`; POST valid + access lost ⇒ 302 to `result_page` ("Saved.").
    - POST invalid + fragment ⇒ `_composer.html` edit fragment (action → `note_edit` via `edit_pk`), 422.
    - POST invalid + no-JS ⇒ **re-render the standalone `edit_page.html`** with the rejected body + error, 422 — *regardless of access*. (The lesson page has no inline edit form — edit is a link to the standalone page — so the standalone page is the correct no-JS edit surface for both the has-access and access-lost cases. This is a deliberate, simpler resolution of spec §6.3's "re-render the full lesson page with the edit form open", which assumed an inline lesson edit form this design does not use.)
  - `note_delete(request, note_pk)` — author-scoped.
    - GET ⇒ confirm page (`confirm_delete.html`), 200.
    - POST + has access ⇒ delete then 302 to `…/u/<unit>/?notes=1`; POST + access lost ⇒ delete then 302 to `result_page` ("Deleted.").

- [ ] **Step 1: Finalize URLs (adds the 4th `result` route)**

`notes/urls.py` already has the three routes from Task 5; this step **adds the `result` route** used by the access-lost redirects (Step 3). Final file:

```python
from django.urls import path

from notes import views

app_name = "notes"

urlpatterns = [
    path("courses/<slug:slug>/u/<int:node_pk>/notes/add/", views.note_add, name="note_add"),
    path("notes/<int:note_pk>/edit/", views.note_edit, name="note_edit"),
    path("notes/<int:note_pk>/delete/", views.note_delete, name="note_delete"),
    path("notes/result/", views.note_result, name="result"),
]
```

- [ ] **Step 2: Write failing tests**

Append to `tests/test_notes_views.py`:

```python
def test_edit_get_renders_standalone_form(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "before")
    client.force_login(me)
    resp = client.get(f"/notes/{note.pk}/edit/")
    assert resp.status_code == 200
    assert b"before" in resp.content


def test_edit_foreign_note_404(client):
    course = CourseFactory()
    unit = _lesson(course)
    note = services.create_note(_enrolled_user(course), unit, None, "x")
    client.force_login(UserFactory())
    assert client.get(f"/notes/{note.pk}/edit/").status_code == 404
    assert client.post(f"/notes/{note.pk}/edit/", {"body": "y"}).status_code == 404


def test_edit_post_valid_redirects_to_lesson(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "before")
    client.force_login(me)
    resp = client.post(f"/notes/{note.pk}/edit/", {"body": "after"})
    assert resp.status_code == 302
    note.refresh_from_db()
    assert note.body == "after"


def test_edit_post_invalid_no_js_rerenders_standalone_with_rejected_text(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "before")
    client.force_login(me)
    resp = client.post(f"/notes/{note.pk}/edit/", {"body": "   "})
    assert resp.status_code == 422
    # standalone edit page re-rendered; the note was NOT changed
    note.refresh_from_db()
    assert note.body == "before"
    # the edit form (posting back to note_edit) is present so the user can retry
    assert f"/notes/{note.pk}/edit/".encode() in resp.content


def test_delete_get_shows_confirm_then_post_deletes(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    note = services.create_note(me, unit, None, "x")
    client.force_login(me)
    assert client.get(f"/notes/{note.pk}/delete/").status_code == 200
    resp = client.post(f"/notes/{note.pk}/delete/")
    assert resp.status_code == 302
    from notes.models import Note
    assert not Note.objects.filter(pk=note.pk).exists()


def test_delete_foreign_note_404(client):
    course = CourseFactory()
    unit = _lesson(course)
    note = services.create_note(_enrolled_user(course), unit, None, "x")
    client.force_login(UserFactory())
    assert client.post(f"/notes/{note.pk}/delete/").status_code == 404
```

- [ ] **Step 3: Implement the views**

**Replace** the placeholder `note_edit` and `note_delete` functions in `notes/views.py` (added in Task 6) with the real bodies below — do not append duplicates. Also add the two new imports to the top of the file (`get_object_or_404`, `Note`) and the `_lesson_url` helper.

```python
from django.shortcuts import get_object_or_404  # add to the imports block

from notes.models import Note  # add to the imports block


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


@login_required
def note_edit(request, note_pk):
    note = get_object_or_404(Note, pk=note_pk, author=request.user)
    unit = note.unit
    has_access = can_access_course(request.user, unit.course)
    if request.method == "GET":
        return render(
            request,
            "notes/edit_page.html",
            {"note": note, "unit": unit, "course": unit.course,
             "body_value": note.body, "has_access": has_access},
        )
    form = NoteForm(request.POST)
    if form.is_valid():
        services.update_note(request.user, note.pk, form.cleaned_data["body"])
        if _wants_fragment(request):
            note.refresh_from_db()
            return render(
                request, "notes/_note_card.html",
                {"note": note, "course": unit.course},
            )
        if has_access:
            return redirect(f"{_lesson_url(unit)}?notes=1#note-{note.pk}")
        return redirect(reverse("notes:result") + "?action=saved")
    body_error = form.errors.get("body", [""])[0]
    body_value = request.POST.get("body", "")
    if _wants_fragment(request):
        return render(
            request, "notes/_composer.html",
            {"unit": unit, "course": unit.course,
             "body_value": body_value, "body_error": body_error, "edit_pk": note.pk},
            status=422,
        )
    # No-JS edit failure: the lesson page has no inline edit form (edit is a link
    # to this standalone page), so re-render the standalone edit page for BOTH the
    # has-access and access-lost cases — the rejected text + error surface here.
    return render(
        request, "notes/edit_page.html",
        {"note": note, "unit": unit, "course": unit.course,
         "body_value": body_value, "body_error": body_error, "has_access": has_access},
        status=422,
    )


@login_required
def note_delete(request, note_pk):
    note = get_object_or_404(Note, pk=note_pk, author=request.user)
    unit = note.unit
    has_access = can_access_course(request.user, unit.course)
    if request.method == "GET":
        return render(
            request, "notes/confirm_delete.html",
            {"note": note, "unit": unit, "course": unit.course},
        )
    services.delete_note(request.user, note.pk)
    if has_access:
        return redirect(f"{_lesson_url(unit)}?notes=1")
    return redirect(reverse("notes:result") + "?action=deleted")
```

The `result` route is already in `notes/urls.py` from Step 1. Add the tiny view it points at (append to `notes/views.py`):

```python
@login_required
def note_result(request):
    action = request.GET.get("action")
    return render(request, "notes/result_page.html", {"action": action})
```

- [ ] **Step 4: Create the standalone templates**

Create `notes/templates/notes/edit_page.html`:

```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<main class="note-standalone">
  <h1>{% trans "Edit note" %}</h1>
  <form method="post" action="{% url 'notes:note_edit' note_pk=note.pk %}">
    {% csrf_token %}
    <textarea name="body" rows="6" maxlength="5000"
              aria-label="{% trans 'Note text' %}">{{ body_value|default:'' }}</textarea>
    {% if body_error %}<p class="note-composer__error" role="alert">{{ body_error }}</p>{% endif %}
    <button type="submit" class="btn">{% trans "Save" %}</button>
    {% if has_access %}
    <a class="btn btn--ghost"
       href="{% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">{% trans "Cancel" %}</a>
    {% endif %}
  </form>
</main>
{% endblock %}
```

> `has_access` is `False` only on the dormant/access-lost edit path (the lesson page would 403), so Cancel is hidden there to avoid linking to a forbidden page. When access is present, Cancel returns to the lesson.

Create `notes/templates/notes/confirm_delete.html`:

```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<main class="note-standalone">
  <h1>{% trans "Delete this note?" %}</h1>
  <p>{{ note.body|linebreaksbr }}</p>
  <form method="post" action="{% url 'notes:note_delete' note_pk=note.pk %}">
    {% csrf_token %}
    <button type="submit" class="btn btn--danger">{% trans "Delete" %}</button>
    <a class="btn btn--ghost"
       href="{% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">{% trans "Cancel" %}</a>
  </form>
</main>
{% endblock %}
```

Create `notes/templates/notes/result_page.html`:

```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<main class="note-standalone">
  {% if action == "deleted" %}<p>{% trans "Deleted." %}</p>
  {% else %}<p>{% trans "Saved." %}</p>{% endif %}
</main>
{% endblock %}
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_notes_views.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check notes
uv run ruff format notes tests/test_notes_views.py
git add notes tests/test_notes_views.py
git commit -m "feat(4a): note_edit/note_delete views + standalone edit/confirm/result pages"
```

---

### Task 8: Outline note-count badge

**Files:**
- Modify: `courses/views.py` (`course_outline`), `templates/courses/_outline_node.html`
- Create: `notes/templates/notes/_outline_badge.html`
- Test: `tests/test_notes_views.py`

**Interfaces:**
- Consumes: `notes.services.note_counts_for_outline`.
- Produces: `course_outline` context gains `note_counts` (`{unit_pk: int}`); `_outline_node.html` renders the badge for lesson units with a count.

- [ ] **Step 1: Write failing test**

Append to `tests/test_notes_views.py`:

```python
def test_outline_shows_note_badge_with_count_and_notes_link(client):
    course = CourseFactory()
    unit = _lesson(course)
    me = _enrolled_user(course)
    services.create_note(me, unit, None, "a")
    services.create_note(me, unit, None, "b")
    client.force_login(me)
    resp = client.get(f"/courses/{course.slug}/")
    assert resp.status_code == 200
    assert b"badge--notes" in resp.content
    assert b"notes=1" in resp.content
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_notes_views.py -k outline -v`
Expected: FAIL.

- [ ] **Step 3: Pass note counts into the outline context**

In `courses/views.py`, in `course_outline`, build and pass the counts (lazy import to avoid cycle):

```python
@login_required
def course_outline(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    from notes.services import note_counts_for_outline  # lazy: avoid cycle

    outline = build_outline(course, request.user)
    return render(
        request,
        "courses/outline.html",
        {
            "course": course,
            "outline": outline,
            "note_counts": note_counts_for_outline(request.user, course),
        },
    )
```

- [ ] **Step 4: Create the badge partial + inject it**

Create `notes/templates/notes/_outline_badge.html`:

```html
{% load i18n %}
{% if count %}
<a class="badge badge--notes"
   href="{% url 'courses:lesson_unit' slug=course.slug node_pk=node_pk %}?notes=1"
   aria-label="{% blocktrans count n=count %}{{ n }} note in this unit{% plural %}{{ n }} notes in this unit{% endblocktrans %}">
  <span aria-hidden="true">📝</span> {{ count }}
</a>
{% endif %}
```

First add a `get_item` dict-lookup filter to `notes/templatetags/notes_extras.py` (Django has no built-in for dict-key lookup with a variable key). Append:

```python
@register.filter
def get_item(mapping, key):
    """dict[key] with a graceful miss — for {{ note_counts|get_item:node.pk }}."""
    return (mapping or {}).get(key)
```

Then in `templates/courses/_outline_node.html`, add `{% load notes_extras %}` at the top (next to its existing `{% load %}`), and inject the badge **after the unit's closing `</a>` (line 10), as a sibling of the unit link — NOT inside it.** The unit link is a single `<a class="outline-unit" …>…</a>` spanning lines 6–10; the badge partial is itself an `<a>`, so placing it inside would create invalid nested anchors (browsers auto-close the outer link and the row breaks). Inject:

```html
  {% include "notes/_outline_badge.html" with count=note_counts|get_item:item.node.pk course=course node_pk=item.node.pk %}
```

Keep this inside the same unit branch (e.g. the `{% if item.is_unit %}` / unit-row block) so it only appears for unit rows, immediately after `</a>`. The badge renders only when `count` is truthy (lesson units with ≥1 note); `note_counts` only contains lesson units (Task 3), and a missing key yields `None` ⇒ no badge.

> Verify the exact line for `</a>` in `_outline_node.html` before editing (the map cited lines 6–10); place the include right after it. Add a quick assertion to the Step 1 test that the badge `<a … badge--notes>` is a sibling, not nested — e.g. assert the response does not contain `badge--notes` *before* the unit `</a>` (or simply eyeball the rendered row in the test output). At minimum, do not rely solely on the `badge--notes` substring.

> NOTE: `_outline_node.html` is included recursively. `note_counts` must reach every level. Confirm the include in `outline.html` forwards it (`{% include "courses/_outline_node.html" with item=item course=course note_counts=note_counts %}`), AND that any recursive self-include of `_outline_node.html` for child nodes also forwards `note_counts=note_counts`. Without this, nested units get no badge.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_notes_views.py -k outline -v` then the full notes suite `uv run pytest tests/test_notes_views.py -v`.
Expected: all PASS.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check notes courses/views.py
uv run ruff format notes courses/views.py tests/test_notes_views.py
git add notes courses/views.py templates/courses/_outline_node.html tests/test_notes_views.py
git commit -m "feat(4a): outline note-count badge"
```

---

### Task 9: CSS + JS progressive enhancement

**Files:**
- Create: `notes/static/notes/css/notes.css`, `notes/static/notes/js/notes.js`
- Modify: `templates/courses/lesson_unit.html` (link CSS in head block + JS in extra_js), `templates/courses/outline.html` (link CSS)
- Test: manual (verified by Task 11 e2e + screenshots); no unit test for visuals.

**Interfaces:**
- Consumes: the DOM emitted by Task 5 partials (`.block-notes[data-element-id][data-colour]`, `.note-composer`, `.note-card`, `.unanchored-notes`).
- Produces: desktop gutter layout + association hover/connector + inline composer/edit + inline delete-confirm + fragment submit; degrades to the no-JS `<details>` accordion.

- [ ] **Step 1: Write the CSS**

Create `notes/static/notes/css/notes.css`. Use existing CSS custom properties / tokens (inspect `core/static/core/css/app.css` for `--primary`, surface, border, and dark-mode variables — reuse them; do NOT hard-code colours that fail in dark mode). Minimum required:

```css
/* Palette: 8 stable per-block hues, light + dark via tokens where possible. */
.block-notes { margin-top: .5rem; }
.block-notes__handle { cursor: pointer; display: inline-flex; gap: .35em; align-items: center;
  font-size: .85rem; border: 1px solid var(--border-strong); border-radius: 999px;
  padding: .15em .7em; background: var(--surface-2, #f2f4f7); color: var(--text); }
.block-notes__count { font-weight: 600; }
.note-card { border: 1px solid var(--border-strong); border-left: 4px solid var(--note-accent, #888);
  border-radius: 6px; padding: .5rem .6rem; margin: .4rem 0; background: var(--surface, #fff); }
.note-card__meta { font-size: .72rem; color: var(--text-muted); }
.note-composer__input { width: 100%; box-sizing: border-box; }
.note-composer__error, .badge--notes { /* ... */ }
.unanchored-notes { margin-top: 1rem; border: 1px dashed var(--border-strong); border-radius: 8px;
  padding: .5rem .75rem; }
/* colour map */
.block-notes[data-colour="0"] { --note-accent: #3b82f6; }
.block-notes[data-colour="1"] { --note-accent: #10b981; }
.block-notes[data-colour="2"] { --note-accent: #f59e0b; }
.block-notes[data-colour="3"] { --note-accent: #8b5cf6; }
.block-notes[data-colour="4"] { --note-accent: #ec4899; }
.block-notes[data-colour="5"] { --note-accent: #14b8a6; }
.block-notes[data-colour="6"] { --note-accent: #ef4444; }
.block-notes[data-colour="7"] { --note-accent: #6366f1; }
.note-card[data-colour="0"] { border-left-color: #3b82f6; } /* …repeat 1–7… */

/* Desktop gutter: lift the per-block notes into a right rail. */
@media (min-width: 1024px) {
  .lesson-block { display: grid; grid-template-columns: minmax(0,1fr) 16rem; gap: 1.25rem; align-items: start; }
  .lesson-block__body { grid-column: 1; }
  .lesson-block .block-notes { grid-column: 2; margin-top: 0; }
  .block-notes__panel[open] .block-notes__list { /* gutter cards */ }
}
@media (prefers-reduced-motion: reduce) { /* no transitions */ }
```

Fill in the remaining colour rows (1–7) and badge styling. Keep all colours dark-mode-safe (prefer token accents; the 8 hues above read on both themes).

- [ ] **Step 2: Write the JS enhancement**

Create `notes/static/notes/js/notes.js` (vanilla, `defer`, no framework). It must:
1. **Fragment submit** for the add composer (`.note-composer` posting to `note_add`): intercept submit, `fetch` with `X-Requested-With: fetch`, on 201 inject the returned `_note_card.html` into the block's `.block-notes__list` and clear the textarea; on 422 replace the composer with the returned fragment (shows the error). 
2. **Inline edit** (this is the JS path for the ✏️ control, per spec §6.3): intercept a click on `.note-action--edit` (the ✏️ `<a href=note_edit>`), `preventDefault`, and swap that note's `.note-card` for an inline edit form built from `_composer.html`'s shape — a `<textarea name="body">` prefilled with the card's current body text (read from `.note-card__body`), a Save button, and `action` = the ✏️ link's `href` (the `note_edit` URL) submitted via `fetch`+`X-Requested-With: fetch`. On 200 (returns `_note_card.html`) swap the edit form back to the updated card; on 422 (returns `_composer.html` with `edit_pk`) show the error inline. A Cancel restores the original card. (No extra GET round-trip — the body comes from the DOM.)
3. **Inline delete-confirm**: intercept a click on `.note-action--delete` (🗑 `<a href=note_delete>`), `preventDefault`, show a small inline "Delete? [Yes] [No]" affordance; Yes ⇒ `fetch` POST (with CSRF token + `X-Requested-With: fetch`) to the link's `href`, on success remove the card from the DOM. (No-JS keeps the GET confirm page.)
4. **Association**: on `mouseenter`/`focus` of a `.block-notes__handle` or a `.note-card`, read the anchor's `data-anchor-element` value and add a shared-colour highlight to the matching content section `.lesson-block[data-element-id="<value>"]` + that block's note cards, dimming others; draw a connector (SVG) on desktop. Triggers ONLY on the handle and the card — never the block body. Remove on `mouseleave`/`blur`. Handles/cards must be keyboard-focusable so focus triggers the same cue (spec §9). (Note the two attributes: content sections carry `data-element-id`; notes carry `data-anchor-element` — match one to the other.)

```javascript
(function () {
  "use strict";
  // CSRF helper: read the token from the page (cookie or a hidden input).
  // 1. add-composer fetch submit (201 -> append card, 422 -> replace composer)
  // 2. inline edit: ✏️ click -> swap card for edit form (body from DOM) -> fetch note_edit
  // 3. inline delete-confirm: 🗑 click -> inline confirm -> fetch POST note_delete -> remove card
  // 4. association highlight + connector (handle/card only, never block body; hover + focus)
  // (Implement per spec §6.1, §6.3, §6.4. Keep it dependency-free.)
})();
```

> Implement all four behaviors fully. This is the file Task 11's e2e exercises — it must actually work, not be a stub. The ✏️/🗑 anchors keep working as plain links with no JS (standalone edit/confirm pages); JS upgrades them to inline.

- [ ] **Step 3: Link the assets**

In `templates/courses/lesson_unit.html`, add the CSS to the head/extra-css block (find the existing CSS-link convention — check `base.html` for an `extra_css`/`extra_head` block) and the JS in the `extra_js` block alongside the existing scripts:

```html
  <script src="{% static 'notes/js/notes.js' %}" defer></script>
```
```html
  <link rel="stylesheet" href="{% static 'notes/css/notes.css' %}">
```

In `templates/courses/outline.html`, the stylesheet needs a block to live in: `outline.html` currently defines only `head_title` and `content` (no `extra_css`). Add an `{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'notes/css/notes.css' %}">{% endblock %}` (base.html exposes an empty `extra_css`), and ensure `{% load static %}` is present at the top of `outline.html`. Mirror the CSS-link convention `lesson_unit.html` already uses.

- [ ] **Step 4: Manually verify (screenshots, light + dark)**

Run the app (`uv run python manage.py runserver`) and, with a throwaway Playwright screenshot script, capture the lesson page (desktop gutter + a hovered association) and the outline badge in **both light and dark**. Self-critique contrast (per the project's screenshot-verification habit) and fix. Delete the throwaway script after review.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff format notes
git add notes templates/courses/lesson_unit.html templates/courses/outline.html
git commit -m "feat(4a): notes CSS + JS progressive enhancement (gutter, association, fragments)"
```

---

### Task 10: i18n (PL translations) + accessibility pass

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Modify: any partial missing an `aria-label` (audit)
- Test: `tests/test_i18n_notes.py`

**Interfaces:**
- Produces: every new msgid translated to PL; catalog clean (no `#, fuzzy`, no `#~`).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl -l en --ignore=.venv`
Expected: new msgids from the notes templates/forms/views appear in both `.po` files.

- [ ] **Step 2: Translate to Polish**

Edit `locale/pl/LC_MESSAGES/django.po`, providing PL for each new msgid. Mind animacy/gender and the count plurals (`note`/`notes`, `note whose block was removed`). Suggested:
- "Add note" → "Dodaj notatkę"; "Save" → "Zapisz"; "Cancel" → "Anuluj"; "Edit note" → "Edytuj notatkę"; "Delete note" → "Usuń notatkę"; "Delete this note?" → "Usunąć tę notatkę?"; "Delete" → "Usuń"; "Saved." → "Zapisano."; "Deleted." → "Usunięto."; "Write a note" → "Napisz notatkę"; "Note text" → "Treść notatki"; "A note cannot be empty." → "Notatka nie może być pusta."; "This note is too long (max 5000 characters)." → "Notatka jest za długa (maks. 5000 znaków)."
- Phrase msgids (from `blocktrans`): "edited %(when)s ago" → "edytowano %(when)s temu"; "added %(when)s ago" → "dodano %(when)s temu"; "on: %(blk)s" → "na: %(blk)s".
- For the plural msgids (`{{ n }} note` / `{{ n }} notes`, `{{ n }} note whose block was removed` / `…notes…`, `{{ n }} note in this unit` / `…notes…`), fill all PL plural forms (`nplurals=3` for Polish — provide `msgstr[0]`, `[1]`, `[2]`).

If any copied translation gets a `#, fuzzy` flag, remove the flag after verifying. Remove any `#~` obsolete entries.

- [ ] **Step 3: Write the catalog test**

Create `tests/test_i18n_notes.py` (mirror `tests/test_i18n_auth.py`):

```python
from pathlib import Path

import pytest
from django.utils import translation

ROOT = Path(__file__).resolve().parent.parent
PO = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"

NOTES_MSGIDS = [
    "Add note", "Save", "Cancel", "Edit note", "Delete note",
    "Delete this note?", "Delete", "Saved.", "Deleted.",
    "Write a note", "Note text",
    "A note cannot be empty.",
]
# blocktrans phrase msgids carry placeholders; assert separately that they changed.
NOTES_PHRASE_MSGIDS = [
    "edited %(when)s ago", "added %(when)s ago", "on: %(blk)s",
]


@pytest.mark.parametrize("msgid", NOTES_MSGIDS)
def test_notes_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        assert str(translation.gettext(msgid)) != msgid, f"untranslated PL: {msgid!r}"


@pytest.mark.parametrize("msgid", NOTES_PHRASE_MSGIDS)
def test_notes_phrase_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        assert str(translation.gettext(msgid)) != msgid, f"untranslated PL: {msgid!r}"


def test_po_catalog_clean():
    text = PO.read_text(encoding="utf-8")
    assert "#, fuzzy" not in text
    assert "#~" not in text
```

> NOTE: a translatable string only resolves at runtime if its `.mo` is compiled. Run `uv run python manage.py compilemessages` before the test.

- [ ] **Step 4: Compile + run**

Run: `uv run python manage.py compilemessages` then `uv run pytest tests/test_i18n_notes.py -v`
Expected: all PASS. Also re-run the existing `tests/test_i18n_auth.py::test_po_catalog_clean` to ensure you didn't introduce fuzzies elsewhere.

- [ ] **Step 5: Accessibility audit**

Grep the notes templates for every emoji/icon control and confirm each has a translatable `aria-label` (📝 handle/add, ✏️ edit, 🗑 delete, ⚠ unanchored toggle) and that counts are textual. `_note_card.html` already names its block via the `element_label` tag + a `.visually-hidden` "on: <label>" line (Task 5 / Task 4) — confirm `.visually-hidden` exists in the app CSS (it's a standard screen-reader-only utility; if absent, add the conventional clip rule to `notes.css`). Also extract the `element_label` strings if any are literal. Fix gaps.

- [ ] **Step 6: Commit**

```bash
git add locale tests/test_i18n_notes.py notes/templates
git commit -m "i18n(4a): Polish translations + accessibility labels for notes"
```

---

### Task 11: End-to-end test (real add → see → edit → delete)

**Files:**
- Create: `tests/test_e2e_notes.py`
- Test: itself (run with `-m e2e`)

**Interfaces:**
- Consumes: the full running stack (views, templates, `notes.js`).
- Produces: one e2e proving the real gesture path works (no `page.evaluate` shortcuts).

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_notes.py` (mirror `tests/test_e2e_grouping.py` setup — `pytestmark = pytest.mark.e2e`, the `DJANGO_ALLOW_ASYNC_UNSAFE` session fixture, `_login` helper, `live_server`/`page` fixtures):

```python
import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_add_see_edit_delete_note_via_ui(page, live_server):
    from courses.models import ContentNode, Enrollment
    from institution.roles import STUDENT, seed_roles
    from notes.models import Note
    from tests.factories import CourseFactory, ElementFactory, UserFactory

    seed_roles()
    course = CourseFactory(slug="e2e-notes")
    unit = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON, title="Lesson",
    )
    ElementFactory(unit=unit)
    student = UserFactory(username="e2e_note_student")
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")

    # login helper (copy _login from test_e2e_grouping.py)
    _login(page, live_server, "e2e_note_student")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")

    # ADD: open the block's composer, type, save
    page.locator(".block-notes__handle").first.click()
    page.locator(".note-composer__input").first.fill("my e2e note")
    page.get_by_role("button", name="Save").first.click()

    # SEE: the note appears
    page.wait_for_selector("text=my e2e note")
    assert Note.objects.filter(author=student, body="my e2e note").exists()

    # EDIT then DELETE: drive the real ✏️ / 🗑 controls and assert DB state
    # (follow the inline-edit / inline-confirm gestures notes.js implements)
    # ... assert Note row updated, then deleted ...
```

> Copy `_login` verbatim from `tests/test_e2e_grouping.py`. Drive the **real** UI gestures notes.js wires up (click handle, fill textarea, click Save/Edit/Delete) — do not call `page.evaluate` to shortcut. Finish the EDIT and DELETE assertions against `Note` rows.

- [ ] **Step 2: Run the e2e**

Run: `uv run pytest tests/test_e2e_notes.py -m e2e -v`
Expected: PASS (real browser gestures create/edit/delete the note).

- [ ] **Step 3: Full-suite green + final lint**

Run: `uv run pytest` (default, excludes e2e) then `uv run ruff check` and `uv run ruff format --check`.
Expected: all PASS / clean.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_notes.py
git commit -m "test(4a): e2e add→see→edit→delete note (real gestures)"
```

---

## Self-Review

**Spec coverage:**
- §4 data model → Task 1. §5 services (CRUD, normalization, queries, gating split) → Tasks 2–3 (service) + Task 6 (view-layer gating). §6.1/6.2/6.4 gutter/accordion/single-markup → Tasks 5 + 9. §6.3 compose/edit/delete + no-JS PRG + 422 + standalone pages → Tasks 6–7. §7.1 outline badge → Task 8. §7.2 unanchored area → Tasks 5 (display) + orphan model behavior (Task 1). §8 app registration + URLs + integration seams → Tasks 1, 5, 8. §9 i18n/a11y/security/testing → Tasks 10 (i18n/a11y), gating tests in 6–7, e2e in 11. §11 open details: colour rule (`pk % 8`) → Task 4/9; `?notes=1` mobile behavior chosen as "auto-expand annotated blocks" → encoded in `_block_notes.html` `open` logic (Task 5).
- Gap watch: the no-JS create/edit error must re-open the *specific* offending region — wired via `note_error` in Tasks 6/7 with a guard added to `_block_notes.html`; ensure that guard is actually implemented (call it out during review).

**Placeholder scan:** JS body (Task 9 Step 2) and the e2e EDIT/DELETE tail (Task 11) are deliberately described-not-coded because they're behavior-heavy and environment-specific; both carry explicit "implement fully, not a stub" notes and are covered by the e2e. All Python/model/service/view/form/template code is complete and copyable.

**Type consistency:** `notes_for_unit` returns `{element_id|None: [Note]}`; `lesson_notes_context` pops the `None` key into `unanchored_notes` and leaves `notes_by_element` keyed by `element_id`; `notes_for_block(notes_by_element, element.pk)` looks up by `element.pk` (== `element_id`). `note_counts_for_outline` → `{unit_pk: int}` consumed by `_outline_badge.html` via `count`. `create_note(author, unit, element_pk_or_none, body)` signature matches the view call and all service tests. `full_lesson_render_context` is the single render-context source for `lesson_unit.html` across `lesson_unit`, `check_answer`, and both notes no-JS re-renders.

**Known follow-ups to verify during execution (not blockers):** exact `Enrollment` field/`source` values; the project's real `Element` construction helper (factory name); whether a `get_item` dict filter already exists; the base template's CSS-link block name.
