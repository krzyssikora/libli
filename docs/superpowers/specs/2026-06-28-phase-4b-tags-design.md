# Phase 4b — Personal Tags (design)

*Brainstormed 2026-06-28. Visual decisions (the three UI surfaces) validated with the
brainstorming visual companion; the chosen mockups are archived under
[`docs/mockups/phase-4b-tags-*.html`](../../mockups/).*

Phase 4 ("Notes & tags") was split into two independent slices in the 4a spec:
**4a — Notes** (shipped, PR #53) and **4b — Tags** (this spec). They share no data and
no UI; splitting keeps each PR focused, matching every prior phase. This spec covers
**4b only**.

---

## 1. Goal

A user (any user who can access a unit — the same gate as the consumption page) can
attach private, reusable **tags** to **units**, see and edit a unit's tags while reading
it, **filter a course's outline** by tag, and browse **all** their tagged units across
courses from a single **"My tags"** page where tags are also renamed, recoloured, and
deleted. Tags are personal: each user sees only their own.

The original vision (`differences.md` §"Per user tags"): add tags to a unit; remove a
tag from a unit; remove a tag *entirely* (incl. when unassigned); and **filter units by
tags**.

---

## 2. Scope

**In scope**
- Per-user, reusable, **named** tags (a `Tag` entity, not a free-text-per-unit label).
- Tag / untag any **unit** — **lessons and quizzes** (tags are metadata only; they never
  render unit *content*, so the quiz-consumption fragility that limited 4a notes to
  lessons does **not** apply here).
- Add / remove a unit's tags from **two** surfaces: the **unit consumption page** and the
  **course outline**.
- **Filter** the course outline by tag (OR semantics across multiple selected tags).
- A cross-course **"My tags"** page: browse units grouped by tag, and **manage** tags
  (rename, recolour, **delete entirely** — anytime, with a confirm when still assigned).
- Per-tag **colour**, chosen from a fixed light/dark-safe palette.
- Full no-JS CRUD + filtering; autocomplete / in-place editing as JS enhancement.

**Out of scope / deferred**
- **Tagging blocks / `Element`s** — tags are **unit-level** only (notes already cover
  per-block annotation; the M2M target is `ContentNode`, so a finer anchor would be a new
  model, not an extension).
- **Tagging whole courses** (e.g. catalog "favourites") — a second target type; deferred.
- **Sharing / visibility of tags between users** — tags are strictly private.
- **Free hex colours, tag hierarchy/nesting, bulk tagging, tag descriptions** — YAGNI.
- **A global tag-driven revision/study mode** beyond the "My tags" browse page.

---

## 3. Decisions (and why)

| Decision | Choice | Rationale |
|---|---|---|
| Decomposition | 4b Tags now, separate from 4a Notes | Independent features; focused PRs; already declared independent in the 4a spec. |
| Tag entity | **Reusable named `Tag` per user** + M2M to units | The vision needs "remove a tag *not assigned to any unit*" ⇒ tags exist independently of assignments; enables filtering and cross-course reuse. |
| Tag target | **Any unit (lesson + quiz)** | Tags are label-only; the quiz-render fragility that limited notes doesn't apply. Closest to the literal "tag a unit". |
| Edit surfaces | **Unit page + outline** | Two natural moments: "tag while reading" and "tag while scanning the list". |
| Filter surfaces | **Per-course outline + cross-course "My tags" page** | Outline = "filter within this course"; My tags = "show everything I flagged" for revision. |
| Multi-tag filter | **OR** (a unit shows if it has *any* selected tag) | Best for "show everything flagged X or Y"; the common revision case. |
| Non-matching units when filtering | **Hide them; drop now-empty parts/chapters** | A punchy flagged-only list; chosen over dim-in-place during brainstorming. |
| Colour | **Fixed palette key, auto-assigned on create, user-editable** | Light/dark-safe (token-mapped, not free hex); quick-tagging never blocks on a colour pick, yet the user *can* choose later. |
| Name identity | **Case-insensitively unique per author**, display case preserved | "Exam"/"exam" are the same tag; reuse-by-typing never duplicates. |
| Delete-tag-entirely | **Anytime, with a confirm warning "removes it from N units"** | One consistent delete path; matches the vision's "remove entirely" without forcing manual pre-unassign. |
| Lost-access assignments | **Persist in DB, hidden + uncounted on all surfaces** | Can't navigate there anyway; mirrors 4a dormant-retention; never silently deletes user data. |
| One markup, responsive | **Accordion base → desktop two-pane (My tags); CSS restyle (outline/unit)** | No dual render (the 4a §6.4 hard rule); no duplicate ids/forms. |

---

## 4. Data model

A new Django app, **`tags`** (parallels `notes`/`grouping` — its own models, services,
views, templates, migration).

### `Tag`

| Field | Type | Notes |
|---|---|---|
| `author` | FK → `accounts.User`, `on_delete=CASCADE`, `related_name="tags"` | Owner; tags are private. |
| `name` | `CharField(max_length=50)` | Display label. **Normalized** before save: strip ends, collapse interior runs of whitespace to a single space (`" ".join(value.split())`), reject empty. **Case-insensitively unique per author** (see constraint). Display case preserved as entered. |
| `color` | `CharField(max_length=20, choices=TAG_PALETTE)` | A **palette key** (not a hex), mapped to a token-based, light/dark-safe colour in CSS. Auto-assigned on create from the palette by a **process-stable** hash of the normalized name (e.g. `zlib.crc32(name.encode()) % TAG_PALETTE_SIZE` — **not** Python's built-in `hash()`, which is salted per process via `PYTHONHASHSEED` and would vary across restarts and break any colour-pinning test) so a freshly typed tag gets a **stable, non-blocking default** colour with no pick; user-editable via §7.3. Palette collisions (two tags sharing a colour) are acceptable — colour is never load-bearing (§9). |
| `created` | `DateTimeField(auto_now_add=True)` | |

- `Meta.ordering = [Lower("name"), "pk"]` (**case-insensitive** alphabetical display, so
  "apple" and "Zebra" sort naturally rather than all-uppercase-first; use a `Lower`
  expression in `ordering` or an equivalent annotation). **Locale-aware collation** (e.g.
  Polish ł/ż order) remains a parked follow-up — see §10, mirroring the Phase 5a subjects
  ordering work.
- **Uniqueness:** a `UniqueConstraint(author, Lower("name"))` (functional index) so two
  tags can't differ only by case. The **service** normalizes + lower-compares before
  insert so the user gets a clean "reuse existing" path rather than an `IntegrityError`;
  the DB constraint is the backstop. The `TAG_NAME_MAX_LEN = 50` cap is enforced
  **identically** in the form `clean_name`, the service `_clean_name`, and the model
  field `max_length` (form/service are authoritative for friendly errors; the field cap
  backs `full_clean`).

### `UnitTag` (the M2M through-row = "this tag is on this unit")

| Field | Type | Notes |
|---|---|---|
| `tag` | FK → `Tag`, `on_delete=CASCADE`, `related_name="unit_tags"` | Deleting a tag cascades its assignments. |
| `unit` | FK → `courses.ContentNode`, `on_delete=CASCADE`, `related_name="unit_tags"`, `limit_choices_to={"kind": "unit"}` | The tagged unit (lesson **or** quiz). Course/unit deletion cascades the row away (acceptable — the page is gone). |
| `created` | `DateTimeField(auto_now_add=True)` | |

- `Meta`: `UniqueConstraint(tag, unit)` (idempotent tagging — a tag is on a unit at most
  once); `ordering = ["created", "pk"]`; indexes on `unit` (tags-for-unit render) and
  `tag` (units-for-tag on the My tags page).
- **Author is derived** via `tag.author` — **not** duplicated on `UnitTag`. Every
  unit-scoped query joins `tag__author=user`. (Storing author on both rows invites drift;
  the join is cheap and indexed.)
- `Tag.units = ManyToManyField(ContentNode, through="UnitTag", related_name="tags")` for
  convenient traversal; all **writes** go through the service, never `.add()`/`.set()`.

**Invariants**
- A `UnitTag.unit` is always `kind="unit"` (enforced at the view via
  `get_node_or_404(..., require_unit=True)` — both lesson and quiz pass; no
  `require_lesson`).
- `(tag, unit)` uniqueness makes `tag_unit` idempotent (re-tagging is a no-op, never a
  duplicate or an error).

### Palette

`TAG_PALETTE` — a fixed **list of ~8 named keys** (e.g. `teal, amber, indigo, rose,
green, violet, slate, cyan`) defined once in `tags/models.py`, each mapped in `tags.css`
to a foreground/background pair built from existing design tokens so every swatch is
legible in **light and dark**. `TAG_PALETTE_SIZE = len(TAG_PALETTE)`. The field sets
`choices=[(k, k) for k in TAG_PALETTE]` (Django `choices` requires 2-tuples — a bare-string
list fails the model system check), and the default-colour hash indexes the key list
directly: `TAG_PALETTE[zlib.crc32(name.encode()) % TAG_PALETTE_SIZE]`.

---

## 5. Services (`tags/services.py`)

The single choke point for all tag mutation and querying (mirrors
`notes/services.py` / `grouping/services.py`). **Unit resolution and course-access gating
live in the view** (§8): the unit-scoped operations (`tag_unit` / `tag_unit_by_id` /
`untag_unit`) receive an already-resolved, already-gated `unit` object. **Tag resolution is
service-level** — every `tag_pk`-keyed operation does its own author-scoped
`get_object_or_404(Tag, pk=tag_pk, author=author)` (this *is* the 404/no-leak guarantee,
mirroring `notes` `update_note`/`delete_note`); the view does **not** double-resolve the
tag.

**Name normalization** — `_clean_name(raw) -> str`: `" ".join((raw or "").split())`;
reject empty; reject `len > TAG_NAME_MAX_LEN`. Used by create and rename so they can't
drift.

- `tag_unit(author, unit, name) -> UnitTag` — **reuse-or-create** the tag, then create the
  link. Because uniqueness is **functional** (`Lower(name)`), tag reuse is **not** a literal
  `get_or_create` on `name` — Django's `get_or_create` matches the *exact* value, so its
  create branch would try to insert a case-variant ("exam" vs an existing "Exam") and hit the
  `Lower(name)` constraint. Instead:
  `tag = Tag.objects.filter(author=author, name__iexact=normalized).first()`, and if `None`,
  `Tag.objects.create(...)` with a default colour — wrapped so an `IntegrityError` from the
  `Lower(name)` constraint (a concurrent insert) **re-queries `name__iexact` and reuses that
  row**. Then the **idempotent** `get_or_create(UnitTag, tag=tag, unit=unit)` (which *does*
  have a real exact-field unique). Returns the (possibly pre-existing) row. Receives a
  validated `kind="unit"` `unit`.
- `tag_unit_by_id(author, unit, tag_pk) -> UnitTag` — the **existing-tag (picker) path**:
  resolve the author-owned tag (service-level `get_object_or_404(Tag, pk=tag_pk,
  author=author)`; a foreign/invalid `tag_pk` ⇒ **404**), then the same **idempotent**
  `get_or_create(UnitTag, tag=tag, unit=unit)`. The `tag_add` view dispatches to
  `tag_unit` when a typed **name** is supplied and to `tag_unit_by_id` when a **`tag_pk`**
  is supplied (§6 / §8).
- `untag_unit(author, unit, tag_pk) -> None` — resolve the author-owned tag (service-level
  `get_object_or_404(Tag, pk=tag_pk, author=author)`; a foreign/unknown `tag_pk` ⇒ **404**,
  consistent with every other `tag_pk` op), then delete the `(tag, unit)` `UnitTag`
  **idempotently** (if it isn't there — e.g. a double-submit — it's a harmless no-op, not an
  error). Removing the **last** assignment leaves the `Tag` existing-but-unused (never
  auto-deleted — the vision requires manual "remove entirely").
- `rename_tag(author, tag_pk, name) -> Tag` — author-scoped; normalizes; on a
  case-insensitive **collision with another of the author's tags**, raise a friendly
  validation error (the view surfaces it; we do **not** silently merge tags this slice).
  Rename **preserves the tag's current colour** — it never re-hashes the new name (the
  hash-default colour applies only at first creation, §4). Like create, the UPDATE is wrapped
  so a concurrent same-author rename racing into the same name (passing the app-level check
  yet violating the `Lower(name)` constraint) is caught as an `IntegrityError` and surfaced
  as the **same** friendly collision error — never an unhandled 500.
- `recolor_tag(author, tag_pk, color) -> Tag` — author-scoped; `color` must be a valid
  `TAG_PALETTE` key — an absent/invalid key (only reachable via a crafted POST; the swatch
  picker only offers valid keys) is rejected as a **422** with **no mutation**.
- `delete_tag(author, tag_pk) -> int` — author-scoped; deletes the `Tag` (cascading
  **all** its `UnitTag`s, including any hidden lost-access rows); returns the **accessible**
  assignment count — the same accessible `unit_count` the user saw on the My tags page (see
  `list_tags`), **not** the raw cascade total — for the confirm message / flash, so the UI
  never cites units the user cannot see.
- `list_tags(author) -> [Tag]` — all the author's tags, ordered, **annotated with an
  accessible `unit_count`** — a `Count("unit_tags")` **filtered to
  `unit_tags__unit__course__in=accessible_courses(author)`** (a conditional/filtered
  aggregate) — so the count matches the units actually rendered and **excludes lost-access
  assignments** (§3). "Unused"/the "(0)" purge case (§7.2) is defined strictly by this
  accessible count: a tag whose only assignments are inaccessible reads as `unit_count = 0`
  and is purgeable, never a non-zero count next to an empty unit list.
- `tags_for_unit(author, unit) -> [Tag]` — the author's tags on this unit, ordered, for
  the unit-page panel and the outline row chips.
- `tags_for_outline(author, course) -> ({unit_pk: [Tag]}, [Tag])` — one pass: a map of
  unit_pk → its tags (for row chips) **and** the sorted distinct set of tags the author
  uses **anywhere in this course** (for the filter bar). Restricted to
  `unit__course=course` and `tag__author=author`.
- `units_by_tag(author) -> [(Tag, {course: [unit]})]` — for the My tags page: each of the
  author's tags with its assigned units **grouped by course**, **filtered to courses the
  author can currently access** (§3 lost-access rule). Tags with zero *accessible* units
  still appear (so they can be purged). Access filtering uses a **new
  `courses.access.accessible_courses(user) -> QuerySet[Course]` helper added as part of
  4b** — there is currently only the per-course boolean `can_access_course`, no
  set-returning query. The helper must encode the **same union** that boolean does —
  `is_staff`/superuser ⇒ all courses, course owner ⇒ owned, otherwise ⇒ enrolled — as a
  single queryset, so the filter is `unit__course__in=accessible_courses(author)` rather
  than a per-unit Python loop. (`tags_for_outline` is already scoped to a course the view
  gated, so it needs no such filter.) **Display order:** the **outer tag list** follows
  `Tag.Meta.ordering` (`Lower(name)`, then pk — matching `list_tags`); courses by title
  (locale-aware where applicable, per §10's parked follow-up); units within each course by
  their **outline position** (tree order). So the page is fully stable and testable.

All mutators are **author-scoped**; a foreign `tag_pk` yields **404** (via the
service-level `get_object_or_404(Tag, pk=…, author=author)` above — including the
`untag_unit`/`tag_remove` path), never 403 — no existence leak. Unit-scoped
`tag_add`/`tag_remove` additionally resolve and access-gate the **unit** in the view (§8).

`tags/services.py` imports from `courses.models` / `courses.access` only (no
`courses.views`), so no import cycle.

---

## 6. Unit-page UX (consumption: lesson *and* quiz)

> Validated mockup: [`docs/mockups/phase-4b-tags-01-unit-tagbar.html`](../../mockups/phase-4b-tags-01-unit-tagbar.html).

- A quiet **"🏷 Tags (N)" toggle** sits by the unit title (N = the author's tag count on
  this unit; the glyph is monochrome/understated, in the spirit of 4a's notes icon).
  Clicking it expands a **tags panel**; the reading view stays clean when collapsed. **The
  toggle is always present** for an authenticated viewer — at N=0 it shows "Tags (0)" with
  the add control available, so the first tag can always be added.
- The panel shows the unit's tags as **chips** (name as text + palette colour), each with
  a **× remove** control, plus an **add** control:
  - **JS:** a text input that **autocompletes** from the author's existing tags
    (datalist or a small suggestion list); submitting a name not yet owned creates the
    tag (default colour) and tags the unit; submitting an existing name reuses it. Add /
    remove submit as **fragments** (`X-Requested-With: fetch` + CSRF, per the existing
    `_wants_fragment` pattern) and re-render the panel + the "(N)" count in place.
  - **No-JS:** the toggle is a native `<details>`. **Adding** uses one "Add" form (POST to
    `tag_add`) offering *either* a brand-new **name** (text input) *or* an **existing-tag
    picker** — a checklist/`<select>` of the author's tags **not already on this unit**
    (each option carries its `tag_pk`); the endpoint accepts whichever was supplied
    (`tag_unit` for a name, `tag_unit_by_id` for a `tag_pk`). **Removing** is **only** via a
    tiny per-chip `×` POST form (to `tag_remove`, body `tag_pk`) — there is **no**
    "uncheck-to-remove" reconciliation. So the no-JS model is unambiguous: an **add-only
    picker plus per-chip remove**, matching the split `tag_add`/`tag_remove` endpoints
    (§8). PRG on success (§8).
- **Both** the lesson template (`courses/lesson_unit.html`) and the **quiz** template get
  the panel via **one shared partial** (`tags/_unit_tag_panel.html`). The panel renders
  **unit-level metadata only** (no `Element` content), so it is safe on the quiz
  consumption path that bedevilled notes. Hosting both templates is the only `courses`
  template change on the consumption side.
- **One markup per chip/control** (no duplicate ids/`name=`s); desktop vs mobile is a
  pure CSS restyle.

---

## 7. Outline UX & "My tags" page

### 7.1 Outline filter + per-row editing

> Validated mockup: [`docs/mockups/phase-4b-tags-02-outline-filter.html`](../../mockups/phase-4b-tags-02-outline-filter.html).

- The **learner-facing course outline** (`course_outline` in `courses/views.py`) gains a
  **filter bar** above the tree: one chip per tag the author uses in this course, each a
  **single `<a>` GET link** with a pre-computed toggle href (see No-JS below). Chips
  **toggle** (the active set filters by **OR**); JS enhances the *same* links to filter in
  place (no element swap — §9). **When the author has no tags in this course the filter bar
  is omitted entirely** (not rendered as an empty bar).
- Each **unit row** shows its tag chips and an **✎ edit** affordance that opens the same
  add/remove editor as the unit page (shared partial; on no-JS the ✎ links to the unit page
  with **`?panel=tags`** — a **unit-page-only** flag, distinct from the outline's `?tags=`
  filter list — which the unit view consumes by rendering the panel `<details open>`).
- **Filtering behaviour (chosen):** non-matching **units are hidden**, and any
  part/chapter/section left with **no visible descendant unit collapses away**. **One shared
  DOM:** the server **always renders the full outline** — every unit carrying its tag ids as
  `data-*` — and *expresses* the filter by adding the **`hidden` attribute** to non-matching
  units (and to every container with no visible descendant unit), **never by omitting them**.
  `hidden` is honoured by browsers with **no JS** (`[hidden]{display:none}`), so the no-JS
  user gets the filtered view, **and** the JS path can both narrow **and broaden** against
  the complete DOM (e.g. a cold-loaded `?tags=5` URL can still OR-in another tag). The two
  paths share this single DOM and the same visibility rule (below).
  - **JS:** toggling a chip flips the `hidden` attribute on non-matching rows and
    re-evaluates ancestor visibility in place, with no round-trip; the active set is
    reflected in the URL (`?tags=…`, via `history.pushState` over the same `<a>` hrefs).
    **After each toggle the JS recomputes every chip's `href`** to encode the new active set,
    so a middle-click / open-in-new-tab (which uses the raw `href`, bypassing the handler)
    still lands on the correct set. A JS inline row edit (✎ add/remove) **under an active
    filter immediately re-runs the visibility rule** for that row and its ancestors — a unit
    that no longer matches becomes `hidden`, a newly-matching one un-hides — matching a
    server reload.
  - **No-JS:** the filter chips are GET links that set `?tags=<id>&tags=<id>`. Each chip's
    `href` encodes the current set **toggled for that chip** — an **inactive** chip's link
    **adds** its id to the current set; an **active** chip's link **omits its own** id
    (carrying the rest) — so a plain link both selects and deselects. The **view honours the
    param server-side** by emitting the full outline with the `hidden` attribute applied per
    the rule above — same result without JS. Unknown, foreign (not the author's), or
    out-of-course `tags` ids in
    the param are **silently dropped** — the effective filter is the intersection of the
    param with the author's in-course tag set — never a 404 or error (a stale/hand-edited
    URL just filters by whatever remains, and leaks nothing).
- **Visibility rule (governs both the JS and server paths).** **An empty selected set ⇒
  filtering is inactive: the full outline renders with every unit visible** (the default
  `?tags`-less view, and the case where every supplied id was dropped). When **≥1 valid
  tag** is selected, one **recursive rule** governs both paths so they can't diverge: **a
  unit is visible iff it has ≥1 selected tag; a container (section / chapter / part) is
  visible iff it has ≥1 visible *descendant* unit** — visibility bubbles up through every
  intermediate level, not just direct children.
- The existing **4a note-count badge** on the outline is untouched and coexists with the
  tag chips on the row.
- The **authoring/manage** outline is **not** touched (tags are personal to the reader).

### 7.2 "My tags" page (cross-course)

> Validated mockup: [`docs/mockups/phase-4b-tags-03-my-tags-page.html`](../../mockups/phase-4b-tags-03-my-tags-page.html).

- A new top-level page (`tags:my_tags`, linked from the main nav / user menu) lists **all**
  the author's tags with the units under each, **grouped by course**, each unit linking to
  its consumption page. Powered by `units_by_tag(author)` (accessible units only, §5).
- **One responsive markup, no dual render:** the base DOM is an **accordion** — a list of
  tag sections, each a native `<details>` holding its units (works on mobile and with no
  JS). On **desktop** (≥ a breakpoint), CSS + a light JS enhancement restyle the **same
  markup** into a **two-pane**: tag summaries become a left rail, the active tag's units
  fill the right pane, one tag open at a time. No second copy of any markup or form.
- Each tag header carries its **manage** controls (§7.3). The per-tag header count is
  `list_tags`' accessible `unit_count` (§5) — the **single source** shared with the
  delete-confirm count. An **unused** tag (accessible count 0) still appears so it can be
  deleted.

### 7.3 Tag management (rename / recolour / delete)

- **Rename:** inline (JS) or a tiny standalone GET form (no-JS), POST to `tag_rename`;
  a case-insensitive collision with another of the author's tags is a friendly field
  error (no silent merge this slice).
- **Recolour:** a small swatch picker (the fixed palette), POST to `tag_recolor`.
- **Delete entirely:** POST to `tag_delete`. When the tag is still on **N > 0** units, a
  **confirm** first — JS shows a small inline confirm; **no-JS** uses a tiny GET
  confirmation page ("Delete 'exam'? This removes it from N units.") → confirm POST — so a
  destructive action is never a single unguarded click (mirrors 4a's no-JS delete-confirm
  rule). Here **N is the accessible count from `list_tags`, computed *before* deletion**
  (§5); `delete_tag`'s return value is used **only** for the post-action flash. A tag whose
  only assignments are inaccessible reads as 0 accessible units and may skip straight to
  POST (still CSRF-guarded), as may any unused tag.
- All three are **author-scoped**, keyed by `tag_pk` only (no course path segment), no
  course-access gate; a foreign `tag_pk` → 404.

---

## 8. Architecture, URLs & integration

**New `tags` app**
- `models.py` (`Tag`, `UnitTag`, `TAG_PALETTE`), `services.py`, `forms.py`, `views.py`
  (tag/untag a unit + fragment renderers; rename/recolour/delete; my-tags page),
  `urls.py`, `templates/tags/` (unit panel, chip, outline filter bar + row chips, my-tags
  accordion/two-pane, manage forms, no-JS confirm), `static/tags/` (`tags.css`,
  `tags.js`), `migrations/0001_initial.py`, tests, factories.
- **Registration:** add `"tags"` to `INSTALLED_APPS`; wire URLs into the project URLconf.
  `0001_initial` declares `dependencies` on `courses` (the `ContentNode` FK) and the user
  model (`settings.AUTH_USER_MODEL`).

**URLs** — namespaced `tags:` routes:
- **Unit-scoped** (carry `<slug>`/`<node_pk>` so the view can reuse
  `get_node_or_404(node_pk, slug, require_unit=True)` + `can_access_course`):
  - `…/<slug>/u/<node_pk>/tags/add` (POST) — body carries **either** a new tag **name**
    (free-type) **or** an existing **`tag_pk`** (picker); the view dispatches to `tag_unit`
    or `tag_unit_by_id` accordingly. A `tag_pk` not owned by the author ⇒ **404** (no
    existence leak). **Dispatch precedence:** a non-empty `tag_pk` wins (→ `tag_unit_by_id`);
    else a non-empty `name` (→ `tag_unit`); a submission with **neither** (empty name, no
    selection) is a **422** field error, nothing created.
  - `…/<slug>/u/<node_pk>/tags/remove` (POST) — body carries `tag_pk`.
- **Tag-scoped, author-scoped** (keyed by `tag_pk` only, no course segment — decorative
  scope would have to be re-validated or be spoofable): `tag_rename` (GET no-JS form +
  POST), `tag_recolor` (POST), `tag_delete` (GET no-JS confirm + POST). Foreign
  `tag_pk` → 404.
- **`my_tags`** (GET) — the cross-course page.

**Gating order in `tag_add`/`tag_remove`** (matches the consumption view & 4a notes):
1. `unit = get_node_or_404(node_pk, slug, require_unit=True)` — 404s a nonexistent /
   non-unit / wrong-course node (a foreign node 404s **before** any 403).
2. `if not can_access_course(request.user, unit.course): raise PermissionDenied` (403).
3. Call the service with the resolved, gated `unit`.

**Integration points in `courses`** (small, additive)
- `course_outline` view: pass `tags_for_outline(request.user, course)` (the row-chip map +
  the filter-bar set) into context and honour `?tags=` server-side (no-JS filtering);
  include the filter-bar + row-chip partials. Coexists with the existing `note_counts`.
- Lesson **and** quiz consumption views: pass `tags_for_unit(request.user, unit)` into
  context; both templates include the shared `tags/_unit_tag_panel.html`. Lesson context
  flows through `full_lesson_render_context`, the single 4a context source; the **`quiz_unit`
  view** (`courses/views.py`) gets the analogous one-line addition —
  `tags_for_unit(request.user, unit)` into its context — and the quiz template includes the
  **same** shared `tags/_unit_tag_panel.html`. Name this quiz injection point in the plan so
  the known lesson/quiz consumption divergence doesn't leave the quiz seam vague.
- No changes to `Element` / `ContentNode` / the builder beyond reading existing rows and
  rendering the panel.

**No-JS success (PRG)** — a successful no-JS add/remove/rename/recolour/delete returns a
**302** (Post/Redirect/Get; refresh can't re-POST):
- unit-scoped add/remove → PRG back to the **unit page carrying `?panel=tags`** (the §7.1
  flag that renders the panel `<details open>`, so the panel reopens after the round-trip).
  The unit page is the **only** no-JS add/remove surface (the outline ✎ is a no-JS *link* to
  it, §7.1), so the redirect target is always this unit's own page — there is **no**
  `origin`/`next` parameter and thus **no open-redirect surface**. (The JS path edits inline
  via fragments and never navigates, so a filtered outline is never lost.)
- tag-scoped rename/recolour/delete → back to **`my_tags`** (the management surface).
- A validation failure (empty/over-long/duplicate name; an empty-both `tag_add`; an invalid
  palette key in `tag_recolor`, §5) re-renders the originating form with the rejected value
  + a field error, **HTTP 422**, nothing persisted (JS path returns the same as a fragment).

---

## 9. Cross-cutting requirements

- **i18n:** every user-facing string marked for translation with EN + PL catalogs
  (`.po`/`.mo`). Watch the known **fuzzy-flag** + mis-guess gotchas (grep new msgids,
  clear fuzzies, verify) and use `msgctxt` where a shared msgid needs divergent Polish
  (e.g. "Tags" the label vs. any verb). JS control labels (add/remove/confirm/show-more)
  read translated strings from a `#tags-i18n` `data-*` config element (the established
  pattern — see `notes.js` / `builder.html`), **not** hard-coded English.
- **Light/dark + responsive:** the palette swatches and all chrome use existing design
  **tokens**; no hard-coded colours that fail in dark mode (verify both themes via
  throwaway Playwright screenshots before shipping — the project's established practice).
  One markup restyled responsively on all three surfaces (no dual render).
- **Progressive enhancement:** tag/untag, filtering, and all management work with **no
  JS**; autocomplete, in-place fragment swaps, inline confirm, and the desktop two-pane
  are enhancement only.
- **Accessibility:** every icon-only control (🏷 toggle, × remove, ✎ edit, swatch picker,
  🗑 delete) carries a translatable `aria-label`; the "(N)" count is **textual**. Tag
  identity is **always the text name** — colour is never the sole signal (so colour-blind
  users and dark-mode contrast are never load-bearing). The filter chips are real
  focusable controls rendered as a **single markup**: `<a>` GET links with pre-computed
  toggle hrefs (§7.1) whose active state is conveyed via `aria-current` + a visually-hidden
  "active" label. JS **enhances the same links** (intercepts clicks to filter in place +
  `history.pushState`); it does **not** swap the element type or add `aria-pressed` (invalid
  on a link). This upholds the no-dual-render rule — one `<a>` markup, JS-enhanced, never a
  `<button>`/`<a>` fork.
- **Security/privacy:** **all `tags:` views require an authenticated user** (`@login_required`),
  so `author` is always a real `request.user` and an `AnonymousUser` never reaches a query or
  a `UnitTag` row; the unit-page panel and outline chips render **only** for authenticated
  viewers (the affordance is simply absent for anyone anonymous — and the consumption/outline
  pages are already `@login_required`). Unit-scoped tagging reuses the consumption gate (404
  for a nonexistent/non-unit node, 403 for an inaccessible course); tag-scoped management is
  author-scoped (foreign `tag_pk` → 404, no existence leak); tag names are **escaped on
  output** (plain text, never HTML). Lost-access assignments stay hidden + uncounted.
- **Testing:** pytest + factory_boy against PostgreSQL —
  - **service** unit tests: get-or-create reuse (case-insensitive, no duplicate),
    idempotent `tag_unit`, author-scoping (foreign `tag_pk` untouched), `untag_unit`
    leaves an unused tag, `rename` collision rejected, `delete_tag` cascades + returns
    count, name normalization + length cap, `tags_for_outline` returns only this author's
    in-course tags, `units_by_tag` excludes inaccessible courses but keeps zero-unit tags;
  - **view** tests: add/remove gate order (404 before 403; quiz unit **allowed**),
    `?tags=` server-side outline filter (incl. empty-ancestor pruning **and the empty/
    no-`?tags=` case rendering the full outline**), `tag_add` dispatch precedence + the
    empty-both 422, 422 validation re-render with repopulated value, foreign `tag_pk` → 404
    on add/remove/manage, anonymous user → login redirect, no-JS delete-confirm page;
  - at least one **e2e** driving the **real** gesture
    (tag a unit → filter the outline by it → untag → delete the tag), **no
    `page.evaluate` shortcuts** (the project's e2e bar — see the 4a notes e2e).

---

## 10. Risks, edge cases & parked follow-ups

| Item | Resolution |
|---|---|
| Case-only duplicate tags ("Exam"/"exam") | Service normalizes + case-folds; DB `UniqueConstraint(author, Lower(name))` backstops. |
| Tagging a unit you later lose access to | `UnitTag` persists; hidden + uncounted on every surface (you can't reach it). |
| Quiz consumption path fragility (the 4a foe) | Tag panel renders **unit-level metadata only**, no `Element` content — safe on quiz pages. |
| Outline filter pruning empty parts in two places (JS + server) | **Empty selected set ⇒ filtering inactive (full outline).** Otherwise one **recursive** rule (unit visible iff ≥1 selected tag; container visible iff ≥1 visible *descendant* unit — bubbles through all levels); both paths implement the same contract; tested server-side incl. a deep part→chapter→section→unit case. |
| No-JS round-trips for every edit | Acceptable (matches 4a notes); fragment/JS path is the fast path. |
| Tag-name **ordering is byte/Unicode, not locale-aware** | **Parked follow-up** (out of this slice), exactly as Phase 5a subjects deferred locale-aware ordering; note it in the ledger. |
| Renaming into a collision could "want" a merge | **Out of scope** — reject with a field error this slice; tag-merge is a future enhancement. |

---

## 11. Open details for the plan (non-blocking)

- Exact palette keys + their token mappings (the *rule* — fixed palette, default by name
  hash, user-editable — is decided in §4).
- Whether the outline `?tags=` param keys tags by **id** or a per-user **slug** (id is
  simpler and not user-meaningful-leaky since author-scoped; pick in the plan).
- Where exactly the **"My tags"** entry point sits in the nav (user menu vs. top-level),
  and whether it shows a global empty state when the user has no tags yet.
- Datalist vs. custom suggestion list for the add-input autocomplete (both are
  enhancement-only over the same no-JS input).
