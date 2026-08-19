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

Migration `grouping/0005_allocation.py` creates the model, the M2M table, the constraint,
and the nullable FK. It adds no data operation — nothing to backfill.

**Course scoping (the load-bearing invariant).** An allocation belongs to exactly one
course, and every group in it must belong to that same course. This is what makes "each
student belongs to at most one group here" a meaningful rule: if an allocation could span
courses, a student legitimately sitting in a maths group and a physics group would read as
a conflict, and the grid's central signal would be noise. Enforcement is in two places:

* `Group.save()` raises `ValidationError` when `allocation_id` is set and
  `allocation.course_id != self.course_id`. `Group.save()` already freezes `course` after
  creation, so a group can never drift out of its allocation's course afterwards.
* `GroupForm.clean()` surfaces the same rule as a field error rather than a 500.

**Lifecycle.**

* *Deleting* an allocation nulls `Group.allocation` (`SET_NULL`) and touches no
  membership. Groups and rosters survive; only the grouping label is gone.
* *Archiving* an allocation hides it from the group form's picker and from the default
  allocation list, and leaves groups and memberships **completely alone**. This is
  deliberately unlike `services.archive_cohort`, which reassigns members to the default
  cohort: a cohort is a student's single home and cannot be left dangling, whereas an
  allocation is only a label over groups that remain valid on their own.
* Archiving or deleting a *group* needs no allocation-specific handling: archived groups
  are excluded from the grid's columns by the same `archived=False` filter used elsewhere.

### Permissions and scoping

`institution/roles.py` gains `grouping.add_allocation`, `change_allocation`,
`delete_allocation`, `view_allocation` in both `GROUPING_COURSE_ADMIN_PERMS` and
`PLATFORM_ADMIN_PERMS`, mirroring the existing group permissions exactly. Teacher gets
none: teachers do not manage groups today, and the grid writes group membership.

`grouping/scoping.py` gains:

```python
def allocations_manageable_by(user):
    """Allocations a user may create/edit/delete. Mirrors groups_manageable_by:
    PA -> all; CA -> allocations on courses they own; else none. Owner-less
    courses (Course.owner is nullable) are PA-only, as for groups."""
```

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
| `manage/allocations/<int:pk>/archive/` | `allocation_archive` | `allocation_archive` (POST) |
| `manage/allocations/<int:pk>/delete/` | `allocation_delete` | `allocation_delete` |
| `manage/allocations/<int:pk>/assign/` | `allocation_assign` | `allocation_assign` (GET + POST) |

CRUD views are gated with `permission_required("grouping.<verb>_allocation")` and scoped
through `allocations_manageable_by`, following `group_list` / `group_create` /
`group_edit` / `group_archive` / `group_delete` line for line. `allocation_list` shows
non-archived allocations by default with the same `?archived=1` toggle `group_list` uses.

`allocation_assign` is gated on **`grouping.change_group`** — it writes
`GroupMembership`, not `Allocation` — and additionally resolves the allocation through
`get_object_or_404(scoping.allocations_manageable_by(request.user), pk=pk)`.

### Forms

`AllocationForm` (`ModelForm`): fields `name`, `course`, `cohorts`, with `cohorts` as a
`CheckboxSelectMultiple` limited to `Cohort.objects.filter(archived=False)`. `archived` is
not a form field — archiving goes through the POST view, matching how `CohortForm` keeps
`archived` off the form. `course` is disabled once the allocation has groups attached,
mirroring `CollectionForm`'s treatment of the same situation.

`GroupForm` gains an allocation control that satisfies "pick an existing value, or type a
new one":

* `allocation` — a `ModelChoiceField` over non-archived allocations, rendered as one
  `<optgroup>` per course, with an empty "— none —" choice.
* `new_allocation` — a plain `CharField(required=False)`, "or create a new allocation".

`clean()` rules: supplying both is an error ("choose an existing allocation or type a new
name, not both"); a `new_allocation` name is stripped and matched case-insensitively
against existing allocations on that course so the same name cannot fork into two rows;
the chosen or created allocation's course must equal the group's course.

`save()` resolves `new_allocation` through `Allocation.objects.get_or_create(course=...,
name=...)` inside the same transaction as the group save.

On the **create** form the course is chosen in the same submission, so all non-archived
allocations are rendered (grouped by course) and filtered client-side to the selected
course by a small script; the server re-validates the course match regardless, so the
client-side filter is convenience, never the gate. On the **edit** form `course` is
already disabled, so the list is filtered server-side to that one course.

### Templates and static files

New templates: `templates/grouping/allocation_list.html`,
`allocation_form.html`, `allocation_confirm_delete.html`, `allocation_assign.html`.

`templates/grouping/group_form.html` gains the allocation row plus, on a saved group with
an allocation, a link to that allocation's grid. `templates/grouping/group_list.html`
gains a muted allocation name per row.

**Entry points.** Two, both permission-gated on `grouping.change_allocation`:

* a third tab in `templates/_groups_tabs.html` ("Allocations", `hub_tab == "allocations"`);
* an "Allocations" item in the Admin menu in `templates/base.html`, next to "Cohorts".
  The menu's outer `{% if %}` currently tests four platform-admin-only permissions, so it
  renders for PA only; `or perms.grouping.change_allocation` must be added to that outer
  condition as well, or a Course Admin would hold the permission and still never see the
  menu.

New static files:

* `grouping/static/grouping/css/allocation_grid.css`, loaded via `{% block extra_css %}`
  (defined in `templates/base.html:49`) — sticky header row and sticky name column, and
  the row-state colours.
* `grouping/static/grouping/js/allocation_grid.js`, loaded via `{% block extra_js %}` —
  live summary counts, row-state classes, and the row filters.

`grouping/static/grouping/js/roster_filter.js` is extended with the add-all control.

### The add-all checkbox

A checkbox rendered in each roster fieldset's filter bar
(`[data-roster-filter]`), labelled "Select all shown".

* Checking it ticks every **visible** item; unchecking clears every **visible** item.
  Hidden items — those filtered out by the cohort select or the name search — are never
  read and never written. This is the whole point: "filter to Year 1, then add all" must
  not sweep in the rest of the school.
* Its own state is derived after every change and after every filter change: unchecked
  when no visible item is ticked, checked when all are, and `indeterminate` in between.
* With zero visible items it is unchecked and disabled.
* It updates the existing "Added" counter through the same `updateSelected()` path, so the
  saved-baseline hint keeps working.

`roster_filter.js` initialises every `[data-roster]` fieldset generically, so the teachers
fieldset gets an add-all too. That is intended: special-casing it out would be more code
than leaving it, and it is harmless on a short list.

Progressive enhancement is preserved — with JS off the checkbox is absent (it is rendered
by the template but inert without the script, so it is rendered `hidden` and unhidden by
the script on init) and the roster submits exactly as it does today.

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
would strand a membership the admin cannot see or undo from this screen). Rows are grouped
under a heading per attached cohort, ordered `-is_default, name`, with a final "outside
these cohorts" heading for the second set's leftovers. Within a heading, students sort by
`polish_sort_key(user.sort_name)` then `username`, exactly as `group_detail` does.

**Cells.** One radio group per student row, `name="student-<pk>"`, one radio per column;
the `— none —` radio carries `value=""`. Radios make double assignment impossible by
construction, which is the feature's stated goal.

**Row states.**

| State | Condition | Treatment |
|---|---|---|
| assigned | exactly one membership among the columns | normal row; that column's radio checked |
| unassigned | no membership among the columns | amber row; `— none —` checked |
| conflict | two or more memberships among the columns (pre-existing data) | red row, **no radio checked**, warning icon |

Independently of the above, a row shows a muted "also in: 2B" note listing the student's
memberships in groups of **this course** that are not columns — i.e. groups in another
allocation, groups with no allocation, and archived groups of this allocation. One rule
covers all three cases.

**Summary.** A header line — "84 students · 72 assigned · 11 unassigned · 1 conflict" —
rendered server-side from the same computed row states and updated live by
`allocation_grid.js` as radios change.

**Filters.** A name search and a cohort select that only *hide* rows (`hidden` attribute).
Every input stays in the DOM, mirroring the roster picker's rule, so a hidden row still
posts and is never silently rewritten.

Without JavaScript the grid still works: native radios, server-rendered summary and row
states, and no filters.

## Data flow

### Rendering

1. Resolve the allocation through `allocations_manageable_by`.
2. `columns` = `allocation.groups.filter(archived=False).order_by("name")`.
3. `rows` = the union described above, each annotated with: the set of column group ids the
   student belongs to, the derived state, the "also in" group names, and a **state token**.
4. The state token is produced by `services.allocation_state_tokens(allocation,
   student_ids)`: for each student, the ids of the column groups they belong to, sorted
   ascending and joined with `,` — `""` for none, `"12"` for one, `"12,15"` for a conflict.
   One helper, called at render and again at save, so the two can never drift.
5. Each row renders a hidden `<input name="student-<pk>-was" value="<token>">` next to its
   radios.

### Saving

`allocation_assign` POST, wrapped in a single `transaction.atomic()`:

1. Recompute `columns` and the **server's own row set** — the request body is never
   trusted to define which students are editable. A posted `student-<pk>` for a student
   outside the recomputed row set is ignored.
2. For each row student, if `student-<pk>` is absent from the POST, the row is left
   untouched. This is exactly what an unresolved conflict row does (no radio checked, so
   the browser posts nothing for that name), so a conflict persists and stays flagged until
   an admin picks a column.
3. A posted value that is neither `""` nor the id of one of the current columns is ignored
   for that row — tolerant parsing, matching `_student_ids_from_post`.
4. **Optimistic guard.** Recompute the current token for the student and compare it with
   the posted `student-<pk>-was`. If they differ, another admin has moved that student
   since the page was rendered: the row is **skipped** and collected into a report list.
5. Surviving rows are applied by `services.set_allocation_assignments`:
   * target group `G` — `add_students_to_group(G, [student])`, then
     `remove_students_from_group(other_column_group, [student])` for every other column the
     student is in;
   * target `— none —` — `remove_students_from_group` for every column the student is in.
   Both helpers already call `recompute_enrollment`, so removing a student's only group on
   this course drops their group-sourced `Enrollment` exactly as the per-group picker does
   today, and adding one creates it.
   **Memberships outside the rectangle of (server row set × current columns) are never
   read for writing and never touched** — a membership in another of the course's groups
   survives a save untouched.
6. Redirect back to the grid. If any rows were skipped, a `messages.warning` names them:
   "2 rows were changed by someone else and were not overwritten: Kowalski, Nowak."

`services.set_allocation_assignments(allocation, assignments, *, added_by=None)` takes
`{student_id: (target_group_id_or_None, was_token)}` and returns the list of skipped
student ids, so the guard is unit-testable without a request.

## Error handling

| Situation | Behaviour |
|---|---|
| Group saved with an allocation on a different course | `ValidationError` from `Group.save()`; `GroupForm.clean()` turns it into a field error |
| Both `allocation` and `new_allocation` supplied | form error, "choose an existing allocation or type a new name, not both" |
| `new_allocation` duplicates an existing name on that course (any case) | reuses the existing allocation; never creates a second row (the DB constraint is the backstop) |
| Allocation deleted while a group points at it | `SET_NULL`; group and roster unaffected |
| Allocation archived | disappears from pickers and the default list; groups and memberships untouched |
| CA opens an allocation on a course they do not own | 404 via `allocations_manageable_by`, matching the group views |
| Teacher opens any allocation URL | 403 from `permission_required` (no allocation permissions) |
| Malformed / forged `student-<pk>` value | row ignored; never a 500 |
| Student posted who is not in the server's row set | ignored |
| Row's stored state changed since render | row skipped, reported via `messages.warning` |
| Conflict row saved without a choice | untouched, still flagged |
| Concurrent identical add | `add_students_to_group`'s per-student savepoint already absorbs the unique violation |

## Testing

Per the repository's practice, each test below is falsified against the mutant named
beside it: the mutant must turn that test **red**, and the test is not trusted until it
has been seen to fail.

| # | Test | Mutant that must make it fail |
|---|---|---|
| 1 | a group whose allocation is on another course raises `ValidationError` | remove the course check from `Group.save()` |
| 2 | `unique(course, name)` rejects a duplicate allocation name on one course | drop the constraint |
| 3 | deleting an allocation nulls `Group.allocation` and keeps every membership | change `on_delete` to `CASCADE` |
| 4 | archiving an allocation leaves its groups and memberships intact | make archive reassign or detach groups |
| 5 | `set_allocation_assignments` writes only inside (rows × columns): a membership in a non-column group of the same course survives | widen the removal to `group__course=allocation.course` |
| 6 | `— none —` removes the membership and drops the group-sourced `Enrollment` | skip the `recompute_enrollment` path (call `GroupMembership.delete()` directly) |
| 7 | a student absent from the POST is untouched (the conflict case) | treat a missing key as `— none —` |
| 8 | the optimistic guard skips a row whose stored state moved since render, applies the others, and reports the skipped one | ignore the `-was` field |
| 9 | a forged `student-<pk>` for a student outside the row set is ignored | build the row set from the POST keys instead of recomputing it |
| 10 | `allocation_assign` returns 404 for a CA on a course they do not own, 403 for a teacher | scope with `Allocation.objects.all()` |
| 11 | rows = cohort union ∪ already-assigned outsiders | drop the outsider union |
| 12 | the three row states and the "also in" note render, and the summary counts match | classify a two-membership row as assigned |
| 13 | `GroupForm` reuses an existing allocation for a case-different new name | compare case-sensitively |
| 14 | e2e: with a cohort filter active, add-all ticks only the filtered students and leaves the rest unticked | make add-all iterate all items instead of visible ones |
| 15 | e2e: add-all reaches `indeterminate` when one visible student is unticked | derive its state from the whole list |
| 16 | e2e: assign two students to different groups in the grid, save, and see both rosters change | — |

Test placement follows the repo layout: `tests/test_allocation_*.py` for model, service,
form and view tests; the e2e tests carry the `e2e` marker and run under `pytest -m e2e`.

`polib`-visible strings: every new user-facing string is wrapped in `{% trans %}` /
`gettext_lazy`, and the Polish catalogue (`locale/pl/LC_MESSAGES/django.po` plus the
compiled `.mo`) is regenerated before the PR.
