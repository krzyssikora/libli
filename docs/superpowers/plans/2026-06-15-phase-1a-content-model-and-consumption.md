# Phase 1a — Content Model & Lesson Consumption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a demonstrable end-to-end learner vertical slice — an admin builds a course (Django admin + a seed command), an enrolled student reads a lesson, and per-element progress is recorded.

**Architecture:** A new `courses` Django app holds the whole slice. The content tree is one uniform `ContentNode` model (`kind` ∈ part/chapter/section/unit, depth invariant `part<chapter<section<unit`, one `OrderField` space per parent). Lesson content is GFK join-rows (`Element`) pointing at 5 concrete element models, each rendering its own template by convention. Progress is a per-(student,unit) row with a seen-element-id set fed by an `IntersectionObserver`, auto-completing when all elements are seen, with an always-present no-JS "Mark as done" fallback. Authoring in 1a is Django admin + an idempotent `seed_demo_course` command; the bespoke builder is deferred to Phase 1b.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL, `nh3` (HTML sanitisation, NEW dependency), Pillow (images), vendored KaTeX (math), pytest + factory_boy, Playwright (e2e). Tooling run via `uv run …`.

**Spec:** `docs/superpowers/specs/2026-06-15-phase-1a-content-model-and-consumption-design.md` (spec-review: 51 applied / 0 disputed / clean).

**Conventions to follow (from the existing codebase):**
- Imports one-per-line (ruff isort `force-single-line`), double quotes, ruff lint set `E,F,I,UP,B,S`.
- Tests live in the top-level `tests/` dir (not per-app), use `@pytest.mark.django_db` (an autouse fixture grants DB access), factory_boy factories in `tests/factories.py`.
- App templates live in the **top-level** `templates/<app>/…`; app static in `<app>/static/<app>/…`.
- AppConfig sets `default_auto_field = "django.db.models.BigAutoField"`.
- Run things with `uv run python manage.py …`, `uv run pytest …`, `uv run ruff …`.
- Commit after every green step.

---

## File Structure

**New app `courses/`:**
- `courses/__init__.py`, `courses/apps.py` — app config (registers the GFK cascade is automatic via `GenericRelation`; no signals needed).
- `courses/constants.py` — `COURSE_LANGUAGES` choices.
- `courses/fields.py` — `OrderField` (lifted from educa, scopes incl. null parent).
- `courses/sanitize.py` — `sanitize_html()` + allowed tags/attrs.
- `courses/validators.py` — `validate_embed_url()` (https + host/subdomain whitelist).
- `courses/models.py` — `Subject`, `Course`, `ContentNode`, `Element`, `ElementBase` (abstract), `TextElement`, `ImageElement`, `VideoElement`, `IframeElement`, `MathElement`, `Enrollment`, `UnitProgress`.
- `courses/access.py` — `is_enrolled()`, `can_access_course()`, `get_node_or_404()`.
- `courses/rollups.py` — `build_outline()`.
- `courses/views.py` — `my_courses`, `course_outline`, `lesson_unit`, `seen`, `complete`.
- `courses/urls.py` — `app_name = "courses"`.
- `courses/admin.py` — admin registrations.
- `courses/templatetags/__init__.py`, `courses/templatetags/courses_extras.py` — `{% render_element %}`, `sanitize` filter.
- `courses/management/__init__.py`, `courses/management/commands/__init__.py`, `courses/management/commands/seed_demo_course.py`.
- `courses/static/courses/js/progress.js`, `courses/static/courses/js/math.js`.
- `courses/static/courses/css/courses.css`.
- `courses/static/courses/vendor/katex/…` (vendored dist).

**Top-level templates:**
- `templates/courses/my_courses.html`, `templates/courses/outline.html`, `templates/courses/_outline_node.html`, `templates/courses/lesson_unit.html`.
- `templates/courses/elements/{textelement,imageelement,videoelement,iframeelement,mathelement}.html`.

**Modified:**
- `config/settings/base.py` — add `"courses"`, `MEDIA_URL`/`MEDIA_ROOT`, `ALLOWED_EMBED_DOMAINS`.
- `config/urls.py` — include `courses.urls`; serve media in DEBUG.
- `pyproject.toml` — add `nh3` dependency.
- `tests/factories.py` — content/learner-state factories + element helper.
- `tests/test_e2e_smoke.py` (or new `tests/test_e2e_courses.py`) — e2e for the lesson path.

**New test files:** `tests/test_courses_models.py`, `tests/test_courses_elements.py`, `tests/test_courses_access.py`, `tests/test_courses_rollups.py`, `tests/test_courses_views.py`, `tests/test_courses_progress.py`, `tests/test_seed_demo_course.py`.

---

## Task 1: App scaffold, settings, OrderField, constants

**Files:**
- Create: `courses/__init__.py`, `courses/apps.py`, `courses/constants.py`, `courses/fields.py`, `courses/migrations/__init__.py`
- Modify: `config/settings/base.py`, `config/urls.py`, `pyproject.toml`

- [ ] **Step 1: Create the app package and config**

`courses/__init__.py` — empty file.

`courses/apps.py`:
```python
from django.apps import AppConfig


class CoursesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "courses"
```

`courses/migrations/__init__.py` — empty file.

- [ ] **Step 2: Add constants and the OrderField**

`courses/constants.py`:
```python
# Content language is monolingual-per-course and pinned here (NOT settings.LANGUAGES),
# so adding a future chrome language never silently becomes a valid content language.
COURSE_LANGUAGES = [("en", "English"), ("pl", "Polski")]
```

`courses/fields.py` (lifted from educa, scopes correctly when `parent` is null):
```python
from django.core.exceptions import ObjectDoesNotExist
from django.db import models


class OrderField(models.PositiveIntegerField):
    """Auto-assigns the next order within a sibling scope (`for_fields`) when blank.

    Not DB-unique: transient duplicates within a scope are tolerated (ties broken by
    pk at query time). Filtering on a null `for_fields` value (e.g. parent=None) works,
    so course-level siblings share one order space. Re-parent/compaction is a Phase-1b
    concern; 1a only needs stable per-scope ordering.
    """

    def __init__(self, for_fields=None, *args, **kwargs):
        self.for_fields = for_fields
        super().__init__(*args, **kwargs)

    def pre_save(self, model_instance, add):
        if getattr(model_instance, self.attname) is None:
            try:
                qs = self.model.objects.all()
                if self.for_fields:
                    query = {
                        field: getattr(model_instance, field)
                        for field in self.for_fields
                    }
                    qs = qs.filter(**query)
                last_item = qs.latest(self.attname)
                value = getattr(last_item, self.attname) + 1
            except ObjectDoesNotExist:
                value = 0
            setattr(model_instance, self.attname, value)
            return value
        return super().pre_save(model_instance, add)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.for_fields is not None:
            kwargs["for_fields"] = self.for_fields
        return name, path, args, kwargs
```

- [ ] **Step 3: Register the app and add MEDIA + embed-whitelist settings**

In `config/settings/base.py`, add `"courses"` to the end of `INSTALLED_APPS`:
```python
    "core",
    "accounts",
    "institution",
    "courses",
]
```

After the `STATIC_*`/`STORAGES` block (near the bottom, before `DEFAULT_AUTO_FIELD`), add:
```python
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Whitelisted hosts for video/iframe embeds (validated in clean()). Bare lowercase
# hosts; a host matches iff it equals one OR is a subdomain of one. Phase 5 makes
# this admin-configurable.
ALLOWED_EMBED_DOMAINS = env.list(
    "LIBLI_ALLOWED_EMBED_DOMAINS",
    default=[
        "www.youtube.com",
        "youtube.com",
        "youtu.be",
        "player.vimeo.com",
        "www.geogebra.org",
    ],
)
```

- [ ] **Step 4: Serve media in DEBUG and prepare the courses URL include**

In `config/urls.py`, add the import lines at the top:
```python
from django.conf import settings
from django.conf.urls.static import static
```
Add `path("", include("courses.urls")),` to `urlpatterns` (after the `accounts` includes), then after the list:
```python
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```
(`courses/urls.py` does not exist yet — create a stub now so `include` resolves: create `courses/urls.py` with `app_name = "courses"` and `urlpatterns = []`.)

- [ ] **Step 5: Add the nh3 dependency**

In `pyproject.toml`, add to `dependencies`:
```toml
    "nh3>=0.2.18",
```
Then run: `uv sync`
Expected: resolves and installs `nh3`.

- [ ] **Step 6: Verify the project boots**

Run: `uv run python manage.py check`
Expected: `System check identified no issues`.

- [ ] **Step 7: Commit**

```bash
git add courses config pyproject.toml uv.lock
git commit -m "feat(courses): app scaffold, OrderField, MEDIA + embed-whitelist settings, nh3 dep"
```

---

## Task 2: Subject + Course models

**Files:**
- Modify: `courses/models.py` (create), `courses/admin.py` (create), `tests/factories.py`
- Test: `tests/test_courses_models.py` (create)

- [ ] **Step 1: Write the failing test**

`tests/test_courses_models.py`:
```python
import pytest

from tests.factories import CourseFactory


@pytest.mark.django_db
def test_course_str_and_defaults():
    course = CourseFactory(title="Algebra", language="pl")
    assert str(course) == "Algebra"
    assert course.visibility == "assigned"  # reserved hook, default
    assert course.language == "pl"
```

- [ ] **Step 2: Add the factories (will fail to import — models not defined)**

In `tests/factories.py`, add at the bottom:
```python
import factory

from courses.models import Course
from courses.models import Subject


class SubjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subject

    title = factory.Sequence(lambda n: f"Subject {n}")
    slug = factory.Sequence(lambda n: f"subject-{n}")


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    title = factory.Sequence(lambda n: f"Course {n}")
    slug = factory.Sequence(lambda n: f"course-{n}")
    language = "en"
```
(`import factory` already exists at the top of the file — do not duplicate it; add only the `courses.models` imports and the two classes.)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_courses_models.py::test_course_str_and_defaults -v`
Expected: FAIL — `ImportError` / `Subject` not defined.

- [ ] **Step 4: Implement Subject and Course**

`courses/models.py`:
```python
from django.conf import settings
from django.db import models

from courses.constants import COURSE_LANGUAGES


class Subject(models.Model):
    """Admin-only metadata in 1a (no learner-facing surface); gives Course.subject a target."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)

    def __str__(self):
        return self.title


class Course(models.Model):
    VISIBILITY_CHOICES = [("assigned", "Assigned"), ("open", "Open")]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    subject = models.ForeignKey(
        Subject, null=True, blank=True, on_delete=models.SET_NULL, related_name="courses"
    )
    language = models.CharField(max_length=5, choices=COURSE_LANGUAGES, default="en")
    overview = models.TextField(blank=True)
    # hook: Course-Admin scoping (inert in 1a — admin-authored).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_courses",
    )
    # hook: 'open'/self-enroll behaviour is Phase 3 (inert in 1a).
    visibility = models.CharField(
        max_length=10, choices=VISIBILITY_CHOICES, default="assigned"
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title
```

- [ ] **Step 5: Make + run migration, run the test**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0001_initial.py` with `Subject`, `Course`.

Run: `uv run pytest tests/test_courses_models.py::test_course_str_and_defaults -v`
Expected: PASS.

- [ ] **Step 6: Register in admin**

`courses/admin.py`:
```python
from django.contrib import admin

from courses.models import Course
from courses.models import Subject


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "language", "visibility")
    list_filter = ("language", "visibility")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("subject", "owner")
```
(For `autocomplete_fields` to work, `SubjectAdmin` needs `search_fields`; add `search_fields = ("title",)` to `SubjectAdmin`. The `owner` autocomplete relies on the existing User admin having search — if `manage.py check` warns, drop `owner` from `autocomplete_fields` and leave it a raw FK.)

Run: `uv run python manage.py check`
Expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add courses tests/factories.py tests/test_courses_models.py
git commit -m "feat(courses): Subject + Course models, admin, factories"
```

---

## Task 3: ContentNode tree + invariants

**Files:**
- Modify: `courses/models.py`, `courses/admin.py`, `tests/factories.py`
- Test: `tests/test_courses_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_courses_models.py`:
```python
from django.core.exceptions import ValidationError

from tests.factories import ContentNodeFactory


@pytest.mark.django_db
def test_kind_depth_invariant_rejects_shallow_child():
    course = CourseFactory()
    section = ContentNodeFactory(course=course, kind="section", parent=None, unit_type=None)
    bad = ContentNodeFactory.build(
        course=course, kind="part", parent=section, unit_type=None
    )
    with pytest.raises(ValidationError):
        bad.full_clean()


@pytest.mark.django_db
def test_root_level_unit_is_allowed():
    course = CourseFactory()
    unit = ContentNodeFactory.build(
        course=course, kind="unit", parent=None, unit_type="lesson"
    )
    unit.full_clean()  # must not raise


@pytest.mark.django_db
def test_unit_requires_unit_type_and_container_forbids_it():
    course = CourseFactory()
    bad_unit = ContentNodeFactory.build(
        course=course, kind="unit", parent=None, unit_type=None
    )
    with pytest.raises(ValidationError):
        bad_unit.full_clean()
    bad_part = ContentNodeFactory.build(
        course=course, kind="part", parent=None, unit_type="lesson"
    )
    with pytest.raises(ValidationError):
        bad_part.full_clean()


@pytest.mark.django_db
def test_clean_rejects_unit_conversion_when_node_has_children():
    course = CourseFactory()
    section = ContentNodeFactory(course=course, kind="section", parent=None, unit_type=None)
    ContentNodeFactory(course=course, kind="unit", parent=section, unit_type="lesson")
    section.kind = "unit"
    section.unit_type = "lesson"
    with pytest.raises(ValidationError):
        section.full_clean()


@pytest.mark.django_db
def test_orderfield_scopes_to_parent_including_null():
    course = CourseFactory()
    a = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    b = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    assert [a.order, b.order] == [0, 1]
    parent = ContentNodeFactory(course=course, parent=None, kind="part", unit_type=None)
    child = ContentNodeFactory(course=course, parent=parent, kind="unit", unit_type="lesson")
    assert child.order == 0  # new scope restarts ordering
```

- [ ] **Step 2: Add the factory**

In `tests/factories.py`, add (after `CourseFactory`):
```python
from courses.models import ContentNode


class ContentNodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContentNode

    course = factory.SubFactory(CourseFactory)
    parent = None
    kind = "unit"
    title = factory.Sequence(lambda n: f"Node {n}")
    unit_type = "lesson"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_courses_models.py -k "kind_depth or root_level or unit_requires or unit_conversion or orderfield" -v`
Expected: FAIL — `ContentNode` not defined.

- [ ] **Step 4: Implement ContentNode**

Add to `courses/models.py` (after `Course`, and add `from django.core.exceptions import ValidationError` and `from courses.fields import OrderField` to the imports):
```python
class ContentNode(models.Model):
    """Uniform content-tree node: Part / Chapter / Section / Unit.

    Invariant: a child's kind is strictly deeper than its parent's
    (part<chapter<section<unit); units are leaves and the only element-bearing kind.
    Middle levels are author-time optional, so any deeper kind may be a child.
    """

    class Kind(models.TextChoices):
        PART = "part", "Part"
        CHAPTER = "chapter", "Chapter"
        SECTION = "section", "Section"
        UNIT = "unit", "Unit"

    class UnitType(models.TextChoices):
        LESSON = "lesson", "Lesson"
        QUIZ = "quiz", "Quiz"

    RANK = {"part": 0, "chapter": 1, "section": 2, "unit": 3}

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="nodes")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    order = OrderField(for_fields=["course", "parent"], blank=True)
    title = models.CharField(max_length=200)
    unit_type = models.CharField(
        max_length=10, choices=UnitType.choices, null=True, blank=True
    )
    obligatory = models.BooleanField(default=True)  # meaningful only for units
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title}"

    def clean(self):
        if self.parent is not None:
            if self.parent.course_id != self.course_id:
                raise ValidationError("Parent must belong to the same course.")
            if self.RANK[self.parent.kind] >= self.RANK[self.kind]:
                raise ValidationError(
                    "A node's kind must be strictly deeper than its parent's."
                )
        if self.kind == self.Kind.UNIT:
            if not self.unit_type:
                raise ValidationError("Units require a unit_type.")
        elif self.unit_type:
            raise ValidationError("Only units may have a unit_type.")
        # Re-validate against existing children (admin edits can break the tree from above).
        if self.pk:
            children = list(self.children.all())
            if self.kind == self.Kind.UNIT and children:
                raise ValidationError("A unit cannot have children.")
            for child in children:
                if self.RANK[self.kind] >= self.RANK[child.kind]:
                    raise ValidationError(
                        "Change would make a child no longer deeper than this node."
                    )
```

- [ ] **Step 5: Migrate and run the tests**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0002_contentnode.py`.

Run: `uv run pytest tests/test_courses_models.py -v`
Expected: all PASS.

- [ ] **Step 6: Register ContentNode in admin**

Add to `courses/admin.py`:
```python
from courses.models import ContentNode


@admin.register(ContentNode)
class ContentNodeAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "kind", "unit_type", "obligatory", "order")
    list_filter = ("course", "kind", "unit_type")
    search_fields = ("title",)
    autocomplete_fields = ("course", "parent")
```
(`CourseAdmin` needs `search_fields = ("title",)` for the `course`/`parent` autocompletes — add it if not already present.)

Run: `uv run python manage.py check`
Expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add courses tests/factories.py tests/test_courses_models.py
git commit -m "feat(courses): ContentNode tree with kind-depth + child-revalidation invariants"
```

---

## Task 4: Element join-row, sanitisation, TextElement + render convention

**Files:**
- Modify: `courses/models.py`, `courses/admin.py`
- Create: `courses/sanitize.py`, `courses/templatetags/__init__.py`, `courses/templatetags/courses_extras.py`, `templates/courses/elements/textelement.html`
- Test: `tests/test_courses_elements.py` (create)

- [ ] **Step 1: Write the failing tests**

`tests/test_courses_elements.py`:
```python
import pytest

from tests.factories import ContentNodeFactory


@pytest.mark.django_db
def test_textelement_sanitised_on_save():
    from courses.models import TextElement

    el = TextElement.objects.create(body="<p>hi</p><script>alert(1)</script>")
    assert "<script>" not in el.body
    assert "<p>hi</p>" in el.body


@pytest.mark.django_db
def test_element_render_dispatches_to_template_and_join_row():
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    text = TextElement.objects.create(body="<p>lesson body</p>")
    el = Element.objects.create(unit=unit, content_object=text)
    html = el.content_object.render()
    assert "lesson body" in html


@pytest.mark.django_db
def test_deleting_concrete_element_cascades_join_row():
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    text = TextElement.objects.create(body="<p>x</p>")
    Element.objects.create(unit=unit, content_object=text)
    assert Element.objects.count() == 1
    text.delete()
    assert Element.objects.count() == 0  # GenericRelation cascade
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_courses_elements.py -v`
Expected: FAIL — `TextElement` not defined.

- [ ] **Step 3: Add the sanitiser**

`courses/sanitize.py`:
```python
import nh3

# Safe subset for styled rich text. NOT the deferred arbitrary-HTML element — no
# scripts, no style/script-bearing attributes.
ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "h2", "h3", "h4",
    "ul", "ol", "li", "a", "blockquote", "code", "pre",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title", "rel"}}


def sanitize_html(value):
    """Strip everything outside the safe subset. Idempotent on already-clean input."""
    return nh3.clean(value or "", tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
```

- [ ] **Step 4: Add Element, ElementBase, TextElement**

Add to `courses/models.py` imports:
```python
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from courses.sanitize import sanitize_html
```
Add the models (after `ContentNode`):
```python
ELEMENT_MODELS = [
    "textelement",
    "imageelement",
    "videoelement",
    "iframeelement",
    "mathelement",
]


class Element(models.Model):
    """GFK join-row: an ordered slot in a unit pointing at one concrete element."""

    unit = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="elements",
        limit_choices_to={"kind": "unit"},
    )
    order = OrderField(for_fields=["unit"], blank=True)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        limit_choices_to={"app_label": "courses", "model__in": ELEMENT_MODELS},
    )
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"Element #{self.pk} of {self.unit_id}"


class ElementBase(models.Model):
    """Abstract base: each concrete element renders its own template by convention."""

    class Meta:
        abstract = True

    def render(self):
        name = self._meta.model_name
        return render_to_string(f"courses/elements/{name}.html", {"el": self})


class TextElement(ElementBase):
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)
```

- [ ] **Step 5: Add the template tag and the text template**

`courses/templatetags/__init__.py` — empty file.

`courses/templatetags/courses_extras.py`:
```python
from django import template
from django.utils.safestring import mark_safe

from courses.sanitize import sanitize_html

register = template.Library()


@register.simple_tag
def render_element(element):
    """Render one Element's concrete payload (empty string if the target was deleted)."""
    obj = element.content_object
    if obj is None:
        return ""
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields


@register.filter
def sanitize(value):
    """Re-sanitise stored rich text at render (defense-in-depth) and mark safe."""
    return mark_safe(sanitize_html(value))  # noqa: S308 — output is sanitised
```

`templates/courses/elements/textelement.html`:
```html
{% load courses_extras %}
<div class="el el--text">{{ el.body|sanitize }}</div>
```

- [ ] **Step 6: Migrate and run tests**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0003_*` with `Element`, `TextElement`.

Run: `uv run pytest tests/test_courses_elements.py -v`
Expected: all PASS.

- [ ] **Step 7: Register Element + TextElement in admin**

Add to `courses/admin.py`:
```python
from courses.models import Element
from courses.models import TextElement

admin.site.register(TextElement)


@admin.register(Element)
class ElementAdmin(admin.ModelAdmin):
    list_display = ("pk", "unit", "content_type", "object_id", "order")
    list_filter = ("content_type",)
    autocomplete_fields = ("unit",)
```

Run: `uv run python manage.py check`
Expected: no issues.

- [ ] **Step 8: Commit**

```bash
git add courses templates/courses tests/test_courses_elements.py
git commit -m "feat(courses): Element GFK join + sanitised TextElement + render convention"
```

---

## Task 5: Image / Video / Iframe / Math elements + embed validator

**Files:**
- Modify: `courses/models.py`, `courses/admin.py`
- Create: `courses/validators.py`, `templates/courses/elements/{imageelement,videoelement,iframeelement,mathelement}.html`
- Test: `tests/test_courses_elements.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_courses_elements.py`:
```python
@pytest.mark.django_db
def test_video_xor_rejects_neither_and_both():
    from django.core.exceptions import ValidationError

    from courses.models import VideoElement

    neither = VideoElement()
    with pytest.raises(ValidationError):
        neither.full_clean()
    both = VideoElement(url="https://www.youtube.com/watch?v=x", file="v.mp4")
    with pytest.raises(ValidationError):
        both.full_clean()


@pytest.mark.django_db
def test_embed_url_requires_https_and_whitelist():
    from django.core.exceptions import ValidationError

    from courses.models import IframeElement

    ok = IframeElement(url="https://www.geogebra.org/m/abc")
    ok.full_clean()  # allowed host
    sub = IframeElement(url="https://sub.geogebra.org/m/abc")
    sub.full_clean()  # subdomain allowed
    bad_scheme = IframeElement(url="http://www.geogebra.org/m/abc")
    with pytest.raises(ValidationError):
        bad_scheme.full_clean()
    bad_host = IframeElement(url="https://evil.example.com/m/abc")
    with pytest.raises(ValidationError):
        bad_host.full_clean()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_courses_elements.py -k "video_xor or embed_url" -v`
Expected: FAIL — models not defined.

- [ ] **Step 3: Add the embed validator**

`courses/validators.py`:
```python
from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError


def validate_embed_url(url):
    """Require https and a host that equals or is a subdomain of a whitelisted host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValidationError("Embed URLs must use https.")
    host = (parts.hostname or "").lower()
    allowed = {d.lower() for d in settings.ALLOWED_EMBED_DOMAINS}
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValidationError("Embed domain is not on the allow-list.")
```

- [ ] **Step 4: Add the four element models**

Add to `courses/models.py` imports:
```python
from courses.validators import validate_embed_url
```
Add the models (after `TextElement`):
```python
class ImageElement(ElementBase):
    image = models.ImageField(upload_to="courses/images/")
    alt = models.CharField(max_length=255, blank=True)  # empty = decorative (valid)
    figcaption = models.CharField(max_length=255, blank=True)
    elements = GenericRelation(Element)


class VideoElement(ElementBase):
    url = models.URLField(blank=True)  # whitelisted embed URL
    file = models.FileField(upload_to="courses/videos/", blank=True)  # OR an upload
    elements = GenericRelation(Element)

    def clean(self):
        has_url = bool(self.url)
        has_file = bool(self.file)
        if has_url == has_file:
            raise ValidationError("Provide exactly one of url or file.")
        if has_url:
            validate_embed_url(self.url)


class IframeElement(ElementBase):
    url = models.URLField(validators=[validate_embed_url])
    title = models.CharField(max_length=255, blank=True)
    elements = GenericRelation(Element)

    def clean(self):
        validate_embed_url(self.url)


class MathElement(ElementBase):
    latex = models.TextField()  # rendered client-side via KaTeX (Task 11)
    elements = GenericRelation(Element)
```

- [ ] **Step 5: Add the element templates**

`templates/courses/elements/imageelement.html`:
```html
<figure class="el el--image">
  <img src="{{ el.image.url }}" alt="{{ el.alt }}">
  {% if el.figcaption %}<figcaption>{{ el.figcaption }}</figcaption>{% endif %}
</figure>
```

`templates/courses/elements/videoelement.html`:
```html
<div class="el el--video">
  {% if el.url %}
    <iframe src="{{ el.url }}" loading="lazy" allowfullscreen title="video"></iframe>
  {% else %}
    <video controls src="{{ el.file.url }}"></video>
  {% endif %}
</div>
```

`templates/courses/elements/iframeelement.html`:
```html
<div class="el el--iframe">
  <iframe src="{{ el.url }}" loading="lazy" title="{{ el.title|default:'embedded content' }}"></iframe>
</div>
```

`templates/courses/elements/mathelement.html`:
```html
<div class="el el--math" data-katex>{{ el.latex }}</div>
```

- [ ] **Step 6: Migrate and run tests**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0004_*` with the four element models.

Run: `uv run pytest tests/test_courses_elements.py -v`
Expected: all PASS.

- [ ] **Step 7: Register in admin + check**

Add to `courses/admin.py`:
```python
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import VideoElement

admin.site.register(ImageElement)
admin.site.register(VideoElement)
admin.site.register(IframeElement)
admin.site.register(MathElement)
```

Run: `uv run python manage.py check`
Expected: no issues.

- [ ] **Step 8: Commit**

```bash
git add courses templates/courses/elements tests/test_courses_elements.py
git commit -m "feat(courses): image/video/iframe/math elements + https embed whitelist"
```

---

## Task 6: Enrollment + UnitProgress

**Files:**
- Modify: `courses/models.py`, `courses/admin.py`, `tests/factories.py`
- Test: `tests/test_courses_models.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_courses_models.py`:
```python
@pytest.mark.django_db
def test_enrollment_unique_per_student_course():
    from django.db import IntegrityError

    from courses.models import Enrollment
    from tests.factories import UserFactory

    course = CourseFactory()
    user = UserFactory()
    Enrollment.objects.create(student=user, course=course)
    with pytest.raises(IntegrityError):
        Enrollment.objects.create(student=user, course=course)


@pytest.mark.django_db
def test_unitprogress_save_stamps_completed_at():
    from courses.models import UnitProgress
    from tests.factories import UserFactory

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    user = UserFactory()
    progress = UnitProgress.objects.create(student=user, unit=unit)
    assert progress.completed_at is None
    progress.completed = True
    progress.save()  # invariant: completed => completed_at set (admin path too)
    assert progress.completed_at is not None
```

- [ ] **Step 2: Add the factories**

In `tests/factories.py`, add:
```python
from courses.models import Enrollment
from courses.models import UnitProgress


class EnrollmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Enrollment

    student = factory.SubFactory(UserFactory)
    course = factory.SubFactory(CourseFactory)


class UnitProgressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UnitProgress

    student = factory.SubFactory(UserFactory)
    unit = factory.SubFactory(ContentNodeFactory)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_courses_models.py -k "enrollment_unique or completed_at" -v`
Expected: FAIL — `Enrollment` not defined.

- [ ] **Step 4: Implement the models**

Add to `courses/models.py` (after the element models; add `from django.utils import timezone` to imports):
```python
class Enrollment(models.Model):
    SOURCE_CHOICES = [("manual", "Manual"), ("group", "Group"), ("self", "Self")]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"], name="uniq_enrollment_student_course"
            )
        ]

    def __str__(self):
        return f"{self.student_id} in {self.course_id}"


class UnitProgress(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="unit_progress"
    )
    unit = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="progress",
        limit_choices_to={"kind": "unit"},
    )
    seen_element_ids = models.JSONField(default=list)  # Element.pk values (the seen-set)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "unit"], name="uniq_progress_student_unit"
            )
        ]

    def save(self, *args, **kwargs):
        # Invariant: completed => completed_at set, for EVERY write path (incl. admin).
        if self.completed and self.completed_at is None:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)
```

- [ ] **Step 5: Migrate and run tests**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0005_*` with `Enrollment`, `UnitProgress`.

Run: `uv run pytest tests/test_courses_models.py -v`
Expected: all PASS.

- [ ] **Step 6: Register in admin + check**

Add to `courses/admin.py`:
```python
from courses.models import Enrollment
from courses.models import UnitProgress


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "source", "created_at")
    list_filter = ("source", "course")
    autocomplete_fields = ("student", "course")


@admin.register(UnitProgress)
class UnitProgressAdmin(admin.ModelAdmin):
    list_display = ("student", "unit", "completed", "completed_at")
    list_filter = ("completed",)
    autocomplete_fields = ("student", "unit")
```

Run: `uv run python manage.py check`
Expected: no issues.

- [ ] **Step 7: Commit**

```bash
git add courses tests/factories.py tests/test_courses_models.py
git commit -m "feat(courses): Enrollment + UnitProgress (completed_at invariant in save)"
```

---

## Task 7: Access helpers + node scoping

**Files:**
- Create: `courses/access.py`
- Test: `tests/test_courses_access.py` (create)

- [ ] **Step 1: Write the failing tests**

`tests/test_courses_access.py`:
```python
import pytest
from django.http import Http404

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_can_access_enrolled_staff_owner_and_deny():
    from courses.access import can_access_course

    course = CourseFactory()
    enrolled = UserFactory()
    EnrollmentFactory(student=enrolled, course=course)
    staff = UserFactory(is_staff=True)
    owner = UserFactory()
    course.owner = owner
    course.save()
    stranger = UserFactory()
    assert can_access_course(enrolled, course) is True
    assert can_access_course(staff, course) is True
    assert can_access_course(owner, course) is True
    assert can_access_course(stranger, course) is False


@pytest.mark.django_db
def test_null_owner_never_matches():
    from courses.access import can_access_course

    course = CourseFactory()  # owner is None
    user = UserFactory()  # user.id is set, owner_id is None
    assert can_access_course(user, course) is False


@pytest.mark.django_db
def test_get_node_or_404_slug_mismatch_and_kind():
    from courses.access import get_node_or_404

    course = CourseFactory(slug="real")
    other = CourseFactory(slug="other")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    # right slug, right kind -> ok
    assert get_node_or_404(unit.pk, "real", require_unit=True).pk == unit.pk
    # wrong slug -> 404 (IDOR guard)
    with pytest.raises(Http404):
        get_node_or_404(unit.pk, "other", require_unit=True)
    # container under lesson route -> 404
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    with pytest.raises(Http404):
        get_node_or_404(part.pk, "real", require_unit=True)
    # quiz unit under a lesson-only endpoint -> 404
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    with pytest.raises(Http404):
        get_node_or_404(quiz.pk, "real", require_unit=True, require_lesson=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_courses_access.py -v`
Expected: FAIL — `courses.access` not found.

- [ ] **Step 3: Implement the access helpers**

`courses/access.py`:
```python
from django.http import Http404
from django.shortcuts import get_object_or_404

from courses.models import ContentNode
from courses.models import Enrollment


def is_enrolled(user, course):
    return Enrollment.objects.filter(student=user, course=course).exists()


def can_access_course(user, course):
    """Enrolled OR staff OR (course has an owner AND it is this user)."""
    if is_enrolled(user, course):
        return True
    if user.is_staff:
        return True
    return course.owner_id is not None and course.owner_id == user.id


def get_node_or_404(node_pk, slug, *, require_unit=False, require_lesson=False):
    """Resolve a node and enforce object scoping. 404 (never 403) on any mismatch.

    Order: exists -> slug match -> kind/unit_type. Access (403) is checked by the
    caller AFTER this returns, so a foreign node always 404s before any 403.
    """
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if node.course.slug != slug:
        raise Http404("node does not belong to this course")
    if require_unit and node.kind != ContentNode.Kind.UNIT:
        raise Http404("not a unit")
    if require_lesson and node.unit_type != ContentNode.UnitType.LESSON:
        raise Http404("not a lesson unit")
    return node
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_courses_access.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/access.py tests/test_courses_access.py
git commit -m "feat(courses): access predicate (null-owner guard) + node scoping (404-before-403)"
```

---

## Task 8: My courses + outline (rollups)

**Files:**
- Create: `courses/rollups.py`, `templates/courses/my_courses.html`, `templates/courses/outline.html`, `templates/courses/_outline_node.html`, `courses/static/courses/css/courses.css`
- Modify: `courses/views.py` (create), `courses/urls.py`
- Test: `tests/test_courses_rollups.py` (create), `tests/test_courses_views.py` (create)

- [ ] **Step 1: Write the failing rollup tests**

`tests/test_courses_rollups.py`:
```python
import pytest

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_rollup_required_additional_and_quiz_excluded():
    from courses.rollups import build_outline

    course = CourseFactory()
    chapter = ContentNodeFactory(course=course, kind="chapter", parent=None, unit_type=None)
    u1 = ContentNodeFactory(course=course, parent=chapter, kind="unit", unit_type="lesson", obligatory=True)
    ContentNodeFactory(course=course, parent=chapter, kind="unit", unit_type="lesson", obligatory=True)
    extra = ContentNodeFactory(course=course, parent=chapter, kind="unit", unit_type="lesson", obligatory=False)
    ContentNodeFactory(course=course, parent=chapter, kind="unit", unit_type="quiz", obligatory=True)
    user = UserFactory()
    UnitProgressFactory(student=user, unit=u1, completed=True)
    UnitProgressFactory(student=user, unit=extra, completed=True)

    roots = build_outline(course, user)
    ch = roots[0]
    assert ch["required_total"] == 2  # two obligatory lessons; quiz excluded
    assert ch["required_done"] == 1
    assert ch["additional_done"] == 1


@pytest.mark.django_db
def test_rollup_container_less_course():
    from courses.rollups import build_outline

    course = CourseFactory()
    ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson", obligatory=True)
    user = UserFactory()
    roots = build_outline(course, user)
    assert len(roots) == 1
    assert roots[0]["required_total"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_courses_rollups.py -v`
Expected: FAIL — `courses.rollups` not found.

- [ ] **Step 3: Implement the rollup builder**

`courses/rollups.py`:
```python
from courses.models import ContentNode
from courses.models import UnitProgress


def build_outline(course, user):
    """Return a nested list of node dicts with required/additional rollups.

    Two queries (nodes + the user's completed unit ids). `required` counts only
    obligatory lesson units; `additional_done` counts completed non-obligatory lesson
    units; quiz units are excluded from both (uncompletable in 1a).
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    completed = set()
    if user.is_authenticated:
        completed = set(
            UnitProgress.objects.filter(
                student=user, unit__course=course, completed=True
            ).values_list("unit_id", flat=True)
        )

    def build(node):
        kids = [build(child) for child in children.get(node.pk, [])]
        if node.kind == ContentNode.Kind.UNIT:
            is_lesson = node.unit_type == ContentNode.UnitType.LESSON
            required_total = 1 if (is_lesson and node.obligatory) else 0
            required_done = 1 if (required_total and node.pk in completed) else 0
            additional_done = (
                1 if (is_lesson and not node.obligatory and node.pk in completed) else 0
            )
        else:
            required_total = sum(k["required_total"] for k in kids)
            required_done = sum(k["required_done"] for k in kids)
            additional_done = sum(k["additional_done"] for k in kids)
        return {
            "node": node,
            "children": kids,
            "required_total": required_total,
            "required_done": required_done,
            "additional_done": additional_done,
            "is_unit": node.kind == ContentNode.Kind.UNIT,
            "completed": node.kind == ContentNode.Kind.UNIT and node.pk in completed,
        }

    return [build(node) for node in children.get(None, [])]
```

- [ ] **Step 4: Run rollup tests**

Run: `uv run pytest tests/test_courses_rollups.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing view tests**

`tests/test_courses_views.py`:
```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory
from tests.factories import make_login

PASSWORD = "Sup3r!pass9"


@pytest.mark.django_db
def test_my_courses_lists_only_enrollments(client):
    user = make_login(client, "stu")
    mine = CourseFactory(title="Mine")
    CourseFactory(title="NotMine")
    EnrollmentFactory(student=user, course=mine)
    resp = client.get(reverse("courses:my_courses"))
    assert resp.status_code == 200
    assert "Mine" in resp.content.decode()
    assert "NotMine" not in resp.content.decode()


@pytest.mark.django_db
def test_outline_403_for_non_enrolled(client):
    make_login(client, "stranger")
    course = CourseFactory(slug="c1")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    resp = client.get(reverse("courses:course_outline", kwargs={"slug": "c1"}))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_outline_renders_for_enrolled(client):
    user = make_login(client, "stu2")
    course = CourseFactory(slug="c2")
    EnrollmentFactory(student=user, course=course)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="Lesson A")
    resp = client.get(reverse("courses:course_outline", kwargs={"slug": "c2"}))
    assert resp.status_code == 200
    assert "Lesson A" in resp.content.decode()
```

Add a small login helper to `tests/factories.py`:
```python
def make_login(client, username):
    """Create a user, log the test client in, and return the user."""
    user = UserFactory(username=username)
    client.force_login(user)
    return user
```

- [ ] **Step 6: Run view tests to verify they fail**

Run: `uv run pytest tests/test_courses_views.py -k "my_courses or outline" -v`
Expected: FAIL — `courses:my_courses` not reversible.

- [ ] **Step 7: Implement the views and URLs**

`courses/views.py` (full file for this task; later tasks append to it):
```python
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from courses.access import can_access_course
from courses.models import Course
from courses.rollups import build_outline


@login_required
def my_courses(request):
    courses = Course.objects.filter(enrollments__student=request.user).order_by("title")
    return render(request, "courses/my_courses.html", {"courses": courses})


@login_required
def course_outline(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    outline = build_outline(course, request.user)
    return render(
        request, "courses/outline.html", {"course": course, "outline": outline}
    )
```
(Tasks 9 and 10 add `lesson_unit`, `seen`, `complete` and the extra imports they need — `get_node_or_404`, `is_enrolled`, `ContentNode`, `MathElement`, `UnitProgress`, `ContentType`, `json`, `JsonResponse`, `HttpResponseBadRequest`, `redirect`, `require_POST`.)

`courses/urls.py`:
```python
from django.urls import path

from courses import views

app_name = "courses"

urlpatterns = [
    path("courses/", views.my_courses, name="my_courses"),
    path("courses/<slug:slug>/", views.course_outline, name="course_outline"),
]
```

- [ ] **Step 8: Add the templates and CSS**

`templates/courses/my_courses.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "My courses" %} — libli{% endblock %}
{% block content %}
<section class="courses-list">
  <h1>{% trans "My courses" %}</h1>
  {% if courses %}
    <ul>
      {% for course in courses %}
        <li><a href="{% url 'courses:course_outline' slug=course.slug %}">{{ course.title }}</a></li>
      {% endfor %}
    </ul>
  {% else %}
    <p class="empty">{% trans "You are not enrolled in any courses yet." %}</p>
  {% endif %}
</section>
{% endblock %}
```

`templates/courses/outline.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{{ course.title }} — libli{% endblock %}
{% block content %}
<section class="outline" lang="{{ course.language }}">
  <h1>{{ course.title }}</h1>
</section>
<nav class="outline-tree" aria-label="{% trans 'Course outline' %}">
  <ul>
    {% for item in outline %}{% include "courses/_outline_node.html" with item=item course=course %}{% endfor %}
  </ul>
</nav>
{% endblock %}
```

`templates/courses/_outline_node.html` — the unit branch is **plain text in this task** (the
`courses:lesson_unit` route doesn't exist until Task 9; Task 9 Step 7 swaps it to a link, avoiding a
forward `{% url %}` reverse that would break this task's commit):
```html
{% load i18n %}
<li class="outline-node outline-node--{{ item.node.kind }}">
  {% if item.is_unit %}
    <span class="outline-node__unit">{{ item.node.title }}</span>
    {% if item.completed %}<span class="badge badge--done">✓</span>{% endif %}
  {% else %}
    <span class="outline-node__title">{{ item.node.title }}</span>
    {% if item.required_total %}
      <span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>
    {% endif %}
    {% if item.additional_done %}
      <span class="rollup rollup--additional">+{{ item.additional_done }} {% trans "additional" %}</span>
    {% endif %}
    {% if item.children %}
      <ul>
        {% for child in item.children %}{% include "courses/_outline_node.html" with item=child course=course %}{% endfor %}
      </ul>
    {% endif %}
  {% endif %}
</li>
```

`courses/static/courses/css/courses.css`:
```css
.outline-tree ul { list-style: none; padding-left: 1rem; }
.outline-node { margin: .25rem 0; }
.rollup { color: var(--text-muted, #555); font-size: .85em; margin-left: .5rem; }
.el { margin: 1rem 0; }
.el--video iframe, .el--iframe iframe { width: 100%; aspect-ratio: 16 / 9; border: 0; }
.el--image img { max-width: 100%; height: auto; }
.unit-progress { position: sticky; bottom: 0; }
```

- [ ] **Step 9: Run the view tests**

Run: `uv run pytest tests/test_courses_views.py -k "my_courses or outline" -v`
Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add courses templates/courses tests/test_courses_rollups.py tests/test_courses_views.py tests/factories.py
git commit -m "feat(courses): my-courses + outline views with required/additional rollups"
```

---

## Task 9: Lesson unit view + element rendering + quiz placeholder + seen/complete views

**Files:**
- Modify: `courses/views.py` (adds `lesson_unit`, `seen`, `complete`), `courses/urls.py`, `templates/courses/_outline_node.html`
- Create: `templates/courses/lesson_unit.html`
- Test: `tests/test_courses_views.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_courses_views.py`:
```python
@pytest.mark.django_db
def test_lesson_unit_renders_elements_in_order(client):
    from courses.models import Element
    from courses.models import TextElement

    user = make_login(client, "reader")
    course = CourseFactory(slug="lc")
    EnrollmentFactory(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    t1 = TextElement.objects.create(body="<p>First</p>")
    t2 = TextElement.objects.create(body="<p>Second</p>")
    Element.objects.create(unit=unit, content_object=t1)
    Element.objects.create(unit=unit, content_object=t2)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "lc", "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "First" in body and "Second" in body
    assert body.index("First") < body.index("Second")
    assert f'data-element-id="' in body


@pytest.mark.django_db
def test_lesson_route_404_on_slug_mismatch_idor(client):
    user = make_login(client, "idor")
    a = CourseFactory(slug="a")
    b = CourseFactory(slug="b")
    EnrollmentFactory(student=user, course=a)
    b_unit = ContentNodeFactory(course=b, kind="unit", unit_type="lesson")
    # pair a slug the user CAN access with b's node -> 404, not 403
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "a", "node_pk": b_unit.pk})
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_quiz_unit_renders_placeholder(client):
    user = make_login(client, "quizreader")
    course = CourseFactory(slug="qc")
    EnrollmentFactory(student=user, course=course)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": "qc", "node_pk": quiz.pk})
    )
    assert resp.status_code == 200
    assert "Phase 2" in resp.content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_courses_views.py -k "lesson_unit or lesson_route or quiz_unit" -v`
Expected: FAIL — `courses:lesson_unit` not reversible.

- [ ] **Step 3: Implement the lesson view**

Add to `courses/views.py` (add imports `from django.contrib.contenttypes.models import ContentType` and `from courses.access import is_enrolled`, `from courses.models import ContentNode`, `from courses.models import MathElement`, `from courses.models import UnitProgress`):
```python
@login_required
def lesson_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if node.unit_type == ContentNode.UnitType.QUIZ:
        return render(
            request,
            "courses/lesson_unit.html",
            {"course": course, "unit": node, "is_quiz": True},
        )
    elements = list(node.elements.order_by("order", "pk").prefetch_related("content_object"))
    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    has_math = any(el.content_type_id == math_ct_id for el in elements)
    progress = None
    seen_ids = set()
    if is_enrolled(request.user, course):
        progress, _ = UnitProgress.objects.get_or_create(student=request.user, unit=node)
        seen_ids = set(progress.seen_element_ids)
    current_ids = [el.pk for el in elements]
    seen_count = len(seen_ids.intersection(current_ids))
    return render(
        request,
        "courses/lesson_unit.html",
        {
            "course": course,
            "unit": node,
            "is_quiz": False,
            "elements": elements,
            "has_math": has_math,
            "progress": progress,
            "element_count": len(current_ids),
            "seen_count": seen_count,
        },
    )
```

- [ ] **Step 3b: Implement the seen/complete endpoint views (needed for the lesson template's `{% url %}`)**

Add to `courses/views.py` (add imports `import json`, `from django.http import HttpResponseBadRequest`, `from django.http import JsonResponse`, `from django.shortcuts import redirect`, `from django.views.decorators.http import require_POST`):
```python
def _progress_json(progress):
    return {
        "seen_element_ids": list(progress.seen_element_ids),
        "completed": progress.completed,
        "completed_at": progress.completed_at.isoformat() if progress.completed_at else None,
    }


@require_POST
@login_required
def seen(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    try:
        data = json.loads(request.body or b"[]")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid JSON")
    if not isinstance(data, list):
        return HttpResponseBadRequest("expected a JSON array")
    if not is_enrolled(request.user, course):
        # untracked preview: no write, synthetic canonical response
        return JsonResponse(
            {"seen_element_ids": [], "completed": False, "completed_at": None}
        )
    current = set(node.elements.values_list("pk", flat=True))
    incoming = {
        x for x in data if isinstance(x, int) and not isinstance(x, bool) and x in current
    }
    progress, _ = UnitProgress.objects.get_or_create(student=request.user, unit=node)
    merged = set(progress.seen_element_ids) | incoming
    progress.seen_element_ids = sorted(merged)
    if not progress.completed and current and current.issubset(merged):
        progress.completed = True  # completed_at stamped in save()
    progress.save()
    return JsonResponse(_progress_json(progress))


@require_POST
@login_required
def complete(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if is_enrolled(request.user, course):
        progress, _ = UnitProgress.objects.get_or_create(student=request.user, unit=node)
        if not progress.completed:
            progress.completed = True
            progress.save()
    return redirect("courses:lesson_unit", slug=slug, node_pk=node_pk)
```
(The seen/complete *behaviour* is exercised by tests in Task 10; here we implement them so the lesson template's `{% url 'courses:seen' %}`/`{% url 'courses:complete' %}` resolve and Task 9's lesson tests pass.)

- [ ] **Step 4: Add all three lesson/endpoint URL routes**

In `courses/urls.py`, add inside `urlpatterns` (keep order `my_courses`, the three node routes, then `course_outline` — the slug converter never matches the `/u/<int>/…` suffix, so order is not load-bearing, but this reads clearly):
```python
    path("courses/<slug:slug>/u/<int:node_pk>/", views.lesson_unit, name="lesson_unit"),
    path("courses/<slug:slug>/u/<int:node_pk>/seen/", views.seen, name="seen"),
    path("courses/<slug:slug>/u/<int:node_pk>/complete/", views.complete, name="complete"),
```

- [ ] **Step 5: Add the lesson template**

`templates/courses/lesson_unit.html`:
```html
{% extends "base.html" %}
{% load i18n static courses_extras %}
{% block head_title %}{{ unit.title }} — libli{% endblock %}
{% block extra_css %}
  <link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">
  {% if has_math %}<link rel="stylesheet" href="{% static 'courses/vendor/katex/katex.min.css' %}">{% endif %}
{% endblock %}
{% block content %}
<article class="lesson" lang="{{ course.language }}"
         data-seen-url="{% url 'courses:seen' slug=course.slug node_pk=unit.pk %}">
  <h1>{{ unit.title }}</h1>
  {% if is_quiz %}
    <p class="placeholder">{% trans "Quizzes arrive in Phase 2." %}</p>
  {% else %}
    {% for el in elements %}
      <section data-element-id="{{ el.pk }}">{% render_element el %}</section>
    {% endfor %}

    {# Within-unit fraction bar: hidden when empty-and-not-done; 100% when completed. #}
    {% if progress.completed %}
      <div class="unit-fraction" data-fraction="100">{% trans "Complete" %} ✓</div>
    {% elif element_count %}
      <div class="unit-fraction" data-fraction="{% widthratio seen_count element_count 100 %}">
        {{ seen_count }}/{{ element_count }}
      </div>
    {% endif %}

    <form class="unit-progress" method="post"
          action="{% url 'courses:complete' slug=course.slug node_pk=unit.pk %}">
      {% csrf_token %}
      <button type="submit" class="btn btn--primary">{% trans "Mark as done" %}</button>
    </form>
  {% endif %}
</article>
{% endblock %}
{% block extra_js %}
  {% if not is_quiz %}<script src="{% static 'courses/js/progress.js' %}" defer></script>{% endif %}
  {% if has_math %}
    <script src="{% static 'courses/vendor/katex/katex.min.js' %}" defer></script>
    <script src="{% static 'courses/js/math.js' %}" defer></script>
  {% endif %}
{% endblock %}
```

- [ ] **Step 6: Wire outline unit links to the lesson route**

In `templates/courses/_outline_node.html`, change the unit branch from plain text to a link (the route now exists):
```html
  {% if item.is_unit %}
    <a href="{% url 'courses:lesson_unit' slug=course.slug node_pk=item.node.pk %}">{{ item.node.title }}</a>
    {% if item.completed %}<span class="badge badge--done">✓</span>{% endif %}
```

- [ ] **Step 7: Run the lesson tests + check**

Run: `uv run python manage.py check`
Expected: no issues (all three views + URLs now exist).
Run: `uv run pytest tests/test_courses_views.py -v`
Expected: all PASS (my-courses, outline, lesson render, IDOR 404, quiz placeholder).

- [ ] **Step 8: Commit**

```bash
git add courses templates/courses tests/test_courses_views.py
git commit -m "feat(courses): lesson view + quiz placeholder + seen/complete endpoints"
```

---

## Task 10: Progress endpoint tests + progress.js

(The `seen`/`complete` *views* were implemented in Task 9 Step 3b; this task pins their behaviour with tests and adds the client-side tracker.)

**Files:**
- Create: `courses/static/courses/js/progress.js`, `tests/test_courses_progress.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_courses_progress.py`:
```python
import json

import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import make_login


def _seen_url(slug, pk):
    return reverse("courses:seen", kwargs={"slug": slug, "node_pk": pk})


def _make_unit_with_elements(course, n):
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    ids = []
    for i in range(n):
        t = TextElement.objects.create(body=f"<p>e{i}</p>")
        ids.append(Element.objects.create(unit=unit, content_object=t).pk)
    return unit, ids


@pytest.mark.django_db
def test_seen_merges_and_autocompletes(client):
    user = make_login(client, "p1")
    course = CourseFactory(slug="pc")
    EnrollmentFactory(student=user, course=course)
    unit, ids = _make_unit_with_elements(course, 2)
    # send first id -> not complete
    r1 = client.post(_seen_url("pc", unit.pk), data=json.dumps([ids[0]]),
                     content_type="application/json")
    assert r1.status_code == 200
    assert r1.json()["completed"] is False
    # send both (cumulative) -> complete
    r2 = client.post(_seen_url("pc", unit.pk), data=json.dumps(ids),
                     content_type="application/json")
    assert r2.json()["completed"] is True
    assert r2.json()["completed_at"] is not None


@pytest.mark.django_db
def test_seen_filters_foreign_and_malformed_returns_200(client):
    user = make_login(client, "p2")
    course = CourseFactory(slug="pf")
    EnrollmentFactory(student=user, course=course)
    unit, ids = _make_unit_with_elements(course, 2)
    r = client.post(_seen_url("pf", unit.pk),
                    data=json.dumps([ids[0], 999999, "x", True]),
                    content_type="application/json")
    assert r.status_code == 200
    assert r.json()["completed"] is False  # only one valid id of two
    # non-list body -> 400
    bad = client.post(_seen_url("pf", unit.pk), data=json.dumps({"a": 1}),
                      content_type="application/json")
    assert bad.status_code == 400


@pytest.mark.django_db
def test_zero_element_unit_completes_only_via_fallback(client):
    user = make_login(client, "p3")
    course = CourseFactory(slug="pz")
    EnrollmentFactory(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    r = client.post(_seen_url("pz", unit.pk), data=json.dumps([]),
                    content_type="application/json")
    assert r.json()["completed"] is False  # empty unit never auto-completes
    comp = client.post(reverse("courses:complete", kwargs={"slug": "pz", "node_pk": unit.pk}))
    assert comp.status_code in (302, 200)
    from courses.models import UnitProgress
    assert UnitProgress.objects.get(student=user, unit=unit).completed is True


@pytest.mark.django_db
def test_quiz_seen_returns_404(client):
    user = make_login(client, "p4")
    course = CourseFactory(slug="pq")
    EnrollmentFactory(student=user, course=course)
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    r = client.post(_seen_url("pq", quiz.pk), data=json.dumps([]),
                    content_type="application/json")
    assert r.status_code == 404


@pytest.mark.django_db
def test_previewer_seen_no_write_synthetic(client):
    from courses.models import UnitProgress

    staff = make_login(client, "staff1")
    staff.is_staff = True
    staff.save()
    course = CourseFactory(slug="pp")  # staff not enrolled
    unit, ids = _make_unit_with_elements(course, 1)
    r = client.post(_seen_url("pp", unit.pk), data=json.dumps(ids),
                    content_type="application/json")
    assert r.status_code == 200
    assert r.json() == {"seen_element_ids": [], "completed": False, "completed_at": None}
    assert not UnitProgress.objects.filter(student=staff, unit=unit).exists()
```

- [ ] **Step 2: Run the tests — they should PASS**

The `seen`/`complete` views were implemented in Task 9 (Step 3b), so these behaviour tests pass immediately.
Run: `uv run pytest tests/test_courses_progress.py -v`
Expected: all PASS. (If any fail, the bug is in the Task 9 endpoint code — fix it there.)

- [ ] **Step 3: Write progress.js**

`courses/static/courses/js/progress.js`:
```javascript
(function () {
  "use strict";
  var lesson = document.querySelector(".lesson[data-seen-url]");
  if (!lesson || !("IntersectionObserver" in window)) return;
  var url = lesson.getAttribute("data-seen-url");
  var seen = new Set();
  var timer = null;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }
  function payload() {
    return JSON.stringify(Array.from(seen));
  }
  // Always fetch+keepalive (NOT sendBeacon): the request needs the X-CSRFToken header,
  // which sendBeacon cannot send. keepalive lets the request outlive the page on unload.
  function flush() {
    if (!seen.size) return;
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: payload(),
      keepalive: true,
    });
  }
  function schedule() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(flush, 500);
  }

  var obs = new IntersectionObserver(function (entries) {
    var added = false;
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        var id = parseInt(e.target.getAttribute("data-element-id"), 10);
        if (!seen.has(id)) { seen.add(id); added = true; }
        obs.unobserve(e.target);
      }
    });
    if (added) schedule();
  }, { threshold: 0, rootMargin: "0px 0px -10% 0px" });

  document.querySelectorAll("[data-element-id]").forEach(function (el) { obs.observe(el); });
  window.addEventListener("pagehide", flush);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") flush();
  });
})();
```

- [ ] **Step 4: Verify boot + full suite**

Run: `uv run python manage.py check`
Expected: no issues.
Run: `uv run pytest -q`
Expected: all PASS (existing suite + new courses tests).

- [ ] **Step 5: Commit**

```bash
git add courses tests/test_courses_progress.py
git commit -m "feat(courses): progress endpoint tests + IntersectionObserver progress.js"
```

---

## Task 11: KaTeX vendoring + math rendering

**Files:**
- Create: `courses/static/courses/vendor/katex/…` (downloaded dist), `courses/static/courses/js/math.js`
- Test: manual collectstatic + an asset-presence assertion

- [ ] **Step 1: Vendor the KaTeX dist (pinned)**

Run (from repo root; downloads the pinned release and copies css/js/fonts into the vendor dir):
```bash
mkdir -p courses/static/courses/vendor/katex
curl -L -o /tmp/katex.tar.gz https://github.com/KaTeX/KaTeX/releases/download/v0.16.11/katex.tar.gz
tar -xzf /tmp/katex.tar.gz -C /tmp
cp /tmp/katex/katex.min.css courses/static/courses/vendor/katex/
cp /tmp/katex/katex.min.js  courses/static/courses/vendor/katex/
cp -r /tmp/katex/fonts       courses/static/courses/vendor/katex/fonts
```
Expected: `courses/static/courses/vendor/katex/` contains `katex.min.css`, `katex.min.js`, and a `fonts/` directory.
(If the environment has no network access, fetch these files by any available means — they are a fixed, pinned vendored dependency. The e2e "no asset 404" check in Task 14 will catch a missing file.)

- [ ] **Step 2: Add the math init script**

`courses/static/courses/js/math.js`:
```javascript
(function () {
  "use strict";
  if (typeof katex === "undefined") return;
  document.querySelectorAll("[data-katex]").forEach(function (el) {
    try {
      katex.render(el.textContent, el, { displayMode: true, throwOnError: false });
    } catch (e) {
      /* leave raw LaTeX on error */
    }
  });
})();
```

- [ ] **Step 3: Verify collectstatic picks up the vendored files**

Run: `uv run python manage.py collectstatic --noinput`
Expected: collects without error; the count includes the KaTeX files. (Clean up `staticfiles/` afterwards if it's git-ignored — check `git status`; it should be ignored.)

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/vendor/katex courses/static/courses/js/math.js
git commit -m "feat(courses): vendor KaTeX + client-side math rendering"
```

---

## Task 12: seed_demo_course management command

**Files:**
- Create: `courses/management/__init__.py`, `courses/management/commands/__init__.py`, `courses/management/commands/seed_demo_course.py`
- Test: `tests/test_seed_demo_course.py` (create)

- [ ] **Step 1: Write the failing tests**

`tests/test_seed_demo_course.py`:
```python
import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_seed_is_idempotent_and_builds_demo():
    from courses.models import Course
    from courses.models import Element
    from courses.models import Enrollment

    call_command("seed_demo_course")
    courses_after_first = Course.objects.count()
    elements_after_first = Element.objects.count()
    enrollments_after_first = Enrollment.objects.count()
    assert courses_after_first == 1
    assert elements_after_first >= 5  # all five element types at least once
    # rerun: no duplicates, no IntegrityError
    call_command("seed_demo_course")
    assert Course.objects.count() == courses_after_first
    assert Element.objects.count() == elements_after_first
    assert Enrollment.objects.count() == enrollments_after_first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_seed_demo_course.py -v`
Expected: FAIL — Unknown command `seed_demo_course`.

- [ ] **Step 3: Implement the command**

`courses/management/__init__.py` and `courses/management/commands/__init__.py` — empty files.

`courses/management/commands/seed_demo_course.py`:
```python
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import Enrollment
from courses.models import IframeElement
from courses.models import ImageElement
from courses.models import MathElement
from courses.models import Subject
from courses.models import TextElement
from courses.models import VideoElement

User = get_user_model()


class Command(BaseCommand):
    help = "Create (idempotently) a demo course, content tree, and an enrolled student."

    @transaction.atomic
    def handle(self, *args, **options):
        subject, _ = Subject.objects.get_or_create(
            slug="demo-subject", defaults={"title": "Demo Subject"}
        )
        course, _ = Course.objects.get_or_create(
            slug="demo-course",
            defaults={"title": "Demo Course", "subject": subject, "language": "en"},
        )
        chapter = self._node(course, None, "chapter", "Chapter 1", None)
        intro = self._node(course, chapter, "unit", "Intro lesson", "lesson", obligatory=True)
        section = self._node(course, chapter, "section", "Section A", None)
        lesson = self._node(course, section, "unit", "Core lesson", "lesson", obligatory=True)
        extra = self._node(course, section, "unit", "Bonus lesson", "lesson", obligatory=False)

        self._text(intro, "intro-text", "<h2>Welcome</h2><p>This is the demo course.</p>")
        self._text(lesson, "core-text", "<p>The core lesson body.</p>")
        self._math(lesson, "core-math", "c = \\pm\\sqrt{a^2 + b^2}")
        self._iframe(lesson, "core-iframe", "https://www.geogebra.org/m/abc")
        self._video(lesson, "core-video", "https://www.youtube.com/embed/dummy")
        self._image(extra, "bonus-image", "Decorative diagram")

        student, created = User.objects.get_or_create(
            username="demo_student", defaults={"display_name": "Demo Student"}
        )
        if created:
            student.set_password("demo-pass-123")
            student.save()
        Enrollment.objects.get_or_create(student=student, course=course)
        self.stdout.write(self.style.SUCCESS("Demo course seeded (idempotent)."))

    def _node(self, course, parent, kind, title, unit_type, obligatory=True):
        node, created = ContentNode.objects.get_or_create(
            course=course,
            parent=parent,
            title=title,
            defaults={"kind": kind, "unit_type": unit_type, "obligatory": obligatory},
        )
        return node

    def _text(self, unit, slug, body):
        self._upsert(unit, TextElement, body=body)

    def _math(self, unit, slug, latex):
        self._upsert(unit, MathElement, latex=latex)

    def _iframe(self, unit, slug, url):
        self._upsert(unit, IframeElement, url=url, title=slug)

    def _video(self, unit, slug, url):
        self._upsert(unit, VideoElement, url=url)

    def _image(self, unit, slug, alt):
        self._upsert(unit, ImageElement, alt=alt, image="courses/images/demo.png")

    def _upsert(self, unit, model, **fields):
        """Idempotently ensure `unit` has exactly one element of `model`.

        Reconciliation key = "the join-row from this unit to an instance of this model".
        On rerun we update the existing concrete row instead of creating a duplicate;
        otherwise we create the concrete row and its join-row.
        """
        existing = Element.objects.filter(
            unit=unit, content_type__model=model._meta.model_name
        ).first()
        if existing and isinstance(existing.content_object, model):
            obj = existing.content_object
            for key, value in fields.items():
                setattr(obj, key, value)
            obj.save()
            return
        obj = model(**fields)
        obj.save()
        Element.objects.create(unit=unit, content_object=obj)
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_seed_demo_course.py -v`
Expected: PASS (both first run and rerun assertions).

- [ ] **Step 5: Commit**

```bash
git add courses/management tests/test_seed_demo_course.py
git commit -m "feat(courses): idempotent seed_demo_course command"
```

---

## Task 13: i18n extraction + Polish + compile

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`

- [ ] **Step 1: Extract new strings**

Run: `uv run python manage.py makemessages -l pl -l en`
Expected: updates the `.po` files with the new `courses` UI strings ("My courses", "required", "additional", "Mark as done", "Quizzes arrive in Phase 2.", "Complete", "You are not enrolled in any courses yet.", "Course outline").

- [ ] **Step 2: Add Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po`, filling `msgstr` for each new `msgid`:
```
"My courses" -> "Moje kursy"
"required" -> "wymagane"
"additional" -> "dodatkowe"
"Mark as done" -> "Oznacz jako ukończone"
"Quizzes arrive in Phase 2." -> "Quizy pojawią się w Etapie 2."
"Complete" -> "Ukończono"
"You are not enrolled in any courses yet." -> "Nie jesteś jeszcze zapisany na żadne kursy."
"Course outline" -> "Plan kursu"
```
(Leave `en` msgstrs empty — English falls back to the msgid.)

- [ ] **Step 3: Compile**

Run: `uv run python manage.py compilemessages`
Expected: produces updated `.mo` files; no errors.

- [ ] **Step 4: Commit**

```bash
git add locale
git commit -m "i18n(courses): extract UI strings + Polish translations + compile"
```

---

## Task 14: Playwright e2e + final DoD pass

**Files:**
- Create: `tests/test_e2e_courses.py`
- Verify: full suite, ruff, migrations, check, collectstatic

- [ ] **Step 1: Write the e2e test**

`tests/test_e2e_courses.py`:
```python
"""Playwright e2e for the lesson consumption path. Marked `e2e` (excluded by default)."""

import os

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed_enrolled_lesson():
    """Build a verified, enrolled student + a one-element lesson; return (username, slug, node_pk)."""
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_verified_user

    user = make_verified_user(username="e2elearner", email="e2el@school.edu")
    course = CourseFactory(slug="e2e-course", language="en")
    EnrollmentFactory(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", title="E2E Lesson")
    text = TextElement.objects.create(body="<p>read me</p>")
    el = Element.objects.create(unit=unit, content_object=text)
    return "e2elearner", course.slug, unit.pk, el.pk


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_lesson_autocompletes_on_view(page, live_server):
    username, slug, node_pk, el_pk = _seed_enrolled_lesson()
    _login(page, live_server, username)
    failures = []
    page.on("response", lambda r: failures.append(r.url) if r.status >= 400 else None)
    page.goto(f"{live_server.url}/courses/{slug}/u/{node_pk}/")
    assert page.locator(f'[data-element-id="{el_pk}"]').is_visible()
    # The single element is on-screen at load -> progress.js flushes -> auto-complete.
    page.wait_for_timeout(1200)  # > 500ms debounce + request
    from courses.models import UnitProgress

    assert UnitProgress.objects.get(unit_id=node_pk).completed is True
    asset_failures = [
        u for u in failures if any(u.endswith(x) for x in (".css", ".js", ".woff2"))
    ]
    assert asset_failures == [], asset_failures


@pytest.mark.django_db(transaction=True)
def test_mark_done_fallback_completes(page, live_server):
    username, slug, node_pk, el_pk = _seed_enrolled_lesson()
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/courses/{slug}/u/{node_pk}/")
    page.locator("form.unit-progress button[type='submit']").click()
    from courses.models import UnitProgress

    assert UnitProgress.objects.get(unit_id=node_pk).completed is True
```

- [ ] **Step 2: Run the e2e suite**

Run: `uv run pytest -m e2e tests/test_e2e_courses.py -v`
Expected: both tests PASS. (Requires the Playwright browser; if not installed, run `uv run playwright install chromium` first.)

- [ ] **Step 3: Final Definition-of-Done sweep**

Run each and confirm clean:
```bash
uv run ruff check --fix   # auto-fixes import ordering (imports were added incrementally)
uv run ruff format
uv run ruff check         # must now report no remaining issues
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py collectstatic --noinput
uv run pytest -q
```
Expected: ruff clean; `makemigrations --check` reports no changes; `check` clean; collectstatic OK; full default suite (`-m 'not e2e'`) green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_courses.py
git commit -m "test(courses): Playwright e2e — lesson auto-complete + mark-done fallback"
```

---

## Self-Review notes (author)

- **Spec coverage:** schema (T2–T6), 5 element renderers (T4–T5, T11), my-courses/outline + rollups + access (T7–T8), lesson view + quiz placeholder + has_math (T9), progress endpoints + JS + no-JS fallback (T9–T10), security/validation (T4 sanitisation, T5 embed whitelist, T7 scoping/IDOR), i18n + `lang` (T8/T9 templates, T13), seed (T12), tests incl. e2e (every task + T14). Every spec success-criterion maps to a task.
- **Deferred/explicitly-out-of-scope** items (bespoke authoring UI, HTML element, quiz behaviour, grouping/self-enroll, notes/tags, DRF, prod media serving) are not implemented — correct.
- **Type/name consistency:** `get_node_or_404(require_unit=, require_lesson=)`, `can_access_course`, `is_enrolled`, `build_outline` keys (`required_total/required_done/additional_done/is_unit/completed`), `_progress_json` shape `{seen_element_ids, completed, completed_at}` are used identically across tasks.
- **No forward dependencies between tasks.** The `seen`/`complete` views live in Task 9 (with the lesson view + URLs that reverse them), so every task ends green and self-contained. Task 10 only adds behaviour tests for those views plus `progress.js`.
- **Grounded deviation from the spec — flush transport.** The spec named `navigator.sendBeacon` *or* `fetch(keepalive)`; the plan uses **`fetch(keepalive)` exclusively** because `sendBeacon` cannot send the `X-CSRFToken` header, and CSRF-exempting the endpoint is the exact anti-pattern the Packt review flagged. `fetch(keepalive)` carries the header and still survives page unload. This stays within the spec's stated options and keeps CSRF protection intact.
