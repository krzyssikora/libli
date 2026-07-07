# Teacher-facing Analytics link — design

**Date:** 2026-07-07
**Type:** Product/UX follow-up (docs slice 2 follow-up)

## Problem

The analytics matrix view (`courses:manage_analytics`, route `manage/courses/<slug>/analytics/`)
is teacher-accessible: its page gate is `scoping.can_review_course(user, course)`
(`grouping/scoping.py:80`), which grants access to a Platform Admin, the course owner,
or **any user who teaches a non-archived group on the course**.

However, the only UI link to it lives in `templates/courses/manage/_course_panel.html:8`,
which is included only from `templates/courses/manage/builder.html` — a page gated by
`can_manage_course` (owner/PA only). So **teachers can reach analytics only by typing the URL.**

## Goal

Give teachers a discoverable, in-UI entry point into the analytics matrix, pre-filtered
to the group/collection they navigated from.

## Design

Additive link-only change in two teacher-facing templates. No new view, URL, permission,
or migration.

### Deep-link scoping

The matrix accepts scope via GET query params: `?scope=group:<pk>` or `?scope=collection:<pk>`
(resolved by `scoping.students_in_scope`, `grouping/scoping.py:118`). That resolver
**re-derives scope from the user's own reach** and safely falls back to "all my students"
for any unreachable/malformed scope, so a scoped deep-link is self-healing. The real guard
remains the page-level `can_review_course` gate (404 on failure).

### 1. `templates/grouping/my_groups.html` — the teacher hub

Add a per-row "Analytics" link, styled `btn btn--ghost btn--small`, appended **after the
`.muted` course-title span** inside each `<li>`:

- each **group** row → `{% url 'courses:manage_analytics' slug=group.course.slug %}?scope=group:{{ group.pk }}`
- each **collection** row → `{% url 'courses:manage_analytics' slug=c.course.slug %}?scope=collection:{{ c.pk }}`

**Group rows: no gating needed.** `my_groups` lists `groups_visible_to(...).filter(archived=False)`,
and for any non-archived group the user can see on a course, `can_review_course` is by definition
true — it is exactly `groups_visible_to(user).filter(course=course, archived=False).exists()`
(`grouping/scoping.py:80`), which this very row satisfies. So each group row's deep-link is always
reachable.

**Collection rows: gated on review reach.** The premise does *not* hold for collections.
`my_groups` lists collections via `collections_manageable_by(user)` — collections the user
*owns* — but `can_review_course` never consults collection ownership; it grants reach only to a
PA, the course owner, or a teacher of a non-archived group on the course. A teacher can own a
collection on a course where they teach no live group (e.g. a zero-group collection, or one whose
member groups were later archived), so an ungated collection link would 404 at the page gate. The
`my_groups` view must therefore annotate each listed collection with
`can_review = scoping.can_review_course(user, collection.course)` (a small per-collection check; N
is tiny), and the template renders the collection's Analytics link only when that flag is true.

### 2. `templates/grouping/group_detail.html` — group page

Add an "Analytics" action link **on its own line immediately after the `<p class="muted">`
course-title line**, styled `btn btn--ghost btn--small` →
`{% url 'courses:manage_analytics' slug=group.course.slug %}?scope=group:{{ group.pk }}`
(pre-filtered to this group).

**Gated** on `can_review and not group.archived`, where `can_review` is a new boolean added to
the `group_detail` view context (`grouping/views.py:275`), computed as
`scoping.can_review_course(request.user, group.course)`:

- `not group.archived`: on an **archived** group's detail page the scoped deep-link would not
  actually pre-filter — `students_in_scope` requires `archived=False` (`grouping/scoping.py:129`)
  and silently falls back to "all my students", breaking the "pre-filtered to this group" promise.
  So we hide the link on archived groups rather than render a mislabelled one. (Archived groups are
  historical; no analytics entry point is expected there.)
- `can_review`: a defensive access gate. It also covers the case where a teacher's *only* reach is
  an archived group — they would 404 on the page gate — though `not group.archived` already hides
  the link in that scenario. For any **non-archived** group the viewer reached this page through,
  `can_review` is necessarily true (same invariant as the group rows above), so in practice the
  visible-link condition reduces to "the group is not archived"; the flag guards against future
  changes to `groups_visible_to` semantics.

### Styling & i18n

- Reuse the existing `btn btn--ghost btn--small` pattern from `_course_panel.html:8` so the
  button matches the established Analytics control.
- These two templates are currently bare/unstyled lists; add only the link, do not restyle.
- Reuse `{% trans "Analytics" %}` (already a translated msgid via `_course_panel.html`), so
  no new catalog string is expected. Verify the PL `.po` during build.

## Testing (TDD)

- **my_groups (reachable)**: as a teacher who teaches a group and owns a collection whose member
  group they teach (so `can_review_course` is true for both courses), assert the page contains an
  Analytics link to `manage_analytics` for each, with the correct `?scope=group:<pk>` /
  `?scope=collection:<pk>` query string.
- **my_groups (unreachable collection)**: as a teacher who owns a collection on a course where they
  teach no live group (zero-group collection, or all member groups archived), assert the
  collection's Analytics link is **absent** — verifying the collection gating from §Design 1.
- **group_detail (teacher)**: as the teacher of a non-archived group, assert the Analytics link
  renders scoped to that group (`?scope=group:<pk>`).
- **group_detail (archived group)**: as a teacher whose only group on the course is **archived**
  (set up so `groups_visible_to` still returns it — the group is theirs — but it is archived),
  view its detail page and assert the Analytics link is **absent** — verifying the
  `not group.archived` gate. This fixture also drives `can_review == False`, since the archived
  group is the teacher's only reach.
- Run the focused `grouping` test suite plus the i18n catalog test (touches translatable
  templates, per the recurring "run i18n catalog tests when touching translatable strings" lesson).

## Non-goals

- No changes to the analytics view, its gating, or scope resolution.
- No restyle of `my_groups.html` / `group_detail.html` beyond adding the link.
- No new top-nav entry (nav is global, not course-scoped — no natural slot).
