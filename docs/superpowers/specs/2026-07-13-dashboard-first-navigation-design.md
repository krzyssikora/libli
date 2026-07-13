# Dashboard-first navigation

## Purpose

The top navigation has grown organically and now carries too many items whose
purpose is unclear to non-student users. It currently offers, for an authenticated
user: **Courses**, **Tags & notes**, **Browse** (students only), **Manage**,
**Groups**, **My groups**, **Help**, and an **Admin** dropdown. Several of these
overlap or are redundant:

- **Courses** (`courses:my_courses`) lists *only enrolled* courses — but the
  post-login dashboard (`core/home.html`) already lists every enrolled course in
  its *My learning* panel, so the nav item is redundant.
- **Manage** is gated by `courses.change_course` and is really the course
  authoring/administration ledger; its name is too generic.
- **Groups** and **My groups** are two separate items that differ only by the
  audience/entitlement they serve.
- A students-only **Browse** link duplicates a "Browse courses" button that already
  lives on the dashboard.

This feature makes the **existing post-login dashboard the primary course hub**
(reached via the logo, as today) and restructures the nav around it. It also
finishes the dashboard's **Teaching** panel, which is currently a stub, and in
doing so fixes issue #91: a teacher assigned to a course via `Group.teachers` today
has **no access path at all** to that course, because `accessible_courses` grants
only staff/owner/enrolled access.

Scope is deliberately bounded to the nav restructure, the dashboard panel work, the
one access-control fix, and the Groups merge. Two ideas are explicitly deferred (see
*Deferred*).

## Architecture / components

The change touches four seams, each independently understandable and testable.

### 1. Navigation (`templates/base.html`)

Transform the authenticated primary nav:

| Today | After |
|---|---|
| Courses · Tags & notes · Browse\* · Manage · Groups · My groups · Help · Admin | Tags & notes · **Studio** · **Groups** · Help · Admin |

- **Drop the "Courses" link** (`courses:my_courses`). The dashboard's *My learning*
  panel already lists every enrolled course. The `courses:my_courses` **route is
  kept** (harmless; a potential future "see all" target) — only the nav link is
  removed.
- **Rename "Manage" → "Studio"**. Gating is unchanged (`perms.courses.change_course`).
  "Studio" reads well in both English and Polish and sidesteps the untranslatable
  "Authoring".
- **Merge "Groups" + "My groups" → a single "Groups"** link pointing at a tabbed
  page (component 4). Both underlying routes are kept.
- **Drop the students-only "Browse" nav link** (`courses:catalog`). The dashboard
  already surfaces a "Browse courses" button for the same audience; one entry point
  is enough. The `courses:catalog` route and the dashboard button are unchanged.
- **Unchanged:** Tags & notes, Help, the Admin dropdown, the notification bell, and
  the account/avatar menu.

### 2. Dashboard panels (`core/home.html`, `core/views.py`)

The dashboard scaffold already exists with five conditional panels. Changes:

- **My learning** — unchanged (lists enrolled courses; empty state kept).
- **Teaching** — *finish the stub*. Today it renders only the text "No classes
  assigned yet." Change it to list the courses the user teaches and, per course,
  link to the course outline and to that course's Analytics view. When the user
  teaches nothing, keep the existing empty state. The taught-courses queryset is
  supplied by the view (component 3).
- **Studio** (currently titled "Authoring") — rename the panel title to **Studio**
  for consistency with the nav. The panel lists the user's owned/editable courses
  inline plus a "New course" affordance, linking into the Studio ledger
  (`courses:manage_course_list`).
- **Administration** — unchanged.
- **Generic empty-state** panel — unchanged.

`core/views.py::home` gains a `taught_courses` queryset in its context (see *Data
flow*). It keeps its existing first-run setup-wizard redirect and the
`enrolled_courses` / `can_manage_courses` context untouched.

### 3. Access control — closes #91 (`courses/access.py`)

`accessible_courses(user)` today returns, for a non-staff user, only
`Q(pk__in=enrolled) | Q(owner=user)`. A group-assigned teacher matches neither, so
`can_access_course` (which delegates to `accessible_courses`) denies them their own
taught courses.

Extend the queryset to also include taught courses via the
`Group.teachers` → `Group.course` path:

```python
return Course.objects.filter(
    Q(pk__in=enrolled) | Q(owner=user) | Q(groups__teachers=user)
).distinct()
```

`.distinct()` is already present and remains necessary (the join can multiply rows).
Because `can_access_course` and every consumer route (`course_outline`,
`lesson_unit`, `quiz_unit`, `course_results`, …) delegate to `accessible_courses`
as the single source of truth, this one change grants teachers read access to the
courses they teach — and **only** those. Staff/superuser (all courses) and
owner/enrolled paths are unchanged.

This is the one security-adjacent change and receives explicit positive and negative
tests (a teacher can open a course they teach; a teacher cannot open a course they
do not teach and are not otherwise related to).

### 4. Groups merge (`grouping`)

Replace the two nav entries with a single tabbed page that reuses the existing
**Tags & notes** tabbed-page pattern:

- **Tab 1 — My Groups** (default): the content of the current `grouping:my_groups`
  view (the user's own group memberships / collections). Entitlement:
  `grouping.view_collection` OR `grouping.view_group`.
- **Tab 2 — Manage**: the content of the current `grouping:group_list` view (group
  administration). Entitlement: `grouping.view_group`.

A user entitled to only one tab sees only that tab (no empty second tab, no tab
strip if there is only one). Both existing routes/views are kept; the tabbed shell
composes them. The nav "Groups" link points at the default (My Groups) entry, which
renders the tab strip when the user is entitled to more than one tab.

### Deferred (explicitly out of scope for this feature)

- **Drag-to-reorder dashboard panels** with per-user persisted order (from the
  reference mockup). Fixed sensible panel order ships first; reordering is a clean
  additive follow-up.
- **Teacher "Browse other courses" block** (the "all school courses" idea). The
  cheap version — widen the `courses:catalog` gate to teachers, read-only,
  catalog-eligible courses only — is a small fast-follow, not part of this slice.

## Data flow

1. A user hits `/` → `core.views.home`. After the existing first-run wizard gate, the
   view builds context:
   - `enrolled_courses = Course.objects.filter(enrollments__student=user).order_by("title")` (existing).
   - `taught_courses = Course.objects.filter(groups__teachers=user).distinct().order_by("title")` (new).
   - `can_manage_courses` (existing).
   - Role flags (`is_student`, `is_teacher`, `is_course_admin`, `is_platform_admin`)
     are injected by the existing `core.context_processors.user_roles` context
     processor and continue to drive which panels render.
2. `core/home.html` renders panels conditionally:
   - *My learning* when `is_student or enrolled_courses`.
   - *Teaching* when `is_teacher` — now iterating `taught_courses`, each row linking
     to `courses:course_outline` and the course's Analytics view; empty state when
     `taught_courses` is empty.
   - *Studio* when `can_manage_courses` — titled "Studio", listing owned/editable
     courses + "New course", linking to `courses:manage_course_list`.
   - *Administration* / generic panels — unchanged.
3. Any course link a teacher follows resolves through `can_access_course` →
   `accessible_courses`, which now includes `Q(groups__teachers=user)`, so the
   teacher is admitted to courses they teach and 403'd elsewhere.
4. The nav "Groups" link → tabbed page; the tab shell selects the default My Groups
   tab and renders the Manage tab only if the user holds `grouping.view_group`.

## Error handling

- **Access denials remain 403 / 404 exactly as today.** Extending
  `accessible_courses` only *adds* rows to the allowed set; it never widens beyond
  taught/owned/enrolled/staff. Node-scoping (`get_node_or_404`) is unchanged, so a
  foreign node still 404s before any 403.
- **Empty states** are preserved for every panel: no enrolled courses, no taught
  courses, and no editable courses each render their existing helptext rather than a
  blank panel.
- **Single-tab Groups**: when a user is entitled to only one Groups tab, the page
  renders that tab's content without a tab strip — never an empty or permission-denied
  second tab.
- **Removed nav links do not break deep links**: `courses:my_courses` and
  `courses:catalog` routes are retained, so any bookmarked/linked URL still resolves;
  only the nav affordances are removed.
- **No new migration.** The `Group.teachers` M2M and `Group.course` FK already exist;
  this feature adds no model fields.

## Testing

Existing tests assert the *current* nav labels and dashboard behavior and **will
break** under the restructure; they are updated as part of the work, and new tests
are added for the new behavior.

**Tests to update** (assert old labels/links that change):
- `tests/test_catalog_nav.py` — students-only Browse link location.
- `tests/test_surfaces.py` — the `test_dashboard_*` panel assertions (Teaching panel
  content, "Authoring"→"Studio" title, manage-link presence).
- `tests/test_consumption_pages.py` — `test_home_dashboard_uses_panels`.
- `tests/test_media_manager.py` — a reference to navigating via "Manage courses".
- Any nav test asserting a top-level "Courses", "Manage", "Groups", or "My groups"
  link (renamed/removed).

**New tests:**
- `accessible_courses` includes courses the user teaches via `Group.teachers`, and
  excludes courses they neither teach, own, nor are enrolled in.
- `can_access_course` / a consumer route (`course_outline`) admits a group-assigned
  teacher to a taught course and 403s them on an untaught course. The teacher fixture
  must be a realistic non-staff teacher (a plain user in the Teacher group assigned
  via `Group.teachers`), not a staff user — mirroring the `course-access-is-staff`
  caveat that `make_teacher` ≠ a production teacher.
- The Teaching dashboard panel lists a teacher's taught courses (and shows the empty
  state when there are none), each with an outline link and an Analytics link.
- The Studio dashboard panel renders under the "Studio" title for an author/owner.
- The nav no longer renders a "Courses" link, renders "Studio" (not "Manage"), and
  renders a single "Groups" entry.
- The merged Groups page renders both tabs for a `view_group` holder, and only the
  My Groups tab for a user with just `view_collection`.

Tests run under the project's `uv run pytest` harness. On Windows, if `pytest-xdist`
parallelism flakes, fall back to serial (`-p no:xdist` / `-n0`), per the project's
established Windows xdist guidance.
