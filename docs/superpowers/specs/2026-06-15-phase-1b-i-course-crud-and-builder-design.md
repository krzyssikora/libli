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
   is view 6.2, later). All checks go through **Django model permissions**, never hardcoded role strings
   (the RBAC re-sliceability cross-cutting principle), with an explicit object-level **`owner OR is_staff`**
   manage predicate.
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
   administers (**`owner` OR `is_staff`**). PAs see a **"New course"** action; non-PA owners do not. This
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
   yet, with a "add your first node" empty state) both render correctly.
4. **Node operations** (fragment `POST`s, owner+PA, CSRF-protected, each atomic in a transaction):
   - **Add** (`…/build/node/add/`): a new child under a chosen parent (or at top level). The UI offers
     **only kind-depth-legal kinds** (child kind strictly deeper than parent; root offers any). Created via
     `Model.save()`/`full_clean()` so 1a invariants hold; `order` auto-assigned at the end of the scope.
   - **Rename** (`…/build/node/rename/`): title only.
   - **Reorder** (`…/build/node/move/`): up/down within siblings (swaps `order` within the scope).
   - **Re-parent** (`…/build/node/move/`): to a kind-depth-legal new parent + position; rejects illegal
     targets with the model `clean()` error. Re-assigns `order` within the destination scope.
   - **Delete** (`…/build/node/delete/`): cascades descendants + their elements; **gap-compacts** the
     remaining siblings' `order` in the vacated scope.
   - Every operation returns the **re-rendered affected subtree fragment** (or a `409` fresh fragment on
     conflict, per #6 below).
5. **Unit settings** edit (within the builder panel): `title`, `unit_type` (lesson/quiz), `obligatory`,
   persisted via `full_clean()`/`save()` (1a's `unit_type` iff `kind=unit`, units-are-leaves invariants
   still enforced).
6. **Element list ops** (owner+PA, CSRF-protected): the unit panel lists the unit's `Element`s in `order`
   (resolving each GFK to its concrete type for a type label); **reorder** (`…/build/element/move/`, up/down
   within the unit's `OrderField` scope) and **delete** (`…/build/element/delete/`, cascading the concrete
   element + its join-row via the 1a `GenericRelation`, then **gap-compacting**). "+ Add element" / "Open
   editor →" render as **disabled/seam links** pointing at the (not-yet-built) 1b-ii route — present but
   inert in 1b-i.
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
9. **Access control & object scoping:** all `/manage/` routes are `@login_required` + a **manage predicate**
   (`owner_id == user.id OR user.is_staff`), with course creation/deletion additionally gated on the
   Django **`courses.add_course` / `courses.delete_course`** permissions (granted to the PA group). Node/
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
    404-before-403, empty-course and container-less-course rendering. A **Playwright e2e**: log in as PA →
    create course → build a small mixed tree → reorder + move a node → open a unit → reorder an element.
14. Full `pytest` green; `ruff` check + format clean; `manage.py check` clean; `makemigrations --check`
    clean; `collectstatic` clean.

---

## Data model

1b-i is **mostly activation of existing 1a hooks** — expect a small or empty migration beyond data/permission
setup.

- **`Course.owner`** (existing FK, inert in 1a) becomes the authoring anchor. The object-level manage
  predicate is `course.owner_id == user.id OR user.is_staff` (explicit `owner_id is not None` guard, as in
  1a's access predicate). No `Course↔admins` M2M is added (multi-admin assignment = view 6.2, later); the
  conflict-safety is built so multi-editor "just works" whenever that lands.
- **`Course.slug`** — auto-suggested from `title` on create (slugified, de-duplicated), editable, unique.
  On **edit**, changing the slug is allowed but is the author's responsibility (student/preview URLs use the
  slug); 1b-i does not add redirects for old slugs (YAGNI; note for later if it bites).
- **Model permissions** — the standard Django `add/change/delete/view_course` (and node/element) perms are
  assigned to the **PA group** (and `change` to a future CA path); the manage predicate adds object-level
  ownership on top. No custom permission classes needed.
- **`OrderField`** (1a, `courses/fields.py`) gains two operations used by the builder service layer:
  re-parent (assign next/inserted `order` within a new `(course, parent)` scope) and **gap-compaction**
  (renumber a scope's siblings 0..n after a delete or move-out). These are **service-layer helpers**, not
  new fields.
- **Concurrency token** — the existing **`ContentNode.updated`** / `Course.updated` `auto_now` field is the
  optimistic token. No schema change. (`Element` has no `updated` in 1a; element reorder/delete uses the
  **parent unit's** `updated` as the token — element ops are scoped to one unit, so the unit row is the
  natural conflict boundary.)

No new models. If a migration is needed it is for permission/group data only (via a data migration or a
management step) — `makemigrations --check` must stay clean.

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
| Delete course (6.3) | `/manage/courses/<slug>/delete/` | POST | PA | Confirm + guard; hard delete. |
| Builder (5.4) | `/manage/courses/<slug>/build/` | GET | owner+PA | Master-detail tree + panel. |
| Node detail panel | `/manage/courses/<slug>/build/node/<int:pk>/` | GET | owner+PA | Right-panel fragment for a node. |
| Node add | `…/build/node/add/` | POST | owner+PA | New child; returns subtree fragment. |
| Node rename | `…/build/node/rename/` | POST | owner+PA | Title; returns fragment. |
| Node move | `…/build/node/move/` | POST | owner+PA | Reorder or re-parent; returns fragment(s). |
| Node delete | `…/build/node/delete/` | POST | owner+PA | Cascade + compact; returns fragment. |
| Element move | `…/build/element/move/` | POST | owner+PA | Reorder within unit; returns element-list fragment. |
| Element delete | `…/build/element/delete/` | POST | owner+PA | Cascade join-row + compact; returns fragment. |

**Builder page** = master-detail: a **tree pane** (indented, kind-badged rows with per-row action affordances)
and a **detail panel** (course metadata for the root; container settings; unit settings + element list). The
panel content is fetched as a fragment on node selection. The student outline/lesson views from 1a are
**untouched**.

---

## Builder interaction & concurrency mechanics

- **Fragment protocol.** Each mutating `POST` (CSRF token included) targets node/element by pk + carries the
  optimistic token (`updated`). The server validates + applies in a `transaction.atomic()` block and returns
  the re-rendered **affected subtree** (for node ops) or **element-list** (for element ops) fragment;
  vanilla JS swaps it into the DOM. The selection/panel is preserved where possible.
- **Add.** UI offers only kind-depth-legal child kinds. New node `full_clean()`d + `save()`d; `order`
  auto-assigned at end of the destination scope.
- **Reorder (up/down).** Swap `order` with the adjacent sibling in the same `(course, parent)` scope.
- **Re-parent ("Move…").** Picker lists only legal destination parents (kind-depth) + "top level" and a
  position; server re-validates via `clean()`, moves the node (and its subtree) into the new scope, assigns
  `order`, and **compacts** the source scope.
- **Delete.** Confirm dialog shows descendant + element counts; server cascades and **compacts** the scope.
- **Element reorder/delete.** Scoped to the unit's `Element` `OrderField`; delete cascades the concrete
  element + join-row (1a `GenericRelation`) and compacts.
- **Optimistic conflict — exact contract.** On every mutating op the view re-reads the target row inside the
  transaction and compares its `updated` to the client-supplied token. **Mismatch → `409`**, no write, body
  = freshly-rendered fragment of current state (the client swaps it in and shows a "this changed — refreshed
  to the latest" cue). **Match → apply**, return the updated fragment (`200`). Token is read from a
  `data-updated="<iso>"` attribute the server emits on each node/unit fragment. (Element ops use the parent
  **unit's** `updated` as the token.) A `clean()`/validation failure (illegal op, e.g. concurrent edit made
  a move illegal) → **`422`** with the in-panel error message, no write.
- **No-JS fallback.** Without JS, the same routes accept standard form POSTs and the server returns a full
  builder page render (302-redirect-to-builder on success, re-render with errors otherwise). Move is via the
  up/down/Move buttons as real submit buttons. Functionality is preserved, just full-reload.

---

## Security, validation & i18n

- **Access:** `@login_required` + manage predicate (`owner_id == user.id OR is_staff`) on every `/manage/`
  route; `courses.add_course`/`delete_course` perms gate create/delete (PA group). Object scoping mirrors
  1a: pk converter → exists (404) → course/slug pairing (404, IDOR guard) → manage predicate (403). CSRF on
  all mutating endpoints.
- **Invariants:** server `ContentNode.clean()` is the authority for kind-depth, unit-leaf, `unit_type`, and
  the 1a child-revalidation rules; the builder only *offers* legal ops as UX. All writes via
  `full_clean()`/`save()` — **no `bulk_create`/`QuerySet.update()`** (preserves `TextElement` sanitisation
  and invariants).
- **Delete guards:** node delete confirm shows cascade counts; course delete (PA) confirms and warns when
  `Enrollment`/`UnitProgress` exist; hard delete.
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
