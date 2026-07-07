# Tags & notes hub

*Design spec — 2026-07-07. Post-v1 roadmap slice: the deferred **notes index page
(revision navigation)** from Phase 4, reframed (per user direction) as a unified
**"Tags & notes" hub** that also folds in the existing "My tags" surface.*

Companion memory: `phase-4a-notes-status`, `phase-4b-tags-status`. Roadmap:
`docs/roadmap.md` Phase 4 ("Deferred: the notes *index* page (revision navigation)").

---

## Purpose

A student who is revising wants to find and revisit their own annotations. Today:

- **Notes** (Phase 4a) are per-block, private, plain-text; reachable only from within a
  lesson (floating panel) or via the outline's per-lesson note-count badge. There is **no
  place to see notes across a course** — the deferred "notes index page".
- **Tags** (Phase 4b) already have a cross-course page, **"My tags"** (`tags:my_tags`),
  organized *by tag* (units grouped under each tag chip) plus tag management
  (rename / recolor / delete).

Notes and tags are used similarly ("my private study aids"), and a student **revises one
subject at a time**. So instead of a standalone notes index, we build one **"Tags &
notes" hub** with two tabs, plus a **per-course notes view** that is the actual revision
surface.

### Goals

1. A single top-nav entry, **"Tags & notes"**, replacing the current **"My tags"** link.
2. A hub with two tabs:
   - **By course** (default) — an organized launcher: one card per course the student has
     notes *or* tags in, linking into per-course revision.
   - **Manage tags** — the existing "My tags" page, essentially unchanged, moved under
     this tab (it stays where cross-course tag management lives).
3. A **per-course notes view** — all the student's notes in one course, in outline order,
   read-and-jump, the surface you actually revise from.
4. Reach the per-course notes view from (a) its hub card and (b) a **"My notes"** link in
   the course outline header. The existing per-lesson note-count badges keep working.

### Non-goals (YAGNI — explicitly out of scope)

- **No search / filter** on either surface (personal note volumes are low; easy to add
  later).
- **No inline note editing on the index** — notes are read-only there; editing stays
  in-context on the lesson, reusing the existing floating-panel CRUD.
- No "recent notes" strip, no dashboard tile, no notes-by-tag cross-referencing.
- **No change to tag management** behavior (rename / recolor / delete) — the "Manage
  tags" tab is the existing page plus a tab bar.
- **No notes on quizzes** — notes remain lesson-only by the existing 4a design; the
  per-course view lists only lesson-unit notes.
- No new model, **no migration** — this slice is read/aggregate + templates over the
  existing `Note` / `Tag` / `UnitTag` schema.

---

## Architecture / components

Three surfaces, all **student-facing, author-scoped, accessible-course-scoped**, riding
the existing `notes` and `tags` apps. No new app.

### 1. The hub tab bar (shared, app-neutral)

Two **linked pages** sharing a tab bar (not client-side tab switching), mirroring the
established pattern in `templates/accounts/manage/_tabs.html`
(`<nav class="manage__tabs"><a class="manage__tab is-on">…`).

- New partial **`templates/_tags_notes_tabs.html`** (root templates dir, app-neutral so
  neither app "owns" the other's tab). Renders two links:
  - **By course** → `notes:overview`
  - **Manage tags** → `tags:my_tags`
- Active tab chosen by a context variable **`hub_tab`** (`"by_course"` | `"manage_tags"`),
  set by whichever view renders. Its own bespoke classes (`tnhub__tabs` / `tnhub__tab`) so
  it doesn't inherit unrelated `manage__*` layout; styling mirrors the manage tab bar.

### 2. "By course" overview page — `notes:overview`

- **Route:** `path("tags-and-notes/", views.overview, name="overview")` in `notes/urls.py`
  (both `notes.urls` and `tags.urls` mount at `""`, so `/tags-and-notes/` is a free
  top-level path). `@login_required`.
- **View (`notes/views.py::overview`)** aggregates, per accessible course, the note count
  and the tag set, then renders `notes/overview.html` with `hub_tab="by_course"`.
- **Card per course** the student has ≥1 note **or** ≥1 tag in:
  - Course **title** → course outline (`courses:course_outline`, the existing student
    outline route).
  - **Notes (N)** → `notes:course_notes` for that course — **rendered only when N > 0**.
  - **Tag chips** (the distinct tags used on that course's units) → each chip links to
    `courses:course_outline` for that course with a **single `?tags=<pk>`** query param (no
    toggle/active state — this is a plain hand-built href, **not** a call to
    `tags.services.filter_chip_hrefs`, which builds toggle hrefs over an active set for the
    outline's own in-page filter).
- **Order:** cards sorted **alphabetically by course title** (stable; matches the existing
  `units_by_tag` course ordering).
- **Empty state:** if the student has no notes and no tags anywhere → a friendly "You
  haven't added any notes or tags yet" message pointing back to their courses.

### 3. Per-course notes view — `notes:course_notes`

- **Route:** `path("courses/<slug:slug>/notes/", views.course_notes, name="course_notes")`
  in `notes/urls.py`. `@login_required`.
- **Access gate** mirrors the student per-course results page
  (`courses:course_results`): resolve the course by slug (`get_object_or_404(Course,
  slug=slug)` → **404** if no such course), then `can_access_course(user, course)` else
  `PermissionDenied` (**403**). So a nonexistent slug 404s and an inaccessible course 403s.
- **Content:** the author's notes in this course, **grouped by lesson unit in outline
  order**; within a unit, note groups ordered by **`Element.order`** (the block's outline
  position within the unit — an explicit `OrderField`, distinct from `pk` and stable under
  block reorder; `courses/models.py` `Element.Meta.ordering = ["order", "pk"]`), with the
  **unanchored ("General") bucket last** for notes whose block was deleted
  (`element_id is None`). Within a single block, notes are ordered `created, pk` (matching
  `notes_for_unit`). Units with zero notes are omitted.
  - Each note renders its **full body** (a reading surface) with the lesson panel's
    **6-line clamp + "Show more"/"Show less"** look. Note that `notes.js`'s
    `setupClamp(scope)` is a helper invoked only from **panel-scoped call sites** (panel
    `toggle`, the post-add/post-edit fragment swaps, and an on-load pass over already-open
    panels), so it never runs on a standalone page whose note cards sit **outside** any
    `.block-notes__panel` — it will **not** auto-activate here. The implementer must budget an
    explicit JS change: either expose / add a global `setupClamp(document)` init in
    `notes.js`, or add a small page-scoped init in `notes/course_notes.html` that measures
    each `.note-card__body` and injects the toggle. **Prerequisites** (today these live only
    in `lesson_unit.html`): `course_notes.html` must link **`notes/css/notes.css`** (defines
    `.note-card__body--clamp` / `.note-card__more`; the clamp is inert without it) and must
    **source the localized "Show more"/"Show less" labels** — either render the `#notes-i18n`
    data element (required if the global-`setupClamp` route is taken, since it reads its
    labels from module-level `I18N` populated from `#notes-i18n`; without it the toggle
    silently falls back to English and fails the PL i18n DoD) or, for the page-scoped-init
    route, emit the labels via `{% trans 'Show more' %}` / `{% trans 'Show less' %}`. The
    **global-init route additionally requires the `notes.js` `<script>` tag** on
    `course_notes.html` (today it lives only in `lesson_unit.html`; without it a global
    init in `notes.js` never runs and the clamp is silently inert). Each
    note also shows a subtle **"updated" date** (see below) and a **"Go to lesson"** link →
    `{lesson_url}?notes=1#note-<pk>` (the existing anchor the lesson page already honors —
    `?notes=1` auto-expands annotated blocks and `#note-<pk>` scrolls to the note).
  - **Read-only here** (no edit/delete controls). The per-course view uses a **new
    read-only card partial** (e.g. `notes/_readonly_note_card.html`) that reuses only the
    existing CSS class vocabulary (`.note-card`, `.note-card__body`, …) — it does **not**
    include the existing `notes/_note_card.html`, which hardcodes edit/delete action links
    (`_note_card.html`) and would violate the read-only non-goal. The new partial renders
    the body + the **"updated" date** + "Go to lesson" link in place of those actions. The
    date **reuses the existing relative rendering**: copy the `edited/added … ago` markup
    from `_note_card.html` — the `{% if note|note_edited %}…{% else %}…{% endif %}`
    `blocktrans` block with `note.updated|timesince` — into the new partial. (`note_edited`
    is only a boolean predicate that selects edited-vs-added; the actual localized string
    lives in the template, so it must be replicated, not obtained from the filter.) This
    keeps it reading identically to the lesson panel rather than inventing an absolute
    format.
- **Header:** course title + a **link back to the hub** — specifically `notes:overview`
  (the "By course" tab the card was reached from); `hub_tab` is **not** set here (this is
  a course-scoped sub-page, not a hub tab).
- **Empty state:** "No notes in this course yet" pointing back to its lessons.

### 4. Entry points

- **Nav (`templates/base.html`):** rename the `"My tags"` link (currently → `tags:my_tags`)
  to **`"Tags & notes"`** → `notes:overview`. Same visibility as today (any authenticated
  user; no role gate — unchanged).
- **Course outline header:** add a **"My notes"** link → `notes:course_notes` for that
  course, alongside the existing "My results" affordance. The existing per-lesson
  note-count badges are untouched.

### Services (thin, choke-point style; no new model)

- **`notes/services.py`**
  - `course_notes(author, course)` → an **ordered** structure for the per-course view: a
    list of `{ "unit": <ContentNode>, "groups": [ (element_or_None, [Note, …]), … ] }`,
    units in outline (pre-order) position; **groups ordered by `Element.order`** (the
    `None`/unanchored bucket last), and notes within a block ordered `created, pk`; units
    with no notes omitted. Built from `courses.rollups.units_in_order(course)` (filtered to
    lesson units) + a single author-scoped `Note` query for the course
    (`select_related("element")`), grouped in Python — no N+1.
  - `note_counts_by_course(author)` → `{course_id: count}` over the author's notes in
    **accessible** courses only (`unit__course__in=accessible_courses(author)`, lesson
    units — reuses the existing `note_counts_for_outline` shape at course granularity).
- **`tags/services.py`**
  - `tags_by_course(author)` → `OrderedDict {Course: [Tag, …]}` — the distinct tags the
    author has used on each **accessible** course's units, courses keyed by object (the
    overview view merges by course). Mirrors `units_by_tag`'s accessible scoping and
    `Lower(name)` tag ordering; one `UnitTag` query with `select_related`.
- **`notes/views.py::overview`** composes `note_counts_by_course` (keyed by course id) +
  `tags_by_course` (keyed by `Course`) into the union of courses. To keep the "no N+1"
  guarantee, it resolves the notes-only course ids in **one batched query**
  (`Course.objects.in_bulk(union_of_ids)`) rather than fetching each `Course` per id, then
  sorts by title and builds the card list. Import direction is **one-way `notes` → `tags`**
  (tags never imports notes — no cycle).

### View / template placement

- `notes` app owns **`overview`** and **`course_notes`** views, `notes/urls.py` routes, and
  templates `notes/overview.html`, `notes/course_notes.html` (+ small partials, e.g.
  `notes/_overview_card.html`).
- `tags` app keeps **all** tag-management views/routes; `tags:my_tags` gains only
  `hub_tab="manage_tags"` in its render context (both the normal and the `tag_recolor`
  422-re-render paths) and includes the shared tab-bar partial in `my_tags.html`.
- Shared tab-bar partial at `templates/_tags_notes_tabs.html`.
- CSS: a small `notes.css` addition (or a shared stylesheet) for `.tnhub__*`, the overview
  cards, and the per-course notes list; reuse existing tag-chip and note-card vocabulary.

---

## Data flow

**Nav → hub (By course):**
`GET /tags-and-notes/` → `overview` → `note_counts_by_course(user)` +
`tags_by_course(user)` → union of accessible courses → sorted card list →
`notes/overview.html` (tab bar `is-on` = By course).

**Hub ↔ Manage tags:** the "Manage tags" tab links to the unchanged `tags:my_tags`
(`GET /tags/`, its existing route), which now renders the same tab bar with
`is-on` = Manage tags.

**By course → per-course notes:** a card's **Notes (N)** → `GET /courses/<slug>/notes/` →
`course_notes` → access gate → `services.course_notes(user, course)` → grouped, ordered
render.

**Per-course notes → lesson:** "Go to lesson" → `GET /courses/<slug>/u/<unit_pk>/…?notes=1
#note-<pk>` (existing lesson route) → lesson page auto-expands the annotated block and
scrolls to the note. This closes the revision loop (index → block → in-context edit).

**Tag chip → filtered outline:** a card's tag chip → the existing outline `?tags=<pk>`
filter (already implemented in `tags.services.outline_with_tags` / `filter_chip_hrefs`).

All queries are **author-scoped** (`author=request.user`) and **accessible-course-scoped**
(`accessible_courses(user)` — the single source of truth `can_access_course` delegates to),
so a lost-access course's notes/tags never appear and no other user's data is reachable.

---

## Error handling & security

- **`course_notes` gate order:** course-existence (404) **before** access (403), mirroring
  `courses:course_results`. A foreign/nonexistent slug 404s; an existing but inaccessible
  course 403s. No information leak about course existence beyond what the catalog already
  exposes.
- **Author scoping everywhere:** every `Note` / `Tag` / `UnitTag` query filters by
  `author=request.user`; the index surfaces can never show another user's annotations.
  (The per-course view reads notes only; there is no object-pk route to forge.)
- **Accessible-course scoping:** overview aggregation and `course_notes` both restrict to
  `accessible_courses(user)`. A note or tag on a course the student has lost access to is
  hidden and uncounted — consistent with the existing tags invariant
  (`tags.services._accessible_unit_count`, `list_tags`).
- **Empty / degenerate states:** no notes and no tags → overview empty state; a course with
  tags but zero notes → card shows chips, **no** Notes link; a course with notes all
  unanchored → per-course view shows only the "General" bucket per unit; a unit whose
  blocks were all deleted → its notes appear under "General".
- **No new writes** → no new validation, CSRF, or integrity surface; the existing note/tag
  mutation endpoints are untouched.
- **`?notes=1#note-<pk>` robustness:** if the anchored block was since deleted, the lesson
  page still loads (the anchor simply doesn't resolve) — the same graceful behavior the
  existing outline badge + note-edit redirect already rely on.

---

## Testing

Reuse the established libli harness: `make_verified_user` / `make_login` (plain
`UserFactory` can't log in — unverified email), real-PostgreSQL pytest, `factory_boy`
factories (`NoteFactory`, tag factories, `ContentNodeFactory`, `EnrollmentFactory`).

**Unit / view tests (`tests/…` mirroring `test_notes_views.py` / tags tests):**

- **Overview aggregation:** a student with (a) notes-only course, (b) tags-only course,
  (c) both, (d) neither → exactly the union {a,b,c} appears, sorted alphabetically by
  title; each card's note count is correct; **Notes link present iff count > 0**; tag chips
  match the course's used tags **and each chip's href is exactly `course_outline?tags=<pk>`**.
- **Overview scoping:** a note/tag on a course the student lost access to (dropped
  enrollment, not owner, not staff) is **absent** from the overview.
- **Overview empty state:** a student with no notes and no tags renders the empty message,
  no cards.
- **`course_notes` ordering:** notes across multiple units render in outline (pre-order)
  position; within a unit, groups in `Element.order` (block) order — assert this stays
  correct **after a block reorder** (so an `element_id`/`pk` sort would fail); **two notes
  on one block** render in `created, pk` order; the unanchored bucket renders **last**;
  units with no notes are omitted.
- **`course_notes` empty state:** an accessible course with zero notes (reached via the
  outline "My notes" link) → 200 with the empty-state message and no note cards.
- **`course_notes` access:** nonexistent slug → 404; existing-but-inaccessible course →
  403; accessible course → 200. Another user's notes never appear (author scoping).
- **`course_notes` jump-back:** each note's "Go to lesson" href is exactly
  `…?notes=1#note-<pk>`.
- **Tab state:** `notes:overview` marks "By course" active; `tags:my_tags` marks "Manage
  tags" active; both render the shared tab bar.

**E2E (Playwright, real gestures, DB-asserted — no `page.evaluate` shortcut, per
`e2e-must-drive-real-ui`):**

- Seed a student with a note on a lesson block in an enrolled course. Drive: nav **"Tags &
  notes"** → **By course** card → **Notes (N)** → per-course view shows the note → **"Go to
  lesson"** lands on the lesson with the block expanded and the note visible. Assert against
  the DB / rendered note body, not a JS shortcut.
- **Standalone clamp activation** (the one genuinely new/risky behavior — browser needed to
  measure overflow): seed a **long** note, load the per-course page, and assert the
  `.note-card__more` toggle is present and actually collapses/expands `.note-card__body`
  (proving the explicit JS init is wired and `notes.js`/`notes.css` are loaded). Run once
  under Polish to assert the toggle label is localized (guards the `#notes-i18n` /
  `{% trans %}` i18n path).

**i18n gate:** all new strings ("Tags & notes", "By course", "Manage tags", "My notes",
"No notes in this course yet", the empty-overview message, etc.) added to EN + real Polish;
the PL catalog stays **0 fuzzy / 0 obsolete** (watch `makemessages`' known mis-guessed
fuzzies — see `phase-4a-notes-status`); if renaming the nav link orphans the old `"My
tags"` msgid, reconcile the catalog (keep it if `my_tags.html`'s heading still uses it,
else remove the obsolete entry).

**DoD (per the libli rhythm):** `uv run pytest -m "not e2e"` green + notes/tags e2e green;
`uv run ruff check` + `uv run ruff format --check` clean; `manage.py makemigrations --check`
= no changes (no model touched); `manage.py check` clean; `compilemessages -l pl` + catalog
0-fuzzy/0-obsolete.
