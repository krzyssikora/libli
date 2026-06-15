# Phase 1b-i — Course CRUD & Course Builder: Design Spec

*Spec date: 2026-06-15. First slice of Phase 1b (the bespoke authoring UI), itself the second
major slice of [Phase 1](../../roadmap.md#phase-1--content-model-authoring--lesson-consumption).
Builds directly on [Phase 1a](2026-06-15-phase-1a-content-model-and-consumption-design.md) (content
schema, `ContentNode` tree, `Element` GFK + 5 concrete models, `Enrollment`, `UnitProgress`,
`OrderField`), which is merged (PR #6). Views numbered per [view-inventory.md](../../view-inventory.md)
§5. Stack per [the 0d UI foundation](2026-06-14-phase-0d1-ui-foundation-design.md): server-rendered
Django, token-driven bespoke CSS, no Bootstrap/React.*

## Goal

Ship a **demonstrable authoring vertical slice**: a **Platform Admin creates a course** and assigns
an owner; the **owner (or a PA) builds the course's structural skeleton** — parts/chapters/sections/units
with ordering, re-parenting, and obligatory flags — and **curates each unit's element list** (reorder,
delete), all through a bespoke UI that replaces the structure-building half of the `seed_demo_course`
command. This activates `Course.owner` as the authoring anchor and lands the re-parent /
gap-compaction `OrderField` operations that 1a explicitly deferred to "the builder." Element *content*
authoring and the media manager remain in Django admin until 1b-ii.

## Phase 1b slice split (decided in brainstorming 2026-06-15)

Phase 1b (the authoring UI) is large; it is split into vertical slices, each its own spec → plan → build:

- **1b-i (this spec) — Course CRUD + builder.** Course create/edit/delete, the master-detail course
  builder (tree of part/chapter/section/unit), the unit-settings panel, and element **list + reorder +
  delete**. End state: a course's full structure is buildable via UI.
- **1b-ii — Content editors + media manager.** The dedicated per-unit **editor ｜ preview** page, the
  5 element editors (text/image/video/iframe/math), element **add/edit**, and the media manager (5.13).
- **HTML element slice** (still Phase 1) — the arbitrary-HTML element (course-wide CSS/JS, per-unit JS,
  MathJax/LaTeX) with its security design. Renders into the **same 1b-ii editor ｜ preview pane**; no new
  layout. Rides with 1b-ii or stands alone — decided later.

## Layout decision (locked in brainstorming, with visual companion)

The builder and unit editor relate as a **hybrid split by level**:

- **Structure work** (add/move/reorder/delete nodes, set a unit's title/type/obligatory, reorder/delete
  its elements) uses a **master-detail** layout: the `ContentNode` tree stays in view on the left;
  selecting a node fills a panel on the right with its settings. This is all of 1b-i. Selecting the
  course root shows course metadata; selecting a unit shows unit settings + the element list.
- **Deep content editing** (element bodies, and later custom CSS/JS + MathJax) gets **its own full page**
  with a **live preview alongside** (editor ｜ preview). This is 1b-ii. 1b-i builds only the **seam**: an
  "Open editor →" link from the unit panel to the per-unit edit route.
- The master-detail panel **collapses to a stacked / drill-in view on mobile** (tap a node → its panel);
  deep editing being full-page sidesteps the small-screen split entirely.

## Foundational decisions (locked in brainstorming)

1. **Interaction model — progressive enhancement, vanilla JS, button-based moves.** The builder is
   server-rendered; each operation (add/rename/move/reorder/delete a node; reorder/delete an element) is
   a small `POST` to a Django view that returns an **HTML fragment** swapped into the page by vanilla JS
   (the same `fetch`-and-swap idiom as 1a's `progress.js`; **no new front-end dependency**, no HTMX).
   Reordering and moving are **button-based** (up/down within siblings; a "Move…" picker for re-parenting);
   **drag-and-drop is deferred** as later polish. With JS off, every operation **degrades to a full-page
   form POST + re-render** — the builder remains fully usable and accessible.
2. **Concurrency — optimistic, conflict-aware; no locking.** Because each action is its own atomic,
   immediately-persisted operation (not a batch "edit whole tree then Save"), two admins interleave small
   atomic edits rather than clobbering whole-tree drafts. The only residual risk — genuine contradictions
   (e.g. moving a node into a chapter another admin just deleted) — is caught by validating each operation
   against current DB state **inside a transaction**, returning a friendly **`409` + fresh fragment**
   ("this changed — refreshing") on conflict. **No pessimistic locking** (stale-lock/force-unlock overhead
   isn't justified at a school's scale).
3. **Permissions — PA creates/deletes, owner+PA edit.** Per view 6.3. **Platform Admin** creates a course
   (assigning an `owner`, possibly themselves) and deletes courses; the **owner and PAs** edit metadata
   and build the tree. Course Admins do **not** create or delete courses in 1b-i (per-course CA assignment
   is view 6.2, later). All checks go through **Django model permissions / Groups**, never hardcoded role
   strings or the `is_staff` flag (the RBAC re-sliceability cross-cutting principle). **"PA" resolves to the
   Platform Admin Group** seeded in Phase 0 (`setup_roles`), which holds the `courses.{add,change,delete}_course`
   model perms. The canonical object-level **manage predicate** (used by edit + builder + all node/element
   fragment routes) is **`course.owner_id == user.id OR user.has_perm("courses.change_course")`** (with the
   explicit `owner_id is not None` guard). This is **separate** from 1a's *student-side* preview predicate
   (`enrolled OR is_staff OR owner`), which is untouched — the authoring surface deliberately does not key on
   `is_staff`.
4. **Element scope in 1b-i — list + reorder + delete only.** The unit panel shows a unit's existing
   elements (created via Django admin / `seed_demo_course`) and supports **reorder (up/down) and delete**,
   reusing the same per-scope `OrderField` reorder machinery built for tree nodes. **Adding** an element
   and **editing** its content are the 1b-ii seam ("+ Add element" / "Open editor →" link out).
5. **Re-parenting — a filtered "Move…" picker, not indent/outdent.** Because node `kind` is **not** tied to
   tree depth (a unit may sit at the root or three levels deep; middle levels are skippable per 1a), an
   indent/outdent control would be ambiguous. Instead a **"Move…"** action offers a destination picker
   filtered to **only kind-depth-legal parents** (plus "top level") and a target position. The builder can
   therefore never *offer* an illegal move; server-side `clean()` remains the authority if a concurrent
   edit invalidates a choice.
6. **Course deletion — hard delete with guards.** PA-only. A confirm dialog; if the course has any
   `Enrollment` or `UnitProgress` rows, an **extra warning** stating what will be lost. Hard delete
   (cascades the tree + elements + learner state). Soft-archive was considered and **not** chosen.

## Success criteria (Definition of Done)

1. **My courses (admin)** (`GET /manage/courses/`, login + manage-permission) lists courses the user
   administers (**owned by the user OR — for PAs (`courses.change_course`) — all courses**), **ordered by
   `title`** for deterministic rendering/tests (pagination is a deferred nicety — fine at a school's scale).
   PAs see a **"New course"** action (gated on `courses.add_course`); non-PA owners do not. This
   is distinct from the student "My courses" (`/courses/`, enrollment-based) from 1a; the two surfaces do
   not bleed into each other.
2. **Create / edit course** (`GET/POST /manage/courses/new/` create=PA; `…/<slug>/edit/` edit=owner+PA): a
   Django `ModelForm` over `title`, `slug` (auto-suggested from title, editable, unique), `subject`
   (dropdown of existing `Subject`s), content `language` (from `COURSE_LANGUAGES`), `overview`,
   `visibility` (assigned/open — `open` is a Phase-3 hook, field shown), and **`owner`** (PA picks at
   create; defaults to the creating PA). Editing preserves `slug` stability rules (see Data model).
3. **Course builder** (`GET /manage/courses/<slug>/build/`, owner+PA): renders the `ContentNode` tree
   master-detail. Selecting the **root** shows course metadata (link to the edit form); selecting a
   **container** shows its settings; selecting a **unit** shows title/type/obligatory + its **element
   list**. A **container-less course** (units directly under the course) and an **empty course** (no nodes
   yet, with a "add your first node" empty state) both render correctly. A **top-level unit is still a unit**
   — adding one requires `unit_type` like any other (the Add form supplies it; see #4 / Add semantics), so
   "any kind at root" does **not** mean "no extra fields for a root unit."
4. **Node operations** (fragment `POST`s, owner+PA, CSRF-protected, each atomic in a transaction):
   - **Add** (`…/build/node/add/`): a new child under a chosen parent (or at top level). The UI offers
     **only kind-depth-legal kinds** (child kind strictly deeper than parent; root offers any). Created via
     `Model.save()`/`full_clean()` so 1a invariants hold; `order` auto-assigned at the end of the scope.
   - **Rename** (`…/build/node/rename/`): title only.
   - **Reorder** (`…/build/node/move/`, `mode=reorder`): up/down within siblings, re-numbering affected
     siblings to **strictly-distinct `order`** values against the effective `(order, pk)` sort (a plain swap
     is insufficient — `order` is non-unique; see Concurrency mechanics).
   - **Re-parent** (`…/build/node/move/`, `mode=reparent`): to a kind-depth-legal new parent + position;
     re-fetches the destination in-txn (gone → `409`), rejects illegal targets with the model `clean()` error
     (→ `422`). Assigns `order` in the destination scope and **compacts the source scope**.
   - **Delete** (`…/build/node/delete/`): cascades descendants + their elements; **gap-compacts** the
     remaining siblings' `order` in the vacated scope.
   - Each operation returns the **re-rendered affected scope fragment(s)** — a re-parent refreshes **both**
     the source and destination scopes (or the whole tree pane); a `409`/`422` returns the fresh fragment /
     in-panel error per the Concurrency mechanics contract.
5. **Unit settings** edit (within the builder panel): `title`, `unit_type` (lesson/quiz), `obligatory`,
   persisted via `full_clean()`/`save()` (1a's `unit_type` iff `kind=unit`, units-are-leaves invariants
   still enforced).
6. **Element list ops** (owner+PA, CSRF-protected): the unit panel lists the unit's `Element`s in `order`,
   labelling each by its **`Element.content_type`** model name (e.g. "text", "image") — **not** by fetching
   each concrete instance, avoiding a per-element GFK N+1 (only a type label, not content, is needed in 1b-i);
   **reorder** (`…/build/element/move/`, up/down
   within the unit's `OrderField` scope) and **delete** (`…/build/element/delete/`, cascading the concrete
   element + its join-row via the 1a `GenericRelation`, then **gap-compacting**). "+ Add element" / "Open
   editor →" render as **visually-disabled, non-navigating affordances** (no `href`, `aria-disabled="true"`,
   a "coming in 1b-ii" tooltip) — present as a seam but with **no route to 404 into** in 1b-i. The 1b-ii
   route is not wired here.
7. **OrderField extension:** the 1a `OrderField` gains **re-parent** (recompute `order` in a new scope) and
   **gap-compaction on delete** (close the hole left in a scope) — the operations 1a deferred to the
   builder. Per-scope ordering remains non-DB-unique (ties broken by `pk`); compaction is best-effort
   normalisation, not a hard constraint.
8. **Optimistic concurrency:** each mutating fragment `POST` carries the target node's (or unit's)
   last-known **`updated`** timestamp (ISO-8601, from the rendered fragment). The view re-reads the row in
   the transaction; if `updated` advanced, it returns **`409`** with a freshly-rendered fragment and a
   "this changed — refreshing" cue, performing **no write**. Otherwise it applies the change. No new version
   column is added. The client swaps in the `409` fragment so the user sees current state. The exact
   request/response contract (token source, `409`/`422` semantics) is specified under Concurrency mechanics.
9. **Access control & object scoping:** all `/manage/` routes are `@login_required` + the canonical **manage
   predicate** (`course.owner_id == user.id OR user.has_perm("courses.change_course")`, `owner_id is not None`
   guard; no `is_staff`), with course creation/deletion additionally gated on the Django **`courses.add_course`
   / `courses.delete_course`** permissions (held by the Platform Admin Group). Node/
   element fragment routes use the **`<int:pk>`** converter and check, in order: object exists (→404),
   **belongs to the URL's course** (slug pairing, →404 — IDOR guard, mirroring 1a's ordering so a mismatch
   404s before any 403), then the manage predicate (→403). Course delete additionally requires PA.
10. **Validation & safety:** the builder only *offers* legal operations, but the server is the authority —
    `ContentNode.clean()` (kind-depth, unit-leaf, `unit_type` rule, the 1a child-revalidation rules) rejects
    anything illegal with a graceful in-panel message; all writes go through `save()`/`full_clean()` (no
    `bulk_create`/`update` that would bypass `TextElement` sanitisation or invariants); every mutating
    endpoint is CSRF-protected.
11. **i18n:** all new UI strings via `gettext`, EN + real Polish, compiled (same flow as 0d/1a). Builder
    chrome (kind labels, "Move…", "Add child", "Mark required", confirm dialogs) is in the **UI** language;
    author-entered titles are content and not translated.
12. **Responsive & theming:** master-detail on desktop; stacked/drill-in on mobile; light/dark + branding
    inherited from the 0d shell.
13. **Tests** (pytest + factory_boy vs real PostgreSQL): permission/access matrix, every node operation +
    invariant rejection, re-parent legality + `OrderField` re-scope, **gap-compaction on delete**,
    **optimistic-conflict `409`** (stale `updated` → no write, fresh fragment), element reorder/delete +
    join-row cascade, course CRUD + **delete guard when enrollments/progress exist**, slug-mismatch/IDOR
    404-before-403, empty-course and container-less-course rendering, **`409`-before-`422` precedence**, and
    the **destination-parent-deleted → `409`** case for Add/Re-parent. A **Playwright e2e**: log in as PA →
    create course → build a small mixed tree → reorder + move a node → open a unit → reorder an element. The
    e2e **additionally asserts** (a) a **stale-token `409`** path — drive the builder, mutate the same row out
    of band, then confirm the next action swaps in the fresh fragment with the "this changed" cue rather than
    clobbering — and (b) the **no-JS fallback** — a node op via full-page form POST + redirect with scripting
    disabled.
14. Full `pytest` green; `ruff` check + format clean; `manage.py check` clean; `makemigrations --check`
    clean; `collectstatic` clean.

---

## Data model

1b-i is **mostly activation of existing 1a hooks** — **no schema migration is expected**. The only DB-write
setup is assigning model permissions to the Platform Admin Group, which is **data**, done via a data
migration or the existing `setup_roles` command — neither shows up in `makemigrations --check`.

- **`Course.owner`** (existing FK, inert in 1a) becomes the authoring anchor. The canonical manage
  predicate is `course.owner_id == user.id OR user.has_perm("courses.change_course")` (explicit
  `owner_id is not None` guard) — **group/permission-based, not `is_staff`** (see Foundational #3). No
  `Course↔admins` M2M is added (multi-admin assignment = view 6.2, later); the conflict-safety is built so
  multi-editor "just works" whenever that lands.
- **`Course.slug`** — auto-suggested from `title` on create: `slugify(title)`, and on collision with an
  existing course **append the smallest free `-2`, `-3`, … suffix** (operating on the full slugified base
  regardless of any trailing digits, e.g. `year-2` → `year-2-2`; the search loops until free, unbounded —
  collisions are tiny at a school's scale). The field is editable; a user-typed slug
  that collides surfaces as a **`ModelForm` field `ValidationError`** ("slug already in use"), never a raw DB
  `IntegrityError`/`500` (the form validates `unique` before save). On **edit**, changing the slug is allowed
  but is the author's responsibility (student/preview URLs use the slug); 1b-i does not add redirects for old
  slugs (YAGNI; note for later if it bites). **The edit POST's
  success redirect targets the *new* slug** (`…/<new-slug>/edit/` or the builder), since the manage routes
  are slug-keyed. **Known consequence:** a builder tab already open under the *old* slug will get a `404` on
  its next slug-keyed fragment POST — acceptable in 1b-i (the user reloads); flagged here so it isn't a
  surprise.
- **Model permissions** — the standard Django `add/change/delete/view_course` (and node/element) perms are
  assigned to the **PA group** (and `change` to a future CA path); the manage predicate adds object-level
  ownership on top. No custom permission classes needed.
- **`OrderField`** (1a, `courses/fields.py`) gains two operations used by the builder service layer:
  re-parent (assign next/inserted `order` within a new `(course, parent)` scope) and **gap-compaction**
  (renumber a scope's siblings 0..n after a delete or move-out). These are **service-layer helpers**, not
  new fields.
- **Concurrency token** — the existing **`ContentNode.updated`** / `Course.updated` `auto_now` field is the
  optimistic token; **no schema change**. Note `auto_now` advances **only when that row is saved**, so the
  token detects edits to the row(s) an operation reads/writes — **not** every sibling-order race. The
  mechanics compensate explicitly (see Concurrency token model): reorder/compaction **re-save every sibling
  whose `order` changed** (advancing their `updated`), Add/Re-parent additionally check the **destination
  parent's** token, and because `Element` has no `updated` in 1a, **every element op bumps the parent unit's
  `updated`** (`save(update_fields=["updated"])`) so the unit row is a real conflict boundary for element
  ops. The known residual — a peer who *viewed* a now-stale sibling position — surfaces as a `409` on that
  peer's *next* write to the moved row, not as silent corruption.

No new models and **no schema change**. The permission/group assignment is **data** (data migration or
`setup_roles` extension), which does not affect `makemigrations --check` — which must therefore stay clean
with no new schema migration in this slice.

---

## Views, routes & layout

All under a **`/manage/`** prefix (new `courses/manage_urls.py` or a `manage/` include), separate from the
1a student `/courses/` routes. Views in `courses/views_manage.py` (keep the manage surface cohesive and out
of the already-populated `courses/views.py`); fragment templates under `courses/templates/courses/manage/`.

| View (inv. #) | Route | Method | Access | Behaviour |
|---|---|---|---|---|
| My courses (admin) (5.1) | `/manage/courses/` | GET | owner+PA | Lists administered courses; "New course" for PA. |
| Create course (5.2) | `/manage/courses/new/` | GET/POST | PA | `CourseForm`; sets `owner`. |
| Edit course (5.2) | `/manage/courses/<slug>/edit/` | GET/POST | owner+PA | Same form; metadata only. |
| Delete course (6.3) | `/manage/courses/<slug>/delete/` | GET/POST | PA | **GET** renders the confirm page with live enrollment/progress + cascade counts; **POST** performs the hard delete. The GET confirm makes the guard work with JS off. |
| Builder (5.4) | `/manage/courses/<slug>/build/` | GET | owner+PA | Master-detail tree + panel. |
| Node detail panel | `/manage/courses/<slug>/build/node/<int:pk>/` | GET | owner+PA | Right-panel fragment for a node. |
| Node add | `…/build/node/add/` | POST | owner+PA | New child; returns subtree fragment. |
| Node rename | `…/build/node/rename/` | POST | owner+PA | Title; returns fragment. |
| Node move | `…/build/node/move/` | POST | owner+PA | `mode=reorder` (direction) **or** `mode=reparent` (new_parent+position); returns the affected scope fragment(s). |
| Node delete | `…/build/node/delete/` | POST | owner+PA | Cascade + compact; returns fragment. |
| Element move | `…/build/element/move/` | POST | owner+PA | Reorder within unit; returns element-list fragment. |
| Element delete | `…/build/element/delete/` | POST | owner+PA | Cascade join-row + compact; returns fragment. |

**Builder page** = master-detail: a **tree pane** (indented, kind-badged rows with per-row action affordances)
and a **detail panel** (course metadata for the root; container settings; unit settings + element list). The
panel content is fetched as a fragment on node selection. **Row indentation reflects actual parent-chain
depth, not kind rank** — so skipped middle levels and a container-less course (units at the root sit at
indent 0) render correctly. The student outline/lesson views from 1a are **untouched**.

---

## Builder interaction & concurrency mechanics

### Request payloads (per operation)

Each mutating `POST` carries CSRF + the optimistic token(s) (see "Concurrency token model" below) plus:

| Op | Route | Required fields |
|---|---|---|
| Add | `…/node/add/` | `parent` (node pk **or** the literal `top` for course-level), `kind`, `title`, and **`unit_type` when `kind=unit`**. Always **appended to end** of the destination scope (no insert-at-position in 1a). |
| Rename | `…/node/rename/` | `node`, `title`. |
| **Reorder** | `…/node/move/` with **`mode=reorder`** | `node`, `direction` ∈ {`up`,`down`}. Operates within the node's current `(course, parent)` scope. |
| **Re-parent** | `…/node/move/` with **`mode=reparent`** | `node`, `new_parent` (node pk or `top`), optional `position` (defaults to end). |
| Delete | `…/node/delete/` | `node`. |
| Element reorder | `…/element/move/` | `element` (the `Element` join-row pk), `direction`. |
| Element delete | `…/element/delete/` | `element`. |

The single `…/node/move/` route is **explicitly discriminated by `mode`** (reorder vs reparent); each mode
validates only its own fields. Unknown/missing `mode` → `400`.

### Operation semantics

- **Add.** UI offers only kind-depth-legal child kinds (root/`top` offers any kind). The view re-fetches the
  destination parent **inside the transaction**, then `full_clean()`s + `save()`s the new node with `order`
  auto-assigned at the end of the destination scope. A top-level Add uses the `(course, parent=NULL)` scope;
  a unit Add **must** include `unit_type` (else `full_clean()` fails → `422`). The Add form **reveals the
  `unit_type` selector iff the chosen kind is `unit`** (the only kind needing an extra field), so the client
  offers it exactly when required. Add is **always append-to-end**
  — it has **no position control** (unlike the Re-parent picker; the two are distinct flows in 1b-i, not a
  shared positioned-insert component). **Parent-gone `409` is the one case that returns the whole tree pane**
  (the destination scope no longer exists to re-render), distinct from the same-scope `409` fragment used by
  the other ops.
- **Reorder (up/down).** The view fetches the node's siblings ordered by the **effective `(order, pk)` sort**
  (matching 1a's display order), finds the adjacent neighbour in the requested direction, and **re-numbers
  the affected siblings to strictly-distinct `order` values** so the new position is deterministic — a plain
  `order`-value swap is **not** sufficient because `order` is non-DB-unique and ties break by `pk` (a swap of
  equal `order`s is a visual no-op). A **boundary no-op** (top item "up" / bottom "down") performs **no save**,
  bumps **no token**, and returns `200` with the **unchanged** fragment carrying the **current (unadvanced)
  `data-updated`** — explicitly distinct from an *applied* `200`, so peers see no spurious token advance.
- **Re-parent ("Move…").** Picker lists only legal destination parents (kind-depth), **excluding the moved
  node itself and all its descendants** (a node can't move under its own subtree), + "top level". The view
  re-fetches the chosen `new_parent` **inside the transaction** (gone → `409`), re-validates the move via
  `clean()` — which is the **authority** for both kind-depth and the **no-cycle rule** (destination is not a
  descendant of the moved node) → `422` on violation. Re-parent **changes only the moved node's own `parent`
  and `order`**; its descendants keep their `parent` FK pointing at the (still-existing) moved node and are
  **not re-saved or token-checked** — so the moved node's token plus the destination parent's token fully
  cover the operation. **`position`** is a **0-based insertion index into the destination scope's
  pre-insertion effective `(order, pk)` sort**, valid range `0..N` where `N` = the current sibling count
  (`N`-or-greater, or omitted → append to end); the view **re-numbers the destination siblings to
  strictly-distinct `order`** (same machinery as Reorder) so the node lands deterministically, then
  **compacts** the source scope. **Any re-parent `409`** (either token mismatch, or destination-gone)
  **returns the whole tree pane** — consistent with the re-parent success path and the Add parent-gone case —
  so the client's swap target is unambiguous.
- **Delete.** The confirm dialog's descendant/element counts are **advisory** (rendered earlier; see I-note
  below); the view re-reads current state in the transaction, cascades descendants + their elements, and
  **compacts** the vacated scope. Acting on an already-deleted node → `409`.
- **Element reorder/delete.** The `element` payload field is the pk of the **1a `Element` join-row** (the row
  carrying the `OrderField` + GFK), **not** the concrete content model's pk. Scoped to the unit's `Element`
  `OrderField` using the same effective-sort re-numbering as node reorder; delete cascades the concrete
  element + join-row (1a `GenericRelation`) and compacts. **An element op on a vanished row** (the `Element`
  pk no longer exists or no longer belongs to this unit — e.g. a peer deleted it) → **`409`** with the fresh
  element-list fragment (mirroring the node "already-deleted → `409`" rule). **Every element op bumps the
  parent unit's `updated`** (explicit `unit.save(update_fields=["updated"])` in the transaction) so the unit
  token is a real concurrency boundary for element ops (see token model).

### Concurrency token model

- **What the token protects:** the token guards against edits to **the row(s) the operation reads/writes**,
  not against every sibling-order race. Plain `auto_now` `updated` advances only when *that* row is saved, so
  the model is made robust per-operation as follows.
- **Tokens carried & checked, per op** (all re-read inside the transaction; **the token check runs first, before any `clean()`**):
  - **Reorder/Rename/Delete (node):** the **target node's** `updated`. **Rename writes
    `save(update_fields=["title","updated"])`** (title column only) so that, even inside the transaction, it
    cannot clobber an `order` a concurrent reorder set — the node token alone is therefore sufficient for
    rename.
  - **Add / Re-parent:** the **destination parent's** `updated` **and** the moved node's `updated` (re-parent
    only). A missing destination row → `409`. For a **`top`-level** destination the token is **`Course.updated`**,
    which the builder bumps (`course.save(update_fields=["updated"])`) on any op that changes the `parent=NULL`
    scope — i.e. **top-level Add / Re-parent-to-top / Delete-of-a-top-node / top-level Reorder**. (Top-level
    Reorder still also re-saves the moved siblings, so a peer editing one of them gets a `409` the normal way;
    the course-token bump additionally guards interleaved top-level Adds.) **The course edit ModelForm
    (DoD #2) also bumps `Course.updated`** (plain `auto_now` save), without being an optimistic participant
    itself — so a benign metadata edit can make the *next* top-level builder op see **one harmless `409`**
    (a "refresh", no lost work). **Accepted in 1b-i** (we do not scope a separate structural-only token).
  - **Element reorder/delete:** the **parent unit's** `updated` (which element ops bump, above). The
    **element-list fragment emits the parent unit's `updated` as its `data-updated`** — there is **no
    element-derived token** (1a `Element` rows have no `updated`). Out-of-band element creation
    (admin/`seed_demo_course`) need not bump the unit; the **first builder element op establishes the
    boundary**, which is sufficient because the token's job is to detect *concurrent builder edits*.
  - Reorder and compaction **re-save every sibling whose `order` changed**, so their `updated` advances —
    a peer viewing a reordered sibling will get a `409` on their next write to it (the residual "I saw a
    stale position" case resolves on the next interaction, not silently mid-write).
- **Precedence (exact):** re-read row(s) → **compare token(s); any mismatch → `409`** (no write, no
  `clean()` run, body = freshly-rendered fragment of current state, client swaps it in with a "this changed —
  refreshed" cue). **All tokens match → run `clean()`/validation; failure → `422`** (in-panel error, no
  write). **Otherwise apply → `200`** with the updated fragment(s). Token is read from a `data-updated="<iso>"`
  attribute the server emits on each node/unit fragment (and the course/tree-pane root).

### Fragment & selection protocol

- A single-scope op (reorder, rename, delete-within-scope) returns the re-rendered **affected scope** fragment.
- A **re-parent touches two disjoint scopes** (source — compacted — and destination). **For 1b-i, re-parent
  re-renders the whole tree pane** (the recommended, least-error-prone choice — a two-fragment swap and a
  whole-pane replace are *not* equivalent for selection/`data-updated` bookkeeping, so the spec picks one).
  After a whole-pane replace the **client re-applies the current selection by node pk** (re-fetching the
  detail panel if needed). Single-scope ops still swap their one **`data-scope`** fragment.
- **`data-scope` value:** the scope's **parent node pk**, or the literal **`top`** for the `(course,
  parent=NULL)` scope. The client replaces the element whose `data-scope` matches the op's affected scope.
- **Top-level token freshness:** because a top-level Add/Re-parent/Delete bumps **`Course.updated`** (the
  token carried on the **tree-pane root**, `data-scope="top"` / its `data-updated`), a single-scope op that
  also bumps `Course.updated` **must re-emit the refreshed tree-pane-root `data-updated`** (re-render that
  root, or update its attribute) — otherwise the next top-level op reads a stale course token and spuriously
  `409`s. (Re-parent's whole-pane re-render gets this for free.)
- **Selection after destructive/move ops (made explicit):** if the **currently-selected node is deleted**, the
  detail panel re-selects and re-renders its **parent** (or the course root if it was top-level). If the
  selected node is **re-parented**, selection follows the node to its new location. On a `409`, **selection is
  preserved** and the fresh fragment is swapped in beneath it.

### No-JS fallback

- Without JS, the same routes accept standard form POSTs and the server returns a full builder page render
  (`302`-redirect-to-builder on success, re-render with errors otherwise). Reorder/Move are real submit
  buttons. The **"Move…" picker is a plain `<form>` GET→POST**: the GET renders the legal-destination form
  with the **moved node's token embedded as a hidden field** (the destination token is read server-side when
  the POST re-fetches the chosen `new_parent`, so a vanished destination still yields `409`). Course delete
  uses the GET confirm page (see Views). Functionality is preserved, just full-reload; the same
  token/precedence rules apply — a **stale token re-renders the full builder page with the "this changed"
  notice** (no fragment swap); the stale POST is **discarded** and the user re-opens the picker, which is
  rendered fresh with a **new hidden token** — so there is no stale-token resubmit loop.

---

## Security, validation & i18n

- **Access:** `@login_required` + the canonical manage predicate (`owner_id == user.id OR
  user.has_perm("courses.change_course")`; no `is_staff`) on every `/manage/` route;
  `courses.add_course`/`delete_course` perms gate create/delete (Platform Admin Group). Object scoping mirrors
  1a: pk converter → exists (404) → course/slug pairing (404, IDOR guard) → manage predicate (403). CSRF on
  all mutating endpoints.
- **Invariants:** server `ContentNode.clean()` is the authority for kind-depth, unit-leaf, `unit_type`, and
  the 1a child-revalidation rules; the builder only *offers* legal ops as UX. All writes via
  `full_clean()`/`save()` — **no `bulk_create`/`QuerySet.update()`** (preserves `TextElement` sanitisation
  and invariants).
- **Delete guards:** node delete confirm shows cascade counts; course delete (PA) uses a **GET confirm page**
  that renders live `Enrollment`/`UnitProgress` + cascade counts (so the guard works with JS off), and the
  **POST** performs the hard delete. All such counts are **advisory** — the deleting transaction re-reads
  current state, so a concurrent change between confirm and submit is handled by the cascade itself, never a
  `500` on a vanished row. **Deliberate 1b-i choice:** the POST hard-deletes unconditionally; if learner state
  appears *after* the GET confirm (so the extra warning was never shown), the delete still proceeds with **no
  re-prompt**. This is acceptable because course delete is a rare, PA-only action; a re-check-and-re-confirm
  gate is a deferred nicety.
- **i18n:** new strings via `gettext`, EN + real Polish, compiled. Builder chrome in the UI language;
  author-entered titles untranslated.

---

## Out of scope (explicit)

- **Element content editors, the editor ｜ preview page, "+ Add element," media manager** — Phase 1b-ii.
- **HTML element / course CSS/JS / per-unit JS / MathJax** — own Phase-1 slice (renders in 1b-ii's preview).
- **Per-course multi-admin (CA) assignment UI** — view 6.2, later (conflict-safety built now regardless).
- **Drag-and-drop reordering** — later polish; button-based + "Move…" picker ship now.
- **Soft-archive / slug-redirects / Subject inline-create** — deferred (YAGNI; noted for later).
- **Quiz authoring / question editors** — Phase 2 (`quiz` unit_type is selectable but inert, per 1a).
- **Course settings (CSS/JS files, colour-band config)** — HTML slice / Phase 3.
- **DRF API for authoring** — server-rendered fragments only.

---

## Likely task decomposition (for the plan)

1. `/manage/` URL surface + `views_manage.py` scaffold + manage-permission/group setup + access predicate
   helper (reused across views).
2. Course CRUD: `CourseForm`, My-courses-admin list, create/edit, delete + guards + confirm.
3. `OrderField` service helpers: re-parent + gap-compaction (with tests) — the deferred 1a operations.
4. Builder page shell: master-detail layout, tree render, node-detail panel fragment, empty/container-less
   states.
5. Node operations (add/rename/reorder/re-parent/delete) as fragment endpoints + vanilla-JS swap + no-JS
   fallback + the "Move…" picker (legal-target filtering).
6. Unit-settings panel (title/type/obligatory) + element list (reorder/delete) + seam links to 1b-ii.
7. Optimistic-concurrency contract (`updated` token, `409`/`422`, fresh-fragment swap) across all mutating
   endpoints.
8. i18n extraction + Polish + compile.
9. Playwright e2e + final DoD pass.
