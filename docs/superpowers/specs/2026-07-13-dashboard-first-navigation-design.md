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
  "Authoring". **Intentional gate divergence:** the *nav* "Studio" link stays
  `change_course`-gated (the PA ledger entry), while the *dashboard* "Studio" panel is
  gated by `can_manage_courses` (True via course ownership alone). A plain course owner
  therefore sees the Studio *panel* but no Studio *nav link* — a faithful port of
  today's Manage/Authoring split; do not "fix" one gate to match the other.
- **Merge "Groups" + "My groups" → a single "Groups"** link, gated
  `perms.grouping.view_collection or perms.grouping.view_group` (matching today's
  broader *My groups* gate so a `view_collection`-only user keeps their entry point),
  targeting `grouping:my_groups`, which renders the tabbed page (component 4). Both
  underlying routes are kept.
- **Drop the students-only "Browse" nav link** (`courses:catalog`). The dashboard
  already surfaces a "Browse courses" button for the same audience; one entry point
  is enough. The `courses:catalog` route is unchanged. The dashboard "Browse courses"
  button's gate **gains `and not taught_courses`** (mirroring the generic-panel fix):
  today's gate (`not is_staff and not is_superuser and not is_teacher and not
  is_course_admin and not is_platform_admin`) would otherwise show the student-style
  Browse button alongside a populated Teaching panel for the flagship group-only
  teacher. Suppressing it there keeps the button student-only in practice.
- **Unchanged:** Tags & notes, Help, the Admin dropdown, the notification bell, and
  the account/avatar menu.

### 2. Dashboard panels (`core/home.html`, `core/views.py`)

The dashboard scaffold already exists with five conditional panels. Changes:

- **My learning** — unchanged (lists enrolled courses; empty state kept).
- **Teaching** — *finish the stub*. Today it renders only the text "No classes
  assigned yet." Change it to list the courses the user teaches and, per course,
  link to the course outline (`courses:course_outline`) and to that course's
  **Analytics matrix** (`courses:manage_analytics`, slug kwarg — the teacher class
  matrix, **not** the student `courses:course_results` page). The Analytics link is
  rendered **unconditionally** for each row, not via a per-row gate call: every course
  in `taught_courses` teaches a non-archived group, which necessarily satisfies
  `scoping.can_review_course` (its `groups_visible_to` includes
  `Group.objects.filter(teachers=user)` and it filters `archived=False`), so the link
  is always live. When the user teaches nothing, keep the existing empty state. The panel's visibility gate is widened to `is_teacher or
  taught_courses` (see component 2's gating note and *Data flow*). The taught-courses
  queryset is supplied by the view (component 3).
- **Studio** (currently titled "Authoring") — rename the panel title to **Studio**
  for consistency with the nav. The panel lists the user's **owned** courses inline
  (`owned_courses`, see *Data flow* — owner-scoped, deliberately **not** the full set
  a Platform Admin could edit; a PA's inline list stays their own courses, and the
  whole platform's courses remain reachable via the ledger link). Each row links to
  that course's builder (`courses:manage_builder`, slug kwarg). Below the list it
  offers an **"All courses"** link to the full Studio ledger
  (`courses:manage_course_list`, login-only, safe) and a **"New course"** action
  (`courses:manage_course_create`). The "New course" action is **rendered only when
  the user holds `perms.courses.add_course`** — independent of the panel's
  `can_manage_courses` visibility gate. This matters because `can_manage_courses` is
  True via *course ownership alone*, while `manage_course_create` is decorated
  `@permission_required("courses.add_course", raise_exception=True)`; a PA can grant a
  user course ownership (via `course_edit`) without `add_course`, so an unconditional
  "New course" link would 403 for that plain owner. When the user owns nothing yet,
  the panel shows the (permission-gated) "New course" action without a list.

**Teaching-panel gating note (closes #91 in the UI too).** The panel gate is
`is_teacher or taught_courses`, **not** `is_teacher` alone. `is_teacher` is TEACHER
*role-group* membership (`core.context_processors.user_roles`), whereas `taught_courses`
derives from `Group.teachers`; the two are independent. Gating on the role group alone
would hide the panel from a user granted course access via `Group.teachers` who is not
in the Teacher role group — leaving them with the access fix but no UI entry point, and
contradicting the Purpose. The `or taught_courses` disjunct guarantees any user with at
least one taught course sees the panel.
- **Administration** — unchanged.
- **Generic empty-state** panel — its render condition **must gain `and not
  taught_courses`**. Today it fires when the user has no role flag, no enrolled
  courses, and no manage capability. Without adding `not taught_courses`, the
  feature's flagship user (granted a course via `Group.teachers`, not in the Teacher
  role group, not enrolled, no `change_course`, owns nothing) would satisfy **both**
  the widened Teaching gate (`is_teacher or taught_courses`) and the generic
  empty-state condition — rendering a populated Teaching panel *and* the "your
  dashboard will fill in" empty state at once. Adding `not taught_courses` (mirroring
  the existing `not can_manage_courses` term) removes the contradiction.

`core/views.py::home` gains a `taught_courses` queryset in its context (see *Data
flow*). It keeps its existing first-run setup-wizard redirect and the
`enrolled_courses` / `can_manage_courses` context untouched.

### 3. Access control — closes #91 (`courses/access.py`)

`accessible_courses(user)` today returns, for a non-staff user, only
`Q(pk__in=enrolled) | Q(owner=user)`. A group-assigned teacher matches neither, so
`can_access_course` (which delegates to `accessible_courses`) denies them their own
taught courses.

Extend the queryset to also include taught courses via the
`Group.teachers` → `Group.course` path, **excluding archived groups**:

```python
return Course.objects.filter(
    Q(pk__in=enrolled)
    | Q(owner=user)
    | Q(groups__teachers=user, groups__archived=False)
).distinct()
```

`.distinct()` is already present and remains necessary (the join can multiply rows).
The `groups__archived=False` qualifier is load-bearing and must sit **inside** the
same `Q(...)` as `groups__teachers=user` (a single join condition), so an archived
group never grants access. This keeps `accessible_courses` consistent with the
scoping layer: `grouping.scoping.can_review_course` (the Analytics gate) and the
`my_groups` view both filter archived groups out, so without this qualifier a teacher
tied only to an archived group would get a working outline but a 404 on Analytics —
an inconsistency. Because `can_access_course` and every consumer route
(`course_outline`, `lesson_unit`, `quiz_unit`, `course_results`, …) delegate to
`accessible_courses` as the single source of truth, this one change grants teachers
read access to the non-archived courses they teach — and **only** those.
Staff/superuser (all courses) and owner/enrolled paths are unchanged. The function's
docstring is updated from "owned ∪ enrolled" to "owned ∪ enrolled ∪ taught
(non-archived groups)".

This is the one security-adjacent change and receives explicit positive and negative
tests (a teacher can open a course they teach; a teacher cannot open a course they
do not teach and are not otherwise related to).

### 4. Groups merge (`grouping`)

Replace the two nav entries with a single tabbed **pair of kept routes**, following
the **Tags & notes** *pattern* (link-based tabs, **not** a composing shell that
embeds one view inside another). This requires a **new** include — the existing
`templates/_tags_notes_tabs.html` hardcodes the notes/tags `<a>` links and `tnhub__`
CSS classes, so it cannot be reused. Author a new sibling include,
`templates/_groups_tabs.html`, holding the two group-tab `<a>` links; both
`grouping/my_groups.html` and `grouping/group_list.html` `{% include %}` it, and each
view sets a `hub_tab` context flag the include matches with `{% if hub_tab == '...' %}`
to mark the active tab:

- **Tab 1 — My groups** (default): the current `grouping:my_groups` view (the user's
  own group memberships / collections). Sets `hub_tab = "my_groups"`. Entitlement:
  `grouping.view_collection` OR `grouping.view_group`.
- **Tab 2 — Manage**: the current `grouping:group_list` view (group administration).
  Sets `hub_tab = "manage"`. Entitlement: `grouping.view_group`.

The one behavioral difference from Tags & notes — whose two tabs are *always* both
shown — is that the Groups strip is **entitlement-conditional**: the include renders
the Manage tab link only when the user holds `grouping.view_group`. When only one tab
is entitled (a `view_collection`-only user), the include renders that tab's content
**with no tab strip at all** — never an empty or permission-denied second tab. Both
existing views are kept unchanged except for setting their `hub_tab` flag and
rendering the new strip include. The nav "Groups" link targets `grouping:my_groups`
(the default tab).

**On the single-tab branch (defensive).** Under the default role matrix
(`institution/roles.py`), every role that holds `grouping.view_collection` (Teacher,
Course Admin, Platform Admin) also holds `grouping.view_group`, so no *standard* role
is `view_collection`-only and the disjunct is effectively equivalent to `view_group`.
The single-tab (no-strip) branch is retained deliberately — it faithfully mirrors
today's broader *My groups* gate and correctly serves any non-standard per-user
permission grant — not as a claim that a standard role reaches it. Keep it; do not
simplify the gate to bare `view_group`.

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
   - `taught_courses = Course.objects.filter(groups__teachers=user, groups__archived=False).distinct().order_by("title")` (new; archived groups excluded to match the scoping layer).
   - `owned_courses = Course.objects.filter(owner=user).order_by("title")` (new; the Studio panel's inline list — owner-scoped, **not** all-editable).
   - `can_manage_courses` (existing).
   - Role flags (`is_student`, `is_teacher`, `is_course_admin`, `is_platform_admin`)
     are injected by the existing `core.context_processors.user_roles` context
     processor and continue to drive which panels render.
2. `core/home.html` renders panels conditionally:
   - *My learning* when `is_student or enrolled_courses`.
   - *Teaching* when **`is_teacher or taught_courses`** (see the gating note in
     component 2) — iterating `taught_courses`, each row linking to
     `courses:course_outline` and the course's Analytics matrix
     (`courses:manage_analytics`, slug kwarg — rendered unconditionally; every taught
     non-archived course satisfies `scoping.can_review_course`, so no per-row gate call
     is needed); empty state when `taught_courses` is empty.
   - *Studio* when `can_manage_courses` — titled "Studio", listing `owned_courses`
     inline (each row → `courses:manage_builder`), an "All courses" link to the ledger
     (`courses:manage_course_list`), and a "New course" action
     (`courses:manage_course_create`) **rendered only when `perms.courses.add_course`**
     (see component 2, I-note).
   - *Administration* panel — unchanged. *Generic empty-state* panel — condition gains
     `and not taught_courses` (see component 2).
3. Any course link a teacher follows resolves through `can_access_course` →
   `accessible_courses`, which now includes
   `Q(groups__teachers=user, groups__archived=False)`, so the teacher is admitted to
   the non-archived courses they teach and 403'd elsewhere.
4. The nav "Groups" link → tabbed page; the tab shell selects the default My groups
   tab and renders the Manage tab only if the user holds `grouping.view_group`.

## Error handling

- **Access denials remain 403 / 404 exactly as today.** Extending
  `accessible_courses` only *adds* rows to the allowed set; it never widens beyond
  taught(non-archived)/owned/enrolled/staff. Node-scoping (`get_node_or_404`) is
  unchanged, so a foreign node still 404s before any 403.
- **Archived groups grant nothing.** The `groups__archived=False` qualifier keeps the
  access grant, the Teaching panel list, and the Analytics gate
  (`scoping.can_review_course`) mutually consistent — a teacher tied only to an
  archived group sees the course in none of them (no phantom row, no dead Analytics
  link).
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
- `tests/test_surfaces.py` — the `test_dashboard_*` panel assertions (Teaching panel
  content, "Authoring"→"Studio" title, manage-link presence).
- `tests/test_consumption_pages.py` — `test_home_dashboard_uses_panels`.
- `tests/test_media_manager.py` — a reference to navigating via "Manage courses".
- `tests/test_grouping_course_links.py` — `test_teacher_can_follow_my_groups_link_to_the_outline`
  has a docstring asserting that access is granted only via the `is_staff` branch and
  that "`Group.teachers` is never consulted by the course-access gate." This fix makes
  that consultation happen, so the docstring is now false. Correct/remove the stale
  docstring; optionally simplify the test to use a non-staff `Group.teachers` teacher
  now that that is the intended access path (this test still passes green via
  `is_staff`, so the falsehood would otherwise ship silently in a security-adjacent
  test).
- Any nav test asserting a top-level "Courses", "Manage", "Groups", or "My groups"
  link (renamed/removed).

**Intentionally unaffected** (do not chase a non-breakage): `tests/test_catalog_nav.py`
asserts the `courses:catalog` link on the *home page*, which is driven by the dashboard
"Browse courses" button — unchanged by this feature (only the redundant *nav* Browse
link is removed). Both its tests stay green. (Note: if M4's decision below suppresses
the Browse button for group-teachers, re-check this file, since its student fixture
must remain a non-teacher.)

**New tests:**
- `accessible_courses` includes courses the user teaches via `Group.teachers`, and
  excludes courses they neither teach, own, nor are enrolled in.
- `accessible_courses` (and `taught_courses`) **excludes** a course whose only tie is
  an *archived* group — the teacher of an archived group is not admitted and the
  course does not appear in the Teaching panel.
- `can_access_course` / a consumer route (`course_outline`) admits a group-assigned
  teacher to a taught course and 403s them on an untaught course. **The fixture must
  have `is_staff=False`** and the test must assert `not user.is_staff`, otherwise the
  test passes vacuously: `accessible_courses` short-circuits to `Course.objects.all()`
  for any `is_staff` user, so an `is_staff` fixture never exercises the new
  `Q(groups__teachers=user, groups__archived=False)` branch. Note the ambiguity to
  avoid: `set_user_role(user, TEACHER)` (adding the *auth role group*) sets
  `is_staff=True` and would mask the branch; the fixture instead needs a plain
  non-staff user added to a `Group.teachers` M2M (the grouping relation, not the auth
  role group) — mirroring the `course-access-is-staff` caveat that a role-group
  teacher ≠ the `Group.teachers` relation this fix keys on.
- The Teaching dashboard panel lists a teacher's taught courses (and shows the empty
  state when there are none), each with an outline link and an Analytics link.
- The Studio dashboard panel, for an author/owner, renders under the "Studio" title,
  lists an owned course inline (row links to its builder `courses:manage_builder`),
  and renders the "New course" action (`courses:manage_course_create`).
- The Teaching panel is visible to a user who has a taught (non-archived) course even
  when they are **not** in the Teacher role group (gate `is_teacher or taught_courses`).
- The nav no longer renders a "Courses" link, renders "Studio" (not "Manage"), and
  renders a single "Groups" entry.
- The merged Groups page renders both tabs (with the tab strip) for a `view_group`
  holder, and only the My groups tab (no tab strip) for a user with just
  `view_collection`. The `view_collection`-only fixture must be built by granting the
  `grouping.view_collection` permission (or a custom group holding only it) **directly
  to the user — not via any standard role**, since no standard role is
  `view_collection`-only (see §4's defensive note). An implementer reaching for
  `set_user_role` cannot reach the single-tab branch.

Tests run under the project's `uv run pytest` harness. On Windows, if `pytest-xdist`
parallelism flakes, fall back to serial (`-p no:xdist` / `-n0`), per the project's
established Windows xdist guidance.

**Internationalization.** This project is bilingual EN/PL and its catalog tests
(`tests/test_i18n_notes.py::test_po_catalog_clean`, mirrored in `test_i18n_auth.py`,
`test_tags_i18n.py`) read the whole `locale/pl/LC_MESSAGES/django.po` and assert
`"#~" not in text` — i.e. **no obsolete entries**. This feature both **adds** and
**removes** `{% trans %}` strings, so the i18n step has two halves:

- *Added* strings needing PL translation: "All courses" and "New course". The Groups
  tab labels **reuse existing msgids** — "My groups" (already translated) and "Manage"
  (survives, reused as the Manage tab label) — so they need no new translation.
- *Removed* string references orphan three currently-translated msgids: the nav
  "Courses" (`base.html`), "Browse" (`base.html`), and the panel "Authoring"
  (`home.html`). ("My groups" is **not** orphaned because it is reused as the tab
  label — see the sentence-case label choice in §4.)

Run `uv run python manage.py makemessages --no-obsolete` (the `--no-obsolete` flag is
load-bearing: plain `makemessages` marks the three removed msgids `#~` obsolete rather
than dropping them, which turns `test_po_catalog_clean` **red** — the exact gotcha the
project's DoD note records) or hand-delete the `#~` blocks. Heed the fuzzy-flag caveat
(review `#, fuzzy` entries), supply the two new Polish translations, compile, and
**re-run the three catalog tests** as part of DoD. **"Studio" is deliberately left as a
loanword** (identical in EN and PL) and needs no PL translation; keep its msgid
self-equal rather than inventing a Polish form.
