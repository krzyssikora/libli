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
every deployed course on the next deploy. Migration `0057_contentnode_published` therefore carries
**two operations in one file**:

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

`AddField` backfills every existing row with `True`; `AlterField` then moves the *schema* default to
`False` so newly created rows land as drafts. No data migration, no separate RunPython, and the
reverse direction is a plain column drop.

**This ordering is the single most important line in the spec.** A reviewer who "simplifies" it to
one `AddField(default=False)` silently unpublishes every course in the install. The migration test
in §9 exists specifically to make that mutation fail.

---

## 2. What "hidden" means, per surface

`rollups._walk_preorder` stays **unfiltered**. It is the shared traversal behind the student
outline, the analytics builders and the unit nav, and those three audiences need three different
answers; pushing a filter into the walk itself would force every caller to opt back out.

Filtering becomes an explicit layer on top:

| Surface | Rule |
|---|---|
| Course outline, unit nav, prev/next, `required_total` / `required_done` / `additional_done` | Drop draft units. Drop containers whose subtree contains no visible unit. |
| Direct unit URL, node permalink, every unit-addressed POST | 404 for non-authors. |
| Analytics matrix, gradebook, student breakdown, review queue | Drop draft units **unless** the unit holds data (≥1 `QuizSubmission` or ≥1 `UnitProgress`). |
| Builder tree, link picker, course/subtree export | Everything, always. |

### Container pruning

A container whose subtree holds no visible unit is dropped from the student outline and nav. Without
this, a CA who drafts a whole new chapter leaves students staring at an empty "Chapter 4".

This also changes existing behaviour for containers that are genuinely empty (no units at all,
draft or otherwise) — those disappear from the student outline too. That is an improvement and is
adopted knowingly, not a side effect to be discovered later.

### Progress arithmetic

`rollups.is_obligatory_lesson` is the single gate on `required_total`. A draft unit must not count:
a student seeing "3 of 10 required units" with seven of them invisible has no way to reach 100%.
Both `required_total` and `required_done` therefore skip drafts, which keeps the ratio coherent —
including for a student who *had* completed a unit that was later pulled back to draft. Their
`UnitProgress` row is untouched; it simply stops being counted while the unit is hidden, and
resumes counting unchanged when it is published again.

### Analytics keeps columns that hold data

A CA pulling a live quiz back to fix a typo must not make a mid-term gradebook column blink out and
back. Teacher-facing surfaces therefore keep any unit with recorded data, flagged as draft, and
drop only drafts that never went live. The cost is one existence check per unit when building
columns; batch it with the maps `rollups._quiz_review_maps` already builds rather than issuing a
query per unit.

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
    ...
    if viewer is not None and not node.published and not can_see_drafts(viewer, node.course):
        raise Http404("node is not published")
```

404, never 403 — the existing docstring's convention ("a foreign node always 404s before any 403")
applies unchanged, and a 403 would make the endpoint an existence oracle for unreleased content.

Call sites that must pass `viewer=request.user`:

`lesson_unit`, `quiz_unit`, `quiz_results`, `progress_reset` (the node-scoped branch), `seen`,
`complete`, `element_state_save`, `check_answer`, `quiz_answer`, `quiz_finish`.

The POST endpoints matter as much as the GETs: a student holding a page that was open when the unit
got pulled must not be able to keep writing progress, answers or submissions into it.

`node_permalink` does not take a slug and so does not call `get_node_or_404`; it gets the same check
inline, immediately after its existing `can_access_course` test.

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

Both sit immediately before the `.tree__title` input — left of the name, after the kind badge.

**Implicit-submission hazard, unit rows only.** The row's comment warns that Enter in the title
picks the form's first submit button in *tree* order, which is why the visually-hidden Rename button
must stay ahead of the cluster. A unit's two toggle buttons must therefore appear *after* that
hidden Rename button in the DOM, while sitting left of the title visually.

`.tree__rowhead` is already `display: flex`, so the gap is closed by giving the two toggles a
negative `order` — a new use of a property the layout already supports, not a new layout. Authoring
them earlier in the DOM instead would make Enter publish a unit instead of renaming it.

**The accepted cost is a DOM-order / visual-order mismatch**: a screen reader reaches the toggles
after the title, not before it. This is tolerable specifically because each toggle's `aria-label`
states its full meaning and target-independent action ("Publish", "Make optional") rather than
relying on proximity to the title to be understood. The alternative — reordering the DOM — trades a
reading-order nuisance for a data-loss bug, which is the worse trade.

Container rows are unaffected: their controls are anchors, and anchors are not submitters. §9 pins
the Enter behaviour.

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

### Tri-state rollup

The builder view already builds `children_map` when rendering the tree. The same pass computes, per
container, `(live_unit_count, obligatory_unit_count, total_unit_count)` for its whole subtree —
one bottom-up fold over the already-loaded node list, no additional queries. A container with zero
units renders both icons disabled with a "no units" tooltip rather than a misleading empty state.

### Tooltips, labels and the legend

Every button carries both `title` (desktop hover) and `aria-label` (screen readers and touch, where
`title` does not exist), stating the *action*, not the state:

- ● → "Hide from students" / ○ → "Publish"
- ★ → "Make optional" / ☆ → "Make obligatory"
- Container mixed → "Publish or hide N units…"

`_structure_legend.html` gains the four unit states plus the mixed container state, because a
tooltip is not reachable on touch.

### Author-facing draft banner

Two places tell an author that what they are looking at is not live:

1. The **editor page** for a draft unit, above the element list.
2. The **student-facing render** of a draft unit, when viewed by an author.

Both read *"Draft — not visible to students"* and carry a Publish button posting to the same
`manage_node_flag` endpoint with `scope=node`.

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

Implementation is one `exists()` per quiz unit, joining `QuizSubmission → student →
GroupMembership → Group(course=…, archived=False)`.

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

No production install exists yet, so there is no deployed reader to coordinate with and no ordering
constraint against the mat-pp cutover. Recorded here because the reverse — a *new* archive fed to an
install running v9 code — is rejected outright by `_exact_keys` ("unknown key 'published'"), which
would matter the moment a second install exists.

---

## 9. Testing

Per the project's standing rule, each test below names the mutation it must fail against. A test
that cannot be made red by breaking the thing it claims to cover does not count.

### Migration

1. **`0057` leaves existing rows published.** Apply the migration against a course built on the
   previous state; assert every pre-existing node has `published=True`. *Mutant:* collapse the two
   operations into `AddField(default=False)` → every row is a draft → red.
2. **A node created after the migration defaults to draft.** *Mutant:* drop the `AlterField` → new
   units land published → red.

### Access

3. **A draft unit 404s for an enrolled student** on `lesson_unit`, and **renders for the owner**.
   *Mutant:* drop the `viewer` argument at the call site → student gets 200 → red.
4. **`is_staff` and an assigned group teacher both 404**, proving the gate is `can_manage_course`
   and not `can_access_course`. *Mutant:* implement `can_see_drafts` as `can_access_course` → both
   get 200 → red.
5. **Every listed POST endpoint 404s for a student on a draft unit** — parameterised over `seen`,
   `complete`, `element_state_save`, `check_answer`, `quiz_answer`, `quiz_finish`. *Mutant:* gate
   only the GET views → the POSTs still write → red.
6. **`node_permalink` 404s** on a draft node for a student.

### Outline and progress

7. **A draft unit is absent from the outline and from `build_unit_nav`'s prev/next chain** — assert
   prev/next *skips over* the draft to the following live unit, not merely that the draft is absent.
8. **`required_total` excludes drafts.** Seed 10 obligatory lesson units, draft 7, assert the
   student's denominator is 3. *Mutant:* filter drafts in the outline but not in the rollup → 10 →
   red.
9. **A completed unit that is later drafted drops out of both numerator and denominator**, and its
   `UnitProgress` row is unchanged. *Mutant:* exclude from `required_total` only → `required_done`
   exceeds it → red.
10. **A container whose units are all draft is pruned from the outline**, and reappears when one is
    published.

### Analytics

11. **A draft quiz with submissions keeps its gradebook column; a draft quiz with none has no
    column.** One test, both halves. *Mutant:* filter analytics identically to the student outline →
    the first half → red.

### Write path

12. **Bulk publish writes every descendant unit and bumps `updated` on each.** Assert the `updated`
    values actually changed. *Mutant:* drop `updated=timezone.now()` from the `.update()` → tokens
    go stale → red. **This is the highest-value test in the file**, because the bug it catches is
    invisible until the *next* edit to an affected row conflicts.
13. **A stale token on a subtree toggle returns 409** and writes nothing.
14. **`flag` outside the two-name allow-list is rejected** before any write.
15. **A container toggle does not touch nodes outside its subtree** — seed a sibling chapter and
    assert it is untouched.
16. **The unit-settings form round-trips `published`**, including unchecking it (absent-means-false).

### Tree rendering

17. **Enter in the title input still renames**, on a row that now carries the two toggle buttons.
    *Mutant:* place the toggles before the visually-hidden Rename button → Enter publishes instead →
    red. Pins the ordering hazard §5 names.
18. **A mixed container renders the half-state glyph**; all-live and all-draft render theirs.
19. **A container with zero units renders both icons disabled.**

### Transfer

20. **`published` round-trips through export → import**, for both values.
21. **A v9 archive imports with every unit published.** *Mutant:* `setdefault("published", False)` →
    everything imports hidden → red.

### e2e

22. Clicking a unit's publish icon toggles it and applies the strike-through, without a page
    reload.
23. Clicking a container's icon opens the confirm strip; confirming updates every descendant row in
    the tree; the tree's scroll position and expansion state survive.
24. A draft unit is absent from the student's outline in a real browser session, and the author sees
    it with the draft banner.

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
