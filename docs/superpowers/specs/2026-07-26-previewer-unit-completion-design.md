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
the first click is plausibly exploratory. Four things make that acceptable where the scroll path is
not:

1. **Blast radius.** A misclick marks exactly the one unit the viewer is looking at, and the pill
   changes visibly and immediately, so the consequence is legible at the moment it is incurred.
   Scroll-tracking marks every unit visited, silently, with no per-unit moment of consent.
2. **Parity, not novelty.** This is precisely the exposure every enrolled student has had since the
   feature shipped: one click, permanent, no undo. The change does not make the button more
   dangerous than it already is for the population it was designed for; it stops making it *lie* to
   everyone else.
3. **Consequence.** The mark lands only in the viewer's *own* progress chrome (see the roster-scoped
   analysis below), so a stray click misinforms nobody but the person who made it — with one
   aggregate exception, `course_delete`'s "N progress records" count, which a checklist tick already
   inflates today (see Accepted side effects). Testing §10 pins the containment rather than leaving
   it as an argument.
4. **A recovery route exists — but a narrow one, and the obvious reading of it is wrong.**
   `courses/admin.py` registers an editable `UnitProgressAdmin` with `completed` in `list_display`,
   which invites the conclusion that the dominant `is_staff` previewer can undo their own mis-click.
   **They cannot.** `is_staff` grants admin-site *login* only; the changelist additionally needs
   `courses.view_unitprogress` / `change_unitprogress`, and **no role group grants either** —
   `institution/roles.py` seeds `PLATFORM_ADMIN_PERMS` (accounts / institution / `COURSE_PERMS` /
   `SUBJECT_PERMS`) and the `GROUPING_*` lists, none of which contains a `unitprogress` codename, and
   `UnitProgressAdmin` defines no `has_*_permission` overrides. So the route is **superuser-only**: a
   Course Admin reaching `/admin/` cannot see the model. Weigh it accordingly — recovery exists, but
   it requires escalating to whoever holds superuser, so this bullet supports the decision far more
   weakly than bullets 1–3 and must not be read as "this population can fix it themselves."

The file being edited argues the opposite doctrine for a neighbouring hazard, and that deserves a
direct answer rather than silence: `progress_reset`'s docstring says reset is "the student's
protection against automatic persistence — shipping it as a one-click no-undo form for no-JS
students would make the safety valve the hazard." That reasoning is about **automatic** persistence
and about the *reset* control specifically; the mark-done button is neither automatic nor a safety
valve. Bullet 2 is the answer: this spec adds no new hazard shape, it extends an existing,
deliberate one to a population the same product already exposes to it.

**The cheap end of the mitigation space was considered too, and rejected on the same ground.** A
warning affordance costing nothing downstream — a `title`/`aria-description` on the button saying the
mark is permanent, or a confirm interstitial — would address the gap bullet 1 leaves open (the
click's *effect* is legible at the moment it lands; its *permanence* is not). It is rejected for
parity: enrolled students get no such warning today, and adding one only for previewers would tell
the population at less risk what the population at more risk is not told. Adding it for everyone is
a change to the student experience and belongs with the toggle/reset question below. This is why the
spec commits to **no template markup change** — a conclusion, not a premise. (§2b does correct one
`{% comment %}` in that template; a comment body changes nothing rendered and is not an affordance.)

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

Two behavioural edits in `courses/views.py`; two new comments there; five comment corrections — four
in `courses/views.py` (one of them in `seen`, a function this diff otherwise leaves behaviourally
untouched) and one in `templates/courses/_lesson_article.html`; one existing test inverted, one
existing test extended (Testing §3), and roughly a dozen new tests in
`tests/test_courses_progress.py` (see Testing — the test work is the bulk of this change, not the
two-line edit). The inverted one is Testing §1(a). No migration, no model change, no new URL, no JS change, no new
translatable strings, and **no template markup change** — the single template edit is a
`{% comment %}` body, which is why it does not reopen the warning-affordance question.

### 1. The write — `courses/views.py::complete`

Drop the `is_enrolled` branch so `can_access_course` (already checked immediately above) is the sole
guard on the write, and take the same lock `save_element_state` (the very next function, `≈:688`)
takes:

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
same page as the checklist. The concurrent writers a previewer can actually reach are
`check_answer` and `element_state_save` — both via `save_element_state` — plus `progress_reset`,
which is harmless and needs no hardening: it is a single-statement queryset `UPDATE`
(`rows.update(element_state={})`) with no read-modify-write, so it cannot lose an update whatever
the lock ordering, and it never touches `completed`. `courses/views.py::save_element_state` already solves exactly this with
`transaction.atomic()` + `select_for_update()`, so this is the file's own house pattern rather than
a new mechanism: same columns written, same semantics. `update_fields` was the other candidate and
is **rejected**: it would change which columns the enrolled path writes, a genuinely different
change with its own regression surface.

**Be precise about the mechanism — the obvious explanation is wrong.** It is tempting to say "a row
lock only excludes writers that also take it." That is **false** on PostgreSQL: a plain `UPDATE`
acquires a row-level exclusive lock and *does* block on an existing `SELECT … FOR UPDATE`, whether
or not the updater asked for one. The real rule is about **ordering**: `FOR UPDATE` serialises
concurrent writers, but it cannot protect a writer that performed its **read** before acquiring (or
without acquiring) the lock — that writer carries a stale in-memory row across the block and writes
it back afterwards. A lost update, not a lock-exclusion failure.

So: `save_element_state` is safe because it locks **before** it reads. §1 above does the same. And
`seen` (≈:662-667) is *not* safe, because it does `get_or_create` → mutate → bare `progress.save()`
with no atomic block and no lock at all: its read is unlocked, so a flush that began before a
`complete` commit can still write `completed=False` and a stale `element_state` back over it. That
is pre-existing, enrolled-only (a previewer never reaches `seen`'s write), and sits on the
highest-frequency writer in the file — a 500 ms debounce during scroll — so hardening it is **out of
scope**: it would change the hot path. Anyone who does harden it later must move the lock **ahead of
the read**, not merely add one. This is the mechanism the §2b comment must encode; stating the
lock-exclusion version there would ship a confident falsehood in the one place nothing tests.

**Cost:** the new shape is `get_or_create` (SELECT, sometimes INSERT) plus a second
`SELECT … FOR UPDATE`, inside an atomic block, where the old shape was one SELECT and — when the
unit was already complete — nothing further. **In production** that is +1 query *within the write block* — before counting the
`is_enrolled` EXISTS this diff deletes — and one `BEGIN`/`COMMIT` per `complete` POST
(`ATOMIC_REQUESTS` is not set anywhere in `config/`, so this block is the outermost transaction).

**Count it against what the diff actually removes.** `is_enrolled` is
`Enrollment.objects.filter(...).exists()` — a query — and this change **deletes that call** from
`complete`. So:

- **Enrolled path: net zero additional queries.** One `EXISTS` (`is_enrolled`) is traded for one
  `SELECT … FOR UPDATE`. The real cost is the `BEGIN`/`COMMIT`, not a query.
- **Previewer path: baseline was one query, not none.** The `is_enrolled` `EXISTS` ran *before* the
  branch was skipped. The new shape is `BEGIN`/`COMMIT` + two SELECTs + the writes — and on a
  **first** POST that is an INSERT *and* an UPDATE, not "one or the other": `get_or_create` carries
  no `defaults`, so it inserts `completed=False`, the re-fetch runs, and `save()` then updates. A
  repeat POST is two SELECTs and no write (Testing §11). Adding `defaults={"completed": True}` is
  **not** the intended optimisation — it would collapse the re-fetch §2b exists to protect. No `assertNumQueries` /
`CaptureQueriesContext` test currently covers `complete` (verified), so nothing breaks. **Under
pytest** it looks different: `django_db` already holds a transaction, so the same block emits
`SAVEPOINT`/`RELEASE` — a harness artefact, not a production cost. Testing §11 wraps this endpoint in
`CaptureQueriesContext`, so its assertion must target `UPDATE` on `courses_unitprogress`
specifically, never "no writes": the SELECTs and that savepoint traffic are expected and correct.

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
`seen_count` remains 0 for them. That is today's behaviour and is not user-visible **anywhere** —
state the closed form, not the weaker one, or a reader goes hunting for the surfaces it might leak
on. `build_lesson_context` is the only producer of `seen_count`/`element_count` on this context
(`views.py:441-442`), and **no template or view in the repo reads either**; the only other
`element_count` in the codebase belongs to the unrelated transfer-preview context
(`transfer/importer.py:444` → `manage/import_preview.html`). The asymmetry is therefore deliberate
rather than discovered, and closed rather than merely bounded to one page.

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

`notes/views.py:194` is **exempt from its own test in writing**: it calls
`full_lesson_render_context(unit, request.user, notes_show=True)` — the same call test 7 drives, the
extra kwarg touching only the notes panel, leaving the progress path byte-identical — with no
additional progress-related logic between the call and the template. A third near-duplicate test would pin the
caller list rather than any behaviour.

### 2b. Five comment corrections (four in `courses/views.py`, one in the lesson template), plus two new comments

The new ones first. The atomic block's **re-fetch under lock** is the only piece of *code* in this
diff that no test can protect — collapsing it back to `progress, _ = get_or_create(...)` is
byte-identical in every sequential test — which is what makes its comment load-bearing rather than
explanatory. (All seven comment edits are equally unguarded by automation; that is why the DoD lists
them.)

- **New, on §1's atomic block.** The snippet deliberately throws away `get_or_create`'s return value
  and re-reads the row under `select_for_update()`. That reads as redundant, and collapsing it back
  to `progress, _ = UnitProgress.objects.get_or_create(...)` is byte-identical in every sequential
  test — the spec argues elsewhere that no test can sample the concurrency window this exists for.
  So the mitigation would otherwise ship with zero protection: no test, no comment. This is the
  file's stated doctrine — comments carry design contracts — applied to the one line whose deletion
  nothing else would catch.
  **Required content, stated once here so §1, this bullet and the DoD cannot diverge.** The comment
  must say the row is re-fetched *under the lock* because `FOR UPDATE` serialises concurrent writers
  but cannot protect a writer whose **read** preceded the lock — which is why `save_element_state`
  locks before reading and why `seen`, which does not, can still lose an update. It must **not** say
  a lock "only excludes writers that also take it": that is false on PostgreSQL (a plain `UPDATE`
  blocks on an existing `FOR UPDATE`), and shipping it would plant a confident falsehood in the one
  place nothing tests. Register: `save_element_state`'s own docstring.

- **New, at `complete`'s access check.** One line recording that `can_access_course` is deliberately
  the sole guard on the write, because the row is the viewer's own record — mirroring the PR #136
  reversal. Test 1 protects the behaviour, so this is not load-bearing the way the atomic-block
  comment is; it earns its place because `element_state_save`'s neighbouring comment still frames
  previewer-exclusion as the house rule, and the gate-lift is the edit most likely to be
  "restored" by a later reader tidying up.

And the five corrections:

Comments in this codebase carry design contracts, so leaving them stale would ship a file arguing
against its own behaviour. All five below are corrections of fact:

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
- **`templates/courses/_lesson_article.html:8-11`** — the one correction outside `views.py`, and the
  same doctrine applies to it. It opens "Completion is auto-tracked: progress.js auto-completes the
  unit once every element has been seen … This pill is the no-JS fallback + manual override". For
  the population this change admits, completion is **never** auto-tracked (`seen` stays
  enrolled-only), so the pill is not a fallback — it is their only route. Say so. This is a
  `{% comment %}` edit only: no markup, no attributes, no strings, so it does not reopen the
  warning-affordance question argued under "The decision, and why", and the block must stay a
  `{% comment %}` (`{# #}` cannot span lines in Django).

### 3. Behaviourally unchanged (comment corrected) — `courses/views.py::seen`

`seen` *is* touched by this diff — its comment at `:652` changes, per §2b. Nothing else about it
does, and the heading says "behaviourally unchanged" rather than "unchanged" so an audit of "which
functions does this diff touch" gets the right answer.

`seen` keeps its `is_enrolled` gate and its synthetic response. This is a specified non-goal, not an
oversight; see "The decision, and why" above. The existing test asserting it must stay green.

**And its synthetic response keeps `"completed": false` regardless of stored state.** This needs
saying, because the change creates the contradiction: a previewer can now hold `completed=True`
while `views.py:653-655` still reports `{"seen_element_ids": [], "completed": false,
"completed_at": null}` to them. That is **intended**. `seen`'s contract is narrow — *this endpoint
reports scroll-tracking, and scroll-tracking is not recorded for previewers* — not "here is your
progress row". Do not "fix" the response to echo the stored row: that would break the previewer
`seen` test — `test_previewer_seen_no_write_synthetic` today, renamed to
`test_previewer_seen_no_write_and_ignores_stored_completion` by Testing §3, so use the post-rename
name anywhere this sentence is echoed (notably the §2b `seen` comment) — and quietly turn a
write-free endpoint into a state reporter.

It is also not user-visible, for a reason worth recording rather than rediscovering: `unitMarkDone`
(`courses/static/courses/js/unit_done.js`) is **add-only** — it early-returns when `is-complete` is
already present and never removes the class — so neither `progress.js` nor `slideshow.js` can
un-flip a server-rendered "✓ Completed" pill on receiving `completed: false`.

**That property is recorded here, not guarded — deliberately, and the distinction matters.** Testing
§3 is a Django-test-client test of `seen`'s JSON; it pins the *server* contract and cannot observe
`unit_done.js` at all, and none of the three e2e suites in the DoD drives a previewer (all are
enrolled-path). So the only thing standing between a previewer and a pill that reverts to "Mark as
done" mid-session, when progress.js's 500 ms flush returns `completed: false`, is this JS invariant.
It is accepted unguarded because of its *shape*: the risk would require some code path to **remove**
`is-complete`, and no such path exists — `markDone` is called only when the server reports
`completed`, and its body exclusively adds. A test would have to assert the absence of code that was
never written. If a future change ever makes the pill two-directional, that is the moment this needs
a previewer-scoped e2e (load a marked-done lesson as a previewer, let the flush return
`completed:false`, assert `[data-unit-done]` keeps `is-complete`) — and this paragraph is the note
telling that author so.

### 4. Also unchanged

`progress_reset` (completion stays non-resettable), the quiz endpoints (`quiz_answer` /
`quiz_finish` still `raise PermissionDenied` for non-enrolled viewers — a graded submission genuinely
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
frontier/matrix builder takes a `students` **argument** and builds one row per member of it; the
`student__in=students` filter inside it merely narrows a lookup dict and is not itself the
containment. **The containment is the roster argument** — `students` comes from
`grouping/scoping.py::students_in_scope`, an **Enrollment- or GroupMembership-derived**
roster (Enrollment on the PA/owner fallback; GroupMembership for the group-teacher fallback and both
explicit `group:<pk>` / `collection:<pk>` scopes). So a non-enrolled viewer's row cannot appear in
teacher analytics or the gradebook **while that viewer is off the roster**. That the two derivations
agree rests on `add_students_to_group` / `remove_students_from_group` keeping GroupMembership ⊆
Enrollment — an invariant maintained by those services, not enforced by the query. The containment
is the roster filter, never any property of the row itself; see "Enrollment transition" below for
what happens when that premise stops holding.

**A second teacher-facing reader is contained by a different mechanism — say so, don't generalise.**
`courses/views_analytics.py::analytics_student` → `rollups.py::build_student_breakdown(course,
student)` → `build_outline(course, student)` runs the *same* `student=user, completed=True` query
that gives the previewer their own payoff, only with another user's identity — and it carries **no**
`student__in` roster filter at all. Its containment is a view-level resolution:
`scoping.reviewable_students(request.user, course).filter(pk=student_pk).first()`, which 404s an
off-roster pk before the breakdown is ever built. So "the containment is the roster filter" is true
of the matrix (`views_analytics.py:53`) and the gradebook export (`views_export.py:44`), both of
which go through `students_in_scope`, but it is **not** the mechanism protecting the per-student
drill-down. Testing §10 drives both mechanisms rather than assuming one covers the other.

**And the write is inert beyond that row.** Worth stating because the sibling completion write is
not: `quiz_finish` calls `notify_needs_review` **and** `emit_result_finalized` (the SIS webhook)
right after setting `completed`. `complete` emits neither, and `UnitProgress` carries no `post_save`
receiver — `courses/signals.py` registers only a `post_delete` on `MediaAsset`. So a previewer's
mark sends no notification and fires no webhook.

**Unguarded, and exempt in writing** — flagged because bullet 3 of "The decision, and why" leans on
it and Testing §10 holds containment claims to "pinned, not argued". The exemption is the same shape
as §3's `unitMarkDone` invariant: the claim is about code that **does not exist** (no `post_save`
receiver, no `notify_*` / `emit_*` call in `complete`), so a test would assert the absence of code
never written, and its falsification recipe would have to *invent* the receiver first — a recipe with
no insertion point, which Testing §8 already rejects as "a wish". The enumeration above is the guard:
if a later change adds a notification or webhook to `complete`, bullet 3 stops holding and needs
re-argument, not a green test.

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
- **The gap between `get_or_create` and `select_for_update().get()`** — a `DoesNotExist` there is
  possible in principle and is correctly left to 500. No *application* code path deletes an
  individual `UnitProgress` row: they disappear only by cascade from `Course`/`ContentNode`/`User`
  deletion. (The superuser admin of "The decision, and why" bullet 4 can delete one, but that is a
  human action, not a concurrent request shape.) So
  a miss would mean the unit was deleted mid-request, which is not a state worth a fallback.
  `save_element_state` has the identical shape and the same reasoning applies to it.
- **Method** — `complete` remains `@require_POST`; a GET cannot complete a unit.

## Testing

Every test below must be **falsifiable**: remove the guard it exists for, confirm RED, restore. The
repo's recorded scar is that a passing test proves nothing.

### Inverted (not extended)

`tests/test_courses_progress.py::test_previewer_complete_redirects_without_write` asserts today's
no-op (`assert not UnitProgress.objects.filter(student=staff, unit=unit).exists()`). It is a
deliberate reversal of a shipped guarantee, exactly as PR #136 reversed markdone's, and becomes
`test_previewer_complete_persists_and_redirects` — named for **both** halves, since §1(a) keeps and
strengthens the redirect assertion; a persistence-only name is an invitation for a later reader to
delete "the assertion unrelated to the name", which is exactly the discipline §3's rename applies.
It must be rewritten, never left alongside a contradicting new test.

### New / adjusted

1. **Write.** Two separate test functions — 1(a) is the rewrite, 1(b) is genuinely new; they cannot
   be one function, since 1(a) starts from no row and 1(b) from a seeded one.
   - **1(a) — `test_previewer_complete_persists_and_redirects`.** *This is the inverted test named above, rewritten
     in place, not a second test beside it.* A non-enrolled `can_access` viewer POSTs
     `courses:complete` → a `UnitProgress` row exists for them with `completed=True` and a stamped
     `completed_at`. **Keep the existing test's redirect assertion** rather than dropping it with the
     old name — the inversion replaces the *write* assertion; the response-shape guarantee is
     orthogonal and still true. Tighten it while you are there: `complete` ends in `redirect(...)`,
     so assert `status_code == 302` **and** that `Location` is `reverse("courses:lesson_unit", …)`
     for the same slug/node. The old `in (302, 200)` hedge made sense when nothing was written; now
     a 200 would mean something went wrong.
     *Falsify:* restore the `is_enrolled` branch in `complete` → RED.
   - **1(b) — the write over a checklist row, the actual production sequence.** A new test in the
     same file, separately named. Every other write test starts from no row (1a, 5, 9, 10) or an
     already-`completed=True` one (11); but the commonest real order is: previewer ticks a mark-done
     checklist (creating `completed=False` + `element_state`), *then* clicks Mark as done. Drive it:
     seed **`UnitProgressFactory(student=viewer, unit=unit, completed=False, element_state={…})`**
     — both kwargs mandatory, see 6(b) — POST `complete`, assert `completed is True`, `completed_at`
     stamped, **and `element_state` byte-identical after `refresh_from_db()`**.
     *Falsify:* the `completed` half rides 1(a)'s recipe (restore the `is_enrolled` branch → RED).
     The `element_state` half is **exempt in writing**, on the §11 reasoning: sequentially,
     `get_or_create` re-reads the row, so the blob survives even a lock-less implementation and no
     mutation makes it RED. It is asserted anyway because it is the outcome §1's atomic re-fetch
     exists to protect, and a cheap regression net beats no net — but it is not claimed as a guard.
   - **1(c) — the enrolled twin of 1(b).** The rewritten `complete` runs for enrolled students too,
     and no existing test covers it against a *pre-existing* row: `test_seen_merges_and_autocompletes`
     never reaches `complete` at all (it POSTs `seen`), and `test_zero_element_unit_completes_only_via_fallback`
     POSTs once on a zero-element unit with no row. So the new re-fetch never runs on the enrolled
     path over a row that already exists — the shape this change most plausibly regresses. Same body
     as 1(b) with an enrolled student, **plus the column 1(b) cannot carry**: seed
     `seen_element_ids=[<a real element pk>]` as well and assert it byte-identical after
     `refresh_from_db()`. This is not symmetry for its own sake — §1's whole lost-update analysis is
     about `progress.save()` writing *every* column from the in-memory instance, and the unhardened
     writer it names is `seen`, whose field is `seen_element_ids`, not `element_state`. A previewer
     never reaches `seen`'s write, so only the enrolled row realistically carries a non-empty
     seen-set; leaving it unasserted would aim the regression net at every column except the one the
     argument centres on. (`seen_element_ids` is a passthrough model kwarg on `UnitProgressFactory`,
     which declares only `student`/`unit` — the same shape as `GroupFactory(archived=…)` in test 5.)
     *Falsify:* exempt for the same reason as 1(b)'s `element_state` half — sequentially,
     `get_or_create` re-reads the row, so both blobs survive even a lock-less implementation. This is
     regression cover, not a guard, and the `seen_element_ids` assertion is claimed as neither more
     nor less.
2. **Read (the one that catches a write-only fix).** A **standalone** test — it issues its own
   `complete` POST and then a separate GET; it does **not** continue test 1 and must not be merged
   into it via `follow=True`, or "test 1 stays green" in the recipe below has no meaning. After its
   POST, the same viewer GETs the lesson → the response shows the "Completed" pill and **not** the "Mark as done" submit button.
   *Falsify:* revert `progress = state_row` → RED while test 1 stays green.
   Assert on markers that cannot false-pass: `unit-done__pill--btn` (the button class) absent, and
   `is-complete` present. Two facts make `is-complete` safe as a body substring **today**:
   `_lesson_article.html:12` is its only template occurrence, and its other two occurrences
   (`courses.css`, `unit_done.js`) are external assets that never enter the response body. Neither
   is guaranteed to hold forever, so scope the assertion to the `[data-unit-done]` element rather
   than searching the whole body. **Parsing is the technique that satisfies both halves; the regex
   shortcut satisfies only one.** `unit-done[^"]*is-complete` expresses the *class-list-present* half
   and nothing else: an absence assertion (`unit-done__pill--btn` **not** present) and 6(b)'s
   descendant assertion (a `button.unit-done__pill--btn` **exists** inside the subtree) cannot be
   written as a body-wide regex without reintroducing exactly the whole-body substring check this
   paragraph forbids. So parse the `[data-unit-done]` subtree out and assert within it; reach for the
   regex only as the class-list half of that, never as the whole assertion.
3. **Asymmetry guard (the deliberate non-edit).** A non-enrolled `can_access` viewer POSTs every
   element id to `courses:seen` → still no completion and no row. The existing
   `test_previewer_seen_no_write_synthetic` covers this; keep it adjacent to test 1 so the
   deliberate split between the two paths is legible on one screen. **Rename it** to something that
   covers what it now asserts — e.g. `test_previewer_seen_no_write_and_ignores_stored_completion` —
   the same discipline the §1(a) inversion follows; a name that says only "no write synthetic" will
   read as unrelated to the stored-row half. **Extend it to pin §3's
   *server* contract** — a previewer holding a `completed=True` row still gets
   `{"completed": false}`. (§3's client-side half — `unitMarkDone`'s add-only shape — is recorded
   there as accepted-unguarded; a Django-test-client test cannot observe it and this one does not
   pretend to.) But
   note this is a fixture change, not a bare extra assert: the existing test's viewer deliberately
   has **no** row and asserts so. Sequence it, don't overwrite it: (1) POST `seen` and keep the
   existing no-row + synthetic-response assertions; (2) *then* seed the `completed=True` row for
   **that same viewer** — a second viewer would need its own `make_login` + `is_staff` setup plus a
   mid-test re-login and buys nothing. **Pass `student=viewer` AND `unit=unit` explicitly**:
   `UnitProgressFactory` declares both as `SubFactory`s, and this is the one seed in the roster whose
   mis-scoping fails *silently*. Every step-(3) assertion is negative, so a row minted against an
   unrelated node leaves them all green — and so does the extension's own falsification recipe, which
   finds no row for `(viewer, node)` and returns the synthetic dict anyway. The extension would then
   be listed in the DoD as falsification-proven when only its pre-existing half is. (Tests 6(a) and 7
   assert positively, so the same mistake fails loudly there.) Then (3) POST `seen` again and assert
   the response is still
   `{"seen_element_ids": [], "completed": false, "completed_at": null}` **and** that the seeded row
   is untouched — name the fields rather than comparing whole objects (`updated_at` is `auto_now`):
   after `refresh_from_db()`, `seen_element_ids == []` (the POSTed ids were not merged),
   `completed is True`, and `completed_at` equal to its pre-POST value. Without this the decision that the synthetic response ignores stored state is
   incidental rather than recorded, and the next reader will "fix" it.
   **Two recipes, because one does not cover both halves.**
   *Falsify (step 1, pre-existing):* temporarily drop the `is_enrolled` gate in `seen` → RED. This
   guard is *outside* the diff — the recipe removes code the change does not touch, which is exactly
   the point: the test's job is to catch a future implementer "finishing the job" by lifting both
   gates. But note it reddens the **pre-existing** assertions and would fire whether or not steps
   (2)–(3) were ever written.
   *Falsify (steps 2–3, the extension's own):* make the synthetic response echo the stored row —
   → step (3) goes RED while step (1) stays green. Without this second recipe the extension is listed
   in the DoD as falsification-proven while only its old half is. **The mutation must be null-safe**,
   or it reddens step 1 too and the recipe loses the very property it was added for: at step 1 the
   previewer deliberately has **no** row, and `_progress_json` dereferences
   `progress.seen_element_ids` unconditionally, so a bare
   `_progress_json(UnitProgress.objects.filter(...).first())` raises `AttributeError` on `None` and
   the test client re-raises it. Write it as
   `row = UnitProgress.objects.filter(student=request.user, unit=node).first()` then
   `return JsonResponse(_progress_json(row) if row else {"seen_element_ids": [], "completed": False, "completed_at": None})`.
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
   successful write, not merely its negative twin. **The four labels are paired positive/negative,
   not sequential** — they are presented (a), (d), (b), (c) so each positive route sits next to its
   twin; the DoD's "5(a)–(d)" means all four, in any order:
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
   **Fixture wiring, and two vacuity traps.** Wire each route explicitly:
   - **(a)** the logged-in user must be the course's owner — `CourseFactory(owner=user)`, and the
     kwarg is **mandatory**: `CourseFactory` declares no `owner` at all and `Course.owner` is
     `null=True`, so a bare `CourseFactory()` yields `owner=None` and route (a) simply does not
     exist. (Only `make_course_with_unit` mints an owner of its own.) The non-staff pin below is
     about the *logged-in* user, not about any factory-created one.
   - **(b)** and **(d)**: `grouping.Group` has a `course` FK, a `teachers` M2M and an `archived`
     boolean. Build **`GroupFactory(course=course, archived=True)`** for (b) and
     **`GroupFactory(course=course)`** for (d) (the model default is `archived=False`), then
     `group.teachers.add(user)`. `archived` is a passthrough model kwarg, **not** a declared factory
     field — writing `group.archived = True` without a `.save()` silently turns route (b) into
     route (d), and the test then passes while proving the opposite of what it claims.
   Then the two traps:
   - **Trap 1 — `is_staff` short-circuit.** `accessible_courses` returns `Course.objects.all()` at
     `if user.is_staff:` *before* evaluating either `Q(owner=user)` or the group clause. So **(a),
     (b) and (d) must each assert their user is non-staff** — not just (b) and (d). A staff owner in
     (a) passes via the wrong route and proves nothing about the owner clause. Routes **(b)** and
     **(c)** both assert a **403**, so a stray staff flag reddens them loudly rather than passing
     silently — (c) therefore needs no pin at all, and (b) keeps one for a different reason: its
     whole claim is about the `groups__archived=False` predicate, and that is only legible if the
     fixture shows the user reaching the group clause in the first place.
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
     a plain GET of the lesson (no POST at all) shows the completed pill. Pins the Data-flow
     "Pre-existing rows" paragraph as intended behaviour rather than an accident. **Use test 2's
     marker discipline, not the English phrasing**: scope to `[data-unit-done]` and assert
     `is-complete` **present** / `unit-done__pill--btn` **absent**. A bare
     `assert "Completed" in body` is **vacuous** — `_lesson_article.html:13` emits
     `data-done-label="{% trans 'Completed' %}"` on that div *unconditionally*, outside the
     `{% if progress.completed %}` branch, so the word is in every lesson response and the
     falsification below would stay GREEN.
     *Falsify:* revert `progress = state_row` → RED.
   - **(b) `completed=False` — the row shape nothing else covers.** Seed
     **`UnitProgressFactory(student=viewer, unit=unit, completed=False, element_state={…})`** — and
     **both kwargs are mandatory**: `UnitProgressFactory` declares `student` and `unit` as
     `SubFactory`s, so a call that omits them mints a row for an unrelated user on an unrelated node.
     The viewer then has no row at all, `progress` is `None`, the button renders, the assertion
     passes — and *both* falsification recipes below stay green too. A mis-scoped seed makes this
     test assert nothing about the shape it exists for. (Same trap as `CourseFactory(owner=…)` in
     test 5 and `GroupFactory(archived=…)`; §3's and §7's seeds need the same kwargs — §3's is the one
     where getting it wrong fails silently.)
     Then → within the `[data-unit-done]`
     subtree, that div's own class list lacks `is-complete` (`_lesson_article.html:12`) **and** a
     descendant `button.unit-done__pill--btn` exists (`:20`) — two different elements, not two
     attributes of one; test 2's assertion needs the same phrasing. This is
     not hypothetical: since PR #136 a previewer who ticks a checklist gets exactly this row, making
     it the *most common* previewer row in production once this ships, and no other test covers it —
     test 4 asserts only that no row is created, tests 2 and 6(a) only the `True` direction.
     **Be honest about what this guards**, because the obvious argument is wrong: the template
     branches on `{% if progress.completed %}` (`_lesson_article.html:12` and `:14`), **not** on the
     truthiness of `progress`. So the tempting "any merely truthy assignment shows a false
     Completed" claim is false — `state_row or UnitProgress()` yields either the real row or one
     with `completed=False`, and a bare sentinel's missing `.completed` resolves to
     `string_if_invalid` (falsy). All of those leave 6(b) green. What 6(b) actually guards is the
     `progress`-vs-`progress.completed` distinction: a future template edit to `{% if progress %}`,
     or any assignment that fabricates a truthy `.completed` for a row that has none.
     *Falsify:* change the template to `{% if progress %}`, or assign
     `SimpleNamespace(completed=bool(state_row))` in the non-enrolled branch → RED. (Do **not** claim
     the "merely truthy" recipe reddens it; it does not.)
7. **The second render surface: `check_answer`'s no-JS path.** A non-enrolled viewer with a
   `completed=True` row — **seeded directly here**
   (`UnitProgressFactory(student=viewer, unit=unit, completed=True)`, both kwargs mandatory as in
   1(b)/3/6(b)), unlike test 9, because this test's falsification targets the *read* assignment and routing it through a
   `complete` POST would couple it to the write edit it does not guard — POSTs a Check on a question
   in that unit — **without** an
   `X-Requested-With: fetch` header — → the re-rendered lesson still shows the completed pill,
   asserted with **test 2's marker discipline** (`[data-unit-done]` carries `is-complete`, no
   `unit-done__pill--btn`), never `assert "Completed" in body` — see 6(a) for why that substring is
   always present and therefore vacuous.
   The header omission is load-bearing, not incidental: with it, `_wants_fragment` short-circuits to
   a question fragment that never renders the pill (see Architecture §2), and an implementer who
   adds the header to imitate the real UI will get a confusing failure against behaviour this change
   does not touch. Covers `notes/views.py:194` by the exemption argued in §2.
   **Fixture:** copy the repo's *only* no-JS `check_answer` test rather than inventing one —
   `courses/tests/test_reset_controls.py::test_reset_link_survives_the_no_js_check_answer_rerender`,
   which seeds a `ShortTextQuestionElement` and POSTs `{"answer": "x"}` (it documents why the answer
   must be non-empty). Naming it matters: every `check_answer` test in the top-level `tests/` package
   passes `HTTP_X_REQUESTED_WITH="fetch"` and therefore drives the *fragment* branch — the wrong
   template for this test. It also lives in `courses/tests/`, which has a module-level `pytestmark`,
   so the copied body needs its own `@pytest.mark.django_db` (see the file-placement rule).
   **Copy the element/POST recipe only — never that file's `_login` helper.** This is the trap that
   silently voids the test: `courses/tests/test_reset_controls.py:21-25` does
   `Enrollment.objects.create(student=student, course=course)` *before* `force_login`, so a copied
   `_login(client, course)` hands you an **enrolled** student. `build_lesson_context` then takes the
   `is_enrolled` branch and assigns `progress` via `get_or_create`, the pill renders completed for a
   reason that has nothing to do with the read edit, and the falsification recipe below stays
   **GREEN** — a test that pins the enrolled path while claiming to pin the previewer one. Build the
   viewer instead as the non-enrolled `can_access` shape this spec's other tests use (`make_login` +
   `is_staff = True`), take access from that `is_staff` pin rather than from the copied fixture
   (`make_course_with_unit()` mints an owner of its own, so the viewer is not it), and assert
   `not Enrollment.objects.filter(student=viewer, course=course).exists()` exactly as §5's Trap 2
   requires.
   Note the incidental write: on a `RESTORABLE_IN_LESSON` question type, `check_answer` calls
   `save_element_state` on the **same** pre-seeded `UnitProgress` row, which is harmless here but
   surprising if unexpected.
   *Falsify:* revert `progress = state_row` → RED (both render paths share the one assignment,
   which is precisely why this test must name the POST path explicitly rather than trusting test 2
   to cover it).
8. **Enrollment transition (pins an accepted decision, not a guard).** A non-enrolled viewer marks a
   unit done, is **then** enrolled → the row survives with `completed=True` and now counts as
   learner progress. **Drive the roster derivation, do not bypass it.**
   `build_progress_matrix(course, students, ...)` takes `students` as a parameter and applies no
   roster logic of its own, so handing it `[viewer]` makes the cell non-zero *before* enrollment too
   and the test would assert nothing about the transition. Instead feed it from
   `grouping/scoping.py::students_in_scope(resolver, course, "all")`, and assert the viewer is
   **absent** from it before enrollment and **present** after. **Re-resolve it on each side of the
   enrollment — never reuse one queryset object across the transition.** `reviewable_students`
   returns a lazy `User.objects.filter(pk__in=…)` (`grouping/scoping.py:72`), and a Django queryset
   caches its rows on first evaluation; the "absent before" assertion *is* that first evaluation, and
   `build_progress_matrix` additionally does `students = list(students)`. Binding it once and
   re-checking the same object after `EnrollmentFactory` therefore re-reads the stale cache and the
   "present after" assertion goes RED **against correct behaviour** — the same false-RED shape the
   resolver-role pin above exists to pre-empt. Call `students_in_scope(...)` afresh for the
   before-state, afresh for the after-state, and afresh for each `build_progress_matrix(...)` it
   feeds. **The `resolver` must be
   the course owner or a Platform Admin — this is load-bearing.** `students_in_scope(..., "all")`
   falls through to `reviewable_students`, which derives from `Enrollment` **only** on the PA/owner
   branch; for a group teacher it derives from `GroupMembership`. Pick a group teacher and enrolling
   the previewer adds them to neither queryset, so the "present after" assertion simply fails —
   against correct behaviour. **Pin the fixture as well as the role:** `CourseFactory(owner=resolver)`
   or `make_pa(...)`. `CourseFactory` declares no `owner`, so a "resolver" never assigned as one is
   neither PA nor owner and the control-student assertion fails for a reason the test text does not
   explain. Then **assert the matrix
   too, explicitly** — otherwise building it is unmotivated and the fixture constraint below has
   nothing to serve: before enrollment `build_progress_matrix(course, students_in_scope(...))` has no
   row whose `student` is the viewer; after enrollment it has one whose `overall["percent"]` is
   non-zero. **Seed a separate, genuinely enrolled control student**, exactly as test 10 requires and
   for the same reason: without one the pre-enrollment roster is empty, `rows == []`, and "the viewer
   is absent" is true of an empty matrix rather than of any scoping. Assert the control student **is**
   in `students_in_scope` and **is** a row in the *before* state, so the viewer's absence
   discriminates. That non-zero is achievable here (unlike test 10) precisely because the viewer *does*
   hold the completion. `lesson_pks` come from `is_obligatory_lesson`, so the seeded unit must be an
   **obligatory lesson** unit or that percent is `None`. Keep the row-survival assertion
   (`completed=True` still set after enrollment) alongside. Label the test in a comment as documenting the "Enrollment transition"
   decision, so nobody mistakes it for a safety guard.
   *Falsify:* **exempt, in writing** — like test 12, and for a stated reason rather than a shrug.
   Every other recipe here removes code that exists; this one would require *inventing* code that
   does not (there is no enrollment-creation hook: `Enrollment` has no `post_save` receiver, and the
   test enrolls via `EnrollmentFactory`, not through `grouping/services.py::add_students_to_group`).
   A recipe with no insertion point is not a falsification, it is a wish. This test documents a
   decision; it guards no code, and the spec says so rather than pretending otherwise.
9. **Downstream chrome actually lights up** (`test_previewer_mark_lights_outline_badge_and_footer_counter`)
   — the spec's whole rationale for fixing rather than hiding. The name carries **both** GETs on
   purpose: §1(a) argues that a name covering only one of a test's assertions invites a later reader
   to delete "the assertion unrelated to the name", and this test is among the most exposed to that,
   asserting across two pages and two rollup paths. **Two pins first, both load-bearing** (§8 and §10 pin their actors; this test must too):
   - **The acting user.** `build_outline(course, user)` and `build_unit_nav(course, user, node)`
     both key on the requesting user, so **both GETs must be issued as the previewer** — not as the
     owner or a teacher, which would fail for reasons unrelated to this change.
   - **The row's provenance.** The `completed=True` row must come from **that previewer's own POST**
     to `courses:complete`. Seeding it with `UnitProgressFactory(completed=True)` — the pattern
     `tests/test_e2e_unit_nav.py` uses — yields a green test whose diff-local falsification below
     **cannot redden**, because the row exists whether or not the write path works.
   These are **two different pages** and must be two GETs:
   - the **course outline** page (`course_outline` → `outline.html` → `_outline_node.html:8`) → the
     ✓ badge renders for that unit. Holds regardless of the unit's `obligatory` flag —
     `rollups.py` sets `"completed": is_unit and node.pk in completed`, i.e. for any completed
     **unit**, quizzes included. (The footer half below is the one that needs an obligatory lesson.) **Scope the assertion to the seeded
     unit's own row**: `outline.html` renders the whole course tree and `_outline_node.html:8` emits
     an identical bare `badge--done` span for *every* completed unit, so a body-wide substring check
     false-passes the moment any other unit is complete. `_outline_node.html:3` puts
     `data-unit="{{ item.node.pk }}"` on the `<li>` — **parse the `li[data-unit="<pk>"]` subtree**
     and assert inside it. A naive `data-unit="<pk>"[^>]*>` … `badge--done` regex does **not** work:
     `[^>]*>` stops at the `<li>`'s own closing `>`, so the match is unbounded on the right and runs
     straight into a later unit's badge — the exact false-pass the scoping exists to prevent. **Parsing is the recommendation; a regex needs care.** Two
     naive forms both false-pass in exactly the way this scoping exists to prevent, because a
     terminator placed *after* the target token constrains nothing about where that token matched:
     `data-unit="<pk>"[^>]*>` … `badge--done` and `data-unit="<pk>".*?outline-unit--done.*?(?:data-unit=|$)`
     will each run the leading `.*?` straight across a *later* `<li data-unit="…">` and match that
     unit's marker. Use a **tempered** pattern, which cannot cross the next unit's boundary:
     `re.search(r'data-unit="<pk>"(?:(?!data-unit=)[\s\S])*?outline-unit--done', body)`
     (`_outline_node.html:5` puts `outline-unit--done` on the unit's own `<a>`). Note `[\s\S]`, not
     `.`: the two tokens sit on `_outline_node.html:3` and `:5`, so any `.`-based form needs `re.S`
     or it matches nothing — a false RED against correct code — and `re.M` must **not** be set if a
     `$` arm is used, or `$` degenerates to end-of-line. Seed no other completed unit as hygiene; with
     the tempered pattern that is no longer what carries the bound;
   - the **lesson unit** page (`_unit_shell.html` → `_unit_footer.html:3-5`) → `unit_nav.course_progress.done`
     is non-zero. This half **requires an obligatory lesson unit**: `course_progress.done` sums
     `required_done`, which `rollups.py` sets only when `is_obligatory_lesson(node)`, and the footer
     bar does not render at all unless `course_progress.total` is truthy. `ContentNode.obligatory`
     defaults to `True`, so a default fixture works — but an implementer seeding a plausibly
     "additional" unit would get a failure unrelated to this change. Asserting on
     **`response.context["unit_nav"]["course_progress"]["done"]`** from the previewer's lesson GET
     is the recommended assertion: `full_lesson_render_context` sets `ctx["unit_nav"] =
     build_unit_nav(...)`, so this reaches the value through the real view without parsing HTML.
     Calling `build_unit_nav(...)` standalone is a fallback only if the test client's context is
     unavailable — and even then the lesson-unit GET must still be issued as the previewer.
     `build_unit_nav` is a pure function, so calling it *instead of* the GET would skip the
     view-level wiring this test's whole claim is about and quietly dissolve the "two GETs" rule it
     sits inside, leaving a GET that asserts nothing beyond not-500-ing.
   The two assertions exercise different rollup paths; do not collapse them into one response.
   *Falsify (diff-local, the one that matters):* restore the `is_enrolled` branch in `complete` →
   RED, proving the test is non-vacuous with respect to *this* change.
   *Secondary (wiring check only):* break `build_outline`'s authenticated
   `student=user, ..., completed=True` query → RED — but note this reddens much of the existing
   outline/nav suite too, so it demonstrates the rationale is still wired, not that this test earns
   its place.
10. **Containment: an off-roster previewer is invisible to teacher-facing surfaces**
    (`test_off_roster_previewer_absent_from_matrix_and_drilldown`) — the name covers both mechanisms
    for the §9 reason: they are separately falsifiable and a single-mechanism name invites deleting
    the other. This is the
    claim the entire "fix rather than hide" decision rests on, and the spec itself flags its premise
    (GroupMembership ⊆ Enrollment) as maintained by services rather than enforced by the query — the
    exact shape the repo's access-widening doctrine says to drive end to end. A non-enrolled
    `can_access` previewer marks a unit done; then, **as the course owner or a Platform Admin**
    (same load-bearing reason as test 8 — only that branch of `reviewable_students` derives from
    `Enrollment`, and `analytics_student`'s `can_review_course` gate resolves the same way), resolve
    `students_in_scope(resolver, course, "all")` and build the analytics matrix from it.
    **Two distinct fixture requirements — and be accurate about what each protects.**
    `build_progress_matrix` builds `rows` from the `students` argument **unconditionally**
    (`for s in students: … rows.append(…)`); the `if all_lesson_pks and students:` guard gates only
    the population of the `completed` lookup dict. So:
    - `students` — an empty roster is the *only* thing that yields `rows == []`, which would make
      "the previewer is not a row" true for a reason unrelated to any scoping. The fixture must
      contain a genuinely **enrolled student**, and the test must assert that student **is** a row;
    - `all_lesson_pks` — an empty one does **not** empty `rows`; it flattens every cell to
      `_cell(None)`. It is unioned from `frontier_columns`, which collects only
      `is_obligatory_lesson(n)` units, so the seeded unit must be an **obligatory lesson** unit.
      The **positive control is `percent is not None`, not "non-zero"** — this matters: the enrolled
      student holds no completion in this fixture, so `_pct(0, total)` gives them a perfectly
      legitimate `0`, and asserting non-zero would go RED against correct code. `None` is what an
      empty `all_lesson_pks` produces, so `None` is the discriminator. (If you would rather assert
      non-zero, the fixture must also give the enrolled student a `completed=True` row on that same
      unit — extra setup buying nothing.)
      Assert on the enrolled student's **`overall["percent"]`**, or on the cell of the column that
      contains the seeded unit — not on `cells[0]` or on every cell. `frontier_columns` emits one
      column per top-level node and any column with no obligatory lessons is `_cell(None)` **by
      design**, so a blanket assertion fails for reasons unrelated to the guard being probed.
    Note `assert matrix["rows"]` alone discriminates neither arm properly: it catches an empty
    roster and is blind to an empty `all_lesson_pks`.
    Assert both halves: the matrix is populated **and still** omits the previewer — which is exactly
    the claim the containment argument needs.
    **Both containment mechanisms must be driven, because they are not the same** (see Data flow):
    - **roster-argument scoping** — the matrix assertion above. Note the mechanism is the `students`
      argument, **not** the `student__in=students` filter: deleting that filter leaves this
      assertion green (it only widens a lookup dict), so do not reach for it as a falsification.
    - **view-level resolution** — the **same course-owner/PA resolver** (never a group teacher — see
      the pin above) GETs `courses:manage_analytics_student` for the previewer's pk → **404** while
      they are off the roster, **200** once enrolled. `analytics_student` reaches `build_outline`
      with no roster filter at all, so the matrix assertion says nothing whatever about this surface.

    The **gradebook export** (`views_export.py:44`) is **exempt in writing**, in the same register as
    `notes/views.py:194`: it resolves its students through the identical `students_in_scope` call the
    matrix assertion already drives, with no roster logic of its own between them. A third test would
    pin the call site rather than any behaviour.

    **Pin the completion's provenance, exactly as §9 does.** Step (1)'s `completed=True` row must
    come from **that previewer's own POST** to `courses:complete`, issued while logged in as them,
    not from `UnitProgressFactory(completed=True)`. §10 opens by invoking the repo's access-widening
    doctrine — drive each newly-reachable route end to end — and a seeded row tests containment
    against a row the new write path never produced. The falsification recipe below cannot catch the
    substitution: moving `EnrollmentFactory` ahead of step 2 reddens whether the row was POSTed or
    seeded, so nothing but this sentence forces the end-to-end drive.

    **Sequence the test explicitly**, because the enrollment is part of the fixture, not an external
    mutation: (1) the previewer marks the unit done while off the roster; (2) assert the matrix is
    populated but omits them **and** the drill-down 404s; (3) enroll the previewer; (4) assert the
    drill-down now 200s. **The previewer and the resolver must be two distinct users** — the course
    owner is itself one of test 5's non-enrolled `can_access` routes, so an implementer can
    accidentally cast one user as both, which silently makes the session switch below a no-op and
    the test's own warning self-contradictory while everything still passes. Natural wiring: test 1's
    `is_staff` previewer plus a separate owner or PA — and **pin the resolver's fixture, not just
    their role**: either `CourseFactory(owner=resolver)` or `make_pa(...)`. `CourseFactory` sets no
    owner (see test 5(a)), so "a separate owner" who is never assigned as one is neither PA nor
    owner; `can_review_course` then returns False and `analytics_student` 404s **unconditionally** —
    step 2 passes for a reason unrelated to the roster and step 4 fails against correct behaviour,
    exactly the shape test 8's resolver *role* pin exists to pre-empt (that pin is about
    owner/PA vs group teacher; this is the fixture half of it, which §8 now carries too). **Step 1 runs as the previewer; steps 2–4 run
    as the resolver** — switch the login between them (or use a second `Client()`). `tests.factories`' login helpers log
    in on the shared client and silently replace the session, so forgetting this makes step 2 issue
    the drill-down GET as the previewer.
    *Falsify:* move the `EnrollmentFactory` call ahead of step 2 → **both** step-2 assertions go
    RED, proving each discriminates.
11. **Double POST is idempotent and writes nothing the second time**
    (`test_double_complete_post_is_idempotent_and_issues_no_second_update`) — the name names the
    load-bearing third assertion, not just idempotence, for the §9/§1(a) reason: the query assertion
    is the only one of the three that a guard deletion reddens, and a name saying only "idempotent"
    reads as satisfied by the row-count assertion alone. A previewer POSTs `complete`
    twice, **issued directly by the test client** — after the first POST the pill replaces the form,
    so a second POST is not reachable through the UI at all. It is a real path nonetheless (double
    submit, back-button, a retried request), and that unreachability is precisely why there is no
    e2e counterpart to chase. Assert: exactly one row, and `completed_at` **on the DB row** is unchanged after the second POST
    (`complete` returns a bare 302 with no body, so there is no response field to compare — assert
    against the row).
    The load-bearing assertion is the third: **the second POST issues no `UPDATE` on
    `courses_unitprogress`** — wrap it in `CaptureQueriesContext` and assert no captured statement
    updates that table. **Pin the match**, or the assertion passes vacuously: Postgres captures
    `UPDATE "courses_unitprogress" SET …` with a *quoted* identifier, so a naive
    `'UPDATE courses_unitprogress' in sql` never matches. Use
    `re.search(r'update\s+"?courses_unitprogress"?', q["sql"], re.I)` over `ctx.captured_queries`.
    Expect SAVEPOINT/RELEASE and both SELECTs in the capture — the assertion targets `UPDATE` on
    that one table, never "no writes". Do **not** assert instead that an `element_state` key written between the
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
12. **Enrolled path unregressed.** The existing enrolled tests
    (`test_seen_merges_and_autocompletes`, `test_zero_element_unit_completes_only_via_fallback`)
    stay green. Be accurate about what that buys: the first never reaches `complete` at all — it
    POSTs `seen` — and the second POSTs `complete` once, on a zero-element unit, with no
    pre-existing row. So the enrolled path's only `complete` coverage is that narrow case, which is
    why test 1(c) exists.
    *Falsify:* exempt — these are pre-existing tests being protected from regression, not new
    guards. Per the falsifiability doctrine, a test whose behaviour the diff does not change has no
    honest RED recipe, and claiming one would be theatre.

**File placement (one rule, since placement is load-bearing here).** Every new test in this list
lands in `tests/test_courses_progress.py`, beside the inverted test — including tests 9 and 10, which
have plausible homes in `tests/test_courses_rollups.py` and the analytics-scoping tests but belong
here, because their whole point is what *this* change does to those surfaces and the co-location is
the signal. The sole exception is test 4, which is not new: it already exists as
`courses/tests/test_markdone_render.py::test_passive_non_enrolled_viewer_gets_no_progress_row`, in a
different package, and stays there. **Note the marker convention differs between the two packages:**
`tests/test_courses_progress.py` has **no** module-level `pytestmark` and decorates each test with
`@pytest.mark.django_db` individually, while the `courses/tests/` modules set
`pytestmark = pytest.mark.django_db` at module level. Copying a test body across (e.g. §7's
`check_answer` fixture) silently drops the DB marker — decorate every new test explicitly.

Use `tests.factories`' helpers and `TEST_PASSWORD`; never a hardcoded password. The existing
previewer tests build their viewer as `is_staff = True`, which is the production-accurate shape for
a Course Admin (`institution.roles.role_is_staff(COURSE_ADMIN)` is `True`) — keep that as the
primary case, but test 5 deliberately adds the **owner** route, the **non-archived-group-teacher**
route, and their two negative twins (archived group, unrelated logged-in user) on top of it.

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
- **all seven comment edits present, and the atomic-block one stating the ordering rule** (not
  merely present — see §2b's "Required content"). No automated gate covers any of these, and the
  re-fetch they document is the one piece of code in the diff no test can protect, so leaving the
  risk as a noun phrase ("needs a checklist hook") is not actionable. **The concrete mechanism: the
  PR description must quote all seven edited comment bodies verbatim, under a heading naming them as
  the unguarded half of the diff** — a reviewer can then diff prose against prose, which is the only
  gate available for text no test reaches. Two new (`complete`'s atomic block;
  `complete`'s access check) and five corrections (`views.py` ≈:273-275, ≈:396-398, ≈:652,
  ≈:784-788, and `_lesson_article.html:8-11`);
- each **new, inverted or extended** test falsification-proven (guard removed → RED → restored) —
  concretely tests **1(a), 1(b), 2, 3, 5(a)–(d), 6(a), 6(b), 7, 9, 10, 11**. Exempt in writing:
  **8** (no insertion point exists for the mutation), **12** (pre-existing regression protection),
  **1(c)** entirely, and **1(b)'s `element_state` assertion** (both regression cover, not guards —
  see Testing §1). Test **4** is pre-existing and unchanged, so running its recipe is optional — it
  is listed to stop an implementer duplicating it, not as new work;
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
- **Help-content updates — deferred, not overlooked.** `docs/help/course-admin/content-editors.md`
  tells Course Admins to "Preview the unit as a student would see it before publishing a course" —
  addressed at exactly the population this change newly exposes to a permanent mark. Nothing in that
  guidance becomes *wrong* (previewing is still correct advice; only the button now does something),
  so no edit ships here. It is named so the decision is recorded, and so a later toggle/reset spec
  knows where the user-facing wording lives.

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
    completed⇒completed_at invariant "for EVERY write path (incl. admin)". So a **superuser** can
    already create or flip a `completed=True` row for any user, enrolled or not. (Superuser
    specifically — no role group grants `unitprogress` model permissions; see "The decision, and
    why", bullet 4. The narrowing does not weaken this "not new" argument, which needs only that the
    route exists.) That is a *second* existing
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
