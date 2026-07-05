# Course Export / Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export a course (or a part/chapter/section/unit subtree) to a versioned zip archive and import it on another instance — full courses become new courses, subtrees graft into an existing course.

**Architecture:** A new `courses/transfer/` package: `schema.py` (format constants + document validation), `export.py` (graph walk → zip), `importer.py` (archive validation → preview → transactional commit), `staging.py` (session-token staging between preview and confirm). Views in `courses/views_transfer.py` follow the `views_export.py` pattern. Bespoke JSON with internal string ids — no pks, no content-type ids, no `dumpdata`.

**Tech Stack:** Django (server-rendered), stdlib `zipfile`/`json`/`tempfile`/`secrets`, pytest + pytest-django, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-07-05-course-export-import-design.md` — the authority for every rule below. When a task references “§N”, that is the spec section.

## Global Constraints

- Tooling: bash `ruff`/`pytest`/`python` are NOT on PATH — always `uv run pytest`, `uv run ruff`, `uv run python manage.py …`.
- Run `uv run ruff format <changed files>` AND `uv run ruff check --fix <changed files>` before every commit (CI runs `ruff format --check`).
- Never hardcode a password literal in tests — use `tests.factories.TEST_PASSWORD` (GitGuardian CI).
- All user-facing strings `gettext`-wrapped; module-level translatable dicts must use `gettext_lazy`. EN/PL translations land in Task 12 (watch makemessages `#, fuzzy` markers — clear them and verify each msgid).
- Django templates: `{# #}` comments are single-line only; use `{% comment %}` for multi-line.
- Every view ships styled (no bare HTML); icons are monochrome currentColor SVGs via the shared `.icon` util.
- All archive-derived strings render through normal autoescaping — never `mark_safe`/unescaped `format_html` (§6).
- Format version 1. Caps (settings constants, Task 1): compressed 1 GiB, uncompressed 1.5 GiB, course.json 10 MiB, manifest.json 64 KiB, 5 000 nodes, 20 000 elements, 1 000 media entries, staging max age 6 h.
- Import is all-or-nothing: any failure → `TransferError` with a specific translated message, never a 500, nothing written.
- When a task says "append" a code block that contains import lines, merge those imports into the file's existing top import block (dropping duplicates) — pasting them mid-file trips ruff E402. The snippets show them inline only for readability.

## File Structure

```
courses/transfer/__init__.py        (empty package marker)
courses/transfer/schema.py          format constants, TransferError, type registry, document validation
courses/transfer/payloads.py        per-type element `data` validators (all 14 types)
courses/transfer/export.py          serialization walk, manifest, zip writing, filenames
courses/transfer/importer.py        archive open/validate, preview builder, commit (course + subtree)
courses/transfer/staging.py         session-slot staging: stage/claim/discard/sweep
courses/views_transfer.py           export + import views
courses/urls.py                     (modify) new routes
courses/models.py                   (modify) ELEMENT_MODELS → 14 entries
courses/color_bands.py              (modify) public is_valid_stored()
courses/migrations/00XX_…           state-only no-op migration (limit_choices_to)
config/settings/base.py             (modify) TRANSFER_* constants
templates/courses/manage/import_course.html      upload form + error rendering
templates/courses/manage/import_preview.html     preview/confirm (shared full-course & subtree)
templates/courses/manage/course_list.html        (modify) Import button + per-row Export
templates/courses/manage/builder.html            (modify) Export / Import content / Export subtree actions
tests/test_transfer_schema.py, test_transfer_export.py, test_transfer_archive.py,
tests/test_transfer_validation.py, test_transfer_media.py, test_transfer_import.py,
tests/test_transfer_subtree.py, test_transfer_staging.py, test_transfer_views.py,
tests/test_e2e_transfer.py
```

Existing seams consumed (verified in code):
- `courses/access.py:can_manage_course(user, course)`; create gate = `permission_required("courses.add_course")` (pattern of `views_manage.course_create`).
- `courses/forms.py:unique_course_slug(title, exclude_pk=None)`.
- `courses/media.py:create_asset(course, kind, uploaded_file, user, name="")`, `truncate_filename(name)`, `_MEDIA_REF_MODELS`.
- `courses/ordering.py:kinds_for_flags(parts, chapters, sections)`, `legal_child_kinds(parent_kind, allowed_kinds)`.
- `courses/validators.py:validate_embed_url`, `effective_image_extensions()`, `effective_video_extensions()`, `effective_max_image_bytes()`, `effective_max_video_bytes()`.
- `courses/video_url.py:canonicalize_video_url(raw)`; `courses/embed.py:extract_embed_url(raw)` (both raise `ValidationError`).
- `courses/fillblank.py:SENTINEL`.
- `courses/models.py`: `ZONE_COORD_EPSILON`, `DragZone.clean()` (the shared zone-bounds authority — validate by instantiating an unsaved `DragZone` and calling `.clean()`), `ContentNode.RANK`, `Course.allowed_kinds`.
- URL names: `manage_course_list`, `manage_builder`, `manage_course_edit`; templates `courses/manage/builder.html`, `courses/manage/course_list.html` (confirm exact list-template path with Glob before editing).
- Tests: reuse `tests/factories.py` (`TEST_PASSWORD`, existing user/course factories — check names there before writing test setup; if no course factory exists, `Course.objects.create(title=…, slug=…, owner=…)` directly).

---

### Task 1: Foundations — settings caps, ELEMENT_MODELS fix, public color-bands validator, TransferError

**Files:**
- Modify: `config/settings/base.py` (append after the media/upload settings block)
- Modify: `courses/models.py:207-218` (`ELEMENT_MODELS`)
- Modify: `courses/color_bands.py`
- Create: `courses/transfer/__init__.py`, `courses/transfer/schema.py` (constants + error only in this task)
- Create: `courses/migrations/` (generated), `tests/test_transfer_schema.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `settings.TRANSFER_MAX_COMPRESSED_BYTES` etc. (names below); `courses.color_bands.is_valid_stored(raw) -> bool`; `courses.transfer.schema.TransferError` (attribute `.message`), `FORMAT_VERSION = 1`, `KIND_COURSE = "course"`, `KIND_SUBTREE = "subtree"`; `ELEMENT_MODELS` with 14 entries.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transfer_schema.py
from django.conf import settings

from courses.color_bands import default_color_bands
from courses.color_bands import is_valid_stored
from courses.models import ELEMENT_MODELS
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError


def test_element_models_lists_all_14_concrete_element_models():
    assert len(ELEMENT_MODELS) == 14
    for name in (
        "extendedresponsequestionelement",
        "dragfillblankquestionelement",
        "matchpairquestionelement",
        "dragtoimagequestionelement",
    ):
        assert name in ELEMENT_MODELS


def test_transfer_settings_constants():
    assert settings.TRANSFER_MAX_COMPRESSED_BYTES == 1 * 1024**3
    assert settings.TRANSFER_MAX_UNCOMPRESSED_BYTES == 1536 * 1024**2  # 1.5 GiB
    assert settings.TRANSFER_MAX_COURSE_JSON_BYTES == 10 * 1024**2
    assert settings.TRANSFER_MAX_MANIFEST_BYTES == 64 * 1024
    assert settings.TRANSFER_MAX_NODES == 5000
    assert settings.TRANSFER_MAX_ELEMENTS == 20000
    assert settings.TRANSFER_MAX_MEDIA_ENTRIES == 1000
    assert settings.TRANSFER_STAGING_MAX_AGE_HOURS == 6
    assert settings.TRANSFER_STAGING_DIR  # a path, not under MEDIA_ROOT
    assert str(settings.MEDIA_ROOT) not in str(settings.TRANSFER_STAGING_DIR)


def test_is_valid_stored_public_wrapper():
    assert is_valid_stored(
        [dict(b, label="") for b in default_color_bands()]
    ) or is_valid_stored(default_color_bands())
    assert not is_valid_stored([{"key": "junk"}])
    assert not is_valid_stored("not-a-list")


def test_transfer_error_carries_message():
    err = TransferError("boom")
    assert err.message == "boom"
    assert FORMAT_VERSION == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: courses.transfer` / `ImportError: is_valid_stored` / settings `AttributeError`.

- [ ] **Step 3: Implement**

`config/settings/base.py` — append:

```python
# --- Course transfer (export/import) — spec 2026-07-05. Deployment guardrails,
# not product limits; deployments hosting bigger courses raise them (and must
# raise proxy body-size + worker timeout limits to match — see docs note).
TRANSFER_MAX_COMPRESSED_BYTES = 1 * 1024**3  # 1 GiB zip upload
TRANSFER_MAX_UNCOMPRESSED_BYTES = 1536 * 1024**2  # 1.5 GiB declared/actual total
TRANSFER_MAX_COURSE_JSON_BYTES = 10 * 1024**2
TRANSFER_MAX_MANIFEST_BYTES = 64 * 1024
TRANSFER_MAX_NODES = 5000
TRANSFER_MAX_ELEMENTS = 20000
TRANSFER_MAX_MEDIA_ENTRIES = 1000
TRANSFER_STAGING_MAX_AGE_HOURS = 6
# NOT under MEDIA_ROOT: staged archives must never be web-served (spec §4.3/§6).
TRANSFER_STAGING_DIR = BASE_DIR / "transfer_staging"
```

Also append `transfer_staging/` to `.gitignore` (staged zips must never be committed — the plan's commit steps use `git add -A`).

`courses/models.py` — extend the list (order: content elements then questions):

```python
ELEMENT_MODELS = [
    "textelement",
    "imageelement",
    "videoelement",
    "iframeelement",
    "mathelement",
    "htmlelement",
    "choicequestionelement",
    "shorttextquestionelement",
    "extendedresponsequestionelement",
    "shortnumericquestionelement",
    "fillblankquestionelement",
    "dragfillblankquestionelement",
    "matchpairquestionelement",
    "dragtoimagequestionelement",
]
```

`courses/color_bands.py` — add below `_is_valid_stored`:

```python
def is_valid_stored(raw):
    """Public alias for the stored-shape check (course transfer import uses it;
    course_color_bands keeps calling the private name)."""
    return _is_valid_stored(raw)
```

`courses/transfer/__init__.py` — empty file.

`courses/transfer/schema.py`:

```python
"""Course transfer archive format: constants, error type, document validation.

Format spec: docs/superpowers/specs/2026-07-05-course-export-import-design.md §2/§5.
"""

FORMAT_VERSION = 1
KIND_COURSE = "course"
KIND_SUBTREE = "subtree"


class TransferError(Exception):
    """Any export/import rejection. `message` is user-facing and translated."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)
```

- [ ] **Step 4: Generate the state-only migration**

Run: `uv run python manage.py makemigrations courses -n extend_element_models`
Expected: one migration, a single `AlterField` on `element.content_type` (limit_choices_to only — no SQL). Sanity: `uv run python manage.py migrate` applies cleanly; `uv run python manage.py makemigrations --check --dry-run` reports no missing migrations.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_transfer_schema.py -v`
Expected: PASS. Also run `uv run pytest tests/test_courses_models.py tests/test_color_bands.py -v` (no regressions — the extended `ELEMENT_MODELS` only widens admin/form choices).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format config/settings/base.py courses/models.py courses/color_bands.py courses/transfer/ tests/test_transfer_schema.py
uv run ruff check --fix .
git add -A
git commit -m "feat(transfer): settings caps, 14-entry ELEMENT_MODELS (+no-op migration), public color-bands validator"
```

---

### Task 2: Export element serializers (all 14 types)

**Files:**
- Create: `courses/transfer/export.py` (serializers only in this task)
- Test: `tests/test_transfer_export.py`

**Interfaces:**
- Consumes: concrete element models from `courses.models`; `TransferError` unused here.
- Produces:
  - `courses.transfer.export.MediaIdMap` — class; `register(asset) -> str` returns the stable internal id (`"m1"`, `"m2"`… in first-reference order), `items() -> list[(internal_id, MediaAsset)]`.
  - `courses.transfer.export.serialize_element_data(concrete, media_ids) -> (type_key: str, data: dict)` — raises `TransferError` on an unknown model (defensive; cannot happen for `ElementBase` subclasses).
  - Data shapes exactly per spec §2.3 (Task 6's validator consumes the same shapes — keep in lockstep):
    - decimals as `str(value)`; `max_attempts` as int or `None`
    - `video`: both keys always present, exactly one non-null: `{"url": str, "media": str|None}` — a URL video has `media: None`; a file video has `url: ""`? **No** — normalize: file video → `{"url": null, "media": "mN"}`, URL video → `{"url": "<url>", "media": null}`.
    - newline blobs (`accepted`, `distractors`, `required_keywords`, `forbidden_keywords`) as the stored string verbatim.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transfer_export.py
from decimal import Decimal

import pytest

from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Course
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import MediaAsset
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.transfer.export import MediaIdMap
from courses.transfer.export import serialize_element_data

pytestmark = pytest.mark.django_db


@pytest.fixture
def course():
    return Course.objects.create(title="Src", slug="src")


@pytest.fixture
def image_asset(course, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    from django.core.files.uploadedfile import SimpleUploadedFile

    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile("pic.png", b"\x89PNG fake"),
        original_filename="pic.png",
    )


def test_text_element(course):
    el = TextElement.objects.create(body="<p>hello</p>")
    key, data = serialize_element_data(el, MediaIdMap())
    assert key == "text"
    assert data == {"body": "<p>hello</p>"}


def test_image_element_registers_media(course, image_asset):
    el = ImageElement.objects.create(media=image_asset, alt="a", figcaption="c")
    ids = MediaIdMap()
    key, data = serialize_element_data(el, ids)
    assert key == "image"
    assert data == {"media": "m1", "alt": "a", "figcaption": "c"}
    assert ids.items() == [("m1", image_asset)]


def test_media_id_map_is_stable_on_reuse(course, image_asset):
    ids = MediaIdMap()
    el1 = ImageElement.objects.create(media=image_asset)
    el2 = ImageElement.objects.create(media=image_asset)
    serialize_element_data(el1, ids)
    _, data2 = serialize_element_data(el2, ids)
    assert data2["media"] == "m1"
    assert len(ids.items()) == 1


def test_video_url_variant(course):
    el = VideoElement.objects.create(url="https://www.youtube.com/embed/x")
    key, data = serialize_element_data(el, MediaIdMap())
    assert key == "video"
    assert data == {"url": "https://www.youtube.com/embed/x", "media": None}


def test_choice_question(course):
    q = ChoiceQuestionElement.objects.create(
        stem="Pick", multiple=False, max_marks=Decimal("2.50")
    )
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False)
    key, data = serialize_element_data(q, MediaIdMap())
    assert key == "choice"
    assert data["multiple"] is False
    assert data["max_marks"] == "2.50"
    assert data["max_attempts"] == 1
    assert data["choices"] == [
        {"text": "A", "is_correct": True},
        {"text": "B", "is_correct": False},
    ]


def test_short_numeric_decimals_are_strings(course):
    q = ShortNumericQuestionElement.objects.create(
        value=Decimal("3.14159265"), tolerance=Decimal("0.001")
    )
    _, data = serialize_element_data(q, MediaIdMap())
    assert data["value"] == "3.14159265"
    assert data["tolerance"] == "0.001"


def test_all_14_types_have_a_serializer(course, image_asset):
    q_kwargs = {}
    fixtures = [
        TextElement.objects.create(body="b"),
        ImageElement.objects.create(media=image_asset),
        VideoElement.objects.create(url="https://www.youtube.com/embed/x"),
        IframeElement.objects.create(url="https://www.youtube.com/embed/y"),
        MathElement.objects.create(latex="x^2"),
        HtmlElement.objects.create(html="<b>raw</b>"),
        ChoiceQuestionElement.objects.create(stem="s", **q_kwargs),
        ShortTextQuestionElement.objects.create(accepted="a\nb", **q_kwargs),
        ExtendedResponseQuestionElement.objects.create(
            required_keywords="k", **q_kwargs
        ),
        ShortNumericQuestionElement.objects.create(value=Decimal("1"), **q_kwargs),
        FillBlankQuestionElement.objects.create(stem="￿0￿", **q_kwargs),
        DragFillBlankQuestionElement.objects.create(
            stem="￿0￿", distractors="d", **q_kwargs
        ),
        MatchPairQuestionElement.objects.create(distractors="", **q_kwargs),
        DragToImageQuestionElement.objects.create(media=image_asset, **q_kwargs),
    ]
    keys = {serialize_element_data(el, MediaIdMap())[0] for el in fixtures}
    assert keys == {
        "text", "image", "video", "iframe", "math", "html",
        "choice", "short_text", "extended_response", "short_numeric",
        "fill_blank", "drag_fill_blank", "match_pair", "drag_to_image",
    }


def test_fill_blank_children_and_sentinel_stem(course):
    q = FillBlankQuestionElement.objects.create(stem="a ￿0￿ b")
    Blank.objects.create(question=q, accepted="x\ny", case_sensitive=False)
    _, data = serialize_element_data(q, MediaIdMap())
    assert data["stem"] == "a ￿0￿ b"
    assert data["blanks"] == [{"accepted": "x\ny", "case_sensitive": False}]


def test_drag_to_image_zones(course, image_asset):
    q = DragToImageQuestionElement.objects.create(media=image_asset, alt="pic")
    DragZone.objects.create(question=q, correct_label="L", x=0.1, y=0.2, w=0.3, h=0.4)
    _, data = serialize_element_data(q, MediaIdMap())
    assert data["zones"] == [
        {"correct_label": "L", "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    ]
    assert data["media"] == "m1"


def test_match_pair_and_drag_fill_children(course):
    mp = MatchPairQuestionElement.objects.create(distractors="z")
    MatchPair.objects.create(question=mp, left="L", right="R")
    _, mp_data = serialize_element_data(mp, MediaIdMap())
    assert mp_data["pairs"] == [{"left": "L", "right": "R"}]
    df = DragFillBlankQuestionElement.objects.create(stem="￿0￿")
    DragBlank.objects.create(question=df, correct_token="tok")
    _, df_data = serialize_element_data(df, MediaIdMap())
    assert df_data["blanks"] == [{"correct_token": "tok"}]
```

Note: `FillBlankQuestionElement.save` sanitizes the stem — the sentinel char survives `sanitize_html` (it is plain text). If a test fixture's stem comes back altered, create via `.objects.create` then re-read; assert against the stored value.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_export.py -v`
Expected: FAIL — `ImportError: courses.transfer.export`.

- [ ] **Step 3: Implement `courses/transfer/export.py` (serializer half)**

```python
"""Export: serialize a course/subtree content graph to the archive format (§2)."""

from courses.models import ChoiceQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from courses.models import VideoElement
from courses.transfer.schema import TransferError


class MediaIdMap:
    """Stable asset-pk -> internal id ("m1", "m2", …) in first-reference order."""

    def __init__(self):
        self._by_pk = {}
        self._assets = []

    def register(self, asset):
        if asset.pk not in self._by_pk:
            self._by_pk[asset.pk] = f"m{len(self._assets) + 1}"
            self._assets.append(asset)
        return self._by_pk[asset.pk]

    def items(self):
        return [(self._by_pk[a.pk], a) for a in self._assets]


def _question_fields(q):
    return {
        "stem": q.stem,
        "explanation": q.explanation,
        "marking_mode": q.marking_mode,
        "max_attempts": q.max_attempts,
        "max_marks": str(q.max_marks),
    }


def _ser_text(el, ids):
    return {"body": el.body}


def _ser_image(el, ids):
    return {"media": ids.register(el.media), "alt": el.alt, "figcaption": el.figcaption}


def _ser_video(el, ids):
    if el.media_id is not None:
        return {"url": None, "media": ids.register(el.media)}
    return {"url": el.url, "media": None}


def _ser_iframe(el, ids):
    return {"url": el.url, "title": el.title}


def _ser_math(el, ids):
    return {"latex": el.latex}


def _ser_html(el, ids):
    return {"html": el.html}


def _ser_choice(el, ids):
    return {
        **_question_fields(el),
        "multiple": el.multiple,
        "choices": [
            {"text": c.text, "is_correct": c.is_correct} for c in el.choices.all()
        ],
    }


def _ser_short_text(el, ids):
    return {
        **_question_fields(el),
        "accepted": el.accepted,
        "case_sensitive": el.case_sensitive,
    }


def _ser_extended(el, ids):
    return {
        **_question_fields(el),
        "required_keywords": el.required_keywords,
        "forbidden_keywords": el.forbidden_keywords,
    }


def _ser_numeric(el, ids):
    return {
        **_question_fields(el),
        "value": str(el.value),
        "tolerance": str(el.tolerance),
    }


def _ser_fill_blank(el, ids):
    return {
        **_question_fields(el),
        "blanks": [
            {"accepted": b.accepted, "case_sensitive": b.case_sensitive}
            for b in el.blanks.all()
        ],
    }


def _ser_drag_fill(el, ids):
    return {
        **_question_fields(el),
        "distractors": el.distractors,
        "blanks": [{"correct_token": b.correct_token} for b in el.dragblanks.all()],
    }


def _ser_match_pair(el, ids):
    return {
        **_question_fields(el),
        "distractors": el.distractors,
        "pairs": [{"left": p.left, "right": p.right} for p in el.pairs.all()],
    }


def _ser_drag_to_image(el, ids):
    return {
        **_question_fields(el),
        "media": ids.register(el.media),
        "alt": el.alt,
        "distractors": el.distractors,
        "zones": [
            {"correct_label": z.correct_label, "x": z.x, "y": z.y, "w": z.w, "h": z.h}
            for z in el.zones.all()
        ],
    }


# type_key -> (model, serializer). The 14-entry registry; Task 6's importer-side
# registry in schema.py mirrors these keys — keep both in lockstep.
SERIALIZERS = {
    "text": (TextElement, _ser_text),
    "image": (ImageElement, _ser_image),
    "video": (VideoElement, _ser_video),
    "iframe": (IframeElement, _ser_iframe),
    "math": (MathElement, _ser_math),
    "html": (HtmlElement, _ser_html),
    "choice": (ChoiceQuestionElement, _ser_choice),
    "short_text": (ShortTextQuestionElement, _ser_short_text),
    "extended_response": (ExtendedResponseQuestionElement, _ser_extended),
    "short_numeric": (ShortNumericQuestionElement, _ser_numeric),
    "fill_blank": (FillBlankQuestionElement, _ser_fill_blank),
    "drag_fill_blank": (DragFillBlankQuestionElement, _ser_drag_fill),
    "match_pair": (MatchPairQuestionElement, _ser_match_pair),
    "drag_to_image": (DragToImageQuestionElement, _ser_drag_to_image),
}

_MODEL_TO_KEY = {model: key for key, (model, _fn) in SERIALIZERS.items()}


def serialize_element_data(concrete, media_ids):
    key = _MODEL_TO_KEY.get(type(concrete))
    if key is None:  # pragma: no cover — every ElementBase subclass is registered
        raise TransferError(f"Unserializable element model: {type(concrete).__name__}")
    _model, fn = SERIALIZERS[key]
    return key, fn(concrete, media_ids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transfer_export.py -v` — PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format courses/transfer/export.py tests/test_transfer_export.py && uv run ruff check --fix .
git add -A && git commit -m "feat(transfer): element serializers for all 14 types with internal media ids"
```

---

### Task 3: Export document + manifest + zip archive builder

**Files:**
- Modify: `courses/transfer/export.py` (append)
- Test: `tests/test_transfer_export.py` (append)

**Interfaces:**
- Consumes: Task 2's `MediaIdMap`, `serialize_element_data`; `courses.models.Element`, `ContentNode`.
- Produces:
  - `build_export(course, node=None, source_host="") -> (manifest: dict, document: dict, media_assets: list[(mid, MediaAsset)])` — `node=None` → full course; else subtree rooted at `node`. Runs inside `transaction.atomic()`; node list snapshotted in ONE query (§3).
  - `write_archive(course, node, fileobj, source_host="") -> None` — writes the complete zip (deflated) into `fileobj` (a spooled temp file). Entry names: `manifest.json`, `course.json`, `media/<mid><ext-lowercased-from-original_filename>`.
  - `export_filename(course, node, today) -> str` — `"{slug}-export-{iso}.zip"`, subtree `"{slug}-{slugify(node.title) or 'content'}-export-{iso}.zip"`.
  - Document shapes exactly §2.2: full course has `course` block (`title, language, overview, html_css, html_js, uses_parts, uses_chapters, uses_sections, color_bands, subjects[{title_en,title_pl}]`); subtree has `context` block (`source_course_title, root_kind, required_kinds, html_css, html_js`). Node dicts: `{id, parent, kind, title, unit_type, obligatory, html_seed_js}` (no `order` key — sequence IS the order). Element dicts: `{id, unit, title, type, data}`. Media dicts: `{id, kind, name, original_filename, file}`.
  - Manifest: `{format_version, kind, exported_at, source: {instance, app_version}, course: {title, slug}, media_total_bytes}`; subtree adds `node: {title, kind}`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_transfer_export.py`)

```python
import io
import json
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile

from courses.models import ContentNode
from courses.models import Element
from courses.transfer.export import build_export
from courses.transfer.export import export_filename
from courses.transfer.export import write_archive


def _mk_tree(course):
    part = ContentNode.objects.create(course=course, kind="part", title="P1")
    chap = ContentNode.objects.create(
        course=course, kind="chapter", title="C1", parent=part
    )
    unit = ContentNode.objects.create(
        course=course, kind="unit", title="U1", parent=chap, unit_type="lesson"
    )
    return part, chap, unit


def _attach(unit, concrete, title=""):
    return Element.objects.create(unit=unit, title=title, content_object=concrete)


def test_build_export_full_course_document(course, image_asset):
    part, chap, unit = _mk_tree(course)
    _attach(unit, TextElement.objects.create(body="hi"))
    _attach(unit, ImageElement.objects.create(media=image_asset, alt="a"))
    manifest, doc, media = build_export(course)
    assert manifest["format_version"] == 1
    assert manifest["kind"] == "course"
    assert manifest["course"] == {"title": "Src", "slug": "src"}
    assert doc["course"]["title"] == "Src"
    assert "slug" not in doc["course"]
    assert [n["kind"] for n in doc["nodes"]] == ["part", "chapter", "unit"]
    assert doc["nodes"][0]["parent"] is None
    assert doc["nodes"][1]["parent"] == doc["nodes"][0]["id"]
    assert "order" not in doc["nodes"][0]
    assert [e["type"] for e in doc["elements"]] == ["text", "image"]
    assert doc["elements"][0]["unit"] == doc["nodes"][2]["id"]
    assert [m["id"] for m in doc["media"]] == ["m1"]
    assert doc["media"][0]["file"] == "media/m1.png"
    assert media[0][1] == image_asset


def test_referenced_only_media(course, image_asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    unused = MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile("unused.png", b"x"),
        original_filename="unused.png",
    )
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    _manifest, doc, media = build_export(course)
    assert len(doc["media"]) == 1
    assert unused.pk not in {a.pk for _mid, a in media}


def test_non_unit_empty_string_unit_type_exports_as_null(course):
    # Admin-saved rows can hold unit_type="" on non-units; export normalizes.
    part = ContentNode.objects.create(course=course, kind="part", title="P")
    ContentNode.objects.filter(pk=part.pk).update(unit_type="")
    _manifest, doc, _media = build_export(course)
    assert doc["nodes"][0]["unit_type"] is None


def test_build_export_subtree_context(course):
    part, chap, unit = _mk_tree(course)
    manifest, doc, _media = build_export(course, node=chap)
    assert manifest["kind"] == "subtree"
    assert manifest["node"] == {"title": "C1", "kind": "chapter"}
    assert doc["context"]["root_kind"] == "chapter"
    assert sorted(doc["context"]["required_kinds"]) == ["chapter", "unit"]
    assert "course" not in doc
    assert doc["nodes"][0]["parent"] is None  # root's parent nulled
    assert [n["kind"] for n in doc["nodes"]] == ["chapter", "unit"]


def test_write_archive_roundtrips_zip(course, image_asset):
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
        assert names == {"manifest.json", "course.json", "media/m1.png"}
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["media_total_bytes"] == image_asset.file.size
        assert zf.read("media/m1.png") == image_asset.file.open("rb").read()


def test_export_filename(course):
    import datetime

    part, chap, unit = _mk_tree(course)
    d = datetime.date(2026, 7, 5)
    assert export_filename(course, None, d) == "src-export-2026-07-05.zip"
    assert export_filename(course, chap, d) == "src-c1-export-2026-07-05.zip"
    chap.title = "!!!"
    assert export_filename(course, chap, d) == "src-content-export-2026-07-05.zip"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_export.py -v` — new tests FAIL with ImportError.

- [ ] **Step 3: Implement (append to `courses/transfer/export.py`)**

```python
import json
import os
import zipfile

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _

from courses.models import Element
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import KIND_COURSE
from courses.transfer.schema import KIND_SUBTREE


def _ordered_nodes(course, root=None):
    """Snapshot the whole node list in one query, then walk depth-first in
    (order, pk) sibling order. Parent always precedes child (format invariant)."""
    cmap = {}
    for n in course.nodes.all().order_by("order", "pk"):
        cmap.setdefault(n.parent_id, []).append(n)
    out = []

    def walk(pid):
        for n in cmap.get(pid, []):
            out.append(n)
            walk(n.pk)

    if root is None:
        walk(None)
    else:
        out.append(root)
        walk(root.pk)
    return out


def _node_dict(node, nid, parent_internal):
    return {
        "id": nid,
        "parent": parent_internal,
        "kind": node.kind,
        "title": node.title,
        # `or None`: admin-saved non-unit rows can hold "" (CharField, clean()
        # only rejects truthy values) — keep the archive canonical (null) so a
        # legitimately exported course survives the strict null-only import rule.
        "unit_type": node.unit_type or None,
        "obligatory": node.obligatory,
        "html_seed_js": node.html_seed_js,
    }


def build_export(course, node=None, source_host=""):
    with transaction.atomic():
        nodes = _ordered_nodes(course, root=node)
        node_ids = {}
        node_dicts = []
        for i, n in enumerate(nodes, start=1):
            nid = f"n{i}"
            node_ids[n.pk] = nid
            parent_internal = (
                None
                if (node is not None and n.pk == node.pk)
                else node_ids.get(n.parent_id)
            )
            node_dicts.append(_node_dict(n, nid, parent_internal))

        media_ids = MediaIdMap()
        element_dicts = []
        i = 0
        unit_pks = [n.pk for n in nodes if n.kind == "unit"]
        joins_by_unit = {}
        for join in (
            Element.objects.filter(unit_id__in=unit_pks)
            .order_by("unit_id", "order", "pk")
            .prefetch_related("content_object")
        ):
            joins_by_unit.setdefault(join.unit_id, []).append(join)
        for n in nodes:
            for join in joins_by_unit.get(n.pk, []):
                i += 1
                if join.content_object is None:  # dangling GFK: concrete row gone
                    raise TransferError(
                        _("Unit “%(unit)s” contains a broken element — repair or "
                          "delete it before exporting.") % {"unit": n.title}
                    )
                type_key, data = serialize_element_data(
                    join.content_object, media_ids
                )
                element_dicts.append(
                    {
                        "id": f"e{i}",
                        "unit": node_ids[n.pk],
                        "title": join.title,
                        "type": type_key,
                        "data": data,
                    }
                )

        media_dicts = []
        total_bytes = 0
        for mid, asset in media_ids.items():
            ext = os.path.splitext(asset.original_filename)[1].lower()
            try:
                total_bytes += asset.file.size
            except OSError as exc:  # orphaned FileField: row intact, file gone
                raise TransferError(
                    _("Media file missing from storage: %(name)s")
                    % {"name": asset.original_filename}
                ) from exc
            media_dicts.append(
                {
                    "id": mid,
                    "kind": asset.kind,
                    "name": asset.name,
                    "original_filename": asset.original_filename,
                    "file": f"media/{mid}{ext}",
                }
            )

        if node is None:
            head = {
                "course": {
                    "title": course.title,
                    "language": course.language,
                    "overview": course.overview,
                    "html_css": course.html_css,
                    "html_js": course.html_js,
                    "uses_parts": course.uses_parts,
                    "uses_chapters": course.uses_chapters,
                    "uses_sections": course.uses_sections,
                    "color_bands": course.color_bands,
                    "subjects": [
                        {"title_en": s.title_en, "title_pl": s.title_pl}
                        for s in course.subjects.all().order_by("title_en", "pk")
                    ],
                }
            }
        else:
            head = {
                "context": {
                    "source_course_title": course.title,
                    "root_kind": node.kind,
                    "required_kinds": sorted({n["kind"] for n in node_dicts}),
                    "html_css": course.html_css,
                    "html_js": course.html_js,
                }
            }

        document = {
            **head,
            "nodes": node_dicts,
            "elements": element_dicts,
            "media": media_dicts,
        }
        manifest = {
            "format_version": FORMAT_VERSION,
            "kind": KIND_COURSE if node is None else KIND_SUBTREE,
            "exported_at": timezone.now().isoformat(),
            "source": {"instance": source_host, "app_version": ""},
            "course": {"title": course.title, "slug": course.slug},
            "media_total_bytes": total_bytes,
        }
        if node is not None:
            manifest["node"] = {"title": node.title, "kind": node.kind}
        return manifest, document, media_ids.items()


def write_archive(course, node, fileobj, source_host=""):
    manifest, document, media_assets = build_export(course, node, source_host)
    entry_by_mid = {m["id"]: m["file"] for m in document["media"]}
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("course.json", json.dumps(document, ensure_ascii=False))
        for mid, asset in media_assets:
            with asset.file.open("rb") as src, zf.open(entry_by_mid[mid], "w") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)


def export_filename(course, node, today):
    if node is None:
        return f"{course.slug}-export-{today.isoformat()}.zip"
    seg = slugify(node.title) or "content"
    return f"{course.slug}-{seg}-export-{today.isoformat()}.zip"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transfer_export.py -v` — PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format courses/transfer/export.py tests/test_transfer_export.py && uv run ruff check --fix .
git add -A && git commit -m "feat(transfer): document/manifest builder and zip archive writer (course + subtree)"
```

---

### Task 4: Export views, URLs, UI entry points

**Files:**
- Create: `courses/views_transfer.py` (export half)
- Modify: `courses/urls.py`
- Modify: `templates/courses/manage/course_list.html` (per-row Export action) and `templates/courses/manage/builder.html` (course Export button + per-node "Export subtree" action) — locate exact templates with Glob first; follow their existing action-markup patterns (`.row-actions` / builder node action cluster).
- Test: `tests/test_transfer_views.py`

**Interfaces:**
- Consumes: `write_archive`, `export_filename` (Task 3); `courses.access.can_manage_course`.
- Produces: URL names `manage_course_export` (`manage/courses/<slug:slug>/export/`), `manage_node_export` (`manage/courses/<slug:slug>/build/node/<int:pk>/export/`). Views `export_course(request, slug)`, `export_subtree(request, slug, pk)` — GET only, `FileResponse` with `as_attachment=True`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transfer_views.py
import io
import zipfile

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Course
from tests.factories import TEST_PASSWORD  # reuse existing user factory if present

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user("owner", password=TEST_PASSWORD)


@pytest.fixture
def outsider(django_user_model):
    return django_user_model.objects.create_user("outsider", password=TEST_PASSWORD)


@pytest.fixture
def course(owner):
    c = Course.objects.create(title="Src", slug="src", owner=owner)
    ContentNode.objects.create(course=c, kind="unit", title="U", unit_type="lesson")
    return c


def test_export_course_streams_zip(client, owner, course):
    client.force_login(owner)
    resp = client.get(reverse("courses:manage_course_export", args=[course.slug]))
    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment;")
    assert "src-export-" in resp["Content-Disposition"]
    body = b"".join(resp.streaming_content)
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert {"manifest.json", "course.json"} <= set(zf.namelist())


def test_export_requires_edit_rights(client, outsider, course):
    client.force_login(outsider)
    resp = client.get(reverse("courses:manage_course_export", args=[course.slug]))
    assert resp.status_code == 403


def test_subtree_export_scoped_to_url_course(client, owner, course):
    other = Course.objects.create(title="Other", slug="other", owner=owner)
    foreign = ContentNode.objects.create(
        course=other, kind="unit", title="X", unit_type="lesson"
    )
    client.force_login(owner)
    resp = client.get(
        reverse("courses:manage_node_export", args=[course.slug, foreign.pk])
    )
    assert resp.status_code == 404  # forged cross-course node id → 404, no archive


def test_subtree_export_ok(client, owner, course):
    node = course.nodes.first()
    client.force_login(owner)
    resp = client.get(
        reverse("courses:manage_node_export", args=[course.slug, node.pk])
    )
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_views.py -v` — FAIL (`NoReverseMatch`).

- [ ] **Step 3: Implement**

`courses/views_transfer.py`:

```python
import tempfile

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET

from courses.access import can_manage_course
from courses.models import ContentNode
from courses.models import Course
from courses.transfer.export import export_filename
from courses.transfer.export import write_archive
from courses.transfer.schema import TransferError


def _stream_archive(request, course, node):
    # Spool fully before streaming: a mid-build failure raises here and returns a
    # clean error response, never a truncated zip (§3).
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    try:
        write_archive(course, node, spool, source_host=request.get_host())
    except TransferError as exc:  # e.g. a media file missing from storage
        spool.close()
        messages.error(request, exc.message)
        # Builder is the deliberate landing spot even for list-page exports:
        # it's the repair surface for a broken element/media reference.
        return redirect("courses:manage_builder", slug=course.slug)
    spool.seek(0)
    return FileResponse(
        spool,
        as_attachment=True,
        filename=export_filename(course, node, timezone.localdate()),
        content_type="application/zip",
    )


@login_required
@require_GET
def export_course(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    return _stream_archive(request, course, None)


@login_required
@require_GET
def export_subtree(request, slug, pk):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    node = get_object_or_404(ContentNode, pk=pk, course=course)  # scoped: forged → 404
    return _stream_archive(request, course, node)
```

`courses/urls.py` — add (near the other manage course routes; import `views_transfer` at top):

```python
    path(
        "manage/courses/<slug:slug>/export/",
        views_transfer.export_course,
        name="manage_course_export",
    ),
    path(
        "manage/courses/<slug:slug>/build/node/<int:pk>/export/",
        views_transfer.export_subtree,
        name="manage_node_export",
    ),
```

Templates: add an "Export" link (`{% trans "Export" %}`, plain `<a href>` styled like sibling actions) to the manage course-list row actions and the builder header; add "Export subtree" to each node's action cluster in the builder tree include (find the node-row include via `Grep "manage_node_panel" templates/`). Use existing icon/button classes; do not invent new CSS. Gate templates the way their siblings gate: the course-list rows already render only manageable courses, and the builder page is already permission-gated — Export needs no extra conditional there, but never render an action a colder-scoped sibling wouldn't.

- [ ] **Step 4: Run tests; screenshot check**

Run: `uv run pytest tests/test_transfer_views.py -v` — PASS. Then `uv run pytest tests/test_e2e_builder.py -v` (builder templates changed — catch breakage).
UI: per house rules, verify the new buttons in light+dark with a throwaway Playwright screenshot script (delete after review).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format courses/views_transfer.py courses/urls.py tests/test_transfer_views.py && uv run ruff check --fix .
git add -A && git commit -m "feat(transfer): export views + URLs + manage/builder export actions"
```

---

### Task 5: Import archive reader — zip-level validation + counted extraction

**Files:**
- Modify: `courses/transfer/importer.py` (create)
- Test: `tests/test_transfer_archive.py`

**Interfaces:**
- Consumes: settings caps (Task 1), `TransferError`, `FORMAT_VERSION`.
- Produces (in `courses/transfer/importer.py`):
  - `read_archive(fileobj, *, expected_kind) -> (zf: zipfile.ZipFile, manifest: dict, document: dict, media_entries: dict[str, ZipInfo])` — runs ALL §5 archive-level checks. Caller owns/closes `zf` (or use the `open_archive` context manager below).
  - `open_archive(fileobj, *, expected_kind)` — `@contextmanager` yielding the same tuple, closing `zf` on exit.
  - `read_entry_bytes(zf, info, cap, what) -> bytes` — counting read: aborts (TransferError) if actual bytes exceed `min(cap, info.file_size)`.
  - `extract_entry_to_tempfile(zf, info) -> file object` — spooled temp file, counted against `info.file_size`; `.name` NOT meaningful (caller wraps in `django.core.files.File` with an explicit name).
  - `parse_json_bytes(raw, what) -> dict` — wraps `json.loads`; `ValueError`/`UnicodeDecodeError`/`RecursionError`/non-dict top level → `TransferError` (“…is not a valid JSON object”).
- Manifest schema enforced here: exactly the keys `format_version, kind, exported_at, source, course, media_total_bytes` (+ `node` required iff kind=subtree); `source` exactly `{instance, app_version}`; `course` exactly `{title, slug}`; unknown keys reject naming the key; `format_version` must be an int ≤ `FORMAT_VERSION`; `kind` must equal `expected_kind` (mismatch message points at the correct entry point); `media_total_bytes` int ≥ 0 and ≤ uncompressed cap.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transfer_archive.py
import io
import json
import zipfile

import pytest

from courses.transfer.importer import open_archive
from courses.transfer.schema import TransferError


def make_manifest(**over):
    m = {
        "format_version": 1,
        "kind": "course",
        "exported_at": "2026-07-05T12:00:00+00:00",
        "source": {"instance": "test", "app_version": ""},
        "course": {"title": "T", "slug": "t"},
        "media_total_bytes": 0,
    }
    m.update(over)
    return m


def make_zip(entries=None, manifest=None, document=None):
    """entries: extra (name, bytes) pairs. Returns BytesIO of a zip with
    manifest.json + course.json (+ extras)."""
    doc = document if document is not None else {
        "course": {
            "title": "T", "language": "en", "overview": "",
            "html_css": "", "html_js": "",
            "uses_parts": True, "uses_chapters": True, "uses_sections": True,
            "color_bands": [], "subjects": [],
        },
        "nodes": [], "elements": [], "media": [],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest or make_manifest()))
        zf.writestr("course.json", json.dumps(doc))
        for name, data in entries or []:
            zf.writestr(name, data)
    buf.seek(0)
    return buf


def _reject(buf, needle, kind="course"):
    with pytest.raises(TransferError) as exc:
        with open_archive(buf, expected_kind=kind):
            pass
    assert needle.lower() in exc.value.message.lower()
    return exc.value.message


def test_happy_path():
    with open_archive(make_zip(), expected_kind="course") as (zf, mani, doc, media):
        assert mani["kind"] == "course"
        assert doc["nodes"] == []
        assert media == {}


def test_not_a_zip():
    _reject(io.BytesIO(b"plain text"), "zip")


def test_compressed_cap(settings):
    settings.TRANSFER_MAX_COMPRESSED_BYTES = 10
    _reject(make_zip(), "at most 10")  # message names the configured limit


def test_uncompressed_declared_cap(settings):
    settings.TRANSFER_MAX_UNCOMPRESSED_BYTES = 8
    _reject(make_zip(), "large")


def test_manifest_size_cap(settings):
    settings.TRANSFER_MAX_MANIFEST_BYTES = 4
    _reject(make_zip(), "manifest")


def test_course_json_size_cap(settings):
    settings.TRANSFER_MAX_COURSE_JSON_BYTES = 4
    _reject(make_zip(), "course.json")


def test_duplicate_entry_names_reject():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(make_manifest()))
        zf.writestr("course.json", "{}")
        zf.writestr("course.json", "{}")  # duplicate
    buf.seek(0)
    _reject(buf, "duplicate")


def test_path_traversal_rejects():
    _reject(make_zip(entries=[("../evil.txt", b"x")]), "entry")
    _reject(make_zip(entries=[("media/sub/dir.png", b"x")]), "entry")
    _reject(make_zip(entries=[("other.txt", b"x")]), "entry")


def test_directory_entries_ignored():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(make_manifest()))
        zf.writestr(
            "course.json",
            json.dumps({"course": {
                "title": "T", "language": "en", "overview": "",
                "html_css": "", "html_js": "", "uses_parts": True,
                "uses_chapters": True, "uses_sections": True,
                "color_bands": [], "subjects": []},
                "nodes": [], "elements": [], "media": []}),
        )
        zf.writestr("media/", b"")  # zero-length dir entry → ignored
    buf.seek(0)
    with open_archive(buf, expected_kind="course"):
        pass  # no raise


def test_newer_format_version_named():
    msg = _reject(make_zip(manifest=make_manifest(format_version=99)), "version")
    assert "99" in msg


def test_version_below_one_rejects():
    _reject(make_zip(manifest=make_manifest(format_version=0)), "version")


def test_nondict_manifest_node_rejects():
    mani = make_manifest(kind="subtree", node=["title", "kind"])
    _reject(make_zip(manifest=mani), "node", kind="subtree")


def test_kind_mismatch_points_at_other_entry():
    _reject(make_zip(), "content", kind="subtree")  # course zip at subtree entry


def test_unknown_manifest_key_rejects():
    _reject(make_zip(manifest=make_manifest(surprise=1)), "surprise")


def test_nonstring_manifest_text_field_rejects():
    _reject(make_zip(manifest=make_manifest(course={"title": {"a": 1},
                                                    "slug": "t"})), "text")


def test_missing_manifest_rejects():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("course.json", "{}")
    buf.seek(0)
    _reject(buf, "manifest")


def test_malformed_json_rejects():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", "{not json")
        zf.writestr("course.json", "{}")
    buf.seek(0)
    _reject(buf, "json")


def test_deeply_nested_json_rejects_not_500():
    deep = "[" * 200_000 + "]" * 200_000
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(make_manifest()))
        zf.writestr("course.json", deep)
    buf.seek(0)
    _reject(buf, "json")


def test_lying_header_counted_read(settings):
    # Declared sizes pass the cap, but a tampered header must not allow reading
    # more than declared: build a zip, then shrink the central-directory size.
    import struct  # noqa: F401  (documenting intent; simplest check below)
    buf = make_zip(entries=[("media/m1.png", b"A" * 1000)])
    with zipfile.ZipFile(buf) as zf:
        info = zf.getinfo("media/m1.png")
        info.file_size = 10  # lie: declared 10, actual 1000
        from courses.transfer.importer import read_entry_bytes

        with pytest.raises(TransferError):
            read_entry_bytes(zf, info, cap=10_000, what="media/m1.png")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_transfer_archive.py -v` → ImportError.

- [ ] **Step 3: Implement `courses/transfer/importer.py` (archive half)**

```python
"""Import: archive/document validation, preview, and transactional commit (§4/§5)."""

import json
import os
import tempfile
import zipfile
from contextlib import contextmanager

from django.conf import settings
from django.utils.translation import gettext as _

from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import KIND_COURSE
from courses.transfer.schema import KIND_SUBTREE
from courses.transfer.schema import TransferError

_CHUNK = 1024 * 1024


def parse_json_bytes(raw, what):
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        doc = None
    if not isinstance(doc, dict):
        raise TransferError(
            _("The archive's %(name)s is not a valid JSON object.") % {"name": what}
        )
    return doc


def read_entry_bytes(zf, info, cap, what):
    if info.file_size > cap:
        raise TransferError(
            _("%(name)s exceeds the configured limit of %(limit)d bytes.")
            % {"name": what, "limit": cap}
        )
    out = b""
    # zipfile itself raises BadZipFile/zlib.error mid-read on tampered entries
    # (CRC or size mismatch) — map ALL read failures to TransferError, and keep
    # our own byte count as defense in depth against lying headers.
    try:
        with zf.open(info) as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                out += chunk
                if len(out) > info.file_size:  # lying header
                    raise TransferError(
                        _("%(name)s is larger than its declared size.")
                        % {"name": what}
                    )
    except TransferError:
        raise
    except Exception as exc:  # BadZipFile, zlib.error, OSError
        raise TransferError(
            _("The archive entry %(name)s is corrupt.") % {"name": what}
        ) from exc
    return out


def extract_entry_to_tempfile(zf, info):
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    read = 0
    try:
        with zf.open(info) as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                read += len(chunk)
                if read > info.file_size:
                    raise TransferError(
                        _("%(name)s is larger than its declared size.")
                        % {"name": info.filename}
                    )
                spool.write(chunk)
    except TransferError:
        spool.close()
        raise
    except Exception as exc:  # BadZipFile, zlib.error, OSError
        spool.close()
        raise TransferError(
            _("The archive entry %(name)s is corrupt.") % {"name": info.filename}
        ) from exc
    spool.seek(0)
    return spool


def _require_exact_keys(obj, required, what):
    missing = [k for k in required if k not in obj]
    if missing:
        raise TransferError(
            _("%(name)s is missing the key '%(key)s'.")
            % {"name": what, "key": missing[0]}
        )
    unknown = [k for k in obj if k not in required]
    if unknown:
        raise TransferError(
            _("%(name)s contains an unknown key '%(key)s'.")
            % {"name": what, "key": unknown[0]}
        )


def _validate_manifest(manifest, expected_kind):
    keys = [
        "format_version", "kind", "exported_at", "source", "course",
        "media_total_bytes",
    ]
    if manifest.get("kind") == KIND_SUBTREE:
        keys.append("node")
    _require_exact_keys(manifest, keys, "manifest.json")
    version = manifest["format_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise TransferError(_("manifest.json: format_version must be a positive "
                              "integer."))
    if version > FORMAT_VERSION:
        raise TransferError(
            _(
                "This archive uses format version %(found)d, but this instance "
                "supports up to version %(max)d. It was exported from a newer "
                "application version."
            )
            % {"found": version, "max": FORMAT_VERSION}
        )
    kind = manifest["kind"]
    if kind not in (KIND_COURSE, KIND_SUBTREE):
        raise TransferError(_("manifest.json: unknown archive kind."))
    if kind != expected_kind:
        if expected_kind == KIND_COURSE:
            raise TransferError(
                _(
                    "This archive contains course content (a subtree), not a whole "
                    "course. Use 'Import content' on the target course's builder "
                    "page instead."
                )
            )
        raise TransferError(
            _(
                "This archive contains a whole course, not a content subtree. "
                "Use 'Import course' on the course list instead."
            )
        )
    if not isinstance(manifest["source"], dict) or not isinstance(
        manifest["course"], dict
    ):
        raise TransferError(_("manifest.json: malformed source/course block."))
    _require_exact_keys(manifest["source"], ["instance", "app_version"], "source")
    _require_exact_keys(manifest["course"], ["title", "slug"], "manifest course")
    # The preview renders these — a non-str value would show a Python repr.
    str_fields = [
        manifest["exported_at"],
        manifest["source"]["instance"], manifest["source"]["app_version"],
        manifest["course"]["title"], manifest["course"]["slug"],
    ]
    if kind == KIND_SUBTREE:
        if not isinstance(manifest["node"], dict):  # a list would pass key loops
            raise TransferError(_("manifest.json: malformed node block."))
        _require_exact_keys(manifest["node"], ["title", "kind"], "manifest node")
        str_fields += [manifest["node"]["title"], manifest["node"]["kind"]]
    if not all(isinstance(v, str) for v in str_fields):
        raise TransferError(_("manifest.json: malformed text field."))
    total = manifest["media_total_bytes"]
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise TransferError(_("manifest.json: media_total_bytes must be an integer."))
    if total > settings.TRANSFER_MAX_UNCOMPRESSED_BYTES:
        raise TransferError(
            _(
                "This export contains %(found)d bytes of media; this instance "
                "accepts at most %(limit)d bytes."
            )
            % {"found": total, "limit": settings.TRANSFER_MAX_UNCOMPRESSED_BYTES}
        )


def read_archive(fileobj, *, expected_kind):
    fileobj.seek(0, os.SEEK_END)
    size = fileobj.tell()
    fileobj.seek(0)
    if size > settings.TRANSFER_MAX_COMPRESSED_BYTES:
        raise TransferError(
            _("The archive is %(found)d bytes; this instance accepts at most "
              "%(limit)d bytes.")
            % {"found": size, "limit": settings.TRANSFER_MAX_COMPRESSED_BYTES}
        )
    try:
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError) as exc:
        raise TransferError(_("The uploaded file is not a valid zip archive.")) from exc

    try:
        infos = [i for i in zf.infolist() if not i.filename.endswith("/")]
        names = [i.filename for i in infos]
        if len(names) != len(set(names)):
            raise TransferError(_("The archive contains duplicate entry names."))
        media_entries = {}
        for info in infos:
            name = info.filename
            if name in ("manifest.json", "course.json"):
                continue
            base = name[len("media/"):] if name.startswith("media/") else None
            if (
                base is None
                or not base
                or "/" in base
                or "\\" in name
                or ".." in name
                or name.startswith("/")
            ):
                raise TransferError(
                    _("The archive contains a disallowed entry: %(name)s.")
                    % {"name": name}
                )
            media_entries[name] = info
        if sum(i.file_size for i in infos) > settings.TRANSFER_MAX_UNCOMPRESSED_BYTES:
            raise TransferError(
                _("The archive's contents are too large (limit %(limit)d bytes).")
                % {"limit": settings.TRANSFER_MAX_UNCOMPRESSED_BYTES}
            )
        try:
            mani_info = zf.getinfo("manifest.json")
        except KeyError:
            raise TransferError(_("The archive has no manifest.json.")) from None
        manifest = parse_json_bytes(
            read_entry_bytes(
                zf, mani_info, settings.TRANSFER_MAX_MANIFEST_BYTES, "manifest.json"
            ),
            "manifest.json",
        )
        _validate_manifest(manifest, expected_kind)
        try:
            doc_info = zf.getinfo("course.json")
        except KeyError:
            raise TransferError(_("The archive has no course.json.")) from None
        document = parse_json_bytes(
            read_entry_bytes(
                zf, doc_info, settings.TRANSFER_MAX_COURSE_JSON_BYTES, "course.json"
            ),
            "course.json",
        )
        return zf, manifest, document, media_entries
    except BaseException:
        zf.close()  # never leak the handle — on Windows it blocks the unlink
        raise


@contextmanager
def open_archive(fileobj, *, expected_kind):
    zf, manifest, document, media_entries = read_archive(
        fileobj, expected_kind=expected_kind
    )
    try:
        yield zf, manifest, document, media_entries
    finally:
        zf.close()
```

- [ ] **Step 4: Run tests to verify they pass** — `uv run pytest tests/test_transfer_archive.py -v` → PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format courses/transfer/importer.py tests/test_transfer_archive.py && uv run ruff check --fix .
git add -A && git commit -m "feat(transfer): hardened archive reader (caps, allowlist, counted reads, manifest schema)"
```

---

### Task 6: Document structural validation

**Files:**
- Modify: `courses/transfer/schema.py` (append)
- Create: `courses/transfer/payloads.py` (stub in this task; Task 7 fills it)
- Test: `tests/test_transfer_validation.py`

**Interfaces:**
- Consumes: `kinds_for_flags`, `ContentNode.RANK`, `is_valid_stored`, `COURSE_LANGUAGES`. (The RANK strictly-deeper check here is deliberately equivalent to `legal_child_kinds` semantics; that helper itself is consumed by Tasks 8 and 12.)
- Produces: `validate_document(doc, *, kind, target_allowed_kinds=None) -> None` (raises TransferError). Covers §5 “Document level” EXCEPT per-type `data` payloads (Task 7 plugs in via `validate_element_data`, called per element from here) and media↔zip correspondence (Task 8 — needs zip entries). Field-check helpers exported for Task 7: `check_str(value, what, *, max_length=None, required=False)`, `check_bool(value, what)`, `check_decimal_str(value, what, max_digits, decimal_places)`, `check_int_or_null(value, what)`, `check_float(value, what)`, `check_list(value, what)`.

Checks implemented here (each with a message naming the offender):
1. Top level: exact keys — course doc: `{course, nodes, elements, media}`; subtree doc: `{context, nodes, elements, media}`; `nodes/elements/media` must be lists.
2. `course` block: exact keys per §2.2; `title` non-blank str ≤200; `language` ∈ `COURSE_LANGUAGES` keys; `overview/html_css/html_js` str; `uses_*` bool; `color_bands` — `[]`/list: empty OK, non-empty must pass `is_valid_stored`; `subjects` list of exact-key `{title_en, title_pl}` str dicts (title_en ≤200 etc.).
3. `context` block: exact keys `{source_course_title, root_kind, required_kinds, html_css, html_js}`; `root_kind` ∈ RANK; `required_kinds` list of strs (informational — NOT trusted).
4. Count caps: `len(nodes) ≤ TRANSFER_MAX_NODES`, elements/media likewise (message names the limit).
5. Node dicts: exact keys `{id, parent, kind, title, unit_type, obligatory, html_seed_js}`; `id` str; `parent` str|null; `kind` ∈ RANK; `title` non-blank ≤200; `obligatory` strict bool; `html_seed_js` str; unit-type rule: kind unit ⇒ `unit_type` ∈ {lesson, quiz}, else `unit_type` is null.
6. Ids unique document-wide (nodes+elements+media share one namespace check).
7. Node parent refs: must reference an EARLIER node in the list; child kind strictly deeper than parent (`RANK`); depth-flag consistency: allowed set = `kinds_for_flags(course uses_*)` for course docs, `target_allowed_kinds` for subtree docs — every node kind ∈ allowed set (message names the offending kind).
8. Subtree shape: exactly one node with `parent: null`, its kind == `context.root_kind`.
9. Element dicts: exact keys `{id, unit, title, type, data}`; `unit` must resolve to an earlier-declared node with kind `unit`; `title` str ≤200; `type` known (unknown → message with the type name); `data` dict → delegated to `validate_element_data(el, media_kinds)` (Task 7; in THIS task wire the call but implement a stub in Task 7’s file position — see Step 3 note).
10. Media dicts: exact keys `{id, kind, name, original_filename, file}`; `kind` ∈ {image, video}; `original_filename` non-blank str ≤255; `file` str starting `media/`; `file` values unique document-wide (bijection half); every media id referenced by ≥1 element (computed AFTER elements pass — collect refs from Task 7 return).

- [ ] **Step 1: Write the failing tests** — representative set + the full §9 hostile list for THIS layer. Use a `make_doc()` helper mirroring Task 5's default document plus a builder for nodes/elements:

```python
# tests/test_transfer_validation.py
import pytest

from courses.transfer.schema import TransferError
from courses.transfer.schema import validate_document


def base_course_doc(**over):
    doc = {
        "course": {
            "title": "T", "language": "en", "overview": "",
            "html_css": "", "html_js": "",
            "uses_parts": True, "uses_chapters": True, "uses_sections": True,
            "color_bands": [], "subjects": [],
        },
        "nodes": [], "elements": [], "media": [],
    }
    doc.update(over)
    return doc


def node(nid, kind="unit", parent=None, **over):
    d = {
        "id": nid, "parent": parent, "kind": kind, "title": "N",
        "unit_type": "lesson" if kind == "unit" else None,
        "obligatory": True, "html_seed_js": "",
    }
    d.update(over)
    return d


def text_el(eid, unit, body="hi"):
    return {"id": eid, "unit": unit, "title": "", "type": "text",
            "data": {"body": body}}


def _reject(doc, needle, kind="course", target_allowed_kinds=None):
    with pytest.raises(TransferError) as exc:
        validate_document(doc, kind=kind, target_allowed_kinds=target_allowed_kinds)
    assert needle.lower() in exc.value.message.lower()


def test_happy_minimal():
    doc = base_course_doc(nodes=[node("n1")], elements=[text_el("e1", "n1")])
    validate_document(doc, kind="course")


def test_unknown_top_key():
    _reject(base_course_doc(extra=1), "extra")


def test_unknown_node_key():
    doc = base_course_doc(nodes=[node("n1", owner="hax")])
    _reject(doc, "owner")


def test_blank_course_title():
    doc = base_course_doc()
    doc["course"]["title"] = "  "
    _reject(doc, "title")


def test_bad_language():
    doc = base_course_doc()
    doc["course"]["language"] = "xx"
    _reject(doc, "language")


def test_nonempty_color_bands_must_validate():
    doc = base_course_doc()
    doc["course"]["color_bands"] = [{"key": "junk"}]
    _reject(doc, "color")
    doc["course"]["color_bands"] = []
    validate_document(doc, kind="course")  # empty is valid


def test_duplicate_ids_reject():
    doc = base_course_doc(nodes=[node("n1"), node("n1", kind="part")])
    _reject(doc, "n1")


def test_dangling_parent_and_forward_parent_reject():
    _reject(base_course_doc(nodes=[node("n1", parent="nope")]), "parent")
    doc = base_course_doc(
        nodes=[node("n1", kind="unit", parent="n2"), node("n2", kind="part")]
    )
    _reject(doc, "parent")  # forward ref: parent must be earlier


def test_illegal_nesting_rejects():
    doc = base_course_doc(
        nodes=[node("n1", kind="unit"), node("n2", kind="part", parent="n1")]
    )
    _reject(doc, "kind")


def test_depth_flags_own_consistency():
    doc = base_course_doc(nodes=[node("n1", kind="part"), ])
    doc["course"]["uses_parts"] = False
    _reject(doc, "part")


def test_nonpreset_flags_accepted():
    doc = base_course_doc(nodes=[node("n1", kind="part"),
                                 node("n2", kind="section", parent="n1"),
                                 node("n3", parent="n2")])
    doc["course"]["uses_chapters"] = False  # (True, False, True) = Custom
    validate_document(doc, kind="course")


def test_subtree_target_flags():
    doc = {
        "context": {"source_course_title": "S", "root_kind": "part",
                    "required_kinds": ["part"], "html_css": "", "html_js": ""},
        "nodes": [node("n1", kind="part")], "elements": [], "media": [],
    }
    _reject(doc, "part", kind="subtree",
            target_allowed_kinds=["chapter", "unit"])  # chapters-only course


def test_subtree_exactly_one_root():
    ctx = {"source_course_title": "S", "root_kind": "unit",
           "required_kinds": ["unit"], "html_css": "", "html_js": ""}
    doc = {"context": ctx, "nodes": [node("n1"), node("n2")],
           "elements": [], "media": []}
    _reject(doc, "root", kind="subtree",
            target_allowed_kinds=["part", "chapter", "section", "unit"])


def test_element_unit_must_be_unit_kind():
    doc = base_course_doc(
        nodes=[node("n1", kind="part")], elements=[text_el("e1", "n1")]
    )
    _reject(doc, "unit")


def test_unknown_element_type_named():
    doc = base_course_doc(
        nodes=[node("n1")],
        elements=[{"id": "e1", "unit": "n1", "title": "", "type": "hologram",
                   "data": {}}],
    )
    _reject(doc, "hologram")


def test_count_caps(settings):
    settings.TRANSFER_MAX_NODES = 1
    doc = base_course_doc(nodes=[node("n1", kind="part"), node("n2", parent="n1")])
    _reject(doc, "node")


def test_obligatory_must_be_bool():
    doc = base_course_doc(nodes=[node("n1", obligatory="yes")])
    _reject(doc, "obligatory")


def test_media_entry_shape_and_uniqueness():
    m = {"id": "m1", "kind": "image", "name": "", "original_filename": "a.png",
         "file": "media/m1.png"}
    doc = base_course_doc(media=[m, {**m, "id": "m2"}])  # same file → reject
    doc["nodes"] = [node("n1")]
    doc["elements"] = [
        {"id": "e1", "unit": "n1", "title": "", "type": "image",
         "data": {"media": "m1", "alt": "", "figcaption": ""}},
        {"id": "e2", "unit": "n1", "title": "", "type": "image",
         "data": {"media": "m2", "alt": "", "figcaption": ""}},
    ]
    _reject(doc, "media/m1.png")


def test_unreferenced_media_item_rejects():
    m = {"id": "m1", "kind": "image", "name": "", "original_filename": "a.png",
         "file": "media/m1.png"}
    doc = base_course_doc(media=[m], nodes=[node("n1")],
                          elements=[text_el("e1", "n1")])
    _reject(doc, "referenced")


def test_bad_media_kind():
    m = {"id": "m1", "kind": "audio", "name": "", "original_filename": "a.mp3",
         "file": "media/m1.mp3"}
    doc = base_course_doc(media=[m])
    _reject(doc, "kind")


def test_unhashable_values_reject_not_500():
    # list/dict where a hashable is expected must reject, never TypeError.
    _reject(base_course_doc(nodes=[node("n1", parent=["x"])]), "parent")
    doc = base_course_doc()
    doc["course"]["language"] = []
    _reject(doc, "language")
    _reject(base_course_doc(nodes=[node("n1", kind=["part"], unit_type=None)]),
            "kind")
    doc3 = base_course_doc(
        nodes=[node("n1")],
        elements=[{"id": "e1", "unit": [], "title": "", "type": "text",
                   "data": {"body": "x"}}],
    )
    _reject(doc3, "unit")
    doc4 = base_course_doc(
        nodes=[node("n1")],
        elements=[{"id": "e1", "unit": "n1", "title": "", "type": ["text"],
                   "data": {"body": "x"}}],
    )
    _reject(doc4, "type")
```

- [ ] **Step 2: Run to verify failure** — ImportError on `validate_document`.

- [ ] **Step 3: Implement (append to `courses/transfer/schema.py`)**

Implementation outline — write it in full, following exactly the check list in this task's Interfaces block. Skeleton with the complete field-check helpers and the traversal (the per-check messages follow the test needles above):

```python
from django.conf import settings
from django.utils.translation import gettext as _

from courses.color_bands import is_valid_stored
from courses.constants import COURSE_LANGUAGES


def _err(msg, **kw):
    raise TransferError(msg % kw if kw else msg)


def check_str(value, what, *, max_length=None, required=False):
    if not isinstance(value, str):
        _err(_("%(what)s must be text."), what=what)
    if required and not value.strip():
        _err(_("%(what)s must not be blank."), what=what)
    if max_length is not None and len(value) > max_length:
        _err(_("%(what)s is longer than %(n)d characters."), what=what, n=max_length)
    return value


def check_bool(value, what):
    if not isinstance(value, bool):
        _err(_("%(what)s must be true or false."), what=what)
    return value


def check_int_or_null(value, what):
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _err(_("%(what)s must be a non-negative integer or null."), what=what)
    return value


def check_decimal_str(value, what, max_digits, decimal_places):
    from decimal import Decimal
    from decimal import InvalidOperation

    if not isinstance(value, str):
        _err(_("%(what)s must be a decimal string."), what=what)
    try:
        d = Decimal(value)
    except InvalidOperation:
        _err(_("%(what)s is not a valid decimal number."), what=what)
    # Finite check MUST precede as_tuple() arithmetic: Decimal("Infinity")
    # has exponent "F" (NaN: "n"), so `-exponent` would TypeError → 500.
    if not d.is_finite():
        _err(_("%(what)s is not a valid decimal number."), what=what)
    exponent = -d.as_tuple().exponent
    digits = len(d.as_tuple().digits)
    if exponent > decimal_places or digits - exponent > max_digits - decimal_places:
        _err(_("%(what)s has too many digits."), what=what)
    return d


def check_float(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _err(_("%(what)s must be a number."), what=what)
    return float(value)


def check_list(value, what):
    if not isinstance(value, list):
        _err(_("%(what)s must be a list."), what=what)
    return value


def _exact_keys(obj, keys, what):
    if not isinstance(obj, dict):
        _err(_("%(what)s must be an object."), what=what)
    for k in keys:
        if k not in obj:
            _err(_("%(what)s is missing the key '%(key)s'."), what=what, key=k)
    for k in obj:
        if k not in keys:
            _err(_("%(what)s contains an unknown key '%(key)s'."), what=what, key=k)


def validate_document(doc, *, kind, target_allowed_kinds=None):
    from courses.models import ContentNode
    from courses.ordering import kinds_for_flags
    from courses.transfer.payloads import validate_element_data  # Task 7

    is_course = kind == KIND_COURSE
    _exact_keys(
        doc,
        (["course"] if is_course else ["context"]) + ["nodes", "elements", "media"],
        "course.json",
    )
    nodes = check_list(doc["nodes"], "nodes")
    elements = check_list(doc["elements"], "elements")
    media = check_list(doc["media"], "media")

    if is_course:
        c = doc["course"]
        _exact_keys(c, [
            "title", "language", "overview", "html_css", "html_js",
            "uses_parts", "uses_chapters", "uses_sections", "color_bands",
            "subjects",
        ], "course")
        check_str(c["title"], _("course title"), max_length=200, required=True)
        # isinstance guards before EVERY dict-membership test: a hostile list/
        # dict value would otherwise raise "unhashable type" → 500.
        if not isinstance(c["language"], str) or c["language"] not in dict(
            COURSE_LANGUAGES
        ):
            _err(_("Unknown course language '%(v)s'."), v=str(c["language"])[:20])
        for f in ("overview", "html_css", "html_js"):
            check_str(c[f], f)
        for f in ("uses_parts", "uses_chapters", "uses_sections"):
            check_bool(c[f], f)
        bands = check_list(c["color_bands"], "color_bands")
        if bands and not is_valid_stored(bands):
            _err(_("color_bands does not match the expected shape."))
        for s in check_list(c["subjects"], "subjects"):
            _exact_keys(s, ["title_en", "title_pl"], "subject")
            check_str(s["title_en"], "title_en", max_length=200)
            check_str(s["title_pl"], "title_pl", max_length=200)
        allowed = kinds_for_flags(
            c["uses_parts"], c["uses_chapters"], c["uses_sections"]
        )
    else:
        ctx = doc["context"]
        _exact_keys(ctx, [
            "source_course_title", "root_kind", "required_kinds",
            "html_css", "html_js",
        ], "context")
        check_str(ctx["source_course_title"], "source_course_title")
        if not isinstance(ctx["root_kind"], str) or (
            ctx["root_kind"] not in ContentNode.RANK
        ):
            _err(_("Unknown root kind '%(v)s'."), v=str(ctx["root_kind"])[:20])
        check_list(ctx["required_kinds"], "required_kinds")  # informational only
        check_str(ctx["html_css"], "html_css")
        check_str(ctx["html_js"], "html_js")
        allowed = list(target_allowed_kinds or [])

    if len(nodes) > settings.TRANSFER_MAX_NODES:
        _err(_("Too many nodes (limit %(n)d)."), n=settings.TRANSFER_MAX_NODES)
    if len(elements) > settings.TRANSFER_MAX_ELEMENTS:
        _err(_("Too many elements (limit %(n)d)."), n=settings.TRANSFER_MAX_ELEMENTS)
    if len(media) > settings.TRANSFER_MAX_MEDIA_ENTRIES:
        _err(_("Too many media entries (limit %(n)d)."),
             n=settings.TRANSFER_MAX_MEDIA_ENTRIES)

    seen_ids = set()

    def _claim_id(v, what):
        check_str(v, what, required=True)
        if v in seen_ids:
            _err(_("Duplicate internal id '%(v)s'."), v=v)
        seen_ids.add(v)

    node_kind = {}
    roots = 0
    for nd in nodes:
        _exact_keys(nd, [
            "id", "parent", "kind", "title", "unit_type", "obligatory",
            "html_seed_js",
        ], _("node"))
        _claim_id(nd["id"], _("node id"))
        if not isinstance(nd["kind"], str) or nd["kind"] not in ContentNode.RANK:
            _err(_("Unknown node kind '%(v)s'."), v=str(nd["kind"])[:20])
        if nd["kind"] not in allowed:
            _err(
                _("The archive contains a '%(kind)s' node, which this structure "
                  "does not allow."),
                kind=nd["kind"],
            )
        check_str(nd["title"], _("node title"), max_length=200, required=True)
        check_bool(nd["obligatory"], "obligatory")
        check_str(nd["html_seed_js"], "html_seed_js")
        if nd["kind"] == "unit":
            if nd["unit_type"] not in ("lesson", "quiz"):
                _err(_("A unit's unit_type must be 'lesson' or 'quiz'."))
        elif nd["unit_type"] is not None:
            _err(_("Only units may have a unit_type."))
        if nd["parent"] is None:
            roots += 1
        else:
            if not isinstance(nd["parent"], str) or nd["parent"] not in node_kind:
                _err(_("Node parent '%(v)s' does not refer to an earlier node."),
                     v=str(nd["parent"])[:50])
            if (
                ContentNode.RANK[node_kind[nd["parent"]]]
                >= ContentNode.RANK[nd["kind"]]
            ):
                _err(_("A node's kind must be strictly deeper than its parent's."))
        node_kind[nd["id"]] = nd["kind"]

    if not is_course:
        if roots != 1:
            _err(_("A subtree archive must contain exactly one root node."))
        if nodes and nodes[0]["parent"] is None:
            if nodes[0]["kind"] != doc["context"]["root_kind"]:
                _err(_("The subtree root does not match the declared root kind."))

    media_kinds = {}
    file_names = set()
    for m in media:
        _exact_keys(m, ["id", "kind", "name", "original_filename", "file"],
                    _("media entry"))
        _claim_id(m["id"], _("media id"))
        if m["kind"] not in ("image", "video"):
            _err(_("Unknown media kind '%(v)s'."), v=str(m["kind"])[:20])
        check_str(m["name"], "name", max_length=255)
        check_str(m["original_filename"], "original_filename",
                  max_length=255, required=True)
        check_str(m["file"], "file", required=True)
        if not m["file"].startswith("media/"):
            _err(_("Media file locator must live under media/."))
        if m["file"] in file_names:
            _err(_("Two media entries share the file %(v)s."), v=m["file"])
        file_names.add(m["file"])
        media_kinds[m["id"]] = m["kind"]

    referenced_media = set()
    for el in elements:
        _exact_keys(el, ["id", "unit", "title", "type", "data"], _("element"))
        _claim_id(el["id"], _("element id"))
        check_str(el["title"], _("element title"), max_length=200)
        if (
            not isinstance(el["unit"], str)
            or el["unit"] not in node_kind
            or node_kind[el["unit"]] != "unit"
        ):
            _err(_("Element '%(v)s' must belong to a unit node."), v=el["id"])
        refs = validate_element_data(el, media_kinds)  # Task 7; returns media ids used
        referenced_media |= refs

    for m in media:
        if m["id"] not in referenced_media:
            _err(_("Media entry '%(v)s' is not referenced by any element."),
                 v=m["id"])
```

Note the import `from courses.transfer.payloads import validate_element_data` — **create `courses/transfer/payloads.py` in this task as a stub** so Task 6 tests can pass with `text`/`image` support only being exercised:

```python
# courses/transfer/payloads.py (Task 6 stub — Task 7 replaces the body)
"""Per-type element `data` validation (§5 per-type invariants). Task 7."""


def validate_element_data(el, media_kinds):
    """Validate el["data"] for el["type"]; return the set of referenced media ids.
    Task 6 stub: unknown types reject; known types minimally accepted."""
    from django.utils.translation import gettext as _

    from courses.transfer.schema import TransferError

    known = {
        "text", "image", "video", "iframe", "math", "html", "choice",
        "short_text", "extended_response", "short_numeric", "fill_blank",
        "drag_fill_blank", "match_pair", "drag_to_image",
    }
    # isinstance guard BEFORE the set lookup: a hostile list/dict type value
    # would otherwise raise "unhashable type" → 500. Same guard stays in front
    # of Task 7's VALIDATORS dict dispatch.
    if not isinstance(el["type"], str) or el["type"] not in known:
        raise TransferError(
            _("Unknown element type '%(v)s' — this archive may come from a newer "
              "application version.") % {"v": str(el["type"])[:40]}
        )
    data = el.get("data")
    if not isinstance(data, dict):
        raise TransferError(_("Element data must be an object."))
    media = data.get("media")
    return {media} if isinstance(media, str) else set()
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_transfer_validation.py tests/test_transfer_schema.py -v` → PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format courses/transfer/ tests/test_transfer_validation.py && uv run ruff check --fix .
git add -A && git commit -m "feat(transfer): structural document validation (ids, nesting, flags, caps, media list)"
```

---

### Task 7: Per-type element payload validation

**Files:**
- Modify: `courses/transfer/payloads.py` (replace stub body)
- Test: `tests/test_transfer_validation.py` (append)

**Interfaces:**
- Consumes: Task 6's check helpers (`check_str`, `check_bool`, `check_decimal_str`, `check_int_or_null`, `check_float`, `check_list`, `_exact_keys` — imported directly from `courses.transfer.schema`); `canonicalize_video_url`, `extract_embed_url`, `validate_embed_url`, `SENTINEL`, `DragZone` (unsaved-instance clean), `Choice`/`DragBlank`/`MatchPair` max lengths (500).
- Produces: `validate_element_data(el, media_kinds) -> set[str]` — full §5 per-type invariants; **mutates** `el["data"]` to store canonicalized embed URLs (video/iframe) so commit persists exactly what was checked.

Per-type rules (each rejection names the element id and the rule):
- Shared question fields: `stem`/`explanation` str; `marking_mode` ∈ {"A","N","R"}; `max_attempts` int≥0-or-null; `max_marks` decimal-str (7,2) ≥ 0.01.
- `text`: `{body: str}`.
- `image`: `{media: id, alt: str≤255, figcaption: str≤255}`; media id must exist with kind `image`.
- `video`: `{url: str|null, media: id|null}` — exactly one non-null; if url: `canonicalize_video_url` (wrap `ValidationError` → TransferError naming the URL) then `validate_embed_url` on the canonical value; write the canonical value back into `data["url"]`; if media: kind must be `video`.
- `iframe`: `{url: str, title: str≤255}`; `extract_embed_url` → write back → `validate_embed_url`.
- `math`: `{latex: str}` (non-blank — model field has no blank=True).
- `html`: `{html: str}` (raw, verbatim).
- `choice`: `multiple` bool; `choices` list of exact-key `{text, is_correct}`; ≥2 choices; each `text` non-blank ≤500; ≥1 correct; exactly one correct when `multiple` is false.
- `short_text`: `accepted` str with ≥1 non-blank line; `case_sensitive` bool.
- `extended_response`: `required_keywords`/`forbidden_keywords` str; when `marking_mode == "A"`: ≥1 non-blank line across the two.
- `short_numeric`: `value` decimal-str (20,8); `tolerance` decimal-str (20,8) ≥ 0.
- `fill_blank`: `blanks` list of exact-key `{accepted, case_sensitive}`, ≥1 row, each `accepted` with ≥1 non-blank line; sentinel-stem check (below).
- `drag_fill_blank`: `distractors` str; `blanks` list of `{correct_token}`, ≥1 row, each token non-blank ≤500; sentinel-stem check.
- `match_pair`: `distractors` str; `pairs` list of `{left, right}`, ≥1 row, both non-blank ≤500.
- `drag_to_image`: media id kind `image`; `alt` ≤255; `distractors` str; `zones` list of `{correct_label, x, y, w, h}`, ≥1 row, label non-blank ≤500; bounds via an unsaved `DragZone(...).clean()` (the exact model mirror incl. `ZONE_COORD_EPSILON`).
- Sentinel-stem check (fill_blank + drag_fill_blank), n = number of blank rows:

```python
import re

from courses.fillblank import SENTINEL

_TOKEN_RE = re.compile(re.escape(SENTINEL) + r"(\d+)" + re.escape(SENTINEL))


def _check_token_stem(stem, n, elid):
    found = [int(m.group(1)) for m in _TOKEN_RE.finditer(stem)]
    if found != list(range(n)):  # exact 0..n-1, each once, ascending appearance
        _err(_("Element '%(v)s': the stem's blank tokens do not match its blank "
               "rows."), v=elid)
    if SENTINEL in _TOKEN_RE.sub("", stem):
        _err(_("Element '%(v)s': the stem contains stray reserved characters."),
             v=elid)
```

(n ≥ 1 is enforced by the ≥1-row rule before this runs, so `found != range(0)` also covers a token-free stem with rows.)

- [ ] **Step 1: Write failing tests** (append to `tests/test_transfer_validation.py`). Cover, at minimum, each named §9 hostile case for this layer — one test per rule, using `base_course_doc` + a per-type element builder:

```python
def q_fields(**over):
    d = {"stem": "s", "explanation": "", "marking_mode": "A",
         "max_attempts": 1, "max_marks": "1.00"}
    d.update(over)
    return d


def el_of(type_key, data, eid="e1", unit="n1"):
    return {"id": eid, "unit": unit, "title": "", "type": type_key, "data": data}


def doc_with(el, media=None):
    return base_course_doc(nodes=[node("n1")], elements=[el], media=media or [])


IMG = {"id": "m1", "kind": "image", "name": "", "original_filename": "a.png",
       "file": "media/m1.png"}
VID = {"id": "m1", "kind": "video", "name": "", "original_filename": "a.mp4",
       "file": "media/m1.mp4"}

# — a representative selection; write ONE test per rule below, same shape —

def test_zero_correct_choice_rejects():
    data = q_fields(multiple=True, choices=[
        {"text": "A", "is_correct": False}, {"text": "B", "is_correct": False}])
    _reject(doc_with(el_of("choice", data)), "correct")


def test_single_choice_needs_exactly_one_correct():
    data = q_fields(multiple=False, choices=[
        {"text": "A", "is_correct": True}, {"text": "B", "is_correct": True}])
    _reject(doc_with(el_of("choice", data)), "exactly one")


def test_choice_needs_two_choices_and_nonempty_text():
    _reject(doc_with(el_of("choice", q_fields(
        multiple=False, choices=[{"text": "A", "is_correct": True}]))), "two")
    _reject(doc_with(el_of("choice", q_fields(multiple=False, choices=[
        {"text": "", "is_correct": True}, {"text": "B", "is_correct": False}]))),
        "text")


def test_keywordless_auto_extended_response_rejects():
    data = q_fields(required_keywords="", forbidden_keywords="")
    _reject(doc_with(el_of("extended_response", data)), "keyword")
    ok = q_fields(required_keywords="k", forbidden_keywords="",
                  marking_mode="A")
    validate_document(doc_with(el_of("extended_response", ok)), kind="course")


def test_sentinel_rules():
    S = "￿"
    blanks = [{"accepted": "a", "case_sensitive": False}]
    def fb(stem, rows=blanks):
        return el_of("fill_blank", q_fields(stem=stem, blanks=rows))
    validate_document(doc_with(fb(f"x {S}0{S} y")), kind="course")  # happy
    _reject(doc_with(fb(f"{S}0{S}{S}0{S}",
                        rows=blanks * 2)), "token")          # duplicate
    _reject(doc_with(fb(f"{S}99{S}")), "token")               # out of range
    _reject(doc_with(fb(f"{S}1{S} {S}0{S}", rows=blanks * 2)), "token")  # order
    _reject(doc_with(fb(f"{S} {S}0{S}")), "reserved")          # stray sentinel
    _reject(doc_with(el_of("fill_blank", q_fields(stem="x", blanks=[]))), "blank")


def test_dragfill_token_and_matchpair_zone_minimums():
    _reject(doc_with(el_of("drag_fill_blank", q_fields(
        stem="￿0￿", distractors="", blanks=[{"correct_token": ""}]))),
        "token")
    _reject(doc_with(el_of("match_pair", q_fields(
        distractors="", pairs=[]))), "pair")
    _reject(doc_with(el_of("drag_to_image", q_fields(
        media="m1", alt="", distractors="", zones=[]), ), media=[IMG]), "zone")


def test_zone_bounds_mirror_model():
    def zone(**over):
        z = {"correct_label": "L", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}
        z.update(over)
        return z
    def d2i(z):
        return doc_with(el_of("drag_to_image", q_fields(
            media="m1", alt="", distractors="", zones=[z])), media=[IMG])
    _reject(d2i(zone(w=0)), "size")           # zero width
    _reject(d2i(zone(x=0.9, w=0.5)), "image")  # overflow
    # boundary noise passes (epsilon-tolerant, mirrors DragZone.clean)
    validate_document(d2i(zone(x=0.5, w=0.5000000000000001)), kind="course")


def test_video_xor_both_set_rejects(settings):
    settings.ALLOWED_EMBED_DOMAINS = ["youtube.com"]
    _reject(
        doc_with(
            el_of("video", {"url": "https://www.youtube.com/embed/x", "media": "m1"}),
            media=[VID],
        ),
        "exactly one",
    )


def test_video_xor_neither_set_rejects():
    _reject(doc_with(el_of("video", {"url": None, "media": None})), "exactly one")


def test_image_element_needs_image_kind_asset():
    _reject(
        doc_with(el_of("image", {"media": "m1", "alt": "", "figcaption": ""}),
                 media=[VID]),
        "image",
    )


def test_watch_url_canonicalized_in_place(settings):
    settings.ALLOWED_EMBED_DOMAINS = ["youtube.com"]
    d = doc_with(
        el_of("video", {"url": "https://www.youtube.com/watch?v=abc12345678",
                        "media": None})
    )
    validate_document(d, kind="course")
    assert "/embed/" in d["elements"][0]["data"]["url"]


def test_disallowed_embed_domain_named(settings):
    settings.ALLOWED_EMBED_DOMAINS = ["vimeo.com"]
    _reject(
        doc_with(el_of("video", {"url": "https://www.youtube.com/embed/x",
                                 "media": None})),
        "youtube.com",
    )


def test_unhashable_media_ref_rejects_not_500():
    _reject(
        doc_with(el_of("image", {"media": [1], "alt": "", "figcaption": ""}),
                 media=[IMG]),
        "media",
    )


def test_malformed_decimal_and_wrong_type_reject():
    _reject(doc_with(el_of("short_numeric", q_fields(value="abc",
        tolerance="0"))), "decimal")
    _reject(doc_with(el_of("text", {"body": 42})), "text")


def test_nonfinite_decimal_strings_reject_not_500():
    for bad in ("Infinity", "-Infinity", "NaN"):
        _reject(doc_with(el_of("short_numeric",
                               q_fields(value=bad, tolerance="0"))), "decimal")


def test_unknown_data_key_rejects():
    _reject(doc_with(el_of("text", {"body": "x", "omitted": True})), "omitted")
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `courses/transfer/payloads.py`** in full: a dispatch table `VALIDATORS = {"text": _val_text, …}` (14 entries), each validator `fn(data, elid, media_kinds) -> set[str]` doing exact-keys + field checks + semantic rules from the Interfaces list, with `validate_element_data(el, media_kinds)` doing the unknown-type rejection (naming the type), delegating, and returning the referenced-media set. The remaining 11 validators follow the same shape as these three, written out here as the pattern:

```python
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from courses.embed import extract_embed_url
from courses.models import DragZone
from courses.transfer.schema import TransferError
from courses.transfer.schema import _exact_keys
from courses.transfer.schema import check_bool
from courses.transfer.schema import check_decimal_str
from courses.transfer.schema import check_int_or_null
from courses.transfer.schema import check_list
from courses.transfer.schema import check_float
from courses.transfer.schema import check_str
from courses.validators import validate_embed_url
from courses.video_url import canonicalize_video_url


def _err(msg, **kw):
    raise TransferError(msg % kw if kw else msg)


def _lines(blob):
    return [ln for ln in (blob or "").splitlines() if ln.strip()]


def _canonical_embed(raw, elid, canonicalizer):
    try:
        url = canonicalizer(raw)
        validate_embed_url(url)
        return url
    except ValidationError:
        _err(_("Element '%(el)s': the embed URL '%(url)s' is not accepted on this "
               "instance."), el=elid, url=str(raw)[:200])


def _check_question_fields(data, elid):
    check_str(data["stem"], _("stem"))
    check_str(data["explanation"], _("explanation"))
    if data["marking_mode"] not in ("A", "N", "R"):
        _err(_("Element '%(el)s': unknown marking mode."), el=elid)
    check_int_or_null(data["max_attempts"], "max_attempts")
    d = check_decimal_str(data["max_marks"], "max_marks", 7, 2)
    from decimal import Decimal

    if d < Decimal("0.01"):
        _err(_("Element '%(el)s': max_marks must be at least 0.01."), el=elid)


Q_KEYS = ["stem", "explanation", "marking_mode", "max_attempts", "max_marks"]


def _require_media(data_media, elid, media_kinds, want_kind):
    if not isinstance(data_media, str) or data_media not in media_kinds:
        _err(_("Element '%(el)s' references an unknown media id."), el=elid)
    if media_kinds[data_media] != want_kind:
        _err(_("Element '%(el)s' requires %(kind)s media."), el=elid, kind=want_kind)
    return {data_media}


# --- example validators (pattern for all 14) ---------------------------------

def _val_video(data, elid, media_kinds):
    _exact_keys(data, ["url", "media"], _("video data"))
    has_url = data["url"] is not None
    has_media = data["media"] is not None
    if has_url == has_media:
        _err(_("Element '%(el)s': provide exactly one of url or media."), el=elid)
    if has_url:
        check_str(data["url"], "url", required=True)
        data["url"] = _canonical_embed(data["url"], elid, canonicalize_video_url)
        return set()
    return _require_media(data["media"], elid, media_kinds, "video")


def _val_choice(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["multiple", "choices"], _("choice data"))
    _check_question_fields(data, elid)
    check_bool(data["multiple"], "multiple")
    choices = check_list(data["choices"], "choices")
    if len(choices) < 2:
        _err(_("Element '%(el)s': a choice question needs at least two choices."),
             el=elid)
    n_correct = 0
    for c in choices:
        _exact_keys(c, ["text", "is_correct"], _("choice"))
        check_str(c["text"], _("choice text"), max_length=500, required=True)
        check_bool(c["is_correct"], "is_correct")
        n_correct += c["is_correct"]
    if n_correct < 1:
        _err(_("Element '%(el)s': at least one choice must be correct."), el=elid)
    if not data["multiple"] and n_correct != 1:
        _err(_("Element '%(el)s': a single-choice question needs exactly one "
               "correct choice."), el=elid)
    return set()


def _val_drag_to_image(data, elid, media_kinds):
    _exact_keys(data, Q_KEYS + ["media", "alt", "distractors", "zones"],
                _("drag-to-image data"))
    _check_question_fields(data, elid)
    refs = _require_media(data["media"], elid, media_kinds, "image")
    check_str(data["alt"], "alt", max_length=255)
    check_str(data["distractors"], "distractors")
    zones = check_list(data["zones"], "zones")
    if not zones:
        _err(_("Element '%(el)s': at least one zone is required."), el=elid)
    for z in zones:
        _exact_keys(z, ["correct_label", "x", "y", "w", "h"], _("zone"))
        check_str(z["correct_label"], _("zone label"), max_length=500, required=True)
        probe = DragZone(
            correct_label=z["correct_label"],
            x=check_float(z["x"], "x"), y=check_float(z["y"], "y"),
            w=check_float(z["w"], "w"), h=check_float(z["h"], "h"),
        )
        try:
            probe.clean()  # the exact model mirror incl. ZONE_COORD_EPSILON
        except ValidationError as exc:
            _err(_("Element '%(el)s': %(detail)s"), el=elid,
                 detail="; ".join(exc.messages))
    return refs
```

- [ ] **Step 4: Run** `uv run pytest tests/test_transfer_validation.py -v` → PASS.
- [ ] **Step 5: Format, lint, commit** — `git commit -m "feat(transfer): per-type payload validation mirroring builder invariants"`.

---

### Task 8: Media↔zip correspondence, media file validation, preview builder

**Files:**
- Modify: `courses/transfer/importer.py` (append)
- Test: `tests/test_transfer_media.py`

**Interfaces:**
- Consumes: Tasks 5–7; `effective_image_extensions()`, `effective_video_extensions()`, `effective_max_image_bytes()`, `effective_max_video_bytes()`, `truncate_filename`; `Subject`; `legal_child_kinds`.
- Produces:
  - `validate_media_entries(document, media_entries) -> None` — bijection: every `media[].file` names an existing zip entry (reject naming id+path); zip `media/*` entries absent from the list reject; per-file: extension checked against `truncate_filename(original_filename)` via `FileExtensionValidator(allowed_extensions=effective_*_extensions())`, size = `info.file_size` vs `effective_max_*_bytes()` — message names the file and rule.
  - `validate_archive_document(zf, manifest, document, media_entries, *, kind, target_course=None) -> None` — one entry point chaining `validate_document` (+ `target_allowed_kinds=target_course.allowed_kinds` for subtrees) and `validate_media_entries`. This is what views call at preview AND confirm (§4.2 re-validation).
  - `match_subjects(subject_dicts) -> (matched: list[Subject], dropped: list[dict])` — language-aligned iexact (leg participates only when the exported title is non-empty — `Q(title_en__iexact=…)` never matches an empty target); multi-match → `.order_by("title_en", "pk").first()`.
  - `build_preview(manifest, document, media_entries, *, target_course=None) -> dict` — keys: `title`, `kind`, `node_count`, `element_count`, `media_count`, `media_total_bytes` (sum of entry sizes), `source` (manifest source dict), `subjects_matched` (titles), `subjects_dropped` (title_en list), `has_html_elements` (bool), `context_css_js` (subtree + has_html only: `{"html_css":…, "html_js":…}` else None), `insertion_choices` (subtree only: list of `{"value": pk-or-"" , "label": …}`).
  - `insertion_choices(target_course, root_kind) -> list[dict]` — `""`/top-level first when `root_kind in legal_child_kinds(None, course.allowed_kinds)`; then every non-unit node (tree order, labels indented `"P1 › C1"` style: join ancestor titles with `" › "`) where `root_kind in legal_child_kinds(node.kind, course.allowed_kinds)`. Empty list ⇒ the preview shows the §4.1 incompatibility rejection instead.

- [ ] **Step 1: Failing tests** — `tests/test_transfer_media.py`: reuse Task 5's `make_zip`/`make_manifest` (import from `tests.test_transfer_archive`). Cases: missing entry (media item points nowhere) names id+path; extra `media/*` entry rejects; wrong-extension media (e.g. `.exe` declared image) names file; oversized media: monkeypatch `courses.transfer.importer.effective_max_image_bytes` (the name as imported into importer.py) to return 10, then assert a >10-byte image entry rejects naming the file; subject matching: exact-ci match on either language; blank-PL never cross-matches; tie-break by (title_en, pk); preview counts + subjects report; insertion choices for a chapters-only target (root chapter → top level only; root part → empty).

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** (append to importer.py):

```python
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Q

from courses.media import truncate_filename
from courses.models import Subject
from courses.ordering import legal_child_kinds
from courses.transfer.schema import validate_document
from courses.validators import effective_image_extensions
from courses.validators import effective_max_image_bytes
from courses.validators import effective_max_video_bytes
from courses.validators import effective_video_extensions


def validate_media_entries(document, media_entries):
    listed = {}
    for m in document["media"]:
        if m["file"] not in media_entries:
            raise TransferError(
                _("Media entry '%(id)s' points at a missing archive file "
                  "%(path)s.") % {"id": m["id"], "path": m["file"]}
            )
        listed[m["file"]] = m
    for name in media_entries:
        if name not in listed:
            raise TransferError(
                _("The archive contains an unlisted media file %(path)s.")
                % {"path": name}
            )
    for name, m in listed.items():
        info = media_entries[name]
        fname = truncate_filename(m["original_filename"])
        if m["kind"] == "image":
            exts, max_bytes = effective_image_extensions(), effective_max_image_bytes()
        else:
            exts, max_bytes = effective_video_extensions(), effective_max_video_bytes()

        holder = type("_Named", (), {"name": fname})()  # validator reads .name
        try:
            FileExtensionValidator(allowed_extensions=list(exts))(holder)
        except ValidationError:
            raise TransferError(
                _("Media file %(name)s has a file type this instance does not "
                  "accept.") % {"name": fname}
            ) from None
        if info.file_size > max_bytes:
            raise TransferError(
                _("Media file %(name)s is larger than the allowed %(limit)d "
                  "bytes.") % {"name": fname, "limit": max_bytes}
            )


def validate_archive_document(zf, manifest, document, media_entries, *, kind,
                              target_course=None):
    target_allowed = target_course.allowed_kinds if target_course else None
    validate_document(document, kind=kind, target_allowed_kinds=target_allowed)
    validate_media_entries(document, media_entries)


def match_subjects(subject_dicts):
    matched, dropped = [], []
    for s in subject_dicts:
        q = Q()
        if s["title_en"].strip():
            q |= Q(title_en__iexact=s["title_en"].strip())
        if s["title_pl"].strip():
            q |= Q(title_pl__iexact=s["title_pl"].strip())
        subj = (
            Subject.objects.filter(q).order_by("title_en", "pk").first()
            if q else None
        )
        if subj is not None:
            matched.append(subj)
        else:
            dropped.append(s)
    return matched, dropped


def insertion_choices(target_course, root_kind):
    allowed = target_course.allowed_kinds
    choices = []
    if root_kind in legal_child_kinds(None, allowed):
        choices.append({"value": "", "label": _("Top level")})
    cmap = {}
    for n in target_course.nodes.all().order_by("order", "pk"):
        cmap.setdefault(n.parent_id, []).append(n)

    def walk(pid, trail):
        for n in cmap.get(pid, []):
            label = " › ".join(trail + [n.title])
            if n.kind != "unit" and root_kind in legal_child_kinds(n.kind, allowed):
                choices.append({"value": str(n.pk), "label": label})
            walk(n.pk, trail + [n.title])

    walk(None, [])
    return choices


def build_preview(manifest, document, media_entries, *, target_course=None):
    doc = document
    is_course = manifest["kind"] == KIND_COURSE
    preview = {
        "kind": manifest["kind"],
        "title": manifest["course"]["title"] if is_course
        else manifest["node"]["title"],
        "source": manifest["source"],
        "node_count": len(doc["nodes"]),
        "element_count": len(doc["elements"]),
        "media_count": len(doc["media"]),
        "media_total_bytes": sum(i.file_size for i in media_entries.values()),
        "has_html_elements": any(e["type"] == "html" for e in doc["elements"]),
        "subjects_matched": [],
        "subjects_dropped": [],
        "context_css_js": None,
        "insertion_choices": None,
    }
    if is_course:
        matched, dropped = match_subjects(doc["course"]["subjects"])
        preview["subjects_matched"] = [s.title for s in matched]
        preview["subjects_dropped"] = [
            s["title_en"] or s["title_pl"] for s in dropped
        ]
    else:
        ctx = doc["context"]
        if preview["has_html_elements"] and (ctx["html_css"] or ctx["html_js"]):
            preview["context_css_js"] = {
                "html_css": ctx["html_css"], "html_js": ctx["html_js"]
            }
        preview["insertion_choices"] = insertion_choices(
            target_course, doc["nodes"][0]["kind"]
        )
    return preview
```

- [ ] **Step 4: Run** `uv run pytest tests/test_transfer_media.py -v` → PASS.
- [ ] **Step 5: Format, lint, commit** — `git commit -m "feat(transfer): media correspondence + file validation, subject matching, preview builder"`.

---

### Task 9: Import commit — full course

**Files:**
- Modify: `courses/transfer/importer.py` (append)
- Test: `tests/test_transfer_import.py`

**Interfaces:**
- Consumes: everything above; `unique_course_slug`, `create_asset`, `ContentType`.
- Produces:
  - `import_course(zf, manifest, document, media_entries, user) -> Course` — assumes `validate_archive_document` already ran on this exact data (views guarantee it at confirm). One `transaction.atomic()` block; on ANY exception: best-effort delete media files already written to storage, then re-raise (`ValidationError` → `TransferError` naming the element/row; `IntegrityError` → generic `TransferError`; `TransferError` passes through).
  - Internals reused by Task 10: `_create_media(zf, document, media_entries, course, user, created_files) -> dict[mid, MediaAsset]` (extract via `extract_entry_to_tempfile`, wrap `django.core.files.File(spool, name=truncate_filename(original_filename))`, `create_asset(course, kind, file, user, name=m["name"])`; append `asset.file.name` to the caller-owned `created_files` list); `_create_nodes(document, course, root_parent=None) -> dict[nid, ContentNode]` (in sequence; `full_clean(exclude=["order"])` then `save()`); `_create_elements(document, node_map, asset_map)` (dispatch table `BUILDERS` mirroring Task 2's keys: build concrete instance from `data` — `Decimal(data["max_marks"])` etc. — `full_clean(exclude=["order"])`, save, create child rows each `full_clean(exclude=["order"])`+save, then `Element(unit=…, title=…, content_object=concrete)` `full_clean(exclude=["order"])`+save).
  - Course row: `title/language/overview/html_css/html_js/uses_*/color_bands` from doc; `slug=unique_course_slug(title)`; `owner=user`; `visibility`/`external_id`/cohorts left at defaults (§2.4). `full_clean()` then save; subjects via `match_subjects` → `course.subjects.set(matched)`.

- [ ] **Step 1: Failing tests** — the §9 round-trip battery. Add a module-level autouse fixture `settings.MEDIA_ROOT = tmp_path` (same shape as Task 12's staging fixture; also add it to `tests/test_transfer_subtree.py` and any Task 12 view test importing a media-bearing zip) — the import path writes through `default_storage`, and without the redirect tests would pollute the repo's real `media/` dir and the orphan-file assertions would scan pre-existing files. Build a source course exercising ALL 14 types (reuse Task 2 fixtures style, BUT every question must also be **import-valid** per Task 7's validators: choice needs ≥2 choices with exactly one correct when single; short-text ≥1 accepted line; auto-marked extended-response ≥1 keyword line; fill-blank/drag-fill ≥1 blank row with the matching `￿0￿` stem token; match-pair ≥1 full pair; drag-to-image ≥1 zone — Task 2's bare `objects.create(stem="s")` fixtures serialize fine but would fail import validation). Give the course `visibility="open"`, an `external_id`, a subject, non-default `color_bands`, media on image/video/drag-to-image, a boundary zone `x=0.5, w=0.5000000000000001`, a `watch?v=`-free canonical URL video and an iframe. Export with `write_archive`, then:

```python
def _import_zip(buf, user, expected_kind="course", target_course=None):
    from courses.transfer.importer import (import_course, open_archive,
                                           validate_archive_document)
    with open_archive(buf, expected_kind=expected_kind) as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind=expected_kind,
                                  target_course=target_course)
        return import_course(zf, mani, doc, media, user)
```

Assertions:
- new course: `slug == "src-2"` (source exists in same DB → suffix), `owner == importer`, `visibility == "assigned"`, `external_id == ""`, no cohorts; subject attached when a same-name Subject exists.
- graph equality: walk source vs imported in canonical `(order, pk)` traversal; compare node kinds/titles/unit_types/obligatory/html_seed_js; element types/titles in sequence; per-type data via re-serialization: `serialize_element_data` on both sides must be equal after mapping media ids (byte-compare `MediaAsset.file.read()`; compare `original_filename`).
- `color_bands=[]` course round-trips; sanitizer re-entry: hand-craft a doc (Task 6 helpers) with `<script>` in a text body → imported body has it stripped (`"<script" not in body`); `watch?v=` video URL → stored canonical; ValidationError backstop (the §4.2 change-between-validate-and-commit scenario): validate a doc containing a video URL while its domain is in `ALLOWED_EMBED_DOMAINS`, then remove the domain from settings and call `import_course` → `TransferError` (not a 500), transaction rolled back (no Course rows), no orphan media files left under `MEDIA_ROOT`.
- orphan cleanup: force a failure AFTER media creation (same scenario) → `MediaAsset.objects.count() == 0` AND no files under `MEDIA_ROOT/courses/media/`.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** (append to importer.py) — full code:

```python
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import IntegrityError
from django.db import transaction

from courses.forms import unique_course_slug
from courses.media import create_asset
from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from courses.models import VideoElement


def _q_kwargs(data):
    return {
        "stem": data["stem"],
        "explanation": data["explanation"],
        "marking_mode": data["marking_mode"],
        "max_attempts": data["max_attempts"],
        "max_marks": Decimal(data["max_marks"]),
    }


def _clean_save(obj):
    obj.full_clean(exclude=["order"] if hasattr(obj, "order") else None)
    obj.save()
    return obj


def _build_text(data, assets):
    return _clean_save(TextElement(body=data["body"])), ()


def _build_image(data, assets):
    el = ImageElement(
        media=assets[data["media"]], alt=data["alt"], figcaption=data["figcaption"]
    )
    return _clean_save(el), ()


def _build_video(data, assets):
    el = VideoElement(
        url=data["url"] or "",
        media=assets[data["media"]] if data["media"] else None,
    )
    return _clean_save(el), ()


def _build_iframe(data, assets):
    return _clean_save(IframeElement(url=data["url"], title=data["title"])), ()


def _build_math(data, assets):
    return _clean_save(MathElement(latex=data["latex"])), ()


def _build_html(data, assets):
    return _clean_save(HtmlElement(html=data["html"])), ()


def _build_choice(data, assets):
    q = _clean_save(ChoiceQuestionElement(**_q_kwargs(data),
                                          multiple=data["multiple"]))
    rows = [
        Choice(question=q, text=c["text"], is_correct=c["is_correct"])
        for c in data["choices"]
    ]
    return q, rows


def _build_short_text(data, assets):
    q = ShortTextQuestionElement(
        **_q_kwargs(data),
        accepted=data["accepted"],
        case_sensitive=data["case_sensitive"],
    )
    return _clean_save(q), ()


def _build_extended(data, assets):
    q = ExtendedResponseQuestionElement(
        **_q_kwargs(data),
        required_keywords=data["required_keywords"],
        forbidden_keywords=data["forbidden_keywords"],
    )
    return _clean_save(q), ()


def _build_numeric(data, assets):
    q = ShortNumericQuestionElement(
        **_q_kwargs(data),
        value=Decimal(data["value"]),
        tolerance=Decimal(data["tolerance"]),
    )
    return _clean_save(q), ()


def _build_fill_blank(data, assets):
    q = _clean_save(FillBlankQuestionElement(**_q_kwargs(data)))
    rows = [
        Blank(question=q, accepted=b["accepted"],
              case_sensitive=b["case_sensitive"])
        for b in data["blanks"]
    ]
    return q, rows


def _build_drag_fill(data, assets):
    q = _clean_save(DragFillBlankQuestionElement(
        **_q_kwargs(data), distractors=data["distractors"]))
    rows = [DragBlank(question=q, correct_token=b["correct_token"])
            for b in data["blanks"]]
    return q, rows


def _build_match_pair(data, assets):
    q = _clean_save(MatchPairQuestionElement(
        **_q_kwargs(data), distractors=data["distractors"]))
    rows = [MatchPair(question=q, left=p["left"], right=p["right"])
            for p in data["pairs"]]
    return q, rows


def _build_drag_to_image(data, assets):
    q = _clean_save(DragToImageQuestionElement(
        **_q_kwargs(data), media=assets[data["media"]], alt=data["alt"],
        distractors=data["distractors"]))
    rows = [
        DragZone(question=q, correct_label=z["correct_label"],
                 x=z["x"], y=z["y"], w=z["w"], h=z["h"])
        for z in data["zones"]
    ]
    return q, rows


BUILDERS = {
    "text": _build_text,
    "image": _build_image,
    "video": _build_video,
    "iframe": _build_iframe,
    "math": _build_math,
    "html": _build_html,
    "choice": _build_choice,
    "short_text": _build_short_text,
    "extended_response": _build_extended,
    "short_numeric": _build_numeric,
    "fill_blank": _build_fill_blank,
    "drag_fill_blank": _build_drag_fill,
    "match_pair": _build_match_pair,
    "drag_to_image": _build_drag_to_image,
}


def _create_media(zf, document, media_entries, course, user, created_files):
    from courses.media import truncate_filename

    assets = {}
    for m in document["media"]:
        info = media_entries[m["file"]]
        spool = extract_entry_to_tempfile(zf, info)
        try:
            wrapped = File(spool, name=truncate_filename(m["original_filename"]))
            asset = create_asset(course, m["kind"], wrapped, user, name=m["name"])
        finally:
            spool.close()  # up to 1000 entries — don't accumulate open handles
        created_files.append(asset.file.name)
        assets[m["id"]] = asset
    return assets


def _create_nodes(document, course, root_parent=None):
    node_map = {}
    for nd in document["nodes"]:
        parent = node_map[nd["parent"]] if nd["parent"] else root_parent
        node = ContentNode(
            course=course, parent=parent, kind=nd["kind"], title=nd["title"],
            unit_type=nd["unit_type"], obligatory=nd["obligatory"],
            html_seed_js=nd["html_seed_js"],
        )
        node.full_clean(exclude=["order"])
        node.save()
        node_map[nd["id"]] = node
    return node_map


def _create_elements(document, node_map, assets):
    for el in document["elements"]:
        concrete, child_rows = BUILDERS[el["type"]](el["data"], assets)
        for row in child_rows:
            row.full_clean(exclude=["order"])
            row.save()
        join = Element(
            unit=node_map[el["unit"]], title=el["title"], content_object=concrete
        )
        join.full_clean(exclude=["order"])
        join.save()


def _cleanup_files(created_files):
    from django.core.files.storage import default_storage

    for name in created_files:
        try:
            default_storage.delete(name)
        except OSError:  # best-effort (§4.4)
            pass


def _run_import(work, created_files):
    """Shared commit wrapper: transaction + error mapping + orphan cleanup."""
    try:
        with transaction.atomic():
            return work()
    except TransferError:
        _cleanup_files(created_files)
        raise
    except ValidationError as exc:
        _cleanup_files(created_files)
        detail = "; ".join(exc.messages)[:300] if hasattr(exc, "messages") else ""
        raise TransferError(
            _("The archive's content failed validation on this instance: "
              "%(detail)s") % {"detail": detail}
        ) from exc
    except IntegrityError as exc:
        _cleanup_files(created_files)
        raise TransferError(
            _("The import could not be completed due to a concurrent change — "
              "please try again.")
        ) from exc
    except Exception:
        _cleanup_files(created_files)
        raise


def import_course(zf, manifest, document, media_entries, user):
    created_files = []

    def work():
        c = document["course"]
        course = Course(
            title=c["title"],
            slug=unique_course_slug(c["title"]),
            language=c["language"],
            overview=c["overview"],
            html_css=c["html_css"],
            html_js=c["html_js"],
            uses_parts=c["uses_parts"],
            uses_chapters=c["uses_chapters"],
            uses_sections=c["uses_sections"],
            color_bands=c["color_bands"],
            owner=user,
        )
        course.full_clean()
        course.save()
        matched, _dropped = match_subjects(c["subjects"])
        course.subjects.set(matched)
        assets = _create_media(zf, document, media_entries, course, user,
                               created_files)
        node_map = _create_nodes(document, course)
        _create_elements(document, node_map, assets)
        return course

    return _run_import(work, created_files)
```

- [ ] **Step 4: Run** `uv run pytest tests/test_transfer_import.py tests/test_transfer_export.py -v` → PASS.
- [ ] **Step 5: Format, lint, commit** — `git commit -m "feat(transfer): transactional full-course import with full_clean rows and orphan cleanup"`.

---

### Task 10: Import commit — subtree

**Files:**
- Modify: `courses/transfer/importer.py` (append)
- Test: `tests/test_transfer_subtree.py`

**Interfaces:**
- Consumes: Task 9 internals (`_create_media`, `_create_nodes`, `_create_elements`, `_run_import`).
- Produces: `import_subtree(zf, manifest, document, media_entries, target_course, insertion_node, user) -> ContentNode` — `insertion_node` is a `ContentNode` of `target_course` or `None` (top level; the VIEW does the scoped lookup and kind-legality re-check before calling). MediaAssets land in the target course's library, `uploaded_by=user`. Root node's parent = insertion point; OrderField appends at the end of siblings automatically.

```python
def import_subtree(zf, manifest, document, media_entries, target_course,
                   insertion_node, user):
    created_files = []

    def work():
        assets = _create_media(zf, document, media_entries, target_course, user,
                               created_files)
        node_map = _create_nodes(document, target_course,
                                 root_parent=insertion_node)
        _create_elements(document, node_map, assets)
        return node_map[document["nodes"][0]["id"]]

    return _run_import(work, created_files)
```

- [ ] **Step 1: Failing tests** — subtree round-trip: export a chapter (with a unit containing a couple of element types incl. an image) from course A; import into course B under a part / at top level; assert: root grafted under the chosen parent, appended AFTER existing siblings (order); descendants + elements + child rows equal by re-serialization; media asset created in B's library with `uploaded_by=importer`; target html_css untouched (§2.2 — context CSS/JS never applied); depth-flag rejection: chapters-only target + part-rooted archive → `validate_archive_document(..., target_course=…)` raises naming "part".
- [ ] **Step 2: Run to verify failure.** — ImportError.
- [ ] **Step 3: Implement** (code above).
- [ ] **Step 4: Run** `uv run pytest tests/test_transfer_subtree.py -v` → PASS.
- [ ] **Step 5: Format, lint, commit** — `git commit -m "feat(transfer): subtree import grafting into an existing course"`.

---

### Task 11: Staging module

**Files:**
- Create: `courses/transfer/staging.py`
- Test: `tests/test_transfer_staging.py`

**Interfaces:**
- Consumes: `settings.TRANSFER_STAGING_DIR`, `TRANSFER_STAGING_MAX_AGE_HOURS`.
- Produces:
  - `SLOT_COURSE = "course"`, `SLOT_SUBTREE = "subtree"`; session key `"transfer_staging"` → `{slot: {"token": str, "path": str, "course_pk": int|None}}`.
  - `stage(session, slot, uploaded_file, course_pk=None) -> (token: str, path: Path)` — sweeps stale files first (best-effort per file, mtime-based); deletes+supersedes the slot's previous staged file; writes to `TRANSFER_STAGING_DIR/<token>.zip` (`secrets.token_urlsafe(32)`); records slot in session (`session.modified = True`); returns the token AND the staged path as one atomic pair (the view must not re-read the path from the session — a concurrent second-tab stage could pair the old token with the new file).
  - `claim(session, slot, token, course_pk=None) -> Path | None` — None unless the slot exists, tokens match, and (subtree) `course_pk` matches; atomic `os.rename` to `<token>.claimed.zip` (rename failure → None: another confirm won); `os.utime` bump; clears the slot from the session. Caller deletes the claimed file when done (`finally`).
  - `discard(session, slot, token) -> None` — cancel: no-op unless `token` matches the slot's current token (a stale tab's Cancel must not delete a newer upload); on match delete the staged file and clear the slot.
  - `sweep() -> None` — delete files under the staging dir older than the max age (both `.zip` and `.claimed.zip`); every unlink in try/except OSError.

Full implementation:

```python
"""Staging between import preview and confirm (§4.3). Session-token slots; the
staging dir is NOT web-served and shared across hosts in multi-host deployments."""

import os
import secrets
import time
from pathlib import Path

from django.conf import settings

SESSION_KEY = "transfer_staging"
SLOT_COURSE = "course"
SLOT_SUBTREE = "subtree"


def _dir():
    p = Path(settings.TRANSFER_STAGING_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sweep():
    cutoff = time.time() - settings.TRANSFER_STAGING_MAX_AGE_HOURS * 3600
    try:
        entries = list(_dir().iterdir())
    except OSError:
        return
    for f in entries:
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            continue  # best-effort per file; never propagate (§4.3)


def _slots(session):
    return session.get(SESSION_KEY, {})


def stage(session, slot, uploaded_file, course_pk=None):
    sweep()
    slots = _slots(session)
    old = slots.get(slot)
    if old:  # supersede: previous upload's file + token die now
        try:
            os.unlink(old["path"])
        except OSError:
            pass
    token = secrets.token_urlsafe(32)
    path = _dir() / f"{token}.zip"
    with open(path, "wb") as out:
        for chunk in uploaded_file.chunks():
            out.write(chunk)
    slots[slot] = {"token": token, "path": str(path), "course_pk": course_pk}
    session[SESSION_KEY] = slots
    session.modified = True
    return token, path


def claim(session, slot, token, course_pk=None):
    slots = _slots(session)
    entry = slots.get(slot)
    if not entry or not token or entry["token"] != token:
        return None
    if entry.get("course_pk") != course_pk:
        return None
    src = Path(entry["path"])
    dst = src.with_suffix(".claimed.zip")
    slots.pop(slot, None)
    session[SESSION_KEY] = slots
    session.modified = True
    try:
        os.rename(src, dst)  # atomic claim: exactly one confirm wins
        os.utime(dst, None)  # fresh sweep window for the in-flight import
    except OSError:
        return None
    return dst


def discard(session, slot, token):
    slots = _slots(session)
    entry = slots.get(slot)
    if not entry or not token or entry["token"] != token:
        return  # stale tab's Cancel must not delete a newer upload
    slots.pop(slot, None)
    session[SESSION_KEY] = slots
    session.modified = True
    try:
        os.unlink(entry["path"])
    except OSError:
        pass
```

- [ ] **Step 1: Failing tests** — use a plain dict-like session (`django.contrib.sessions.backends.db.SessionStore()` or a `dict` subclass with `.modified`); `settings.TRANSFER_STAGING_DIR = tmp_path`. Cases: stage→claim returns the claimed path and clears the slot; second claim with same token → None; wrong token → None; subtree course_pk mismatch → None; supersede deletes the previous file; discard with the matching token deletes, with a stale/wrong token is a no-op (newer upload survives); sweep removes only old-mtime files (set `os.utime(f, (old, old))`), skips fresh, tolerates a locked/missing file; claimed file has fresh mtime.
- [ ] **Step 2–5:** fail → implement (above) → `uv run pytest tests/test_transfer_staging.py -v` PASS → format/lint → `git commit -m "feat(transfer): session-slot staging with atomic claim and mtime sweep"`.

---

### Task 12: Import views, templates, URLs, EN/PL i18n

**Files:**
- Modify: `courses/views_transfer.py` (import half), `courses/urls.py`
- Create: `templates/courses/manage/import_course.html`, `templates/courses/manage/import_preview.html`
- Modify: manage course-list template (Import course button — wrap in `{% if perms.courses.add_course %}`; no dead links for users who can't import) and builder template (Import content action — page already edit-gated, no extra conditional)
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compile)
- Test: `tests/test_transfer_views.py` (append)

**Interfaces:**
- Consumes: Tasks 5–11.
- Produces URL names (all under the `courses` namespace):
  - `manage_course_import` — GET upload form / POST file → validate → preview page; `manage_course_import_confirm` — POST token; `manage_course_import_cancel` — POST token.
  - `manage_import_content` (`manage/courses/<slug:slug>/import-content/`) + `…_confirm` + `…_cancel`.
- View logic (shared helper `_preview_or_error(request, slot, expected_kind, target_course)`):
  1. Upload POST: file present? (`request.FILES.get("archive")`) → `staging.stage(request.session, slot, file, course_pk)`; open the staged path, `open_archive` + `validate_archive_document` + `build_preview`; on `TransferError`: `staging.discard`, re-render the upload form with the message (safe, autoescaped); on success render `import_preview.html` with preview + token (+ insertion `<select name="insertion">` for subtrees, or the incompatibility message when `insertion_choices == []`).
  2. Confirm POST: `staging.claim(...)` → None ⇒ upload form with the “staged upload expired or not found — upload again” message; else in `try/finally: os.unlink(claimed)`: reopen with `open_archive`, **re-run** `validate_archive_document` (current DB state), re-check the permission predicate (decorators already re-run) and, for subtrees, resolve `insertion` (`""` → None, else `get_object_or_404(ContentNode, pk=…, course=target)` + `root_kind in legal_child_kinds(node.kind, allowed)` else TransferError); call `import_course`/`import_subtree`; `messages.success`; redirect to the new course's builder / the target builder.
  3. Cancel POST: `staging.discard`; redirect back with an info message.
- Permission gates: full import views `@permission_required("courses.add_course", raise_exception=True)`; subtree views `can_manage_course` on the slug course (403).
- Templates: styled per house rules — reuse `.card`, form styles, `.btn` patterns from existing manage templates (crib from `import`-adjacent pages like the course form). Preview shows: title, counts, human media size (`filesizeformat`), source instance, matched/dropped subjects, subtree CSS/JS note (`{{ … }}` plain interpolation — never `|safe`), confirm + cancel buttons (two separate forms), hidden `token` input.
- i18n: `uv run python manage.py makemessages -l pl`, translate every new msgid, **clear any `#, fuzzy` markers makemessages adds and grep-verify each new msgid**, `uv run python manage.py compilemessages`.

- [ ] **Step 1: Failing tests** (append to `tests/test_transfer_views.py`) — drive with real exported zips (build via `write_archive` into `io.BytesIO`, upload with `SimpleUploadedFile("x.zip", buf.getvalue())`). Add an **autouse fixture redirecting `settings.TRANSFER_STAGING_DIR` to `tmp_path`** at the top of the module (and again in Task 13's e2e module) — otherwise view tests write real staged zips into `BASE_DIR/transfer_staging/`:

```python
@pytest.fixture(autouse=True)
def _staging_tmp(settings, tmp_path):
    settings.TRANSFER_STAGING_DIR = tmp_path / "staging"
```

Grant `courses.add_course` where the full-import flow needs it (Task 4's `owner` fixture is a bare `create_user` and would 403):

```python
from django.contrib.auth.models import Permission

user.user_permissions.add(
    Permission.objects.get(codename="add_course",
                           content_type__app_label="courses")
)
```

(or crib the fixture from the existing `views_manage.course_create` tests). Cases:
  - full import happy path: upload → 200 preview page (contains title + counts) → confirm with the token from the page context → 302; new course exists; staged file gone.
  - subtree confirm happy path: stage a chapter subtree at course B, confirm with `insertion=""` (top level) and again in a second test with a part's pk → 302 to B's builder; grafted root exists under the chosen parent; claimed file gone.
  - wrong kind at each entry point → upload response shows the pointer message, nothing staged.
  - permissions: user without `add_course` → 403 on full import; non-editor → 403 on subtree import.
  - staging lifecycle: confirm with a garbage token → “expired” message, no course; double confirm (replay the same token) → second gets “expired”, exactly ONE course; another user's token → “expired”; cancel deletes the staged file; a token staged for course A confirmed at course B's `manage_import_content_confirm` URL (user manages both) → “expired”, nothing imported, A's staged file untouched (exercises the view passing `course_pk` into `claim`).
  - confirm re-validation: stage a subtree import, delete the insertion node, confirm → **404** (same scoped `get_object_or_404` path as a forged pk; the `finally` still unlinks the claimed file), nothing written; revoke rights between preview and confirm (remove owner) → 403, nothing written; forged cross-course insertion pk → 404, nothing written.
  - subtree structure: part-rooted archive into a chapters-only course → preview shows rejection, nothing staged after discard.

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** — append to `courses/views_transfer.py`:

```python
import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from courses.ordering import legal_child_kinds
from courses.transfer import staging
from courses.transfer.importer import build_preview
from courses.transfer.importer import import_course
from courses.transfer.importer import import_subtree
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import KIND_COURSE
from courses.transfer.schema import KIND_SUBTREE
from courses.transfer.schema import TransferError

# gettext_lazy: a module-level constant with eager gettext would freeze to the
# import-time language (the PR #46 footgun).
_EXPIRED_MSG = gettext_lazy(
    "The staged upload has expired or was not found — please upload the "
    "archive again."
)


def _render_upload(request, *, target_course=None, error=None, status=200):
    return render(
        request,
        "courses/manage/import_course.html",
        {"target_course": target_course, "error": error},
        status=status,
    )


def _handle_upload(request, *, slot, expected_kind, target_course=None):
    upload = request.FILES.get("archive")
    if upload is None:
        return _render_upload(
            request, target_course=target_course,
            error=_("Choose a .zip archive to import."), status=422,
        )
    # Pre-stage size check: don't stream a multi-GiB body to the staging dir
    # only to reject it; read_archive re-checks as defense in depth.
    if upload.size > settings.TRANSFER_MAX_COMPRESSED_BYTES:
        return _render_upload(
            request, target_course=target_course, status=422,
            error=_("The archive is %(found)d bytes; this instance accepts at "
                    "most %(limit)d bytes.")
            % {"found": upload.size,
               "limit": settings.TRANSFER_MAX_COMPRESSED_BYTES},
        )
    course_pk = target_course.pk if target_course else None
    token, path = staging.stage(request.session, slot, upload, course_pk=course_pk)
    try:
        with open(path, "rb") as fh, open_archive(
            fh, expected_kind=expected_kind
        ) as (zf, manifest, document, media_entries):
            validate_archive_document(
                zf, manifest, document, media_entries,
                kind=expected_kind, target_course=target_course,
            )
            preview = build_preview(
                manifest, document, media_entries, target_course=target_course
            )
    except OSError:  # superseded/unlinked by a concurrent second-tab stage
        return _render_upload(
            request, target_course=target_course, error=_EXPIRED_MSG, status=422
        )
    except TransferError as exc:
        staging.discard(request.session, slot, token)
        return _render_upload(
            request, target_course=target_course, error=exc.message, status=422
        )
    if (
        expected_kind == KIND_SUBTREE
        and not preview["insertion_choices"]
    ):
        staging.discard(request.session, slot, token)
        return _render_upload(
            request, target_course=target_course, status=422,
            error=_(
                "This subtree cannot be placed anywhere in this course's "
                "structure."
            ),
        )
    return render(
        request,
        "courses/manage/import_preview.html",
        {"preview": preview, "token": token, "target_course": target_course},
    )


def _handle_confirm(request, *, slot, expected_kind, target_course=None):
    course_pk = target_course.pk if target_course else None
    claimed = staging.claim(
        request.session, slot, request.POST.get("token", ""), course_pk=course_pk
    )
    if claimed is None:
        return _render_upload(
            request, target_course=target_course, error=_EXPIRED_MSG, status=422
        )
    try:
        with open(claimed, "rb") as fh, open_archive(
            fh, expected_kind=expected_kind
        ) as (zf, manifest, document, media_entries):
            # §4.2: full re-validation against CURRENT state at confirm time.
            validate_archive_document(
                zf, manifest, document, media_entries,
                kind=expected_kind, target_course=target_course,
            )
            if expected_kind == KIND_COURSE:
                course = import_course(zf, manifest, document, media_entries,
                                       request.user)
                messages.success(
                    request,
                    _("Course “%(title)s” imported.") % {"title": course.title},
                )
                return redirect("courses:manage_builder", slug=course.slug)
            insertion = None
            raw = request.POST.get("insertion", "")
            if raw:
                try:
                    pk = int(raw)
                except ValueError:
                    raise TransferError(_("Invalid insertion point.")) from None
                insertion = get_object_or_404(
                    ContentNode, pk=pk, course=target_course  # scoped (§4.1)
                )
            root_kind = document["nodes"][0]["kind"]
            parent_kind = insertion.kind if insertion else None
            if root_kind not in legal_child_kinds(
                parent_kind, target_course.allowed_kinds
            ):
                raise TransferError(
                    _("A '%(kind)s' cannot be placed there.") % {"kind": root_kind}
                )
            import_subtree(zf, manifest, document, media_entries,
                           target_course, insertion, request.user)
            messages.success(request, _("Content imported."))
            return redirect("courses:manage_builder", slug=target_course.slug)
    except TransferError as exc:
        return _render_upload(
            request, target_course=target_course, error=exc.message, status=422
        )
    finally:
        try:
            os.unlink(claimed)
        except OSError:
            pass


@login_required
@permission_required("courses.add_course", raise_exception=True)
def import_course_view(request):
    if request.method == "POST":
        return _handle_upload(request, slot=staging.SLOT_COURSE,
                              expected_kind=KIND_COURSE)
    return _render_upload(request)


@login_required
@permission_required("courses.add_course", raise_exception=True)
@require_POST
def import_course_confirm(request):
    return _handle_confirm(request, slot=staging.SLOT_COURSE,
                           expected_kind=KIND_COURSE)


@login_required
@permission_required("courses.add_course", raise_exception=True)
@require_POST
def import_course_cancel(request):
    staging.discard(request.session, staging.SLOT_COURSE,
                    request.POST.get("token", ""))
    messages.info(request, _("Import cancelled."))
    return redirect("courses:manage_course_list")


def _target_or_403(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    return course


@login_required
def import_content_view(request, slug):
    course = _target_or_403(request, slug)
    if request.method == "POST":
        return _handle_upload(request, slot=staging.SLOT_SUBTREE,
                              expected_kind=KIND_SUBTREE, target_course=course)
    return _render_upload(request, target_course=course)


@login_required
@require_POST
def import_content_confirm(request, slug):
    course = _target_or_403(request, slug)
    return _handle_confirm(request, slot=staging.SLOT_SUBTREE,
                           expected_kind=KIND_SUBTREE, target_course=course)


@login_required
@require_POST
def import_content_cancel(request, slug):
    course = _target_or_403(request, slug)
    staging.discard(request.session, staging.SLOT_SUBTREE,
                    request.POST.get("token", ""))
    messages.info(request, _("Import cancelled."))
    return redirect("courses:manage_builder", slug=course.slug)
```

`courses/urls.py` — add (the `import/` literals sit safely beside the `<slug>` routes; no manage route is bare `manage/courses/<slug>/`):

```python
    path("manage/courses/import/", views_transfer.import_course_view,
         name="manage_course_import"),
    path("manage/courses/import/confirm/", views_transfer.import_course_confirm,
         name="manage_course_import_confirm"),
    path("manage/courses/import/cancel/", views_transfer.import_course_cancel,
         name="manage_course_import_cancel"),
    path("manage/courses/<slug:slug>/import-content/",
         views_transfer.import_content_view, name="manage_import_content"),
    path("manage/courses/<slug:slug>/import-content/confirm/",
         views_transfer.import_content_confirm,
         name="manage_import_content_confirm"),
    path("manage/courses/<slug:slug>/import-content/cancel/",
         views_transfer.import_content_cancel,
         name="manage_import_content_cancel"),
```

Template skeletons (extend the manage base template used by sibling pages — check `course_list.html`'s `{% extends %}`; style with the existing `.card`/`.btn`/form classes, no new CSS):

`templates/courses/manage/import_course.html`:

```html
{% extends "base.html" %}{% load i18n %}
{% block content %}
<div class="card">
  {% if target_course %}
    <h1>{% blocktrans with title=target_course.title %}Import content into {{ title }}{% endblocktrans %}</h1>
  {% else %}
    <h1>{% trans "Import course" %}</h1>
  {% endif %}
  {% if error %}<p class="form-error" role="alert">{{ error }}</p>{% endif %}
  {% comment %}Explicit action is load-bearing: this template is also re-rendered
  from the confirm/cancel URLs on error; a relative post would hit @require_POST
  confirm again and loop on "expired".{% endcomment %}
  <form method="post" enctype="multipart/form-data"
        action="{% if target_course %}{% url 'courses:manage_import_content' target_course.slug %}{% else %}{% url 'courses:manage_course_import' %}{% endif %}">
    {% csrf_token %}
    <input type="file" name="archive" accept=".zip" required>
    <button type="submit" class="btn">{% trans "Upload and preview" %}</button>
  </form>
</div>
{% endblock %}
```

`templates/courses/manage/import_preview.html` — same shell; shows `{{ preview.title }}`, node/element/media counts, `{{ preview.media_total_bytes|filesizeformat }}`, `{{ preview.source.instance }}`, matched/dropped subject lists, the subtree CSS/JS note when `preview.context_css_js`, then two forms side by side: confirm (hidden `token`, plus the `<select name="insertion">` looping `preview.insertion_choices` for subtrees) and cancel (also carrying the hidden `token` — discard is token-matched). Both forms need explicit branched `action` attributes, mirroring the upload form:

```html
<form method="post"
      action="{% if target_course %}{% url 'courses:manage_import_content_confirm' target_course.slug %}{% else %}{% url 'courses:manage_course_import_confirm' %}{% endif %}">
...
<form method="post"
      action="{% if target_course %}{% url 'courses:manage_import_content_cancel' target_course.slug %}{% else %}{% url 'courses:manage_course_import_cancel' %}{% endif %}">
```

All interpolation plain `{{ }}` — never `|safe`.
- [ ] **Step 4: i18n pass** — makemessages/translate/de-fuzz/compilemessages; `uv run pytest tests/test_transfer_views.py -v` PASS; run the full suite `uv run pytest -x -q` (regressions).
- [ ] **Step 5: Screenshot check** — throwaway Playwright script: upload form + preview page, light and dark; self-critique; delete script.
- [ ] **Step 6: Format, lint, commit** — `git commit -m "feat(transfer): import views (upload/preview/confirm/cancel), templates, EN/PL strings"`.

---

### Task 13: e2e tests, deployment note, final DoD

**Files:**
- Create: `tests/test_e2e_transfer.py`
- Create: `docs/deployment-course-transfer.md` (or append to the existing deployment doc if one exists — Glob `docs/*deploy*` first)
- Test: full suite

**Interfaces:** consumes everything; no new production code (test-only + docs).

- [ ] **Step 1: Write the two e2e tests** (mirror the structure/fixtures of `tests/test_e2e_builder.py` — same live_server + Playwright page fixtures; REAL gestures only, no `page.evaluate` shortcuts):
  1. **Full-course round trip:** seed a small course (a unit with a text element) as an owner granted `courses.add_course` via `user.user_permissions.add(Permission.objects.get(codename="add_course", content_type__app_label="courses"))`; log in through the real login form; navigate to the builder, click the real **Export** button and capture the download (`page.expect_download()`); go to `/manage/courses/`, click **Import course**, set the file input to the downloaded path (`set_input_files` on the real `<input type=file>`), submit, assert the preview shows the course title, click **Confirm import**, assert redirect and that the new course (suffixed slug) appears in the manage list.
  2. **Subtree via insertion picker:** seed course A (chapter → unit) and course B (full depth, one part); export the chapter subtree via the real per-node action; open B's **Import content**, upload, pick the part in the real `<select>`, confirm; open B's builder and assert the chapter title renders under the part.
- [ ] **Step 2: Run** `uv run pytest tests/test_e2e_transfer.py -v` — PASS (headed debug locally if flaky; follow the existing e2e wait patterns).
- [ ] **Step 3: Deployment note** — short doc: proxy `client_max_body_size` + worker/proxy timeouts must accommodate `TRANSFER_MAX_COMPRESSED_BYTES` on the import endpoints; `TRANSFER_STAGING_DIR` must be shared storage in multi-host deployments and must not be web-served; caps are settings — raise them for video-heavy courses.
- [ ] **Step 4: Final DoD sweep**

```bash
uv run pytest -q                      # full suite green
uv run ruff format --check . && uv run ruff check .
uv run python manage.py makemigrations --check --dry-run   # no missing migrations
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test(transfer): e2e export→import round trips + deployment note"
```

---

## Self-Review Notes (already applied)

- Spec coverage walked §1–§10: every §5 check has a task (archive: T5; structural: T6; per-type: T7; media: T8; commit backstop: T9), §4.3 staging: T11/T12, §3 export: T2–T4, §9 tests distributed to the layer that owns each rule, §8 messages asserted by needle in each layer's tests. The §5 deployment note lands in T13.
- Type consistency: `TransferError.message`, `open_archive(fileobj, *, expected_kind)`, `validate_archive_document(zf, manifest, document, media_entries, *, kind, target_course=None)`, `import_course(zf, manifest, document, media_entries, user)`, `import_subtree(… , target_course, insertion_node, user)`, `stage/claim/discard(session, slot, …)` — used with these exact signatures in T5–T13.
- Known seams re-verified in code before writing: `unique_course_slug` (forms.py:21), `create_asset`/`truncate_filename` (media.py), `legal_child_kinds`/`kinds_for_flags` (ordering.py), `can_manage_course` (access.py:30), `add_course` gate (views_manage.py:66), URL names (urls.py), `DragZone.clean` epsilon (models.py:879-889), `SENTINEL` (fillblank.py:17), `_validate_file` committed-skip (validators.py:81).
