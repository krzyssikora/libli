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

Add a per-row "Analytics" link:

- each **group** row → `{% url 'courses:manage_analytics' slug=group.course.slug %}?scope=group:{{ group.pk }}`
- each **collection** row → `{% url 'courses:manage_analytics' slug=c.course.slug %}?scope=collection:{{ c.pk }}`

No gating needed. `my_groups` lists `groups_visible_to(...).filter(archived=False)` and
`collections_manageable_by(...).filter(archived=False)` — every row is something the user
teaches/manages on a non-archived group/collection, so `can_review_course` is guaranteed
true for each row's course.

### 2. `templates/grouping/group_detail.html` — group page

Add an "Analytics" action link near the heading →
`{% url 'courses:manage_analytics' slug=group.course.slug %}?scope=group:{{ group.pk }}`
(pre-filtered to this group).

**Gated** on a new `can_review` boolean added to the `group_detail` view context
(`grouping/views.py:275`), computed as `scoping.can_review_course(request.user, group.course)`.
This covers the edge case where a teacher's *only* reach is an **archived** group: they would
404 on the page gate, so the link is hidden rather than offered dead.

### Styling & i18n

- Reuse the existing `btn btn--ghost btn--small` pattern from `_course_panel.html:8` so the
  button matches the established Analytics control.
- These two templates are currently bare/unstyled lists; add only the link, do not restyle.
- Reuse `{% trans "Analytics" %}` (already a translated msgid via `_course_panel.html`), so
  no new catalog string is expected. Verify the PL `.po` during build.

## Testing (TDD)

- **my_groups**: as a teacher with a group and a collection, assert the page contains an
  Analytics link to `manage_analytics` for each, with the correct `?scope=group:<pk>` /
  `?scope=collection:<pk>` query string.
- **group_detail**: as a group teacher, assert the Analytics link renders scoped to that
  group. As a viewer whose `can_review` is False, assert the link is absent (verifies the flag).
- Run the focused `grouping` test suite plus the i18n catalog test (touches translatable
  templates, per the recurring "run i18n catalog tests when touching translatable strings" lesson).

## Non-goals

- No changes to the analytics view, its gating, or scope resolution.
- No restyle of `my_groups.html` / `group_detail.html` beyond adding the link.
- No new top-nav entry (nav is global, not course-scoped — no natural slot).
