# Phase 4b — Personal Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user attach private, reusable, colour-coded **tags** to any **unit** (lesson or quiz), edit them from the unit page and the course outline, filter the outline by tag, and browse/manage all their tags across courses from a "My tags" page.

**Architecture:** A new self-contained `tags` Django app paralleling `notes`/`grouping`: two models (`Tag`, `UnitTag` M2M-through to `courses.ContentNode`), a `tags/services.py` choke-point for all mutation/query, function-based views (unit tag add/remove + tag rename/recolour/delete + "My tags"), templates restyled responsively, and a `tags.js`/`tags.css` enhancement layer. One small refactor in `courses/access.py` adds an `accessible_courses(user)` queryset that `can_access_course` then delegates to (single source of truth). Integration into `courses` is additive: the outline and both unit-consumption views inject tag context.

**Tech Stack:** Django (function views, `gettext_lazy` i18n), PostgreSQL, pytest + factory_boy, vanilla progressive-enhancement JS, Playwright for e2e. Tooling is via **`uv run`** (bash `ruff`/`pytest`/`python` are NOT on PATH).

**Spec:** `docs/superpowers/specs/2026-06-28-phase-4b-tags-design.md` (read it before starting). Validated mockups: `docs/mockups/phase-4b-tags-0{1,2,3}-*.html`.

## Global Constraints

- **Tooling:** run all commands with `uv run` — `uv run pytest …`, `uv run ruff check .`, `uv run ruff format .`, `uv run python manage.py …`. CI checks `ruff format --check`, so run `uv run ruff format .` after each task.
- **Tests:** pytest + factory_boy against PostgreSQL. Every service/view task is TDD (failing test first). At least one **e2e** drives the real gesture with **no `page.evaluate` shortcuts**.
- **Auth:** every `tags:` view is `@login_required`; the unit panel + outline chips render only for an authenticated `request.user`.
- **Privacy/security:** tag-scoped ops are author-scoped via service-level `get_object_or_404(Tag, pk=…, author=author)` → foreign pk yields **404** (never 403, no existence leak). Unit-scoped add/remove additionally gate the unit: `get_node_or_404(node_pk, slug, require_unit=True)` then `can_access_course` (404 before 403). Tag names are plain text, **escaped on output**.
- **Colour:** a fixed palette `TAG_PALETTE` (8 keys); the field uses `choices=[(k, k) for k in TAG_PALETTE]`. Default colour = `TAG_PALETTE[zlib.crc32(name.encode()) % TAG_PALETTE_SIZE]` (process-stable — never Python's salted `hash()`).
- **Names:** normalized `" ".join(raw.split())`; non-empty; ≤ `TAG_NAME_MAX_LEN = 50`; **case-insensitively unique per author** (`UniqueConstraint(Lower("name"), "author")`).
- **i18n:** all user-facing strings `gettext_lazy`; EN+PL catalogs compiled; PL catalog has **0 fuzzy / 0 obsolete**; JS labels read from a `#tags-i18n` `data-*` element (never hard-coded English). Watch the makemessages fuzzy mis-guess gotcha — grep new msgids and verify.
- **Light/dark + responsive:** palette + chrome use existing design tokens; verify both themes via throwaway Playwright screenshots before the final commit. One markup per surface, restyled by CSS (no dual render).

---

### Task 1: `tags` app skeleton + models + migration

**Files:**
- Create: `tags/__init__.py`, `tags/apps.py`, `tags/models.py`, `tags/migrations/__init__.py`
- Modify: `config/settings/base.py` (INSTALLED_APPS, after `"notes"`)
- Modify: `tests/factories.py` (add `TagFactory`, `UnitTagFactory`)
- Test: `tests/test_tags_models.py`

**Interfaces:**
- Produces: `tags.models.Tag(author, name, color, created)`; `tags.models.UnitTag(tag, unit, created)`; constants `TAG_PALETTE: list[str]`, `TAG_PALETTE_SIZE: int`, `TAG_NAME_MAX_LEN = 50`. `Tag.unit_tags` (reverse of `UnitTag.tag`) is used by `Count("unit_tags")`. `ContentNode.tags` (M2M reverse) and `ContentNode.unit_tags` (FK reverse) both resolve.

- [ ] **Step 1: Create the app package**

`tags/__init__.py` — empty file.

`tags/apps.py`:
```python
from django.apps import AppConfig


class TagsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tags"
```

`tags/migrations/__init__.py` — empty file.

- [ ] **Step 2: Register the app**

In `config/settings/base.py`, add `"tags",` to `INSTALLED_APPS` immediately after `"notes",` (line 37).

- [ ] **Step 3: Write `tags/models.py`**

```python
import zlib

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

TAG_NAME_MAX_LEN = 50
TAG_PALETTE = ["teal", "amber", "indigo", "rose", "green", "violet", "slate", "cyan"]
TAG_PALETTE_SIZE = len(TAG_PALETTE)


def default_color_for(name):
    """Process-stable palette default (crc32, NOT salted built-in hash())."""
    return TAG_PALETTE[zlib.crc32(name.encode("utf-8")) % TAG_PALETTE_SIZE]


class Tag(models.Model):
    """A private, reusable, named, colour-coded label one user applies to units."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags"
    )
    name = models.CharField(max_length=TAG_NAME_MAX_LEN)
    color = models.CharField(
        max_length=20, choices=[(k, k) for k in TAG_PALETTE], default=TAG_PALETTE[0]
    )
    units = models.ManyToManyField(
        "courses.ContentNode", through="UnitTag", related_name="tags"
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [Lower("name"), "pk"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "author", name="uniq_tag_author_lower_name"
            )
        ]

    def __str__(self):
        return self.name


class UnitTag(models.Model):
    """Join-row: this tag is on this unit (lesson or quiz)."""

    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="unit_tags")
    unit = models.ForeignKey(
        "courses.ContentNode",
        on_delete=models.CASCADE,
        related_name="unit_tags",
        limit_choices_to={"kind": "unit"},
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created", "pk"]
        constraints = [
            models.UniqueConstraint("tag", "unit", name="uniq_unittag_tag_unit")
        ]
        indexes = [
            models.Index(fields=["unit"]),
            models.Index(fields=["tag"]),
        ]

    def __str__(self):
        return f"UnitTag(tag={self.tag_id}, unit={self.unit_id})"
```

- [ ] **Step 4: Add factories** to `tests/factories.py` (after `NoteFactory`)

```python
class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "tags.Tag"

    author = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"tag{n}")
    color = "teal"


class UnitTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "tags.UnitTag"

    tag = factory.SubFactory(TagFactory)
    unit = factory.SubFactory(ContentNodeFactory)  # lesson unit by default
```

- [ ] **Step 5: Write the failing tests** `tests/test_tags_models.py`

```python
import pytest
from django.db import IntegrityError
from django.db.models.functions import Lower

from tags.models import TAG_PALETTE, Tag, UnitTag, default_color_for
from tests.factories import (
    ContentNodeFactory,
    TagFactory,
    UnitTagFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


def test_default_color_is_stable_and_in_palette():
    c1 = default_color_for("exam")
    c2 = default_color_for("exam")
    assert c1 == c2
    assert c1 in TAG_PALETTE


def test_case_insensitive_unique_per_author():
    user = UserFactory()
    TagFactory(author=user, name="Exam")
    with pytest.raises(IntegrityError):
        Tag.objects.create(author=user, name="exam", color="teal")


def test_same_name_different_authors_ok():
    TagFactory(author=UserFactory(), name="Exam")
    TagFactory(author=UserFactory(), name="Exam")  # no error


def test_unittag_unique_per_tag_unit():
    tag = TagFactory()
    unit = ContentNodeFactory()
    UnitTagFactory(tag=tag, unit=unit)
    with pytest.raises(IntegrityError):
        UnitTag.objects.create(tag=tag, unit=unit)


def test_tag_ordering_is_case_insensitive():
    user = UserFactory()
    TagFactory(author=user, name="Zebra")
    TagFactory(author=user, name="apple")
    names = list(Tag.objects.filter(author=user).values_list("name", flat=True))
    assert names == ["apple", "Zebra"]
```

- [ ] **Step 6: Generate + run the migration**

```bash
uv run python manage.py makemigrations tags
uv run pytest tests/test_tags_models.py -v
```
Expected: migration `tags/0001_initial.py` created; all 5 tests PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/ tests/factories.py tests/test_tags_models.py config/settings/base.py
git commit -m "feat(4b): tags app models (Tag, UnitTag) + migration"
```

---

### Task 2: `accessible_courses(user)` helper + `can_access_course` delegation

**Files:**
- Modify: `courses/access.py`
- Test: `tests/test_tags_access.py`

**Interfaces:**
- Produces: `courses.access.accessible_courses(user) -> QuerySet[Course]` (staff/superuser ⇒ all; else owned ∪ enrolled; anonymous ⇒ none). `can_access_course(user, course)` now delegates to it — **parity is guaranteed by construction**.

- [ ] **Step 1: Write the failing parity test** `tests/test_tags_access.py`

```python
import pytest

from courses.access import accessible_courses, can_access_course
from courses.models import Enrollment
from tests.factories import CourseFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_accessible_courses_matches_can_access_for_every_role():
    owner = UserFactory()
    enrolled = UserFactory()
    outsider = UserFactory()
    staff = UserFactory(is_staff=True)

    owned = CourseFactory(owner=owner)
    joined = CourseFactory()
    other = CourseFactory()
    Enrollment.objects.create(student=enrolled, course=joined)

    for user in (owner, enrolled, outsider, staff):
        accessible_pks = set(accessible_courses(user).values_list("pk", flat=True))
        for course in (owned, joined, other):
            assert (course.pk in accessible_pks) == can_access_course(user, course), (
                user,
                course.pk,
            )


def test_accessible_courses_anonymous_is_empty():
    from django.contrib.auth.models import AnonymousUser

    CourseFactory()
    assert accessible_courses(AnonymousUser()).count() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tags_access.py -v`
Expected: FAIL with `ImportError: cannot import name 'accessible_courses'`.

- [ ] **Step 3: Implement in `courses/access.py`**

Add imports at top (`from django.db.models import Q`, and `Course`, `Enrollment` from `courses.models`), then:
```python
def accessible_courses(user):
    """Courses `user` may access, as a queryset (single source of truth for
    can_access_course): staff/superuser ⇒ all; else owned ∪ enrolled."""
    if not user.is_authenticated:
        return Course.objects.none()
    if user.is_staff:
        return Course.objects.all()
    enrolled = Enrollment.objects.filter(student=user).values("course_id")
    return Course.objects.filter(Q(pk__in=enrolled) | Q(owner=user)).distinct()
```

Then refactor `can_access_course` to delegate:
```python
def can_access_course(user, course):
    """Enrolled OR staff OR owner — delegates to accessible_courses (single source)."""
    return accessible_courses(user).filter(pk=course.pk).exists()
```

- [ ] **Step 4: Run the new test + the full suite (no regressions in the existing access-dependent tests)**

```bash
uv run pytest tests/test_tags_access.py -v
uv run pytest -q
```
Expected: new tests PASS; full suite still green (the delegation is behaviour-preserving).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/access.py tests/test_tags_access.py
git commit -m "feat(4b): accessible_courses(user) queryset; can_access_course delegates"
```

---

### Task 3: Name normalization, validation & colour default (`tags/services.py` part 1)

**Files:**
- Create: `tags/services.py`
- Test: `tests/test_tags_services.py`

**Interfaces:**
- Produces: `normalize_name(raw) -> str`; `_clean_name(raw) -> str` (raises `django.core.exceptions.ValidationError` on empty/over-long). Reuses `tags.models.default_color_for`.

- [ ] **Step 1: Write the failing tests** `tests/test_tags_services.py`

```python
import pytest
from django.core.exceptions import ValidationError

from tags import services
from tags.models import TAG_NAME_MAX_LEN

pytestmark = pytest.mark.django_db


def test_normalize_name_collapses_whitespace():
    assert services.normalize_name("  to   do \n") == "to do"


def test_clean_name_rejects_empty():
    with pytest.raises(ValidationError):
        services._clean_name("   ")


def test_clean_name_rejects_over_length():
    with pytest.raises(ValidationError):
        services._clean_name("x" * (TAG_NAME_MAX_LEN + 1))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_services.py -v`
Expected: FAIL (`ModuleNotFoundError: tags.services`).

- [ ] **Step 3: Implement `tags/services.py`**

```python
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from tags.models import TAG_NAME_MAX_LEN, default_color_for


def normalize_name(raw):
    """Collapse all whitespace runs to single spaces; strip ends."""
    return " ".join((raw or "").split())


def _clean_name(raw):
    name = normalize_name(raw)
    if not name:
        raise ValidationError(_("Enter a tag name."))
    if len(name) > TAG_NAME_MAX_LEN:
        raise ValidationError(
            _("Tag name is too long (max %(n)d characters).") % {"n": TAG_NAME_MAX_LEN}
        )
    return name
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tags_services.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/services.py tests/test_tags_services.py
git commit -m "feat(4b): tag name normalization + validation service"
```

---

### Task 4: Tag lifecycle services — reuse/create, rename, recolour, delete, list

**Files:**
- Modify: `tags/services.py`
- Test: `tests/test_tags_services.py`

**Interfaces:**
- Produces:
  - `_reuse_or_create_tag(author, name) -> Tag` (case-insensitive reuse; `IntegrityError` re-query on race)
  - `rename_tag(author, tag_pk, name) -> Tag` (self-excluding collision check; preserves colour; `IntegrityError` backstop) — raises `ValidationError` on collision, `Http404` on foreign pk
  - `recolor_tag(author, tag_pk, color) -> Tag` (invalid key ⇒ `ValidationError`)
  - `delete_tag(author, tag_pk) -> int` (snapshots **accessible** count, then cascades, returns snapshot)
  - `list_tags(author) -> list[Tag]` (each annotated `.unit_count`, accessible-only)
  - `_accessible_unit_count(author, tag) -> int`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_tags_services.py`)

```python
from courses.models import Enrollment
from django.http import Http404
from tags.models import Tag, UnitTag
from tests.factories import (
    ContentNodeFactory,
    CourseFactory,
    TagFactory,
    UnitTagFactory,
    UserFactory,
)


def test_reuse_or_create_is_case_insensitive():
    user = UserFactory()
    a = services._reuse_or_create_tag(user, "Exam")
    b = services._reuse_or_create_tag(user, "  exam ")
    assert a.pk == b.pk
    assert Tag.objects.filter(author=user).count() == 1


def test_rename_allows_recasing_own_name():
    tag = TagFactory(name="exam")
    services.rename_tag(tag.author, tag.pk, "Exam")
    tag.refresh_from_db()
    assert tag.name == "Exam"


def test_rename_rejects_collision_with_other_tag():
    user = UserFactory()
    TagFactory(author=user, name="exam")
    other = TagFactory(author=user, name="hard")
    with pytest.raises(ValidationError):
        services.rename_tag(user, other.pk, "EXAM")


def test_rename_preserves_colour():
    tag = TagFactory(name="exam", color="rose")
    services.rename_tag(tag.author, tag.pk, "exams")
    tag.refresh_from_db()
    assert tag.color == "rose"


def test_rename_foreign_tag_404():
    tag = TagFactory()
    with pytest.raises(Http404):
        services.rename_tag(UserFactory(), tag.pk, "x")


def test_recolor_rejects_invalid_key():
    tag = TagFactory()
    with pytest.raises(ValidationError):
        services.recolor_tag(tag.author, tag.pk, "not-a-colour")


def test_delete_tag_returns_accessible_count_then_cascades():
    user = UserFactory()
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course)
    tag = TagFactory(author=user)
    UnitTagFactory(tag=tag, unit=unit)
    n = services.delete_tag(user, tag.pk)
    assert n == 1
    assert not Tag.objects.filter(pk=tag.pk).exists()
    assert not UnitTag.objects.filter(tag_id=tag.pk).exists()


def test_list_tags_unit_count_excludes_inaccessible():
    user = UserFactory()
    reachable = CourseFactory()
    Enrollment.objects.create(student=user, course=reachable)
    unreachable = CourseFactory()
    tag = TagFactory(author=user, name="exam")
    UnitTagFactory(tag=tag, unit=ContentNodeFactory(course=reachable))
    UnitTagFactory(tag=tag, unit=ContentNodeFactory(course=unreachable))
    [t] = services.list_tags(user)
    assert t.unit_count == 1  # the inaccessible one is not counted
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_services.py -v`
Expected: the new tests FAIL (attributes/functions undefined).

- [ ] **Step 3: Implement** (append to `tags/services.py`; add imports)

```python
from collections import OrderedDict, defaultdict

from django.db import IntegrityError
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404

from courses.access import accessible_courses
from courses.models import ContentNode
from tags.models import TAG_PALETTE, Tag, UnitTag


def _reuse_or_create_tag(author, name):
    name = _clean_name(name)
    existing = Tag.objects.filter(author=author, name__iexact=name).first()
    if existing:
        return existing
    try:
        return Tag.objects.create(
            author=author, name=name, color=default_color_for(name)
        )
    except IntegrityError:  # concurrent insert hit the Lower(name) constraint
        return Tag.objects.get(author=author, name__iexact=name)


def rename_tag(author, tag_pk, name):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    name = _clean_name(name)
    clash = (
        Tag.objects.filter(author=author, name__iexact=name)
        .exclude(pk=tag.pk)
        .exists()
    )
    if clash:
        raise ValidationError(_("You already have a tag with this name."))
    tag.name = name
    try:
        tag.save(update_fields=["name"])
    except IntegrityError:  # concurrent same-author rename race
        raise ValidationError(_("You already have a tag with this name."))
    return tag


def recolor_tag(author, tag_pk, color):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    if color not in TAG_PALETTE:
        raise ValidationError(_("Invalid colour."))
    tag.color = color
    tag.save(update_fields=["color"])
    return tag


def _accessible_unit_count(author, tag):
    return UnitTag.objects.filter(
        tag=tag, unit__course__in=accessible_courses(author)
    ).count()


def delete_tag(author, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    count = _accessible_unit_count(author, tag)  # snapshot BEFORE cascade
    tag.delete()
    return count


def list_tags(author):
    accessible = accessible_courses(author)
    return list(
        Tag.objects.filter(author=author).annotate(
            unit_count=Count(
                "unit_tags", filter=Q(unit_tags__unit__course__in=accessible)
            )
        )
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tags_services.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/services.py tests/test_tags_services.py
git commit -m "feat(4b): tag lifecycle services (reuse/rename/recolour/delete/list)"
```

---

### Task 5: Unit-tagging services — tag/untag a unit, tags-for-unit

**Files:**
- Modify: `tags/services.py`
- Test: `tests/test_tags_services.py`

**Interfaces:**
- Produces:
  - `tag_unit(author, unit, name) -> UnitTag` (reuse-or-create tag, idempotent link)
  - `tag_unit_by_id(author, unit, tag_pk) -> UnitTag` (foreign pk ⇒ `Http404`; idempotent)
  - `untag_unit(author, unit, tag_pk) -> None` (foreign pk ⇒ `Http404`; idempotent delete)
  - `tags_for_unit(author, unit) -> list[Tag]` (ordered by `Lower(name)`, pk)

- [ ] **Step 1: Write the failing tests** (append)

```python
def test_tag_unit_is_idempotent():
    unit = ContentNodeFactory()
    user = UserFactory()
    services.tag_unit(user, unit, "exam")
    services.tag_unit(user, unit, "Exam")  # same tag, same unit
    assert UnitTag.objects.filter(unit=unit, tag__author=user).count() == 1


def test_tag_unit_allows_quiz_unit():
    quiz = ContentNodeFactory(unit_type="quiz")
    user = UserFactory()
    services.tag_unit(user, quiz, "revise")
    assert UnitTag.objects.filter(unit=quiz).count() == 1


def test_tag_unit_by_id_foreign_tag_404():
    foreign = TagFactory()
    with pytest.raises(Http404):
        services.tag_unit_by_id(UserFactory(), ContentNodeFactory(), foreign.pk)


def test_untag_unit_is_idempotent_and_keeps_unused_tag():
    unit = ContentNodeFactory()
    user = UserFactory()
    ut = services.tag_unit(user, unit, "exam")
    services.untag_unit(user, unit, ut.tag_id)
    services.untag_unit(user, unit, ut.tag_id)  # no error second time
    assert not UnitTag.objects.filter(unit=unit).exists()
    assert Tag.objects.filter(pk=ut.tag_id).exists()  # tag survives


def test_untag_unit_foreign_tag_404():
    foreign = TagFactory()
    with pytest.raises(Http404):
        services.untag_unit(UserFactory(), ContentNodeFactory(), foreign.pk)


def test_tags_for_unit_ordered_case_insensitive():
    unit = ContentNodeFactory()
    user = UserFactory()
    services.tag_unit(user, unit, "Zebra")
    services.tag_unit(user, unit, "apple")
    assert [t.name for t in services.tags_for_unit(user, unit)] == ["apple", "Zebra"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_services.py -k unit -v`
Expected: FAIL (functions undefined).

- [ ] **Step 3: Implement** (append to `tags/services.py`)

```python
def tag_unit(author, unit, name):
    tag = _reuse_or_create_tag(author, name)
    link, _created = UnitTag.objects.get_or_create(tag=tag, unit=unit)
    return link


def tag_unit_by_id(author, unit, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    link, _created = UnitTag.objects.get_or_create(tag=tag, unit=unit)
    return link


def untag_unit(author, unit, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=author)
    UnitTag.objects.filter(tag=tag, unit=unit).delete()


def tags_for_unit(author, unit):
    return list(
        Tag.objects.filter(author=author, unit_tags__unit=unit).order_by(
            Lower("name"), "pk"
        )
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tags_services.py -k unit -v`
Expected: all PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/services.py tests/test_tags_services.py
git commit -m "feat(4b): unit tagging services (tag/untag/tags_for_unit)"
```

---

### Task 6: Outline & My-tags query services + visibility annotation

**Files:**
- Modify: `tags/services.py`
- Test: `tests/test_tags_services.py`

**Interfaces:**
- Produces:
  - `tags_for_outline(author, course) -> (dict[int, list[Tag]], list[Tag])` (`tags_by_unit`, name-ordered `course_tags`)
  - `outline_with_tags(outline, tags_by_unit, active_ids) -> outline` (mutates each node dict: adds `tags` for units, `tag_hidden` per the recursive rule; empty `active_ids` ⇒ nothing hidden)
  - `filter_chip_hrefs(base, course_tags, active_ids) -> list[dict]` (`{tag, active, href}`; toggle semantics)
  - `units_by_tag(author) -> list[(Tag, OrderedDict[Course, list[ContentNode]])]` (accessible only; courses by title, units by outline order; zero-unit tags retained)

- [ ] **Step 1: Write the failing tests** (append)

```python
from courses.rollups import build_outline


def test_outline_with_tags_empty_active_hides_nothing():
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    unit = ContentNodeFactory(course=course, parent=part, unit_type="lesson")
    user = UserFactory()
    by_unit, _ = services.tags_for_outline(user, course)
    outline = services.outline_with_tags(build_outline(course, user), by_unit, [])
    assert outline[0]["tag_hidden"] is False
    assert outline[0]["children"][0]["tag_hidden"] is False


def test_outline_with_tags_prunes_unmatched_and_empty_ancestors():
    course = CourseFactory()
    user = UserFactory()
    p1 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    u_match = ContentNodeFactory(course=course, parent=p1, unit_type="lesson")
    p2 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    ContentNodeFactory(course=course, parent=p2, unit_type="lesson")  # no tag
    exam = services.tag_unit(user, u_match, "exam").tag
    by_unit, _ = services.tags_for_outline(user, course)
    outline = services.outline_with_tags(build_outline(course, user), by_unit, [exam.pk])
    nodes = {d["node"].pk: d for d in outline}
    assert nodes[p1.pk]["tag_hidden"] is False  # has a matching descendant
    assert nodes[p1.pk]["children"][0]["tag_hidden"] is False
    assert nodes[p2.pk]["tag_hidden"] is True  # no matching descendant


def test_filter_chip_hrefs_toggle():
    user = UserFactory()
    t1 = TagFactory(author=user, name="exam")
    t2 = TagFactory(author=user, name="hard")
    chips = services.filter_chip_hrefs("/c/x/", [t1, t2], [t1.pk])
    by_tag = {c["tag"].pk: c for c in chips}
    assert by_tag[t1.pk]["active"] is True
    assert by_tag[t1.pk]["href"] == "/c/x/"  # active → clears itself
    assert f"tags={t1.pk}" in by_tag[t2.pk]["href"]
    assert f"tags={t2.pk}" in by_tag[t2.pk]["href"]  # inactive → adds itself


def test_units_by_tag_groups_accessible_only_and_keeps_zero():
    user = UserFactory()
    reachable = CourseFactory(title="Bio")
    Enrollment.objects.create(student=user, course=reachable)
    unit = ContentNodeFactory(course=reachable)
    used = services.tag_unit(user, unit, "exam").tag
    TagFactory(author=user, name="later")  # zero units
    result = dict((t.name, grouped) for t, grouped in services.units_by_tag(user))
    assert list(result["exam"].keys())[0].pk == reachable.pk
    assert not result["later"]  # zero-unit tag retained, empty grouping


def test_units_by_tag_orders_units_by_outline_position():
    user = UserFactory()
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    p1 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    p2 = ContentNodeFactory(course=course, kind="part", unit_type=None)
    # Units under different parents: per-parent `order` would interleave; pre-order
    # must yield p1's unit before p2's unit.
    first = ContentNodeFactory(course=course, parent=p1, unit_type="lesson", title="A")
    second = ContentNodeFactory(course=course, parent=p2, unit_type="lesson", title="B")
    services.tag_unit(user, second, "exam")
    services.tag_unit(user, first, "exam")
    [(tag, grouped)] = services.units_by_tag(user)
    titles = [u.title for u in grouped[course]]
    assert titles == ["A", "B"]  # outline order, not tag/insert order
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_services.py -k "outline or chip or units_by_tag" -v`
Expected: FAIL.

- [ ] **Step 3: Implement** (append to `tags/services.py`)

```python
def tags_for_outline(author, course):
    """({unit_pk: [Tag, ...]}, [Tag, ...]) — per-unit chips + the in-course tag set."""
    qs = (
        UnitTag.objects.filter(tag__author=author, unit__course=course)
        .select_related("tag")
        .order_by(Lower("tag__name"), "tag__pk")
    )
    tags_by_unit = defaultdict(list)
    course_tags = []
    seen = set()
    for ut in qs:
        tags_by_unit[ut.unit_id].append(ut.tag)
        if ut.tag_id not in seen:
            seen.add(ut.tag_id)
            course_tags.append(ut.tag)
    return dict(tags_by_unit), course_tags


def outline_with_tags(outline, tags_by_unit, active_ids):
    """Annotate each build_outline node dict in place: `tags` (units) + `tag_hidden`.

    Empty active set ⇒ nothing hidden. Otherwise: a unit is visible iff it carries
    ≥1 active tag; a container is visible iff ≥1 descendant unit is visible.
    """
    active = set(active_ids)

    def visit(d):
        if d["is_unit"]:
            tags = tags_by_unit.get(d["node"].pk, [])
            d["tags"] = tags
            d["tag_hidden"] = bool(active) and not any(t.pk in active for t in tags)
            return not d["tag_hidden"]
        any_visible = False
        for child in d["children"]:
            if visit(child):
                any_visible = True
        d["tag_hidden"] = bool(active) and not any_visible
        return not d["tag_hidden"]

    for root in outline:
        visit(root)
    return outline


def filter_chip_hrefs(base, course_tags, active_ids):
    """[{tag, active, href}] — each href toggles that tag in/out of the active set."""
    active = set(active_ids)
    chips = []
    for tag in course_tags:
        if tag.pk in active:
            ids = [i for i in active_ids if i != tag.pk]
        else:
            ids = active_ids + [tag.pk]
        query = "&".join(f"tags={i}" for i in ids)
        chips.append(
            {"tag": tag, "active": tag.pk in active, "href": f"{base}?{query}" if query else base}
        )
    return chips


def units_by_tag(author):
    """[(Tag, {Course: [unit, ...]})] for the My tags page (accessible courses only).

    Courses ordered by title; units within a course in true **outline (pre-order)**
    position. NB: `ContentNode.order` is per-parent (`OrderField(for_fields=
    ["course","parent"])`), so units under different parents share order values — a flat
    `order` sort would interleave them. We index each course's pre-order walk instead.
    """
    from courses.rollups import _walk_preorder

    accessible = accessible_courses(author)
    result = []
    for tag in list_tags(author):  # ordered, carries accessible unit_count
        links = (
            UnitTag.objects.filter(tag=tag, unit__course__in=accessible)
            .select_related("unit", "unit__course")
        )
        by_course = defaultdict(list)
        for link in links:
            by_course[link.unit.course].append(link.unit)
        grouped = OrderedDict()
        for course in sorted(by_course, key=lambda c: c.title):
            order_index = {n.pk: i for i, n in enumerate(_walk_preorder(course))}
            grouped[course] = sorted(
                by_course[course], key=lambda u: order_index.get(u.pk, 1 << 30)
            )
        result.append((tag, grouped))
    return result
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_tags_services.py -v`
Expected: every service test PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/services.py tests/test_tags_services.py
git commit -m "feat(4b): outline + my-tags query services & visibility annotation"
```

---

### Task 7: URLs + unit tag add/remove views

**Files:**
- Create: `tags/urls.py`, `tags/views.py`
- Modify: `config/urls.py` (include after `notes.urls`)
- Test: `tests/test_tags_views.py`

**Interfaces:**
- Produces URL names `tags:tag_add`, `tags:tag_remove` (unit-scoped) and view helpers `_wants_fragment`, `_unit_url`, `_panel_context`. `tag_add` POST dispatch: ≥1 `tag_pk` (getlist) ⇒ `tag_unit_by_id` each; else non-empty `name` ⇒ `tag_unit`; neither ⇒ 422.

- [ ] **Step 1: Write the failing view tests** `tests/test_tags_views.py`

```python
import pytest
from django.urls import reverse

from courses.models import Enrollment
from tags.models import Tag, UnitTag
from tests.factories import ContentNodeFactory, CourseFactory, TagFactory, UserFactory

pytestmark = pytest.mark.django_db


def _enrolled_unit(user, **kw):
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    return ContentNodeFactory(course=course, **kw)


def test_tag_add_by_name_creates_link(client):
    user = UserFactory()
    client.force_login(user)
    unit = _enrolled_unit(user)
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    resp = client.post(url, {"name": "exam"})
    assert resp.status_code == 302
    assert UnitTag.objects.filter(unit=unit, tag__author=user).count() == 1


def test_tag_add_by_multiple_tag_pks(client):
    user = UserFactory()
    client.force_login(user)
    unit = _enrolled_unit(user)
    t1 = TagFactory(author=user)
    t2 = TagFactory(author=user)
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    client.post(url, {"tag_pk": [t1.pk, t2.pk]})
    assert UnitTag.objects.filter(unit=unit).count() == 2


def test_tag_add_empty_is_422(client):
    user = UserFactory()
    client.force_login(user)
    unit = _enrolled_unit(user)
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    resp = client.post(url, {"name": "  "})
    assert resp.status_code == 422
    assert UnitTag.objects.filter(unit=unit).count() == 0


def test_tag_add_inaccessible_course_403(client):
    user = UserFactory()
    client.force_login(user)
    unit = ContentNodeFactory(course=CourseFactory())  # not enrolled
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    assert client.post(url, {"name": "x"}).status_code == 403


def test_tag_add_foreign_tag_pk_404(client):
    user = UserFactory()
    client.force_login(user)
    unit = _enrolled_unit(user)
    foreign = TagFactory()
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    assert client.post(url, {"tag_pk": [foreign.pk]}).status_code == 404


def test_tag_add_requires_login(client):
    unit = ContentNodeFactory()
    url = reverse("tags:tag_add", args=[unit.course.slug, unit.pk])
    resp = client.post(url, {"name": "x"})
    assert resp.status_code == 302 and "/login" in resp.url


def test_tag_remove_deletes_link(client):
    user = UserFactory()
    client.force_login(user)
    unit = _enrolled_unit(user)
    from tags import services

    ut = services.tag_unit(user, unit, "exam")
    url = reverse("tags:tag_remove", args=[unit.course.slug, unit.pk])
    client.post(url, {"tag_pk": ut.tag_id})
    assert not UnitTag.objects.filter(unit=unit).exists()
    assert Tag.objects.filter(pk=ut.tag_id).exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_views.py -v`
Expected: FAIL (`NoReverseMatch` / module missing).

- [ ] **Step 3: Create `tags/urls.py`**

```python
from django.urls import path

from tags import views

app_name = "tags"

urlpatterns = [
    path(
        "courses/<slug:slug>/u/<int:node_pk>/tags/add/",
        views.tag_add,
        name="tag_add",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/tags/remove/",
        views.tag_remove,
        name="tag_remove",
    ),
]
```

- [ ] **Step 4: Wire into `config/urls.py`**

Add `path("", include("tags.urls")),` immediately after the `notes.urls` include (line 25).

- [ ] **Step 5: Create `tags/views.py`**

```python
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from courses.access import can_access_course, get_node_or_404
from tags import services
from tags.rendering import unit_tags_context


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _unit_url(unit):
    name = (
        "courses:quiz_unit"
        if unit.unit_type == "quiz"
        else "courses:lesson_unit"
    )
    return reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})


def _panel_response(request, unit, *, status=200, error=None, draft=""):
    ctx = unit_tags_context(request.user, unit, panel_open=True)
    ctx.update(course=unit.course, unit=unit, tag_error=error, tag_draft=draft)
    return render(request, "tags/_unit_tag_panel.html", ctx, status=status)


@login_required
@require_POST
def tag_add(request, slug, node_pk):
    unit = get_node_or_404(node_pk, slug, require_unit=True)
    if not can_access_course(request.user, unit.course):
        raise PermissionDenied
    tag_pks = request.POST.getlist("tag_pk")
    name = request.POST.get("name", "")
    if tag_pks:
        # atomic so a foreign id later in the list leaves no partial links (it 404s)
        with transaction.atomic():
            for pk in tag_pks:
                services.tag_unit_by_id(request.user, unit, pk)
    elif name.strip():
        try:
            services.tag_unit(request.user, unit, name)
        except ValidationError as exc:
            return _add_error(request, unit, name, exc)
    else:
        return _add_error(request, unit, "", ValidationError(_("Enter a tag name or pick a tag.")))
    if _wants_fragment(request):
        return _panel_response(request, unit)
    return redirect(_unit_url(unit) + "?panel=tags")


def _add_error(request, unit, draft, exc):
    msg = exc.messages[0] if hasattr(exc, "messages") else str(exc)
    if _wants_fragment(request):
        return _panel_response(request, unit, status=422, error=msg, draft=draft)
    ctx = unit_tags_context(request.user, unit, panel_open=True)
    ctx.update(course=unit.course, unit=unit, tag_error=msg, tag_draft=draft)
    # Re-render the unit page would require its full context; for the no-JS error
    # path we render the standalone panel page (mirrors notes' standalone surfaces).
    return render(request, "tags/panel_page.html", ctx, status=422)


@login_required
@require_POST
def tag_remove(request, slug, node_pk):
    unit = get_node_or_404(node_pk, slug, require_unit=True)
    if not can_access_course(request.user, unit.course):
        raise PermissionDenied
    services.untag_unit(request.user, unit, request.POST.get("tag_pk"))
    if _wants_fragment(request):
        return _panel_response(request, unit)
    return redirect(_unit_url(unit) + "?panel=tags")
```

- [ ] **Step 6: Create `tags/rendering.py`** (needed by the views; templates land in Task 9)

```python
from tags import services


def unit_tags_context(user, unit, *, panel_open=False):
    """Context for the shared unit tag panel partial."""
    on_unit = services.tags_for_unit(user, unit)
    on_ids = {t.pk for t in on_unit}
    addable = [t for t in services.list_tags(user) if t.pk not in on_ids]
    return {
        "unit_tags": on_unit,
        "addable_tags": addable,
        "tags_panel_open": panel_open,
    }
```

- [ ] **Step 7: Create minimal templates so the views render**

`tags/templates/tags/_unit_tag_panel.html` (functional placeholder, fleshed out in Task 9):
```html
{% load i18n %}
<details class="unit-tags" {% if tags_panel_open %}open{% endif %}>
  <summary class="unit-tags__summary">🏷 {% blocktrans count n=unit_tags|length %}Tags ({{ n }}){% plural %}Tags ({{ n }}){% endblocktrans %}</summary>
  <div class="unit-tags__panel">
    {% if tag_error %}<p class="form-error" role="alert">{{ tag_error }}</p>{% endif %}
    <ul class="unit-tags__chips">
      {% for tag in unit_tags %}
        <li class="tag-chip tag-chip--{{ tag.color }}">{{ tag.name }}
          <form method="post" action="{% url 'tags:tag_remove' slug=course.slug node_pk=unit.pk %}">
            {% csrf_token %}<input type="hidden" name="tag_pk" value="{{ tag.pk }}">
            <button type="submit" aria-label="{% blocktrans %}Remove tag {{ tag }}{% endblocktrans %}">×</button>
          </form>
        </li>
      {% endfor %}
    </ul>
    <form method="post" action="{% url 'tags:tag_add' slug=course.slug node_pk=unit.pk %}" class="unit-tags__add">
      {% csrf_token %}
      <input type="text" name="name" value="{{ tag_draft }}" list="tags-datalist"
             placeholder="{% trans 'Add a tag…' %}" maxlength="50">
      {% if addable_tags %}
        <fieldset class="unit-tags__picker">
          {% for tag in addable_tags %}
            <label><input type="checkbox" name="tag_pk" value="{{ tag.pk }}"> {{ tag.name }}</label>
          {% endfor %}
        </fieldset>
      {% endif %}
      <button type="submit">{% trans "Add" %}</button>
    </form>
    <datalist id="tags-datalist">
      {% for tag in addable_tags %}<option value="{{ tag.name }}">{% endfor %}
    </datalist>
  </div>
</details>
```

`tags/templates/tags/panel_page.html` (standalone no-JS error surface):
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
  <main class="page-narrow">
    <h1>{{ unit.title }} — {% trans "Tags" %}</h1>
    {% include "tags/_unit_tag_panel.html" %}
    <p><a href="{% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">{% trans "Back to the unit" %}</a></p>
  </main>
{% endblock %}
```

- [ ] **Step 8: Run the view tests**

Run: `uv run pytest tests/test_tags_views.py -v`
Expected: all PASS.

- [ ] **Step 9: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/urls.py tags/views.py tags/rendering.py tags/templates/ config/urls.py tests/test_tags_views.py
git commit -m "feat(4b): unit tag add/remove views + URLs + panel partial"
```

---

### Task 8: Tag management views (rename / recolour / delete) + "My tags" page

**Files:**
- Modify: `tags/urls.py`, `tags/views.py`
- Create: `tags/templates/tags/my_tags.html`, `tags/templates/tags/rename_page.html`, `tags/templates/tags/delete_confirm.html`, `tags/templates/tags/_tag_section.html`
- Test: `tests/test_tags_manage.py`

**Interfaces:**
- Produces URL names `tags:tag_rename`, `tags:tag_recolor`, `tags:tag_delete`, `tags:my_tags`. Rename/delete serve GET (no-JS form/confirm) + POST; recolor POST. All author-scoped (foreign pk ⇒ 404), no course gate.

- [ ] **Step 1: Write the failing tests** `tests/test_tags_manage.py`

```python
import pytest
from django.urls import reverse

from tags import services
from tags.models import Tag
from tests.factories import (
    ContentNodeFactory,
    CourseFactory,
    TagFactory,
    UserFactory,
)
from courses.models import Enrollment

pytestmark = pytest.mark.django_db


def test_rename_post_updates(client):
    tag = TagFactory(name="exam")
    client.force_login(tag.author)
    resp = client.post(reverse("tags:tag_rename", args=[tag.pk]), {"name": "Exam"})
    assert resp.status_code == 302
    tag.refresh_from_db()
    assert tag.name == "Exam"


def test_rename_collision_is_422(client):
    user = UserFactory()
    TagFactory(author=user, name="hard")
    tag = TagFactory(author=user, name="exam")
    client.force_login(user)
    resp = client.post(reverse("tags:tag_rename", args=[tag.pk]), {"name": "hard"})
    assert resp.status_code == 422
    tag.refresh_from_db()
    assert tag.name == "exam"


def test_recolor_invalid_key_422(client):
    tag = TagFactory()
    client.force_login(tag.author)
    resp = client.post(reverse("tags:tag_recolor", args=[tag.pk]), {"color": "nope"})
    assert resp.status_code == 422


def test_delete_post_removes_tag(client):
    tag = TagFactory()
    client.force_login(tag.author)
    resp = client.post(reverse("tags:tag_delete", args=[tag.pk]))
    assert resp.status_code == 302
    assert not Tag.objects.filter(pk=tag.pk).exists()


def test_delete_confirm_get_shows_accessible_count(client):
    user = UserFactory()
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    tag = TagFactory(author=user, name="exam")
    services.tag_unit(user, ContentNodeFactory(course=course), "exam")
    client.force_login(user)
    resp = client.get(reverse("tags:tag_delete", args=[tag.pk]))
    assert resp.status_code == 200
    assert b"1" in resp.content


def test_foreign_tag_manage_404(client):
    tag = TagFactory()
    client.force_login(UserFactory())
    assert client.post(reverse("tags:tag_rename", args=[tag.pk]), {"name": "x"}).status_code == 404


def test_my_tags_lists_only_own(client):
    user = UserFactory()
    TagFactory(author=user, name="mine")
    TagFactory(author=UserFactory(), name="theirs")
    client.force_login(user)
    resp = client.get(reverse("tags:my_tags"))
    assert resp.status_code == 200
    assert b"mine" in resp.content
    assert b"theirs" not in resp.content
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_manage.py -v`
Expected: FAIL.

- [ ] **Step 3: Add URLs** (append to `tags/urls.py` `urlpatterns`)

```python
    path("tags/", views.my_tags, name="my_tags"),
    path("tags/<int:tag_pk>/rename/", views.tag_rename, name="tag_rename"),
    path("tags/<int:tag_pk>/recolor/", views.tag_recolor, name="tag_recolor"),
    path("tags/<int:tag_pk>/delete/", views.tag_delete, name="tag_delete"),
```

- [ ] **Step 4: Add views** (append to `tags/views.py`)

```python
from django.shortcuts import get_object_or_404

from tags.models import TAG_PALETTE, Tag


@login_required
def my_tags(request):
    return render(
        request,
        "tags/my_tags.html",
        {"tags_by_tag": services.units_by_tag(request.user), "palette": TAG_PALETTE},
    )


@login_required
def tag_rename(request, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=request.user)
    if request.method == "POST":
        try:
            services.rename_tag(request.user, tag.pk, request.POST.get("name", ""))
        except ValidationError as exc:
            return render(
                request,
                "tags/rename_page.html",
                {"tag": tag, "error": exc.messages[0], "draft": request.POST.get("name", "")},
                status=422,
            )
        return redirect("tags:my_tags")
    return render(request, "tags/rename_page.html", {"tag": tag, "draft": tag.name})


@login_required
@require_POST
def tag_recolor(request, tag_pk):
    try:
        services.recolor_tag(request.user, tag_pk, request.POST.get("color", ""))
    except ValidationError:
        return render(request, "tags/my_tags.html",
                      {"tags_by_tag": services.units_by_tag(request.user),
                       "palette": TAG_PALETTE}, status=422)
    return redirect("tags:my_tags")


@login_required
def tag_delete(request, tag_pk):
    tag = get_object_or_404(Tag, pk=tag_pk, author=request.user)
    if request.method == "POST":
        services.delete_tag(request.user, tag.pk)
        return redirect("tags:my_tags")
    count = services._accessible_unit_count(request.user, tag)
    return render(request, "tags/delete_confirm.html", {"tag": tag, "count": count})
```

- [ ] **Step 5: Add templates**

`tags/templates/tags/my_tags.html`:
```html
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "My tags" %} — libli{% endblock %}
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'tags/css/tags.css' %}">{% endblock %}
{% block content %}
<section class="my-tags">
  <h1>{% trans "My tags" %}</h1>
  {% if not tags_by_tag %}
    <p class="my-tags__empty">{% trans "You haven't created any tags yet. Open a lesson or quiz and add one." %}</p>
  {% endif %}
  <div class="my-tags__list">
    {% for tag, grouped in tags_by_tag %}
      {% include "tags/_tag_section.html" with tag=tag grouped=grouped palette=palette %}
    {% endfor %}
  </div>
</section>
{% include "tags/_tags_i18n.html" %}
{% endblock %}
```

(The `_tags_i18n.html` include — created in Task 9 — emits both the `#tags-i18n`
config element **and** the `tags.js` script, so the My-tags page's inline
delete-confirm has its translated labels available. Do **not** also add a bare
`<script src="…tags.js">` here, or it would double-load.)

`tags/templates/tags/_tag_section.html`:
```html
{% load i18n %}
<details class="tag-section" open>
  <summary class="tag-section__head">
    <span class="tag-swatch tag-swatch--{{ tag.color }}" aria-hidden="true"></span>
    <span class="tag-section__name">{{ tag.name }}</span>
    <span class="tag-section__count">{{ tag.unit_count }}</span>
    <span class="tag-section__manage">
      <a href="{% url 'tags:tag_rename' tag_pk=tag.pk %}" aria-label="{% blocktrans %}Rename {{ tag }}{% endblocktrans %}">✎</a>
      <a href="{% url 'tags:tag_delete' tag_pk=tag.pk %}" aria-label="{% blocktrans %}Delete {{ tag }}{% endblocktrans %}">🗑</a>
    </span>
  </summary>
  <form method="post" action="{% url 'tags:tag_recolor' tag_pk=tag.pk %}" class="tag-section__palette">
    {% csrf_token %}
    {% for key in palette %}
      <button type="submit" name="color" value="{{ key }}"
              class="tag-swatch tag-swatch--{{ key }}{% if key == tag.color %} is-current{% endif %}"
              aria-label="{{ key }}"></button>
    {% endfor %}
  </form>
  <div class="tag-section__units">
    {% for course, units in grouped.items %}
      <p class="tag-section__course">{{ course.title }}</p>
      <ul>
        {% for unit in units %}
          <li><a href="{% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">{{ unit.title }}</a></li>
        {% endfor %}
      </ul>
    {% endfor %}
  </div>
</details>
```

`tags/templates/tags/rename_page.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<main class="page-narrow">
  <h1>{% trans "Rename tag" %}</h1>
  {% if error %}<p class="form-error" role="alert">{{ error }}</p>{% endif %}
  <form method="post">
    {% csrf_token %}
    <input type="text" name="name" value="{{ draft }}" maxlength="50" autofocus>
    <button type="submit">{% trans "Save" %}</button>
    <a href="{% url 'tags:my_tags' %}">{% trans "Cancel" %}</a>
  </form>
</main>
{% endblock %}
```

`tags/templates/tags/delete_confirm.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<main class="page-narrow">
  <h1>{% blocktrans %}Delete “{{ tag }}”?{% endblocktrans %}</h1>
  {% if count %}
    <p>{% blocktrans count n=count %}This removes it from {{ n }} unit.{% plural %}This removes it from {{ n }} units.{% endblocktrans %}</p>
  {% endif %}
  <form method="post">
    {% csrf_token %}
    <button type="submit" class="btn btn--danger">{% trans "Delete" %}</button>
    <a href="{% url 'tags:my_tags' %}">{% trans "Cancel" %}</a>
  </form>
</main>
{% endblock %}
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_tags_manage.py -v`
Expected: all PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/urls.py tags/views.py tags/templates/ tests/test_tags_manage.py
git commit -m "feat(4b): tag management views + My tags page"
```

---

### Task 9: Unit-page panel integration (lesson + quiz) + `?panel=tags`

**Files:**
- Modify: `courses/views.py` (`full_lesson_render_context`, `quiz_unit`, `quiz_results`)
- Modify: `templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html`, `templates/courses/quiz_results.html`
- Test: `tests/test_tags_consumption.py`

**Interfaces:**
- Consumes: `tags.rendering.unit_tags_context(user, unit, *, panel_open)`.
- Produces: the lesson page, the active quiz page, **and the submitted-quiz `quiz_results` page** all render the tag panel; `?panel=tags` opens it. Context keys `unit_tags`, `addable_tags`, `tags_panel_open` present on all three. (A submitted quiz redirects `quiz_unit → quiz_results`, so the panel must live on `quiz_results` too, and the redirect must carry `?panel=tags` — otherwise a submitted quiz can never be tagged. Spec §2/§3 require tagging **any** unit, quizzes included.)

- [ ] **Step 1: Write the failing tests** `tests/test_tags_consumption.py`

```python
import pytest
from django.urls import reverse

from courses.models import Enrollment
from tags import services
from tests.factories import ContentNodeFactory, CourseFactory, UserFactory

pytestmark = pytest.mark.django_db


def _enrolled(user, **kw):
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    return ContentNodeFactory(course=course, **kw)


def test_lesson_page_shows_existing_tag(client):
    user = UserFactory()
    client.force_login(user)
    unit = _enrolled(user)
    services.tag_unit(user, unit, "exam")
    resp = client.get(reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk]))
    assert b"exam" in resp.content


def test_quiz_page_renders_tag_panel(client):
    user = UserFactory()
    client.force_login(user)
    quiz = _enrolled(user, unit_type="quiz")
    resp = client.get(reverse("courses:quiz_unit", args=[quiz.course.slug, quiz.pk]))
    assert resp.status_code == 200
    assert b"unit-tags" in resp.content


def test_panel_open_flag(client):
    user = UserFactory()
    client.force_login(user)
    unit = _enrolled(user)
    resp = client.get(
        reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk]) + "?panel=tags"
    )
    assert resp.context["tags_panel_open"] is True


def test_submitted_quiz_shows_panel_on_results(client):
    """A submitted quiz redirects to quiz_results; the panel must live there."""
    from courses.models import QuizSubmission

    user = UserFactory()
    client.force_login(user)
    quiz = _enrolled(user, unit_type="quiz")
    QuizSubmission.objects.create(
        student=user, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )
    # quiz_unit?panel=tags forwards to quiz_results?panel=tags
    resp = client.get(
        reverse("courses:quiz_unit", args=[quiz.course.slug, quiz.pk]) + "?panel=tags",
        follow=True,
    )
    assert resp.status_code == 200
    assert b"unit-tags" in resp.content
    assert resp.context["tags_panel_open"] is True
```
(Adjust the `QuizSubmission.objects.create(...)` kwargs to the model's real fields —
inspect `courses/models.py` `QuizSubmission`; the point is a `SUBMITTED` submission for
this unit+user. If a factory exists, prefer it.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_consumption.py -v`
Expected: FAIL.

- [ ] **Step 3: Inject tag context in `courses/views.py`**

In `full_lesson_render_context`, change the signature to accept `tags_panel=False` and update the context:
```python
def full_lesson_render_context(node, user, *, notes_show=False, tags_panel=False):
    from notes.rendering import lesson_notes_context
    from tags.rendering import unit_tags_context

    ctx = build_lesson_context(node, user)
    ctx["unit_nav"] = build_unit_nav(node.course, user, node)
    ctx.update(
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    )
    ctx.update(lesson_notes_context(user, node, show=notes_show))
    ctx.update(unit_tags_context(user, node, panel_open=tags_panel))
    return ctx
```

In `lesson_unit`, pass the flag:
```python
    ctx = full_lesson_render_context(
        node,
        request.user,
        notes_show=bool(request.GET.get("notes")),
        tags_panel=request.GET.get("panel") == "tags",
    )
```

In `quiz_unit`, the `SUBMITTED` branch redirects to `quiz_results` **before** building
the page — so (a) make that redirect **carry `?panel=tags`** when present, and (b) inject
the panel context on the active-quiz path. Replace the submitted-redirect line and add the
context after `ctx["unit_nav"] = build_unit_nav(...)`:
```python
    sub = ctx["submission"]
    if sub is not None and sub.status == QuizSubmission.Status.SUBMITTED:
        target = reverse("courses:quiz_results", kwargs={"slug": slug, "node_pk": node_pk})
        if request.GET.get("panel") == "tags":
            target += "?panel=tags"
        return redirect(target)
    ctx["unit_nav"] = build_unit_nav(course, request.user, node)
    from tags.rendering import unit_tags_context

    ctx.update(
        unit_tags_context(
            request.user, node, panel_open=request.GET.get("panel") == "tags"
        )
    )
```
(`reverse` is already imported in `courses/views.py`; if not, add `from django.urls import reverse`.)

In `quiz_results(request, slug, node_pk)`, after its context is built (before the
`render(...)`), inject the same panel context so a submitted quiz can be tagged here:
```python
    from tags.rendering import unit_tags_context

    ctx.update(
        unit_tags_context(
            request.user, node, panel_open=request.GET.get("panel") == "tags"
        )
    )
```
(Use whatever the function names its resolved node/unit + context dict — mirror the
variable names already in `quiz_results`.)

- [ ] **Step 4: Include the panel + assets in both templates**

In `templates/courses/lesson_unit.html`: add the tags CSS link in `extra_css` (`<link rel="stylesheet" href="{% static 'tags/css/tags.css' %}">`), and inside the content block, render the panel near the top (before the `_unit_shell` include):
```html
{% block content %}
  {% include "tags/_unit_tag_panel.html" %}
  {% include "courses/_unit_shell.html" with content_partial="courses/_lesson_article.html" %}
  {% include "tags/_tags_i18n.html" %}
{% endblock %}
```
Apply the same `{% include "tags/_unit_tag_panel.html" %}` (top of content) + the CSS link + `{% include "tags/_tags_i18n.html" %}` to **both** `templates/courses/quiz_unit.html` **and** `templates/courses/quiz_results.html` (so a submitted quiz shows the panel). The shared `_unit_tag_panel.html` reads `course` + `unit`; confirm `quiz_results.html`'s context exposes those under the same names (the quiz context builders expose `course` and `unit`) — if `quiz_results` names the unit differently, pass it explicitly via `{% include "tags/_unit_tag_panel.html" with unit=<its-name> course=course %}`.

- [ ] **Step 5: Create `tags/templates/tags/_tags_i18n.html`** (config element + script)

```html
{% load i18n static %}
<div id="tags-i18n" hidden
     data-msg-add="{% trans 'Add' %}"
     data-msg-remove="{% trans 'Remove' %}"
     data-msg-cancel="{% trans 'Cancel' %}"
     data-msg-delete-q="{% trans 'Delete?' %}"
     data-msg-yes="{% trans 'Yes' %}"
     data-msg-no="{% trans 'No' %}"></div>
<script src="{% static 'tags/js/tags.js' %}" defer></script>
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_tags_consumption.py -v`
Expected: all PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views.py templates/courses/lesson_unit.html templates/courses/quiz_unit.html templates/courses/quiz_results.html tags/templates/tags/_tags_i18n.html tests/test_tags_consumption.py
git commit -m "feat(4b): tag panel on lesson + quiz + quiz-results pages with ?panel=tags"
```

---

### Task 10: Outline filter integration (server-side)

**Files:**
- Modify: `courses/views.py` (`course_outline`)
- Modify: `templates/courses/outline.html`, `templates/courses/_outline_node.html`
- Create: `templates/courses/_tags_filter_bar.html`
- Test: `tests/test_tags_outline.py`

**Interfaces:**
- Consumes: `tags.services.tags_for_outline`, `outline_with_tags`, `filter_chip_hrefs`.
- Produces: outline renders tag chips per unit; `?tags=<id>` hides non-matching units/containers via the `hidden` attribute; the filter bar renders toggle links; unknown/foreign ids dropped.

- [ ] **Step 1: Write the failing tests** `tests/test_tags_outline.py`

```python
import pytest
from django.urls import reverse

from courses.models import Enrollment
from tags import services
from tests.factories import ContentNodeFactory, CourseFactory, UserFactory

pytestmark = pytest.mark.django_db


def _course_with_units(user):
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    u1 = ContentNodeFactory(course=course, parent=part, unit_type="lesson", title="Photosynthesis")
    u2 = ContentNodeFactory(course=course, parent=part, unit_type="lesson", title="Membranes")
    return course, u1, u2


def test_outline_renders_chip_for_tagged_unit(client):
    user = UserFactory()
    client.force_login(user)
    course, u1, _ = _course_with_units(user)
    services.tag_unit(user, u1, "exam")
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert b"exam" in resp.content


def test_filter_hides_non_matching_unit(client):
    user = UserFactory()
    client.force_login(user)
    course, u1, u2 = _course_with_units(user)
    exam = services.tag_unit(user, u1, "exam").tag
    resp = client.get(
        reverse("courses:course_outline", args=[course.slug]) + f"?tags={exam.pk}"
    )
    html = resp.content.decode()
    # the matching unit's row is visible; the non-matching one carries hidden
    assert "Photosynthesis" in html
    # crude check: the membranes row's <li> has the hidden attribute
    assert "Membranes" in html  # still in DOM (hidden, not omitted)


def test_unknown_tag_id_is_dropped_not_404(client):
    user = UserFactory()
    client.force_login(user)
    course, _, _ = _course_with_units(user)
    resp = client.get(
        reverse("courses:course_outline", args=[course.slug]) + "?tags=999999"
    )
    assert resp.status_code == 200
    assert resp.context["active_tag_ids"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_outline.py -v`
Expected: FAIL (`active_tag_ids` missing / chips absent).

- [ ] **Step 3: Update `course_outline` in `courses/views.py`**

```python
@login_required
def course_outline(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    from notes.services import note_counts_for_outline
    from tags import services as tag_services
    from django.urls import reverse

    outline = build_outline(course, request.user)
    tags_by_unit, course_tags = tag_services.tags_for_outline(request.user, course)
    course_tag_ids = {t.pk for t in course_tags}
    active_tag_ids = [
        int(x)
        for x in request.GET.getlist("tags")
        if x.isdigit() and int(x) in course_tag_ids
    ]
    tag_services.outline_with_tags(outline, tags_by_unit, active_tag_ids)
    base = reverse("courses:course_outline", kwargs={"slug": course.slug})
    return render(
        request,
        "courses/outline.html",
        {
            "course": course,
            "outline": outline,
            "note_counts": note_counts_for_outline(request.user, course),
            "active_tag_ids": active_tag_ids,
            "filter_chips": tag_services.filter_chip_hrefs(base, course_tags, active_tag_ids),
        },
    )
```

- [ ] **Step 4: Add the filter bar** `templates/courses/_tags_filter_bar.html`

```html
{% load i18n %}
{% if filter_chips %}
<div class="tags-filter" role="group" aria-label="{% trans 'Filter by tag' %}" data-tags-filter>
  <span class="tags-filter__label">{% trans "Filter:" %}</span>
  {% for chip in filter_chips %}
    <a class="tag-chip tag-chip--{{ chip.tag.color }}{% if chip.active %} is-active{% endif %}"
       href="{{ chip.href }}" data-tag-id="{{ chip.tag.pk }}"
       {% if chip.active %}aria-current="true"{% endif %}>
      {{ chip.tag.name }}{% if chip.active %} <span class="visually-hidden">{% trans "(active)" %}</span>{% endif %}
    </a>
  {% endfor %}
</div>
{% endif %}
```

In `templates/courses/outline.html`: add the tags CSS link in `extra_css`, render the filter bar just before `<nav class="outline-tree" …>`, and append a `tags.js` script at the end of the content block:
```html
{% include "courses/_tags_filter_bar.html" %}
```
plus `<script src="{% static 'tags/js/tags.js' %}" defer></script>` and `{% load static %}` if not loaded.

- [ ] **Step 5: Update `_outline_node.html`** to render chips + the `hidden` attribute + the ✎ edit

Change the unit branch to carry `hidden` and `data-tags`, render chips and an edit link:
```html
{% load i18n notes_extras %}
<li class="outline-node outline-node--{{ item.node.kind }}"{% if item.tag_hidden %} hidden{% endif %}
    {% if item.is_unit %}data-unit="{{ item.node.pk }}" data-tags="{% for t in item.tags %}{{ t.pk }} {% endfor %}"{% endif %}>
  {% if item.is_unit %}
    <a class="outline-unit{% if item.completed %} outline-unit--done{% endif %}" lang="{{ course.language }}"
       href="{% url 'courses:lesson_unit' slug=course.slug node_pk=item.node.pk %}">
      <span class="outline-unit__title">{{ item.node.title }}</span>
      {% if item.completed %}<span class="badge badge--done" aria-label="{% trans 'Completed' %}">✓</span>{% endif %}
    </a>
    {% for t in item.tags %}<span class="tag-chip tag-chip--{{ t.color }}">{{ t.name }}</span>{% endfor %}
    {% if item.node.unit_type == "quiz" %}
      <a class="outline-unit__edit-tags" aria-label="{% trans 'Edit tags' %}"
         href="{% url 'courses:quiz_unit' slug=course.slug node_pk=item.node.pk %}?panel=tags">✎</a>
    {% else %}
      <a class="outline-unit__edit-tags" aria-label="{% trans 'Edit tags' %}"
         href="{% url 'courses:lesson_unit' slug=course.slug node_pk=item.node.pk %}?panel=tags">✎</a>
    {% endif %}
    {% include "notes/_outline_badge.html" with count=note_counts|get_item:item.node.pk course=course node_pk=item.node.pk %}
  {% else %}
    <div class="outline-node__head">
      <span class="outline-node__title" lang="{{ course.language }}">{{ item.node.title }}</span>
      {% if item.required_total %}<span class="rollup">{{ item.required_done }}/{{ item.required_total }} {% trans "required" %}</span>{% endif %}
      {% if item.additional_done %}<span class="rollup rollup--additional">+{{ item.additional_done }} {% trans "additional" %}</span>{% endif %}
    </div>
    {% if item.children %}
      <ul>{% for child in item.children %}{% include "courses/_outline_node.html" with item=child course=course note_counts=note_counts %}{% endfor %}</ul>
    {% endif %}
  {% endif %}
</li>
```
(The ✎ href branches on `item.node.unit_type` **unconditionally** — for a quiz it targets `courses:quiz_unit?panel=tags` directly, because `lesson_unit`'s `redirect("courses:quiz_unit", …)` builds the URL with **no** query string and would always drop `?panel=tags`. The quiz panel surface is handled by Task 9, including the submitted-quiz → `quiz_results` forwarding.)

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_tags_outline.py -v`
Expected: all PASS. The quiz ✎ links straight to `quiz_unit?panel=tags` (Step 5 branch) — no lesson→quiz redirect is involved, so the query survives.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views.py templates/courses/outline.html templates/courses/_outline_node.html templates/courses/_tags_filter_bar.html tests/test_tags_outline.py
git commit -m "feat(4b): outline tag chips + server-side ?tags filter (hidden attr)"
```

---

### Task 11: `tags.css` + `tags.js` (progressive enhancement)

**Files:**
- Create: `tags/static/tags/css/tags.css`, `tags/static/tags/js/tags.js`
- Test: `tests/test_tags_static.py` (smoke: files exist + key selectors/strings present)

**Interfaces:**
- Consumes: DOM produced by Tasks 9–10 (`[data-tags-filter]`, `.tag-chip[data-tag-id]`, `li[data-unit][data-tags]`, `#tags-i18n`).
- Produces: token-driven palette styling (light/dark), responsive My-tags two-pane, JS filter interception (toggle `hidden`, prune ancestors, recompute hrefs, `pushState`), **unit-panel fragment add/remove** (intercept the panel forms, POST with `X-Requested-With: fetch`, swap the returned panel HTML — exercising the `_panel_response`/422 server paths from Task 7), and inline delete-confirm.

- [ ] **Step 1: Write the smoke test** `tests/test_tags_static.py`

```python
from pathlib import Path


def test_tags_css_has_palette_tokens():
    css = Path("tags/static/tags/css/tags.css").read_text(encoding="utf-8")
    for key in ("teal", "amber", "indigo", "rose", "green", "violet", "slate", "cyan"):
        assert f"tag-chip--{key}" in css


def test_tags_js_filters_and_recomputes():
    js = Path("tags/static/tags/js/tags.js").read_text(encoding="utf-8")
    assert "data-tags-filter" in js
    assert "pushState" in js
    assert "hidden" in js


def test_tags_js_wires_panel_fragments():
    js = Path("tags/static/tags/js/tags.js").read_text(encoding="utf-8")
    assert "X-Requested-With" in js  # panel add/remove fragment submission
    assert "unit-tags" in js
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_tags_static.py -v`
Expected: FAIL (files missing).

- [ ] **Step 3: Write `tags/static/tags/css/tags.css`**

Define palette swatch/chip colours from existing design tokens (foreground/background pairs that read in light and dark), chip layout, the unit panel, the responsive My-tags two-pane (accordion base; `@media (min-width: 60rem)` → rail + content), and a `.visually-hidden` utility. Example skeleton (fill all 8 palette keys):
```css
.tag-chip { display:inline-flex; align-items:center; gap:.3rem; border-radius:999px;
  padding:.1rem .55rem; font-size:.8rem; font-weight:600; color:#fff; }
.tag-chip--teal   { background: var(--tag-teal,   #1f6f5c); }
.tag-chip--amber  { background: var(--tag-amber,  #b4541a); }
.tag-chip--indigo { background: var(--tag-indigo, #3a5bb8); }
.tag-chip--rose   { background: var(--tag-rose,   #a8324f); }
.tag-chip--green  { background: var(--tag-green,  #2f7d32); }
.tag-chip--violet { background: var(--tag-violet, #6b3fa0); }
.tag-chip--slate  { background: var(--tag-slate,  #4a5568); }
.tag-chip--cyan   { background: var(--tag-cyan,   #1f7a8c); }
.tag-chip.is-active { outline: 2px solid currentColor; }
.tag-swatch { width:.85rem; height:.85rem; border-radius:50%; display:inline-block; }
.tag-swatch--teal { background: var(--tag-teal, #1f6f5c); } /* …repeat 8… */
.visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden;
  clip:rect(0 0 0 0); white-space:nowrap; }
/* My tags: accordion base; two-pane ≥60rem */
@media (min-width: 60rem) {
  .my-tags__list { display:grid; grid-template-columns: 16rem 1fr; gap:1rem; }
}
```
(Match `courses.css`/`notes.css` token conventions; verify in dark mode in Task 13.)

- [ ] **Step 4: Write `tags/static/tags/js/tags.js`**

Implement (vanilla, defer): read `#tags-i18n`; outline filter — intercept `[data-tags-filter] a.tag-chip` clicks, maintain the active id set, apply `applyFilter()` (set `hidden` on each `li[data-unit]` whose `data-tags` lacks an active id; then bubble: a container `li` is hidden iff it has no visible descendant unit; empty set ⇒ clear all `hidden`), `history.pushState` the new `?tags=`, and **recompute every chip's `href`** + `aria-current` from the new set; **unit-panel fragment submission** — intercept the `.unit-tags__add` and per-chip `×` remove forms, POST them with `X-Requested-With: fetch` + the form's CSRF token, and replace the `.unit-tags` panel with the returned HTML fragment (which carries the refreshed chips + count, and a `422` body on validation error); inline delete-confirm — intercept the My-tags `🗑` link, swap in a Yes/No confirm before POSTing. Example core:
```javascript
(function () {
  "use strict";
  var bar = document.querySelector("[data-tags-filter]");
  if (bar) setupFilter(bar);
  wirePanels();

  function setupFilter(bar) {
    var chips = Array.prototype.slice.call(bar.querySelectorAll("a.tag-chip"));
    var active = new Set(
      chips.filter(function (c) { return c.classList.contains("is-active"); })
           .map(function (c) { return c.dataset.tagId; })
    );
    chips.forEach(function (chip) {
      chip.addEventListener("click", function (e) {
        e.preventDefault();
        var id = chip.dataset.tagId;
        if (active.has(id)) active.delete(id); else active.add(id);
        applyFilter(active);
        syncChips(chips, active);
        var ids = Array.from(active);
        var qs = ids.map(function (i) { return "tags=" + i; }).join("&");
        history.pushState(null, "", qs ? "?" + qs : location.pathname);
      });
    });
    applyFilter(active);
  }

  function applyFilter(active) {
    var units = document.querySelectorAll("li[data-unit]");
    units.forEach(function (li) {
      var tags = (li.dataset.tags || "").trim().split(/\s+/).filter(Boolean);
      var match = active.size === 0 || tags.some(function (t) { return active.has(t); });
      li.hidden = !match;
    });
    // bubble: container visible iff it has a visible descendant unit
    var containers = Array.prototype.slice.call(
      document.querySelectorAll("li.outline-node")
    ).reverse();
    containers.forEach(function (li) {
      if (li.hasAttribute("data-unit")) return;
      if (active.size === 0) { li.hidden = false; return; }
      li.hidden = !li.querySelector("li[data-unit]:not([hidden])");
    });
  }

  function syncChips(chips, active) {
    var ids = Array.from(active);
    chips.forEach(function (chip) {
      var id = chip.dataset.tagId;
      var on = active.has(id);
      chip.classList.toggle("is-active", on);
      if (on) chip.setAttribute("aria-current", "true");
      else chip.removeAttribute("aria-current");
      var rest = on ? ids.filter(function (i) { return i !== id; }) : ids.concat(id);
      var qs = rest.map(function (i) { return "tags=" + i; }).join("&");
      chip.setAttribute("href", qs ? "?" + qs : location.pathname);
    });
  }

  // Unit-panel fragment add/remove: intercept the panel forms, POST with the
  // fetch header, swap the returned .unit-tags panel HTML in place.
  function wirePanels() {
    document.addEventListener("submit", function (e) {
      var form = e.target;
      var panel = form.closest(".unit-tags");
      if (!panel) return;  // not a tag-panel form
      if (!form.matches(".unit-tags__add, .unit-tags__chips form")) return;
      e.preventDefault();
      var data = new FormData(form);
      fetch(form.action, {
        method: "POST",
        body: data,
        headers: { "X-Requested-With": "fetch" },
      })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          var tmp = document.createElement("div");
          tmp.innerHTML = html;
          var fresh = tmp.querySelector(".unit-tags");
          if (fresh) panel.replaceWith(fresh);  // wirePanels uses delegation, so the
                                                 // replacement's forms stay wired
        });
    });
  }
})();
```
(The submit handler is **delegated** on `document`, so swapping the panel HTML keeps
new forms working without re-binding. The server returns the rendered
`tags/_unit_tag_panel.html` fragment — wrap its root element in `class="unit-tags"` so the
swap target matches; the panel's `<details>` already carries that class in Task 7.)

- [ ] **Step 5: Run the smoke test**

Run: `uv run pytest tests/test_tags_static.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add tags/static/ tests/test_tags_static.py
git commit -m "feat(4b): tags.css + tags.js (filter interception, palette, responsive)"
```

---

### Task 12: Navigation entry point for "My tags"

**Files:**
- Modify: the main nav template (find it: `grep -rl "courses:course" templates/ | head` or inspect `templates/base.html` / the nav partial used app-wide)
- Test: `tests/test_tags_nav.py`

**Interfaces:**
- Produces: an authenticated-only nav link to `tags:my_tags`.

- [ ] **Step 1: Locate the nav** — inspect `templates/base.html` and any `_nav`/header partial it includes; identify where authenticated links (e.g. the existing user menu) live.

- [ ] **Step 2: Write the failing test** `tests/test_tags_nav.py`

```python
import pytest
from django.urls import reverse
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_nav_has_my_tags_link_when_authenticated(client):
    client.force_login(UserFactory())
    resp = client.get(reverse("home"))
    assert reverse("tags:my_tags").encode() in resp.content


def test_nav_no_my_tags_link_when_anonymous(client):
    resp = client.get(reverse("home"))
    assert reverse("tags:my_tags").encode() not in resp.content
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_tags_nav.py -v`
Expected: FAIL.

- [ ] **Step 4: Add the link** inside the authenticated branch of the nav (mirror the existing authenticated links):
```html
{% if user.is_authenticated %}
  <a href="{% url 'tags:my_tags' %}">{% trans "My tags" %}</a>
{% endif %}
```
(Place it alongside the existing user-menu items; match their markup/classes.)

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_tags_nav.py -v`
Expected: PASS. If `home` isn't a no-arg URL in this project, use a known authenticated GET (e.g. the landing/home view confirmed in `config/urls.py`).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add templates/ tests/test_tags_nav.py
git commit -m "feat(4b): My tags nav entry point (authenticated only)"
```

---

### Task 13: i18n — EN/PL catalogs + visual verification (light/dark)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_tags_i18n.py`

**Interfaces:**
- Produces: every new msgid translated to PL; catalog has 0 fuzzy / 0 obsolete.

- [ ] **Step 1: Extract messages**

```bash
uv run python manage.py makemessages -l pl -l en
```

- [ ] **Step 2: Translate** every new tags msgid in `locale/pl/LC_MESSAGES/django.po`. Provide PL strings (e.g. "My tags"→"Moje tagi", "Add"→"Dodaj", "Filter:"→"Filtruj:", "Rename tag"→"Zmień nazwę tagu", "Delete"→"Usuń", "Tags ({{ n }})"→"Tagi ({{ n }})", "Edit tags"→"Edytuj tagi", "Add a tag…"→"Dodaj tag…", the delete-confirm plural). **Clear any `#, fuzzy` flags** makemessages added and verify it didn't mis-guess (grep each new msgid and read its msgstr — this codebase has hit the fuzzy mis-guess gotcha repeatedly).

- [ ] **Step 3: Write the catalog test** `tests/test_tags_i18n.py`

```python
import re
from pathlib import Path


def test_pl_catalog_clean_for_tags_strings():
    po = Path("locale/pl/LC_MESSAGES/django.po").read_text(encoding="utf-8")
    assert "#, fuzzy" not in po
    assert "#~ msgid" not in po  # no obsolete entries
    # spot-check a few new msgids are translated (non-empty msgstr)
    for msgid in ['"My tags"', '"Add a tag…"', '"Filter:"']:
        idx = po.find("msgid " + msgid)
        assert idx != -1, msgid
        tail = po[idx: idx + 200]
        assert re.search(r'msgstr "(?!")\S', tail), msgid
```

- [ ] **Step 4: Compile + run**

```bash
uv run python manage.py compilemessages
uv run pytest tests/test_tags_i18n.py -v
```
Expected: PASS.

- [ ] **Step 5: Visual verification (light + dark)** — throwaway Playwright screenshot harness

Write a temporary script that logs in, screenshots: the lesson page with the tag panel open, the outline with a filter active, and the My-tags page — in **both** light and dark — at 1280px and 390px widths. Review the images, self-critique (contrast, dark-mode token correctness, responsive two-pane↔accordion, chip legibility), fix any CSS, then **delete the harness** (the established delete-after-review pattern). Verify the My-tags two-pane appears ≥60rem and collapses to the accordion on mobile.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run ruff format .
git add locale/ tests/test_tags_i18n.py tags/static/tags/css/tags.css
git commit -m "feat(4b): EN/PL i18n for tags + light/dark visual polish"
```

---

### Task 14: End-to-end test (real gestures)

**Files:**
- Create: `tests/test_e2e_tags.py`

**Interfaces:**
- Consumes: the full running app. Drives tag → filter → untag → delete with real Playwright gestures (no `page.evaluate`).

- [ ] **Step 1: Write the e2e** `tests/test_e2e_tags.py` (mirror `tests/test_e2e_notes.py` setup: `pytestmark = pytest.mark.e2e`, the `_allow_sync_orm_under_playwright` fixture, `_login` helper, `@pytest.mark.django_db(transaction=True)`)

```python
import os
import pytest
from playwright.sync_api import expect
from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_tag_filter_untag_delete_via_ui(page, live_server):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory, CourseFactory, UserFactory

    user = UserFactory(username="tagger")
    course = CourseFactory(title="Bio")
    Enrollment.objects.create(student=user, course=course)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    unit = ContentNodeFactory(course=course, parent=part, unit_type="lesson", title="Photosynthesis")

    _login(page, live_server, "tagger")

    # Add a tag on the unit page
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/?panel=tags")
    page.locator(".unit-tags__add input[name='name']").fill("exam")
    page.get_by_role("button", name="Add").click()
    expect(page.locator(".tag-chip", has_text="exam")).to_be_visible()

    # Filter the outline by it
    page.goto(f"{live_server.url}/courses/{course.slug}/")
    page.locator("[data-tags-filter] a.tag-chip", has_text="exam").click()
    expect(page.locator("li[data-unit]", has_text="Photosynthesis")).to_be_visible()

    # Untag from the unit page
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/?panel=tags")
    page.locator(".unit-tags__chips button", has_text="×").first.click()

    # Delete the tag entirely from My tags
    page.goto(f"{live_server.url}/tags/")
    page.get_by_role("link", name="Delete exam").click()
    page.get_by_role("button", name="Delete").click()
    expect(page.locator(".tag-section", has_text="exam")).to_have_count(0)
```

- [ ] **Step 2: Run the e2e**

```bash
uv run pytest tests/test_e2e_tags.py -m e2e -v
```
Expected: PASS (driving real clicks/fills, no `page.evaluate`). Adjust selectors to the exact markup if needed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_tags.py
git commit -m "test(4b): e2e tag → filter → untag → delete (real gestures)"
```

---

### Task 15: Full-suite green + final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite + lint**

```bash
uv run pytest -q
uv run pytest tests/test_e2e_tags.py tests/test_e2e_notes.py -m e2e -q
uv run ruff check . && uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
```
Expected: all green; no uncommitted migrations; `ruff format --check` clean.

- [ ] **Step 2: Spec cross-check** — re-read the spec §§4–9 and confirm each requirement maps to a shipped task (data model, services, gating, three surfaces, no-JS parity, i18n, a11y, security, tests). Note any gap and add a follow-up task.

- [ ] **Step 3: Commit any final fixes**

```bash
uv run ruff format .
git add -A
git commit -m "chore(4b): final verification fixes"
```

---

## Self-Review

**Spec coverage:**
- Data model (Tag/UnitTag/palette/constraints) → Task 1. `accessible_courses` parity → Task 2. Name validation/colour → Task 3. Tag lifecycle (reuse/rename/recolour/delete/list, IntegrityError, self-exclude, snapshot count) → Tasks 3–4. Unit tagging + tags_for_unit → Task 5. Outline/my-tags queries + recursive visibility + chip hrefs → Task 6. Unit add/remove views (gate order, dispatch precedence, 404/403, fragment/PRG/422, login) → Task 7. Management + My-tags views → Task 8. Unit-page panel on lesson **and** quiz + `?panel=tags` → Task 9. Outline filter (hidden-attr, drop ids, chips, ✎) → Task 10. CSS/JS enhancement (filter interception, href recompute, responsive) → Task 11. Nav → Task 12. i18n + light/dark → Task 13. e2e → Task 14. Full green → Task 15.
- **Possible gap:** the no-JS delete-confirm "≥1 unit ⇒ confirm; unused ⇒ may skip" — Task 8 always shows a confirm page on GET (safe superset; the spec permits skipping but doesn't require it). Acceptable.
- **Possible gap:** the spec's "JS inline outline ✎ re-runs the visibility rule immediately" — Task 11's filter handles chip toggles; inline outline editing under JS is an enhancement the e2e doesn't force. The no-JS path (link to unit page) is fully covered; flag JS inline-edit re-eval as a polish item if manual testing wants it.

**Placeholder scan:** No "TBD"/"handle edge cases" — every code step has concrete code. The CSS task lists all 8 palette keys; fill the remaining `tag-swatch--*` rules by repeating the pattern shown.

**Type consistency:** `tag_unit`/`tag_unit_by_id`/`untag_unit` signatures match across services (Task 5), views (Task 7), and tests. `outline_with_tags`/`tags_for_outline`/`filter_chip_hrefs` signatures match between Task 6 and Task 10. `unit_tags_context` keys (`unit_tags`, `addable_tags`, `tags_panel_open`) are consistent across Tasks 7/9 and the panel template.
