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
| C3 | The editor link opens in a **new tab**, mirroring the "Edit unit" link in `templates/courses/_unit_strip.html`. The dashboard links (card and Studio "View") open in the **same tab**, with no `target`: in a standalone PWA a `_blank` would throw the author out of the app. Tests assert those anchors have no `target`. |
| C4 | The editor link is rendered only when `can_access_course(user, course)` is true. |
| C6 | Dashboard panel order is unchanged; the card lives inside Studio even if that puts it below the fold on a phone. |
| C5 | EN wording: "View" (Studio row action), "Last edited" (card label), "View live" (editor link). PL wording is proposed in the PR for owner review. |

## Non-goals

- No change to the live page for authors: the draft banner, the "Edit unit"
  link, no Continue card and unrecorded quiz attempts all stay.
- No "hide drafts" or "view as a real student" mode.
- No change to `quiz_unit`'s existing redirect to `quiz_results` when the
  viewer has a SUBMITTED `QuizSubmission` (`courses/views.py` ~1503-1511). An
  author with such a row lands on results, which is accepted under D1. Do not
  "fix" it, and do not write a test expecting the quiz page in that state.
- No QR code or "send to phone".
- No change to the builder page.
- No tracking of *who* last edited a unit.
- No live refresh of the "Last edited" card. Navigations are network-first
  (`templates/core/sw.js`), but an installed PWA resumed from memory or
  bfcache shows the dashboard as it was. Reopening or pulling to refresh
  updates it. That is accepted.

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
`core/static/core/css/app.css` (around line 390), but it cannot wrap a long
unbroken title. The flex row has no `min-width: 0` or `overflow-wrap`, so an
unbreakable run overflows the row and the panel and pushes out the page's
`scrollWidth`. So the row's title link and **both** titles on the card (the
unit title and the course title, Component 2) need
`min-width: 0; overflow-wrap: anywhere`, as `.outline-unit__title`
(app.css ~647) already has. Prefer `anywhere` over `break-word`. Do not change
the `.dash-grid` tracks. The 360px e2e is the RED test and the authority on
whether the fix works. The fix also helps the Teaching rows, which share the
class, and that is intended.

Access: `owned_courses` is `Course.objects.filter(owner=request.user)`, and the
owner always passes `can_access_course` (the owner disjunct of
`accessible_courses`), so the link always works.

### Component 2 — "Last edited" card (dashboard)

At the top of the Studio panel (before the course list), when the user owns at
least one unit, render one card: the unit title and the course title. The whole
card links to the unit's live page (URL rule below).

- **Query (computed in `core.views.home`):** `ContentNode` rows with
  `kind=ContentNode.Kind.UNIT`, `course__owner=request.user`, ordered `-updated, -pk`, the
  first one, with `select_related("course")`. Drafts are included.
- **No owned unit → no card**, and no empty-state text.
- **Known approximation (D3).** `updated` is `auto_now`. `courses/builder.py`
  bumps it on every element save, reorder and delete, which is the case this
  feature serves. It is also bumped on units the author did not edit:
  - sibling renumbering on a move (`courses/ordering.py:27`, `:89-93`);
  - a subtree flag toggle (`courses/builder.py:950`);
  - bulk maintenance commands (e.g.
    `courses/management/commands/fix_space_before_punctuation.py`);
  - creating a unit (`auto_now` on insert) and importing a course
    (`import_course` creates every unit with `updated=now`, so after an import
    the card shows an arbitrary imported unit).

  After one of those the card may show a neighbouring unit. That is accepted.
  **Do NOT stop those bumps** to "fix" it: they keep the concurrency tokens
  valid. The `-pk` tie-break makes equal timestamps deterministic.
- Unit titles can contain maths. The dashboard loads no KaTeX and renders no
  node titles today. Render the title as
  `{{ unit.title|strip_math_delimiters }}` (`courses_extras`, as used by the
  lesson and editor `head_title`), with no KaTeX on the dashboard.
  `templates/core/home.html` loads only `i18n` today, so it must add
  `{% load courses_extras %}`. Without it the template raises
  `TemplateSyntaxError` for every user.
- The link URL is chosen by unit type: `courses:quiz_unit` when
  `unit.unit_type == ContentNode.UnitType.QUIZ`, `courses:lesson_unit`
  otherwise (no redirect round trip). Component 3 uses the same check. The
  editor template may reuse `_editor_page`'s existing `unit_is_quiz` key.
- Structure: the visible "Last edited" label sits **outside** the `<a>`. The
  link contains the unit title and the course title, so its accessible name
  reads "unit title, course title" and not a run-on including the label.
  The two titles need a separator a screen reader announces (block-level
  children or a visually hidden ", "). The builder picks which, but one must
  exist.
- **Tap target: the whole card**, through a stretched link. The `<a>` wraps
  only the two titles, and its `::after` (`position: absolute; inset: 0` on a
  `position: relative` card) covers the card. So tapping anywhere, the label
  included, follows the link, while the label stays outside the anchor in the
  DOM. The e2e taps the **label area** to prove it. Keyboard focus is shown
  on the whole card (e.g. `:focus-within` on the card, or the outline on the
  `::after`), and the card must not clip it (no `overflow: hidden` that cuts
  the ring).
- **Position:** the card's first child after the Studio panel's
  `<h2 class="dash-panel__title">`, before the course list. Studio comes after
  "My learning" and "Teaching" in `home.html`, so on a phone the card can sit
  below the fold for a user who also has those panels. That is accepted. The
  panel order does not change (Claude's call C6).
- Styling: within the existing dashboard visual language (tokens from
  `app.css`), light and dark mode, phone width with no horizontal scroll. The
  exact markup and CSS are the builder's.

### Component 3 — "View live" link (unit editor)

`templates/courses/manage/editor/editor.html`, the `editor-crumb` row (next to
the "Media library" link is the natural spot; exact placement is the
builder's). An `<a>` to the unit's live page (see the URL rule below), with
`target="_blank" rel="noopener"` and the
visually hidden "(opens in a new tab)" suffix, mirroring
`templates/courses/_unit_strip.html`.

- Rendered only when `can_access_course(request.user, course)` is true (C4).
  A Platform Admin holding `courses.change_course` who is neither `is_staff`
  nor the owner can open the editor, but `lesson_unit` would 403 them. **Do
  not widen the read gate** to make the link work for them.
- The flag (`can_view_live`) is computed **inside `_editor_page`**
  (`courses/views_manage.py`, around line 2178), in its context dict next to
  `"course": unit.course`. It must not go in only one caller. `_editor_page`
  has three callers: the editor GET (~`:2236`) and two 422 error re-renders,
  `node_rename`'s `to_editor` `ValidationError` path (~`:975`) and
  `_flag_error` reached by `node_flag` with `ctx="editor"` (~`:1343`). A flag set only
  at the GET call site would silently drop the link on every error re-render.
- The link's URL is chosen by unit type: `courses:quiz_unit` for a quiz,
  `courses:lesson_unit` otherwise. That saves a redirect round trip on a
  phone.
- An icon is optional; if used, a monochrome inline SVG with `currentColor`,
  never an emoji.

## Data flow

- Dashboard GET → `home` computes `owned_courses` (existing) plus
  `last_edited_unit` (new, Component 2) → template renders the card and the
  per-course "View" actions → the author taps → existing `lesson_unit` /
  `quiz_unit` / `course_outline` views apply their existing gates.
- Editor render (GET or a 422 re-render) → `_editor_page` adds
  `can_view_live` (`can_access_course`) →
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
It does exist: `msgid "View"` → `msgstr "Widok"` (a noun, the editor's
view-toggle caption, `editor.html:137`), which does not fit a row action. The
Studio action **must** use `{% translate "View" context "…" %}` (or
`pgettext`) with its own PL verb form.

## Testing

Server-rendered; Django view and template tests are the main layer, plus one
e2e check for the property only a browser can see.

- **Where:** extend `tests/test_dashboard_panels.py` for the Studio and card
  tests, so they sit with the existing Studio assertions (`:70-72`). Editor
  tests sit with the existing editor or `test_unit_edit_link.py` tests.
- **Dashboard GETs by a `make_pa` user** must call
  `core.services.mark_onboarded()` first, as `test_dashboard_panels.py:85-88`
  does. Otherwise `home` 302s to `institution:setup` and a "not in content"
  assertion passes vacuously. Every dashboard test asserts status 200, and
  every negative assertion is paired with a positive one on the same response.
- **Timestamps:** `ContentNode.updated` is `auto_now`, so `save()` overwrites
  any value set by a test. Pin timestamps with
  `ContentNode.objects.filter(pk=...).update(updated=...)`. For the "later
  wins" test, give the **lower-pk** unit the later timestamp, so it fails if
  `-updated` is dropped and only `-pk` remains. For the tie-break test, set
  both rows to the same value. The mutant it must catch is `-pk` flipped to
  `pk`. A fully dropped tie-break leaves Postgres order undefined, so do not
  claim the test catches that.
- **Studio "View":** the owner's dashboard row has a link to that course's
  `course_outline`; following it returns 200; the title still links to the
  builder. Check each anchor of the row separately, not substrings anywhere in
  the body: parse the `data-section="manage"` `li.dash-row` and assert that
  the title `<a>` → `manage_builder` and the `.dash-row__action` `<a>` →
  `course_outline`. A swap or a duplicate must fail.
- **Last edited:**
  - With two owned units, the one with the later `updated` is shown, and its
    link is that unit's `lesson_unit` URL.
  - A **draft** unit can be the one shown, and following its link returns 200
    for the owner.
  - The tie-break: equal `updated`, so the higher pk wins.
  - A unit in a course owned by someone else, updated later, is **not** shown,
    including for a Platform Admin (`make_pa`) who owns a course of their own.
  - A user with no owned units sees no card.
  - Containers are never shown: an owned section/chapter whose `updated` is
    pinned later than the owned unit's leaves the card on the unit (catches a
    dropped `kind=UNIT` filter, whose card would link to a 404).
  - A unit titled with inline maths (e.g. `Pole \(x^2\)`) shows on the card
    without the `\(` `\)` delimiters, **and** the stripped text (`Pole x^2`)
    is present inside the card.
  - A quiz unit's card links to `quiz_unit`, a lesson's to `lesson_unit`.
  - The Platform Admin case shows the PA's own owned unit (positive) and not
    the other author's later-updated unit (negative).
- **Editor "View live":**
  - The owner sees, for a lesson unit, the link to its `lesson_unit` URL, with
    `target="_blank"`; following it returns 200 (a draft included).
  - A non-staff, non-owner Platform Admin can open the editor (200) but gets
    **no** "View live" link. On the same response, assert an editor marker
    is present (e.g. the crumb's "Media library" link) and that both the
    unit's live URL and the "View live" text are absent.
  - The link is still present on a 422 error re-render of the editor page:
    a `node_rename` POST with `node`, `ctx=editor`, the **current** token
    (`token=<unit.updated.isoformat()>` read from the DB row, since a stale or
    missing token raises `ConflictError` and 302s before validation runs) and
    a value that fails validation (the
    builder picks a concrete failing value from `node_rename`'s
    `ValidationError` sources). Assert status 422 **and** the link.
  - A quiz unit's link targets `quiz_unit`.
- **e2e (one test):** at a 360px-wide viewport, the owner's dashboard with a
  long unbroken unit title on the "Last edited" card and a long course title in
  a Studio row (the long-titled unit **belongs to** the long-titled course, so
  one fixture covers the row, the card's unit title and the card's course
  title) has `document.documentElement.scrollWidth <= clientWidth`.
  The e2e unit is a **draft**, matching the triggering case. Tapping the card
  lands on the unit's live page. Prove the landing by waiting for **both** the
  unit title heading and the draft banner, never `to_have_url` alone, which
  passes at navigation start. Also take light and dark screenshots of the
  Studio panel (including a keyboard-focused card) and the editor crumb, and
  check them by eye.
- Test fixtures: use `make_pa` / `make_verified_user` / `make_login` from
  `tests/factories.py`. Never use `UserFactory` + `force_login` (the password
  is never persisted, so the client is silently anonymous).
- Each new assertion must be shown to fail on a mutant (e.g. drop the
  `owner` filter, drop the `kind=UNIT` filter, drop the `can_access_course`
  guard, flip the ordering).
- Test runs stay narrow per task. One branch-level run at the end.
