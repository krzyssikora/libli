# Phase 4a — Personal Notes (design)

*Brainstormed 2026-06-28. Visual decisions validated with the brainstorming visual
companion (mockups archived under `.superpowers/brainstorm/`).*

Phase 4 ("Notes & tags" in [`roadmap.md`](../../roadmap.md)) is split into two
independent slices: **4a — Notes** (this spec) and **4b — Tags** (a later cycle).
They share no data and no UI; splitting keeps each PR focused, matching every prior
phase. This spec covers **4a only**.

---

## 1. Goal

A student (or any authenticated reader) can attach private, plain-text notes to
individual content blocks within a **lesson** unit, see and manage them while
reading, and find annotated units at a glance from the course outline. Notes are
personal: each user sees only their own.

---

## 2. Scope

**In scope**
- Per-user notes anchored to a content block (`Element` join-row) inside a lesson unit.
- Many notes per block; plain multi-line text.
- Create / edit / delete, on the lesson consumption page.
- Desktop right-gutter presentation with block↔note association; mobile inline accordion.
- Outline per-unit note-count badges that link back to the unit with notes surfaced.
- Graceful preservation of notes whose anchor block a teacher later deletes
  ("unanchored notes").

**Out of scope / deferred**
- **Tags** → Phase 4b.
- **Quiz-unit notes.** Lessons only. The anchor model (`Note → Element`) is identical
  for quiz question elements, so extending later is additive, not a rewrite. Excluded
  now because the quiz consumption path renders differently (a known source of bugs)
  and "notes during an attempt vs review" adds semantics lessons don't have.
- **Notes-index page** (cross-unit revision navigation) — already deferred in the roadmap.
- **Inline math in notes** (`$...$` → KaTeX) and **rich text** — plain text only this slice.
- **Sharing / visibility of notes between users** — notes are strictly private.

---

## 3. Decisions (and why)

| Decision | Choice | Rationale |
|---|---|---|
| Decomposition | 4a Notes now, 4b Tags later | Independent features; focused PRs. |
| Anchor granularity | Per **`Element` block** | Roadmap's "anchored to content blocks"; supports margin presentation + per-block revision. |
| Unit scope | **Lessons only** | Avoids the fragile quiz consumption path and attempt/review mode semantics; extendable. |
| Notes per block | **Many** | Natural for ongoing revision; makes count badges meaningful. |
| Audience | **Any authenticated viewer** | Uniform "personal private notes for whoever's reading"; avoids the staff/non-staff predicate that has caused bugs here. |
| Content format | **Plain multi-line text** | YAGNI; no HTML sanitization surface; covers the vast majority of jottings. |
| Orphan policy | **Preserve as unanchored note** | Never silently lose user-authored data when a teacher edits content. |
| Association trigger | **Note card + block handle only**, never the block body | Interactive HTML/iframe blocks keep their own hover/click behavior; cross-origin iframes swallow mouse events anyway. |
| Outline badge click | **Navigate to unit with `?notes=1`** | Useful and predictable; avoids drifting into the deferred notes-index. |

---

## 4. Data model

A new Django app, **`notes`** (parallels the existing `grouping` app — a distinct
concern with its own model, services, views, templates, and migration).

### `Note`

| Field | Type | Notes |
|---|---|---|
| `author` | FK → `accounts.User`, `on_delete=CASCADE` | Owner; notes are private to this user. |
| `unit` | FK → `courses.ContentNode`, `on_delete=CASCADE`, `limit_choices_to={"kind": "unit"}` | **Stable page anchor.** Survives block deletion; powers the outline badge and the unanchored-notes area. |
| `element` | FK → `courses.Element`, `null=True, blank=True, on_delete=SET_NULL` | **Within-page anchor** (the GFK join-row = "content block"). `NULL` ⇒ unanchored/orphaned. |
| `body` | `TextField` | Plain text; HTML-**escaped on render**; never stored as HTML, never sanitized-as-HTML. **Capped at 5,000 characters** — measured as `len(body)` (Unicode code points) **after** normalization, with the **identical** measurement in both the form and the service so they never disagree. Long enough for any genuine note, short enough to bound layout and storage. |
| `created` | `DateTimeField(auto_now_add=True)` | |
| `updated` | `DateTimeField(auto_now=True)` | Timestamp of last change. **The UI shows an "edited X ago" label only when `updated > created` (with a ~1 s tolerance, since `auto_now`/`auto_now_add` fire microseconds apart on insert); otherwise it shows "added X ago".** |

- `Meta.ordering = ["created", "pk"]` (stable display order within a block).
- Indexes: `(author, unit)` (consumption + outline-badge queries),
  `(author, element)` (per-block grouping).

**Anchoring invariants**
- A note's `element`, when set, must belong to its `unit`. Enforced in the service
  layer at create time (the element is looked up *within* the unit).
- **Editing** a block updates the `Element` join-row **in place** (verified:
  `builder.save_element` only creates a new row for brand-new elements), so a note
  stays attached through content edits, typo fixes, and reorders.
- **Deleting** a block removes the `Element` join-row; `SET_NULL` orphans the note
  (`element=NULL`) while preserving `unit`, `author`, and `body`.
- Deleting the **unit** (or its course) cascades its notes away (acceptable — the
  page no longer exists).
- **Lessons-only is an enforced invariant, not just a UI convention.** A unit is
  `kind="unit"` with a separate `unit_type` of `lesson` or `quiz`, so the `unit` FK's
  `limit_choices_to={"kind": "unit"}` does **not** by itself exclude quizzes. The
  service layer is the enforcement point: `create_note` rejects any target unit whose
  `unit_type != lesson` (see §5). This guards the independently-reachable `note_add`
  endpoint — without it, a quiz-unit note could be created with no UI to view, edit, or
  delete it. To extend to quizzes later, relax this single guard.

---

## 5. Services (`notes/services.py`)

Pure-ish functions, the single choke point for all note mutation and querying
(mirrors `grouping/services.py`):

- `create_note(author, unit, element_pk_or_none, body) -> Note`:
  - **Access gate (required):** reuse the **existing** course-access gate the
    consumption views already share — `courses.access.can_access_course(user, course)`
    plus `courses.access.get_node_or_404(...)` for the unit (both live in
    `courses/access.py`, a standalone module with no view imports, so
    `notes/services.py` importing from it creates **no cycle**; the dependency direction
    is notes → courses.access only). Mirror the consumption view's outcomes exactly: a
    nonexistent/non-unit node ⇒ **404** (via `get_node_or_404`); a unit in a course the
    author cannot access ⇒ **`PermissionDenied` (403)** — the same response the lesson
    page returns, so notes leak nothing the consumption URL doesn't already. This closes
    the create-time IDOR that author-scoping alone does not cover.
  - **Lessons-only guard (required):** reject any unit whose `unit_type != lesson`
    (404). See §4.
  - **Element resolution:** the `element_pk` arrives as a **hidden field in the
    per-block composer's POST body** (the URL carries only `unit_pk`). Resolution uses
    the `Element.unit` FK (`Element` rows point at their unit via
    `unit = FK(ContentNode, related_name="elements")`): look up
    `unit.elements.filter(pk=element_pk).first()`. Found ⇒ anchored note;
    **not found in this unit** (deleted between page load and submit, or a stale/forged
    pk) ⇒ **gracefully fall back to an unanchored note** (`element=None`), consistent
    with the orphan policy — never a hard error for this race. A pk belonging to another
    unit simply isn't found by this unit-scoped query and falls back to unanchored.
  - **`element_pk=None` is reachable only via this fallback** (and the stale-pk path
    above), **not** from a deliberate "add a unit-level note" UI control — there is no
    such control in this slice. Unanchored notes are otherwise produced only by block
    deletion (§7.2).
  - **Body normalization:** strip leading/trailing whitespace, normalize line endings
    CRLF→LF, **preserve all interior whitespace and blank lines** (multi-line formatting
    is meaningful). Reject if empty after stripping, or if it exceeds the 5,000-char cap.
- `update_note(author, note_pk, body) -> Note` — author-scoped; same body normalization,
  empty-rejection, and length cap as create.
- `delete_note(author, note_pk) -> None` — author-scoped.
- `notes_for_unit(author, unit) -> {element_pk|None: [Note, ...]}` — grouped for
  rendering the gutter / accordion / orphan area in one query
  (`select_related`/`prefetch` as needed).
- `note_counts_for_outline(author, course) -> {unit_pk: int}` — one aggregate query
  for the outline badges (counts the author's notes per unit, including unanchored).

All mutation functions are **author-scoped** (a user can only touch their own notes);
a foreign `note_pk` yields 404, never 403, to avoid leaking existence.

---

## 6. Consumption UX

### 6.1 Desktop — right gutter

- Lesson content renders as today; a **notes gutter** sits to its right.
- Each annotated block shows a persistent **📝 handle** (count) at its top-right;
  un-annotated blocks show a faint **+ note** handle (visible on hover/focus).
- Gutter holds **note cards**, colour-coded per block, positioned near their block.
- **Association (JS enhancement):** hovering/focusing a note card *or* a block handle
  highlights the matching block + note(s) in a shared colour, dims the rest, and draws
  a connector line. **The block content body never triggers this** — interactive
  HTML/iframe widgets are untouched.
- **Colour assignment:** deterministic by a **stable per-block key** — `element.pk`
  modulo the palette size — so a given block keeps its colour even when notes are
  added to or removed from *other* blocks (indexing by annotated-block *order* would
  re-colour later blocks whenever the annotated set changes). Palette collisions
  (two annotated blocks landing on the same colour) are cosmetic and acceptable;
  association still works via the hover highlight + connector.

### 6.2 Mobile — inline accordion

> **Intentional deviation from the roadmap.** [`roadmap.md`](../../roadmap.md) §Phase 4
> sketches "📝 icon → modal on mobile." We deliberately choose an **inline accordion**
> instead: it keeps a single CRUD form per note shared with desktop (see §6.4), needs
> no modal/focus-trap machinery, and degrades to native `<details>` with no JS.

- Each block shows a 📝 chip: count, or "Add note" when empty.
- Tapping expands that block's notes + an "Add a note" composer **inline beneath the
  block**. Degrades to native `<details>`/`<summary>` with no JS.

### 6.3 Compose / edit / delete

- **+ note** opens a composer (textarea + Save / Cancel) in the gutter (desktop) or
  inline (mobile).
- Existing notes show **✏️ edit** (in place) and **🗑 delete** affordances; a muted
  "edited X ago" label.
- All three operations are **standard POST forms** (work without JS). When JS is
  present, they submit as fragments and re-render the affected region in place
  (consistent with the existing `_wants_fragment` pattern in `courses`).
- **Delete confirmation:** with JS, delete shows a small **inline confirm** before
  POSTing. With **no JS**, the 🗑 control links to a tiny **GET confirmation page**
  ("Delete this note?" → confirm POST), so a destructive action is never a single
  unguarded click; immediate-delete-without-confirm is **not** the no-JS behavior.
- **Validation-failure contract** (empty body / over-length):
  - **No-JS:** re-render the full unit page with the composer **repopulated** with the
    rejected text and a field-level error shown; nothing is persisted. (A POST→GET
    redirect would lose the text, so the failure path renders directly, HTTP 422.) The
    re-render must **re-open the specific offending region** — the `<details>` for the
    failing block's composer (create) or the failing note's edit form (edit) is rendered
    `open`, and the field error is bound to that exact `element_pk` (create) or `note_pk`
    (edit) — so the no-JS user lands on the populated form, not a collapsed page.
  - **JS/fragment:** return the composer fragment with the same repopulated text + field
    error (HTTP 422); the surrounding page is untouched. This mirrors the existing
    `ElementFormInvalid` 422 fragment handling in `courses`.

### 6.4 One markup source, restyled responsively (no dual render)

The server renders HTML once and cannot know the viewport, so the gutter and the
accordion are **the same DOM, restyled by CSS** — not two parallel renders. Concretely:

- Each note is emitted **once**, with **one** edit form and **one** delete form; the
  composer for a block is emitted **once**. There are **no duplicated element/form
  `id`s and no duplicated `<textarea name=...>`** for the same note.
- The "desktop gutter" vs "mobile accordion" difference is purely presentational
  (CSS — gutter positioning + the association/connector layer on wider viewports;
  stacked `<details>` accordion on narrow ones). The association/connector visuals are
  a desktop-only JS *enhancement* over this single markup; they add no second copy of
  any form.
- This is a hard requirement, not an open detail: the implementation must keep one
  canonical markup per note/composer to avoid duplicate-id and double-submit hazards.

---

## 7. Outline & orphans

### 7.1 Outline badge

- Each unit row on the course outline shows a **📝 count** of the author's own notes
  in that unit (including unanchored ones). Units with zero notes show nothing.
- The badge is a **link to the unit** carrying `?notes=1`. On that page:
  - desktop — the gutter is already visible (no extra behavior needed);
  - mobile — annotated blocks auto-expand (or the page scrolls to the first note).
  - **unit whose notes are *only* unanchored** — `?notes=1` **expands the
    unanchored-notes area (§7.2) and scrolls to it**, so the link always lands the user
    on visible notes rather than a collapsed page with nothing surfaced.

### 7.2 Unanchored notes

- Notes with `element IS NULL` render in a **collapsed "⚠ notes whose block was
  removed" area** at the bottom of the unit.
- They remain **editable and deletable** and are **counted** in the outline badge.
- This area is omitted entirely when the user has no unanchored notes on the unit.

---

## 8. Architecture & integration

**New `notes` app**
- `models.py` (`Note`), `services.py`, `views.py` (add / edit / delete + fragment
  renderers), `urls.py`, `templates/notes/` (gutter, accordion, composer, note card,
  orphan area, outline-badge partials), `migrations/0001_initial.py`, tests, factories.

**Integration points in `courses`** (small, additive)
- Lesson consumption view: pass the author's `notes_for_unit(...)` into context;
  the lesson template includes the notes partial(s) and reads `?notes=1`.
- Outline view: the **learner-facing course outline only** (`course_outline` in
  `courses/views.py`) gets the badge — pass `note_counts_for_outline(...)` into its
  context and include the badge partial. The authoring/manage builder outline is
  **not** touched (notes are personal to the reader, irrelevant to authors).
- No changes to `Element` / `ContentNode` / the builder beyond reading existing rows.

**URLs** — namespaced `notes:` routes:
- `note_add` is **unit-scoped** (`…/<unit_pk>/notes/add`) and applies the §5 create
  access gate + lessons-only guard against that unit.
- `note_edit` / `note_delete` are keyed by **`note_pk` only** and **author-scoped** —
  the note already knows its `unit`, so no course/unit path segments are needed
  (decorative scope segments would otherwise have to be re-validated against the note,
  or be spoofable). A `note_pk` the requester doesn't own ⇒ **404**.

---

## 9. Cross-cutting requirements

- **i18n:** every user-facing string marked for translation with EN + PL catalogs
  (`.po`/`.mo`). Watch the known fuzzy-flag + animacy/context gotchas; use `msgctxt`
  where a shared msgid would need divergent Polish.
- **Light/dark + responsive:** gutter (desktop) ↔ accordion (mobile) is a CSS restyle
  of **one** markup source (see §6.4 — no dual render), via the existing token-driven
  CSS; no hard-coded colours that fail in dark mode.
- **Progressive enhancement:** CRUD works with no JS; association visuals and fragment
  swaps are enhancement only.
- **Accessibility:** every icon-only control carries a **translatable `aria-label`**
  (📝 add/handle, ✏️ edit, 🗑 delete, the ⚠ unanchored-area toggle); the count handle
  exposes its count **textually** (not colour/glyph alone). The block↔note association
  must not be **colour-only** — the connector + highlight are a sighted enhancement, and
  each gutter note card names its block (e.g. "on: <block label/type>") so the
  relationship is available without seeing colour. Keyboard: handles and note actions
  are real focusable controls (`<button>`/`<a>`), and focusing a handle/card triggers
  the same association cue as hover.
- **Security/privacy:** **create** reuses the consumption access gate (§5) — a
  nonexistent/non-unit node → 404, a unit in an inaccessible course → 403
  (`PermissionDenied`), matching the lesson page exactly; **edit/delete** are
  author-scoped, foreign `note_pk` → 404 (no existence leak); body escaped on output.
- **Testing:** pytest + factory_boy against PostgreSQL; service-layer unit tests
  (CRUD, author-scoping, **create access-gate: 404 for a nonexistent/non-unit node and
  403 for an inaccessible course**, **lessons-only guard rejecting a quiz unit**,
  **stale-element-pk → unanchored fallback**, body normalization + length cap, orphan
  preservation, outline counts),
  view tests (forms + fragments, **422 validation re-render with repopulated body**,
  404 on foreign notes), and at least one e2e that drives the **real**
  add→see→edit→delete gesture (no `page.evaluate` shortcuts).

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Editing a block silently orphaning notes | Verified `save_element` updates in place; only true deletion orphans (by design). |
| Gutter alignment / long notes on narrow desktop | Notes are positioned *near* their block, not pixel-pinned; association is by colour + hover, not strict vertical alignment. |
| Interactive HTML/iframe blocks fighting the association hover | Triggers live only on the note card + block handle, never the body. |
| Quiz scope creep | Explicitly excluded; anchor model leaves the door open. |
| Notes-index scope creep via the outline badge | Badge only navigates (`?notes=1`); no in-place note list on the outline. |

---

## 11. Open detail for the plan (non-blocking)

- Exact gutter colour palette (the cycling *rule* is already decided in §6.1:
  `element.pk` modulo palette size).
- Whether `?notes=1` mobile behavior is "auto-expand all annotated blocks" vs "scroll
  to first" — pick one in the plan; both are presentation-only.
