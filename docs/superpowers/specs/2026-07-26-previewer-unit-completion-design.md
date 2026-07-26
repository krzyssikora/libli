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

Two edits in `courses/views.py`, one deliberate non-edit, and one existing test inverted. No
migration, no model change, no new URL, no template change, no JS change, no new translatable
strings.

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

**Downstream, roster-scoped (unaffected):** the teacher-facing frontier/matrix query in
`courses/rollups.py` filters `student__in=students` — an enrolled roster — so a non-enrolled
viewer's row can never appear in teacher analytics or the gradebook.

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
   *Falsify:* restore the `is_enrolled` branch → RED.
2. **Read (the one that catches a write-only fix).** After that POST, the same viewer GETs the
   lesson → the response contains the "Completed" pill and **not** the "Mark as done" submit button.
   *Falsify:* revert `progress = state_row` → RED while test 1 stays green.
   Assert on a marker that cannot false-pass: `unit-done__pill--btn` (the button class) must be
   absent and `is-complete` present. Do **not** assert on the bare string `type="submit"` —
   `base.html` emits it unconditionally for the language switcher and logout.
3. **Asymmetry guard.** A non-enrolled `can_access` viewer POSTs every element id to `courses:seen`
   → still no completion (existing `test_previewer_seen_no_write_synthetic` covers this; keep it adjacent
   to test 1 so the deliberate split is legible in one screen).
4. **No spurious row on GET.** A non-enrolled viewer merely GETting the lesson creates no
   `UnitProgress` row.
   *Falsify:* change the read to `get_or_create` → RED.
5. **Access still enforced.** A logged-in user who fails `can_access_course` POSTing `complete` gets
   403 and no row.
6. **Enrolled path unregressed.** The existing enrolled complete/auto-complete tests
   (`test_seen_merges_and_autocompletes`, `test_zero_element_unit_completes_only_via_fallback`) stay
   green.

Use `tests.factories`' helpers and `TEST_PASSWORD`; never a hardcoded password. Note the existing
previewer tests build their viewer as `is_staff = True` — that is the production-accurate shape for
a Course Admin (`role_is_staff(COURSE_ADMIN)` is `True`), so reuse it rather than inventing a role.

### Definition of done

- Full non-e2e suite green (`-n auto`), no new failures against the base;
- `ruff check` and `ruff format --check` clean;
- `manage.py makemigrations --check` and `manage.py check` clean (both expected trivially — no model
  change);
- each new/inverted test falsification-proven (guard removed → RED → restored).

No e2e test is required: the change has no client-side component, and the round trip is fully
observable at the view/template layer by tests 1 and 2.

## Non-goals

- Auto-completing units for non-enrolled viewers on scroll (explicitly rejected above).
- Making completion resettable via "Start fresh".
- Letting non-enrolled viewers submit quizzes or accumulate quiz analytics.
- Suppressing progress chrome (outline badges, tree counters, footer bar) for non-learners.
- Any change to how teacher-facing analytics scope their students.

## Accepted side effects

- A non-enrolled viewer's own outline ✓ badges, unit-tree counters and footer progress bar begin
  reflecting their manual marks. This is the intended payoff, not a regression.
- `courses/views_manage.py::course_delete`'s "N progress records" count may include such rows. This
  is already true today, since a checklist tick creates a `UnitProgress` row for a non-enrolled
  viewer; the change adds no new class of row.
