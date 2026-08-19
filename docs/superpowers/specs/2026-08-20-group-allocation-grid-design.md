# Group allocations and the assignment grid

## Purpose

Assigning students to a course's groups is done today one group at a time, in
`grouping/views.py::group_edit`, through a flat checkbox roster
(`templates/grouping/group_form.html` + `grouping/static/grouping/js/roster_filter.js`).
Two things are painful at school scale:

1. **Bulk selection.** After filtering the roster to a cohort, every student must be
   ticked individually. There is no "add all".
2. **Whole-year allocation.** A school splits a year group (a *cohort*) into parallel
   classes on one course — e.g. "matematyka" taught by four teachers. Working group by
   group, the admin cannot see *who has not been placed yet* and cannot see *who has been
   placed twice*, because each group's page shows only its own roster. Both mistakes are
   silent and expensive: an unplaced student never gets the course, a twice-placed student
   shows up in two teachers' registers.

This design adds:

* an **add-all checkbox** to the existing roster picker, and
* an **allocation** — a named grouping of a course's groups that are meant to partition
  one or more cohorts — plus an **assignment grid** that shows students down the side and
  the allocation's groups across the top, so a whole year group is placed in one screen
  with unplaced and double-placed students visible at a glance.

### Non-goals

* No change to how a group's roster is edited today; the per-group picker stays, and the
  grid is an additional surface, not a replacement.
* No cross-course allocations (see "Course scoping" below).
* No marking of memberships in groups belonging to *other* courses. A student is normally
  in several course groups; badging them would bury the signal that matters.
* No timetabling, capacity limits, or auto-balancing. The grid records decisions; it does
  not make them.
* No enforcement of the course-scoping invariant against bulk-write paths
  (`QuerySet.update`, `bulk_update`, fixtures, data migrations) — see "Course scoping".

### Terminology, and two names that are already taken

The concept is called **allocation** throughout: model `Allocation`, field
`Group.allocation`, URL segment `allocations`, UI label "Allocation".

Two nearby names are **already used in this repository and must not be reused**:

* `grouping.Collection` — a teacher-owned bundle of groups used for combined analytics.
* "band" — `courses/color_bands.py`, the per-course analytics colour bands.

## Architecture

### Data model

New model in `grouping/models.py`:

```python
class Allocation(models.Model):
    name = models.CharField(max_length=200)
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="allocations"
    )
    cohorts = models.ManyToManyField(Cohort, blank=True, related_name="allocations")
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["course", "name"], name="uniq_allocation_course_name"
            )
        ]
```

and a new field on `Group`:

```python
    allocation = models.ForeignKey(
        Allocation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="groups",
    )
```

`Group.allocation` defaults to `None`; every existing group keeps that value, so the
feature is inert until an admin opts a group in.

One migration in `grouping/migrations/` creates the model, the M2M table, the constraint,
and the nullable FK. It adds no data operation — nothing to backfill. Its number is
whatever the graph head is at implementation time (`0004_group_external_id` is the head
today, so `0005_allocation` unless something else lands first); any test that exercises
migrations must target the graph head rather than a pinned migration name.

**Course scoping (the load-bearing invariant).** An allocation belongs to exactly one
course, and every group in it must belong to that same course. This is what makes "each
student belongs to at most one group here" a meaningful rule: if an allocation could span
courses, a student legitimately sitting in a maths group and a physics group would read as
a conflict, and the grid's central signal would be noise. Enforcement is at three Python
points:

* `Group.save()` raises `ValidationError` when `allocation_id` is set and
  `allocation.course_id != self.course_id`. `Group.save()` already freezes `course` after
  creation, so a group can never drift out of its allocation's course afterwards.
* `Allocation.save()` raises `ValidationError` when `course_id` changes while any group is
  attached — the mirror-image drift, and the reason the form's `disabled` widget is not
  sufficient on its own. This mirrors `Collection.save()`'s existing guard.
* `GroupForm.clean()` surfaces the group-side rule as a field error rather than a 500.

There is deliberately **no database-level backstop**: the rule relates two tables
(`grouping_group.course_id` must equal `grouping_allocation.course_id`), which a
`CheckConstraint` cannot express. `Collection`'s equivalent rule is enforced by an
`m2m_changed` receiver in `grouping/signals.py`; an FK assignment offers no such hook.
Bulk-write paths (`QuerySet.update`, `bulk_update`, fixtures, data migrations) therefore
bypass all three guards, and are explicitly out of scope — as they already are for
`Group.course`'s existing immutability guard.

**Lifecycle.**

* *Deleting* an allocation nulls `Group.allocation` (`SET_NULL`) and touches no
  membership. Groups and rosters survive; only the grouping label is gone.
* *Archiving* an allocation removes it from the group form's picker (except on a group
  already attached to it — see "Forms") and from the default allocation list, and leaves
  groups and memberships **completely alone**. This is deliberately unlike
  `services.archive_cohort`, which reassigns members to the default cohort: a cohort is a
  student's single home and cannot be left dangling, whereas an allocation is only a label
  over groups that remain valid on their own. `allocation_archive` **toggles**, exactly as
  `group_archive` does, so `?archived=1` plus that button is the un-archive path.
* Archiving or deleting a *group* needs no allocation-specific handling: archived groups
  are excluded from the grid's columns by the same `archived=False` filter used elsewhere,
  and a deleted group takes its memberships with it.
* Archiving a *cohort* attached to an allocation: `services.archive_cohort` reassigns every
  member to the Default cohort, so that cohort's section of the grid empties of students,
  while the cohort itself remains in `Allocation.cohorts` (nothing cascades). Students
  already placed in the allocation's groups still appear, via the "already assigned" arm of
  the row union, now under the Default cohort's heading or the "outside these cohorts"
  heading. Nothing is silently unassigned.
* Deleting a *cohort* likewise reassigns members to Default first, then cascades the M2M
  row away, so the allocation simply loses that cohort from its row set. Already-placed
  students still appear through the same union arm.

### Permissions and scoping

`institution/roles.py` gains `grouping.add_allocation`, `change_allocation`,
`delete_allocation`, `view_allocation` in **`GROUPING_COURSE_ADMIN_PERMS`** and
**`GROUPING_PLATFORM_ADMIN_PERMS`** — the two lists that already carry the grouping
permissions (note: *not* `PLATFORM_ADMIN_PERMS`, which holds the accounts / institution /
courses permissions). Teacher gets none: teachers do not manage groups today, and the grid
writes group membership.

**Operational step (permissions do not reach an existing database by themselves).**
`institution/migrations/0003_seed_roles.py` creates only the four auth Groups; permission
*assignment* happens in `institution.roles.seed_roles()`, which runs only from
`python manage.py setup_roles` (and from `init_platform` / `seed_demo_course`). Editing the
constants therefore grants nothing on an already-migrated database. Running
`python manage.py setup_roles` after `migrate` is part of this change's definition of done.
The test suite masks this gap — `tests/factories.py` calls `seed_roles()` — so no test can
catch it; it is called out here instead.

`grouping/scoping.py` gains:

```python
def allocations_manageable_by(user):
    """Allocations a user may create/edit/delete. Mirrors groups_manageable_by:
    PA -> all; CA (tested via `user.has_perm("grouping.change_allocation")`) ->
    allocations on courses they own; else none. Owner-less courses (Course.owner
    is nullable) are PA-only, as for groups."""
```

The CA branch tests `grouping.change_allocation`, so a user holding `change_group` but not
`change_allocation` passes `allocation_assign`'s decorator and then gets a 404 from the
scoped lookup. That is the intended outcome and is asserted by a test.

Because manageability is decided per *course* and an allocation is course-scoped, an admin
who can manage one group of an allocation can manage all of them. The grid therefore never
needs read-only columns — a simplification that follows from course scoping, not an
assumption about the data.

### URLs and views

Added to `grouping/urls.py`, alongside the existing cohort and group management routes:

| URL | name | view |
|---|---|---|
| `manage/allocations/` | `allocation_list` | `allocation_list` |
| `manage/allocations/new/` | `allocation_create` | `allocation_create` |
| `manage/allocations/<int:pk>/edit/` | `allocation_edit` | `allocation_edit` |
| `manage/allocations/<int:pk>/archive/` | `allocation_archive` | `allocation_archive` (POST, toggles) |
| `manage/allocations/<int:pk>/delete/` | `allocation_delete` | `allocation_delete` |
| `manage/allocations/<int:pk>/assign/` | `allocation_assign` | `allocation_assign` (GET + POST) |

CRUD views are gated with `permission_required("grouping.<verb>_allocation")` and scoped
through `allocations_manageable_by`, following `group_list` / `group_edit` /
`group_archive` / `group_delete`.

`allocation_create` additionally repeats `group_create`'s **create-time ownership check**,
which scoping cannot cover because there is no row to scope yet:

```python
if not (request.user.has_perm("courses.change_course")
        or course.owner_id == request.user.id):
    raise PermissionDenied
```

`AllocationForm.course`'s queryset is additionally restricted to courses the user may use
(all courses for a PA, owned courses for a CA), so the check is a backstop rather than the
only gate.

`allocation_list` shows non-archived allocations by default with the same `?archived=1`
toggle `group_list` uses, ordered `("course__title", "name")`. Each row shows the
allocation name (linking to its grid), the course, the attached cohort names, and the
count of non-archived groups; row actions are Edit, Archive/Un-archive, Delete. It sets
`hub_tab = "allocations"` and includes `_groups_tabs.html`.

`allocation_assign` is gated on **`grouping.change_group`** — it writes `GroupMembership`,
not `Allocation` — and additionally resolves the allocation through
`get_object_or_404(scoping.allocations_manageable_by(request.user), pk=pk)`.

### Forms

**`AllocationForm`** (`ModelForm`): fields `name`, `course`, `cohorts`, with `cohorts` as a
`CheckboxSelectMultiple`. `archived` is not a form field — archiving goes through the POST
view, matching how `CohortForm` keeps `archived` off the form. `course` is disabled once
the allocation has groups attached, mirroring `CollectionForm`.

The `cohorts` queryset is `Cohort.objects.filter(Q(archived=False) |
Q(pk__in=self.instance.cohorts.values("pk")))` when editing, `archived=False` when
creating. The `pk__in` arm is load-bearing: `ModelMultipleChoiceField` validates posted pks
against its own queryset and silently drops anything outside it, so a plain
`archived=False` queryset would strip an already-attached, later-archived cohort from the
M2M on the next unrelated save — emptying a whole section out of the grid. An attached
archived cohort renders with an "(archived)" suffix.

**`GroupForm`** gains an allocation control that satisfies "pick an existing value, or type
a new one":

* `allocation` — a `ModelChoiceField` with an empty "— none —" choice, queryset
  `Allocation.objects.filter(Q(archived=False) | Q(pk=self.instance.allocation_id))`. The
  second arm is load-bearing for exactly the reason above: without it, opening a group
  whose allocation has since been archived and saving an unrelated change (a rename, a
  teacher) would write `allocation = None` and silently detach the group. The attached
  archived allocation renders with an "(archived)" suffix.
* `new_allocation` — a plain `CharField(required=False)`, "or create a new allocation".

`clean()` rules: supplying both is an error ("choose an existing allocation or type a new
name, not both"); a `new_allocation` name is stripped and matched case-insensitively
(`iexact`) against existing allocations on that course so the same name cannot fork into
two rows; the chosen or created allocation's course must equal the group's course.

`save()` resolves `new_allocation` inside the same transaction as the group save, using the
repo's savepoint-and-retry idiom (as in `services.add_students_to_group` and
`services.enroll_self`) rather than a bare `get_or_create`:

```python
try:
    with transaction.atomic():
        allocation, _ = Allocation.objects.get_or_create(course=course, name=name)
except IntegrityError:
    allocation = Allocation.objects.get(course=course, name=name)
```

`get_or_create` matches exactly while `clean()` deduped case-insensitively, and two
concurrent saves of the same new name race regardless — either path would otherwise raise
`uniq_allocation_course_name` as a bare 500.

**Rendering the allocation select.** `ModelChoiceField` emits a flat `<option>` list, so
grouping by course is built explicitly: a custom `ModelChoiceIterator` subclass yields
`(course.title, [(pk, name), ...])` tuples, which Django's `Select` widget renders as
`<optgroup>`s. Each `<option>` also carries `data-course="<course_pk>"`, which is what the
client-side filter keys on.

On the **create** form the course is chosen in the same submission, so all selectable
allocations are rendered and filtered client-side to the selected course; the server
re-validates the course match regardless, so the filter is convenience, never the gate.
That filter is a small `initAllocationFilter()` function appended to
`grouping/static/grouping/js/roster_filter.js` (already loaded by `group_form.html`'s
`{% block extra_js %}`), keyed on `[data-allocation-select]` and the course select's value.
On the **edit** form `course` is already disabled, so the list is filtered server-side to
that one course and the script is inert.

### Templates and static files

New templates: `templates/grouping/allocation_list.html`, `allocation_form.html`,
`allocation_confirm_delete.html`, `allocation_assign.html`.

`templates/grouping/group_form.html` gains the allocation row plus, on a saved group with
an allocation, a link to that allocation's grid. `templates/grouping/group_list.html`
gains a muted allocation name per row, and `group_list`'s queryset gains
`select_related("course", "allocation")` so the extra column is not an N+1.

**Entry points.** Two, both gated on `grouping.change_allocation`:

* a third tab in `templates/_groups_tabs.html` ("Allocations"), **nested inside** the
  strip's existing `{% if perms.grouping.view_group %}` wrapper — a Teacher holds
  `view_group` and must keep seeing the strip without the new tab. `tests/test_groups_tabs.py`
  already asserts strip composition and gains a case for this.
* an "Allocations" item in the Admin menu in `templates/base.html`, next to "Cohorts". That
  menu's outer `{% if %}` currently tests four platform-admin-only permissions, so it
  renders for PA only; `or perms.grouping.change_allocation` must be added to that outer
  condition as well, or a Course Admin would hold the permission and still never see the
  menu.

New static files:

* `grouping/static/grouping/css/allocation_grid.css`, loaded via `{% block extra_css %}`
  (`templates/base.html:49`) — sticky header row, sticky name column, and the row-state
  treatments. Colours come from the existing surface/border tokens in
  `core/static/core/css/tokens.css`, with explicit dark-mode definitions; no raw hex.
* `grouping/static/grouping/js/allocation_grid.js`, loaded via `{% block extra_js %}` —
  live summary counts, row-state classes, and the row filters.

`grouping/static/grouping/js/roster_filter.js` is extended with the add-all control and the
allocation-select filter.

### The add-all checkbox

A checkbox rendered inside each roster fieldset's filter bar (`[data-roster-filter]`),
labelled "Select all shown", carrying **no `name` attribute** — like the existing filter
inputs, it must never post. Its wrapping `<label>` is rendered `hidden` and unhidden by the
script on init (the same treatment `[data-roster-count]` gets), so with JS off it is
invisible and the roster submits exactly as it does today.

* Checking it ticks every **visible** item; unchecking clears every **visible** item.
  Hidden items — those filtered out by the cohort select or the name search — are never
  read and never written. This is the whole point: "filter to Year 1, then add all" must
  not sweep in the rest of the school, and the *unchecking* direction matters more, because
  there a stray sweep silently removes students.
* With zero visible items it is unchecked and `disabled`.
* Its tri-state is recomputed by a new `syncAddAll()`: unchecked when no visible item is
  ticked, checked when all are, `indeterminate` in between.

**Wiring (the part that does not happen by itself).** Setting `input.checked` from script
fires **no** `change` event, and `roster_filter.js` currently updates its counter only via
`list.addEventListener("change", updateSelected)`. So the add-all handler must call
`updateSelected()` explicitly after mutating checkboxes, and both `applyFilter()` (which
also runs once at init) and the list's `change` handler must call `syncAddAll()`.

`roster_filter.js` initialises every `[data-roster]` fieldset generically, so the teachers
fieldset gets an add-all too. That is intended: special-casing it out would be more code
than leaving it, and it is harmless on a short list.

### The assignment grid

`allocation_assign` renders one `<form method="post">` containing a table.

**Columns.** `— none —`, then the allocation's `archived=False` groups ordered by name.
Archived groups of the allocation are *not* columns; a membership in one is left untouched
and surfaces in the row's "also in" note.

**Rows.** The union of

* `services.student_users()` whose `cohort_membership.cohort` is one of the allocation's
  cohorts, and
* every student already in one of the allocation's non-archived groups —

so a student assigned from outside the attached cohorts can never become invisible (which
would strand a membership the admin cannot see or undo from this screen).

The union **must be built by pk membership**, not `qs_a | qs_b`:

```python
User.objects.filter(Q(pk__in=by_cohort.values("pk")) | Q(pk__in=assigned.values("pk")))
```

`services.student_users()` ends in `.distinct()`, and OR-ing a distinct queryset with a
non-distinct one raises "Cannot combine a unique query with a non-unique query."
`scoping.collections_visible_to` carries an in-repo comment documenting exactly this trap
and this workaround; follow it.

Rows are grouped under a heading per attached cohort, ordered `-is_default, name`, with a
final "outside these cohorts" heading for the second arm's leftovers. Within a heading,
students sort by `polish_sort_key(user.sort_name)` then `username`, exactly as
`group_detail` does. Memberships needed for the row states and the "also in" notes are
fetched in one query over `GroupMembership.objects.filter(student_id__in=..., group__course=
allocation.course).select_related("group")` and bucketed in Python — never per row.

**Cells.** One radio group per student row, `name="student-<pk>"`, one radio per column;
the `— none —` radio carries `value=""`. Radios make double assignment impossible by
construction, which is the feature's stated goal. Each radio carries an `aria-label` of the
form "<student> → <group>" (and "<student> → none"), because a bare radio in a table cell
has no accessible name and would otherwise be read as one of N unlabelled options.

**Row states.**

| State | Condition | Treatment |
|---|---|---|
| assigned | exactly one membership among the columns | normal row; that column's radio checked |
| unassigned | no membership among the columns | amber row, **plus a text/icon marker** ("not placed"); `— none —` checked |
| conflict | two or more memberships among the columns (pre-existing data) | red row, **no radio checked**, warning icon |

Both non-normal states carry a non-colour marker: colour alone fails colour-blind users and
high-contrast mode.

Independently of the above, a row shows a muted "also in: 2B" note listing the student's
memberships in groups of **this course** that are not columns — i.e. groups in another
allocation, groups with no allocation, and archived groups of this allocation. One rule
covers all three cases.

**Summary.** A header line — "84 students · 72 assigned · 11 unassigned · 1 conflict" —
rendered server-side from the computed row states and updated live by
`allocation_grid.js` as radios change. It **always describes the whole allocation**, never
the filtered subset: "who is still unplaced" is the number the admin came for, and a
filter-sensitive count would hide exactly the students being looked for.

**Filters.** A name search and a cohort select that only *hide* rows (`hidden` attribute).
Every input stays in the DOM, mirroring the roster picker's rule, so a hidden row still
posts and is never silently rewritten.

**Empty states.** With no rows, the grid names the cause and the fix: "This allocation has
no cohorts attached" (linking to `allocation_edit`) when `cohorts` is empty, and "No
students in the attached cohorts yet" when cohorts are attached but yield nobody. With no
columns: "No groups belong to this allocation yet" (linking to `group_list`).

**Form size.** Each row posts two fields (the radio's single value plus the hidden token),
so a grid past roughly 500 students exceeds Django's default
`DATA_UPLOAD_MAX_NUMBER_FIELDS` of 1000 and 400s with `TooManyFieldsSent`, losing every
pending edit. No override exists in `config/settings/`; this change adds one — raised to
5000, with a comment naming this form as the reason — which covers ~2400 students.

Without JavaScript the grid still works: native radios, server-rendered summary and row
states, and no filters.

## Data flow

### Rendering

1. Resolve the allocation through `allocations_manageable_by`.
2. `columns` = `allocation.groups.filter(archived=False).order_by("name")`.
3. `rows` = the pk-membership union described above, each annotated with: the set of column
   group ids the student belongs to, the derived state, the "also in" group names, and a
   **state token**.
4. The state token comes from `services.allocation_state_tokens(allocation, student_ids)`:
   for each student, the ids of the column groups they belong to, sorted ascending and
   joined with `,` — `""` for none, `"12"` for one, `"12,15"` for a conflict. One helper,
   called at render and again at save, so the two cannot drift *for a fixed column set*
   (see the column-set rule below).
5. Each row renders a hidden `<input name="student-<pk>-was" value="<token>">` next to its
   radios. The form also renders one hidden `<input name="columns" value="<sorted column
   ids>">` describing the column set the page was built from.

### Saving

`allocation_assign` POST, wrapped in a single `transaction.atomic()`:

1. **Column-set check first.** Recompute the current columns; if their sorted ids differ
   from the posted `columns` field, abort the whole save, change nothing, and re-render
   with "the allocation's groups changed while you were editing — reload and try again."
   Every row's token is computed *over the columns*, so a column archived between render
   and POST would otherwise shift every affected student's token at once and be reported as
   dozens of phantom "someone else changed this" rows.
2. Recompute the **server's own row set** — the request body is never trusted to define
   which students are editable. A posted `student-<pk>` for a student outside the
   recomputed row set is ignored.
3. For each row student, if `student-<pk>` is absent from the POST, the row is left
   untouched. This is exactly what an unresolved conflict row does (no radio checked, so
   the browser posts nothing for that name), so a conflict persists and stays flagged until
   an admin picks a column.
4. A posted value that is neither `""` nor the id of one of the current columns is ignored
   for that row — tolerant parsing, matching `_student_ids_from_post`.
5. Rows are then applied by `services.set_allocation_assignments`, which **owns the
   optimistic guard end to end** (the view only forwards the posted tokens):
   * If the posted target already equals the row's current state, the row is a **no-op**:
     nothing is written and nothing is reported, *even if the current token differs from
     `-was`*. This matters because every assigned and unassigned row posts a value, so a
     guard keyed on "token moved" alone would make admin A's save warn about every row
     admin B touched — dozens of misleading "not overwritten" names for rows A never
     edited.
   * Otherwise, if the current token differs from the posted `-was`, someone moved that
     student since render: the row is **skipped** and collected into a report list.
   * A `student-<pk>` posted without a well-formed matching `-was` (absent, or not a valid
     token) counts as a mismatch — skipped and reported, never an unguarded write.
   * Surviving rows are written: target group `G` → `add_students_to_group(G, [student])`
     then `remove_students_from_group(other_column_group, [student])` for every other
     column the student is in; target `— none —` → `remove_students_from_group` for every
     column the student is in. Both helpers already call `recompute_enrollment`, so removing
     a student's only group on this course drops their group-sourced `Enrollment` exactly as
     the per-group picker does today, and adding one creates it.
   * **Memberships outside the rectangle of (server row set × current columns) are never
     read for writing and never touched** — a membership in another of the course's groups
     survives a save untouched.
6. Redirect back to the grid. If any rows were skipped, a `messages.warning` names them:
   "2 rows were changed by someone else and were not overwritten: Kowalski, Nowak."

```python
def set_allocation_assignments(allocation, assignments, *, added_by=None):
    """assignments: {student_id: (target_group_id_or_None, was_token)}.
    Applies the rectangle-scoped delta and returns the list of skipped student ids."""
```

Keeping the guard in the service (rather than half in the view) is what makes it
unit-testable without a request, and leaves exactly one place where the rule lives.

## Error handling

| Situation | Behaviour |
|---|---|
| Group saved with an allocation on a different course | `ValidationError` from `Group.save()`; `GroupForm.clean()` turns it into a field error |
| Allocation's course changed while groups are attached | `ValidationError` from `Allocation.save()` |
| Group edited whose allocation is archived | the archived allocation stays selected and attached; no silent detach |
| Allocation edited whose cohort is archived | the archived cohort stays attached |
| Both `allocation` and `new_allocation` supplied | form error, "choose an existing allocation or type a new name, not both" |
| `new_allocation` duplicates an existing name on that course (any case) | reuses the existing allocation |
| Two concurrent saves creating the same new allocation name | savepoint + `IntegrityError` catch re-fetches the winner's row; no 500 |
| Allocation deleted while a group points at it | `SET_NULL`; group and roster unaffected |
| Allocation archived | disappears from pickers (except its own attached groups) and the default list; groups and memberships untouched |
| CA creates an allocation on a course they do not own | `PermissionDenied`; no row created |
| CA opens an allocation on a course they do not own | 404 via `allocations_manageable_by` |
| Holder of `change_group` without `change_allocation` opens the grid | 404 from the scoped lookup |
| Teacher opens any allocation URL | 403 from `permission_required` |
| Malformed / forged `student-<pk>` value | row ignored; never a 500 |
| Missing or malformed `student-<pk>-was` | treated as a guard mismatch: row skipped and reported |
| Student posted who is not in the server's row set | ignored |
| Row's stored state changed since render, and the post would change it | row skipped, reported via `messages.warning` |
| Row's stored state changed since render, but the post matches it | no-op; not written, not reported |
| Column set changed since render | whole save aborted with a distinct message; nothing written |
| Conflict row saved without a choice | untouched, still flagged |
| Grid larger than `DATA_UPLOAD_MAX_NUMBER_FIELDS` | avoided by raising the setting to 5000; beyond that, Django's `TooManyFieldsSent` 400 stands |
| Concurrent identical add | `add_students_to_group`'s per-student savepoint already absorbs the unique violation |

## Testing

Per the repository's practice, each test below is falsified against the mutant named
beside it: the mutant must turn that test **red**, and the test is not trusted until it has
been seen to fail.

| # | Test | Mutant that must make it fail |
|---|---|---|
| 1 | a group whose allocation is on another course raises `ValidationError` | remove the course check from `Group.save()` |
| 2 | changing an allocation's course while groups are attached raises `ValidationError` | remove the guard from `Allocation.save()` |
| 3 | `unique(course, name)` rejects a duplicate allocation name on one course | drop the constraint |
| 4 | deleting an allocation nulls `Group.allocation` and keeps every membership | change `on_delete` to `CASCADE` |
| 5 | archiving an allocation leaves its groups and memberships intact, and `allocation_archive` toggles back | make archive one-way / detach groups |
| 6 | editing a group whose allocation is archived (changing only the name) leaves `allocation_id` unchanged | filter the `allocation` queryset on `archived=False` alone |
| 7 | editing an allocation whose attached cohort is archived keeps the cohort in the M2M | filter the `cohorts` queryset on `archived=False` alone |
| 8 | `GroupForm` reuses an existing allocation for a case-different new name | compare case-sensitively |
| 9 | `set_allocation_assignments` writes only inside (rows × columns): a membership in a non-column group of the same course survives | widen the removal to `group__course=allocation.course` |
| 10 | `— none —` removes the membership and drops the group-sourced `Enrollment` | bypass `recompute_enrollment` (call `GroupMembership.delete()` directly) |
| 11 | a student absent from the POST is untouched (the conflict case) | treat a missing key as `— none —` |
| 12 | the guard skips a row whose stored state moved since render, applies the others, and reports the skipped one | ignore the `-was` field |
| 13 | a row whose stored state moved but whose posted value already matches it is neither written nor reported | report on token mismatch alone |
| 14 | a `student-<pk>` posted with a missing/garbage `-was` is skipped, not written | treat an absent `-was` as "no prior state" and write |
| 15 | a save whose posted `columns` differs from the current columns writes nothing and reports the distinct message | drop the column-set check |
| 16 | a forged `student-<pk>` for a student outside the row set is ignored | build the row set from the POST keys instead of recomputing it |
| 17 | `allocation_assign` returns 404 for a CA on a course they do not own, 404 for a `change_group`-only holder, 403 for a teacher | scope with `Allocation.objects.all()` |
| 18 | `allocation_create` refuses (403, no row) when a CA posts a course they do not own | drop the `PermissionDenied` check |
| 19 | rows = cohort union ∪ already-assigned outsiders | drop the outsider union |
| 20 | the conflict row renders unchecked and flagged | classify a two-membership row as assigned |
| 21 | the "also in" note covers all three cases (other allocation, no allocation, archived column) | narrow it to `allocation__isnull=True` |
| 22 | the summary counts match the whole allocation, including with a cohort filter active | compute the summary from the visible rows |
| 23 | the tabs strip renders for a Teacher **without** the Allocations tab, and with it for a CA | hoist the tab outside the per-permission gate |
| 24 | e2e: with a cohort filter active, add-all ticks only the filtered students | make add-all iterate all items instead of visible ones |
| 25 | e2e: with a cohort filter active, **unchecking** add-all clears only the filtered students | clear all items regardless of `hidden` |
| 26 | e2e: add-all reaches `indeterminate` when one visible student is unticked, and is disabled when nothing is visible | derive its state from the whole list |
| 27 | e2e: assign two students to different groups in the grid, save, and see both rosters change | make `set_allocation_assignments` add to the target group but skip the removals, leaving a student in both rosters |

Test files follow the existing grouping layout (`tests/test_grouping_*.py`):
`tests/test_grouping_allocation_models.py`, `_forms.py`, `_service.py`, `_views.py`, plus
cases added to `tests/test_groups_tabs.py`. The e2e tests carry the `e2e` marker and run
under `pytest -m e2e`.

Every new user-facing string is wrapped in `{% trans %}` / `gettext_lazy`, and the Polish
catalogue (`locale/pl/LC_MESSAGES/django.po` plus the compiled `.mo`) is regenerated before
the PR.
