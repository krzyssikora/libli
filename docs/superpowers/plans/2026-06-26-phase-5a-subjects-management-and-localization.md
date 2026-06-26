# Phase 5a — Subjects: management UI + localization + multi-subject courses — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Platform Admin a bespoke `/manage/subjects/` UI to curate a bilingual (EN/PL) subject taxonomy, and let a course belong to multiple subjects.

**Architecture:** Localize `Subject` with per-language `title_en`/`title_pl` fields plus a `title` property (single read path); convert `Course.subject` (FK) to `Course.subjects` (M2M, flat set) via a careful 4-step migration that dodges a reverse-accessor clash; add PA-gated CRUD views mirroring the existing `grouping` cohort management pattern. All consumption surfaces (catalog, manage list) render subjects as chips.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django + factory_boy, pytest-playwright (e2e), `uv` for all tooling, Django i18n (gettext/ngettext, EN/PL).

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff`, `uv run pytest`, `uv run python manage.py`. CI checks `uv run ruff format --check` — run `uv run ruff format` (not just `ruff check`) every task.
- **Single read path for subject titles:** every consumer uses `subject.title` (the property). Never read `title_en`/`title_pl` directly in templates or views.
- **Subject sort key is `title_en`** (a real column). Never `order_by("title")` — `title` is a Python property and cannot be a DB sort key. Accepted limitation: PL UI shows subjects in English-alphabetical order (5b follow-up, not a bug).
- **Subjects are PA-only.** Management views gate on `courses.add_subject` / `courses.change_subject` / `courses.delete_subject`. The list gates on `change_subject`. `view_subject` is intentionally unused.
- **Permissions are seeded via `setup_roles`** (`institution/roles.py` → `seed_roles()`), never via a migration `RunPython` (Permission rows may not exist mid-migration).
- **i18n:** all new UI strings get PL translations; `.po` updated and `.mo` compiled. Count-bearing strings ("used by N courses") MUST use `{% blocktrans count %}` / `ngettext` (Polish has 3 plural forms). Watch the `makemessages` fuzzy-flag gotcha (clear stale `#, fuzzy`; verify new msgids).
- **i18n imports:** in models/forms use `from django.utils.translation import gettext_lazy as _` (module-level translatable strings must be lazy); in views the file already uses `gettext as _`.
- **Latest courses migration is `0023_course_structure_flags`.** Task 1 produces `0024`, Task 2 produces `0025` (adjust the numbers if makemigrations assigns differently, and update the migration-test references accordingly).

---

## File map

**Modify:**
- `courses/models.py` — `Subject` fields/property/Meta/docstring; `Course.subject` → `Course.subjects`.
- `courses/forms.py` — new `SubjectForm` + `unique_subject_slug`; `CourseForm` Meta `subject` → `subjects`.
- `courses/views_manage.py` — new `subject_list`/`subject_create`/`subject_edit`/`subject_delete`; fix `course_create` `save_m2m`; `course_list` `select_related` → `prefetch_related`.
- `courses/views.py` — catalog subject query order + filter + prefetch.
- `courses/urls.py` — 4 `manage/subjects/...` routes.
- `courses/admin.py` — `SubjectAdmin` (title_en), `CourseAdmin` (subjects).
- `courses/management/commands/seed_demo_course.py` — `title_en`, `subjects.add`.
- `institution/roles.py` — add subject perms to PLATFORM_ADMIN.
- `templates/base.html` — "Subjects" nav link.
- `templates/courses/catalog.html`, `templates/courses/_catalog_detail.html`, `templates/courses/manage/course_list.html` — subject chip rows.
- `tests/factories.py` — `SubjectFactory.title` → `title_en`; `CourseFactory` `subjects` post-generation.
- `tests/test_catalog_views.py`, `tests/test_e2e_catalog.py`, `tests/test_course_structure.py` — subject call-site sweep.

**Create:**
- `courses/migrations/0024_subject_localize_title.py`, `courses/migrations/0025_course_subjects_m2m.py`.
- `templates/courses/manage/subject_list.html`, `subject_form.html`, `subject_confirm_delete.html`.
- `tests/test_subject_model.py`, `tests/test_subject_migrations.py`, `tests/test_subject_admin_views.py`, `tests/test_e2e_subjects.py`.

---

## Task 1: Localize `Subject` (title_en / title_pl / property / ordering)

Keeps `Course.subject` FK intact. Only touches `Subject.title` consumers.

**Files:**
- Modify: `courses/models.py:27-45` (Subject), imports
- Create: `courses/migrations/0024_subject_localize_title.py`
- Modify: `courses/admin.py:16-20` (SubjectAdmin)
- Modify: `courses/management/commands/seed_demo_course.py:25-26`
- Modify: `tests/factories.py:58-63` (SubjectFactory)
- Modify: `tests/test_catalog_views.py:35`, `tests/test_e2e_catalog.py:32` (`SubjectFactory(title=…)` → `title_en=…`)
- Modify: `courses/views.py:702-706` (catalog subject `order_by`)
- Create: `tests/test_subject_model.py`, `tests/test_subject_migrations.py`

**Interfaces:**
- Produces: `Subject.title_en` (CharField, required), `Subject.title_pl` (CharField, blank), `Subject.title` (read-only property → active-language title with EN fallback), `Subject.Meta.ordering = ["title_en"]`. `SubjectFactory(title_en=…)`.

- [ ] **Step 1: Write the failing model test**

Create `tests/test_subject_model.py`:

```python
import pytest
from django.utils import translation

from courses.models import Subject

pytestmark = pytest.mark.django_db


def test_title_returns_en_under_en_locale():
    s = Subject.objects.create(title_en="Mathematics", title_pl="Matematyka", slug="m")
    with translation.override("en"):
        assert s.title == "Mathematics"


def test_title_returns_pl_under_pl_locale():
    s = Subject.objects.create(title_en="Mathematics", title_pl="Matematyka", slug="m")
    with translation.override("pl"):
        assert s.title == "Matematyka"


def test_title_falls_back_to_en_when_pl_blank():
    s = Subject.objects.create(title_en="Mathematics", title_pl="", slug="m")
    with translation.override("pl"):
        assert s.title == "Mathematics"


def test_str_uses_title_property():
    s = Subject.objects.create(title_en="Science", slug="sci")
    assert str(s) == "Science"


def test_default_ordering_is_title_en():
    Subject.objects.create(title_en="Zoology", slug="z")
    Subject.objects.create(title_en="Algebra", slug="a")
    assert [s.title_en for s in Subject.objects.all()] == ["Algebra", "Zoology"]
```

- [ ] **Step 2: Run it — expect failure**

Run: `uv run pytest tests/test_subject_model.py -v`
Expected: FAIL (`title_en` is not a field / `TypeError`).

- [ ] **Step 3: Edit the `Subject` model**

In `courses/models.py`, add the import near the other translation import (line ~14):

```python
from django.utils.translation import get_language
```

Replace the `Subject` class body (lines 27-45) with:

```python
class Subject(models.Model):
    """Course taxonomy: gives Course.subjects its targets.

    Bilingual (EN/PL): `title_en` is required, `title_pl` optional. Read titles
    via the `title` property (resolves the active language, EN fallback) — never
    the raw fields. Curated by the Platform Admin via the bespoke
    /manage/subjects/ UI (Phase 5a); also learner-facing on the self-enrol
    catalog (cards + subject filter, Phase 3b)."""

    title_en = models.CharField(max_length=200)
    title_pl = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(max_length=200, unique=True)

    class Meta:
        # Real-column sort key (the localized `title` is a property, unusable as
        # a DB ordering). PL UIs therefore see English-alphabetical order — an
        # accepted 5a limitation (locale-aware ordering is a 5b follow-up).
        ordering = ["title_en"]

    @property
    def title(self):
        if (get_language() or "").startswith("pl") and self.title_pl:
            return self.title_pl
        return self.title_en

    def __str__(self):
        return self.title
```

- [ ] **Step 4: Write the data migration**

Create `courses/migrations/0024_subject_localize_title.py`:

```python
from django.db import migrations, models


def copy_title_to_en(apps, schema_editor):
    Subject = apps.get_model("courses", "Subject")
    for s in Subject.objects.all():
        s.title_en = s.title
        s.save(update_fields=["title_en"])


def reverse_copy(apps, schema_editor):
    Subject = apps.get_model("courses", "Subject")
    for s in Subject.objects.all():
        s.title = s.title_en
        s.save(update_fields=["title"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0023_course_structure_flags")]

    operations = [
        migrations.AddField(
            "subject",
            "title_en",
            models.CharField(default="", max_length=200),
            preserve_default=False,
        ),
        migrations.AddField(
            "subject",
            "title_pl",
            models.CharField(blank=True, default="", max_length=200),
            preserve_default=False,
        ),
        migrations.RunPython(copy_title_to_en, reverse_copy),
        migrations.RemoveField("subject", "title"),
        migrations.AlterModelOptions("subject", options={"ordering": ["title_en"]}),
    ]
```

Note: this migration is hand-written (do NOT trust `makemigrations` alone — it emits add+remove with no copy and would wipe titles). The `RunPython` sits **between** the `AddField`s and the `RemoveField`.

- [ ] **Step 5: Fix the `Subject.title` call-sites (or imports/system checks break)**

`courses/admin.py` (SubjectAdmin, lines 16-20):

```python
@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("title_en", "title_pl", "slug")
    search_fields = ("title_en", "title_pl")
    prepopulated_fields = {"slug": ("title_en",)}
```

`courses/management/commands/seed_demo_course.py` (line 26): change `defaults={"title": "Demo Subject"}` → `defaults={"title_en": "Demo Subject"}`.

`courses/views.py` — the catalog **subject** query (lines 702-706): change `.order_by("title")` → `.order_by("title_en")`. (Leave the Course `order_by("title")` at line 724 untouched — `title` is still a real column on Course.)

`tests/factories.py` (SubjectFactory, line 62): change `title = factory.Sequence(lambda n: f"Subject {n}")` → `title_en = factory.Sequence(lambda n: f"Subject {n}")`.

`tests/test_catalog_views.py:35` and `tests/test_e2e_catalog.py:32`: `SubjectFactory(title="Math")` / `SubjectFactory(title="Science")` → `SubjectFactory(title_en="Math")` / `SubjectFactory(title_en="Science")`.

- [ ] **Step 6: Write the migration test**

Create `tests/test_subject_migrations.py`:

```python
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

APP = "courses"
BEFORE = "0023_course_structure_flags"
AFTER = "0024_subject_localize_title"


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor.loader.project_state([(APP, target)]).apps


def test_title_is_copied_into_title_en():
    old_apps = _migrate(BEFORE)
    Subject = old_apps.get_model(APP, "Subject")
    s = Subject.objects.create(title="Mathematics", slug="math-mig")

    new_apps = _migrate(AFTER)
    NewSubject = new_apps.get_model(APP, "Subject")
    assert NewSubject.objects.get(pk=s.pk).title_en == "Mathematics"

    # leave the DB migrated forward for the rest of the suite
    _migrate(AFTER)
```

(If makemigrations assigned a different filename than `0024_subject_localize_title`, update `AFTER`.)

- [ ] **Step 7: Run the full affected set — expect pass**

Run: `uv run python manage.py makemigrations --check --dry-run` (should report no changes — the hand-written migration matches the model), then `uv run pytest tests/test_subject_model.py tests/test_subject_migrations.py tests/test_catalog_views.py tests/test_e2e_catalog.py -v`
Expected: PASS. Then `uv run pytest -q` for the whole suite — Expected: PASS (FK still intact; only `Subject.title` consumers changed).

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/models.py courses/migrations/0024_subject_localize_title.py courses/admin.py courses/management/commands/seed_demo_course.py courses/views.py tests/factories.py tests/test_catalog_views.py tests/test_e2e_catalog.py tests/test_subject_model.py tests/test_subject_migrations.py
git commit -m "feat(subjects): localize Subject titles (title_en/title_pl + property)"
```

---

## Task 2: Convert `Course.subject` (FK) → `Course.subjects` (M2M, flat set)

Atomic schema change: model + 4-step migration + every FK call-site that would FieldError or break the suite, including templates. Ends green.

**Files:**
- Modify: `courses/models.py:53-59` (Course.subject → subjects)
- Create: `courses/migrations/0025_course_subjects_m2m.py`
- Modify: `courses/forms.py:44-76` (CourseForm Meta)
- Modify: `courses/views.py:717-719` (catalog filter) + `:735` prefetch
- Modify: `courses/views_manage.py:37` (course_list select_related → prefetch)
- Modify: `courses/admin.py:29` (CourseAdmin autocomplete)
- Modify: `courses/management/commands/seed_demo_course.py:28-30` (subjects.add)
- Modify: `templates/courses/catalog.html:35`, `_catalog_detail.html:3`, `manage/course_list.html:21-23`
- Modify: `tests/factories.py` (CourseFactory subjects post-gen)
- Modify: `tests/test_catalog_views.py:36`, `tests/test_e2e_catalog.py:32`, `tests/test_course_structure.py:277`
- Modify: `tests/test_subject_migrations.py` (add FK→M2M assertion)

**Interfaces:**
- Consumes: `Subject` (Task 1).
- Produces: `Course.subjects` (M2M to Subject, `related_name="courses"`, `blank=True`). `CourseFactory(subjects=[s1, s2])`. Catalog filters by `subjects__id`. Chip-row templates over `course.subjects.all`.

- [ ] **Step 1: Write failing tests (filter + chip render + factory M2M)**

Append to `tests/test_catalog_views.py` (and keep the existing `test_catalog_subject_filter`, updating its call below):

```python
def test_course_appears_under_each_of_its_subjects(client):
    make_login(client, "v3b")
    math = SubjectFactory(title_en="Math")
    art = SubjectFactory(title_en="Art")
    _open_course_with_unit(title="Geometry", subjects=[math, art])
    by_math = client.get(reverse("courses:catalog"), {"subject": math.pk})
    by_art = client.get(reverse("courses:catalog"), {"subject": art.pk})
    assert [c.title for c in by_math.context["courses"]] == ["Geometry"]
    assert [c.title for c in by_art.context["courses"]] == ["Geometry"]


def test_card_renders_subject_chip(client):
    make_login(client, "v3c")
    _open_course_with_unit(title="Calculus", subjects=[SubjectFactory(title_en="Math")])
    resp = client.get(reverse("courses:catalog"))
    assert "Math" in resp.content.decode()


def test_catalog_detail_fragment_renders_subject_chip(client):
    # _catalog_detail.html fails SILENTLY if not converted (a removed FK attr
    # resolves to empty, no crash) — so assert the chip explicitly.
    make_login(client, "v3d")
    course = _open_course_with_unit(
        title="Topology", subjects=[SubjectFactory(title_en="Math")]
    )
    resp = client.get(
        reverse("courses:catalog_detail", kwargs={"slug": course.slug}),
        HTTP_X_REQUESTED_WITH="fetch",  # _wants_fragment: X-Requested-With == "fetch"
    )
    assert "Math" in resp.content.decode()
```

Append to `tests/test_catalog_views.py` a manage-list chip assertion (also a silent-failure surface; this file already imports `make_pa` and `CourseFactory`):

```python
def test_manage_course_list_renders_subject_chip(client):
    make_pa(client, "pa_chip")
    CourseFactory(title="Mechanics", subjects=[SubjectFactory(title_en="Physics")])
    resp = client.get(reverse("courses:manage_course_list"))
    assert "Physics" in resp.content.decode()
```

Update the existing `test_catalog_subject_filter` (line 36): `_open_course_with_unit(title="Algebra", subject=math)` → `_open_course_with_unit(title="Algebra", subjects=[math])`.

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_catalog_views.py -v`
Expected: FAIL (`CourseFactory` rejects `subjects=`; filter uses `subject_id`).

- [ ] **Step 3: Edit the `Course` model**

In `courses/models.py`, replace the `subject` FK (lines 53-59) with:

```python
    subjects = models.ManyToManyField(
        Subject, blank=True, related_name="courses"
    )
```

- [ ] **Step 4: Write the M2M migration (temp related_name transition)**

Create `courses/migrations/0025_course_subjects_m2m.py`:

```python
from django.db import migrations, models


def backfill_subjects(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    # Forward accessor on the field `subjects` (stable name); only the reverse
    # related_name is temporary. Never use the ambiguous reverse subject.courses.
    for course in Course.objects.exclude(subject__isnull=True):
        course.subjects.add(course.subject_id)


def reverse_backfill(apps, schema_editor):
    Course = apps.get_model("courses", "Course")
    for course in Course.objects.all():
        first = course.subjects.first()
        if first is not None:
            course.subject_id = first.pk
            course.save(update_fields=["subject"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0024_subject_localize_title")]

    operations = [
        # 1. Add the M2M under a TEMPORARY related_name so it doesn't clash with
        #    the FK's related_name="courses" while both coexist (fields.E304).
        migrations.AddField(
            "course",
            "subjects",
            models.ManyToManyField(
                blank=True, related_name="courses_m2m", to="courses.subject"
            ),
        ),
        # 2. Backfill from the old FK (still present).
        migrations.RunPython(backfill_subjects, reverse_backfill),
        # 3. Drop the FK, freeing the "courses" reverse name.
        migrations.RemoveField("course", "subject"),
        # 4. Rename the M2M's reverse to the final "courses" (DB no-op).
        migrations.AlterField(
            "course",
            "subjects",
            models.ManyToManyField(
                blank=True, related_name="courses", to="courses.subject"
            ),
        ),
    ]
```

Hand-written (makemigrations would Remove+Add in an unsafe order with no backfill). Verify with `uv run python manage.py makemigrations --check --dry-run` → no changes.

- [ ] **Step 5: Add the `CourseFactory` M2M post-generation hook**

In `tests/factories.py`, inside `CourseFactory` (after the existing fields, ~line 72):

```python
    @factory.post_generation
    def subjects(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.subjects.add(*extracted)
```

- [ ] **Step 6: Fix the FK call-sites (views/forms/admin/seed)**

`courses/forms.py` — `CourseForm.Meta`: in `fields` (line 47) `"subject"` → `"subjects"`; in `labels` (line 63) replace `"subject": _("Subject")` with `"subjects": _("Subjects")`; in `widgets` (line 72-76) add `"subjects": forms.CheckboxSelectMultiple,`.

`courses/views.py` — catalog filter (line 718-719):

```python
    if sel_subject:
        qs = qs.filter(subjects__id=sel_subject).distinct()
```

and add a prefetch where `qs` is finalized (after line 724 `qs = qs.order_by("title")`):

```python
    qs = qs.prefetch_related("subjects")
```

`courses/views_manage.py` — `course_list` (line 37): change

```python
    courses = courses.select_related("subject", "owner").prefetch_related(
        "self_enroll_cohorts"
    )
```

to

```python
    courses = courses.select_related("owner").prefetch_related(
        "subjects", "self_enroll_cohorts"
    )
```

`courses/admin.py` — `CourseAdmin` (line 29): `autocomplete_fields = ("subject", "owner")` → `("subjects", "owner")`. (M2M autocomplete needs the related admin's `search_fields`, which Task 1 set on `SubjectAdmin`.)

`courses/management/commands/seed_demo_course.py` (lines 28-30): drop `"subject": subject` from the course `get_or_create` defaults, and after the course exists add:

```python
        course.subjects.add(subject)
```

- [ ] **Step 7: Convert the templates to subject chip rows**

`templates/courses/catalog.html` (line 35): replace

```django
      {% if course.subject %}<p class="catalog__eyebrow">{{ course.subject.title }}</p>{% endif %}
```

with

```django
      {% with subs=course.subjects.all %}{% if subs %}<p class="catalog__eyebrow">{% for s in subs %}{{ s.title }}{% if not forloop.last %} · {% endif %}{% endfor %}</p>{% endif %}{% endwith %}
```

`templates/courses/_catalog_detail.html` (line 3): same replacement (uses `catalog__eyebrow`).

`templates/courses/manage/course_list.html` (lines 21-23): replace

```django
            {% if course.subject %}
              <span class="course-list__subject">{{ course.subject.title }}</span>
            {% endif %}
```

with

```django
            {% with subs=course.subjects.all %}{% if subs %}
              <span class="course-list__subject">{% for s in subs %}{{ s.title }}{% if not forloop.last %} · {% endif %}{% endfor %}</span>
            {% endif %}{% endwith %}
```

- [ ] **Step 8: Sweep remaining test call-sites**

`tests/test_e2e_catalog.py` (lines 28-34): in the `CourseFactory(...)` call, remove `subject=SubjectFactory(title="Science")` and instead pass `subjects=[SubjectFactory(title_en="Science")]`.

`tests/test_course_structure.py:277`: in the parametrize list, `"subject"` → `"subjects"`.

Run the grep checklist to confirm nothing is missed (scope `subject=` to `courses/` + `tests/`; ignore email `subject` in `test_invitations.py`):

Run: `git grep -nE "\.subject\b|subject_id|SubjectFactory\(|[\"']subject[\"']" courses/ tests/ templates/`
Expected: only intentional hits remain (e.g. `subjects`, `self_enroll_cohorts`); no bare `course.subject` / `subject_id` / `"subject"` field refs.

- [ ] **Step 9: Extend the migration test with the FK→M2M assertion**

In `tests/test_subject_migrations.py`, add:

```python
def test_fk_subject_lands_in_m2m():
    old_apps = _migrate("0024_subject_localize_title")
    Subject = old_apps.get_model(APP, "Subject")
    Course = old_apps.get_model(APP, "Course")
    s = Subject.objects.create(title_en="Physics", slug="phys-mig")
    c = Course.objects.create(title="Mechanics", slug="mech-mig", subject=s)

    new_apps = _migrate("0025_course_subjects_m2m")
    NewCourse = new_apps.get_model(APP, "Course")
    assert list(NewCourse.objects.get(pk=c.pk).subjects.values_list("pk", flat=True)) == [s.pk]

    _migrate("0025_course_subjects_m2m")
```

- [ ] **Step 10: Run the full suite — expect pass**

Run: `uv run python manage.py makemigrations --check --dry-run` (no changes), then `uv run pytest -q`
Expected: PASS. (`course_create` silently drops subjects on POST — that defect is caught in Task 3; no current test asserts create-time subject persistence, so the suite is green here.)

- [ ] **Step 11: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add -A
git commit -m "feat(subjects): Course.subject FK -> subjects M2M (flat set) with safe migration"
```

---

## Task 3: Fix `course_create` to persist selected subjects (`save_m2m`)

TDD the create-vs-edit asymmetry: `course_create` uses `commit=False` + `course.save()` with no `save_m2m()`, so M2M selections are silently dropped on create (edit already works via `form.save()`).

**Files:**
- Modify: `courses/views_manage.py:45-58` (course_create)
- Create/append: `tests/test_subject_admin_views.py` (view-level persistence tests)

**Interfaces:**
- Consumes: `Course.subjects` (Task 2), `CourseForm` with `subjects` (Task 2), `make_pa`/`make_login` factories.

- [ ] **Step 1: Write the failing view-level test**

Create `tests/test_subject_admin_views.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Course
from tests.factories import SubjectFactory, make_login, make_pa

pytestmark = pytest.mark.django_db


def _course_post(subjects):
    return {
        "title": "Mechanics",
        "slug": "",
        "subjects": [s.pk for s in subjects],
        "language": "en",
        "overview": "",
        "visibility": "assigned",
        "owner": "",
        "html_css": "",
        "html_js": "",
        "structure": "chapters",
    }


def test_course_create_persists_selected_subjects(client):
    make_pa(client, "pa_create")
    math = SubjectFactory(title_en="Math")
    art = SubjectFactory(title_en="Art")
    resp = client.post(
        reverse("courses:manage_course_create"), _course_post([math, art])
    )
    assert resp.status_code == 302
    course = Course.objects.get(title="Mechanics")
    assert set(course.subjects.values_list("pk", flat=True)) == {math.pk, art.pk}


def test_course_edit_persists_selected_subjects(client):
    pa = make_pa(client, "pa_edit")
    from tests.factories import CourseFactory

    course = CourseFactory(title="Optics", owner=pa)
    math = SubjectFactory(title_en="Math")
    data = _course_post([math])
    data["title"] = "Optics"
    data["slug"] = course.slug
    resp = client.post(
        reverse("courses:manage_course_edit", kwargs={"slug": course.slug}), data
    )
    assert resp.status_code == 302
    assert set(course.subjects.values_list("pk", flat=True)) == {math.pk}
```

(Confirm `make_pa` exists in `tests/factories.py`; if its signature differs, mirror the helper used by other manage-view tests. Check `git grep -n "def make_pa" tests/factories.py`.)

- [ ] **Step 2: Run — expect create test to fail**

Run: `uv run pytest tests/test_subject_admin_views.py -v`
Expected: `test_course_create_persists_selected_subjects` FAILS (subjects empty); the edit test PASSES (already correct).

- [ ] **Step 3: Add `save_m2m()` to `course_create`**

In `courses/views_manage.py`, `course_create` (lines 48-53), after `course.save()`:

```python
        if form.is_valid():
            course = form.save(commit=False)
            if course.owner_id is None:
                course.owner = request.user  # default owner = creating PA
            course.save()
            form.save_m2m()  # persist subjects + self_enroll_cohorts (commit=False skipped them)
            return redirect("courses:manage_builder", slug=course.slug)
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_subject_admin_views.py -v`
Expected: PASS (both).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views_manage.py tests/test_subject_admin_views.py
git commit -m "fix(courses): persist M2M subjects on course_create (save_m2m)"
```

---

## Task 4: Grant subject permissions to the Platform Admin role

**Files:**
- Modify: `institution/roles.py`
- Create/append: `tests/test_subject_roles.py`

**Interfaces:**
- Produces: PA role holds `courses.add_subject` / `change_subject` / `delete_subject`; CA/Teacher/Student do not.

- [ ] **Step 1: Write the failing permission test**

Create `tests/test_subject_roles.py`:

```python
import pytest
from django.contrib.auth.models import Group

from institution.roles import PLATFORM_ADMIN, seed_roles

pytestmark = pytest.mark.django_db

SUBJECT_PERMS = {"add_subject", "change_subject", "delete_subject"}


def test_platform_admin_holds_subject_perms():
    seed_roles()
    pa = Group.objects.get(name=PLATFORM_ADMIN)
    codenames = set(pa.permissions.values_list("codename", flat=True))
    assert SUBJECT_PERMS <= codenames


def test_platform_admin_does_not_hold_view_subject():
    seed_roles()
    pa = Group.objects.get(name=PLATFORM_ADMIN)
    codenames = set(pa.permissions.values_list("codename", flat=True))
    assert "view_subject" not in codenames
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_subject_roles.py -v`
Expected: FAIL (`add_subject` not granted).

- [ ] **Step 3: Add the perms to `institution/roles.py`**

After `COURSE_PERMS` (line 19), add:

```python
# Subjects are PA-only taxonomy (Phase 5a). view_subject is intentionally
# omitted — the only audience is the PA, who holds change_subject.
SUBJECT_PERMS = [
    "courses.add_subject",
    "courses.change_subject",
    "courses.delete_subject",
]
```

and include it in `PLATFORM_ADMIN_PERMS` (line 32) — add `*SUBJECT_PERMS,` after `*COURSE_PERMS,`.

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_subject_roles.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add institution/roles.py tests/test_subject_roles.py
git commit -m "feat(subjects): grant subject add/change/delete to Platform Admin role"
```

---

## Task 5: `SubjectForm` (bilingual titles + create/edit slug behavior)

**Files:**
- Modify: `courses/forms.py` (add `unique_subject_slug` + `SubjectForm`; import `Subject`)
- Create: `tests/test_subject_form.py`

**Interfaces:**
- Consumes: `Subject` (Task 1).
- Produces: `SubjectForm` (ModelForm over `title_en`, `title_pl`, `slug`; slug optional, create-derives / edit-retains, uniqueness-aware excluding self). `unique_subject_slug(title, exclude_pk=None)`.

- [ ] **Step 1: Write failing form tests**

Create `tests/test_subject_form.py`:

```python
import pytest

from courses.forms import SubjectForm
from courses.models import Subject

pytestmark = pytest.mark.django_db


def test_create_derives_slug_from_title_en():
    form = SubjectForm(data={"title_en": "Pure Mathematics", "title_pl": "", "slug": ""})
    assert form.is_valid(), form.errors
    subject = form.save()
    assert subject.slug == "pure-mathematics"


def test_derived_slug_collision_gets_suffix():
    Subject.objects.create(title_en="Math", slug="math")
    form = SubjectForm(data={"title_en": "Math", "title_pl": "", "slug": ""})
    assert form.is_valid(), form.errors
    assert form.save().slug == "math-2"


def test_edit_blank_slug_retains_existing():
    subject = Subject.objects.create(title_en="Math", slug="math")
    form = SubjectForm(
        data={"title_en": "Mathematics", "title_pl": "", "slug": ""}, instance=subject
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.slug == "math"  # NOT re-derived to "mathematics"
    assert saved.title_en == "Mathematics"


def test_explicit_duplicate_slug_is_a_field_error():
    Subject.objects.create(title_en="Math", slug="math")
    form = SubjectForm(data={"title_en": "Other", "title_pl": "", "slug": "math"})
    assert not form.is_valid()
    assert "slug" in form.errors


def test_title_pl_optional():
    form = SubjectForm(data={"title_en": "Science", "title_pl": "", "slug": "sci"})
    assert form.is_valid(), form.errors
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_subject_form.py -v`
Expected: FAIL (`SubjectForm` undefined).

- [ ] **Step 3: Implement `unique_subject_slug` + `SubjectForm`**

In `courses/forms.py`, add `Subject` to the model imports (line 11 area: `from courses.models import Subject`). After `unique_course_slug` (line 29), add:

```python
def unique_subject_slug(title, exclude_pk=None):
    """slugify(title); on collision append the smallest free -2, -3, … suffix."""
    base = slugify(title) or "subject"
    qs = Subject.objects.all()
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if not qs.filter(slug=base).exists():
        return base
    n = 2
    while qs.filter(slug=f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"
```

Then add the form (place it after `CourseForm`, before `ReviewResponseForm`):

```python
class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ["title_en", "title_pl", "slug"]
        labels = {
            "title_en": _("Title (English)"),
            "title_pl": _("Title (Polish)"),
            "slug": _("Slug"),
        }
        help_texts = {
            "title_pl": _("Optional — falls back to the English title when blank."),
            "slug": _("Optional — generated from the English title if left blank."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False

    def clean_slug(self):
        slug = self.cleaned_data.get("slug")
        if not slug:
            if self.instance.pk and self.instance.slug:
                slug = self.instance.slug  # edit: retain existing slug, don't re-derive
            else:
                slug = unique_subject_slug(
                    self.cleaned_data.get("title_en", ""), exclude_pk=self.instance.pk
                )
        qs = Subject.objects.filter(slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("That slug is already in use."))
        return slug
```

(`title_en` precedes `slug` in `Meta.fields`, so `cleaned_data["title_en"]` is available when `clean_slug` runs.)

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_subject_form.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/forms.py tests/test_subject_form.py
git commit -m "feat(subjects): SubjectForm with bilingual titles + create/edit slug rules"
```

---

## Task 6: Subject management views + URLs

**Files:**
- Modify: `courses/views_manage.py` (imports + 4 views)
- Modify: `courses/urls.py` (4 routes)
- Append: `tests/test_subject_admin_views.py` (permission + CRUD tests)

**Interfaces:**
- Consumes: `SubjectForm` (Task 5), `Subject` (Task 1), subject perms (Task 4).
- Produces: URL names `courses:manage_subject_list` / `manage_subject_create` / `manage_subject_edit` / `manage_subject_delete`. Views render `courses/manage/subject_list.html`, `subject_form.html`, `subject_confirm_delete.html`.

- [ ] **Step 1: Write failing view tests**

Append to `tests/test_subject_admin_views.py`:

```python
from courses.models import Subject


def test_pa_can_list_subjects(client):
    make_pa(client, "pa_list")
    SubjectFactory(title_en="Math")
    resp = client.get(reverse("courses:manage_subject_list"))
    assert resp.status_code == 200
    assert "Math" in resp.content.decode()


def test_pa_can_create_subject(client):
    make_pa(client, "pa_new")
    resp = client.post(
        reverse("courses:manage_subject_create"),
        {"title_en": "Biology", "title_pl": "Biologia", "slug": ""},
    )
    assert resp.status_code == 302
    assert Subject.objects.filter(title_en="Biology").exists()


def test_pa_can_edit_subject(client):
    make_pa(client, "pa_ed")
    s = SubjectFactory(title_en="Maths")
    resp = client.post(
        reverse("courses:manage_subject_edit", kwargs={"slug": s.slug}),
        {"title_en": "Mathematics", "title_pl": "", "slug": ""},
    )
    assert resp.status_code == 302
    s.refresh_from_db()
    assert s.title_en == "Mathematics"


def test_delete_unlinks_without_orphaning_course(client):
    make_pa(client, "pa_del")
    from tests.factories import CourseFactory

    s = SubjectFactory(title_en="Temp")
    course = CourseFactory(subjects=[s])
    resp = client.post(
        reverse("courses:manage_subject_delete", kwargs={"slug": s.slug})
    )
    assert resp.status_code == 302
    assert not Subject.objects.filter(pk=s.pk).exists()
    course.refresh_from_db()  # course survives, just loses the subject
    assert course.subjects.count() == 0


def test_course_admin_cannot_create_subject(client):
    from django.contrib.auth.models import Group
    from institution.roles import COURSE_ADMIN, seed_roles

    seed_roles()
    user = make_login(client, "ca1")
    user.groups.add(Group.objects.get(name=COURSE_ADMIN))  # CA lacks add_subject
    resp = client.post(
        reverse("courses:manage_subject_create"),
        {"title_en": "X", "title_pl": "", "slug": ""},
    )
    assert resp.status_code == 403


def test_student_cannot_list_subjects(client):
    make_login(client, "stu1")
    resp = client.get(reverse("courses:manage_subject_list"))
    assert resp.status_code == 403
```

(Confirm how existing tests build a Course Admin / assign a role via `make_login`; mirror their pattern — `git grep -n "def make_login\|def make_pa\|role=" tests/factories.py`. Adjust the role kwarg if the helper differs.)

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_subject_admin_views.py -v -k subject`
Expected: FAIL (URLs/views undefined).

- [ ] **Step 3: Add the views**

In `courses/views_manage.py`, extend imports:

```python
from django.db.models import Count
```

and add `Subject` to the courses.models imports, and `from courses.forms import SubjectForm`.

Append the views:

```python
@login_required
@permission_required("courses.change_subject", raise_exception=True)
def subject_list(request):
    subjects = Subject.objects.annotate(course_count=Count("courses", distinct=True))
    return render(request, "courses/manage/subject_list.html", {"subjects": subjects})


@login_required
@permission_required("courses.add_subject", raise_exception=True)
def subject_create(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("courses:manage_subject_list")
    else:
        form = SubjectForm()
    return render(
        request, "courses/manage/subject_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("courses.change_subject", raise_exception=True)
def subject_edit(request, slug):
    subject = get_object_or_404(Subject, slug=slug)
    if request.method == "POST":
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            return redirect("courses:manage_subject_list")
    else:
        form = SubjectForm(instance=subject)
    return render(
        request,
        "courses/manage/subject_form.html",
        {"form": form, "creating": False, "subject": subject},
    )


@login_required
@permission_required("courses.delete_subject", raise_exception=True)
def subject_delete(request, slug):
    subject = get_object_or_404(Subject, slug=slug)
    if request.method == "POST":
        subject.delete()  # M2M: just unlinks from courses, no orphaned data
        return redirect("courses:manage_subject_list")
    course_count = subject.courses.count()
    return render(
        request,
        "courses/manage/subject_confirm_delete.html",
        {"subject": subject, "course_count": course_count},
    )
```

- [ ] **Step 4: Add the URLs**

In `courses/urls.py`, in the `/manage/` block (after the course routes, ~line 62):

```python
    path("manage/subjects/", views_manage.subject_list, name="manage_subject_list"),
    path(
        "manage/subjects/new/",
        views_manage.subject_create,
        name="manage_subject_create",
    ),
    path(
        "manage/subjects/<slug:slug>/edit/",
        views_manage.subject_edit,
        name="manage_subject_edit",
    ),
    path(
        "manage/subjects/<slug:slug>/delete/",
        views_manage.subject_delete,
        name="manage_subject_delete",
    ),
```

- [ ] **Step 5: Add minimal templates (so the views render in tests)**

Create the three templates now (full styling/i18n polish lands in Task 7; these must render the assertions above). `templates/courses/manage/subject_list.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% trans "Subjects" %}</h1>
<a class="btn" href="{% url 'courses:manage_subject_create' %}">{% trans "New subject" %}</a>
<ul class="card-list">
  {% for s in subjects %}
  <li>
    <span>{{ s.title_en }}</span>
    <div class="row-actions">
      <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_subject_edit' s.slug %}">{% trans "Edit" %}</a>
      <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_subject_delete' s.slug %}">{% trans "Delete" %}</a>
    </div>
  </li>
  {% endfor %}
</ul>
{% endblock %}
```

`templates/courses/manage/subject_form.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% if creating %}{% trans "New subject" %}{% else %}{% trans "Edit subject" %}{% endif %}</h1>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button class="btn" type="submit">{% trans "Save" %}</button>
  <a class="btn btn--ghost" href="{% url 'courses:manage_subject_list' %}">{% trans "Cancel" %}</a>
</form>
{% endblock %}
```

`templates/courses/manage/subject_confirm_delete.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% blocktrans with name=subject.title_en %}Delete subject "{{ name }}"?{% endblocktrans %}</h1>
<form method="post">
  {% csrf_token %}
  <button class="btn btn--ghost" type="submit">{% trans "Delete" %}</button>
  <a class="btn btn--ghost" href="{% url 'courses:manage_subject_list' %}">{% trans "Cancel" %}</a>
</form>
{% endblock %}
```

- [ ] **Step 6: Run — expect pass**

Run: `uv run pytest tests/test_subject_admin_views.py -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add courses/views_manage.py courses/urls.py templates/courses/manage/subject_list.html templates/courses/manage/subject_form.html templates/courses/manage/subject_confirm_delete.html tests/test_subject_admin_views.py
git commit -m "feat(subjects): PA-only /manage/subjects/ CRUD views + routes"
```

---

## Task 7: Polish templates (usage count + plural strings) + nav link

**Files:**
- Modify: `templates/courses/manage/subject_list.html` (count + plural + title_pl + manage styling)
- Modify: `templates/courses/manage/subject_confirm_delete.html` (plural count)
- Modify: `templates/base.html` (nav link)
- Append: `tests/test_subject_admin_views.py` (usage-count + plural assertions)

**Interfaces:**
- Consumes: `subject_list` annotation `course_count` (Task 6), nav perms.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_subject_admin_views.py`:

```python
def test_list_shows_usage_count(client):
    make_pa(client, "pa_count")
    from tests.factories import CourseFactory

    s = SubjectFactory(title_en="Math")
    CourseFactory(subjects=[s])
    CourseFactory(subjects=[s])
    resp = client.get(reverse("courses:manage_subject_list"))
    body = resp.content.decode()
    assert "2" in body  # used by 2 courses


def test_nav_shows_subjects_link_for_pa(client):
    make_pa(client, "pa_nav")
    resp = client.get(reverse("courses:manage_subject_list"))
    assert reverse("courses:manage_subject_list") in resp.content.decode()


def test_nav_hides_subjects_link_for_student(client):
    make_login(client, "stu_nav")
    resp = client.get(reverse("courses:my_courses"))
    assert reverse("courses:manage_subject_list") not in resp.content.decode()
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_subject_admin_views.py -v -k "usage_count or nav"`
Expected: FAIL (count not rendered; nav link absent).

- [ ] **Step 3: Flesh out `subject_list.html`**

Replace `templates/courses/manage/subject_list.html` with:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Subjects" %} · libli{% endblock %}
{% block content %}
<section class="manage">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "Subjects" %}</h1>
    <a class="btn btn--primary" href="{% url 'courses:manage_subject_create' %}">{% trans "New subject" %}</a>
  </header>
  {% if subjects %}
    <ul class="card-list">
      {% for s in subjects %}
        <li>
          <div class="course-list__main">
            <span class="course-list__title">{{ s.title_en }}</span>
            <p class="course-list__spec">
              {% if s.title_pl %}<span>{{ s.title_pl }}</span>{% else %}<span aria-hidden="true">—</span>{% endif %}
              <span class="course-list__sep" aria-hidden="true">·</span>
              <span>{% blocktrans count n=s.course_count %}used by {{ n }} course{% plural %}used by {{ n }} courses{% endblocktrans %}</span>
            </p>
          </div>
          <div class="row-actions">
            <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_subject_edit' s.slug %}">{% trans "Edit" %}</a>
            <a class="btn btn--ghost btn--small" href="{% url 'courses:manage_subject_delete' s.slug %}">{% trans "Delete" %}</a>
          </div>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <div class="manage__empty"><p>{% trans "No subjects yet." %}</p></div>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 4: Add the plural count to the delete confirmation**

In `templates/courses/manage/subject_confirm_delete.html`, after the `<h1>`:

```django
<p>{% blocktrans count n=course_count %}This subject is used by {{ n }} course; deleting it removes it from that course.{% plural %}This subject is used by {{ n }} courses; deleting it removes it from those courses.{% endblocktrans %}</p>
```

- [ ] **Step 5: Add the nav link**

In `templates/base.html`, after the Manage link block (lines 88-90):

```django
          {% if perms.courses.change_subject %}
          <a class="app-nav__link" href="{% url 'courses:manage_subject_list' %}">{% trans "Subjects" %}</a>
          {% endif %}
```

- [ ] **Step 6: Run — expect pass**

Run: `uv run pytest tests/test_subject_admin_views.py -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format .
git add templates/courses/manage/subject_list.html templates/courses/manage/subject_confirm_delete.html templates/base.html tests/test_subject_admin_views.py
git commit -m "feat(subjects): subject list usage count, plural strings, nav link"
```

---

## Task 8: i18n (PL translations) + e2e + roadmap

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Create: `tests/test_e2e_subjects.py`
- Modify: `docs/roadmap.md`

**Interfaces:**
- Consumes: all UI strings from Tasks 1-7.

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Then open `locale/pl/LC_MESSAGES/django.po` and fill PL translations for the new msgids: "Subjects", "New subject", "Edit subject", "Delete subject", "Title (English)", "Title (Polish)", "Slug", the `title_pl`/slug help texts, "No subjects yet.", the "used by N course(s)" plural (both forms — `nplurals=3` for PL: provide `msgstr[0]`, `[1]`, `[2]`), the delete-confirmation plural, and the `Delete subject "%(name)s"?` string.

**Gotcha:** `makemessages` re-marks copied strings `#, fuzzy` (ignored at runtime) and can mis-guess. Clear every stale `#, fuzzy` flag on the new entries and verify each msgstr by eye. Provide all three Polish plural forms for the count strings (e.g. `0 → "używany w %(n)s kursie"`, `1 → "używany w %(n)s kursach"`, `2 → "używany w %(n)s kursach"` — confirm grammar; 1 kurs / 2–4 kursy / 5 kursów).

- [ ] **Step 2: Add a plural-rendering test**

Append to `tests/test_subject_admin_views.py`:

```python
from django.utils import translation


def test_usage_count_plural_pl(client):
    make_pa(client, "pa_pl")
    from tests.factories import CourseFactory

    s = SubjectFactory(title_en="Math")
    for _ in range(5):
        CourseFactory(subjects=[s])
    with translation.override("pl"):
        resp = client.get(reverse("courses:manage_subject_list"))
    body = resp.content.decode()
    assert "kurs" in body.lower()  # PL plural form rendered (not English "courses")
```

- [ ] **Step 3: Compile + run**

Run: `uv run python manage.py compilemessages -l pl` then `uv run pytest tests/test_subject_admin_views.py -v -k plural`
Expected: PASS.

- [ ] **Step 4: Write the e2e test**

Create `tests/test_e2e_subjects.py`, mirroring `tests/test_e2e_catalog.py` (reuse its `_login` helper pattern, `page` + `live_server` fixtures). Flow, all via real gestures:

1. Seed a PA user and log in (mirror how `test_e2e_catalog` builds users; use a PA so the nav shows "Subjects").
2. `page.get_by_role("link", name="Subjects").click()` → reach the list.
3. Click "New subject", fill `title_en` = "Geography", submit → assert it appears in the list.
4. Seed an open course with a unit and attach the subject (either through the course edit form's Subjects checkboxes, or via a factory in the fixture, per the catalog e2e's setup), with `visibility="open"` and **empty `self_enroll_cohorts`** so it is catalog-eligible.
5. Seed a **separate non-staff student** (PA is staff → `catalog_courses_for` would surface a different set), log in as the student, go to `/catalog/`, select the "Geography" subject filter, submit → assert the course is listed.

```python
def test_pa_creates_subject_and_student_filters_catalog(page, live_server):
    # ... seed PA + student + open course with a unit (see test_e2e_catalog setup) ...
    # PA path:
    _login(page, live_server, pa_username)
    page.get_by_role("link", name="Subjects").click()
    page.get_by_role("link", name="New subject").click()
    page.fill("input[name='title_en']", "Geography")
    page.get_by_role("button", name="Save").click()
    assert "Geography" in page.content()
    # ... attach subject to the open course ...
    # Student path:
    _login(page, live_server, student_username)
    page.goto(f"{live_server.url}/catalog/")
    page.select_option("select[name='subject']", label="Geography")
    page.get_by_role("button", name="Filter").click()
    assert "<course title>" in page.content()
```

Fill the seeding/attachment specifics from the `test_e2e_catalog.py` fixture pattern (it builds an open course with a unit and a `make_verified_user` student). Drive the real click path — no `page.evaluate` shortcuts.

- [ ] **Step 5: Run the e2e + full suite**

Run: `uv run pytest tests/test_e2e_subjects.py -v` then `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Update the roadmap**

In `docs/roadmap.md`, the deferred table row "Subject localization (EN/PL)": mark it resolved — note that Phase 5a landed per-language `title_en`/`title_pl` (with EN-order limitation), a bespoke PA `/manage/subjects/` UI, and multi-subject courses (`Course.subjects` M2M). Leave **taxonomy structure (5b)**, **merge subjects**, and **platform-wide content translation** as the recorded follow-ups (move them into the deferred table / a "5b" note as appropriate).

- [ ] **Step 7: Manual UI verification (light + dark)**

Per the project's "verify UI with screenshots" norm: spin up a throwaway Playwright screenshot harness, capture `/manage/subjects/`, the subject form, the delete confirmation, the catalog cards (chips), and the manage course list (chips) in **both** light and dark, self-critique, then delete the harness. Fix any contrast/spacing issues found.

- [ ] **Step 8: Final lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_e2e_subjects.py tests/test_subject_admin_views.py docs/roadmap.md
git commit -m "feat(subjects): PL translations, e2e flow, roadmap update"
```

---

## Definition of Done

- `uv run pytest -q` green (incl. model, migration, permission, form, view, catalog, plural, e2e tests).
- `uv run ruff check .` and `uv run ruff format --check .` clean.
- `uv run python manage.py makemigrations --check --dry-run` reports no missing migrations.
- `uv run python manage.py migrate` + `setup_roles` clean; PA role holds the three subject perms.
- `.po`/`.mo` updated with PL strings (incl. 3-form plurals); no stray fuzzy flags.
- UI verified light + dark (screenshots, delete-after-review).
- `docs/roadmap.md` updated; 5b / merge / content-translation recorded as follow-ups.
