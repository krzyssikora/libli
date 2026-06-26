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

Three logical steps (may be combined where Django allows, but order matters):

1. **Add per-language title fields.** Add `title_en` (default `""` for the
   migration, then drop default) and `title_pl`. Data-migrate: copy the old
   `title` value into `title_en` for every existing row. Then remove the old
   `title` field.
2. **Add `Course.subjects` M2M.** Create the M2M.
3. **Backfill M2M + drop old FK.** Data-migrate: for each course with a
   non-null `subject`, add that subject to `course.subjects`. Then remove the
   old `Course.subject` FK.

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

## Management UI (`/manage/subjects/`)

New views in `courses/views_manage.py`, new URL routes under the existing
`/manage/` namespace, new templates following the existing manage-area styling
(the styled `.card-list` / `.row-actions` ledger pattern, light + dark).

| View | Route | Gate | Behavior |
|---|---|---|---|
| List | `/manage/subjects/` | `change_subject` (view-ish; list is the hub) | All subjects ordered by `title_en`; each row shows `title_en`, `title_pl` (or a muted "—" when blank), and a **"used by N courses"** count (`Count("courses")`). Create button + per-row edit/delete actions. |
| Create | `/manage/subjects/new/` | `add_subject` | `SubjectForm`; on success redirect to list. |
| Edit | `/manage/subjects/<slug>/edit/` | `change_subject` | `SubjectForm` bound to the instance. |
| Delete | `/manage/subjects/<slug>/delete/` | `delete_subject` | Confirmation page stating the usage count ("This subject is used by N courses; deleting it removes it from those courses"). M2M deletion just unlinks — **no orphaned course data**. POST performs the delete. |

### `SubjectForm` (`courses/forms.py`)

- `ModelForm` over `title_en`, `title_pl`, `slug`.
- `title_en` required; `title_pl` optional; `slug` required and unique
  (model-level uniqueness surfaces as a form error).
- Slug derived from `title_en` when left blank (mirror the Django-admin
  `prepopulated_fields` convenience; can be a simple `slugify(title_en)` in
  `clean`/`save` when slug is empty), but remains editable.
- Labels are `{% trans %}`-wrapped; help text clarifies that `title_pl` is
  optional and falls back to English.

## Catalog & course-form integration

### `CourseForm` (`courses/forms.py`)

- Field `subject` → `subjects`.
- Rendered as a **checkbox multi-select** (`CheckboxSelectMultiple`),
  consistent with the Phase-3a roster pickers that moved off multi-selects.
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
- **Migrations**: a data-migration test (or fixture-based) asserting an existing
  `title` lands in `title_en` and an existing `Course.subject` lands in
  `Course.subjects`.
- **Permissions**: PA can reach all `/manage/subjects/` views; a Course Admin and
  a Student get 403 on create/edit/delete; CA can still assign subjects via the
  course form.
- **Management views**: create/edit/delete happy paths; the list usage count;
  delete-unlinks-without-orphaning (a course keeps existing, just loses the
  subject).
- **Catalog**: a multi-subject course appears under each subject's filter; the
  filter returns it without duplicate rows; cards render the chip row.
- **Course form**: multi-select round-trips multiple subjects.
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
