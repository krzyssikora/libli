# Design: In-app role manuals (`/help/`) — Documentation slice 2

**Date:** 2026-07-07
**Status:** Approved (brainstorming); ready for implementation planning
**Initiative:** Documentation slice 2 of 4 (after slice 1 — SIS webhook guide, PR #70 merged). Remaining: (3) developer onboarding, (4) docstring / `.env` gaps.

## Summary

Build an in-app help system that serves role-specific user manuals rendered from
repo-authored markdown files. It generalizes slice-1's single-guide seed
(`integrations/docs.py::render_markdown_doc` + the `webhook_guide` view/template)
into a multi-topic, role-grouped, permission-gated, bilingual help section rooted
at `/help/`.

Audience: the three staff roles — **Platform Admin, Course Admin, Teacher**.
Students are intentionally excluded: the learner experience must be intuitive on
its own, and hidden manuals would signal otherwise.

Content target is **comprehensive** (one topic per feature area across all shipped
phases), with the explicit fallback that if content runs long in a session we ship
the fully-built system plus whatever topics are written, and the remainder become
follow-up writing passes. The machinery is the durable deliverable; every topic is
an independent file, so partial content never leaves anything half-built.

## Goals

- A `/help/` index that lists the manuals the current user is allowed to see,
  grouped by role.
- Per-topic pages rendered from trusted repo markdown, styled like the slice-1
  guide, with a back-to-index breadcrumb and a sibling-topic sidebar.
- Permission gating consistent with the rest of the app: you see help only for
  things your role can do.
- Bilingual (EN/PL) via the existing `<name>.md` / `<name>.pl.md` convention.
- A single "Help" nav entry for staff users.

## Non-goals (this slice)

- Contextual per-page "?" / "Learn more" deep-links from feature pages (deferred;
  a possible later slice).
- Student-facing help.
- Editing help content through the UI (content is repo markdown, trusted, not user
  input — no sanitization needed, fixed paths only).
- Full-text search across manuals.

## Architecture

The help system lives in the existing **`core`** app — the natural cross-cutting
home (it already owns `user_settings`, language/theme, context processors).
`core.urls` is already mounted at the project root, so `/help/...` needs no new
`include`.

### Components

**`core/help.py`** — registry + shared renderer.
- `render_markdown_doc(rel_path)` **moves here from `integrations/docs.py`**;
  `integrations` imports it from `core`. It is the single renderer:
  `markdown.markdown(text, extensions=["fenced_code", "tables"])`, fail-loud on a
  missing file (a missing trusted asset is a deploy/packaging bug), no sanitization
  (fixed trusted paths only, never a user-supplied path).
- `localized_doc_path(base, lang)` — generalizes slice-1's `_GUIDE_BY_LANG`. Given
  a base relative path (e.g. `help/teacher/analytics.md`) and a language, returns
  the localized path (`help/teacher/analytics.pl.md` for `pl`), falling back to the
  English base for any language without a translation. English is canonical.
- `Topic` dataclass and the `TOPICS` registry (see below).
- `topics_for(user)` → an ordered mapping `{role_label: [Topic, ...]}` containing
  only topics where `user.has_perm(topic.perm)`, preserving registry order. Empty
  roles are omitted.

**`core/views_help.py`** — two views (kept in their own module to keep
`core/views.py` focused):
- `help_index(request)` — `@login_required`. Renders `topics_for(request.user)`.
  A user with no marker perms (e.g. a Student) sees a short empty state
  ("No manuals are available for your account.").
- `help_topic(request, slug)` — `@login_required`. Looks up `slug` in the registry;
  raises `Http404` if the slug is unknown **or** `not request.user.has_perm(
  topic.perm)` (404, not 403 — do not reveal a topic's existence to users who
  cannot access it). Renders the localized markdown into the shared doc template
  with breadcrumb + sibling sidebar.

**URLs** (added to `core/urls.py`):
- `path("help/", views_help.help_index, name="help_index")`
- `path("help/<slug:slug>/", views_help.help_topic, name="help_topic")`

Slugs are **flat and globally unique** (`builder`, `analytics`, `users-roles`, …).
Role is registry metadata used for grouping and the sidebar, **not** part of the
URL — this avoids URL/registry drift. On disk, files are organized by role folder
for authoring clarity: `docs/help/<role>/<slug>.md` and `.pl.md`.

**Templates:**
- `templates/help/index.html` — role-grouped list of `{title}` links; empty state.
- `templates/help/doc.html` — generalizes `webhook_guide.html`. Reuses the
  `.doc-page` styling (headings, `pre`, tables). Adds a breadcrumb
  ("Help / {title}") and a sidebar listing the sibling topics of the current
  topic's role (registry data — cheap). `{{ content|safe }}` for the rendered
  markdown.

**Nav** (`templates/base.html`): a top-level **"Help"** link, shown when the user
has at least one visible topic. Recommended gate: reuse the same marker perms —
show when the user holds any of `courses.change_course`, `grouping.view_collection`,
or `institution.change_institution` (covers all three staff roles; excludes plain
students). Top-level placement (not the Admin dropdown) because help spans all
staff roles, not just PA tooling.

### The registry

```python
@dataclass(frozen=True)
class Topic:
    slug: str          # globally unique, URL segment (e.g. "builder")
    role: str          # role label key, for grouping/sidebar (COURSE_ADMIN, ...)
    perm: str          # marker permission gating visibility
    title: object      # gettext_lazy display title
    path: str          # base markdown rel path, e.g. "help/course-admin/builder.md"

TOPICS: list[Topic] = [ ... ]   # ordered
```

`title` uses `gettext_lazy` (module-import-time dict — eager `gettext` would freeze
labels to the import-time language; the same lesson as `institution/roles.py`
`ROLE_LABELS`).

### Gating model

Topics are gated by a **representative marker permission** per role — the coarse
"which role should see this manual," not the feature's per-object gate. This is
deliberate: some features (e.g. analytics, quiz review) are `@login_required` and
gate by teaching relationship, not a global perm, so there is no per-object perm to
mirror for help visibility.

| Role | Marker perm | Held by |
| --- | --- | --- |
| Course Admin | `courses.change_course` | CA, PA |
| Teacher | `grouping.view_collection` | Teacher, CA, PA |
| Platform Admin | `institution.change_institution` (and per-topic: `accounts.view_user`, `courses.change_subject`, `grouping.change_cohort`) | PA |

Platform Admin holds the superset of permissions, so a PA sees every topic. A
Teacher sees only Teacher topics. A Course Admin sees CA topics (and, since CAs
hold `grouping.view_collection`, Teacher topics too — acceptable: CAs do view group
progress). Students hold none of the markers and see an empty index.

## Content inventory (comprehensive target)

Each topic = one `.md` + one `.pl.md` under `docs/help/<role>/`. Written in per-role
batches so the slice can checkpoint.

**Course Admin** (`docs/help/course-admin/`):
- `create-a-course` — creating a course, subjects, ownership
- `builder` — the course builder, structure/depth presets (Flat/Chapters/Parts/Full)
- `content-editors` — lesson block types and the content editor
- `quiz-editors` — quiz question types and the quiz editor
- `notes-tags` — personal notes and tags on units
- `export-import` — course export/import (zip transfer, tolerant export)
- `media-manager` — the media manager and picker

**Teacher** (`docs/help/teacher/`):
- `analytics` — the analytics matrix and colour bands
- `drill-down` — recursive drill-down and per-student cherry-pick subsets
- `quiz-review` — the quiz review queue and force-submit
- `groups-collections` — groups, cohorts, collections
- `roster` — roster management (cohort/name filters, adding students)
- `gradebook-export` — CSV/XLSX/print of course results

**Platform Admin** (`docs/help/platform-admin/`):
- `users-roles` — the People page, users and roles
- `invitations` — inviting users, domain allowlist
- `branding-settings` — branding and platform settings (access, uploads)
- `sso` — SSO (OIDC) configuration
- `subjects` — subject taxonomy management
- `cohorts` — cohort management
- `integrations` — grade-sync / SIS webhook overview; **links out** to the existing
  `/integrations/webhook/` receiver guide rather than duplicating it
- `first-run-wizard` — the setup wizard
- `notifications` — notification kinds, email delivery, retention

## Data flow

1. Request `/help/` → `help_index` → `topics_for(user)` filters `TOPICS` by
   `has_perm` and groups by role → template renders grouped links.
2. Request `/help/<slug>/` → `help_topic` → registry lookup → perm check (404 on
   miss) → `localized_doc_path(topic.path, get_language())` →
   `render_markdown_doc(path)` → HTML into `help/doc.html` with breadcrumb +
   sibling sidebar (siblings = other visible topics of the same role).

## Error handling

- Unknown slug or perm-denied topic → `Http404` (uniform; never reveals existence).
- Missing markdown file for a registered topic → fail-loud (`FileNotFoundError`
  from `read_text`), surfacing a packaging/deploy bug rather than a silent blank
  page. The content-integrity test (below) prevents this from ever reaching prod.
- `localized_doc_path` falls back to the English base when a `.pl.md` is absent, so
  a not-yet-translated topic still renders (in English) rather than 500ing.

## i18n

- Registry `title`s and all template chrome (nav "Help", breadcrumb, empty state,
  index/sidebar headings) use `gettext_lazy` / `{% trans %}` and go through
  `makemessages` → PL catalog. Watch the known fuzzy-match gotcha (new short strings
  fuzzy-matched to unrelated old ones) — clear fuzzy flags and translate properly.
- Markdown **content** is not gettext'd; it lives in the `.pl.md` sibling files
  (same as slice 1). Code/JSON/identifiers stay verbatim across languages.
- Language resolution follows the existing `SessionLocaleMiddleware` /
  `translation.get_language()`, clamped to `Institution.enabled_languages`.

## Testing

- **Renderer:** `render_markdown_doc` renders fenced code + tables; fail-loud on a
  missing path. (Move/adapt the existing `integrations` renderer test to `core`;
  keep integrations importing from core.)
- **Gating / index:** `help_index` shows exactly the expected topics for each role
  (PA: all; Teacher: teacher only; CA: CA + teacher; Student: empty state).
- **Topic access:** `help_topic` returns 200 for a permitted topic; `Http404` for
  an unknown slug and for a real slug the user lacks the marker perm for.
- **Bilingual:** a topic renders its PL file under `HTTP_ACCEPT_LANGUAGE: pl` and
  the EN file otherwise; a topic missing its `.pl.md` falls back to EN (no 500).
- **Nav:** the "Help" link is present for each staff role and absent for a Student
  on a representative page.
- **Content integrity (parametrized over `TOPICS`):** every registered topic has
  **both** an EN and a PL file that exist and render without error. This enforces
  the missing-file contract and guarantees scaffolded topics exist as files even if
  their prose is short.

## Definition of Done (gate)

Per the slice-1 CI lesson, the DoD runs **both**:
- `uv run ruff check .` **and** `uv run ruff format --check .`
- the full `uv run pytest` suite
- i18n catalog tests (translatable strings are added/removed this slice) +
  `makemessages` with fuzzy flags resolved
- visual QA of the index and a sample topic page, light + dark.

## Files touched

New:
- `core/help.py` (registry + moved renderer + helpers)
- `core/views_help.py`
- `templates/help/index.html`, `templates/help/doc.html`
- `docs/help/<role>/<slug>.md` + `.pl.md` per topic
- `core/tests/test_help.py` (or equivalent)

Modified:
- `core/urls.py` (two routes)
- `integrations/docs.py` → re-export/import `render_markdown_doc` from `core.help`
  (and update `integrations/views.py` / tests accordingly)
- `templates/base.html` (Help nav link)
- PL locale catalog

## Open decisions (resolved)

- **Audience:** PA, CA, Teacher; not Student. ✔
- **Structure:** topic pages grouped by role under a `/help/` index. ✔
- **Discovery:** single "Help" nav entry → index; contextual per-page links
  deferred. ✔
- **Content depth:** comprehensive, with scaffold-remainder fallback. ✔
- **Gating:** permission-gated (marker perm per role/topic; 404 on deny). ✔
- **URL shape:** flat `/help/<slug>/`, files organized by role folder. ✔
- **Nav placement:** top-level "Help" for staff (not the Admin dropdown). ✔
