# Previewer unit completion

## Purpose

A Course Admin (or any other non-enrolled viewer who can access a course — the course owner, a
group teacher, a Platform Admin) opens a lesson unit and sees a **"Mark as done"** button. Clicking
it does nothing: the page redirects back and the button is still there. Nothing is stored, and the
UI gives no hint why.

That is a lying affordance, and it is also inconsistent with the rest of the page. Since PR #136 —
reaffirmed by the practice-state slices — a non-enrolled viewer's *own* practice state (mark-done
checklist ticks, reveal gates, restored question answers) **does** persist, on the stated principle
that this is personal self-tracking rather than analytics. Unit completion is the one visible,
explicit control that still silently no-ops.

This spec resolves the inconsistency in the direction the rest of the page already took: **an
explicit "Mark as done" click persists for any viewer who can access the course.** Scroll-based
auto-completion deliberately stays enrolled-only.

### The decision, and why

The alternative — hiding the button for non-enrolled viewers — was considered and rejected. The
completion pill is not the only progress chrome such a viewer sees: the course outline's ✓ badges,
the unit tree's "X of Y required units completed" counters, and the unit footer's course-progress
bar all read from **the viewer's own** `UnitProgress` rows (`courses/rollups.py`, the
`student=user` query). Hiding one control while leaving the other three pinned at zero — which is
what a viewer who was *never* enrolled sees — is a half-fix. Making the click work lights all four
up coherently. (A viewer who was enrolled *previously* is a different case: `build_outline` gates
only on `user.is_authenticated`, so their badges already show. See Data flow, "Pre-existing rows".)

The *scroll* path is excluded for a distinct reason: completion is not undoable. `progress_reset`
never clears `completed`, and `templates/courses/progress_reset_confirm.html` explicitly promises
"lessons you have completed stay completed." A teacher paging through twenty units to check
formatting would silently and irreversibly "complete" all of them. An explicit button click is an
intentional act; an IntersectionObserver firing is not.

**The button's own irreversibility is accepted, deliberately — and the asymmetry with scroll is the
point.** A fair objection is that this change makes a permanent, unrecoverable mark reachable by one
click from a population that has spent the product's whole life learning the button is a no-op, so
the first click is plausibly exploratory. Three things make that acceptable where the scroll path is
not:

1. **Blast radius.** A misclick marks exactly the one unit the viewer is looking at, and the pill
   changes visibly and immediately, so the consequence is legible at the moment it is incurred.
   Scroll-tracking marks every unit visited, silently, with no per-unit moment of consent.
2. **Parity, not novelty.** This is precisely the exposure every enrolled student has had since the
   feature shipped: one click, permanent, no undo. The change does not make the button more
   dangerous than it already is for the population it was designed for; it stops making it *lie* to
   everyone else.
3. **Consequence.** The mark lands only in the viewer's *own* progress chrome (see the roster-scoped
   analysis below), so a stray click misinforms nobody but the person who made it. Testing §10 pins
   this rather than leaving it as an argument.
4. **A recovery route exists, for exactly this population.** `courses/admin.py` registers an
   editable `UnitProgressAdmin` with `completed` in `list_display` — and the dominant previewer is
   `is_staff`, i.e. precisely who can reach it. It is a permission-gated admin action, not a product
   affordance, so it does not make the button safe; it does mean a mis-click is recoverable by the
   people most likely to make one.

The file being edited argues the opposite doctrine for a neighbouring hazard, and that deserves a
direct answer rather than silence: `progress_reset`'s docstring says reset is "the student's
protection against automatic persistence — shipping it as a one-click no-undo form for no-JS
students would make the safety valve the hazard." That reasoning is about **automatic** persistence
and about the *reset* control specifically; the mark-done button is neither automatic nor a safety
valve. Bullet 2 is the answer: this spec adds no new hazard shape, it extends an existing,
deliberate one to a population the same product already exposes to it.

The escape hatch — making `progress_reset` clear `completed`, or turning the pill into a toggle — is
therefore **out of scope here and stays a non-goal**, but as a scoping decision rather than an
oversight: it would change behaviour for every enrolled student on the platform, which is a distinct
product question deserving its own spec, not a rider on a two-line previewer fix. This spec is
written so that adding a reset later requires no rework of anything it ships.

## Current behaviour (verified against base `87c7a44b`)

- **The control.** `templates/courses/_lesson_article.html:12-23` renders the completion pill
  unconditionally. For a non-enrolled viewer the ambient `progress` is `None`, so `progress.completed`
  is falsy and the `{% else %}` branch — the `<form>` POSTing to `courses:complete` — always wins.
- **The write.** `courses/views.py::complete` (≈:671-685) gates on `can_access_course` (raising
  `PermissionDenied` otherwise), then writes **only** inside `if is_enrolled(request.user, course)`.
  A non-enrolled viewer's POST therefore falls through to the redirect having written nothing.
- **The read.** `courses/views.py::build_lesson_context` (≈:385-399) sets `progress` only in the
  `is_enrolled` branch. The `elif user.is_authenticated` branch fetches a `state_row` for practice
  state via `UnitProgress.objects.filter(...).first()` — deliberately no `get_or_create` on a GET —
  but never assigns `progress`.
- **The scroll path.** `courses/views.py::seen` (≈:651-655) returns a synthetic
  `{"seen_element_ids": [], "completed": false, "completed_at": null}` for a non-enrolled viewer and
  writes nothing. `courses/static/courses/js/progress.js` and `slideshow.js` both only call
  `window.unitMarkDone()` when the server reports `completed`, so the pill never flips.
- **Who "can access".** `courses/access.py::can_access_course` delegates to `accessible_courses`:
  `is_staff` (which includes the Course Admin role — `institution.roles.COURSE_ADMIN` is a staff
  role) ⇒ all courses; otherwise enrolled ∪ owned ∪ taught-via-non-archived-group.

## Architecture / components

Two behavioural edits in `courses/views.py`, four comment corrections in the same file, one
deliberate non-edit, and one existing test inverted. No migration, no model change, no new URL, no
template change, no JS change, no new translatable strings.

### 1. The write — `courses/views.py::complete`

Drop the `is_enrolled` branch so `can_access_course` (already checked immediately above) is the sole
guard on the write, and take the same lock `save_element_state` takes two functions below:

```python
with transaction.atomic():
    UnitProgress.objects.get_or_create(student=request.user, unit=node)
    progress = UnitProgress.objects.select_for_update().get(
        student=request.user, unit=node
    )
    if not progress.completed:
        progress.completed = True
        progress.save()  # completed_at stamped in save()
```

Lifting the gate is the same reversal PR #136 applied to `markdone_save`, for the same stated
reason: the row is the viewer's own record, not course analytics. `get_or_create` is correct and
intended here — a POST is an explicit act, so creating the row on it does not violate the "no
spurious rows on a GET" rule.

**Why the lock, when the old code had none.** `progress.save()` carries no `update_fields`, so it
writes every column from the in-memory instance — including `element_state` as it was at fetch time.
A checklist tick landing between the fetch and the save is silently lost. That window exists today
on the enrolled path, but this change extends it to the previewer population, who sit on the very
same page as the checklist. `courses/views.py::save_element_state` already solves exactly this with
`transaction.atomic()` + `select_for_update()`, so this is the file's own house pattern rather than
a new mechanism: same columns written, same semantics. `update_fields` was the other candidate and
is **rejected**: it would change which columns the enrolled path writes, a genuinely different
change with its own regression surface.

**Be precise about what the lock does and does not close.** A row lock only excludes writers that
also take it. It therefore closes the window against `save_element_state`'s callers (`check_answer`
and `element_state_save`) — which is the *only* concurrent writer the previewer population can
reach, so for the population this change admits, the window really is shut. It does **not** close
the window against `seen` (≈:662-667), which is still `get_or_create` → mutate → bare
`progress.save()` with no atomic block and no lock, writing every column from its own fetch. A
`seen` flush that began before a `complete` commit can therefore write `completed=False` back over
it, and can clobber an `element_state` key the same way. That is pre-existing, enrolled-only (a
previewer never reaches `seen`'s write at all), and on the highest-frequency writer in the file —
a 500 ms debounce during scroll — so hardening it is **out of scope**: it would change the hot path.
Do not read "closed" as "the row is now lock-protected in general."

**Cost:** the new shape is `get_or_create` (SELECT, sometimes INSERT) plus a second
`SELECT … FOR UPDATE`, inside a savepointed atomic block, where the old shape was one SELECT and —
when the unit was already complete — nothing further. That is +1 query and a transaction per
`complete` POST, on the enrolled path too. No `assertNumQueries` / `CaptureQueriesContext` test
currently covers `complete` (verified), so nothing breaks; but Testing §11 wraps this very endpoint
in `CaptureQueriesContext`, so its assertion must target `UPDATE` on `courses_unitprogress`
specifically, never "no writes" — SELECT and SAVEPOINT traffic is expected and correct.

### 2. The read — `courses/views.py::build_lesson_context`

In the existing `elif user.is_authenticated:` branch, additionally assign `progress = state_row`.

This is the load-bearing half. PR #136's recorded lesson is that **the enrollment gate must be
lifted in both the write and the read, or saved state never re-renders.** Without this edit the
write lands but the pill still says "Mark as done" after the redirect, and the change is invisible —
indistinguishable from the bug being fixed.

`state_row` remains a `.filter(...).first()`, so:

- a passive GET by a non-enrolled viewer still creates **no** `UnitProgress` row;
- when no row exists, `progress` is `None`, `progress.completed` is falsy, and the button renders —
  correct;
- when a row exists with `completed=False` (e.g. created by an earlier checklist tick), the button
  renders — also correct.

`seen_ids` is *not* sourced from this branch and stays empty for a non-enrolled viewer, so
`seen_count` remains 0 for them. That is today's behaviour and is not user-visible on the lesson
page; it is stated here so the asymmetry is deliberate rather than discovered.

**The lesson page has three render surfaces, not one — and the docstring that says "two" is itself
wrong.** `build_lesson_context` is reached via `full_lesson_render_context`, which has three
callers:

- `courses/views.py:605` — `lesson_unit`, the GET;
- `courses/views.py:846` — `check_answer`, but **only on its no-JS branch**;
- `notes/views.py:194` — the no-JS note-create re-render on an invalid `NoteForm` (renders
  `courses/lesson_unit.html` with status 422).

All three now show "✓ Completed" to a previewer who has marked the unit, which is the correct
outcome and comes for free from the single shared assignment.

**`check_answer`'s JS path never re-renders the pill at all.** `full_lesson_render_context` is
called only *after* the `if _wants_fragment(request):` early return (`views.py:825-845`), and
`_wants_fragment` is `request.headers.get("X-Requested-With") == "fetch"` — the header
`courses/static/courses/js/question.js:29` always sets. So in the real JS-enabled UI a Check click
returns a bare question fragment and the pill is untouched. Only the no-JS fallback re-renders the
whole lesson. Testing §7 must therefore drive a POST **without** that header (the Django test
client's default); adding the header to "mimic the real UI" would test the fragment branch, which
this change does not touch.

`notes/views.py:194` is **exempt from its own test in writing**: it makes the identical
`full_lesson_render_context(unit, user)` call that test 7 already drives, with no additional
progress-related logic between the call and the template. A third near-duplicate test would pin the
caller list rather than any behaviour.

### 2b. Four comments in `courses/views.py` that this change makes wrong

Comments in this codebase carry design contracts, so leaving them stale would ship a file arguing
against its own behaviour. All four are corrections of fact, not new prose:

- **≈:784-788** (in `element_state_save`) reads: persisting practice state for any accessing viewer
  "deliberately diverges from seen/quiz (which ignore previewers so authors don't pollute their own
  progress/analytics)". The **enumeration is already correct** — it names `seen`/quiz and never
  mentions `complete`, so there is nothing to narrow; do not go hunting for a broader list. The
  **parenthetical rationale** is the part this change falsifies: it must stop implying that progress
  writes in general exclude previewers, since completion now does not.
- **≈:396-398** (the `elif user.is_authenticated` branch in `build_lesson_context`) says the row is
  read "for their practice state". It now also feeds the completion pill; the comment must say so,
  and must keep stating why the read is `.filter().first()` rather than `get_or_create`.
- **≈:273-275** (`build_lesson_context`'s docstring) is wrong twice. It says the function is "Used
  by **both** `lesson_unit` (GET) and `check_answer` (POST re-render) so **the two** cannot drift" —
  already false today; and it says the function "Performs the same `UnitProgress.get_or_create` +
  seen-count as a normal view", which is true only on the enrolled path. Fix both clauses. For the
  first, do **not** re-enumerate the render sites: `build_lesson_context` has exactly one production
  caller, `full_lesson_render_context`, whose own docstring (`views.py:449-450`) already lists all
  three sites. Say it is reached through `full_lesson_render_context`, which serves every render site
  (see its docstring) — copying the list here just creates a second copy to drift. For the second,
  name the non-enrolled path's read-only row lookup. Do not correct only one sentence: the diff
  deliberately edits this docstring, so leaving a known-false contract in it is worse than never
  having touched it.
- **≈:652** (in `seen`) reads `# untracked preview: no write, synthetic canonical response`. After
  this change a preview is no longer "untracked" in any general sense — the viewer's completion and
  their practice state both persist; it is specifically the **scroll signal** that is dropped. This
  comment sits exactly at the asymmetry the spec most wants legible, so it must name that asymmetry:
  seen-tracking is not recorded for previewers, while completion via the explicit button is.

### 3. Deliberately unchanged — `courses/views.py::seen`

`seen` keeps its `is_enrolled` gate and its synthetic response. This is a specified non-goal, not an
oversight; see "The decision, and why" above. The existing test asserting it must stay green.

### 4. Also unchanged

`progress_reset` (completion stays non-resettable), the quiz endpoints (`quiz_answer` /
`quiz_submit` still `raise PermissionDenied` for non-enrolled viewers — a graded submission genuinely
is a student record), `unit_done.js`, `progress.js`, `slideshow.js`, and every template.

## Data flow

**Before (non-enrolled viewer):**

```
GET lesson  → build_lesson_context: progress = None       → button renders
POST complete → can_access ✓ → is_enrolled ✗ → no write   → redirect
GET lesson  → progress = None                             → button renders (unchanged)
```

**After:**

```
GET lesson  → build_lesson_context: state_row = None → progress = None → button renders
POST complete → can_access ✓ → get_or_create + completed=True         → redirect
GET lesson  → state_row = the row → progress = row (completed=True)   → "✓ Completed" pill
```

**Also after (the other two render surfaces, fed by the same one assignment):**

```
POST check_answer (no-JS, no X-Requested-With) → full_lesson_render_context → pill stays "Completed"
POST check_answer (JS, X-Requested-With: fetch) → early return, question fragment only → pill untouched
POST note create (invalid form, 422)            → full_lesson_render_context → pill stays "Completed"
```

**Unchanged in both:**

```
scroll → POST seen → is_enrolled ✗ → synthetic {"completed": false} → pill never flips
```

**Downstream, viewer-scoped (starts working, by design):** `courses/rollups.py`'s per-viewer
completed-unit-id query (`student=user, unit__course=course, completed=True`) feeds the outline ✓
badges, the unit-tree required/additional counters, and the footer course-progress bar. These begin
reflecting the viewer's own manual marks. Note the tree and footer also render on **quiz** unit
pages — `quiz_unit.html:11` includes the same `_unit_shell.html`, and the quiz view builds its
`unit_nav` through the same `build_unit_nav` call — so a previewer's lesson completions move those
counters there too. No separate test: it is the same call, on the same data.

**Downstream, roster-scoped (contained, with a stated boundary):** the teacher-facing
frontier/matrix query in `courses/rollups.py` filters `student__in=students`, where `students` comes
from `grouping/scoping.py::students_in_scope` — an **Enrollment- or GroupMembership-derived**
roster (Enrollment on the PA/owner fallback; GroupMembership for the group-teacher fallback and both
explicit `group:<pk>` / `collection:<pk>` scopes). So a non-enrolled viewer's row cannot appear in
teacher analytics or the gradebook **while that viewer is off the roster**. That the two derivations
agree rests on `add_students_to_group` / `remove_students_from_group` keeping GroupMembership ⊆
Enrollment — an invariant maintained by those services, not enforced by the query. The containment
is the roster filter, never any property of the row itself; see "Enrollment transition" below for
what happens when that premise stops holding.

**And the write is inert beyond that row.** Worth stating because the sibling completion write is
not: `quiz_finish` calls `notify_needs_review` **and** `emit_result_finalized` (the SIS webhook)
right after setting `completed`. `complete` emits neither, and `UnitProgress` carries no `post_save`
receiver — `courses/signals.py` registers only a `post_delete` on `MediaAsset`. So a previewer's
mark sends no notification and fires no webhook.

**Pre-existing rows (a visible day-one change for one population).** The read edit does not only
surface rows the viewer creates. Someone who *was* enrolled earlier — a teacher enrolled for a
pilot, a Course Admin who took the course — still has `completed=True` rows from that time. Today
`progress` is `None` for them once the enrollment is gone, so the button renders; after this change
the pill reads "✓ Completed" on the very first page load, with no click. This is **intended**: their
outline ✓ badges already show those units as done (`rollups.py` never checked enrollment), so today's
lesson page is the surface that is lying, not the outline. It is called out because it is a visible
change to existing data that no POST triggers, and it gets its own test (Testing §6).

## Error handling

- **No access** — `complete` still raises `PermissionDenied` before any write for a user failing
  `can_access_course`; anonymous users are stopped earlier by `@login_required`. Unchanged.
- **Wrong node** — `get_node_or_404(..., require_unit=True, require_lesson=True)` still 404s a
  foreign or non-lesson node before the access check. Unchanged.
- **Double POST** — `get_or_create` plus the `if not progress.completed` guard keeps the write
  idempotent; `completed_at` is stamped once, in `UnitProgress.save()`. `UnitProgress` carries a
  `UniqueConstraint(student, unit)`, so concurrent `get_or_create` calls cannot produce a duplicate
  row.
- **Concurrent `element_state` write — closed against every writer the previewer can reach.** The
  full-row `save()` would otherwise clobber a checklist tick that landed between the fetch and the
  save; §1 closes that window with `transaction.atomic()` + `select_for_update()`, the pattern
  `save_element_state` already uses. See §1 for why that mitigation was chosen over `update_fields`,
  and — importantly — for what it does **not** close: `seen` remains an unlocked full-row writer on
  the enrolled path. This is a *concurrency* window — a write landing inside another request — so no
  sequential test can sample it; Testing §11 pins the observable consequence (a second POST issues
  no UPDATE at all) rather than pretending to reproduce the race.
- **No row on GET** — the read path stays `.filter().first()`. A `None` `progress` is a valid,
  expected state that the template already handles.
- **Method** — `complete` remains `@require_POST`; a GET cannot complete a unit.

## Testing

Every test below must be **falsifiable**: remove the guard it exists for, confirm RED, restore. The
repo's recorded scar is that a passing test proves nothing.

### Inverted (not extended)

`tests/test_courses_progress.py::test_previewer_complete_redirects_without_write` asserts today's
no-op (`assert not UnitProgress.objects.filter(student=staff, unit=unit).exists()`). It is a
deliberate reversal of a shipped guarantee, exactly as PR #136 reversed markdone's, and becomes
`test_previewer_complete_persists`. It must be rewritten, never left alongside a contradicting new
test.

### New / adjusted

1. **Write.** A non-enrolled `can_access` viewer POSTs `courses:complete` → a `UnitProgress` row
   exists for them with `completed=True` and a stamped `completed_at`.
   *(This **is** the inverted test named above, rewritten in place — not a second test alongside
   it.)*
   *Falsify:* restore the `is_enrolled` branch in `complete` → RED.
2. **Read (the one that catches a write-only fix).** After that POST, the same viewer GETs the
   lesson → the response shows the "Completed" pill and **not** the "Mark as done" submit button.
   *Falsify:* revert `progress = state_row` → RED while test 1 stays green.
   Assert on markers that cannot false-pass: `unit-done__pill--btn` (the button class) absent, and
   `is-complete` present. Two facts make `is-complete` safe as a body substring **today**:
   `_lesson_article.html:12` is its only template occurrence, and its other two occurrences
   (`courses.css`, `unit_done.js`) are external assets that never enter the response body. Neither
   is guaranteed to hold forever, so scope the assertion to the `[data-unit-done]` element (parse it
   out, or match `unit-done[^"]*is-complete`) rather than searching the whole body.
3. **Asymmetry guard (the deliberate non-edit).** A non-enrolled `can_access` viewer POSTs every
   element id to `courses:seen` → still no completion and no row. The existing
   `test_previewer_seen_no_write_synthetic` covers this; keep it adjacent to test 1 so the
   deliberate split between the two paths is legible on one screen.
   *Falsify:* temporarily drop the `is_enrolled` gate in `seen` → RED. Note this guard is *outside*
   the diff — the recipe removes code the change does not touch, which is exactly the point: the
   test's job is to catch a future implementer "finishing the job" by lifting both gates.
4. **No spurious row on GET — this guard already exists; do not duplicate it.**
   `courses/tests/test_markdone_render.py::test_passive_non_enrolled_viewer_gets_no_progress_row`
   already asserts that a non-enrolled viewer GETting the lesson creates no `UnitProgress` row, with
   exactly this falsification recipe. It must stay green; it is the test that catches an implementer
   "tidying" the read into a `get_or_create` while making `progress` available. Note it lives in
   `courses/tests/`, **not** the top-level `tests/` package where every other test named here lives
   — an implementer scanning only `tests/` will not find it and will write a silent duplicate, which
   this spec's own doctrine (invert, don't double; the `notes/views.py` exemption) forbids.
   *Falsify:* change the non-enrolled read from `.filter().first()` to `get_or_create` → RED.
5. **Every access route driven, positively and negatively.** `can_access_course` is now the sole
   guard on the write, and it admits three distinct non-enrolled routes — `is_staff`, course owner,
   and teacher of a **non-archived** group. The repo's recorded lesson is that widening a write
   requires driving each newly-reachable role end to end, so each positive route must reach a
   successful write, not merely its negative twin:
   - **(a)** a non-staff **course owner** POSTs `complete` → row written, `completed=True`;
   - **(d)** a non-staff, non-owner **teacher of a non-archived group** attached to the course POSTs
     `complete` → row written, `completed=True`. It is the only positive route not otherwise covered
     (`is_staff` is covered by test 1). Be accurate about *why* it earns a test: **not** because it
     is the common production previewer — it is not. `institution/roles.py::role_is_staff` returns
     `True` for every role except Student, and `accounts/services.py` sets `is_staff` from it, so a
     production Teacher short-circuits `accessible_courses` at `if user.is_staff: return
     Course.objects.all()` and never reaches the group clause at all. Route (d) is reachable in
     production only by a user whose *role* is Student (or who was created outside `set_user_role`)
     yet teaches a group — an edge shape. It is tested because the branch exists in
     `accessible_courses` and is now the sole guard on a write. The dominant production previewer is
     the `is_staff` route, covered by test 1;
   - **(b)** a user whose only link is an **archived** group they teach → 403 and **no** row — the
     negative twin of (d), making the `groups__archived=False` pin in `accessible_courses` visible
     from both sides;
   - **(c)** a logged-in user with no relationship to the course → 403 and no row.
   (b) and (c) are **regression guards on unchanged access behaviour**, not new boundaries: `complete`
   already 403s both cases today at the `can_access_course` check, ahead of the `is_enrolled` branch.
   What changes is that this gate becomes the *only* thing standing between them and a write, which
   is what makes the guards load-bearing. Reserve "newly reachable" for the positive routes.
   **Fixture wiring, and two vacuity traps.** `grouping.Group` has a `course` FK, a `teachers` M2M
   and an `archived` boolean, so (b) and (d) are built with `GroupFactory(course=course)` +
   `group.teachers.add(user)` + `archived=True` / `False`. Then:
   - **Trap 1 — `is_staff` short-circuit.** `accessible_courses` returns `Course.objects.all()` at
     `if user.is_staff:` *before* evaluating either `Q(owner=user)` or the group clause. So **(a),
     (b) and (d) must each assert their user is non-staff** — not just (b) and (d). A staff owner in
     (a) passes via the wrong route and proves nothing about the owner clause; `CourseFactory`'s
     owner comes from `UserFactory`, so this is fixture-dependent rather than guaranteed.
     (`tests.factories`' `_make_role` never sets `is_staff`, so the role helpers are safe.)
   - **Trap 2 — enrollment.** (a) and (d) must assert
     `not Enrollment.objects.filter(student=user, course=course).exists()`. An enrolled owner or
     group teacher writes on the **base** commit too, via the `is_enrolled` branch, so the test
     would be green before and after the change — vacuous with respect to this diff, and the
     `can_access_course` recipe below would never catch it.
   *Falsify (gate):* drop the `can_access_course` check in `complete` → (b) and (c) go RED.
   *Falsify (diff-local):* restore the `is_enrolled` branch in `complete` → (a) and (d) go RED.
6. **Pre-existing row, both directions.** One fixture shape, two cases that must not be collapsed:
   - **(a) `completed=True`.** Seed such a row for a user who is **not** enrolled but can access →
     a plain GET of the lesson (no POST at all) shows the "Completed" pill. Pins the Data-flow
     "Pre-existing rows" paragraph as intended behaviour rather than an accident.
     *Falsify:* revert `progress = state_row` → RED.
   - **(b) `completed=False` — the case that catches a wrong assignment.** Seed a
     `completed=False` row carrying `element_state` for a non-enrolled `can_access` viewer → the GET
     shows `unit-done__pill--btn` **present** and `is-complete` **absent** on `[data-unit-done]`.
     This is not hypothetical: since PR #136 a previewer who ticks a checklist gets exactly this
     row, making it the *most common* previewer row in production once this ships. It is also the
     only shape where the read edit can produce a visibly wrong answer — assign anything merely
     truthy (`progress = state_row or UnitProgress()`, a sentinel, a fresh unsaved instance) and a
     viewer who never clicked is told "✓ Completed", while every other test in this list stays
     green. Test 4 only asserts no row is created; test 2 and 6(a) only cover the `True` direction.
     *Falsify:* assign any truthy non-row value to `progress` in the non-enrolled branch → RED.
7. **The second render surface: `check_answer`'s no-JS path.** A non-enrolled viewer with a
   `completed=True` row POSTs a Check on a question in that unit — **without** an
   `X-Requested-With: fetch` header — → the re-rendered lesson still shows the "Completed" pill.
   The header omission is load-bearing, not incidental: with it, `_wants_fragment` short-circuits to
   a question fragment that never renders the pill (see Architecture §2), and an implementer who
   adds the header to imitate the real UI will get a confusing failure against behaviour this change
   does not touch. Covers `notes/views.py:194` by the exemption argued in §2.
   *Falsify:* revert `progress = state_row` → RED (both render paths share the one assignment,
   which is precisely why this test must name the POST path explicitly rather than trusting test 2
   to cover it).
8. **Enrollment transition (pins an accepted decision, not a guard).** A non-enrolled viewer marks a
   unit done, is **then** enrolled → the row survives with `completed=True` and now counts as
   learner progress. **Drive the roster derivation, do not bypass it.**
   `build_progress_matrix(course, students, ...)` takes `students` as a parameter and applies no
   roster logic of its own, so handing it `[viewer]` makes the cell non-zero *before* enrollment too
   and the test would assert nothing about the transition. Instead feed it from
   `grouping/scoping.py::students_in_scope(owner_or_teacher, course, "all")`, and assert the viewer
   is **absent** from that queryset before enrollment and **present** after. `build_progress_matrix`'s
   `lesson_pks` come from `is_obligatory_lesson`, so the seeded unit must be an **obligatory lesson**
   unit for the cell to move. Keep the row-survival assertion (`completed=True` still set after
   enrollment) alongside. Label the test in a comment as documenting the "Enrollment transition"
   decision, so nobody mistakes it for a safety guard.
   *Falsify:* add any enrollment-time clearing or preview-origin filtering of completions → RED.
9. **Downstream chrome actually lights up** — the spec's whole rationale for fixing rather than
   hiding. These are **two different pages** and must be two GETs:
   - the **course outline** page (`course_outline` → `outline.html` → `_outline_node.html:8`) → the
     ✓ badge renders for that unit. Holds regardless of the unit's `obligatory` flag —
     `d["completed"]` is set for any completed lesson unit. **Scope the assertion to the seeded
     unit's own row**: `outline.html` renders the whole course tree and `_outline_node.html:8` emits
     an identical bare `badge--done` span for *every* completed unit, so a body-wide substring check
     false-passes the moment any other unit is complete. `_outline_node.html:3` puts
     `data-unit="{{ item.node.pk }}"` on the `<li>` — **parse the `li[data-unit="<pk>"]` subtree**
     and assert inside it. A naive `data-unit="<pk>"[^>]*>` … `badge--done` regex does **not** work:
     `[^>]*>` stops at the `<li>`'s own closing `>`, so the match is unbounded on the right and runs
     straight into a later unit's badge — the exact false-pass the scoping exists to prevent. If a
     regex is preferred over parsing, bound it: `_outline_node.html:5` puts `outline-unit--done` on
     the same unit's `<a>`, so matching that non-greedily between `data-unit="<pk>"` and the next
     `data-unit=` is one correctly-bounded check. Seed no other completed unit either way;
   - the **lesson unit** page (`_unit_shell.html` → `_unit_footer.html:3-5`) → `unit_nav.course_progress.done`
     is non-zero. This half **requires an obligatory lesson unit**: `course_progress.done` sums
     `required_done`, which `rollups.py` sets only when `is_obligatory_lesson(node)`, and the footer
     bar does not render at all unless `course_progress.total` is truthy. `ContentNode.obligatory`
     defaults to `True`, so a default fixture works — but an implementer seeding a plausibly
     "additional" unit would get a failure unrelated to this change. Asserting on
     `build_unit_nav(...)["course_progress"]` directly is an acceptable alternative to parsing the
     footer.
   The two assertions exercise different rollup paths; do not collapse them into one response.
   *Falsify (diff-local, the one that matters):* restore the `is_enrolled` branch in `complete` →
   RED, proving the test is non-vacuous with respect to *this* change.
   *Secondary (wiring check only):* break `build_outline`'s authenticated
   `student=user, ..., completed=True` query → RED — but note this reddens much of the existing
   outline/nav suite too, so it demonstrates the rationale is still wired, not that this test earns
   its place.
10. **Containment: an off-roster previewer is invisible to teacher-facing surfaces.** This is the
    claim the entire "fix rather than hide" decision rests on, and the spec itself flags its premise
    (GroupMembership ⊆ Enrollment) as maintained by services rather than enforced by the query — the
    exact shape the repo's access-widening doctrine says to drive end to end. A non-enrolled
    `can_access` previewer marks a unit done; then, as the course owner or a teacher, resolve
    `students_in_scope(teacher, course, "all")` and build the analytics matrix from it.
    **The fixture must contain a genuinely enrolled student, and both halves must be asserted:**
    that student **is** a row, and the previewer **is not**. With nobody enrolled,
    `students_in_scope` returns empty, `build_progress_matrix` short-circuits at
    `if all_lesson_pks and students:` and returns `rows == []` — "the previewer is not a row" would
    then hold for a reason that has nothing to do with the roster filter. The claim the containment
    argument needs is "the matrix is populated **and still** omits them".
    *Falsify:* enroll the previewer → RED (they appear), proving the assertion discriminates.
11. **Double POST is idempotent and writes nothing the second time.** A previewer POSTs `complete`
    twice → exactly one row, and `completed_at` **on the DB row** is unchanged after the second POST
    (`complete` returns a bare 302 with no body, so there is no response field to compare — assert
    against the row).
    The load-bearing assertion is the third: **the second POST issues no `UPDATE` on
    `courses_unitprogress`** — wrap it in `CaptureQueriesContext` and assert no captured statement
    updates that table. Do **not** assert instead that an `element_state` key written between the
    two POSTs survives: `get_or_create` re-reads the row on POST 2, so the in-memory instance
    already carries that key and a guardless `save()` writes it straight back. That assertion stays
    GREEN with the guard deleted — it is vacuous, and the clobber it appears to test is a
    *concurrency* window that no sequential test can sample (see the repo's "tests that sample race
    windows" lesson). Likewise `completed_at` alone cannot carry the test: `UnitProgress.save()`
    only stamps when it is `None`, so the timestamp stays correct without the guard; and "exactly
    one row" is guaranteed by `get_or_create` plus the unique constraint either way.
    *Falsify:* delete the `if not progress.completed:` guard → the redundant UPDATE appears → RED on
    the query assertion (and only on that one — which is precisely why it is the assertion that
    matters).
12. **Enrolled path unregressed.** The existing enrolled complete/auto-complete tests
    (`test_seen_merges_and_autocompletes`, `test_zero_element_unit_completes_only_via_fallback`)
    stay green.
    *Falsify:* exempt — these are pre-existing tests being protected from regression, not new
    guards. Per the falsifiability doctrine, a test whose behaviour the diff does not change has no
    honest RED recipe, and claiming one would be theatre.

**File placement (one rule, since placement is load-bearing here).** Every new test in this list
lands in `tests/test_courses_progress.py`, beside the inverted test — including tests 9 and 10, which
have plausible homes in `tests/test_courses_rollups.py` and the analytics-scoping tests but belong
here, because their whole point is what *this* change does to those surfaces and the co-location is
the signal. The sole exception is test 4, which is not new: it already exists as
`courses/tests/test_markdone_render.py::test_passive_non_enrolled_viewer_gets_no_progress_row`, in a
different package, and stays there.

Use `tests.factories`' helpers and `TEST_PASSWORD`; never a hardcoded password. The existing
previewer tests build their viewer as `is_staff = True`, which is the production-accurate shape for
a Course Admin (`institution.roles.role_is_staff(COURSE_ADMIN)` is `True`) — keep that as the
primary case, but test 5 deliberately adds the owner and archived-group-teacher routes on top of it.

### Definition of done

- Full non-e2e suite green (`-n auto`), no new failures against the base. One caveat: the repo
  records `tests/test_html_element.py::test_lesson_html_render_query_count_invariant` as already
  failing **in isolation** on master. Since this change touches `build_lesson_context`, that test is
  the one an implementer will wrongly blame. `progress = state_row` is a bare assignment of an
  already-fetched row and issues **zero** additional queries, so a failure there must be reproduced
  on the base commit before it is attributed to this diff.
- `ruff check` and `ruff format --check` clean;
- `manage.py makemigrations --check` and `manage.py check` clean (both expected trivially — no model
  change);
- each new/inverted test falsification-proven (guard removed → RED → restored), except test 12,
  exempted in writing above;
- **existing e2e over the touched surface, run and green** — three suites, covering both surfaces
  this change feeds:
  - `tests/test_e2e_slideshow.py` (asserts `[data-unit-done]` gains `is-complete`) and
    `tests/test_e2e_unit_head_layout.py` (queries `.unit-done`) — the pill;
  - `tests/test_e2e_unit_nav.py` (seeds `UnitProgressFactory(..., completed=True)` and drives the
    unit-tree and footer counters) — the second-largest surface the change lights up.

  Run them **with `-m e2e`** — without that marker the entire e2e set is silently deselected and
  pytest exits 5, which reads like a pass. Expected result: green and unchanged; all three exercise
  the enrolled path, which this change does not alter.

No **new** e2e test is required: the change has no client-side component, and the full round trip is
observable at the view/template layer by tests 1, 2 and 7.

## Non-goals

- Auto-completing units for non-enrolled viewers on scroll (explicitly rejected above).
- Making completion resettable via "Start fresh", or turning the pill into a toggle — argued and
  scoped out under "The decision, and why", not merely declined here.
- Letting non-enrolled viewers submit quizzes or accumulate quiz analytics.
- Suppressing progress chrome (outline badges, tree counters, footer bar) for non-learners.
- Any change to how teacher-facing analytics scope their students.

## Accepted side effects

- A non-enrolled viewer's own outline ✓ badges, unit-tree counters and footer progress bar begin
  reflecting their manual marks. This is the intended payoff, not a regression.
- `courses/views_manage.py::course_delete`'s "N progress records" count may include such rows. That
  specific count is already inflated today, since a checklist tick creates a `UnitProgress` row for
  a non-enrolled viewer.
- **What is new is the *creation*, not the existence, of a `completed=True` row for a non-roster
  user.** State this precisely, because the two are easy to conflate:
  - *Not new:* such rows already exist. Every write that can set `completed=True` is enrolled-gated
    or student-scoped at the time of writing — `seen` and `complete` (both `is_enrolled`),
    `quiz_finish` (enrolled-only), `review.py::force_submit` (acts on the *student's* row, never the
    teacher's) — plus the Django admin, which is neither: `courses/admin.py` registers a plain
    add/change-enabled `UnitProgressAdmin`, and `UnitProgress.save()`'s own comment pins the
    completed⇒completed_at invariant "for EVERY write path (incl. admin)". So an admin can already
    create or flip a `completed=True` row for any user, enrolled or not. That is a *second* existing
    route to the shape, which strengthens the "not new" argument rather than weakening it (and it is
    the same admin named as the recovery route under "The decision, and why"). And nothing keeps a
    row and its enrollment together afterwards.
    `grouping/services.py::remove_students_from_group` drops the `Enrollment` and deliberately
    preserves the progress row (pinned by
    `tests/test_grouping_recompute.py::test_progress_preserved_across_drop_and_readd`), so a former
    enrollee is already a non-roster user holding `completed=True` rows. That is exactly the
    population Testing §6 seeds.
  - *New:* a currently-non-enrolled viewer can now **create** one, and the lesson page now
    **surfaces** whichever such rows exist.
  Either way the containment argument is unchanged and rests solely on the roster filter described
  in Data flow, never on any property of the row. Do not read "rows already exist" as "nothing
  downstream changed".

### Enrollment transition (the boundary this change creates)

`UnitProgress` has no link to `Enrollment`; the roster filter is applied at query time, per query.
So if a viewer who self-marked units while previewing is **later enrolled** — a Course Admin joining
a cohort to test the student flow, a teacher enrolled for a pilot, an SIS sync — those completions
become ordinary learner progress on the spot, with a `completed_at` predating the enrollment, and
are indistinguishable from work done as a student.

**This is accepted, not mitigated.** The reasoning:

- It is not new with this change. `element_state` practice-state rows written while previewing
  already survive into enrollment the same way, by the same mechanism, since PR #136.
- The completions are *true statements about that person*: they did click "Mark as done" on those
  units. Nothing is fabricated; only the framing shifts from "my own tracking" to "my progress in
  this course."
- The alternatives all cost more than the problem. Distinguishing preview-origin rows needs a new
  column and a migration; clearing them at enrollment silently destroys work the user did
  deliberately, which is the exact failure mode the practice-state slices exist to prevent.

Testing §8 pins this decision so a future change cannot silently reverse it.
