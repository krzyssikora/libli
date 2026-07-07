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

`core/urls.py` sets `app_name = "core"`, so all reversing uses the `core:` namespace:
`core:help_index` and `core:help_topic` (templates, breadcrumb, nav, tests).

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

**Nav** (`templates/base.html`): a top-level **"Help"** link. To keep the nav flag
and the index in perfect sync (and avoid a hand-maintained perm-OR list drifting
from the registry), a `core` **context processor** exposes
`help_available = bool(topics_for(user))`; the nav shows the link iff that is true.
This is the single source of truth — a staff user who holds a marker perm but has
zero registered topics for their role (transient, during scaffolding) correctly
sees no link and no empty page mismatch. Top-level placement (not the Admin
dropdown) because help spans all staff roles, not just PA tooling.

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

`Topic.role` stores the **storage constant** from `institution/roles.py`
(`COURSE_ADMIN`, `TEACHER`, `PLATFORM_ADMIN`) — the stable key for grouping and
registry ordering. Templates render the human label via `ROLE_LABELS[role]` (the
lazy-translated proxy), never the raw constant; so `topics_for` keys its mapping off
the constant and display goes through the label.

**Slug uniqueness invariant:** slugs are globally unique across role folders.
`core/help.py` asserts this at import time (`assert len({t.slug for t in TOPICS}) ==
len(TOPICS)`) and a test re-asserts it, so a duplicate slug fails loudly rather than
silently shadowing a topic in the `{slug: Topic}` lookup.

**Registry ↔ file existence:** a `Topic` is added to `TOPICS` only once its English
`.md` file exists. Unwritten (scaffold-remainder) topics are simply absent from the
registry, so the comprehensive-vs-scaffold fallback ships whatever is registered
with no half-built entries. The English file is mandatory; the `.pl.md` sibling is
optional and its absence degrades gracefully to English (see Error handling).

### Gating model

Topics are gated by a **representative marker permission** per role — the coarse
"which role should see this manual," not the feature's per-object gate. This is
deliberate: authoring a course is gated by course **ownership** (the global
`courses.change_course` perm is Platform-Admin-only — see `courses/access.py`), and
some features (analytics, quiz review) are `@login_required` and gate by teaching
relationship. Neither exposes a per-object perm to mirror for help visibility, so
each topic declares a role-marker perm its audience provably holds.

Marker perms, verified against `institution/roles.py`:

| Role | Marker perm | Held by (per roles.py) |
| --- | --- | --- |
| Course Admin | `grouping.change_group` | CA, PA — in `GROUPING_COURSE_ADMIN_PERMS` + `GROUPING_PLATFORM_ADMIN_PERMS`; NOT in `GROUPING_TEACHER_PERMS` |
| Teacher | `grouping.view_collection` | Teacher, CA, PA — in all three grouping perm sets; not Student |
| Platform Admin | per-topic (table below) | PA only |

`courses.change_course` must **not** be used as a marker: it is assigned only to the
Platform Admin group, so a Course Admin does not hold it and would see zero CA
topics.

Platform Admin holds the superset of permissions, so a PA sees every topic. A
Teacher sees only Teacher topics. A Course Admin sees CA topics **and** Teacher
topics (CAs hold `grouping.view_collection` — acceptable: CAs do view group
progress). Students hold none of the markers and see an empty index.

**Explicit per-topic `perm` (the value of every `Topic.perm`):**

| Topic slug(s) | Role | `perm` |
| --- | --- | --- |
| create-a-course, builder, content-editors, quiz-editors, notes-tags, export-import, media-manager | Course Admin | `grouping.change_group` |
| analytics, drill-down, quiz-review, groups-collections, roster, gradebook-export | Teacher | `grouping.view_collection` |
| users-roles, invitations | Platform Admin | `accounts.view_user` |
| branding-settings, sso, first-run-wizard, notifications, integrations | Platform Admin | `institution.change_institution` |
| subjects | Platform Admin | `courses.change_subject` |
| cohorts | Platform Admin | `grouping.change_cohort` |

Every PA perm above is in `PLATFORM_ADMIN_PERMS` / `GROUPING_PLATFORM_ADMIN_PERMS`,
so a PA sees all PA topics.

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
- **Bilingual:** because the help views are `@login_required`, locale is driven by
  the user's stored preference, **not** `Accept-Language` — on login,
  `core/signals.py::seed_language_on_login` seeds the session language from
  `user.language`, and `SessionLocaleMiddleware` then ignores `Accept-Language`. So
  the PL test creates/logs-in a user with `language="pl"` (or sets the session
  `_language` key directly) and asserts the `.pl.md` renders; the EN default renders
  otherwise.
- **PL fallback:** a registered topic whose `.pl.md` is absent renders its English
  content (no 500) under a PL session. Exercise this with a topic that legitimately
  ships EN-only, or a synthetic registry entry in the test.
- **Nav:** the "Help" link is present for each staff role and absent for a Student
  on a representative page.
- **Content integrity (parametrized over `TOPICS`):** every registered topic has an
  **English** `.md` file that exists and renders without error (mandatory — enforces
  the missing-file contract). PL is optional; where a `.pl.md` exists it must also
  render. This keeps the comprehensive-vs-scaffold model valid: only EN-complete
  topics are registered, so the suite never fails on not-yet-translated prose.
- **Slug uniqueness:** assert `len({t.slug for t in TOPICS}) == len(TOPICS)`.
- **Role helpers:** the gating tests need PA/CA/Teacher/Student users, but
  `tests/factories.py` currently ships only `make_pa`. The slice adds analogous
  `make_ca` / `make_teacher` (and a plain-student) helpers that add the role `Group`
  and clear the perm caches (`_perm_cache`, `_user_perm_cache`,
  `_group_perm_cache`), mirroring `make_pa`.

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
- `core/context_processors.py` (`help_available = bool(topics_for(user))`; add the
  callable to the `TEMPLATES` context-processor list if it exposes multiple)
- `integrations/docs.py` → re-export/import `render_markdown_doc` from `core.help`
  (and update `integrations/views.py` / tests accordingly)
- `templates/base.html` (Help nav link)
- `tests/factories.py` (add `make_ca`, `make_teacher`, and a plain-student helper)
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
