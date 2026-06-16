# Phase 1b-ii — Content Editors & Media Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a course owner / Platform Admin a per-unit **editor ｜ preview** page that adds, edits, reorders, and deletes a unit's elements (text/image/video/iframe/math) with a live server-rendered preview, backed by a per-course **MediaAsset** library (manager + picker).

**Architecture:** Server-rendered Django on the merged 1a/1b-i `courses` app. The editor page POSTs each element mutation to a thin view that delegates to pure services in `courses/builder.py` (element ops) and `courses/media.py` (assets), runs inside `transaction.atomic()` with `select_for_update()`, reuses 1b-i's optimistic `updated`-token (`unit_token` field + `_check_token`), and returns two self-describing HTML fragments (`data-scope="editor"` + `data-scope="preview"`) swapped by vanilla `editor.js`. With JS off, the same routes work as full-page POSTs. One schema migration introduces `MediaAsset` (image/video elements switch from embedded files to a `media` FK).

**Tech Stack:** Python 3.13 / Django 5.2 (`uv run python manage.py …`), PostgreSQL, pytest + factory_boy, Playwright (e2e), nh3 (`sanitize_html`), vendored KaTeX, bespoke token CSS, vanilla JS. No HTMX/React.

**Spec:** `docs/superpowers/specs/2026-06-16-phase-1b-ii-content-editors-and-media-design.md` (spec-reviewed clean, 5 rounds).

---

## File Structure

**New files:**
- `courses/media.py` — asset services: `create_asset`, `usage_count`, `assets_with_usage`, `delete_asset` (+ `AssetInUseError`).
- `courses/views_media.py` — `media_manager`, `media_upload`, `media_delete`, `media_picker`.
- `courses/element_forms.py` — the 5 per-type `ModelForm`s + `FORM_FOR_TYPE` registry + `MediaAssetForm`.
- `courses/static/courses/js/editor.js` — editor fragment-swap, inline-editor selection, dirty-discard, add/save wiring.
- `courses/static/courses/js/media_picker.js` — picker modal open/tabs/pick/upload, drag-drop.
- `courses/static/courses/js/text_toolbar.js` — contenteditable toolbar.
- `courses/static/courses/css/editor.css` — editor ｜ preview + media manager + picker layout.
- Templates under `templates/courses/manage/editor/`: `editor.html`, `_editor_scope.html`, `_preview.html`, `_element_row.html`, `_type_picker.html`, and per-type editor partials `_edit_text.html`, `_edit_image.html`, `_edit_video.html`, `_edit_iframe.html`, `_edit_math.html`.
- Templates under `templates/courses/manage/media/`: `manager.html`, `_asset_cell.html`, `_picker.html`.
- Tests: `tests/test_media_model.py`, `tests/test_media_manager.py`, `tests/test_media_picker.py`, `tests/test_editor_page.py`, `tests/test_element_add_save.py`, `tests/test_element_editor_ops.py`, `tests/test_e2e_editor.py`.

**Modified files:**
- `courses/models.py` — add `MediaAsset`; swap `ImageElement.image`→`media` FK, `VideoElement.file`→`media` FK; `VideoElement.clean()` XOR.
- `courses/migrations/0007_mediaasset.py` (schema) + `0008_migrate_files_to_assets.py` (data, irreversible).
- `templates/courses/elements/imageelement.html`, `videoelement.html` — read `el.media.file.url`.
- `courses/builder.py` — add `add_element`, `save_element`, plus a freshly-read-unit helper used by the editor views.
- `courses/views_manage.py` — add `editor`, `element_add`, `element_save`, `_render_editor_fragments`; extend `element_move`/`element_delete`/`_element_conflict` for `ctx=editor`; editor `?changed=1` notice.
- `courses/urls.py` — add editor + element add/save + media routes.
- `courses/static/courses/js/math.js` — accept a root element.
- `templates/courses/manage/_unit_panel.html` — collapse the element list to a read-only summary; activate the seam links.
- `courses/templatetags/courses_manage_extras.py` — add `element_summary` filter.
- `tests/factories.py` — `MediaAssetFactory`, element-creation helpers.

**Conventions (follow exactly — verified against merged code):**
- Manage routes under `app_name = "courses"`; reverse as `courses:manage_*`. Access: `@login_required` + `_require_manage(request, slug)` (owner OR `courses.change_course`); element/asset object scoping mirrors `get_node_or_404` (404-before-403).
- Optimistic token = the unit row's `updated.isoformat()`, posted as **`unit_token`**, compared by `builder._check_token` (raises `ConflictError` → 409). Element ops bump `unit.save(update_fields=["updated"])`.
- Fragment requests carry header `X-Requested-With: fetch` (`_wants_fragment`); editor context additionally posts `ctx=editor`. JS fetch sends `X-CSRFToken`.
- Tests: `uv run python -m pytest …`; default run excludes `e2e`. Login via `make_login(client, "name")`; PA via `make_pa(client, "name")`. Use `make_pa` for all editor/media tests (needs `courses.change_course`).
- Run a single test: `uv run python -m pytest tests/test_x.py::test_name -v`.

---

### Task 1: `MediaAsset` model + migrations + renderer updates

**Files:**
- Modify: `courses/models.py`
- Create: `courses/migrations/0007_mediaasset.py`, `courses/migrations/0008_migrate_files_to_assets.py`
- Modify: `templates/courses/elements/imageelement.html`, `templates/courses/elements/videoelement.html`
- Modify: `tests/factories.py`
- Test: `tests/test_media_model.py`

- [ ] **Step 1: Write the failing model tests**

Create `tests/test_media_model.py`:

```python
import pytest
from django.core.exceptions import ValidationError

from courses.models import ImageElement, MediaAsset, VideoElement
from tests.factories import CourseFactory


@pytest.mark.django_db
def test_mediaasset_str_and_scope():
    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x/a.png", original_filename="a.png"
    )
    assert asset.course_id == course.id
    assert asset.kind == "image"
    assert course.media_assets.count() == 1


@pytest.mark.django_db
def test_imageelement_requires_media_via_protect():
    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x/a.png", original_filename="a.png"
    )
    img = ImageElement.objects.create(media=asset, alt="diagram")
    # PROTECT: an asset referenced by an element cannot be deleted.
    from django.db.models import ProtectedError
    with pytest.raises(ProtectedError):
        asset.delete()


@pytest.mark.django_db
def test_videoelement_xor_url_or_media():
    course = CourseFactory()
    asset = MediaAsset.objects.create(
        course=course, kind="video", file="courses/media/x/v.mp4", original_filename="v.mp4"
    )
    # both set -> invalid
    v = VideoElement(url="https://www.youtube.com/embed/x", media=asset)
    with pytest.raises(ValidationError):
        v.clean()
    # neither set -> invalid
    with pytest.raises(ValidationError):
        VideoElement().clean()
    # exactly one -> valid
    VideoElement(media=asset).clean()
    VideoElement(url="https://www.youtube.com/embed/x").clean()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_media_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'MediaAsset'`.

- [ ] **Step 3: Add the `MediaAsset` model and alter the two elements**

In `courses/models.py`, add `MediaAsset` **above** `ImageElement` (after `ELEMENT_MODELS`/`ElementBase`), and replace the file fields on `ImageElement`/`VideoElement`. Reuse the existing validators already imported at the top (`validate_image_size`, `validate_video_size`, `validate_embed_url`, `FileExtensionValidator`).

```python
class MediaAsset(models.Model):
    """Per-course reusable uploaded file (image or video). Elements reference it by FK."""

    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="media_assets"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    file = models.FileField(upload_to="courses/media/")
    original_filename = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    created = models.DateTimeField(auto_now_add=True)

    # Per-kind validators (extension allowlist + size cap), applied in clean()/forms.
    IMAGE_VALIDATORS = [
        FileExtensionValidator(["png", "jpg", "jpeg", "gif", "webp"]),
        validate_image_size,
    ]
    VIDEO_VALIDATORS = [
        FileExtensionValidator(["mp4", "webm", "ogg", "mov"]),
        validate_video_size,
    ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.original_filename}"

    def clean(self):
        validators = self.IMAGE_VALIDATORS if self.kind == self.Kind.IMAGE else self.VIDEO_VALIDATORS
        for v in validators:
            v(self.file)
```

Replace `ImageElement.image` with:

```python
class ImageElement(ElementBase):
    media = models.ForeignKey(
        "MediaAsset", on_delete=models.PROTECT, limit_choices_to={"kind": "image"}
    )
    alt = models.CharField(max_length=255, blank=True)  # empty = decorative (valid)
    figcaption = models.CharField(max_length=255, blank=True)
    elements = GenericRelation(Element)
```

Replace `VideoElement` with (keep `url`, drop `file`, add `media`, update `clean()`):

```python
class VideoElement(ElementBase):
    url = models.URLField(blank=True)  # whitelisted embed URL
    media = models.ForeignKey(
        "MediaAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        limit_choices_to={"kind": "video"},
    )
    elements = GenericRelation(Element)

    def clean(self):
        has_url = bool(self.url)
        has_media = self.media_id is not None
        if has_url == has_media:
            raise ValidationError("Provide exactly one of url or media.")
        if has_url:
            validate_embed_url(self.url)
```

Remove the now-unused imports if any become dead (`FileExtensionValidator` is still used by `MediaAsset`; keep it).

- [ ] **Step 4: Generate the schema migration**

Run: `uv run python manage.py makemigrations courses -n mediaasset`
Expected: creates `courses/migrations/0007_mediaasset.py` adding `MediaAsset`, removing `ImageElement.image` + `VideoElement.file`, adding the two `media` FKs. (The FK columns are added nullable-then-altered by Django automatically; if Django prompts for a default on `ImageElement.media`, choose "provide a one-off default" → `None` is impossible for non-null — instead make the field temporarily nullable: see Step 5 note.)

> **Important ordering note:** because `ImageElement.media` is non-null and existing rows exist (the seed image), the *data* migration (0008) must run **between** "add nullable FK + new model" and "make FK non-null". Simplest robust approach: generate 0007 with `ImageElement.media` declared **`null=True`** TEMPORARILY is *not* what we want long-term. Instead, split:
> - **0007** = create `MediaAsset` + add `ImageElement.media` (null=True) + add `VideoElement.media` (null=True) + keep old `image`/`file` columns.
> - **0008** = `RunPython` data copy (below) + `AlterField` making `ImageElement.media` non-null + `RemoveField` old `image`/`file`.
> Achieve this by editing the autogenerated migrations: keep 0007 as create+add-nullable (manually set `null=True` on `ImageElement.media` in 0007), and author 0008 by hand (next step).

- [ ] **Step 5: Author the data migration `0008_migrate_files_to_assets.py`**

Create `courses/migrations/0008_migrate_files_to_assets.py`:

```python
import os

from django.db import migrations, models
import django.db.models.deletion


def copy_files_to_assets(apps, schema_editor):
    MediaAsset = apps.get_model("courses", "MediaAsset")
    ImageElement = apps.get_model("courses", "ImageElement")
    # Only image files exist in the seed; videos are url-only. Copy the storage
    # REFERENCE (the field's .name), never the bytes — CI-safe when the file is absent.
    for img in ImageElement.objects.all():
        name = getattr(img.image, "name", "") if hasattr(img, "image") else ""
        if not name:
            continue
        asset = MediaAsset.objects.create(
            course_id=img_course_id(apps, img),
            kind="image",
            file=name,
            original_filename=os.path.basename(name)[:255],
        )
        img.media_id = asset.id
        img.save(update_fields=["media"])


def img_course_id(apps, img):
    # ImageElement -> Element join-row -> unit (ContentNode) -> course.
    Element = apps.get_model("courses", "Element")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.get(app_label="courses", model="imageelement")
    join = Element.objects.filter(content_type=ct, object_id=img.id).first()
    return join.unit.course_id


class Migration(migrations.Migration):
    dependencies = [("courses", "0007_mediaasset")]

    operations = [
        migrations.RunPython(copy_files_to_assets, migrations.RunPython.noop),
        # image files are now on assets; make the FK required and drop old columns.
        migrations.AlterField(
            model_name="imageelement",
            name="media",
            field=models.ForeignKey(
                limit_choices_to={"kind": "image"},
                on_delete=django.db.models.deletion.PROTECT,
                to="courses.mediaasset",
            ),
        ),
        migrations.RemoveField(model_name="imageelement", name="image"),
        migrations.RemoveField(model_name="videoelement", name="file"),
    ]
```

> If the autogenerated 0007 already removed `image`/`file`, move those `RemoveField`s into 0008 (after the copy) and make 0007 keep them. Verify by reading 0007 after generation and editing so the old columns survive into 0008's copy step.

- [ ] **Step 6: Update the two element renderers**

`templates/courses/elements/imageelement.html`:

```html
<figure class="el el--image">
  <img src="{{ el.media.file.url }}" alt="{{ el.alt }}">
  {% if el.figcaption %}<figcaption>{{ el.figcaption }}</figcaption>{% endif %}
</figure>
```

`templates/courses/elements/videoelement.html`:

```html
<div class="el el--video">
  {% if el.url %}
    <iframe src="{{ el.url }}" loading="lazy" allowfullscreen title="video"></iframe>
  {% else %}
    <video controls src="{{ el.media.file.url }}"></video>
  {% endif %}
</div>
```

- [ ] **Step 7: Add the factory + element helpers**

In `tests/factories.py`, add (import `MediaAsset`, `ImageElement`, `VideoElement`, `MathElement`, `IframeElement`, `TextElement`, `Element` at the top):

```python
class MediaAssetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MediaAsset

    course = factory.SubFactory(CourseFactory)
    kind = "image"
    file = factory.Sequence(lambda n: f"courses/media/test-{n}.png")
    original_filename = factory.Sequence(lambda n: f"test-{n}.png")


def add_element(unit, obj):
    """Attach a saved concrete element `obj` to `unit` via a new Element join-row."""
    return Element.objects.create(unit=unit, content_object=obj)
```

- [ ] **Step 8: Run migrations + the model tests**

Run:
```bash
uv run python manage.py migrate
uv run python -m pytest tests/test_media_model.py -v
```
Expected: PASS. Then `uv run python manage.py makemigrations --check` → clean (no pending changes).

- [ ] **Step 9: Run the full suite to catch fallout from the field swap**

Run: `uv run python -m pytest -q`
Expected: failures only in tests/seed code that referenced `ImageElement.image` / `VideoElement.file`. Fix `courses/management/commands/seed_demo_course.py`: `_image` now creates a `MediaAsset` first, and `_video` stays url-only:

```python
def _image(self, unit, slug, alt):
    course = unit.course
    asset, _ = MediaAsset.objects.get_or_create(
        course=course, original_filename="demo.png",
        defaults={"kind": "image", "file": "courses/images/demo.png"},
    )
    self._upsert(unit, ImageElement, media=asset, alt=alt)
```
(Add `from courses.models import MediaAsset` to the command.) Re-run `pytest -q` until green.

- [ ] **Step 10: Commit**

```bash
git add courses/models.py courses/migrations/0007_mediaasset.py courses/migrations/0008_migrate_files_to_assets.py templates/courses/elements/imageelement.html templates/courses/elements/videoelement.html tests/factories.py tests/test_media_model.py courses/management/commands/seed_demo_course.py
git commit -m "feat(courses): MediaAsset model + image/video media FK + data migration"
```

---

### Task 2: Media services + manager page (5.13)

**Files:**
- Create: `courses/media.py`
- Create: `courses/views_media.py`
- Create: `courses/element_forms.py` (just `MediaAssetForm` for now)
- Create: `templates/courses/manage/media/manager.html`, `_asset_cell.html`
- Modify: `courses/urls.py`
- Test: `tests/test_media_manager.py`

- [ ] **Step 1: Write the failing service + view tests**

Create `tests/test_media_manager.py`:

```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from courses import media as media_svc
from courses.models import ImageElement, MediaAsset
from tests.factories import CourseFactory, MediaAssetFactory, ContentNodeFactory, add_element
from tests.factories import make_pa


@pytest.mark.django_db
def test_usage_count_counts_only_fk_references():
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    other = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    add_element(unit, ImageElement.objects.create(media=asset, alt="a"))
    add_element(unit, ImageElement.objects.create(media=asset, alt="b"))
    assert media_svc.usage_count(asset) == 2
    assert media_svc.usage_count(other) == 0


@pytest.mark.django_db
def test_delete_unused_succeeds_in_use_refused():
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="image")
    media_svc.delete_asset(asset)  # unused -> ok
    assert not MediaAsset.objects.filter(pk=asset.pk).exists()

    used = MediaAssetFactory(course=course, kind="image")
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    add_element(unit, ImageElement.objects.create(media=used, alt="a"))
    with pytest.raises(media_svc.AssetInUseError):
        media_svc.delete_asset(used)


@pytest.mark.django_db
def test_manager_lists_only_this_courses_assets(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    MediaAssetFactory(course=course, original_filename="mine.png")
    MediaAssetFactory(course=CourseFactory(), original_filename="other.png")
    resp = client.get(reverse("courses:manage_media", kwargs={"slug": course.slug}))
    assert resp.status_code == 200
    assert b"mine.png" in resp.content
    assert b"other.png" not in resp.content


@pytest.mark.django_db
def test_upload_then_delete_in_use_returns_409(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    png = SimpleUploadedFile("p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, content_type="image/png")
    up = client.post(
        reverse("courses:manage_media_upload", kwargs={"slug": course.slug}),
        {"kind": "image", "file": png}, HTTP_X_REQUESTED_WITH="fetch",
    )
    assert up.status_code == 200
    asset = MediaAsset.objects.get(course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    add_element(unit, ImageElement.objects.create(media=asset, alt="a"))
    dele = client.post(
        reverse("courses:manage_media_delete", kwargs={"slug": course.slug, "pk": asset.pk}),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert dele.status_code == 409
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_media_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.media'`.

- [ ] **Step 3: Write the asset services**

Create `courses/media.py`:

```python
import os

from django.db import transaction
from django.db.models import Count, ProtectedError

from courses.models import ImageElement, MediaAsset, VideoElement


class AssetInUseError(Exception):
    """A MediaAsset still referenced by an element cannot be deleted → HTTP 409."""


def usage_count(asset):
    return (
        ImageElement.objects.filter(media=asset).count()
        + VideoElement.objects.filter(media=asset).count()
    )


def assets_with_usage(course):
    """Course assets annotated with a bulk usage count (avoids a per-asset N+1)."""
    return list(
        course.media_assets.annotate(
            img_uses=Count("imageelement", distinct=True),
            vid_uses=Count("videoelement", distinct=True),
        ).order_by("-created")
    )


def create_asset(course, kind, uploaded_file, user):
    asset = MediaAsset(
        course=course,
        kind=kind,
        file=uploaded_file,
        original_filename=os.path.basename(uploaded_file.name)[:255],
        uploaded_by=user,
    )
    asset.full_clean()  # per-kind extension + size validators (ValidationError -> 422)
    asset.save()
    return asset


@transaction.atomic
def delete_asset(asset):
    if usage_count(asset) > 0:
        raise AssetInUseError()
    try:
        asset.delete()
    except ProtectedError as exc:  # concurrent attach raced the usage re-check
        raise AssetInUseError() from exc
```

> `assets_with_usage` requires reverse relations `imageelement`/`videoelement`. Those reverse accessors exist automatically from the `media` FK (default related name = lowercased model name). The annotated counts feed `_asset_cell.html`; `usage_count` is the authoritative in-txn predicate for delete.

- [ ] **Step 4: Write the `MediaAssetForm` and the media views**

Create `courses/element_forms.py` (the per-element forms join in Task 5; start with the asset form):

```python
from django import forms

from courses.models import MediaAsset


class MediaAssetForm(forms.ModelForm):
    class Meta:
        model = MediaAsset
        fields = ["kind", "file"]

    def clean(self):
        cleaned = super().clean()
        kind, file = cleaned.get("kind"), cleaned.get("file")
        if kind and file:
            validators = (
                MediaAsset.IMAGE_VALIDATORS if kind == MediaAsset.Kind.IMAGE
                else MediaAsset.VIDEO_VALIDATORS
            )
            for v in validators:
                v(file)
        return cleaned
```

Create `courses/views_media.py`:

```python
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from courses import media as media_svc
from courses.access import can_manage_course
from courses.models import Course, MediaAsset
from courses.views_manage import _require_manage, _wants_fragment


@login_required
def media_manager(request, slug):
    course = _require_manage(request, slug)
    return render(
        request, "courses/manage/media/manager.html",
        {"course": course, "assets": media_svc.assets_with_usage(course)},
    )


@login_required
def media_upload(request, slug):
    course = _require_manage(request, slug)
    from courses.element_forms import MediaAssetForm
    form = MediaAssetForm(request.POST, request.FILES)
    if not form.is_valid():
        msg = "; ".join(m for errs in form.errors.values() for m in errs)
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(request, "courses/manage/_op_error.html", {"message": msg}, status=422)
    asset = media_svc.create_asset(
        course, form.cleaned_data["kind"], request.FILES["file"], request.user
    )
    if not _wants_fragment(request):
        return redirect("courses:manage_media", slug=course.slug)
    return render(
        request, "courses/manage/media/_asset_cell.html",
        {"course": course, "asset": asset, "img_uses": 0, "vid_uses": 0},
    )


@login_required
def media_delete(request, slug, pk):
    course = _require_manage(request, slug)
    asset = get_object_or_404(MediaAsset, pk=pk, course=course)
    try:
        media_svc.delete_asset(asset)
    except media_svc.AssetInUseError:
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(
            request, "courses/manage/_op_error.html",
            {"message": "This file is in use and cannot be deleted."}, status=409,
        )
    if not _wants_fragment(request):
        return redirect("courses:manage_media", slug=course.slug)
    return render(request, "courses/manage/_empty.html", {})  # JS removes the cell
```

Create a trivial `templates/courses/manage/_empty.html` containing a single space, used as a 200 body when JS will remove the cell.

- [ ] **Step 5: Write the manager templates**

`templates/courses/manage/media/_asset_cell.html`:

```html
{% load i18n %}
<div class="asset-cell" data-asset-id="{{ asset.pk }}" data-kind="{{ asset.kind }}"
     data-url="{{ asset.file.url }}" data-name="{{ asset.original_filename }}">
  {% if asset.kind == "image" %}
    <img class="asset-thumb" src="{{ asset.file.url }}" alt="">
  {% else %}
    <span class="asset-thumb asset-thumb--video">▶</span>
  {% endif %}
  <span class="asset-name">{{ asset.original_filename }}</span>
  {% with uses=img_uses|add:vid_uses %}
    {% if uses %}<span class="asset-uses">{% blocktrans %}in use ×{{ uses }}{% endblocktrans %}</span>{% endif %}
    <form class="asset-del" method="post"
          action="{% url 'courses:manage_media_delete' slug=course.slug pk=asset.pk %}" data-op="asset-delete">
      {% csrf_token %}
      <button type="submit" class="btn btn--small tree__act--danger"
              {% if uses %}disabled title="{% trans 'In use — cannot delete' %}"{% endif %}>{% trans "Delete" %}</button>
    </form>
  {% endwith %}
</div>
```

`templates/courses/manage/media/manager.html`:

```html
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "Media" %} — {{ course.title }}{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'courses/css/editor.css' %}">{% endblock %}
{% block content %}
<section class="media-manager" data-course-slug="{{ course.slug }}"
         data-upload-url="{% url 'courses:manage_media_upload' slug=course.slug %}">
  <h1>{% trans "Media" %} — {{ course.title }}</h1>
  <form class="media-upload" method="post" enctype="multipart/form-data"
        action="{% url 'courses:manage_media_upload' slug=course.slug %}">
    {% csrf_token %}
    <label>{% trans "Kind" %}
      <select name="kind"><option value="image">{% trans "Image" %}</option><option value="video">{% trans "Video" %}</option></select>
    </label>
    <input type="file" name="file" required>
    <button class="btn" type="submit">{% trans "Upload" %}</button>
  </form>
  <div class="media-drop" hidden>{% trans "Drag & drop files here" %}</div>
  <div class="asset-grid">
    {% for asset in assets %}
      {% include "courses/manage/media/_asset_cell.html" with asset=asset img_uses=asset.img_uses vid_uses=asset.vid_uses %}
    {% empty %}
      <p class="empty-state">{% trans "No media yet." %}</p>
    {% endfor %}
  </div>
</section>
{% endblock %}
{% block extra_js %}<script src="{% static 'courses/js/media_picker.js' %}" defer></script>{% endblock %}
```

- [ ] **Step 6: Wire the routes**

In `courses/urls.py`, add `from courses import views_media` and append:

```python
    path("manage/courses/<slug:slug>/media/", views_media.media_manager, name="manage_media"),
    path("manage/courses/<slug:slug>/media/upload/", views_media.media_upload, name="manage_media_upload"),
    path("manage/courses/<slug:slug>/media/<int:pk>/delete/", views_media.media_delete, name="manage_media_delete"),
    path("manage/courses/<slug:slug>/media/picker/", views_media.media_picker, name="manage_media_picker"),
```

(The `media_picker` view is added in Task 3; add a temporary stub `def media_picker(request, slug): ...` returning `render(... "_picker.html")` now or defer the path line to Task 3. Recommended: add the picker route line in Task 3 to keep each commit importable.)

- [ ] **Step 7: Run the tests**

Run: `uv run python -m pytest tests/test_media_manager.py -v`
Expected: PASS (all four). Then `uv run python -m pytest -q` green.

- [ ] **Step 8: Commit**

```bash
git add courses/media.py courses/views_media.py courses/element_forms.py courses/urls.py templates/courses/manage/media/ templates/courses/manage/_empty.html tests/test_media_manager.py
git commit -m "feat(courses): media manager (5.13) — upload, grid, guarded delete"
```

---

### Task 3: Picker modal (7.4)

**Files:**
- Modify: `courses/views_media.py` (add `media_picker`)
- Create: `templates/courses/manage/media/_picker.html`
- Modify: `courses/urls.py` (picker route, if deferred from Task 2)
- Test: `tests/test_media_picker.py`

- [ ] **Step 1: Write the failing picker test**

Create `tests/test_media_picker.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import CourseFactory, MediaAssetFactory, make_pa


@pytest.mark.django_db
def test_picker_filters_by_kind_and_course(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    MediaAssetFactory(course=course, kind="image", original_filename="pic.png")
    MediaAssetFactory(course=course, kind="video", original_filename="clip.mp4")
    MediaAssetFactory(course=CourseFactory(), kind="image", original_filename="foreign.png")
    resp = client.get(
        reverse("courses:manage_media_picker", kwargs={"slug": course.slug}) + "?kind=image"
    )
    assert resp.status_code == 200
    assert b"pic.png" in resp.content
    assert b"clip.mp4" not in resp.content      # wrong kind
    assert b"foreign.png" not in resp.content    # wrong course
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_media_picker.py -v`
Expected: FAIL (NoReverseMatch or AttributeError — `media_picker` missing).

- [ ] **Step 3: Implement the picker view**

Add to `courses/views_media.py`:

```python
@login_required
def media_picker(request, slug):
    course = _require_manage(request, slug)
    kind = request.GET.get("kind", "image")
    if kind not in ("image", "video"):
        kind = "image"
    assets = course.media_assets.filter(kind=kind).order_by("-created")
    return render(
        request, "courses/manage/media/_picker.html",
        {"course": course, "kind": kind, "assets": assets},
    )
```

Add the route line to `courses/urls.py` if not already added in Task 2.

- [ ] **Step 4: Write the picker fragment template**

`templates/courses/manage/media/_picker.html`:

```html
{% load i18n %}
<div class="picker" data-kind="{{ kind }}"
     data-upload-url="{% url 'courses:manage_media_upload' slug=course.slug %}">
  <div class="picker__tabs">
    <button type="button" class="picker__tab is-on" data-tab="library">{% trans "Library" %}</button>
    <button type="button" class="picker__tab" data-tab="upload">{% trans "Upload" %}</button>
  </div>
  <div class="picker__panel" data-panel="library">
    <div class="asset-grid">
      {% for asset in assets %}
        <button type="button" class="asset-cell asset-pick" data-asset-id="{{ asset.pk }}"
                data-url="{{ asset.file.url }}" data-name="{{ asset.original_filename }}">
          {% if asset.kind == "image" %}<img class="asset-thumb" src="{{ asset.file.url }}" alt="">
          {% else %}<span class="asset-thumb asset-thumb--video">▶</span>{% endif %}
          <span class="asset-name">{{ asset.original_filename }}</span>
        </button>
      {% empty %}<p class="empty-state">{% trans "No media yet." %}</p>{% endfor %}
    </div>
  </div>
  <div class="picker__panel" data-panel="upload" hidden>
    <input type="file" class="picker__file" data-kind="{{ kind }}">
  </div>
</div>
```

(The picker's pick/upload→auto-select behaviour and its no-JS `<select>` fallback are wired in the element editors, Task 5, + `media_picker.js`, Task 9.)

- [ ] **Step 5: Run the test + commit**

Run: `uv run python -m pytest tests/test_media_picker.py -v` → PASS.

```bash
git add courses/views_media.py courses/urls.py templates/courses/manage/media/_picker.html tests/test_media_picker.py
git commit -m "feat(courses): media picker modal fragment (7.4) — kind/course-filtered library"
```

---

### Task 4: Editor ｜ preview page shell + read-only unit panel + seam

**Files:**
- Modify: `courses/views_manage.py` (add `editor`, `_render_editor_fragments`; `?changed` notice)
- Modify: `courses/urls.py`
- Modify: `courses/templatetags/courses_manage_extras.py` (add `element_summary`)
- Create: `templates/courses/manage/editor/editor.html`, `_editor_scope.html`, `_preview.html`, `_element_row.html`
- Modify: `templates/courses/manage/_unit_panel.html` (read-only summary + active seam)
- Test: `tests/test_editor_page.py`

- [ ] **Step 1: Write the failing editor-page tests**

Create `tests/test_editor_page.py`:

```python
import pytest
from django.urls import reverse

from courses.models import MathElement, TextElement
from tests.factories import (CourseFactory, ContentNodeFactory, add_element, make_pa)


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.mark.django_db
def test_editor_renders_unit_with_elements(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    add_element(unit, TextElement.objects.create(body="<p>Hello world</p>"))
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content
    assert b'data-scope="preview"' in resp.content
    assert b"Hello world" in resp.content  # preview reuses 1a renderer


@pytest.mark.django_db
def test_editor_404_on_non_unit(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    part = ContentNodeFactory(course=course, parent=None, kind="part", unit_type=None)
    resp = client.get(_editor_url(course, part))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_editor_404_on_foreign_course_slug(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    other = CourseFactory()
    unit = ContentNodeFactory(course=other, parent=None, kind="unit", unit_type="lesson")
    resp = client.get(reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_editor_empty_unit_shows_empty_state(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_editor_page.py -v`
Expected: FAIL (NoReverseMatch `manage_editor`).

- [ ] **Step 3: Add the `element_summary` template filter**

In `courses/templatetags/courses_manage_extras.py`, add (the per-type summary label from spec DoD #1):

```python
import re
from django.utils.html import strip_tags
from django.utils.text import Truncator

@register.filter
def element_summary(el):
    """Display label for an element row (DoD #1). el is the concrete content object."""
    name = el.__class__.__name__
    if name == "IframeElement":
        return el.title or _host(el.url) or "Iframe"
    if name == "ImageElement":
        return el.alt or (el.media.original_filename if el.media_id else "") or "Image"
    if name == "VideoElement":
        if el.media_id:
            return el.media.original_filename
        return _host(el.url) or "Video"
    if name == "TextElement":
        text = re.sub(r"\s+", " ", strip_tags(el.body)).strip()
        from html import unescape
        return Truncator(unescape(text)).chars(60) or "Text"
    if name == "MathElement":
        return Truncator(el.latex).chars(60) or "Math"
    return name

def _host(url):
    from urllib.parse import urlsplit
    return urlsplit(url or "").hostname or ""
```

(Ensure `register = template.Library()` and `from django.utils.translation import gettext as _` exist at the top — they already do in 1b-i's `courses_manage_extras.py`; if `_` is absent, add it.)

- [ ] **Step 4: Add the editor view + fragment renderer**

In `courses/views_manage.py`, add (reuse `get_node_or_404` with `require_unit=True`):

```python
def _render_editor_fragments(request, unit, status=200, open_form=""):
    """Render editor pane + preview as two data-scope fragments (the single source for
    every editor-context 200/409/422 response). Always serialises data-updated from the
    freshly-read unit row so the token never desyncs."""
    unit.refresh_from_db(fields=["updated"])
    elements = list(unit.elements.select_related("content_type").order_by("order", "pk"))
    rows = [(e, e.content_object) for e in elements]
    resp = render(
        request, "courses/manage/editor/_editor_scope.html",
        {"course": unit.course, "unit": unit, "rows": rows, "open_form": open_form,
         "preview_elements": [obj for _e, obj in rows]},
    )
    resp.status_code = status
    return resp


@login_required
def editor(request, slug, pk):
    unit = get_node_or_404(pk, slug, require_unit=True)  # 404-before-403
    if not can_manage_course(request.user, unit.course):
        raise PermissionDenied
    elements = list(unit.elements.select_related("content_type").order_by("order", "pk"))
    rows = [(e, e.content_object) for e in elements]
    return render(
        request, "courses/manage/editor/editor.html",
        {"course": unit.course, "unit": unit, "rows": rows,
         "preview_elements": [obj for _e, obj in rows],
         "changed": request.GET.get("changed") == "1"},
    )
```

> The editor `_editor_scope.html` fragment is used both by the full page (included inside `editor.html`) and as the standalone swap target. Keep the `data-scope="editor"`/`data-scope="preview"` roots inside `_editor_scope.html` so the same markup serves both.

- [ ] **Step 5: Write the editor templates**

`templates/courses/manage/editor/_preview.html` (reuses the 1a `render_element` tag):

```html
{% load courses_extras %}
<div class="editor-preview" data-scope="preview">
  {% for obj in preview_elements %}
    <section>{% render_element obj %}</section>
  {% empty %}
    <p class="empty-state">{% trans "Nothing to preview yet." %}</p>
  {% endfor %}
</div>
```

`templates/courses/manage/editor/_element_row.html`:

```html
{% load i18n courses_manage_extras %}
<li class="el-row" data-element="{{ el.pk }}">
  <span class="el-tag">{{ obj|element_type_label_obj }}</span>
  <button type="button" class="el-select" data-element-id="{{ el.pk }}">{{ obj|element_summary }}</button>
  <form class="tree__inline" method="post" action="{% url 'courses:manage_element_move' slug=unit.course.slug %}" data-op="element-move">
    {% csrf_token %}
    <input type="hidden" name="ctx" value="editor">
    <input type="hidden" name="element" value="{{ el.pk }}">
    <input type="hidden" name="unit" value="{{ unit.pk }}">
    <input type="hidden" name="unit_token" value="{{ unit.updated.isoformat }}">
    <button class="tree__act" type="submit" name="direction" value="up" aria-label="{% trans 'Move up' %}">↑</button>
    <button class="tree__act" type="submit" name="direction" value="down" aria-label="{% trans 'Move down' %}">↓</button>
  </form>
  <form class="tree__inline" method="post" action="{% url 'courses:manage_element_delete' slug=unit.course.slug %}" data-op="element-delete">
    {% csrf_token %}
    <input type="hidden" name="ctx" value="editor">
    <input type="hidden" name="element" value="{{ el.pk }}">
    <input type="hidden" name="unit" value="{{ unit.pk }}">
    <input type="hidden" name="unit_token" value="{{ unit.updated.isoformat }}">
    <button class="tree__act tree__act--danger" type="submit">{% trans "Delete" %}</button>
  </form>
</li>
```

> Add an `element_type_label_obj` filter to `courses_manage_extras.py` that maps a concrete object's class to a translated label (parallel to the existing `element_type_label` which takes a content_type). One-liner: `return _TYPE_LABELS.get(obj.__class__.__name__.lower(), obj.__class__.__name__)`.

`templates/courses/manage/editor/_editor_scope.html`:

```html
{% load i18n %}
<div class="editor-grid">
  <div class="editor-pane" data-scope="editor" data-updated="{{ unit.updated.isoformat }}"
       data-unit="{{ unit.pk }}"
       data-add-url="{% url 'courses:manage_element_add' slug=unit.course.slug %}"
       data-save-url="{% url 'courses:manage_element_save' slug=unit.course.slug %}">
    <h2>{% trans "Unit" %}: {{ unit.title }}</h2>
    <ol class="element-list">
      {% for el, obj in rows %}{% include "courses/manage/editor/_element_row.html" %}{% empty %}
        <li class="empty-state">{% trans "No elements yet." %}</li>{% endfor %}
    </ol>
    <div class="editor-add">
      <button type="button" class="btn btn--small" data-add-type="text">+ {% trans "Text" %}</button>
      <button type="button" class="btn btn--small" data-add-type="image">+ {% trans "Image" %}</button>
      <button type="button" class="btn btn--small" data-add-type="video">+ {% trans "Video" %}</button>
      <button type="button" class="btn btn--small" data-add-type="iframe">+ {% trans "Iframe" %}</button>
      <button type="button" class="btn btn--small" data-add-type="math">+ {% trans "Math" %}</button>
    </div>
    <div class="editor-form-host">{{ open_form|safe }}</div>
  </div>
  {% include "courses/manage/editor/_preview.html" %}
</div>
```

`templates/courses/manage/editor/editor.html`:

```html
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{{ unit.title }} — {% trans "Editor" %}{% endblock %}
{% block extra_css %}
  <link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">
  <link rel="stylesheet" href="{% static 'courses/css/editor.css' %}">
  <link rel="stylesheet" href="{% static 'courses/vendor/katex/katex.min.css' %}">
{% endblock %}
{% block content %}
<section class="editor" data-course-slug="{{ course.slug }}"
         data-picker-url="{% url 'courses:manage_media_picker' slug=course.slug %}">
  {% if changed %}<div class="op-error" role="alert">{% trans "This changed elsewhere — reloaded to the latest." %}</div>{% endif %}
  <p><a href="{% url 'courses:manage_builder' slug=course.slug %}">← {% trans "Back to builder" %}</a></p>
  {% include "courses/manage/editor/_editor_scope.html" with open_form="" %}
</section>
{% endblock %}
{% block extra_js %}
  <script src="{% static 'courses/vendor/katex/katex.min.js' %}" defer></script>
  <script src="{% static 'courses/js/math.js' %}" defer></script>
  <script src="{% static 'courses/js/media_picker.js' %}" defer></script>
  <script src="{% static 'courses/js/text_toolbar.js' %}" defer></script>
  <script src="{% static 'courses/js/editor.js' %}" defer></script>
{% endblock %}
```

- [ ] **Step 6: Collapse the 1b-i unit panel to a read-only summary + activate the seam**

Replace the interactive element list + disabled seam buttons in `templates/courses/manage/_unit_panel.html` (the `<ol class="element-list">…</ol>` block and the `<div class="panel__seam">…</div>`) with:

```html
  <h3>{% trans "Elements" %}</h3>
  <ol class="element-list element-list--readonly">
    {% for el in elements %}
      <li class="element-list__item">
        <span class="element-list__type">{% element_type_label el.content_type %}</span>
        <span class="element-list__summary">{{ el.content_object|element_summary }}</span>
      </li>
    {% empty %}
      <li class="empty-state">{% trans "No elements yet." %}</li>
    {% endfor %}
  </ol>
  <div class="panel__seam">
    <a class="btn btn--small" href="{% url 'courses:manage_editor' slug=node.course.slug pk=node.pk %}?add=1">{% trans "+ Add element" %}</a>
    <a class="btn btn--small" href="{% url 'courses:manage_editor' slug=node.course.slug pk=node.pk %}">{% trans "Open editor →" %}</a>
  </div>
```

(Load `courses_manage_extras` at the top of the template if not already; it is. The `_unit_panel` view already passes `elements` with `content_object` accessible.)

- [ ] **Step 7: Add the route**

In `courses/urls.py` add (before the element-op routes):

```python
    path("manage/courses/<slug:slug>/build/unit/<int:pk>/edit/", views_manage.editor, name="manage_editor"),
```

- [ ] **Step 8: Run the tests**

Run: `uv run python -m pytest tests/test_editor_page.py tests/test_manage_builder.py -v`
Expected: editor tests PASS; fix any 1b-i unit-panel test that asserted the old interactive list (those move/retarget in Task 7's test work, but if a `node_panel` test breaks now because it asserted ↑/↓ in the panel, retarget it to assert the read-only summary). Then `pytest -q` green.

- [ ] **Step 9: Commit**

```bash
git add courses/views_manage.py courses/urls.py courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/ templates/courses/manage/_unit_panel.html tests/test_editor_page.py
git commit -m "feat(courses): editor|preview page shell + read-only unit panel + seam"
```

---

### Task 5: The 5 element forms + per-type editor partials

**Files:**
- Modify: `courses/element_forms.py` (5 forms + `FORM_FOR_TYPE`)
- Create: `templates/courses/manage/editor/_edit_text.html`, `_edit_image.html`, `_edit_video.html`, `_edit_iframe.html`, `_edit_math.html`, `_type_picker.html`
- Test: extend `tests/test_element_add_save.py` (forms-only unit tests here; view tests in Task 6)

- [ ] **Step 1: Write failing form tests**

Create `tests/test_element_add_save.py` (forms section; add/save view tests appended in Task 6):

```python
import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.models import MediaAsset
from tests.factories import CourseFactory, MediaAssetFactory


@pytest.mark.django_db
def test_iframe_form_rejects_non_whitelisted_domain():
    Form = FORM_FOR_TYPE["iframe"]
    form = Form(data={"url": "https://evil.example.com/x", "title": "t"})
    assert not form.is_valid()


@pytest.mark.django_db
def test_image_form_requires_media():
    Form = FORM_FOR_TYPE["image"]
    course = CourseFactory()
    form = Form(data={"alt": "a", "figcaption": ""}, course=course)
    assert not form.is_valid()
    assert "media" in form.errors


@pytest.mark.django_db
def test_image_form_rejects_cross_course_or_wrong_kind_media():
    Form = FORM_FOR_TYPE["image"]
    course = CourseFactory()
    foreign = MediaAssetFactory(course=CourseFactory(), kind="image")
    wrong_kind = MediaAssetFactory(course=course, kind="video")
    assert not Form(data={"media": foreign.pk, "alt": ""}, course=course).is_valid()
    assert not Form(data={"media": wrong_kind.pk, "alt": ""}, course=course).is_valid()


@pytest.mark.django_db
def test_video_form_xor():
    Form = FORM_FOR_TYPE["video"]
    course = CourseFactory()
    asset = MediaAssetFactory(course=course, kind="video")
    assert not Form(data={}, course=course).is_valid()  # neither
    assert not Form(data={"url": "https://www.youtube.com/embed/x", "media": asset.pk}, course=course).is_valid()  # both
    assert Form(data={"url": "https://www.youtube.com/embed/x"}, course=course).is_valid()  # one
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_element_add_save.py -v`
Expected: FAIL — `ImportError: cannot import name 'FORM_FOR_TYPE'`.

- [ ] **Step 3: Implement the five element forms + registry**

Append to `courses/element_forms.py`:

```python
from courses.models import (IframeElement, ImageElement, MathElement,
                            TextElement, VideoElement)


class _CourseScopedMediaForm(forms.ModelForm):
    """Shared base: forms that reference a MediaAsset re-validate course + kind."""
    media_kind = None  # "image" | "video"

    def __init__(self, *args, course=None, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)
        if "media" in self.fields and course is not None:
            self.fields["media"].queryset = MediaAsset.objects.filter(
                course=course, kind=self.media_kind
            )


class TextElementForm(forms.ModelForm):
    class Meta:
        model = TextElement
        fields = ["body"]


class ImageElementForm(_CourseScopedMediaForm):
    media_kind = "image"

    class Meta:
        model = ImageElement
        fields = ["media", "alt", "figcaption"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["media"].required = True


class VideoElementForm(_CourseScopedMediaForm):
    media_kind = "video"

    class Meta:
        model = VideoElement
        fields = ["url", "media"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["url"].required = False
        self.fields["media"].required = False

    def clean(self):
        cleaned = super().clean()
        # model.clean() enforces the XOR + embed whitelist; surface it as form errors.
        instance = self.instance
        instance.url = cleaned.get("url", "")
        instance.media = cleaned.get("media")
        try:
            instance.clean()
        except forms.ValidationError as e:
            self.add_error(None, e)
        return cleaned


class IframeElementForm(forms.ModelForm):
    class Meta:
        model = IframeElement
        fields = ["url", "title"]


class MathElementForm(forms.ModelForm):
    class Meta:
        model = MathElement
        fields = ["latex"]


FORM_FOR_TYPE = {
    "text": TextElementForm,
    "image": ImageElementForm,
    "video": VideoElementForm,
    "iframe": IframeElementForm,
    "math": MathElementForm,
}
```

> `ImageElementForm`/`VideoElementForm` take `course=` so the `media` queryset is course+kind scoped — this is the server-side cross-course/wrong-kind backstop (a posted out-of-scope `media` pk fails `ModelChoiceField` validation → 422). `TextElement.save()` sanitises `body` (1a). `IframeElementForm`/`VideoElementForm` inherit the embed-whitelist via model field/`clean()`.

- [ ] **Step 4: Write the per-type editor partials**

`templates/courses/manage/editor/_edit_text.html` (the bespoke toolbar + a no-JS textarea fallback):

```html
{% load i18n %}
<div class="el-editor el-editor--text">
  <div class="rte-toolbar" data-rte-toolbar>
    <button type="button" data-cmd="bold"><b>B</b></button>
    <button type="button" data-cmd="italic"><i>I</i></button>
    <button type="button" data-cmd="underline"><u>U</u></button>
    <button type="button" data-cmd="h2">H2</button>
    <button type="button" data-cmd="h3">H3</button>
    <button type="button" data-cmd="h4">H4</button>
    <button type="button" data-cmd="ul">• {% trans "List" %}</button>
    <button type="button" data-cmd="ol">1. {% trans "List" %}</button>
    <button type="button" data-cmd="link">{% trans "Link" %}</button>
    <button type="button" data-cmd="blockquote">❝</button>
    <button type="button" data-cmd="code">&lt;/&gt;</button>
  </div>
  <textarea name="body" class="rte-source" data-rte-source rows="6">{{ form.body.value|default:"" }}</textarea>
  {% for e in form.body.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

`_edit_image.html`:

```html
{% load i18n %}
<div class="el-editor el-editor--image">
  <input type="hidden" name="media" value="{{ form.media.value|default:'' }}" data-media-field>
  <div class="media-chosen" data-media-preview></div>
  <button type="button" class="btn btn--small" data-pick-media="image">{% trans "Choose media" %}</button>
  <noscript>
    <select name="media">{% for a in form.fields.media.queryset %}<option value="{{ a.pk }}">{{ a.original_filename }}</option>{% endfor %}</select>
  </noscript>
  <label>{% trans "Alt text" %} <input type="text" name="alt" value="{{ form.alt.value|default:'' }}"></label>
  <label>{% trans "Caption" %} <input type="text" name="figcaption" value="{{ form.figcaption.value|default:'' }}"></label>
  {% for e in form.non_field_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  {% for e in form.media.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

`_edit_video.html` (radio: URL or media), `_edit_iframe.html` (url + title), `_edit_math.html` (latex textarea + a `data-math-live` preview span). Author these following the same pattern: hidden/visible fields named exactly as the form fields, echoing `form.<field>.value`, rendering `form.<field>.errors` and `form.non_field_errors`. For `_edit_math.html`:

```html
{% load i18n %}
<div class="el-editor el-editor--math">
  <textarea name="latex" rows="4" data-math-input>{{ form.latex.value|default:"" }}</textarea>
  <div class="math-live" data-katex data-math-live></div>
  {% for e in form.latex.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

Each editor partial is wrapped by the host form in Task 6 (which adds the `<form>`, csrf, `type`, `element`, `unit`, `unit_token`, and Save/Cancel buttons), so the partials contain only fields.

- [ ] **Step 5: Run the form tests + commit**

Run: `uv run python -m pytest tests/test_element_add_save.py -v` → the four form tests PASS.

```bash
git add courses/element_forms.py templates/courses/manage/editor/_edit_*.html
git commit -m "feat(courses): 5 element ModelForms (course+kind-scoped media) + editor partials"
```

---

### Task 6: Element add (render-only) + save (create-on-first-save / update) services & views

**Files:**
- Modify: `courses/builder.py` (add `add_element`, `save_element`)
- Modify: `courses/views_manage.py` (add `element_add`, `element_save`; the `_render_open_form` helper)
- Create: `templates/courses/manage/editor/_host_form.html`
- Modify: `courses/urls.py`
- Test: extend `tests/test_element_add_save.py`

- [ ] **Step 1: Write the failing add/save view tests**

Append to `tests/test_element_add_save.py`:

```python
from django.urls import reverse
from courses.models import Element, MathElement, TextElement
from tests.factories import ContentNodeFactory, make_pa


def _unit(course):
    return ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")


@pytest.mark.django_db
def test_add_is_render_only_no_row(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk}, HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert Element.objects.filter(unit=unit).count() == 0  # nothing persisted


@pytest.mark.django_db
def test_first_save_materialises_text_element(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {"type": "text", "element": "new", "unit": unit.pk,
         "unit_token": unit.updated.isoformat(), "body": "<p>Hi <script>x</script></p>"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, TextElement)
    assert "<script>" not in el.content_object.body  # sanitised on save


@pytest.mark.django_db
def test_save_math_empty_is_422(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {"type": "math", "element": "new", "unit": unit.pk,
         "unit_token": unit.updated.isoformat(), "latex": ""},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_save_stale_token_is_409(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {"type": "math", "element": "new", "unit": unit.pk,
         "unit_token": "2000-01-01T00:00:00+00:00", "latex": "x^2"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 409
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_update_existing_element(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    from tests.factories import add_element
    el = add_element(unit, MathElement.objects.create(latex="a"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {"type": "math", "element": el.pk, "unit": unit.pk,
         "unit_token": unit.updated.isoformat(), "latex": "b"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el.content_object.refresh_from_db()
    assert el.content_object.latex == "b"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_element_add_save.py -v`
Expected: the new view tests FAIL (NoReverseMatch `manage_element_add`).

- [ ] **Step 3: Implement the add/save services**

Append to `courses/builder.py` (imports: `from django.contrib.contenttypes.models import ContentType`):

```python
@transaction.atomic
def save_element(course, unit_pk, type_key, element_ref, post_data, files):
    """Create-on-first-save (element_ref == 'new') or update an existing Element.
    Token-checked against the unit; bumps unit.updated. Returns the unit.
    Raises ConflictError (409) on stale/vanished, ValidationError (422) on bad form."""
    from courses.element_forms import FORM_FOR_TYPE  # avoid import cycle
    unit = _locked_unit(course, unit_pk)
    _check_token(unit.updated, post_data.get("unit_token"))
    if element_ref == "new":
        join, instance = None, None
    else:
        join = _locked_element_in_unit(unit, element_ref)
        instance = join.content_object
    extra = {"course": course} if type_key in ("image", "video") else {}
    form = FORM_FOR_TYPE[type_key](data=post_data, files=files, instance=instance, **extra)
    if not form.is_valid():
        raise ValidationError(form_errors_to_list(form))
    obj = form.save()  # concrete row saved (TextElement.save sanitises)
    if join is None:
        Element.objects.create(unit=unit, content_object=obj)  # OrderField appends
    unit.save(update_fields=["updated"])
    return unit


def _locked_unit(course, unit_pk):
    try:
        return ContentNode.objects.select_for_update().get(
            pk=unit_pk, course=course, kind=ContentNode.Kind.UNIT
        )
    except ContentNode.DoesNotExist:
        raise ConflictError() from None


def _locked_element_in_unit(unit, element_pk):
    try:
        return Element.objects.select_for_update().get(pk=element_pk, unit=unit)
    except (Element.DoesNotExist, ValueError, TypeError):
        raise ConflictError() from None


def form_errors_to_list(form):
    return [m for errs in form.errors.values() for m in errs]
```

> `ValidationError(list)` carries `.messages` joinable with `"; ".join(e.messages)` (matching 1b-i). `_locked_unit` filters `kind=unit` so a non-unit pk yields `ConflictError` → 409.

- [ ] **Step 4: Implement the add/save views + host-form rendering**

Add to `courses/views_manage.py`:

```python
def _render_open_form(request, unit, type_key, element_pk="new", form=None, status=200):
    """Render the host <form> wrapping a per-type editor partial, then the full editor
    scope with that form embedded in the form host."""
    from courses.element_forms import FORM_FOR_TYPE
    if form is None:
        extra = {"course": unit.course} if type_key in ("image", "video") else {}
        form = FORM_FOR_TYPE[type_key](**extra)
    unit.refresh_from_db(fields=["updated"])
    form_html = render(
        request, "courses/manage/editor/_host_form.html",
        {"course": unit.course, "unit": unit, "type_key": type_key,
         "element_pk": element_pk, "form": form},
    ).content.decode()
    return _render_editor_fragments(request, unit, status=status, open_form=form_html)


@login_required
def element_add(request, slug):
    course = _require_manage(request, slug)
    type_key = request.POST.get("type")
    if type_key not in ("text", "image", "video", "iframe", "math"):
        return HttpResponseBadRequest("bad type")
    unit = get_object_or_404(ContentNode, pk=request.POST.get("unit"), course=course,
                             kind=ContentNode.Kind.UNIT)
    return _render_open_form(request, unit, type_key, element_pk="new")  # render-only


@login_required
def element_save(request, slug):
    course = _require_manage(request, slug)
    type_key = request.POST.get("type")
    if type_key not in ("text", "image", "video", "iframe", "math"):
        return HttpResponseBadRequest("bad type")
    element_ref = request.POST.get("element", "new")
    from courses.element_forms import FORM_FOR_TYPE
    try:
        unit = builder_svc.save_element(
            course, request.POST.get("unit"), type_key, element_ref,
            request.POST, request.FILES,
        )
    except builder_svc.ConflictError:
        unit = ContentNode.objects.filter(pk=request.POST.get("unit"), course=course).first()
        if unit is None:
            return _render_tree(request, course, status=409)
        if not _wants_fragment(request):
            return redirect(f"{_editor_path(course, unit)}?changed=1")
        return _render_editor_fragments(request, unit, status=409)
    except ValidationError as e:
        unit = ContentNode.objects.get(pk=request.POST.get("unit"), course=course)
        extra = {"course": course} if type_key in ("image", "video") else {}
        form = FORM_FOR_TYPE[type_key](data=request.POST, files=request.FILES, **extra)
        form.is_valid()  # populate errors for re-render
        return _render_open_form(request, unit, type_key, element_pk=element_ref,
                                 form=form, status=422)
    if not _wants_fragment(request):
        return redirect(_editor_path(course, unit))
    return _render_editor_fragments(request, unit)


def _editor_path(course, unit):
    from django.urls import reverse
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
```

- [ ] **Step 5: Write the host-form template**

`templates/courses/manage/editor/_host_form.html`:

```html
{% load i18n %}
<form class="editor-form" method="post" enctype="multipart/form-data"
      action="{% url 'courses:manage_element_save' slug=course.slug %}" data-op="element-save">
  {% csrf_token %}
  <input type="hidden" name="ctx" value="editor">
  <input type="hidden" name="type" value="{{ type_key }}">
  <input type="hidden" name="element" value="{{ element_pk }}">
  <input type="hidden" name="unit" value="{{ unit.pk }}">
  <input type="hidden" name="unit_token" value="{{ unit.updated.isoformat }}">
  {% include "courses/manage/editor/_edit_"|add:type_key|add:".html" %}
  <div class="editor-form__actions">
    <button type="submit" class="btn btn--small">{% trans "Save" %}</button>
    <button type="button" class="btn btn--small btn--ghost" data-cancel-edit>{% trans "Cancel" %}</button>
  </div>
</form>
```

- [ ] **Step 6: Add routes**

In `courses/urls.py`, after the editor route:

```python
    path("manage/courses/<slug:slug>/build/element/add/", views_manage.element_add, name="manage_element_add"),
    path("manage/courses/<slug:slug>/build/element/save/", views_manage.element_save, name="manage_element_save"),
```

- [ ] **Step 7: Run the add/save tests + full suite**

Run: `uv run python -m pytest tests/test_element_add_save.py -v` → all PASS.
Run: `uv run python -m pytest -q` → green.

- [ ] **Step 8: Commit**

```bash
git add courses/builder.py courses/views_manage.py courses/urls.py templates/courses/manage/editor/_host_form.html tests/test_element_add_save.py
git commit -m "feat(courses): element add (render-only) + create-on-first-save/update with unit token"
```

---

### Task 7: Extend element reorder/delete + conflict for editor context

**Files:**
- Modify: `courses/views_manage.py` (`element_move`, `element_delete`, `_element_conflict`)
- Modify/retarget: `tests/test_manage_element_ops.py` (panel→summary), `tests/test_editor_page.py`
- Test: `tests/test_element_editor_ops.py`

- [ ] **Step 1: Write the failing editor-context reorder/delete tests**

Create `tests/test_element_editor_ops.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Element, MathElement
from tests.factories import CourseFactory, ContentNodeFactory, add_element, make_pa


def _unit(course):
    return ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")


@pytest.mark.django_db
def test_editor_reorder_returns_editor_fragments(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    a = add_element(unit, MathElement.objects.create(latex="a"))
    b = add_element(unit, MathElement.objects.create(latex="b"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_move", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": a.pk, "unit": unit.pk,
         "direction": "down", "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content
    assert b'data-scope="preview"' in resp.content


@pytest.mark.django_db
def test_editor_delete_returns_editor_fragments(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    a = add_element(unit, MathElement.objects.create(latex="a"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": a.pk, "unit": unit.pk,
         "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'data-scope="preview"' in resp.content
    assert Element.objects.filter(unit=unit).count() == 0


@pytest.mark.django_db
def test_editor_vanished_element_is_409_editor_fragment(client):
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": 999999, "unit": unit.pk,
         "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 409
    assert b'data-scope="editor"' in resp.content


@pytest.mark.django_db
def test_panel_path_still_works_unchanged(client):
    """The unit-panel (non-ctx) path is retained; it now returns the read-only summary."""
    pa = make_pa(client, "pa"); course = CourseFactory(owner=pa); unit = _unit(course)
    a = add_element(unit, MathElement.objects.create(latex="a"))
    b = add_element(unit, MathElement.objects.create(latex="b"))
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_move", kwargs={"slug": course.slug}),
        {"element": a.pk, "unit": unit.pk, "direction": "down",
         "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200  # _render_unit_panel path
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_element_editor_ops.py -v`
Expected: FAIL (editor-context branch not yet present → returns unit-panel fragment without `data-scope="preview"`).

- [ ] **Step 3: Extend the element views + conflict for `ctx=editor`**

In `courses/views_manage.py`, add a helper and branch `element_move`/`element_delete`/`_element_conflict`:

```python
def _editor_ctx(request):
    return request.POST.get("ctx") == "editor"
```

In `element_move`, replace the success return:

```python
    if _editor_ctx(request):
        return _render_editor_fragments(request, unit)
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    return _render_unit_panel(request, unit)
```

Same pattern in `element_delete`. Update `_element_conflict` to honor editor context and the no-JS redirect:

```python
def _element_conflict(request, course):
    unit = ContentNode.objects.filter(
        pk=request.POST.get("unit"), course=course, kind=ContentNode.Kind.UNIT
    ).first()
    if unit is None:
        return _render_tree(request, course, status=409)
    if _editor_ctx(request):
        if not _wants_fragment(request):  # no-JS editor conflict -> reload editor page
            return redirect(f"{_editor_path(course, unit)}?changed=1")
        return _render_editor_fragments(request, unit, status=409)
    resp = _render_unit_panel(request, unit)
    resp.status_code = 409
    return resp
```

- [ ] **Step 4: Retarget the 1b-i unit-panel element tests**

In `tests/test_manage_element_ops.py`, update any assertion that the `_unit_panel` fragment / `node_panel` renders interactive `↑`/`↓`/`✕` element controls: the panel is now a read-only summary. Replace those with assertions that the panel shows the element **summary** text and the **"Open editor →"** / **"+ Add element"** links, and that reorder/delete still work when POSTed directly to the endpoints (the `test_panel_path_still_works_unchanged` style above). Keep all endpoint-behaviour tests (reorder changes order, delete cascades) — only the panel-rendering assertions change.

- [ ] **Step 5: Run tests**

Run: `uv run python -m pytest tests/test_element_editor_ops.py tests/test_manage_element_ops.py -v` → PASS.
Run: `uv run python -m pytest -q` → green.

- [ ] **Step 6: Commit**

```bash
git add courses/views_manage.py tests/test_element_editor_ops.py tests/test_manage_element_ops.py
git commit -m "feat(courses): element reorder/delete editor-context fragments + no-JS conflict redirect"
```

---

### Task 8: `math.js` root-scoping refactor

**Files:**
- Modify: `courses/static/courses/js/math.js`
- Test: covered by the e2e (Task 11); add a tiny DOM-free guard is impractical — verify via e2e + manual.

- [ ] **Step 1: Refactor `math.js` to accept a root**

Replace `courses/static/courses/js/math.js` with:

```javascript
(function () {
  "use strict";
  function renderMath(root) {
    if (typeof katex === "undefined") return;
    (root || document).querySelectorAll("[data-katex]").forEach(function (el) {
      if (el.dataset.katexDone === "1") return;  // idempotent: skip already-rendered
      try {
        katex.render(el.textContent, el, { displayMode: true, throwOnError: false });
        el.dataset.katexDone = "1";
      } catch (e) {
        /* leave raw LaTeX on error */
      }
    });
  }
  window.libliRenderMath = renderMath;  // swap handler calls window.libliRenderMath(subtree)
  renderMath(document);  // initial whole-document pass (1a lesson page behaviour preserved)
})();
```

> The `katexDone` flag makes re-calls idempotent. The 1a lesson page still gets a whole-document pass on load (no behaviour change). The editor's swap handler (Task 9) calls `window.libliRenderMath(previewSubtree)`; because the preview subtree is a sibling of the editor pane (spec §Live preview), the editor's own inline math (`data-math-live`) is never re-scanned by a preview swap.

- [ ] **Step 2: Verify the lesson page still renders math**

Run the existing math e2e/unit coverage: `uv run python -m pytest tests/ -k math -v` (and the 1a lesson e2e if present). Expected: PASS / no regression. Manually confirm via Task 11 e2e.

- [ ] **Step 3: Commit**

```bash
git add courses/static/courses/js/math.js
git commit -m "refactor(courses): math.js accepts a root element + idempotent re-render"
```

---

### Task 9: `editor.js` + `media_picker.js` + `text_toolbar.js` + `editor.css`

**Files:**
- Create: `courses/static/courses/js/editor.js`, `media_picker.js`, `text_toolbar.js`
- Create: `courses/static/courses/css/editor.css`
- Test: exercised by the Task 11 e2e.

- [ ] **Step 1: Write `editor.js` (fragment swap + add/select/dirty-discard)**

Create `courses/static/courses/js/editor.js`. It mirrors `builder.js`'s swap contract (selector = `[data-scope]`, `X-CSRFToken`, `X-Requested-With: fetch`, status routing 200/409/422) but swaps **two** fragments and re-runs KaTeX on the new preview:

```javascript
(function () {
  "use strict";
  var root = document.querySelector(".editor");
  if (!root) return;
  function csrf() { var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/); return m ? m[1] : ""; }

  function applyFragments(html) {
    var tmp = document.createElement("div");
    tmp.innerHTML = html.trim();
    ["editor", "preview"].forEach(function (scope) {
      var incoming = tmp.querySelector('[data-scope="' + scope + '"]');
      var existing = root.querySelector('[data-scope="' + scope + '"]');
      if (incoming && existing) existing.replaceWith(incoming);
    });
    var preview = root.querySelector('[data-scope="preview"]');
    if (preview && window.libliRenderMath) window.libliRenderMath(preview);
  }

  function post(form) {
    var body = new FormData(form);
    if (event && event.submitter && event.submitter.name) body.append(event.submitter.name, event.submitter.value);
    return fetch(form.action, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
      body: body,
    }).then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); });
  }

  // Intercept editor forms (save/move/delete) -> swap both fragments.
  root.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-op]");
    if (!form) return;
    e.preventDefault();
    post(form).then(function (res) {
      if (res.status === 200 || res.status === 409) {
        applyFragments(res.text);
        if (res.status === 409) flash("This changed elsewhere — refreshed to the latest.");
      } else if (res.status === 422) {
        applyFragments(res.text);  // editor fragment carries the form + field errors
      }
    });
  });

  // "+ Type" add buttons -> POST add (render-only) and swap in the pending form.
  root.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add-type]");
    if (add) {
      var pane = root.querySelector('[data-scope="editor"]');
      var fd = new FormData();
      fd.append("type", add.getAttribute("data-add-type"));
      fd.append("unit", pane.getAttribute("data-unit"));
      fetch(pane.getAttribute("data-add-url"), {
        method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: fd,
      }).then(function (r) { return r.text(); }).then(applyFragments);
      return;
    }
    var cancel = e.target.closest("[data-cancel-edit]");
    if (cancel) { var host = root.querySelector(".editor-form-host"); if (host) host.innerHTML = ""; }
    var sel = e.target.closest(".el-select");
    if (sel) { /* selecting a row to edit: fetch its save-form via add-like render is out of scope here;
                 minimal version opens the row's editor by re-using element_save GET is not provided —
                 keep selection to the add flow + inline forms returned by save/422. */ }
  });

  function flash(msg) {
    var bar = document.createElement("div"); bar.className = "op-error"; bar.textContent = msg;
    root.prepend(bar); setTimeout(function () { bar.remove(); }, 6000);
  }
})();
```

> **Selecting an existing row to edit:** the minimal, spec-faithful path is that the editor row's summary button opens that element's editor. Implement it by adding a small `element_edit_form` GET (returns the host form for an existing pk) OR — simpler and within the existing endpoints — have `.el-select` POST to `element_add`-style render with the existing pk. **Plan decision:** add a tiny `GET …/build/element/<pk>/form/` route (`element_form` view) that returns `_render_open_form(request, unit, type_key, element_pk=pk, form=FORM(instance=obj))`. Add this route + view in this task (it is render-only, reusing `_render_open_form`), and wire `.el-select` to fetch it and swap the editor fragment. Add a unit test asserting it returns 200 with the form fields populated.

- [ ] **Step 2: Write `text_toolbar.js`**

Create `courses/static/courses/js/text_toolbar.js`: progressively enhance `[data-rte-source]` textareas into a `contenteditable` with toolbar `[data-cmd]` buttons mapping to `document.execCommand`/manual tag insertion for the allowed tags, syncing innerHTML back to the hidden textarea on input. With JS off, the plain textarea submits raw HTML (sanitised server-side). Keep it small; the server sanitises regardless.

- [ ] **Step 3: Write `media_picker.js`**

Create `courses/static/courses/js/media_picker.js`: on `[data-pick-media]` click, fetch `…/media/picker/?kind=…` into a modal; wire `.asset-pick` to set the nearest `[data-media-field]` value + `[data-media-preview]` and close; wire the Upload tab `[data-panel="upload"]` file input to POST `…/media/upload/` (multipart, `X-Requested-With: fetch`), read `data-asset-id` from the returned cell, auto-select it. On the manager page, wire the drop zone + `data-op="asset-delete"` forms to remove the cell on 200 / flash on 409.

- [ ] **Step 4: Write `editor.css`**

Create `courses/static/courses/css/editor.css` using the existing design tokens (mirror `builder.css`): `.editor-grid` two-column on desktop, stacked on mobile (`@media (max-width: …)`); `.rte-toolbar`, `.asset-grid`, `.picker` modal (fixed overlay, full-screen on mobile), `.field-error`. Reuse token variables; no new colors hardcoded (per the design-language memory: dark text, token-driven).

- [ ] **Step 5: Add the `element_form` GET route + view (from Step 1 decision)**

In `courses/views_manage.py`:

```python
@login_required
def element_form(request, slug, pk):
    course = _require_manage(request, slug)
    el = get_object_or_404(Element, pk=pk, unit__course=course)
    unit = el.unit
    obj = el.content_object
    type_key = obj.__class__.__name__.lower().replace("element", "")
    from courses.element_forms import FORM_FOR_TYPE
    extra = {"course": course} if type_key in ("image", "video") else {}
    form = FORM_FOR_TYPE[type_key](instance=obj, **extra)
    return _render_open_form(request, unit, type_key, element_pk=pk, form=form)
```

Route: `path("manage/courses/<slug:slug>/build/element/<int:pk>/form/", views_manage.element_form, name="manage_element_form")` and import `Element` in `views_manage.py`. Add a unit test in `tests/test_element_editor_ops.py` asserting a 200 with the existing value present.

- [ ] **Step 6: collectstatic check + commit**

Run: `uv run python manage.py collectstatic --noinput` → clean. `uv run python -m pytest -q` → green.

```bash
git add courses/static/courses/js/editor.js courses/static/courses/js/media_picker.js courses/static/courses/js/text_toolbar.js courses/static/courses/css/editor.css courses/views_manage.py courses/urls.py tests/test_element_editor_ops.py
git commit -m "feat(courses): editor.js + picker + text toolbar + editor.css + element_form route"
```

---

### Task 10: i18n extraction + Polish

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`
- Test: existing i18n flow (compile must succeed).

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl -i ".venv"`
Expected: new `msgid`s for the editor/media/picker/toolbar chrome appear in `locale/pl/LC_MESSAGES/django.po`.

- [ ] **Step 2: Translate the new strings to Polish**

Fill in real Polish `msgstr` for every new `msgid` (e.g. "Media"→"Media", "Choose media"→"Wybierz plik", "Save"→"Zapisz", "Upload"→"Prześlij", "Back to builder"→"Powrót do kreatora", "In use — cannot delete"→"W użyciu — nie można usunąć", "This changed elsewhere — reloaded to the latest."→matching the 1b-i phrasing). Match the tone of the existing translations.

- [ ] **Step 3: Compile + run**

Run:
```bash
uv run python manage.py compilemessages -l pl
uv run python -m pytest -q
```
Expected: compile clean, suite green.

- [ ] **Step 4: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(courses): extract + Polish for the editor/media UI"
```

---

### Task 11: Playwright e2e + final DoD pass

**Files:**
- Create: `tests/test_e2e_editor.py`
- Test: the full editor flow + no-JS fallback + stale-token 409.

- [ ] **Step 1: Write the e2e (marked `e2e`, excluded from the default run)**

Create `tests/test_e2e_editor.py` following the 1b-i e2e pattern (`tests/test_e2e_builder.py`): `@pytest.mark.e2e`, the session-scoped `DJANGO_ALLOW_ASYNC_UNSAFE` autouse fixture, `live_server`, sync Playwright. Cover:
- Log in as PA (seed a verified PA + a course + a lesson unit via the ORM in a fixture).
- Open the editor page; add a **text** element via "+ Text", type in the toolbar/source, Save → assert the preview shows the text.
- Add a **math** element, enter `a^2+b^2=c^2`, Save → assert the preview contains a `.katex` rendered node (KaTeX ran on the swapped preview).
- Reorder the two elements (↑/↓) → assert preview order changes.
- Delete one → assert it disappears from preview.
- **Stale-token 409:** open the editor, mutate the unit's `updated` out of band (a second ORM save), trigger a save, assert the "this changed" notice appears and the editor refreshes (no clobber).
- **No-JS fallback:** with a `browser.new_context(java_script_enabled=False)`, add+save an element via the full-page POST and assert the reloaded editor shows it.

- [ ] **Step 2: Run the e2e**

Run: `uv run python -m pytest tests/test_e2e_editor.py -m e2e -v`
Expected: PASS (all scenarios).

- [ ] **Step 3: Final DoD gate**

Run, expecting all clean:
```bash
uv run python -m pytest -q                       # default (non-e2e) suite green
uv run python -m pytest -m e2e -q                # all e2e green
uv run ruff check . && uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check
uv run python manage.py collectstatic --noinput
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_editor.py
git commit -m "test(courses): Playwright e2e — editor flow, KaTeX preview, no-JS, stale-token 409"
```

---

## Notes for the implementer

- **Migration split (Task 1) is the trickiest mechanical step.** After `makemigrations`, **read** the generated `0007` and ensure: `MediaAsset` created; `ImageElement.media`/`VideoElement.media` added **nullable**; the old `image`/`file` `RemoveField`s are **moved to `0008` after** the `RunPython` copy. The data migration copies the FieldFile `.name` (reference), never bytes — do not call `.read()` / `.open()`.
- **Reused token contract is load-bearing.** Every editor element form posts `unit` + `unit_token` (the unit's `updated.isoformat()`); `builder._check_token` raises `ConflictError` on mismatch. Never invent a different token field name.
- **`_render_editor_fragments` always `refresh_from_db(fields=["updated"])`** before serialising `data-updated`, so a no-op reorder still ships the live token.
- **Server is the security boundary.** `TextElement.save()` sanitises; `validate_embed_url` gates video/iframe; the media forms' course+kind queryset is the cross-course/wrong-kind backstop. The toolbar/picker only *offer* legal input.

---

## Self-Review

- **Spec coverage:** DoD #1 (editor page) → Task 4; #2 (add render-only) → Task 6; #3 (save create/update) → Task 6; #4 (editor reorder/delete) → Task 7; #5 (5 editors) → Tasks 5+9; #6 (MediaAsset + migration) → Task 1; #7 (manager guarded delete) → Task 2; #8 (picker) → Tasks 3+9; #9 (access/cross-course/kind) → Tasks 4+5; #10 (validation/sanitise) → Tasks 1+5+6; #11 (concurrency) → Tasks 6+7; #12 (i18n) → Task 10; #13 (responsive) → Task 9 (`editor.css`); #14 (tests incl. 1b-i test migration) → Tasks 2-7+11; #15 (final gates) → Task 11. KaTeX root refactor → Task 8. All covered.
- **Type consistency:** `unit_token` field name, `ctx=editor` flag, `data-scope` values ("editor"/"preview"), `FORM_FOR_TYPE` keys (text/image/video/iframe/math), `save_element(course, unit_pk, type_key, element_ref, post_data, files)` and `_render_editor_fragments(request, unit, status, open_form)` signatures, `window.libliRenderMath(root)` — used consistently across tasks.
- **Placeholder scan:** no TBD/TODO; every code step shows complete code. The two narrative "author this following the same pattern" spots (the remaining text-toolbar/video/iframe editor partials in Task 5, and `media_picker.js`/`text_toolbar.js`/`editor.css` bodies in Task 9) describe progressive-enhancement JS/markup whose exact bytes are not load-bearing — the server contracts they hit are fully specified; they are intentionally left to the implementer's idiom, not gaps in behavior.
