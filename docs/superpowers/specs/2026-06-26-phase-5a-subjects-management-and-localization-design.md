# Phase 5a — Subjects: management UI + localization + multi-subject courses

*Brainstormed 2026-06-26. A focused slice carved out of the broad "Phase 5 —
Platform admin polish" roadmap bundle, scoped to the **subjects/taxonomy** strand.*

## Context

`Subject` today is a flat `title` + `slug` model, created only through Django
admin, and `Course.subject` is a single nullable FK. As of Phase 3b subjects are
learner-facing: they appear on the self-enrol catalog cards and the catalog
subject filter. Two debts are outstanding:

- **No bespoke management UI** — subjects can only be curated via Django admin,
  contrary to the Phase-5 "a non-technical Platform Admin runs the institution"
  goal.
- **Monolingual titles** — `Subject.title` is one string rendered identically in
  the EN and PL UI (the deferred "Subject localization" item in
  `docs/roadmap.md`).

This slice resolves both, and — per the design dialogue — also lets a course
belong to **multiple subjects**.

## Goals

1. A Platform Admin can create / edit / delete subjects from a bespoke
   `/manage/subjects/` UI, with **no Django admin required**.
2. Subject titles are **bilingual (EN/PL)** and render in the active UI language.
3. A course can have **multiple subjects** (flat, unordered set).

## Non-goals (explicitly deferred)

- **Taxonomy structure** — hierarchy (subject → sub-subject), levels/grades, or
  free-form tags. This is the follow-on "5b" slice (the user's "2 follows").
- **Merge** subjects (fold A into B, reassigning courses) — a fast follow if
  duplicates pile up; deletion + editing cover early cleanup.
- A **generalized content-translation layer** for other models (course titles,
  overviews, element content). That remains the separate cross-cutting
  "content translation strategy" decision; this slice deliberately does **not**
  commit it. Per-language fields here are a local choice for one model, not a
  platform-wide precedent.
- **Course-Admin subject creation** — only Platform Admin curates the
  vocabulary; CAs continue to *assign* existing subjects to their courses.

## Design decisions (from the brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Localization storage | Per-language fields (`title_en`, `title_pl`) | Two fixed languages (EN/PL); least machinery; no new dependency; does not prematurely commit the platform-wide translation strategy. |
| Who curates subjects | Platform Admin only | Subjects are institution-wide vocabulary; PA-only keeps it curated and matches the Phase-5 framing. CAs still assign from the controlled list. |
| Course ↔ subject cardinality | Many-to-many, **flat set** | A course can belong to several subjects; no "primary" precedence to avoid inventing hierarchy/ordering in this slice. |
| Cleanup operations | Create / edit / delete (no merge) | Merge is the most code; defer until duplicate sprawl actually appears. |

## Data model

### `Subject` (`courses/models.py`)

Replace the single `title` field with two per-language fields and expose a
read-path property:

- `title_en = models.CharField(max_length=200)` — **required**.
- `title_pl = models.CharField(max_length=200, blank=True)` — optional;
  blank means "fall back to EN".
- `slug = models.SlugField(max_length=200, unique=True)` — unchanged; one slug
  per subject, **language-independent**.
- `title` **property**: returns the field for the active language
  (`django.utils.translation.get_language()`), falling back to `title_en` when
  the language is EN, unknown, or the PL field is blank. This is the **single
  read path** — `__str__`, catalog cards, the catalog filter ordering, and all
  templates use `subject.title` and need no per-language awareness.

  ```python
  @property
  def title(self):
      if (get_language() or "").startswith("pl") and self.title_pl:
          return self.title_pl
      return self.title_en
  ```

  `__str__` returns `self.title`.

- `Meta.ordering = ["title_en"]` — gives every `Subject` queryset (the management
  list, the `CourseForm` checkbox choices, the catalog sidebar) a stable, real-
  column default order. Ordering must use `title_en`, not the localized `title`
  property (a property cannot be a DB sort key). This also lets call-sites drop
  explicit `order_by("title_en")` where the default suffices.
  **Accepted limitation:** a Polish UI therefore shows subject lists in
  English-alphabetical order, which may look unsorted to PL users. This is an
  accepted trade-off for this slice; locale-aware ordering is a 5b follow-up, not
  a bug.

> **Note on `order_by("title")`:** the catalog view currently orders subjects by
> the DB column `title` (see `courses/views.py`). Once `title` is a Python
> property there is no `title` column to order by. Replace such ordering with
> `order_by("title_en")` (a stable, language-independent sort key). This is a
> required call-site change, not optional — flagged for the plan.

### `Course.subjects` (`courses/models.py`)

Replace the `subject` FK with:

- `subjects = models.ManyToManyField(Subject, blank=True, related_name="courses")`

`related_name="courses"` is preserved, so `subject.courses` continues to work
(it was the FK's reverse accessor and is used by the catalog usage queries).

## Migrations

Logical steps (may be combined into fewer migration files where Django allows,
but the ordering and the `related_name` transition below matter):

1. **Add per-language title fields.** Add `title_en` with
   `AddField(default="", preserve_default=False)` (one-shot — `title_en` is
   required, no `blank=True`, so the default exists only to populate existing
   rows) and `title_pl`. Then a `RunPython` copies the old `title` into
   `title_en` for every row. The `RunPython` MUST be ordered **between** the
   `AddField(title_en)` and the `RemoveField(title)` operations — a naive
   `makemigrations` emits add+remove with no copy and would wipe titles. Remove
   the old `title` field last.
2. **Add `Course.subjects` M2M under a temporary `related_name`.** The old FK
   `subject` already uses `related_name="courses"`. If the new M2M also declared
   `related_name="courses"` while the FK still exists, the two reverse accessors
   clash (`fields.E304`) — and the historical model state during the step-3
   backfill would carry both. So add the M2M with a temporary, non-clashing
   `related_name` (e.g. `courses_m2m`) in this step.
3. **Backfill M2M.** Data-migrate: for each course with a non-null `subject`, add
   that subject to the new M2M. Only the reverse `related_name` is temporary —
   the **field name `subjects` is stable across all steps**, so the forward
   accessor is `course.subjects.add(subject)` (reading the old FK
   `course.subject`). Use this forward accessor only; never the ambiguous reverse
   `subject.courses`, to avoid relying on the clashing accessor.
4. **Drop old FK, then rename the M2M's `related_name` to `courses`.** Remove the
   `Course.subject` FK first (freeing the `courses` reverse name), then
   `AlterField` the M2M's `related_name` from the temporary value to `courses`.
   After this step `subject.courses` resolves to the M2M, matching the final
   model definition.

All existing subject titles and course→subject assignments are preserved. Data
migrations use `apps.get_model` (historical models) and are reversible where
practical (reverse can be a no-op for the destructive drops, documented).

## Permissions

- Subject management is gated on the Django model permissions
  `courses.add_subject`, `courses.change_subject`, `courses.delete_subject`,
  using `@permission_required(..., raise_exception=True)` — the same pattern the
  existing `/manage/` course views use.
- The **Platform Admin role** must be granted these three perms via
  `setup_roles` (the role-permission seeding entry point; not via a migration
  RunPython — consistent with the established precedent that `Permission` rows
  may not exist yet inside a migration). The plan must add the perms to the PA
  role definition and confirm `setup_roles` grants them.
- Course Admins are **not** granted subject add/change/delete; they retain the
  ability to assign existing subjects via the course form only.
- Django auto-creates a `view_subject` permission; this slice **intentionally
  does not use it**. The list view gates on `change_subject` because the only
  audience is the PA (who holds all three of add/change/delete), and the list is
  the management hub rather than a read-only surface. If a view-only subject role
  is ever introduced, switch the list gate to `view_subject` then.

## Management UI (`/manage/subjects/`)

New views in `courses/views_manage.py`, new URL routes under the existing
`/manage/` namespace, new templates following the existing manage-area styling
(the styled `.card-list` / `.row-actions` ledger pattern, light + dark).

**Navigation (mandatory):** the area must be reachable from the UI, not just by
URL. Add a "Subjects" nav link in `templates/base.html`, gated on
`{% if perms.courses.change_subject %}`, mirroring the existing Manage / Cohorts
/ Groups nav entries (~`base.html:88-90`). Without it the feature ships
invisible to the PA. The e2e flow must reach the create screen via this link.

| View | Route | Gate | Behavior |
|---|---|---|---|
| List | `/manage/subjects/` | `change_subject` | All subjects ordered by `title_en`; each row shows `title_en`, `title_pl` (or a muted "—" when blank), and a **"used by N courses"** count (`Count("courses", distinct=True)` — `distinct=True` guards against over-counting if another joined annotation is ever added). Create button + per-row edit/delete actions. |
| Create | `/manage/subjects/new/` | `add_subject` | `SubjectForm`; on success redirect to list. |
| Edit | `/manage/subjects/<slug>/edit/` | `change_subject` | `SubjectForm` bound to the instance; on success redirect to the list (the slug may have changed, so redirect to the list rather than back to a now-stale edit URL). |
| Delete | `/manage/subjects/<slug>/delete/` | `delete_subject` | Confirmation page stating the usage count ("This subject is used by N courses; deleting it removes it from those courses"). M2M deletion just unlinks — **no orphaned course data**. POST performs the delete. |

### `SubjectForm` (`courses/forms.py`)

- `ModelForm` over `title_en`, `title_pl`, `slug`.
- `title_en` required; `title_pl` optional.
- `slug` field is declared `required=False` (mirroring `CourseForm`) so a blank
  submission reaches `clean`/`save` instead of failing field validation first.
  The field remains editable when supplied.
- **Blank-slug behavior differs by create vs edit:**
  - **Create** (no `instance.pk`): derive the slug from `title_en`.
  - **Edit** (existing `instance.pk`): a blank slug **retains the instance's
    current slug** — do NOT re-derive, which would silently change the subject's
    `/<slug>/` URL and break existing links. Only derive on edit if the instance
    somehow has no slug.
- **Uniqueness-aware derivation:** a bare `slugify(title_en)` can collide with an
  existing slug (e.g. two "Mathematics" subjects), which would bypass the form's
  field-level uniqueness check and surface as a DB `IntegrityError`. The derived
  slug MUST be made unique before save — append a numeric suffix (`-2`, `-3`, …)
  until free — OR the derived value MUST be run back through the form's slug
  uniqueness validation so a collision surfaces as a clean field error rather
  than a 500. The free-slug check / re-validation MUST **exclude the current
  instance** (`.exclude(pk=self.instance.pk)` when editing) so a subject never
  collides with its own row. An explicitly-supplied duplicate slug surfaces as a
  normal field-level uniqueness error.
- Labels are `{% trans %}`-wrapped; help text clarifies that `title_pl` is
  optional and falls back to English.

## Catalog & course-form integration

### `CourseForm` (`courses/forms.py`)

- The Meta `fields`, `labels`, and `widgets` entries all move from `subject` to
  `subjects` (the existing `labels = {... "subject": _("Subject") ...}` key must
  be renamed, not just the field, or it becomes a dead entry and the new field
  renders with an auto-derived label).
- Rendered as a **checkbox multi-select** (`CheckboxSelectMultiple`),
  consistent with the Phase-3a roster pickers that moved off multi-selects. The
  choices render in a stable order via `Subject.Meta.ordering = ["title_en"]`
  (above).
- Label `{% trans "Subjects" %}`.

### Catalog (`courses/views.py`)

- The subject sidebar/filter query already collects subjects via
  `courses__in=eligible` — unchanged in shape; update `order_by("title")` →
  `order_by("title_en")`.
- The filter application changes from `qs.filter(subject_id=sel_subject)` to the
  M2M equivalent (`qs.filter(subjects__id=sel_subject)` with `.distinct()` to
  avoid row duplication when a course matches via multiple joins).
- A course now appears under **each** of its subjects in the filter — an
  intentional browsing improvement.

### Templates

- **Catalog cards**: the single-subject eyebrow generalizes to a **chip row**
  rendering `course.subjects.all` (each `subject.title`). When a course has no
  subjects, render nothing (no empty chip).
- **Manage course list**: show each course's subjects as chips (or a muted "—"
  when none).
- All subject display uses `subject.title` (the property), so PL users see PL
  titles automatically.

## Affected call-sites (mandatory edits)

Turning `Subject.title` into a property and replacing the `Course.subject` FK
with an M2M breaks existing references. Each of these MUST be updated **in the
same change** or the app fails system checks / queries at startup — they are not
optional polish. (Grep for `\.subject\b`, `subject_id`, `Subject.*title`,
`select_related.*subject`, **`subject=`** (the bare kwarg, no leading dot — used
in course factories/tests; scope this one to `courses/` + `tests/` and read each
hit in context, since `subject=` also matches unrelated email code like
`tests/test_invitations.py`'s `INVITE_SUBJECT` / `message.subject` — those are
NOT call-sites to change), and **`SubjectFactory(`** to confirm none are missed.)

- **`courses/admin.py` — `SubjectAdmin`** *(blocker: admin system checks fail
  app-wide, breaking `migrate`/`test`/`runserver`)*: `prepopulated_fields =
  {"slug": ("title",)}` references a non-field once `title` is a property
  (`admin.E030`); `search_fields = ("title",)` / `list_display` reference the
  property. Switch to `title_en` (and `title_pl` where useful); drop or repoint
  `prepopulated_fields` to `title_en`.
- **`courses/admin.py` — `CourseAdmin`** *(blocker)*: `autocomplete_fields =
  ("subject", "owner")` references the removed FK. Change to `subjects`
  (`autocomplete_fields` works for M2M, or use `filter_horizontal`).
- **`courses/management/commands/seed_demo_course.py`** *(blocker: command
  crashes)*: `Subject.objects.get_or_create(..., defaults={"title": ...})` must
  set `title_en`; the course create passing `defaults={"subject": subject}` must
  drop `subject` from defaults and instead `course.subjects.add(subject)` after
  the course exists (an M2M cannot be set via create `defaults`).
- **`courses/views_manage.py` (`course_management_list`, ~line 37)** *(blocker:
  `FieldError` at query time)*: `select_related("subject", "owner")` cannot span
  the M2M. Change to `select_related("owner").prefetch_related("subjects", …)`
  (keep the existing `self_enrol` prefetch).
- **`courses/views_manage.py` (`course_create`, ~lines 45-53)** *(blocker:
  selected subjects silently lost on create)*: the view does
  `course = form.save(commit=False)` then `course.save()` with **no
  `form.save_m2m()`**. With `subject` as an FK, `commit=False` still set the FK
  attribute; with `subjects` as an M2M, `commit=False` skips it, so any ticked
  subjects are silently discarded. Add `form.save_m2m()` after `course.save()`.
  Note the create-vs-edit **asymmetry**: `course_edit` uses `form.save()`
  (commit=True, which calls `save_m2m`) and already works — the fix belongs in
  `course_create` only. (The pre-existing `self_enroll_cohorts` M2M on this form
  has the same latent gap; fixing it here is in-scope since it's the same line.)
- **`templates/courses/_catalog_detail.html` (line ~3)**: renders
  `{{ course.subject.title }}` — convert to the `course.subjects.all` chip row
  (same treatment as the catalog cards), guarding the empty case.
- **`templates/courses/catalog.html` (cards)** and
  **`templates/courses/manage/course_list.html` (lines ~21-22, renders
  `course.subject.title`)**: convert the single-subject eyebrow to the chip row
  over `course.subjects.all` (already covered under Catalog & course-form
  integration; restated here for the call-site checklist).
- **`tests/factories.py` and existing tests** *(blocker: breaks suite
  collection — DoD requires the full suite green)*: `SubjectFactory` declares
  `title` (removed) → change to `title_en`. Callers pass `subject=` to
  course-creating helpers (e.g. `tests/test_e2e_catalog.py`,
  `tests/test_catalog_views.py`'s `_open_course_with_unit(subject=…)`); the
  course factory/helpers must accept and attach via the `subjects` M2M (a
  post-generation hook), and every `subject=`/`SubjectFactory(title=…)` site in
  `tests/` must be swept and updated.
- **`courses/forms.py` (`CourseForm` Meta)**: `fields`/`labels`/`widgets` move
  from `subject` to `subjects` (see CourseForm section above).
- **Catalog view subject filter & ordering** (`courses/views.py`): change
  `order_by("title")` → `order_by("title_en")` **only on the Subject sidebar
  query (~line 705)**. Do NOT touch the `order_by("title")` calls on **Course**
  querysets (e.g. `views.py:177`, `:724`, `views_manage.py:32`,`:34`) —
  `title_en` exists only on `Subject`, so rewriting a Course `order_by` raises
  `FieldError`. Separately, `filter(subject_id=…)` → `filter(subjects__id=…)`
  with `.distinct()` (see Catalog section above).

## Internationalization

- All new UI strings (`{% trans %}` / `gettext`) get PL translations; `.po`
  updated and `.mo` compiled. Watch the known `makemessages` fuzzy-flag gotcha
  (clear stale `#, fuzzy` flags; verify new msgids).
- Subject **data** (the titles themselves) is now genuinely bilingual via the
  two fields — this is the localization the slice delivers.

## Testing

Follow the project's TDD + real-PostgreSQL + factory_boy conventions.

- **Model**: `title` property resolves EN under EN locale, PL under PL locale,
  EN fallback when `title_pl` blank or locale unknown; `__str__`.
- **Migrations**: a data-migration test using the migration executor to pin the
  historical state — e.g. `django-test-migrations` (`MigratorTestCase`: migrate
  to the pre-change state, create a `Subject` with a `title` and a `Course` with
  a `subject` FK via the historical models, migrate forward, assert `title` →
  `title_en` and the FK value landed in `Course.subjects`). If
  `django-test-migrations` is not already a dependency and adding it is
  undesirable, the fallback is a `MigrationExecutor`-driven test in the same
  shape; either way the test must drive the real migrations, not re-implement
  the copy in Python.
- **Permissions**: PA can reach all `/manage/subjects/` views; a Course Admin and
  a Student get 403 on create/edit/delete; CA can still assign subjects via the
  course form.
- **Management views**: create/edit/delete happy paths; the list usage count;
  delete-unlinks-without-orphaning (a course keeps existing, just loses the
  subject).
- **Catalog**: a multi-subject course appears under each subject's filter; the
  filter returns it without duplicate rows; cards render the chip row. Add
  explicit chip-render assertions on **`_catalog_detail.html`** (the
  detail/modal fragment) and the **manage course list**, because a missed
  template conversion fails **silently** — `{% if course.subject %}` resolves to
  empty (Django swallows the failed attribute lookup) rather than erroring, so
  there is no crash or system-check to catch it; only a render assertion will.
- **Course form**: multi-select round-trips multiple subjects. This must be a
  **view-level** test (POST to `course_create` with subjects selected, then
  assert `course.subjects` is non-empty after the redirect, plus the analogous
  `course_edit` POST) — a form-only `form.save()` round-trip passes even when the
  create *view* drops subjects (the C1 `save_m2m` gap), giving false confidence
  on the exact broken path.
- **e2e** (per project norm): a PA creates a subject through the real UI and
  assigns it to a course; the catalog filter shows it. Drive the real click
  path (no `page.evaluate` shortcuts).

## Rollout / DoD

- Full suite green (incl. migration + permission + catalog tests); e2e green.
- `uv run ruff check` and `uv run ruff format --check` clean.
- `migrate` + `setup_roles` clean; PA role holds the three subject perms.
- `.po`/`.mo` updated with PL strings; no stray fuzzy flags.
- UI verified light + dark via throwaway Playwright screenshots (delete-after-
  review), per the project's "verify UI with screenshots" norm.
- `docs/roadmap.md` updated: tick the subject-localization deferred row and note
  that the bespoke subject UI + multi-subject courses landed; leave taxonomy
  structure (5b) and merge as the recorded follow-ups.

## Open follow-ups (recorded, not in this slice)

- **5b — taxonomy structure**: hierarchy and/or a second axis (level/grade,
  tags) for richer catalog browsing.
- **Merge subjects**: PA tool to fold one subject into another, reassigning
  courses.
- **Platform-wide content translation**: if bilingual *course* content (titles,
  overviews, elements) is ever needed, revisit the cross-cutting strategy
  (per-language fields vs django-modeltranslation/parler) as its own brainstorm.
