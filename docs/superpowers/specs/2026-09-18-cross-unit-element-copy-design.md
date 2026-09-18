# Cross-unit element copy

## Purpose

Authors can already mark an element (⊹) and move or copy it to another slot **inside the
same unit** (`element_clip` / `element_paste`). They cannot put a copy of an element into a
*different* unit: `paste_allowed` clause 0 refuses with `wrong_unit`, and `_clip_context`
hides the mark on every other unit.

This feature lets an author mark an element in unit X, go to unit Y **of the same course**,
and paste a **copy** there -- into any admissible slot, or directly above a chosen element.

A real cross-unit *move* is deliberately out of scope: learner data is keyed by unit
(`UnitProgress.seen_element_ids` / `element_state`, `QuizSubmission` → `QuestionResponse`,
`notes.Note.unit`), so moving a join row would strand it. A copy mints new pks and touches
no learner data. An author who wants a move copies and then deletes the original.

## Owner decisions (verbatim — a reviewer may NOT reverse these without asking the owner)

These were approved one by one in the brainstorm. A review catch that conflicts with one of
them is **Disputed**, never applied.

| # | Decision |
|---|---|
| D1 | Copy only. A real cross-unit MOVE is out of scope (UnitProgress / QuestionResponse / Note are keyed by unit). |
| D2 | Same course only. Cross-course copy is out of scope (MediaAsset is per-course). |
| D3 | The existing session mark follows the author to other units of the same course; the destination unit shows paste slots. |
| D4 | "Copy before this element" is supported in the DESTINATION unit (not added to the source unit, whose rows keep only "Move before"). |
| D5 | Source-unit banner gains a "Copy to another unit…" control: a server-rendered `<details>` listing the course's units (reusing the link picker's tree), each unit a plain link to its editor page; current unit shown but not a link. Works without JS, no new endpoint. |
| D6 | Destination banner: "Selected: <label> — from <Unit>" where <Unit> links back to the source unit editor; cancel as today; "Copy to another unit…" also present. |
| D7 | Outside the source unit only COPY buttons render; move never appears. |
| D8 | Mark persists after a copy (as in-unit copy does). A mark from another course is ignored (not cleared). |
| D9 | Replace the existing 📋 emoji on the paste-before button with a monochrome SVG (project icon rule); the new copy-before button uses an SVG too. |

**Implementation notes on two decisions** (interpretation, not reversal):

- **D5 — "reusing the link picker's tree".** `_link_picker_node.html` cannot be included
  as-is: its rows are JS-driven `role="treeitem"` widgets carrying a `data-href` to the
  *student* permalink and no `<a>` at all. What is reused is the picker's **data source**
  (`_children_map(course)`, one query, `courses/views_manage.py:146`) and its **badge
  markup** (the L / Q / kind badges). A new partial renders the same tree as nested lists
  of plain `<a href="{% url 'courses:manage_editor' ... %}">` links.
- **D9 — which buttons.** The slot "Move here" button also uses 📋, and the slot "Copy
  here" button and the row's "Duplicate" button (`_element_row_controls.html`) use the ⧉
  text glyph. All five (slot move, slot copy, move before, copy before, Duplicate) switch
  to **two** monochrome SVG symbols, one for move and one for copy, so the same action
  always shows the same icon. `aria-label` / `title` strings are unchanged apart from the
  new "Copy before this element".

## Behaviour (what the author sees)

### Source unit (where the element was marked)

- Banner: `⊹ Selected: <label>` + cancel (unchanged) + **"Copy to another unit…"**.
- "Copy to another unit…" is a `<details>`; its body is the course tree (parts → chapters →
  sections → units) with the L/Q badges. Each **unit** is a link to its editor page. The
  current unit is rendered as plain text, not a link, and marked `aria-current="page"`.
  Container nodes (part / chapter / section) are plain text headings for their sublists.
- Slots and rows: unchanged. Slots offer move + copy; rows offer "Move before" only (D4).

### Destination unit (any other unit of the same course)

- Banner: `⊹ Selected: <label> — from <source unit title>`, where the title links to the
  source unit's editor page; cancel; "Copy to another unit…" (same `<details>`, with *this*
  unit as the non-link current one).
- Every slot that `paste_allowed(..., mode="copy")` admits shows **only** the copy button.
- Every row whose slot admits a copy shows **"Copy before this element"**.
- No move control anywhere (D7).
- Interactive elements (the add menu's "Interactive" group — gates, fill-table, spoiler,
  step-by-step, checklist, guess-the-number), alone or inside a container, cannot be
  copied into a quiz unit (§2 clause 2d).
- If no slot admits the copy (e.g. a callout holding a question, marked for a quiz), the
  banner says **"Nothing can be pasted into this unit."** instead of leaving the author
  with a banner and no controls.
- Containers force-open while a mark is active, as they already do in the source unit.

### Lifetime of the mark

- A copy keeps the mark (D8), in either unit, so one original can seed many places.
- Cancel, or ⊹ on any row in any unit, replaces / clears the mark, exactly as today
  (`element_clip` already works against whichever unit the form posts).
- A mark whose element was deleted is cleared lazily on the next render (as today).
- A mark from another course is ignored — not cleared (D8).

## Architecture / components

### 1. `_clip_context(request, unit)` (`courses/views_manage.py`)

Classify the session mark against the rendered `unit`:

| Mark state | Result |
|---|---|
| none | empty context (as today) |
| `clip.unit == unit.pk` | **same-unit** branch — today's logic unchanged, plus the new keys below |
| `clip.unit` is another unit of `unit.course`, marked element exists in it | **cross-unit** branch |
| marked element or its unit no longer exists (any course) | clear the mark, empty context |
| `clip.unit` belongs to another course, element exists | empty context, mark kept (D8) |

Lookups, in order (the same-unit branch keeps today's single `unit.elements` lookup):

1. `marked = Element.objects.select_related("unit").filter(pk=clip["element"],
   unit_id=clip["unit"]).first()`.
2. Not found → the mark is **dead** in every case (its element was deleted, or its unit
   was, in whatever course) → clear the mark, empty context. No further query is needed
   to tell the cases apart, because none of them is worth keeping.
3. Found in another course (`marked.unit.course_id != unit.course_id`) → empty context,
   mark kept (D8). Cost accepted: one query per editor render while such a mark is
   pending; no prefetch is paid for it.
4. Found in this course → load the root's `content_object` (one GFK query — the map does
   not supply it for this instance; read by `_slot_cap`, `has_interactive` and
   `clip_label`), then the cross-unit branch.

The `ValueError` / `TypeError` guard around these lookups is kept (see its existing
comment). If it fires (a non-numeric `clip["unit"]` or `clip["element"]`), the mark is
**cleared** and the context is empty — today's outcome for a guarded lookup.

**Cross-unit branch:**

- `pairs, _dest_children = enumerate_slots(unit)` — the destination's slots.
- `facts = subtree_facts(marked, children_map=unit_children_map(marked.unit))`. The
  destination map does not contain the marked subtree, so it cannot be reused. The map
  builder is **extracted** from `enumerate_slots` into a helper `unit_children_map(unit)`
  in `courses/builder.py`, which `enumerate_slots` then calls — one copy, no drift. Cost:
  one query plus one GFK prefetch query per distinct content type (the prefetch is
  required: `nested_question` reads `content_object`).
- `copy_slots` = the slot keys where `paste_allowed(unit, marked, parent, tab, "copy",
  facts=facts, dest_depth=dest_depth)` is OK.
- `move_slots = set()`.
- `before_slots = set(copy_slots)` — the only clause that distinguishes an append from a
  positional placement is clause 5, which is move-only.
- `clip_noop_pk = ""` — a copy is never a no-op.
- `clip_active = True`, `clip_element_pk = str(marked.pk)`, `clip_label` computed as
  today. `clip_element_pk` is load-bearing even though the marked row is not in this
  unit: `paste_before_button` returns `show: False` whenever it is empty, and the cancel
  form posts it — blanking it would silently remove every "Copy before" button.

**New context keys, both branches:**

- `clip_mode` — `"move"` in the same-unit branch, `"copy"` in the cross-unit branch. Read
  by `paste_before_button` to choose the mode it posts and the icon/label it shows.
- `clip_source_unit` — the source `ContentNode` in the cross-unit branch, `None` otherwise.
  Drives the "— from <Unit>" part of the banner.
- `copy_units_map` / `copy_units_top` — `_children_map(unit.course)` and its `None` roots,
  for the "Copy to another unit…" tree. Built **only when a mark is active**; the empty
  context carries empty values and does no query.

- Values in the fixed `empty` dict (shared by `_editor_page` and
  `_render_editor_fragments`, so both builders get every key): `clip_mode=""`,
  `clip_source_unit=None`, `clip_nothing_fits=False`, `copy_units_map={}`,
  `copy_units_top=[]`.
- `clip_nothing_fits` — `True` in the cross-unit branch when `copy_slots` is empty (e.g. a
  callout holding a question, marked for a quiz; or a subtree too deep for every slot),
  `False` otherwise. The banner then says "Nothing can be pasted into this unit." so the
  author is not left with a banner and no controls. No per-reason text: the reasons can
  differ per slot.

Comments that become false and are rewritten:

- `_clip_context`'s docstring: the "five mark-dependent context keys" count, and "a
  marked element … that belongs to another unit, is treated as absent".
- The `clip.get("unit") != unit.pk` comment inside `_clip_context` ("Rendering ANOTHER
  unit: ignored, not cleared").
- `element_paste`'s comment describing `clip.unit != unit.pk` as a 409 path.
- `element_clip`'s docstring, which says the paste "re-resolves it through
  `_locked_element(course, ...)`" — still true for the source, but the paste now also
  locks the destination.

### 2. `paste_allowed(unit, marked_join, dest_parent, tab, mode, ...)` (`courses/builder.py`)

`unit` is the **destination** unit throughout (it already is in the in-unit case).

- **Clause 0 (rewritten)**, ordered so the common in-unit case never loads
  `marked_join.unit`:
  - `marked_join.unit_id == unit.pk` → pass (no further clause-0 check for the marked
    element; this short-circuit is what keeps in-unit renders free of an extra query).
  - otherwise `mode == "move"` → `wrong_unit` (D1);
  - otherwise `marked_join.unit.course_id != unit.course_id` → `wrong_unit` (defence in
    depth — the endpoint already 409s a foreign-course element, see §4 step 1).
  - `dest_parent is not None and dest_parent.unit_id != unit.pk` → `wrong_unit` (unchanged).
- **Clause 4 (`into_own_subtree`)** needs no change: across units `dest_parent` is never in
  the source subtree, and the check stays correct in-unit.
- **New clause 2c (`question_in_quiz`, whole subtree):** if `unit.unit_type == QUIZ` and
  `facts.nested_question` → `question_in_quiz`. It applies in **both** branches of the
  function (top-level destination and container destination). It is evaluated **after**
  clause 2b in the container branch, and at the same precedence position in the top-level
  branch, so the documented reason precedence is: `wrong_unit, into_own_subtree,
  not_a_container, unknown_slot, type_not_nestable, question_in_quiz, too_deep, own_slot`
  — i.e. unchanged; 2c reports the same key as 2b.
- **New clause 2d (`interactive_in_quiz`, whole subtree, CROSS-UNIT ONLY):** if
  `marked_join.unit_id != unit.pk` and `unit.unit_type == QUIZ` and
  `facts.has_interactive` → `interactive_in_quiz`. *Pipeline default, not an owner
  decision — flagged to the owner in the PR body.* Rationale: quiz units hide the add
  menu's whole "Interactive" group (`_add_menu.html`, `{% if not unit_is_quiz %}`) and
  student state saves require a lesson (`require_lesson=True` in `courses/views.py`), so
  offering "Copy here" for a stepper / checklist / gate in a quiz would hand the author a
  control the add menu deliberately withholds. Cross-unit only, because in-unit such
  elements can already legitimately sit in a quiz (a lesson flipped to quiz keeps them;
  `rename_node` checks only nested questions), and refusing their in-unit move would be a
  regression. Evaluated in both branches (top level and container), after 2b/2c and
  before clause 3. Message (new `PASTE_REFUSAL_MESSAGES` key): "Interactive elements can
  only be placed in a lesson unit." → Polish "Elementy interaktywne można umieszczać tylko
  w lekcjach." Resulting reason precedence: `wrong_unit, into_own_subtree,
  not_a_container, unknown_slot, type_not_nestable, question_in_quiz,
  interactive_in_quiz, too_deep, own_slot`.
- The interactive type set is a new module constant `QUIZ_EXCLUDED_TYPE_KEYS` in
  `courses/builder.py`, a frozenset of **transfer keys** (the values `model_to_key`
  returns, `courses/transfer/export.py` `SERIALIZERS`) for the nine types of the add
  menu's Interactive group: `reveal_gate`, `fill_gate`, `switch_gate`, `switch_grid`,
  `fill_table`, `spoiler`, `stepper`, `mark_done`, `guess_number`. A **derived** drift
  guard pins it to the template: render the add menu for a lesson and for a quiz (same
  depth, not nested), take the difference of the `data-add-type` **card names**, map each
  through `_NESTABLE_FORM_KEY_ALIASES.get(name, name)` (the existing card-name → transfer
  key map, `courses/builder.py`), and assert the result equals the frozenset — never a
  hard-coded count.
- Clause 2b's comment that the root-only check is "sound … because clause 0 (wrong_unit)
  makes cross-unit pastes impossible" is rewritten: 2c now closes the gap it described.
- The docstring gains one paragraph on the cross-unit case.

### 3. `SubtreeFacts` / `subtree_facts` (`courses/builder.py`)

- New field `nested_question: bool` — true iff any node **strictly below** the root
  (relative depth ≥ 1) is a question. "Question" uses the same model set
  `unit_has_nested_question` uses (`courses.richtext.CONCRETE_QUESTION_MODELS`, the
  WIDE set — see that function's docstring for why narrowing reopens a hole), tested via
  `isinstance(join.content_object, tuple(CONCRETE_QUESTION_MODELS))`.
- The root itself is excluded: a question at the root pasted at top level of a quiz is
  legal; a question at the root pasted into a container is already caught by 2b.
- New field `has_interactive: bool` — true iff **any** node of the subtree, root
  included, has `model_to_key(type(content_object)) in QUIZ_EXCLUDED_TYPE_KEYS`.
  `subtree_facts` imports `model_to_key` (and `CONCRETE_QUESTION_MODELS`)
  **function-locally**, like `paste_allowed` and `unit_has_nested_question` do — a
  module-level import risks the cycle the existing comments warn about. A dangling GFK
  gives `type(None)`, for which `model_to_key` returns `None`, so it is never counted as
  interactive (nor, by `isinstance`, as a question).
- Cost: the walk already visits every node and `_slot_cap` already reads
  `content_object` per node, so both fields add no query when `children_map` carries the
  GFK prefetch. Without a map the walk pays one children query plus one GFK query per node
  — today's cost for `_slot_cap`, unchanged.
  - **Cross-unit paste:** `paste_element` computes `facts = subtree_facts(el,
    children_map=unit_children_map(source_unit))` once and passes it to `paste_allowed`.
  - **In-unit paste:** unchanged — `paste_allowed` computes facts itself with today's
    per-subtree walk. Building a whole-unit map there would make every in-unit paste of a
    leaf load the entire unit, a cost today's endpoint does not pay.
  Both fields are computed unconditionally, not only for quiz destinations: one
  `isinstance` / key lookup per node.

### 4. `paste_element(...)` (`courses/builder.py`)

New keyword argument `dest_unit_pk`. The view passes the posted `unit`. When it is absent
or equals the marked element's unit, the **lock/token path** is today's
(`_locked_element` + `_check_token(unit.updated, …)`); the two deliberate in-unit
behaviour changes (copy may carry `before`; clause 2c) are listed under Out of scope.

**Return value:** always `(dest_unit, placed)` — on the in-unit path the destination IS
the element's unit, so this is today's `(unit, placed)`. The view rebinds `unit` from this
tuple and renders its fragments, so returning the source would paint unit X's editor into
Y's page.

**Mode validation stays first**, on both paths, before any lookup or lock: `mode not in
("move", "copy")` → `NestingError` (400), exactly as today — so an unknown mode with a
stale or foreign mark is still a 400, never a 409.

Order of operations, inside the existing `@transaction.atomic`. When `dest_unit_pk is
None` (direct callers that predate this feature), step 1 is **skipped** and the function
runs today's path unchanged: `_locked_element` + `_check_token(unit.updated, …)`, then
steps 4–9 with `source_unit = dest_unit = unit`. When `dest_unit_pk` is given, step 1
**always** runs first and is the discriminator between the two paths:

1. **Resolve the source unit pk, unlocked:**
   `Element.objects.filter(pk=element_pk, unit__course=course).values_list("unit_id",
   flat=True).first()`, wrapped in `try/except (ValueError, TypeError)` → `ConflictError`
   (a non-numeric session element must stay a 409, as `_locked_element`'s guard makes it
   today). No row → `ConflictError` (409). Because of the `unit__course` filter, an
   element of **another course** also ends here as a 409 and is never loaded; clause 0's
   course comparison (§2) is therefore defence in depth, reachable only by direct callers
   and unit tests. `dest_unit_pk` is int-coerced under the same guard.
   - `src_pk == dest_unit_pk` → **in-unit path**: today's
     `_locked_element` + `_check_token(unit.updated, …)`, then steps 4–9 with
     `source_unit = dest_unit = unit`. Steps 2–3 below are skipped.
   - otherwise → **cross-unit path**, steps 2–9.
2. **Lock both units in ascending pk order, taking the SOURCE through `_locked_element`.**
   Every existing **element-level** writer locks exactly one unit, and in-unit writers on
   an element take it via `_locked_element` (element row + unit row in one joined
   `SELECT … FOR UPDATE`). The copy reuses that exact shape for the source, so against any
   element-level writer it behaves like one more in-unit writer:
   - `src_pk < dest_pk`: `el, source_unit = _locked_element(course, element_pk)`, then
     `dest_unit = _locked_unit(course, dest_unit_pk)`.
   - `dest_pk < src_pk`: `dest_unit = _locked_unit(course, dest_unit_pk)` first, then
     `el, source_unit = _locked_element(course, element_pk)`.
   Two opposite-direction copies (X→Y, Y→X) both take the lower-pk unit first, so they
   cannot deadlock with each other; a copy holding Y while waiting for (e, X) cannot
   deadlock with an element-level writer on X, because that writer never wants Y.
   **Not covered — node-level writers that lock several unit rows.** Before this feature
   no transaction held two unit rows, so these cycles are new:
   - `reorder_node` locks **every sibling** of a node with `select_for_update()` in
     `("order", "pk")` order — tree order, not pk order. When X and Y are siblings whose
     tree order runs opposite to their pk order, a unit reorder in that section can
     deadlock with a copy between them.
   - `reparent_node`, and `compact_nodes` / `assign_orders_nodes` reached from node
     add / delete, lock or update several sibling `ContentNode` rows.
   - A cascade delete of an ancestor node (section / chapter / part) or of the course
     touches many units in an order Postgres chooses.
   Postgres detects the cycle and aborts one transaction (SQLSTATE 40P01). This is
   **accepted** — both sides must be in flight at once, on the same section — and made
   harmless on the copy side: `element_paste` maps it to the ordinary 409 (§7). The
   docstring lists exactly these cases and the mapping, and claims nothing beyond them.
   - `_locked_element` raising → `ConflictError` (element or source unit gone).
   - `_locked_unit` (existing; filters `kind=UNIT`, raises `ConflictError`) covers a
     missing or non-unit destination — no separate kind check.
   - `source_unit.pk != src_pk` (the element changed unit between steps 1 and 2 — no code
     path does this today) → `ConflictError`.
3. **Token check against the destination only:** `_check_token(dest_unit.updated,
   unit_token)`. The source is only read; its row lock stops a concurrent edit changing it
   mid-export. A stale *source* is not an error.
4. `before`: `_resolve_before(dest_unit, el, before)` — the anchor must be in the
   destination. The "`before` is a move-only argument" refusal is **removed**: copy now
   accepts `before` in both the cross-unit and the in-unit case (the in-unit UI simply
   never renders a copy-before button, per D4).
5. Otherwise `_parse_scope_ref(dest_unit, parent_ref, tab)`.
6. `paste_allowed(dest_unit, el, dest_parent, tab_id, mode, facts=facts,
   positional=anchor is not None)`, where on the cross-unit path `facts` is computed once
   from `unit_children_map(source_unit)`, and on the in-unit path `facts=None` as today
   (§3).
   A cross-unit `mode == "move"` is refused **here** by clause 0 with `wrong_unit` — only
   once steps 4–5 have accepted the slot/anchor; a malformed or vanished one answers 400 /
   422 `parent_gone` first.
7. `_copy_into(el, source_unit, dest_unit, dest_parent, tab_id, anchor=anchor)`.
8. `dest_unit.save(update_fields=["updated"])`. The source unit's `updated` is **not**
   touched on a cross-unit copy.
9. `return dest_unit, placed`.

The docstring states the lock order and the argument above, next to the code, and claims
nothing beyond it (no concurrency test — see Testing).

### 5. `_copy_into` (`courses/builder.py`)

Signature becomes `_copy_into(el, source_unit, dest_unit, dest_parent, tab_id,
anchor=None)`:

- `build_element_export(source_unit, el)` — its assertion that the root belongs to the
  exported unit requires the **source**.
- `graft_elements(document, media_map, dest_unit)`. `media_map` maps to the source's
  `MediaAsset` rows, which is correct because both units are in the same course (D2).
- Everything the export carries travels unchanged — including a question's quiz marking
  fields (`marking_mode`, `max_attempts`, `max_marks`), which the lesson editor never
  shows (`_marking_fields.html` is quiz-only). A question copied from a lesson into a quiz
  therefore arrives with whatever values it had; this is accepted, and the author reviews
  them in the quiz editor, where they are visible. A service test pins that they carry
  over unchanged.
- Set `parent` / `tab_id` on the new root and save them (unchanged).
- `place_element(new_join, dest_unit, None, before=anchor)` — append when `anchor` is None,
  otherwise land directly above it.

### 6. `graft_elements` docstring (`courses/transfer/importer.py`)

Point 2 currently says skipping `_rewrite_links` is dead work because the call is
"provably a NO-OP". For a cross-unit graft that is false: `link_nodes` can name the
**source** unit, the fabricated `node_map` maps the source unit's export id to the
**destination**, and running `_rewrite_links` would silently repoint a link to the source
unit at the destination. The skip is therefore a **correctness requirement**. The
docstring is rewritten to say so; the code is unchanged. Edit is line-count neutral where
practical (the repo carries line citations into this file).

### 7. `element_paste` view (`courses/views_manage.py`)

- `clip.unit != unit.pk` no longer 409s by itself. Instead: if the clip is empty → 409 (as
  today); otherwise call `paste_element(..., dest_unit_pk=unit.pk)` and let the service
  decide (same-course, mode, admissibility).
- `mode == "move"` still clears the mark on success; a copy keeps it (unchanged rule).
- **Deadlock abort → 409.** The `paste_element` call is additionally wrapped in
  `except django.db.OperationalError as exc:` — if `getattr(exc.__cause__, "sqlstate",
  None) == "40P01"` — one `__cause__` hop, which is where Django's
  `DatabaseErrorWrapper` (`raise … from exc_value`) puts psycopg's `DeadlockDetected`.
  (`tests/deadlock_retry.py`'s `is_deadlock` walks the whole chain; it is test code and
  not importable here, and one hop is sufficient for this call site.) Answer via the
  existing `_element_conflict(request, course)` 409 path; any other `OperationalError`
  re-raises. The project does not set `ATOMIC_REQUESTS`, so the service's own
  `@transaction.atomic` has already rolled back and the view is free to render. The
  mark is kept.
- Error mapping is unchanged (see Error handling).

### 8. Templates and tags

- **Banner layout.** The banner is today a `<span id="clip-banner">` as the third child of
  `.pane-head`, a two-child `display:flex; justify-content:space-between` row. A
  `<details>` holding nested lists is flow content and invalid inside a `<span>`, and an
  open course tree inside the flex header would wreck it. So:
  - The banner becomes `<div id="clip-banner" class="clip-banner">` — **id unchanged**
    (`tests/test_e2e_clipboard.py`, `test_e2e_paste_before.py` and
    `test_e2e_before_after.py` locate `#clip-banner`) — still inside
    `[data-scope="editor"]` (the existing comment explains why it must stay there).
    Order of the pane's children: `.pane-head`, then `#clip-banner`, then the existing
    `#editor-error` slot, then `.pane-body` — so a refusal message sits between the
    banner and the list it refers to. `.pane-head` goes back to exactly two children;
    the template comments about the third child and about the error slot's position are
    rewritten accordingly.
  - Structure: a first-line wrapper `<div class="clip-banner__line">` holding
    `⊹ Selected: <label>`, the optional "— from <link>", and the cancel form; then the
    optional "Nothing can be pasted into this unit." paragraph; then
    `<details class="clip-banner__units">`.
  - **CSS rewrite** (`courses/static/courses/css/editor.css`, the `.clip-banner` block and
    its comments, currently ~lines 465–506):
    - The pill styling moves from `.clip-banner` to `.clip-banner__line`: it keeps the
      existing measured design — one line, `nowrap` + `overflow: hidden` + ellipsis, the
      cancel form out of flow in the reserved trailing padding lane. The first line
      **ellipsises, it does not wrap**, at every width including narrow viewports; the
      comment's measured rationale (floating the ✕ doubled the head height) is kept.
      Dropped from the pill: `max-width: 60%` and `margin-inline-start: auto` (they only
      made sense as a flex item sharing the head); the line now spans the pane's
      **content column** (the same inline inset as the pane head and body), not the full
      pane width.
    - `.clip-banner` itself becomes a plain block container: no overflow clipping, no
      `nowrap`, so the open `<details>` list is never clipped. `.pane` has no inline
      padding of its own — `.pane-head` and `.pane-body` each supply `var(--space-4)` —
      and `editor.css` already records the defect a bare child causes (`.op-error` was
      measured spanning the full pane, border on the pane border). So the banner gets the
      same inset as that fix: `.editor-pane > .clip-banner { margin: var(--space-3)
      var(--space-4) 0; }`.
    - The two `.pane-head:has(.clip-banner)` rules and their comments are **deleted** —
      the banner is no longer in the head, so they would match nothing.
  - An open `<details>` **pushes the pane content down** (no overlay, no JS). Its list
    scrolls inside itself (`overflow-y: auto`), so a course with hundreds of units
    (mat-pp) never grows the page.
  - **Wide, viewport-locked layout (≥ 70rem).** There `body.editor-page` is fixed at
    `100vh` with `overflow: hidden`, `.editor-pane` is a fixed-height flex column and only
    `.pane-body` scrolls (`editor.css`, the two-pane block). The banner is a
    non-scrolling flex item above `.pane-body`, so an open list takes height from it.
    The list is therefore capped at `max-height: min(35vh, 18rem)` in every layout,
    and `.clip-banner` gets `flex: none` so it is never squeezed itself; `.pane-body`
    (already `min-height: 0` in that layout — the implementer confirms) absorbs the rest.
    At 1280×720 this leaves `.pane-body` at least ~40% of the pane with the list open.
  - Screenshots: narrow (≤ 480px), and a short wide viewport (1280×720, split mode) with
    the list open.
  - Narrow viewport (≤ 480px): the first line ellipsises, the ✕ stays visible; checked in
    the screenshots.
  - The tree is part of `[data-scope="editor"]`, so every editor op re-renders it while a
    mark is pending, and an open `<details>` closes after each swap. Closing is intended
    (the list is a navigation aid; after a paste the author is done with it). Render cost:
    one recursive include per node. The implementer times one marked editor op on the
    largest local course (mat-pp) before and after, and reports the delta in the PR; if
    it adds more than ~10% to the op, the tree is rendered flat (one loop over a
    pre-ordered list with a depth class) instead of recursively.
- **Banner text / i18n shape.** The existing msgid `Selected: %(clip_label)s` is kept
  unchanged. The source part is a separate, contextual msgid with the link OUTSIDE it, so
  no HTML reaches translators:
  `— {% translate "from unit" context "clip banner" %} <a href="{% url 'courses:manage_editor' … %}" data-math-title>{{ clip_source_unit.title }}</a>`.
  Polish: "from unit" (context "clip banner") → **"z jednostki"**. Other new msgids and
  their Polish: "Copy to another unit…" → "Kopiuj do innej jednostki…"; "Copy before this
  element" → "Kopiuj przed ten element"; "Nothing can be pasted into this unit." → "Do
  tej jednostki nie można niczego wkleić." The implementer checks the catalogue's existing
  rendering of "unit" and aligns these if it uses a different noun.
- New partial `templates/courses/manage/editor/_copy_units_tree.html` (+ a recursive node
  partial) rendering `copy_units_top` / `copy_units_map` as nested `<ol>` of links, badges
  reused from the link picker. Titles keep `data-math-title` like the editor crumb does.
- **Typesetting titles after a swap.** `math.js` typesets `[data-math-title]` only in its
  initial whole-document pass; after a swap, `editor.js` `applyFragments` typesets the
  **preview** pane only. The editor crumb never needed more (it lives outside the swapped
  scope), but the banner link and the tree live **inside** `[data-scope="editor"]`, so
  without a change every editor op while a mark is pending would show raw `\(…\)`.
  `applyFragments` therefore also runs, on the swapped editor scope,
  `scope.querySelectorAll("[data-math-title]").forEach(renderPreviewMath)` — only those
  nodes, never a whole-pane typeset (which would also reach row labels and forms).
- `paste_before_button` tag: pass `mode = context["clip_mode"]` through.
  `_paste_before_button.html` posts `mode={{ mode }}` and shows the move or copy SVG with
  label "Move before this element" / "Copy before this element".
- `_paste_buttons.html`: 📋 and ⧉ replaced by the two SVG symbols (D9); likewise the
  Duplicate button's ⧉ in `_element_row_controls.html`.
- Two new `<symbol>`s (move, copy) in the editor's inline sprite in `editor.html`, drawn as
  single-colour line icons with `currentColor`, matching the existing `ed-*` symbols.
- CSS for the banner and the `<details>` list uses existing editor tokens; both light and
  dark themes.
- i18n: **both** catalogues (`locale/pl` and `locale/en`) are regenerated with
  `makemessages` — never hand-edited — so the `en` catalogue gains the new msgids
  (including the `msgctxt "clip banner"` entry) with empty msgstrs, like its existing
  entries. Only `pl` gets translations (above), with any fuzzy pre-fills cleared; both
  `.mo` files are recompiled.

## Data flow

```
source unit X editor
  ⊹ on element e        → element_clip  → session[clip] = {unit: X, element: e}
  "Copy to another unit…" → <a href=/…/unit/Y/edit/>   (plain navigation, no POST)

destination unit Y editor (GET)
  editor → _clip_context(request, Y)
         → cross-unit branch: enumerate_slots(Y), subtree_facts(e, source map of X),
           paste_allowed(Y, e, slot, "copy") per slot
         → copy buttons + copy-before buttons + banner "from X"

  copy / copy-before (POST element_paste, unit=Y, unit_token=Y.updated, mode=copy[, before])
         → paste_element(course, e, …, dest_unit_pk=Y)
             lock (e+X via _locked_element) and Y in ascending unit-pk order
             → check Y token → resolve slot/anchor in Y
             → paste_allowed(Y, …) → _copy_into(e, X, Y, …) → Y.updated bumped
         → editor fragments for Y, mark kept
```

## Error handling

All through channels the editor already renders; no new error UI.

| Situation | Response |
|---|---|
| No mark in session | 409 (`_element_conflict`), as today |
| Destination unit token stale | 409, destination reloads, as today |
| Marked element or its unit deleted before the paste | 409; the mark is cleared on the next render (§1 lookups) |
| Destination unit not in this course / not a unit | 409 (`_no_unit_409` path via `_clip_unit`), as today |
| Inadmissible placement (too deep, question in quiz, interactive in quiz, not nestable, unknown slot) | 422 via `_refused` with the reason message; mark kept |
| Deadlock abort (40P01) against a node-level writer — sibling reorder / reparent / add / delete, ancestor cascade delete (rare) | 409, reload, mark kept (§7); any other `OperationalError` still propagates |
| Destination slot or anchor vanished | 422 `parent_gone`, as today |
| Hand-crafted cross-unit `mode=move` (with a valid slot/anchor) | 422 `wrong_unit` |
| Mark from another course (hand-crafted POST) | 409 — §4 step 1's course filter never loads the element |
| Destination unit has no admissible slot | not an error: banner shows "Nothing can be pasted into this unit." |
| Damaged source element (dangling GFK) | 422 "This element is damaged and cannot be copied." |
| Malformed payload (`before` not an int, bad slot ref) | 400, as today |

`PASTE_REFUSAL_MESSAGES["wrong_unit"]` ("That element is not part of this unit.") is
reachable only by hand-crafted POSTs, so its wording is left alone.

## Testing

Project rules apply: every guard is **falsified** by a named mutant that must turn it red
(read the `git diff` of each mutant; revert by hand, never with `git checkout`); no
assertion compares pks across models; e2e drives the real UI and waits on the paste
**request**, never a sleep.

### `paste_allowed` / `subtree_facts` (unit tests)

- Cross-unit copy, same course, into a top-level slot and into a container slot → allowed.
- Cross-unit move → `wrong_unit`. Mark from another course, mode copy → `wrong_unit`.
- Quiz destination: a callout holding a question, pasted at top level → `question_in_quiz`;
  pasted into a container slot → `question_in_quiz`. Same subtree into a lesson → allowed.
  A bare question pasted at top level of a quiz → allowed.
- `subtree_facts(...).nested_question`: false for a lone question root, true for a
  container with a question child, true for a question two levels down.
- Cross-unit, quiz destination: a stepper → `interactive_in_quiz`; a callout containing a
  checklist → `interactive_in_quiz`, at top level and in a slot; the same into a lesson →
  allowed. In-unit, a stepper already in a quiz moved to another slot of that quiz →
  allowed (2d is cross-unit only).
- The derived `QUIZ_EXCLUDED_TYPE_KEYS` drift guard (lesson vs quiz add-menu diff).
- **Mutants:** delete the clause-2d check (interactive tests go red); drop the
  cross-unit condition from 2d (in-unit quiz move test goes red); remove one key from
  `QUIZ_EXCLUDED_TYPE_KEYS` (drift guard goes red); spell the frozenset with card names
  (`revealgate`, `markdone`, …) instead of transfer keys (the stepper test may still pass
  — `stepper` is spelled the same both ways — but the callout-containing-a-checklist
  test goes red, and the drift guard goes red).
- **Mutants:** delete the clause-2c check (quiz tests go red); make `nested_question`
  include the root (lone-question-at-top-level test goes red); drop the course comparison
  from clause 0 (other-course test goes red).

### `paste_element` (service tests)

- Copy into a slot of Y lands at the end of that slot; copy with `before` lands directly
  above the anchor (assert the ordered sibling list of titles/`content_object` identity,
  not pks across models).
- Source rows, their order, and `X.updated` are unchanged; `Y.updated` is bumped.
- A copied image element points at the **same** `MediaAsset` as the original.
- A text element containing a link to unit X still links to X after being copied into Y.
- Stale Y token → `ConflictError`. Stale X token is irrelevant (X is never token-checked).
- Marked element deleted → `ConflictError`. Element of another course → `ConflictError`.
- The returned unit is Y: `returned_unit.pk == Y.pk` (same model).
- In-unit copy with `before` now works (the removed refusal). The existing test
  `tests/test_builder_paste_element.py::test_a_copy_may_not_name_a_before_target` pins
  the old refusal; it is **replaced** by this positive test (renamed accordingly), not
  silently deleted.
- **Mutants:** check the token against the source unit (stale-Y test goes red / stale-X
  passing test goes red); bump the source's `updated` (unchanged-X test goes red); return
  the source unit (returned-unit test goes red); pass the destination to
  `build_element_export` — the test asserts the **observable** result, `TransferError`
  raised and no new `Element` in Y (the export's `AssertionError` is wrapped into
  `TransferError` by `_copy_into`'s `except Exception`).

### Views

- Editor GET of Y with a mark from X: no "Move here" / "Move before" controls; copy slots
  and "Copy before this element" rows present, each copy-before form posting `mode=copy`;
  banner shows "from <X title>" linking to X's editor URL.
- Editor GET of X with the same mark: rows show "Move before" only (D4); banner has no
  "from".
- "Copy to another unit…" lists every unit of the course as a link to its editor page,
  except the current unit, which is present but not a link.
- A mark from another course: editor GET of a unit in this course shows no banner and no
  paste controls, and the mark is still in the session afterwards.
- A mark whose source unit was deleted: editor GET of another unit shows no banner and the
  session mark is gone.
- A callout holding a question, marked in a lesson, rendered in a quiz: no paste controls
  and "Nothing can be pasted into this unit." is shown.
- POST `element_paste` into Y with a mark from X: 200 fragments **of Y**, element copied,
  mark kept.
- The copy list is built only while a mark is active, following the precedent of
  `tests/test_element_paste_view.py::test_an_unmarked_render_never_walks_the_unit`:
  monkeypatch `views_manage._children_map` with a call-counting wrapper; an unmarked
  editor render → **0** calls, a marked render → **exactly 1** call (so the test also
  fails if the tree is never built). `_children_map` is not otherwise called on the editor
  render path; the implementer confirms this before relying on it.
- The existing `tests/test_element_paste_view.py::test_a_mark_naming_another_unit_is_a_409`
  (same-course mark in another unit, default `mode="move"`, asserts 409) pins the old
  behaviour and becomes **"a cross-unit move is a 422 `wrong_unit`, mark kept"**. A new
  test keeps the old intent where it still holds: a mark whose element belongs to
  **another course** → 409.
- Deadlock mapping: monkeypatch `builder_svc.paste_element` to raise an
  `OperationalError` whose `__cause__` is a `psycopg.errors.DeadlockDetected` → 409 and
  the mark is kept; one whose `__cause__` is some other error → propagates (the test
  asserts the exception, with the client's `raise_request_exception`). **Mutant:** drop
  the sqlstate check (the other-error test goes red); delete the handler (the 409 test
  goes red).
- **Cross-unit render cost**, mirroring the existing same-unit guards
  (`test_a_marked_render_does_not_walk_parents_per_slot`,
  `test_a_marked_render_never_falls_back_to_walking_parents`):
  - `django_assert_max_num_queries` ceiling on a GET of Y with a mark from X, using a
    fixture with several container slots in Y; the ceiling is set from a measured run
    plus a small margin, stated in the test with that measurement.
  - A GET of Y with a mark from X with `builder.element_depth` monkeypatched to raise.
  - **Mutants**, chosen so the cost grows with the slot count (a one-query regression —
    e.g. dropping `select_related("unit")` — cannot be separated by any sane ceiling, as
    `test_a_marked_render_does_not_walk_parents_per_slot`'s docstring already records,
    and is **not** claimed to be caught): drop `facts=facts` from the cross-unit
    `paste_allowed` loop, so `subtree_facts` re-walks the source unmapped once per slot
    (ceiling goes red — the fixture has at least 10 slots and the marked element has at
    least 2 descendants, so the excess clears the margin); omit `dest_depth=` in the loop
    (the `element_depth` raise goes red).
- A non-numeric session `element` on a paste → 409 (step 1's guard). A non-numeric
  `clip["unit"]` rendered on another unit → empty context, mark cleared.
- **Mutants:** hard-code `mode=move` in `_paste_before_button.html` (copy-before view test
  goes red); render move slots in the cross-unit branch (no-move test goes red); clear the
  mark for another-course clips (mark-kept test goes red); render the current unit as a
  link in the copy list (not-a-link test goes red); build `copy_units_map` unconditionally
  (no-query test goes red); drop `clip_nothing_fits` from the banner (nothing-fits test
  goes red).

### e2e (one test, real UI)

Mark an element in unit A → open "Copy to another unit…" → click unit B → click "Copy
before this element" on a middle row of B → wait for the paste **request** to complete →
assert B's row order and that B's preview shows the copied element. Before clicking unit B,
assert a unit link inside the open `<details>` is **visible and not clipped** (Playwright
visibility plus its bounding box lying within `#clip-banner`'s box). The test runs at a
**1280×720** viewport in split mode and seeds enough units to overflow the list; it also
scrolls the list's **last** unit link into view and asserts its bounding box lies inside
the viewport. It asserts the pill's left edge lines up with the "Editor" heading's left
edge (±1px), which catches a full-bleed banner. The source unit is titled with inline
maths (`Unit \(x^2\)`), and after the paste — a fragment swap — the banner's "from" link
contains a `.katex` node, not raw `\(`. Screenshots of the
banner and the open `<details>` in light and dark themes (dark via `user.theme`, not the
cookie), judged separately.

### Not tested, by decision

Lock ordering between two concurrent opposite-direction copies — correctness rests on the
ascending-pk acquisition, documented in the code; a concurrency test would be flaky.

## Out of scope

- Moving an element to another unit (D1).
- Copying between courses (D2).
- Any other change to in-unit mark/paste behaviour beyond: the clause-2c quiz check (which
  applies in-unit too and is strictly stricter), the accepted `before` + copy combination
  in the service, and the icon swap (D9).
