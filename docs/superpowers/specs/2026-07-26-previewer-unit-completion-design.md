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
`student=user` query). Hiding one control while leaving the other three permanently pinned at zero
is a half-fix. Making the click work lights all four up coherently.

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
   analysis below), so a stray click misinforms nobody but the person who made it.

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

Two behavioural edits in `courses/views.py`, three comment corrections in the same file, one
deliberate non-edit, and one existing test inverted. No migration, no model change, no new URL, no
template change, no JS change, no new translatable strings.

### 1. The write — `courses/views.py::complete`

Drop the `is_enrolled` branch so `can_access_course` (already checked immediately above) is the sole
guard on the write:

```python
progress, _ = UnitProgress.objects.get_or_create(student=request.user, unit=node)
if not progress.completed:
    progress.completed = True
    progress.save()  # completed_at stamped in save()
```

This is the same reversal PR #136 applied to `markdone_save`, for the same stated reason: the row is
the viewer's own record, not course analytics. `get_or_create` here is correct and intended — a POST
is an explicit act, so creating the row on it does not violate the "no spurious rows on a GET" rule.

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

**`build_lesson_context` has two callers, not one.** Its own docstring records that it is shared by
`lesson_unit` (GET) and `check_answer` (the POST re-render) "so the two cannot drift." This edit
therefore also changes what a non-enrolled viewer sees after clicking **Check** on a question: the
pill must stay "✓ Completed" across that re-render rather than reverting to the button. That is the
correct outcome and it comes for free from editing the shared function — but it is a second render
surface, so it gets its own test (Testing §7) rather than being assumed from the shared-function
argument.

### 2b. Three comments in `courses/views.py` that this change makes wrong

Comments in this codebase carry design contracts, so leaving them stale would ship a file arguing
against its own behaviour. All three are corrections of fact, not new prose:

- **≈:784-788** (in `element_state_save`) states that persisting practice state for any accessing
  viewer "deliberately diverges from seen/quiz (which ignore previewers so authors don't pollute
  their own progress/analytics)". After this change `complete` joins the diverging side, so the
  enumeration must narrow to `seen`/quiz-submission only, and the parenthetical rationale must stop
  implying that *all* progress writes exclude previewers.
- **≈:396-398** (the `elif user.is_authenticated` branch in `build_lesson_context`) says the row is
  read "for their practice state". It now also feeds the completion pill; the comment must say so,
  and must keep stating why the read is `.filter().first()` rather than `get_or_create`.
- **≈:273-275** (`build_lesson_context`'s docstring) says it "Performs the same
  `UnitProgress.get_or_create` + seen-count as a normal view" — true only on the enrolled path. It
  must name the non-enrolled path's read-only row lookup.

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

**Unchanged in both:**

```
scroll → POST seen → is_enrolled ✗ → synthetic {"completed": false} → pill never flips
```

**Downstream, viewer-scoped (starts working, by design):** `courses/rollups.py`'s per-viewer
completed-unit-id query (`student=user, unit__course=course, completed=True`) feeds the outline ✓
badges, the unit-tree required/additional counters, and the footer course-progress bar. These begin
reflecting the viewer's own manual marks.

**Downstream, roster-scoped (contained, with a stated boundary):** the teacher-facing
frontier/matrix query in `courses/rollups.py` filters `student__in=students` — an enrolled roster —
so a non-enrolled viewer's row cannot appear in teacher analytics or the gradebook **while that
viewer is off the roster**. The containment is the roster filter, not any property of the row
itself; see "Enrollment transition" below for what happens when that premise stops holding.

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
  idempotent; `completed_at` is stamped once, in `UnitProgress.save()`.
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
4. **No spurious row on GET.** A non-enrolled viewer merely GETting the lesson creates no
   `UnitProgress` row.
   *Falsify:* change the non-enrolled read from `.filter().first()` to `get_or_create` → RED.
5. **Access still enforced, across all three non-enrolled routes.** `can_access_course` is now the
   sole guard on the write, and it admits three distinct routes — `is_staff`, course owner, and
   teacher of a **non-archived** group. The repo's recorded lesson is that widening a gate requires
   driving each newly-reachable role end to end, so cover:
   - **(a)** a non-staff **course owner** POSTs `complete` → row written, `completed=True`;
   - **(b)** a user whose only link is an **archived** group they teach → 403 and **no** row (this
     is the new boundary the change exposes: `accessible_courses` pins `groups__archived=False`);
   - **(c)** a logged-in user with no relationship to the course → 403 and no row.
   *Falsify:* drop the `can_access_course` check in `complete` → (b) and (c) go RED.
6. **Pre-existing `completed=True` row.** Seed a `completed=True` row for a user, ensure they are
   **not** enrolled but can access → a plain GET of the lesson (no POST at all) shows the
   "Completed" pill. Pins the Data-flow "Pre-existing rows" paragraph as intended behaviour rather
   than an accident.
   *Falsify:* revert `progress = state_row` → RED.
7. **The second render surface: `check_answer`.** A non-enrolled viewer with a `completed=True` row
   POSTs a Check on a question in that unit → the re-rendered response still shows the "Completed"
   pill. Guards the shared-context path called out in Architecture §2.
   *Falsify:* revert `progress = state_row` → RED (both render paths share the one assignment,
   which is precisely why this test must name the POST path explicitly rather than trusting test 2
   to cover it).
8. **Enrollment transition (pins an accepted decision, not a guard).** A non-enrolled viewer marks a
   unit done, is **then** enrolled → the row survives with `completed=True` and now counts as
   learner progress in the roster-scoped query. This test documents the decision recorded under
   "Enrollment transition"; label it as such in a comment so nobody mistakes it for a safety guard.
   *Falsify:* add any enrollment-time clearing or preview-origin filtering of completions → RED.
9. **Downstream chrome actually lights up** — the spec's whole rationale for fixing rather than
   hiding. A non-enrolled `can_access` viewer POSTs `complete`, then GETs the course outline → the
   ✓ badge renders for that unit, and the unit footer's `course_progress.done` is non-zero.
   *Falsify:* break `build_outline`'s authenticated branch (`rollups.py`, the
   `student=user, ..., completed=True` query) → RED. Without this test the justification for the
   whole design could regress silently while every other test stayed green.
10. **Enrolled path unregressed.** The existing enrolled complete/auto-complete tests
    (`test_seen_merges_and_autocompletes`, `test_zero_element_unit_completes_only_via_fallback`)
    stay green.
    *Falsify:* exempt — these are pre-existing tests being protected from regression, not new
    guards. Per the falsifiability doctrine, a test whose behaviour the diff does not change has no
    honest RED recipe, and claiming one would be theatre.

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
- each new/inverted test falsification-proven (guard removed → RED → restored), except test 10,
  exempted in writing above;
- **existing e2e over the touched surface, run and green:** `tests/test_e2e_slideshow.py` (asserts
  `[data-unit-done]` gains `is-complete`) and `tests/test_e2e_unit_head_layout.py` (queries
  `.unit-done`) both render the pill this change feeds. Run them **with `-m e2e`** — without that
  marker the entire e2e set is silently deselected and pytest exits 5, which reads like a pass.
  Expected result: green and unchanged; they exercise the enrolled path, which this change does not
  alter.

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
- **A `completed=True` row for a non-roster user is genuinely new, and that matters.** Row
  *existence* for a previewer is old news, but every existing write that can set `completed=True` is
  enrolled-gated or student-scoped — `seen` and `complete` (both `is_enrolled`), `quiz_finish`
  (`courses/views.py`, enrolled-only), and `review.py::force_submit` (acts on the *student's* row,
  never the teacher's). So today a non-enrolled viewer's rows are always `completed=False`, and
  `completed=True` is exactly the predicate the outline, tree, footer, frontier and gradebook
  queries filter on. The containment is therefore entirely the roster filter described in Data flow
  — not the shape of the row. Do not read "rows already exist" as "nothing downstream changed".

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
