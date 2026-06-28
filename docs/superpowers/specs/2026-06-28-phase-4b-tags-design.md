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
| `color` | `CharField(max_length=20, choices=TAG_PALETTE)` | A **palette key** (not a hex), mapped to a token-based, light/dark-safe colour in CSS. Auto-assigned on create from the palette **deterministically by name** (`hash(lower(name)) % len(palette)`) so a freshly typed tag gets a distinct colour with no pick; user-editable via §7.3. |
| `created` | `DateTimeField(auto_now_add=True)` | |

- `Meta.ordering = ["name", "pk"]` (alphabetical display; locale-aware ordering is a
  parked follow-up — see §10, mirroring the Phase 5a subjects ordering work).
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

`TAG_PALETTE` — a fixed list of ~**8** named keys (e.g. `teal, amber, indigo, rose,
green, violet, slate, cyan`) defined once in `tags/models.py`, each mapped in `tags.css`
to a foreground/background pair built from existing design tokens so every swatch is
legible in **light and dark**. `TAG_PALETTE_SIZE = len(TAG_PALETTE)`.

---

## 5. Services (`tags/services.py`)

The single choke point for all tag mutation and querying (mirrors
`notes/services.py` / `grouping/services.py`). **Resolution & HTTP gating live in the
view, not the service** (§8); services receive already-resolved, already-gated objects.

**Name normalization** — `_clean_name(raw) -> str`: `" ".join((raw or "").split())`;
reject empty; reject `len > TAG_NAME_MAX_LEN`. Used by create and rename so they can't
drift.

- `tag_unit(author, unit, name) -> UnitTag` — **get-or-create** the tag by normalized,
  case-folded name (reuse an existing tag, never duplicate; assign a default colour on
  first creation), then **idempotent** `get_or_create(UnitTag, tag=tag, unit=unit)`.
  Returns the (possibly pre-existing) row. Receives a validated `kind="unit"` `unit`.
- `untag_unit(author, unit, tag_pk) -> None` — author-scoped
  (`UnitTag.objects.filter(tag__pk=tag_pk, tag__author=author, unit=unit).delete()`).
  Removing the **last** assignment leaves the `Tag` existing-but-unused (never
  auto-deleted — the vision requires manual "remove entirely").
- `rename_tag(author, tag_pk, name) -> Tag` — author-scoped; normalizes; on a
  case-insensitive **collision with another of the author's tags**, raise a friendly
  validation error (the view surfaces it; we do **not** silently merge tags this slice).
- `recolor_tag(author, tag_pk, color) -> Tag` — author-scoped; `color` must be a valid
  palette key (else reject).
- `delete_tag(author, tag_pk) -> int` — author-scoped; deletes the `Tag` (cascading its
  `UnitTag`s); returns the count of assignments removed (for the confirm message / flash).
- `list_tags(author) -> [Tag]` — all the author's tags, ordered, **annotated with
  `unit_count`** (`Count("unit_tags")`) for the My tags list and the "(0)" purge case.
- `tags_for_unit(author, unit) -> [Tag]` — the author's tags on this unit, ordered, for
  the unit-page panel and the outline row chips.
- `tags_for_outline(author, course) -> ({unit_pk: [Tag]}, [Tag])` — one pass: a map of
  unit_pk → its tags (for row chips) **and** the sorted distinct set of tags the author
  uses **anywhere in this course** (for the filter bar). Restricted to
  `unit__course=course` and `tag__author=author`.
- `units_by_tag(author) -> [(Tag, {course: [unit]})]` — for the My tags page: each of the
  author's tags with its assigned units **grouped by course**, **filtered to courses the
  author can currently access** (§3 lost-access rule). Tags with zero *accessible* units
  still appear (so they can be purged). Access filtering reuses `courses.access`
  (an accessible-courses query, not a per-unit Python loop).

All mutators are **author-scoped**; a foreign `tag_pk` yields **404** (via the view's
`get_object_or_404(Tag, pk=…, author=request.user)`), never 403 — no existence leak.

`tags/services.py` imports from `courses.models` / `courses.access` only (no
`courses.views`), so no import cycle.

---

## 6. Unit-page UX (consumption: lesson *and* quiz)

> Validated mockup: [`docs/mockups/phase-4b-tags-01-unit-tagbar.html`](../../mockups/phase-4b-tags-01-unit-tagbar.html).

- A quiet **"🏷 Tags (N)" toggle** sits by the unit title (N = the author's tag count on
  this unit; the glyph is monochrome/understated, in the spirit of 4a's notes icon).
  Clicking it expands a **tags panel**; the reading view stays clean when collapsed.
- The panel shows the unit's tags as **chips** (name as text + palette colour), each with
  a **× remove** control, plus an **add** control:
  - **JS:** a text input that **autocompletes** from the author's existing tags
    (datalist or a small suggestion list); submitting a name not yet owned creates the
    tag (default colour) and tags the unit; submitting an existing name reuses it. Add /
    remove submit as **fragments** (`X-Requested-With: fetch` + CSRF, per the existing
    `_wants_fragment` pattern) and re-render the panel + the "(N)" count in place.
  - **No-JS:** the toggle is a native `<details>`; the panel renders a plain text input
    (POST to `tag_add`) **and** a checklist of the author's existing tags (check to add /
    uncheck to remove on submit). Each remove is its own tiny POST form. PRG on success
    (§8).
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
  **filter bar** above the tree: a chip per tag the author uses in this course. Chips
  **toggle**; the active set filters by **OR**.
- Each **unit row** shows its tag chips and an **✎ edit** affordance that opens the same
  add/remove editor as the unit page (shared partial; on no-JS the ✎ links to the unit
  page's tags panel via `#`-anchor / `?tags-open`).
- **Filtering behaviour (chosen):** non-matching **units are hidden**, and any
  part/chapter/section left with **no visible descendant unit collapses away**.
  - **JS:** all units render with their tag ids as `data-*`; toggling chips filters in
    place (hide rows + prune now-empty ancestors) with no round-trip; the active set is
    reflected in the URL (`?tags=…`) so the view is shareable/reloadable.
  - **No-JS:** the filter chips are GET links/submit that set `?tags=<id>&tags=<id>`; the
    **view honours the param server-side**, rendering only matching units (and pruning
    empty ancestors) — same result without JS. The pruning logic lives in **one** helper
    used by both the JS and the server path's conceptual contract (server prunes in
    Python; JS prunes in DOM; both follow the same "hide unit unless it has ≥1 selected
    tag; hide container unless it has ≥1 visible unit" rule, stated once in the spec/plan
    so they can't diverge).
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
- Each tag header carries its **manage** controls (§7.3). An **unused** tag (count 0)
  still appears so it can be deleted.

### 7.3 Tag management (rename / recolour / delete)

- **Rename:** inline (JS) or a tiny standalone GET form (no-JS), POST to `tag_rename`;
  a case-insensitive collision with another of the author's tags is a friendly field
  error (no silent merge this slice).
- **Recolour:** a small swatch picker (the fixed palette), POST to `tag_recolor`.
- **Delete entirely:** POST to `tag_delete`. When the tag is still on **N > 0** units, a
  **confirm** first — JS shows a small inline confirm; **no-JS** uses a tiny GET
  confirmation page ("Delete 'exam'? This removes it from N units.") → confirm POST — so a
  destructive action is never a single unguarded click (mirrors 4a's no-JS delete-confirm
  rule). Deleting an unused tag may skip straight to POST (still CSRF-guarded).
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
  - `…/<slug>/u/<node_pk>/tags/add` (POST) — body carries the tag **name** (free-type) or
    an existing **tag id** (checklist).
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
  context; both templates include the shared `tags/_unit_tag_panel.html`. (Lesson context
  flows through `full_lesson_render_context`, the single 4a context source; the quiz view
  gets the analogous addition.)
- No changes to `Element` / `ContentNode` / the builder beyond reading existing rows and
  rendering the panel.

**No-JS success (PRG)** — a successful no-JS add/remove/rename/recolour/delete returns a
**302** (Post/Redirect/Get; refresh can't re-POST):
- unit-scoped add/remove → back to the **unit page** (tags panel surfaced), or to the
  **outline carrying the current `?tags=` filter** when the edit originated there (the
  form carries a `next` hint validated against the two known surfaces).
- tag-scoped rename/recolour/delete → back to **`my_tags`** (the management surface).
- A validation failure (empty/over-long/duplicate name) re-renders the originating form
  with the rejected value + a field error, **HTTP 422**, nothing persisted (JS path
  returns the same as a fragment).

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
  focusable `<button>`/`<a>` controls with `aria-pressed` reflecting the active set.
- **Security/privacy:** unit-scoped tagging reuses the consumption gate (404 for a
  nonexistent/non-unit node, 403 for an inaccessible course); tag-scoped management is
  author-scoped (foreign `tag_pk` → 404, no existence leak); tag names are **escaped on
  output** (plain text, never HTML). Lost-access assignments stay hidden + uncounted.
- **Testing:** pytest + factory_boy against PostgreSQL —
  - **service** unit tests: get-or-create reuse (case-insensitive, no duplicate),
    idempotent `tag_unit`, author-scoping (foreign `tag_pk` untouched), `untag_unit`
    leaves an unused tag, `rename` collision rejected, `delete_tag` cascades + returns
    count, name normalization + length cap, `tags_for_outline` returns only this author's
    in-course tags, `units_by_tag` excludes inaccessible courses but keeps zero-unit tags;
  - **view** tests: add/remove gate order (404 before 403; quiz unit **allowed**),
    `?tags=` server-side outline filter (incl. empty-ancestor pruning), 422 validation
    re-render with repopulated value, foreign `tag_pk` → 404, no-JS delete-confirm page;
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
| Outline filter pruning empty parts in two places (JS + server) | One stated rule ("hide unit unless ≥1 selected tag; hide container unless ≥1 visible unit"); both paths implement the same contract; tested server-side. |
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
