# Unit publish state, and one-click flag toggles in the builder tree

## Purpose

A Course Admin working on a course that is **already live** — students enrolled, teachers reading
it, results accumulating — has no way to add content privately. Every unit they create is visible
to students the moment it is saved, half-written. The only workarounds are authoring elsewhere and
pasting at the end, or accepting that students see drafts.

This spec adds a second, independent boolean to `ContentNode` — `published` — and gives the builder
tree one-click toggles for **both** `published` and the existing `obligatory`, so a CA can see and
change either state across the whole course without opening a single unit.

### The two flags are orthogonal, deliberately

`obligatory` and `published` are **not** three values of one enum. A unit may be obligatory and
draft, optional and live, or any other combination, and the CA sets each independently, before or
after the other. A new unit is created **obligatory and draft** (`obligatory=True, published=False`)
— the common case is "this will be required course material, and it is not ready yet".

The alternative — a single `state ∈ {obligatory, optional, draft}` — was rejected because it cannot
represent "an optional unit that is not ready", and because publishing a draft would then have to
guess which of the two live states to restore.

## Terminology

- **Live** / **published**: `published=True`. Visible to students.
- **Draft** / **hidden**: `published=False`. Visible only to authors.
- **Author**: a user for whom `access.can_manage_course(user, course)` is true — the course owner,
  or a holder of `courses.change_course` (the Platform Admin group). Deliberately **not**
  `is_staff`, and deliberately **not** an assigned group teacher; see §3.

## Deployment reality — stated once, deferred to everywhere

**There is no production install yet.** The first deploy happens after this work, or later.

Two consequences, and §1 and §8 must both defer to this paragraph rather than re-deriving it:

- **§1's migration still matters.** "No production" is not "no data". Populated development
  databases exist — `libli_mat` holds the grafted mat-pp course, 925 nodes and ~19,900 elements —
  and the migration runs against them on the next `migrate`. The two-operation form is required to
  protect *those*, and to be correct for the first real install whenever it happens. The hazard is
  not hypothetical merely because it is not yet in production.
- **§8's transfer bump is uncoordinated, and only for now.** With one install there is no second
  reader to negotiate a format version with, so `FORMAT_VERSION` can move freely and there is no
  ordering constraint against the mat-pp cutover. That freedom expires the moment a second install
  exists; §8 records what changes then.

---

## 1. Model and migration

```python
# courses/models.py, ContentNode
obligatory = models.BooleanField(default=True)   # unchanged; meaningful only for units
published = models.BooleanField(default=False)   # meaningful only for units
```

`published` follows `obligatory`'s established convention exactly: the column exists on every node
row, but only a unit's value is ever read. Container rows carry the field and ignore it. Nothing
walks ancestors — a unit's visibility is decided by its own flag alone (see §2, "Why not
inheritance").

### The migration must not hide every existing course

`AddField(default=False)` would backfill `published=False` into every existing row and black out
every course in every existing database on the next `migrate` (see "Deployment reality" above —
that means the populated dev databases today, and the first real install later). Migration
`0057_contentnode_published` therefore carries **two operations in one file**:

```python
operations = [
    migrations.AddField(
        model_name="contentnode",
        name="published",
        field=models.BooleanField(default=True),
    ),
    migrations.AlterField(
        model_name="contentnode",
        name="published",
        field=models.BooleanField(default=False),
    ),
]
```

**What each operation actually does — the naïve reading is wrong.** Django does not leave a
database-level default in place: `AddField` adds the column *with* the default, backfills every
existing row from it, and then **drops the DB default**. So:

- `AddField(default=True)` exists solely to **backfill existing rows** as published. That is the
  whole point of the pair, and it is the operation that must not be touched.
- `AlterField(default=False)` writes **nothing** to the database. It reconciles Django's *migration
  state* with `models.py`, which declares `default=False`. Without it, `makemigrations --check
  --dry-run` — a real CI gate in the `unit` job since #204 — reports a pending migration and fails
  the build.

New rows land as drafts because **`models.py` says `default=False`**, not because of the
`AlterField`. No data migration, no `RunPython`, and the reverse direction is a plain column drop.

**This is the single most important passage in the spec.** A reviewer who "simplifies" the pair to
one `AddField(default=False)` silently unpublishes every course in every database. §9 MIG1 exists
specifically to make that mutation fail.

**Do not write a test asserting "a node created after the migration defaults to draft" as the guard
on the `AlterField`.** It cannot fail: deleting the `AlterField` leaves `models.py` untouched, so
`ContentNode.objects.create(...)` still yields `published=False` and the test stays green on the
mutant. The `AlterField`'s real guard is the CI `makemigrations --check` gate, which §9 MIG2
asserts directly.

---

## 2. What "hidden" means, per surface

`rollups._walk_preorder` stays **unfiltered**. It is the shared traversal behind the student
outline, the analytics builders and the unit nav, and those three audiences need three different
answers; pushing a filter into the walk itself would force every caller to opt back out.

Filtering becomes an explicit layer on top:

| Surface | Rule |
|---|---|
| Course outline, unit nav, prev/next, all four progress counters | `hide` — drop draft units; drop containers whose subtree contains no visible unit. |
| Notes hub, tags hub (`notes/services.py:116` iterates `units_in_order`) | `hide`. |
| Direct unit URL, node permalink, every unit-addressed POST | 404 for non-authors (§3). |
| Analytics matrix, gradebook, student breakdown, review queue | `keep-with-data` — drop draft units **unless** the unit holds data. |
| Builder tree, link picker, course/subtree export | `keep` — everything, always. |

### The filter is a caller-chosen parameter, never a viewer lookup

`build_outline(course, user)` is the single implementation behind **three** surfaces with three
different rules: the student outline, `build_unit_nav` (`rollups.py:768`), and
`build_student_breakdown` (`rollups.py:377`).

**`build_student_breakdown` calls `build_outline(course, student)` — the `user` argument is the
student whose progress is being read, while the actual *viewer* is a teacher.** Deriving the draft
filter from `build_outline`'s `user` would therefore silently apply the student rule to a
teacher-facing analytics surface, which is the exact opposite of the §2 table. `user` selects whose
`UnitProgress` rows to read; it does not identify the viewer, and must never be repurposed to.

The filter is therefore an **explicit third parameter**:

```python
def build_outline(course, user, *, drafts="hide"):   # "hide" | "keep" | "keep-with-data"
```

with each caller stating its own choice, and no default-by-inference anywhere:

| Caller | `drafts=` |
|---|---|
| `course_outline` (student view) | `"hide"` |
| `build_unit_nav` | `"hide"` (propagated from its own caller) |
| `build_student_breakdown` | `"keep-with-data"` |

`units_in_order` and `units_under` take the same keyword with the same three values.

### An author browsing the student view sees drafts, and sees a denominator that says so

An author opening a *student-facing* page passes `drafts="keep"`, so drafts appear — this is what
makes §5's draft banner reachable at all, and an author who could not open a draft unit's student
render could not preview their own work.

The consequence must be stated rather than discovered: **the author's progress counters therefore
count drafts, and differ from what any student sees.** That is accepted. The author is previewing,
not being assessed, and the draft banner on the page already tells them they are looking at content
students cannot see. No attempt is made to show an author "the student's denominator" — two
denominators on one page is worse than one honest one.

### Container pruning

A container whose subtree holds no visible unit is dropped from the student outline and nav. Without
this, a CA who drafts a whole new chapter leaves students staring at an empty "Chapter 4".

This also changes existing behaviour for containers that are genuinely empty (no units at all,
draft or otherwise) — those disappear from the student outline too. That is an improvement and is
adopted knowingly, not a side effect to be discovered later.

### Progress arithmetic — four counters, and `is_obligatory_lesson` gates only two of them

A draft unit must not count: a student seeing "3 of 10 required units" with seven of them invisible
has no way to reach 100%.

**`is_obligatory_lesson` is NOT the single gate, despite its docstring saying so.** Reading
`build_outline`'s rollup (`rollups.py:150–167`) shows four independent expressions, and only two
route through that predicate:

| Counter | Current expression | Routes through `is_obligatory_lesson`? |
|---|---|---|
| `required_total` | `is_obligatory_lesson(node)` | yes |
| `required_done` | `is_obligatory_lesson(node) and pk in completed` | yes |
| `additional_done` | `is_lesson and not node.obligatory and pk in completed` | **no** |
| `"completed"` (per-node key, `rollups.py:150`) | `is_unit and pk in completed` | **no** |

Gating `is_obligatory_lesson` alone would fix the first two and leave `additional_done` counting
drafted optional units the student cannot see, and leave every draft unit's dict carrying
`completed: True`.

The fix is one new predicate that all four call, rather than four parallel edits that can drift:

```python
def counts_for_progress(node, *, drafts):
    """A unit whose progress the viewer may see at all. The publish gate, applied
    once. is_obligatory_lesson and the three sibling expressions all sit on top."""
```

§9 OUT2 and OUT3 cover the first two counters; **OUT4** covers `additional_done` and the `completed`
key specifically, because those are the two the obvious implementation misses.

A student who *had* completed a unit that is later pulled back to draft keeps their `UnitProgress`
row untouched; it simply stops being counted while the unit is hidden, and resumes counting
unchanged when the unit is published again.

### `progress_reset`'s blast-radius count

`progress_reset`'s "honest blast radius" number comes from `units_under(node)`, which is unfiltered.
For a student viewer it must pass `drafts="hide"`, so the count describes only units they can see.

In practice a draft unit holds no student practice state, so the number is usually identical either
way — but that is a property of today's data, not an invariant, and a view whose docstring makes
honesty its entire point should not depend on a coincidence. §9 OUT6 pins it.

### Analytics keeps columns that hold data

A CA pulling a live quiz back to fix a typo must not make a mid-term gradebook column blink out and
back. Teacher-facing surfaces therefore keep any unit with recorded data, flagged as draft, and
drop only drafts that never went live.

"Holds data" is **two** conditions over **two** models, and they need **two** batched lookups —
one per course, never one query per unit:

```python
has_submissions = set(QuizSubmission.objects.filter(unit__course=course)
                                            .values_list("unit_id", flat=True))
has_progress    = set(UnitProgress.objects.filter(unit__course=course)
                                          .values_list("unit_id", flat=True))
```

Do **not** try to fold this into `rollups._quiz_review_maps`. That helper is fed
`quiz_units_in_order(course)` (`rollups.py:280`, `:599`) and knows nothing about lesson units or
`UnitProgress`, so extending it would batch the quiz half and leave the lesson half issuing a query
per unit — the exact N+1 this paragraph exists to prevent. Both sets are built once by the caller
and handed to `build_outline`/`build_matrix_columns` alongside `drafts="keep-with-data"`.

### Why not inheritance

Storing `published` on containers and computing visibility as "self AND every ancestor" was
considered and rejected. It preserves per-unit state perfectly when a chapter is hidden and
restored, which is a genuine advantage. It was rejected because it produces a unit whose own row
says *published* while students cannot see it, for a reason displayed several rows higher up the
tree — the support question that never resolves. Every read path would also have to walk ancestors
rather than read a field.

**The accepted cost:** hiding a container and then re-publishing it publishes *every* unit beneath
it, including ones that were deliberately draft. The confirm strip (§4) states the count plainly
before the write, which is the mitigation. This matches how a container-level `obligatory` toggle
behaves too, so the two flags stay consistent with each other.

---

## 3. Access gating

### The predicate

```python
# courses/access.py
def can_see_drafts(user, course):
    """Draft units are visible only to authors — the course owner or a holder of
    courses.change_course. NOT is_staff (which grants read access to every course)
    and NOT an assigned group teacher (who cannot fix what they can see)."""
    return can_manage_course(user, course)
```

A thin alias over `can_manage_course` rather than a direct call at each site: the two answers are
the same today but the questions are not, and a future "teachers may preview drafts" setting must
have one place to change.

### The chokepoint

`access.get_node_or_404` is the funnel every node-addressed view already passes through. It gains an
optional `viewer` argument:

```python
def get_node_or_404(node_pk, slug, *, viewer=None, require_unit=False, ...):
    # ... existing: exists -> slug match -> kind/unit_type ...
    # Draft check runs LAST, after every existing check.
    if (
        viewer is not None
        and node.kind == ContentNode.Kind.UNIT      # <-- see "Units only" below
        and not node.published
        and not can_see_drafts(viewer, node.course)
    ):
        raise Http404("node is not published")
```

**The `kind == UNIT` guard is mandatory, not defensive tidiness.** Every container row created after
the migration carries `published=False`, because the model default applies to the whole table while
only units' values are ever *meant* to be read (§1). Without the guard, two existing call sites
break for every student:

- `progress_reset`'s node-scoped branch calls `get_node_or_404(..., require_unit=False)` and
  legitimately resolves chapters and parts.
- `node_permalink` explicitly branches on `node.kind != UNIT` and redirects to an outline anchor.

Both would 404 on any chapter or part created after the migration — a container's own flag deciding
visibility, which §1 and §2 both forbid.

**A permalink to a container** is governed by §2's pruning rule, not by the container's field: it
redirects to the outline anchor as it does today, and if the container has no visible unit the
student simply lands on an outline that does not contain that anchor. No extra check; a container
with nothing visible under it is already invisible by pruning.

404, never 403 — the existing docstring's convention ("a foreign node always 404s before any 403")
applies unchanged, and a 403 would make the endpoint an existence oracle for unreleased content.

**Ordering.** The draft check runs **last**, after the existing kind/unit_type checks, so the
docstring's stated order becomes four steps: *exists → slug match → kind/unit\_type → published*.
Update the docstring in the same change; leaving it at three steps while the function does four is
how the next reader learns to distrust it.

### Call sites that must pass `viewer=request.user`

**`courses` app:** `lesson_unit`, `quiz_unit`, `quiz_results`, `progress_reset` (node-scoped
branch), `seen`, `complete`, `element_state_save`, `check_answer`, `quiz_answer`, `quiz_finish`.

**Other apps — easy to miss, since neither is in `courses/`:**

- `notes.views.note_add` (`notes/views.py:161`) — resolves a unit via `get_node_or_404` from a
  student session and writes a `Note` keyed to it.
- `tags.views.tag_add` and `tags.views.tag_remove` (`tags/views.py:38`, `:75`) — same shape.

The POST endpoints matter as much as the GETs: a student holding a page that was open when the unit
got pulled must not be able to keep writing progress, answers, submissions, notes or tags into it.

`node_permalink` does not take a slug and so does not call `get_node_or_404`; it gets the same
unit-guarded check inline, immediately after its existing `can_access_course` test.

Management views (`views_manage.*`) pass no `viewer` and are unaffected.

### Deliberate gap: the element-level check endpoints

`fillgate_check`, `switchgate_check`, `switchgrid_check`, `guessnumber_check` and `filltable_check`
are addressed by `element_pk` alone, with no node or slug in scope. They are ungraded practice
checks, reachable only by a client that already rendered the page, and threading node resolution
through all five for a draft-content leak of "is this answer right" is not worth the surface area.

**This is a stated limitation, not an oversight.** If it is ever closed, close it by giving those
views the same `unit → course` resolution the graded path uses, not by a special case.

---

## 4. Write path

### One endpoint for both flags

```
POST courses:manage_node_flag
  node   = <pk>
  token  = <node.updated.isoformat()>       # optimistic concurrency, as rename_node
  flag   = "published" | "obligatory"
  value  = "0" | "1"
  scope  = "node" | "subtree"
```

A single endpoint rather than one per flag: the two toggles differ only in which column they write,
and splitting them would duplicate the token check, the subtree walk, the confirmation rendering and
the quiz warning. `flag` is validated against a literal allow-list of the two column names before it
reaches the ORM — never interpolated from user input into a query.

The service function lives in `courses/builder.py` beside `rename_node`, whose `_locked_node` +
`_check_token` preamble it reuses verbatim.

### Authorization

Both the GET and the POST open with `course = _require_manage(request, slug)`, exactly as
`node_rename` and every other management view do. This is stated explicitly because it is the one
endpoint in the codebase that can unpublish an entire course in a single request, and because §4
otherwise describes only the token check and the allow-list — a reader could reasonably infer those
*are* the guard. They are not; they protect against staleness and injection, not against the wrong
person. §9 WR1 pins it for a student and for an assigned group teacher, on both methods.

### Unit scope: one click, no confirmation

Clicking a unit's icon posts `scope=node` and returns the re-rendered row fragment. No interstitial,
no dialog. The action is trivially reversible by clicking again, which is the whole justification
for skipping confirmation.

### Subtree scope: the in-place confirm strip

`GET courses:manage_node_flag` with the same parameters returns a confirm-strip fragment that the
row expands into — the pattern `_move_picker.html` already establishes. The tree keeps its scroll
position and its expansion state, which a full-page interstitial would cost.

The strip always states the count, and for a **mixed** container offers *both* actions rather than
guessing which way a half-filled icon toggles:

```
┌─ Publish or hide 5 units in "Chapter 3"? ─┐
│  2 are live, 3 are drafts.                │
│  [ Publish all 5 ]  [ Hide all 5 ]   ×    │
└───────────────────────────────────────────┘
```

For an all-live or all-draft container only the meaningful action is offered.

No-JS falls back to a full-page interstitial reusing the `node_confirm_delete.html` shape, so the
feature degrades rather than breaking.

### The bulk write bypasses `auto_now`

```python
ContentNode.objects.filter(pk__in=unit_pks).update(
    published=value, updated=timezone.now()
)
```

`QuerySet.update()` does **not** fire `auto_now`, so an `update(published=...)` alone would leave
every touched row's `updated` — and therefore its optimistic-concurrency token, and the builder's
`data-updated` attribute — pointing at a state that no longer exists. Setting `updated` explicitly
in the same call is mandatory. §9 pins it.

The subtree's unit ids come from `ContentNode._subtree_node_ids()` filtered to `kind="unit"`; that
method already exists and is already used by `delete()`.

### Response contract

Because the bulk write bumps `updated` on **every** descendant unit, every affected row's
`data-updated` attribute in the DOM is stale the instant the write lands. Returning just the
container's own `<li>` would leave open descendant rows carrying tokens that 409 on their next edit.

| Case | Response |
|---|---|
| Unit, `scope=node`, fragment request | The re-rendered `_tree_node.html` `<li>` for that unit. |
| Container, `scope=subtree`, fragment request | The re-rendered `_scope.html` fragment rooted at the container, so every currently-open descendant row is replaced with fresh tokens. |
| Either, non-fragment (no-JS) | Redirect to the builder via `_redirect_to_builder`, as `node_rename` does. |
| Stale token (409) | `_conflict_scope(request, course, node_pk)` for fragments; `_builder_with_notice(..., status=409)` otherwise — the existing `node_rename` shapes, unchanged. |
| Bad `flag` / `value` / `scope` (422) | `_op_error.html` for fragments; `_builder_with_notice(..., status=422)` otherwise. |

`X-Builder-Info` carries full state and is emitted on the same terms as the other builder ops — this
endpoint introduces no new convention for it.

**Collapsed descendants are not re-rendered and do not need to be.** A collapsed scope is fetched
fresh when it is expanded, so it cannot be holding a stale token in the DOM. Only currently-open
rows matter, which is exactly what the `_scope.html` fragment covers.

### Unit settings form

`templates/courses/manage/editor/_unit_settings.html` gains a **Published** checkbox beside the
existing **Obligatory** one. It routes through the same `node_rename` `is_settings` path, using the
established checkbox-absent-means-false idiom:

```python
published=("published" in request.POST) if is_settings else builder_svc._UNSET
```

`builder.rename_node` gains a `published=_UNSET` parameter guarded by the same
`if node.kind == ContentNode.Kind.UNIT:` block that already guards `unit_type`, `obligatory` and
`html_seed_js`.

---

## 5. Builder tree UI

### Two controls, reusing the row's existing markup patterns

`_tree_node.html` is already **one form per row** — a deliberate optimisation, since on mat-pp the
three-form layout produced 2,866 forms and 10,641 inputs. Nothing here adds a form, a `csrf_token`
or a hidden input.

The two controls take **different element types**, because they need different HTTP methods:

- **On a unit** (POST, applies immediately): `<button type="submit" formaction="…">` inside the
  row's existing form, carrying `data-op` like every other button in the cluster. The row's `node`
  and `token` inputs already carry what the endpoint needs; `flag`/`value`/`scope` ride in the
  `formaction` query string.
- **On a container** (GET, opens the confirm strip): `<a href="…">`, exactly as the existing
  Delete and Move controls in the cluster already do, carrying a `data-` hook for the JS that swaps
  the strip in place. A submit button cannot issue the GET without `formmethod="get"`, which would
  also drag the form's other inputs into the query string.

### Placement: direct flex children, with explicit `order` on every sibling

**The toggles do NOT go in `<span class="tree__cluster">`,** even though every other row control
(grip, move, export, duplicate, delete) lives there. They must be **direct children of
`<form class="tree__rowhead">`, siblings of `.tree__cluster`.**

The reason is mechanical: `.tree__rowhead` is the flex container, so `.tree__cluster` is the flex
*item* and its children are not. `order` on an element nested inside the cluster is **inert** — it
applies to nothing, produces no error, and the toggles simply render wherever the cluster puts them.
An implementer who follows the cluster convention gets a silent layout failure with nothing to
debug.

**Implicit-submission hazard, unit rows only.** The row's own comment warns that Enter in the title
picks the form's first submit button in *tree* order, which is why the visually-hidden Rename button
must stay ahead of the cluster. A unit's two toggle buttons must therefore appear **after** that
hidden Rename button in the DOM — while sitting left of the title visually.

**One negative `order` will not achieve that.** The expand toggle, the kind badge and the title
input are all rowhead children at the default `order: 0`, so a single negative value puts the
toggles leftmost in the row — ahead of the chevron and the badge, not between the badge and the
title. Closing the gap requires making **every** rowhead child's order explicit:

| Rowhead child | DOM position | `order` |
|---|---|---|
| Expand toggle / leaf spacer | 1 | `1` |
| Kind badge (Part / L / Q) | 2 | `2` |
| Title input | 3 | `4` |
| Visually-hidden Rename submit | 4 | `4` |
| **Publish toggle** | 5 | `3` |
| **Obligatory toggle** | 6 | `3` |
| `.tree__cluster` | 7 | `5` |

This is a **new layout rule**, not "a new use of a property the layout already supports" — every
sibling's order becomes load-bearing, so a future row control added without an `order` lands at `0`
and jumps to the front. Note that in a CSS-less rendering (or if the stylesheet fails to load) the
toggles appear after the title; that is cosmetic and acceptable.

**The accepted cost is a DOM-order / visual-order mismatch**: a screen reader reaches the toggles
after the title, not before it. This is tolerable specifically because each toggle's `aria-label`
states a self-contained action ("Publish", "Make optional") rather than relying on proximity to the
title to be understood. The alternative — reordering the DOM — trades a reading-order nuisance for a
data-loss bug, which is the worse trade.

Container rows are unaffected by the Enter hazard: their controls are anchors, and anchors are not
submitters. They take the same `order` values. §9 TREE1 pins the Enter behaviour.

### The glyphs

| State | Publish | Obligatory |
|---|---|---|
| Unit, on | ● filled dot | ★ filled star |
| Unit, off | ○ hollow dot | ☆ outline star |
| Container, mixed | ◑ half dot | ◐ half star |

Fill *and* silhouette both carry the state, so the pair survives greyscale and colour-blindness
rather than relying on a red/green distinction alone. Colour is applied on top as reinforcement, via
existing tokens, never as the sole channel. The dot and the star have distinct silhouettes so the
two adjacent controls are not confusable.

Both glyphs are added to `_icon_sprite.html` as monochrome `currentColor` SVGs, per the project's
icon convention — six new symbols (`bi-live`, `bi-draft`, `bi-live-mixed`, `bi-req`, `bi-opt`,
`bi-req-mixed`).

### Draft rows are struck through

A draft row gets a modifier class that applies `text-decoration: line-through` to `.tree__title`.
The title is an `<input type="text">`, on which `text-decoration` renders correctly.

Strike-through is applied to **units only**. A container has no publish state of its own, so
striking it would assert something the model does not hold.

### Tri-state rollup — fold the FULL map, never the rendered one

Per container, the tree needs `(live_unit_count, obligatory_unit_count, total_unit_count)` over its
whole subtree: one bottom-up fold over the already-loaded node list, no additional queries.

**Fold `cmap = _children_map(course)`, the unrestricted map — never the `children_map` in the
template context.** When the builder's filter is active, the template's `children_map` is
`fc.restricted` (`views_manage.py:379`, `:500`), a map narrowed to matching nodes. Folding over
*that* makes a container claim "3 units" when its real subtree holds 40 — and the count in the
confirm strip is §2's sole stated mitigation for the accepted over-publish cost, so a wrong count
does not merely mislead, it removes the only guard.

**Container toggles are `disabled` while a filter is active**, matching the existing grip button,
which is already `{% if filtered %}disabled{% endif %}` with the tooltip "Clear the filter to
reorder." The same reasoning applies with more force: reordering under a filter is confusing,
whereas bulk-publishing under a filter invites the CA to believe the action is scoped to what they
can see. Unit toggles stay enabled under a filter — they affect exactly the one row shown.

A container with zero units renders both icons disabled with a "no units" tooltip rather than a
misleading empty state.

### Tooltips, labels and the legend

Every button carries both `title` (desktop hover) and `aria-label` (screen readers and touch, where
`title` does not exist), stating the *action*, not the state:

- ● → "Hide from students" / ○ → "Publish"
- ★ → "Make optional" / ☆ → "Make obligatory"
- Container mixed → "Publish or hide N units…"

`_structure_legend.html` gains **all six states** — live / draft / mixed-publish and obligatory /
optional / mixed-obligatory, one entry per sprite symbol — because a tooltip is not reachable on
touch. Six entries, six symbols: the legend and the sprite must stay in step, and an entry count
that disagrees with the symbol count is the first sign they have drifted.

### Author-facing draft banner

Two places tell an author that what they are looking at is not live:

1. The **editor page** for a draft unit, above the element list.
2. The **student-facing render** of a draft unit (`lesson_unit.html` / the quiz template), when
   viewed by an author.

Both read *"Draft — not visible to students"* and carry a Publish button.

**The banner is text-only — no sprite glyph.** `_icon_sprite.html` is included by `builder.html`,
`editor/editor.html` and `help/doc.html` only. A glyph on the student-facing render would resolve
to nothing and paint blank. Pulling the sprite into the lesson and quiz templates to serve one
banner would ship the whole symbol set to every student page for no other purpose, so the banner
uses text. (This is a defect class that has already recurred on a recent element build; it is
recorded here so it does not recur a third time.)

**The banner's Publish button does not reuse the builder response contract.** §4's fragment
responses render `_tree_node.html` / `_scope.html`, which need `rename_url`, `move_url`,
`delete_url`, `duplicate_url`, `is_first`, `is_last`, `children_map`, `open_ids`, `q` and `filtered`
in context — none of which exists on the editor page or the student render. The banner therefore
posts with a `ctx=` marker and gets a **redirect back to the originating page**, exactly as
`node_rename` already does for `ctx=editor` (`views_manage.py:762`):

| Origin | `ctx=` | Success response | 409 response |
|---|---|---|---|
| Editor page | `editor` | Redirect to `courses:manage_editor` | Redirect to the editor with `?changed=1` |
| Student-facing render | `unit` | Redirect to the same unit URL | Redirect to the same unit URL |

Each banner is a real `<form method="post">` carrying `{% csrf_token %}`, the node pk, and
`token` = the unit's own `node.updated.isoformat` — which both surfaces already have in context,
since both are rendering that node. Neither surface has a form today, so the form element itself is
new markup, not a modification of an existing one.

---

## 6. Quiz results and quiz edits

### The pre-existing hazard this makes visible

Editing a quiz that already has submissions silently desynchronises recorded results, and this is
true **today**, before any of this spec ships:

- `QuestionResponse.fraction` and `earned_marks` are computed at answer time and never recomputed.
  Changing a question's correct answer or its marks leaves stored marks referring to a rule that no
  longer exists.
- `QuizSubmission.max_score` is cached at Finish. Adding a question makes old submissions
  incomparable to new ones — two students' percentages are then computed against different
  denominators.
- `QuestionResponse.element` is a FK with `on_delete=CASCADE`. **Deleting a question element already
  deletes every recorded answer to it.**

### The decision: warn, never touch the data

Nothing is recomputed, nothing is deleted, no versioning is introduced. Re-grading is *unsound*, not
merely expensive: reorder an MCQ's options and the stored answer index now designates a different
option, so an automatic re-grade would confidently produce wrong marks rather than admitting it
cannot know. Quiz versioning is a separate feature with its own spec.

What ships is a count and a banner:

1. The **editor page** for a quiz unit with ≥1 submission shows a persistent banner naming the count
   and the three facts above.
2. The **unpublish confirm strip** repeats the count, because "pull it back to edit" is exactly the
   gesture that precedes the damage.

### Archived groups soften the warning, they do not silence it

If every submission comes from students whose only `Group` on that course is archived, the loud
banner would cry wolf: that is a finished cohort, and preparing the quiz for the next one is normal
work. The banner is therefore scoped:

- **Any** submission from a student in a non-archived `Group` on this course → the loud banner.
- **All** submissions from archived groups only → a quieter note: *"12 submissions, all from
  archived groups."*
- A student enrolled but in **no** group (self-enrolled via cohort) counts as **active**. "Not
  provably archived" must read as active; the opposite default would silence the warning for the
  population it most protects.

Never fully suppressed: archived is not deleted. Deleting a question still destroys that cohort's
historical responses, and their gradebook is still reachable.

### State the predicate as the QUIET condition, not the loud one

The obvious implementation — one `exists()` joining `QuizSubmission → student → GroupMembership →
Group(course=…, archived=False)`, quiet when it returns `False` — **inverts the third rule above.**
A self-enrolled student has no `GroupMembership` at all (`Cohort` and `CohortMembership` are
separate models from `Group`/`GroupMembership`), so that `exists()` returns `False` for them and
routes exactly the population the rule protects into the quiet branch.

The quiet note therefore fires only when **every** submitting student is *provably* in a finished
class — which requires two lookups, not one:

```python
submitters = set(QuizSubmission.objects.filter(unit=unit)
                                       .values_list("student_id", flat=True))
in_any_group = set(GroupMembership.objects
    .filter(group__course=course, student_id__in=submitters)
    .values_list("student_id", flat=True))
in_active_group = set(GroupMembership.objects
    .filter(group__course=course, group__archived=False, student_id__in=submitters)
    .values_list("student_id", flat=True))

ungrouped = submitters - in_any_group          # self-enrolled -> treated as ACTIVE
quiet = bool(submitters) and not in_active_group and not ungrouped
```

`quiet` is `False` whenever `submitters` is empty, because with no submissions neither banner shows
at all — that case is handled before this predicate is reached, and is spelled out here only so the
empty-set edge is not left to inference.

**`Cohort.archived` does not participate.** A cohort gates self-enrolment eligibility, not class
membership; an archived cohort says nothing about whether a given student's work is historical. Only
`Group.archived` — which does mean "this class is finished" — softens the warning.

---

## 7. Content links

An internal content link pointing at a draft unit **renders normally and 404s on click** for a
student. This matches what already happens for a link to a deleted node, needs no per-link query on
every lesson render, and keeps the markup identical for authors and students. Suppressing the link
was considered and rejected on those two grounds.

---

## 8. Transfer

`FORMAT_VERSION` goes **9 → 10**. `published` joins the node payload in
`transfer/export.py`, the `_exact_keys` list in `transfer/schema.py`, and the node construction in
`transfer/importer.py`.

`schema._exact_keys` both requires every listed key and rejects every unlisted one, so a v9 archive
would otherwise fail with *"node is missing the key 'published'"*. The optional-key pattern already
documented at `schema.py:114` handles it:

```python
nd.setdefault("published", True)
```

**Default `True`, not `False`.** A v9 archive was exported from an install that had no concept of
drafts, so every unit in it was live; importing it as a pile of hidden units would be wrong.

**Containers are normalised on import.** `setdefault("published", True)` would give an imported
chapter `published=True` while a natively-created chapter gets `False` from the model default. The
field is meant to be ignored on containers either way, so neither value is *wrong* — but the
divergence means a bug like the one §3's `kind == UNIT` guard prevents would reproduce only on
natively-created containers and not on imported ones, which is a miserable thing to debug. The
importer therefore forces `published=False` on every non-unit node regardless of payload, so the two
creation paths agree.

### The bump breaks seven existing assertions — update them as one mechanical step

These pin the current value and go red the moment `FORMAT_VERSION` moves. They are listed because
otherwise an implementer meets them as a surprise failure sweep after the real work is done:

| File | Line | Assertion |
|---|---|---|
| `tests/test_link_transfer.py` | 54 | `FORMAT_VERSION == 9` |
| `tests/test_table_transfer.py` | 296 | `FORMAT_VERSION == 9` |
| `tests/test_tabs_transfer.py` | 62 | `FORMAT_VERSION == 9` |
| `tests/test_transfer_schema.py` | 57 | `FORMAT_VERSION == 9` |
| `tests/test_transfer_export.py` | 220 | `manifest["format_version"] == 9` |
| `courses/tests/test_beforeafter_transfer.py` | 165 | `FORMAT_VERSION == 9` |
| `courses/tests/test_image_size_transfer.py` | 41 | `FORMAT_VERSION == 9` |

`tests/test_table_transfer.py:560` also names the value in a **comment** (`4 <= FORMAT_VERSION=9`).
Update it too: comments in this repo are matched by source-scanning tests, so a stale one is not
merely untidy.

**Re-verify the value at rebase time, not at branch time.** Two branches bumping this constant to
the *same* number produce no git conflict — the change is line-identical, so it merges silently and
green, and the union of assertion sites is larger than either branch saw. Confirm `FORMAT_VERSION`
is still `9` on `origin/master` immediately before opening the PR, and re-run the grep for pinned
sites rather than trusting this table.

---

## 9. Testing

Per the project's standing rule, each test below names the mutation it must fail against. A test
that cannot be made red by breaking the thing it claims to cover does not count.

Tests carry **stable ids**, not positions, so a later insertion does not silently invalidate every
cross-reference in this document.

### Migration — `MIG`

- **MIG1. `0057` leaves existing rows published.** Apply the migration against a course built on the
  previous state (the `MigrationExecutor` pattern already used in
  `tests/test_subject_migrations.py`); assert every pre-existing node has `published=True`.
  *Mutant:* collapse the two operations into `AddField(default=False)` → every row is a draft → red.
- **MIG2. Migration state matches `models.py`.** Assert `makemigrations --check --dry-run` reports
  no pending change for `courses`. *Mutant:* drop the `AlterField` → migration state still says
  `default=True` while the model says `False` → a pending migration is detected → red.

  **Do not substitute "a node created after the migration defaults to draft" for this.** That
  assertion is green on the mutant — see §1 — and would be one more entry in this project's running
  tally of assertions that could not fail.
- **MIG3. A node created through the model defaults to draft**, and an existing node is untouched.
  Worth asserting, but as a guard on `models.py`'s declared default, not on the `AlterField`.
  *Mutant:* change `models.py` to `default=True` → red.

### Access — `ACC`

- **ACC1. A draft unit 404s for an enrolled student** on `lesson_unit`, and **renders for the
  owner**. *Mutant:* drop the `viewer` argument at the call site → student gets 200 → red.
- **ACC2. `is_staff` and an assigned group teacher both 404**, proving the gate is
  `can_manage_course` and not `can_access_course`. *Mutant:* implement `can_see_drafts` as
  `can_access_course` → both get 200 → red.
- **ACC3. Every unit-addressed POST 404s for a student on a draft unit** — parameterised over
  `seen`, `complete`, `element_state_save`, `check_answer`, `quiz_answer`, `quiz_finish`,
  **`notes.note_add`, `tags.tag_add`, `tags.tag_remove`**. *Mutant:* gate only the GET views → the
  POSTs still write → red. The three cross-app endpoints are the ones a `courses/`-scoped
  implementation misses.
- **ACC4. `node_permalink` 404s** on a draft unit for a student.
- **ACC5. A container created after the migration is reachable by every student.** Create a chapter
  natively (so it carries `published=False`), then assert a student gets a normal redirect from
  `node_permalink` and a normal `progress_reset` confirmation page for it. *Mutant:* drop the
  `kind == UNIT` guard from the chokepoint → both 404 → red. This is the test that catches the
  whole-course outage; without it the guard is a comment.

### Outline and progress — `OUT`

- **OUT1. A draft unit is absent from the outline and from `build_unit_nav`'s prev/next chain** —
  assert prev/next *skips over* the draft to the following live unit, not merely that the draft is
  absent.
- **OUT2. `required_total` excludes drafts.** Seed 10 obligatory lesson units, draft 7, assert the
  student's denominator is 3. *Mutant:* filter drafts in the outline but not in the rollup → 10 →
  red.
- **OUT3. A completed unit that is later drafted drops out of both numerator and denominator**, and
  its `UnitProgress` row is unchanged. *Mutant:* exclude from `required_total` only →
  `required_done` exceeds it → red.
- **OUT4. `additional_done` and the per-node `completed` key also exclude drafts.** Complete a
  *non-obligatory* lesson unit, then draft it; assert `additional_done` returns to 0 and the node's
  `completed` key is not `True` for a student. *Mutant:* add the publish gate to
  `is_obligatory_lesson` only → `additional_done` still counts it → red. **This is the counter the
  obvious implementation misses**, because it is the one expression in the rollup that never calls
  the shared predicate.
- **OUT5. A container whose units are all draft is pruned from the outline**, and reappears when one
  is published.
- **OUT6. `progress_reset`'s affected-count excludes drafts** for a student. Seed practice state on
  a unit, draft it, assert the confirmation page's count drops. *Mutant:* leave `units_under`
  unfiltered → count includes the invisible unit → red.
- **OUT7. `build_student_breakdown` keeps a draft unit that holds data**, even though its `user`
  argument is the *student*. *Mutant:* derive the filter from `build_outline`'s `user` instead of
  from an explicit parameter → the teacher-facing breakdown silently applies the student rule → red.

### Analytics — `ANA`

- **ANA1. A draft quiz with submissions keeps its gradebook column; a draft quiz with none has no
  column.** One test, both halves. *Mutant:* filter analytics identically to the student outline →
  the first half → red.
- **ANA2. A draft *lesson* unit with `UnitProgress` keeps its column**, proving the rule covers both
  models. *Mutant:* implement "holds data" as the `QuizSubmission` check alone → red.

### Write path — `WR`

- **WR1. A student and an assigned group teacher are both rejected** from `manage_node_flag`, on
  **both** the GET strip and the POST, with no write. *Mutant:* omit `_require_manage` → a student
  can unpublish the course → red.
- **WR2. Bulk publish writes every descendant unit and bumps `updated` on each.** Assert the
  `updated` values actually changed. *Mutant:* drop `updated=timezone.now()` from the `.update()` →
  tokens go stale → red. **The highest-value test in the file**: the bug it catches is invisible
  until the *next* edit to an affected row conflicts.
- **WR3. A stale token on a subtree toggle returns 409** and writes nothing.
- **WR4. `flag` outside the two-name allow-list is rejected** before any write.
- **WR5. A container toggle does not touch nodes outside its subtree** — seed a sibling chapter and
  assert it is untouched.
- **WR6. The unit-settings form round-trips `published`**, including unchecking it
  (absent-means-false).
- **WR7. The subtree POST returns a `_scope.html` fragment whose open descendant rows carry the new
  `data-updated` values** — i.e. a second edit to a descendant, using the token from the returned
  fragment, succeeds rather than 409ing. *Mutant:* return only the container's `<li>` → the
  follow-up edit 409s → red.
- **WR8. The draft banner's Publish redirects to its originating page**, for `ctx=editor` and
  `ctx=unit`. *Mutant:* return the builder row fragment → a template error or a nonsense response
  body → red.

### Tree rendering — `TREE`

- **TREE1. Enter in the title input still renames**, on a row that now carries the two toggle
  buttons. *Mutant:* place the toggles before the visually-hidden Rename button in DOM order →
  Enter publishes instead → red.
- **TREE2. A mixed container renders the half-state glyph**; all-live and all-draft render theirs.
- **TREE3. A container with zero units renders both icons disabled.**
- **TREE4. Container counts are computed over the FULL subtree while a filter is active.** Seed a
  chapter with 6 units, filter so only 2 match, assert the container's rendered count is 6.
  *Mutant:* fold over the template's `children_map` (`fc.restricted`) → 2 → red.
- **TREE5. Container toggles are `disabled` while a filter is active**; unit toggles are not.

### Quiz warning — `QZ`

- **QZ1. A submission from a student in a non-archived group → the loud banner.**
- **QZ2. All submissions from archived groups only → the quiet note.**
- **QZ3. A submitting student with NO group membership → the loud banner.** *Mutant:* implement the
  predicate as the single `exists()` on non-archived groups → the self-enrolled student's
  submissions read as "all archived" and the note goes quiet → red. This is the inversion §6 exists
  to prevent, and it is invisible without this specific fixture.
- **QZ4. A quiz with zero submissions shows neither banner.**

### Content links — `LNK`

- **LNK1. A link to a draft unit renders identically for author and student**, and the student
  gets 404 on following it. Pins §7's decision so a later "helpful" suppression is a deliberate
  change rather than a silent one.

### Visibility of drafts to authoring surfaces — `KEEP`

- **KEEP1. A course containing draft units exports all of them**, and the link picker lists them.
  *Mutant:* push the draft filter down into `units_in_order` or `_walk_preorder` → drafts vanish
  from the builder and are silently dropped from the export → red. This is the row of §2's table
  most likely to be broken by a well-meaning refactor, and dropping units from an export is data
  loss on transfer.

### Transfer — `TR`

- **TR1. `published` round-trips through export → import**, for both values.
- **TR2. A v9 archive imports with every unit published.** *Mutant:* `setdefault("published",
  False)` → everything imports hidden → red.
- **TR3. Imported containers land `published=False`**, matching natively-created ones.

### e2e — `E2E`

- **E2E1.** Clicking a unit's publish icon toggles it and applies the strike-through, without a page
  reload.
- **E2E2.** Clicking a container's icon opens the confirm strip; confirming updates every descendant
  row in the tree; the tree's scroll position and expansion state survive.
- **E2E3.** A draft unit is absent from the student's outline in a real browser session, and the
  author sees it with the draft banner.

`checkVisibility()` is required wherever a collapsed `<details>` is involved, and the confirm strip
must be synchronised on a condition rather than a sleep, per the project's e2e conventions.

---

## 10. i18n

New strings in the tree buttons, the confirm strip, the legend, the draft banners and the quiz
warning need PL/EN entries. `makemessages -l pl -l en --no-obsolete` then `compilemessages`, and the
result must be **0 fuzzy / 0 obsolete** — `makemessages` pre-fills fuzzy matches with *wrong*
translations for near-miss strings, and this feature adds several strings close to existing ones
("Publish" / "Published", "Hide" / "Hidden").

---

## 11. Out of scope

Named explicitly so they are not re-litigated mid-implementation:

- **Quiz versioning and re-grading** (§6). Warn only.
- **Scheduled publishing** (publish at a date/time). No requirement expressed.
- **Per-cohort or per-group publish state.** `published` is course-global.
- **A "publish everything" course-level action.** The root container's toggle already reaches every
  unit; a separate control would be a second way to do one thing.
- **Closing the element-level `*_check` leak** (§3).
- **Suppressing content links to drafts** (§7).
