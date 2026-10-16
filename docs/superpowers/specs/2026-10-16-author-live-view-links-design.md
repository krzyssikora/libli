# Author live-view links

Date: 2026-10-16
Status: approved by the owner (brainstorming, 2026-10-16)

## Purpose

An author edits a unit on the computer, then opens the installed app (PWA) on
their phone to see how that unit looks and works on a real device. Today they
cannot find it:

- The dashboard (`core.views.home`, `templates/core/home.html`) is the PWA's
  start page. It lists the author's courses only in the **Studio** panel, and
  every Studio link opens the **builder** (`courses:manage_builder`).
- The author is not enrolled in their own course, so "My learning" does not
  list it.
- Nothing on the dashboard reaches the student-facing pages.

The student-facing page already exists and already admits the author:
`/courses/<slug>/u/<unit-pk>/` (`courses:lesson_unit`, which redirects a quiz
to `courses:quiz_unit`). For an author it shows drafts, with the draft banner,
and an "Edit unit" link. **The owner confirmed that this page, exactly as it
behaves today, is the target.** This work only adds ways to get there.

The triggering case was a **draft** unit, so nothing may hide drafts.

## Owner decisions (verbatim intent; do not reverse in review)

| # | Decision |
|---|----------|
| D1 | The target is the existing `/courses/<slug>/u/<pk>/` page (and `courses:course_outline` for a course), with **no change** to what it shows an author. |
| D2 | Build all three entry points: the Studio "View" link, the "Last edited" card and the editor's "View live" link. |
| D3 | "Last edited" uses `ContentNode.updated` and **accepts its approximation "for now"** (see Component 2). No new field, no migration. |

## Calls made by Claude (owner may override)

| # | Call |
|---|------|
| C1 | The Studio course title keeps linking to the builder; "View" is a secondary action. Desktop habit is unchanged. |
| C2 | "Last edited" covers courses the user **owns** (`Course.owner == user`) only, not `manageable_courses`. |
| C3 | The editor link opens in a **new tab**, mirroring the "Edit unit" link in `templates/courses/_unit_strip.html`. |
| C4 | The editor link is rendered only when `can_access_course(user, course)` is true. |
| C5 | EN wording: "View" (Studio row action), "Last edited" (card label), "View live" (editor link). PL wording is proposed in the PR for owner review. |

## Non-goals

- No change to the live page for authors: the draft banner, the "Edit unit"
  link, no Continue card and unrecorded quiz attempts all stay.
- No "hide drafts" or "view as a real student" mode.
- No QR code or "send to phone".
- No change to the builder page.
- No tracking of *who* last edited a unit.

## Anti-goals

- Changing where the Studio course title goes.
- Any widening of who can see drafts or open the live pages. Every link points
  at a page whose access rules already exist and **stay untouched**:
  `can_access_course`, `get_node_or_404(viewer=...)` and `can_see_drafts`
  (`courses/access.py`). A link appears only where following it succeeds.
- A "Last edited" card that surfaces another author's unit.

## Architecture / components

### Component 1 — Studio "View" link (dashboard)

`templates/core/home.html`, Studio panel (`data-section="manage"`). Each
`owned_courses` row changes from a bare `<li><a …builder…>` to the Teaching
panel's existing pattern: `<li class="dash-row">` with the title link
(unchanged: `courses:manage_builder`) and a `dash-row__action` link labelled
"View" pointing at `courses:course_outline` for that course. The
`.dash-list li.dash-row` / `.dash-row__action` CSS already exists in
`core/static/core/css/app.css` (around line 390). No new CSS is expected
beyond what that pattern already provides.

Access: `owned_courses` is `Course.objects.filter(owner=request.user)`, and the
owner always passes `can_access_course` (the owner disjunct of
`accessible_courses`), so the link always works.

### Component 2 — "Last edited" card (dashboard)

At the top of the Studio panel (before the course list), when the user owns at
least one unit, render one card: the unit title and the course title. The whole
card links to `courses:lesson_unit` for that unit.

- **Query (computed in `core.views.home`):** `ContentNode` rows with
  `kind="unit"`, `course__owner=request.user`, ordered `-updated, -pk`, the
  first one, with `select_related("course")`. Drafts are included.
- **No owned unit → no card**, and no empty-state text.
- **Known approximation (D3).** `updated` is `auto_now`. `courses/builder.py`
  bumps it on every element save, reorder and delete, which is the case this
  feature serves. It is also bumped on units the author did not edit:
  - sibling renumbering on a move (`courses/ordering.py:27`, `:89-93`);
  - a subtree flag toggle (`courses/builder.py:950`);
  - bulk maintenance commands (e.g.
    `courses/management/commands/fix_space_before_punctuation.py`).

  After one of those the card may show a neighbouring unit. That is accepted.
  **Do NOT stop those bumps** to "fix" it: they keep the concurrency tokens
  valid. The `-pk` tie-break makes equal timestamps deterministic.
- Unit titles can contain maths. Render the title the way the dashboard
  renders other node titles, and if a `data-math-title` / KaTeX hook is needed
  for titles elsewhere on the dashboard, follow it. If the dashboard has none,
  plain escaped text is acceptable.
- Styling: within the existing dashboard visual language (tokens from
  `app.css`), light and dark mode, phone width with no horizontal scroll. The
  exact markup and CSS are the builder's.

### Component 3 — "View live" link (unit editor)

`templates/courses/manage/editor/editor.html`, the `editor-crumb` row (next to
the "Media library" link is the natural spot; exact placement is the
builder's). An `<a>` to `courses:lesson_unit` for the unit (a quiz redirects to
`quiz_unit`, as today), with `target="_blank" rel="noopener"` and the
visually hidden "(opens in a new tab)" suffix, mirroring
`templates/courses/_unit_strip.html`.

- Rendered only when `can_access_course(request.user, course)` is true (C4).
  A Platform Admin holding `courses.change_course` who is neither `is_staff`
  nor the owner can open the editor, but `lesson_unit` would 403 them. The
  flag is computed in the editor view (`courses/views_manage.py`) and passed
  in the context. **Do not widen the read gate** to make the link work for
  them.
- An icon is optional; if used, a monochrome inline SVG with `currentColor`,
  never an emoji.

## Data flow

- Dashboard GET → `home` computes `owned_courses` (existing) plus
  `last_edited_unit` (new, Component 2) → template renders the card and the
  per-course "View" actions → the author taps → existing `lesson_unit` /
  `course_outline` views apply their existing gates.
- Editor GET → the editor view adds `can_view_live` (`can_access_course`) →
  the template renders the link or omits it → the click opens the existing
  live page in a new tab.

No writes, no migrations, no JS.

## Error handling

There are no new failure paths. Every target view keeps its own gate (404 for a
draft to a non-author, 403 for no access). The new links are rendered only
where those gates already admit the viewer, so a rendered link never leads to a
403 or 404 for the viewer it was rendered for.

## i18n

New msgids ("View", "Last edited", "View live" and any card label) get PL
translations in `locale/pl/LC_MESSAGES/django.po`, and the `.mo` is
regenerated. Watch for `makemessages` marking entries `#, fuzzy` with a wrong
guess. "View" may already exist as a msgid with a different sense, so reuse it
only if the existing PL fits a link label, otherwise use a `pgettext` context.

## Testing

Server-rendered; Django view and template tests are the main layer, plus an e2e
check that the links work on a narrow viewport.

- **Studio "View":** the owner's dashboard row has a link to that course's
  `course_outline`; following it returns 200; the title still links to the
  builder.
- **Last edited:**
  - With two owned units, the one with the later `updated` is shown, and its
    link is that unit's `lesson_unit` URL.
  - A **draft** unit can be the one shown, and following its link returns 200
    for the owner.
  - The tie-break: equal `updated`, so the higher pk wins.
  - A unit in a course owned by someone else, updated later, is **not** shown,
    including for a Platform Admin (`make_pa`) who owns a course of their own.
  - A user with no owned units sees no card.
- **Editor "View live":**
  - The owner sees the link to `lesson_unit` for the unit, with
    `target="_blank"`; following it returns 200 (a draft included).
  - A non-staff, non-owner Platform Admin can open the editor (200) but gets
    **no** "View live" link.
- Test fixtures: use `make_pa` / `make_verified_user` / `make_login` from
  `tests/factories.py`. Never use `UserFactory` + `force_login` (the password
  is never persisted, so the client is silently anonymous).
- Each new assertion must be shown to fail on a mutant (e.g. drop the
  `owner` filter, drop the `can_access_course` guard, flip the ordering).
- Test runs stay narrow per task. One branch-level run at the end.
