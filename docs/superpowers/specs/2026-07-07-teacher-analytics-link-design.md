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

Additive link-only change in three teacher-facing templates (`my_groups`, `group_detail`,
`collection_detail`), each adding a context flag where noted. No new view, URL, permission,
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
`my_groups` lists collections via `collections_manageable_by(user)` — collections the user *owns*
or that sit on a course they own (`Q(owner=user) | Q(course__owner=user)`, `grouping/scoping.py:48`)
— but `can_review_course` never consults collection ownership; it grants reach only to a
PA, the course owner, or a teacher of a non-archived group on the course. A teacher can own a
collection on a course where they teach no live group (e.g. a zero-group collection, or one whose
member groups were later archived), so an ungated collection link would 404 at the page gate.

Mechanism: the `my_groups` view must **materialize the collections queryset to a list**, attach a
`can_review = scoping.can_review_course(user, c.course)` boolean to each collection instance, and
pass that list into the context — annotating the lazy `collections.order_by("name")` queryset in
place would silently drop the flags. The template then guards the link with `{% if c.can_review %}`.
Each flag costs one small `.exists()` query per collection (N is tiny). The view should also
`select_related("course")` on **both** the groups and collections querysets, since every row now
dereferences `.course.slug` (and already dereferenced `.course.title`).

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

### 3. `templates/grouping/collection_detail.html` — collection page

Symmetric with §2, so teachers get the same scoped entry point from a collection they navigated
into (not only from the `my_groups` row). Add an "Analytics" action link to the page's existing
`btn btn--ghost btn--small` action row, **immediately after the existing Edit link and before the
Delete control** →
`{% url 'courses:manage_analytics' slug=collection.course.slug %}?scope=collection:{{ collection.pk }}`
(pre-filtered to this collection).

**Gated** on `can_review and not collection.archived`, where `can_review` is a new boolean added to
the `collection_detail` view context (`grouping/views.py:354`), computed as
`scoping.can_review_course(request.user, collection.course)`. Same rationale as §1's collection
rows: `collection_detail` resolves the collection via `collections_manageable_by` (collection-owner
or course-owner, which does *not* imply review reach — so `can_review` is **load-bearing** here, not
merely defensive), and
an archived collection's `scope=collection:<pk>` would fall back to "all my students"
(`students_in_scope` accepts a collection scope only via `collections_visible_to`, which excludes
archived — `grouping/scoping.py:139`), so the link is hidden on archived collections.

### Styling & i18n

- Reuse the existing `btn btn--ghost btn--small` pattern from `_course_panel.html:8` so the
  button matches the established Analytics control.
- `my_groups.html` and `group_detail.html` are currently bare/unstyled lists and
  `collection_detail.html` already has a small `btn` action row; in all three, add only the link,
  do not restyle.
- Reuse `{% trans "Analytics" %}` (already a translated msgid via `_course_panel.html`), so
  no new catalog string is expected. Because the msgid now appears in three new templates,
  `makemessages` will add fresh `#:` location comments to `locale/*/LC_MESSAGES/django.po`; run
  `makemessages` and commit the refreshed catalogs so source locations aren't left stale — the
  catalog-clean tests only guard against `#, fuzzy` / `#~` obsolete entries, not stale locations, so
  skipping this would still pass CI. Confirm no new untranslated msgid appears.

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
- **group_detail (archived, `can_review` True)** — the fixture that *isolates* the `not group.archived`
  gate: a course owner (or CA) viewing their **own archived group** — `groups_visible_to` returns it
  and `can_review_course` is True (they own the course) — assert the link is **absent**. This is the
  only setup where removing the `not group.archived` term would flip the outcome, so it is what
  actually proves the archived gate (a teacher whose *only* reach is the archived group has
  `can_review` False too, so that case can't distinguish the two terms).
- **group_detail (archived, only reach)**: a teacher whose only group on the course is archived —
  `groups_visible_to` still returns it (the group is theirs) but `can_review_course` is False —
  assert the link is absent, covering the `can_review` term / 404-avoidance rationale.
- **collection_detail (reachable)**: as a teacher of a non-archived member group of a non-archived
  collection (`can_review` True), assert the Analytics link renders scoped to the collection
  (`?scope=collection:<pk>`).
- **collection_detail (unreachable)**: as a user who owns/manages the collection but teaches no live
  group on its course (`can_review` False), assert the link is **absent** — verifying the
  load-bearing `can_review` gate on collection_detail.
- **collection_detail (archived, `can_review` True)** — isolates the `not collection.archived` term,
  mirroring the group_detail archived test: a viewer with `can_review` True on the course (course
  owner, or teacher of a live group) who opens their own **archived** collection, assert the link is
  **absent**. This is the only setup where removing the archived term would flip the outcome.
- Run the focused `grouping` test suite plus the i18n catalog test (touches translatable
  templates, per the recurring "run i18n catalog tests when touching translatable strings" lesson).

## Non-goals

- No changes to the analytics view, its gating, or scope resolution.
- No restyle of `my_groups.html` / `group_detail.html` / `collection_detail.html` beyond adding the link.
  **(Superseded during execution:** the user requested a design-system restyle of these three
  previously-bare pages once the links were in place, so a restyle was deliberately folded onto the
  same branch as a follow-on slice — see the `style(grouping): …` commit. The link-only Non-goal
  above reflects the original scope; the restyle is intentional, not scope creep.)
- No new top-nav entry (nav is global, not course-scoped — no natural slot).
