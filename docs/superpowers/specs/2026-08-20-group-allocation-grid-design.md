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
* No hard concurrency guarantee. The optimistic guard is advisory — see "Saving".

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

    def __str__(self):
        return self.name
```

`__str__` is not decoration: `Cohort`, `Group` and `Collection` all define one, and without
it `{{ allocation }}` in `allocation_confirm_delete.html` and any default `ModelChoiceField`
label render as `Allocation object (7)`.

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

`uniq_allocation_course_name` is a plain `UniqueConstraint` and is therefore
**case-sensitive**: it does not by itself prevent "Klasy" and "klasy" coexisting on one
course. Case-insensitive deduplication is a form-level rule (see "Forms"), and the
constraint's only job is to catch a genuine concurrent create of the identical name.

**Course scoping (the load-bearing invariant).** An allocation belongs to exactly one
course, and every group in it must belong to that same course. This is what makes "each
student belongs to at most one group here" a meaningful rule: if an allocation could span
courses, a student legitimately sitting in a maths group and a physics group would read as
a conflict, and the grid's central signal would be noise. Enforcement is at three Python
points:

* `Group.save()` raises `ValidationError` when `allocation_id` is set and the allocation's
  course differs from `self.course_id`. It reads that course id **without dereferencing the
  FK** —
  `Allocation.objects.filter(pk=self.allocation_id).values_list("course_id", flat=True).first()`
  — mirroring the `old_course_id` lookup shape already at `grouping/models.py:98-102`.
  Touching `self.allocation` instead would fetch the whole row on *every* `Group.save()`,
  including `services.set_group_archived`'s `save(update_fields=["archived"])`.
  `Group.save()` already freezes `course` after creation, so a group can never drift out of
  its allocation's course afterwards.
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
  `group_archive` does, so `?archived=1` plus that button is the un-archive path. An
  archived allocation's grid stays reachable and writable — archiving is a shelving
  gesture, not a lock.
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
    is nullable) are PA-only, as for groups. Includes archived rows; list views
    apply the active/archived filter on top."""
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

| URL | name | view | permission |
|---|---|---|---|
| `manage/allocations/` | `allocation_list` | `allocation_list` | `view_allocation` |
| `manage/allocations/new/` | `allocation_create` | `allocation_create` | `add_allocation` |
| `manage/allocations/<int:pk>/edit/` | `allocation_edit` | `allocation_edit` | `change_allocation` |
| `manage/allocations/<int:pk>/archive/` | `allocation_archive` | `allocation_archive` (toggles) | `change_allocation` |
| `manage/allocations/<int:pk>/delete/` | `allocation_delete` | `allocation_delete` | `delete_allocation` |
| `manage/allocations/<int:pk>/assign/` | `allocation_assign` | `allocation_assign` (GET + POST) | `change_group` |

Every view carries the repo's standard decorator stack, spelled out once here because the
error table's 403s depend on it — without `raise_exception=True` these would be 302
redirects to login, not 403s:

```python
@login_required
@permission_required("grouping.<perm>", raise_exception=True)
```

`allocation_archive` additionally carries `@require_POST`, exactly as `group_archive` does
(`grouping/views.py:252-254`).

Rows are scoped through `allocations_manageable_by`, following `group_list` /
`group_edit` / `group_archive` / `group_delete`.

**Create-time ownership: the form queryset is the gate, and there is deliberately no
`PermissionDenied` check.** `allocations_manageable_by` cannot cover creation, since there is
no row to scope yet. `group_create` handles its equivalent with an explicit
`raise PermissionDenied` after `is_valid()`, but that shape does not transfer here:
`AllocationForm` restricts `fields["course"].queryset` to `manageable_courses(user)`, so a CA
posting an unowned course pk fails `ModelChoiceField.to_python` with `invalid_choice`,
`form.is_valid()` is `False`, and the view re-renders — a `PermissionDenied` placed after
`is_valid()` would be unreachable dead code, and a test asserting 403 could never pass.

So the outcome for "a CA posts a course they do not own" is a **200 re-render with a field
error on `course`, and no row created**, and the queryset restriction is the live gate. This
is the one place this design deliberately diverges from `group_create` (whose `course` field
is unrestricted, and which therefore genuinely needs the check).

`allocation_list` shows non-archived allocations by default with the same `?archived=1`
toggle `group_list` uses, ordered `("course__title", "name")`. Each row shows the
allocation name (linking to its grid), the course, the attached cohort names, and the
count of non-archived groups; row actions are Edit, Archive/Un-archive, Delete. Those three
per-row lookups are an N+1 unless the queryset carries `select_related("course")`,
`prefetch_related("cohorts")`, and a `Count("groups", filter=Q(groups__archived=False))`
annotation — the same discipline this change also introduces on `group_list` (which has no
`select_related` today and is already an N+1 on `group.course`) and on the grid. It sets
`hub_tab = "allocations"` and includes `_groups_tabs.html`.

A successful `allocation_create` redirects to `allocation_edit` (matching `group_create`,
which redirects to `group_edit`); `allocation_edit` redirects to `allocation_list` (matching
`cohort_edit`).

`allocation_assign` is gated on **`grouping.change_group`** — it writes `GroupMembership`,
not `Allocation` — and additionally resolves the allocation through
`get_object_or_404(scoping.allocations_manageable_by(request.user), pk=pk)`. It also
includes `_groups_tabs.html` with `hub_tab = "allocations"`, and offers a back link to
`allocation_list` plus a link to `allocation_edit` (the empty states below need it).

### Forms

**`AllocationForm`** (`ModelForm`): fields `name`, `course`, `cohorts`, with `cohorts` as a
`CheckboxSelectMultiple`. `archived` is not a form field — archiving goes through the POST
view, matching how `CohortForm` keeps `archived` off the form. `course` is disabled once
the allocation has groups attached, mirroring `CollectionForm`.

It takes a `user` kwarg — `AllocationForm(..., user=request.user)`, the same shape
`CollectionForm(..., owner=request.user)` already uses at `grouping/views.py:340` — and
restricts `course` to `courses.access.manageable_courses(user)`. That helper already has
exactly the semantics wanted (PA unfiltered via the model-level `courses.change_course`
permission, CA filtered to owned courses). As set out above, this restriction **is** the
create-time gate — there is no separate `PermissionDenied` backstop, because it would be
unreachable behind it.

**`clean()`** — *not* `clean_name()` — enforces the case-insensitive rule that the data model
deliberately does not. It must be the cross-field hook: `BaseForm._clean_fields` iterates
`self.fields` in declaration order and `fields_for_model` preserves `Meta.fields` order, so a
`clean_name()` would run **before** `course` is cleaned, seeing `cleaned_data["course"]` as
`None` and (on a create) `self.instance.course_id` as `None` too — with no course to scope
the lookup to. `CollectionForm.clean()` already does its cross-field course check the same
way. The rule: a name matching an existing allocation on that course `iexact` (excluding
`self.instance.pk` on edit) raises `self.add_error("name", …)` — "an allocation with this
name already exists on this course" — keeping the error on the field the template renders.

**`clean()` must resolve the course defensively and bail when it cannot.** Django runs
`_clean_form()` even after a field has already failed, and `add_error` *deletes* the
offending key from `cleaned_data` — so in precisely the scenario this design nominates as
the create-time gate (a CA posting an unowned course pk, which fails
`ModelChoiceField.to_python` with `invalid_choice`) there is **no `"course"` key at all**. A
literal `cleaned_data["course"]` raises `KeyError` and turns the specified 200 re-render into
a 500. Resolve it as `cleaned_data.get("course") or self.instance.course_id`, and skip the
dedup lookup entirely when nothing resolves — a field error is already present, so there is
nothing useful to add. `CollectionForm.clean()`'s `course = cleaned.get("course")` /
`if course and groups:` is the shape to copy. **The same guard applies to `GroupForm.clean()`**,
whose course-equality check and `new_allocation` lookup read the same key.
Without it the primary UI can create "Klasy" and then "klasy" side by side, because
`uniq_allocation_course_name` is case-sensitive and would not object. This is the same rule
`GroupForm` applies to `new_allocation`, at the other entry point.

**Both dedup lookups span archived rows.** `uniq_allocation_course_name` carries no
`archived` condition, so an archived allocation still occupies its `(course, name)` slot.
Every *other* allocation queryset in this design is scoped `archived=False`, which makes
scoping these two the same way the obvious mistake — and an expensive one: `AllocationForm`
would accept a name an archived row already holds and hit the constraint in `save()`, where
there is no savepoint and no `except IntegrityError`, i.e. a 500. So:

* `AllocationForm.clean()` searches archived rows too, and reports "an archived allocation
  with this name already exists on this course — un-archive it to reuse the name" (the
  allocation list's `?archived=1` view is where that is done).
* `GroupForm.clean()` likewise searches archived rows, and a `new_allocation` matching one is
  a **field error on `new_allocation`** with the same message — never a silent resolve. The
  picker deliberately hides archived allocations, so silently attaching a group to one would
  leave the admin unable to see where the group went.

The `cohorts` queryset is `Cohort.objects.filter(Q(archived=False) |
Q(pk__in=self.instance.cohorts.values("pk"))).order_by("-is_default", "name")` when editing,
`archived=False` when creating (same ordering, for parity with `_cohort_choices()` in
`grouping/views.py`, since `Cohort` has no `Meta.ordering`).

The `pk__in` arm is load-bearing, and the mechanism is worth getting right because it is
*not* validation. `ModelMultipleChoiceField._check_values` **raises**
`ValidationError(code="invalid_choice")` for a posted pk outside its queryset — it does not
drop it silently. The silent loss happens one step earlier, in rendering:
`CheckboxSelectMultiple` never emits a checkbox for the excluded cohort, so the browser has
nothing to post back, and `save_m2m()` writes only what was posted. A plain `archived=False`
queryset would therefore strip an already-attached, later-archived cohort from the M2M on
the next unrelated save — emptying a whole section out of the grid, with a perfectly valid
form and no error anywhere. An attached archived cohort renders with an "(archived)" suffix.

The same distinction governs the `allocation` field below (via `ModelChoiceField.to_python`,
which raises `invalid_choice` likewise) and, importantly, how tests 6 and 7 must be written:
under the mutant the POST is *rejected*, so an assertion that only checks "the value is
unchanged" passes vacuously. Both tests must additionally assert that the save **succeeded**.

**`GroupForm`** gains an allocation control that satisfies "pick an existing value, or type
a new one". `allocation` joins `Meta.fields` (today
`["name", "course", "teachers", "external_id"]`) so the model field is form-managed and
rendered at all, and its queryset and `empty_label` are then tuned in `__init__`, exactly as
`teachers`' queryset already is. It is *not* `Meta.fields` that writes the value — `save()`
assigns `group.allocation` explicitly below — so removing it from `Meta.fields` is not a
targeted mutant but a crash: `self.fields["allocation"]` would `KeyError` in `__init__`.
`new_allocation` stays a declared non-model field, outside `Meta.fields`.

`GroupForm` also gains a **keyword-only `user=None`** parameter. It must default to `None`,
and a falsy `user` must yield `Allocation.objects.none()` for the choices (mirroring
`manageable_courses`'s unauthenticated branch, which would otherwise raise `AttributeError`
on `user.is_authenticated`). This is not hypothetical tidiness: `GroupForm` is constructed
with no kwargs at `tests/test_grouping_forms.py:17`, `:22`, `:61` and at
`integrations/tests/test_form_fields.py:40` — a different app — and all four must keep
passing untouched. The four in-view construction sites (`grouping/views.py:192`, `:207`,
`:227`, `:235`) pass `user=request.user`.

* `allocation` — a `ModelChoiceField` with an empty "— none —" choice. One conditional
  definition, so the field has exactly one queryset:

  ```python
  if self.instance.pk:          # editing: course is frozen, so scope to it
      base = Q(course=self.instance.course)
  elif user:                    # creating: every course the user may manage
      base = Q(course__in=manageable_courses(user))
  else:
      base = Q(pk__in=[])       # no user -> no choices
  qs = (Allocation.objects
        .filter((base & Q(archived=False)) | Q(pk=self.instance.allocation_id))
        .select_related("course")
        .order_by("course__title", "name"))
  ```

  The `select_related` and the ordering are not cosmetic: the iterator below reads
  `course.title` per option (an N+1 without it) and groups options into `<optgroup>`s, which
  needs a deterministic course-major order or one course can emit several separate groups.

  Both filter parts are load-bearing. Without the course scoping, every non-archived
  allocation on every course — names and course titles — is disclosed to any holder of
  `add_group`, including a CA who owns one course. Without the trailing `pk` arm, the
  currently-attached-but-archived allocation is never *rendered* as an option, so the browser
  posts no `allocation` value at all and `construct_instance` writes `None` — silently
  detaching the group on any unrelated save. (Note it is the missing option, not a validation
  rejection, that loses the value; a posted-but-out-of-queryset pk would raise
  `invalid_choice` instead.) The attached archived allocation renders with an "(archived)"
  suffix.
* `new_allocation` — `CharField(max_length=200, required=False)`, "or create a new
  allocation". The `max_length` matches `Allocation.name`; without it a longer value passes
  validation and fails at the database as a 500.

`clean()` rules:

* supplying both `allocation` and `new_allocation` is an error ("choose an existing
  allocation or type a new name, not both"), attached to `new_allocation` — but **only when
  the admin actually picked a different existing allocation**. On the edit form of a group
  that already has an allocation, `allocation` is a `Meta.fields` model field whose initial
  is that allocation, so the browser *always* posts it back; a naive "both are non-empty"
  test would make the natural way to move a group into a new allocation — type the new name
  — fail every time, blaming the admin for a selection they never touched. Stated exactly,
  with `new_allocation` non-empty:

  | posted `allocation` | outcome |
  |---|---|
  | empty / `None` (the select was explicitly cleared) | no conflict; the new name wins |
  | equal to `self.instance.allocation_id` (the untouched echo) | no conflict; the new name wins |
  | non-empty and different from `self.instance.allocation_id` | **conflict** — the error above |

  In *both* non-conflict cases `clean()` must then **set `cleaned_data["allocation"] = None`**.
  This is the mechanism, not a detail: without it `construct_instance` writes the echoed
  allocation and `save()`'s `self._resolved_allocation or self.cleaned_data.get("allocation")`
  fallback evaluates to the old allocation, so `if allocation is None and name:` never fires,
  the new allocation is never created, and the group silently stays where it was — behind a
  success redirect. (Equivalently, `save()` may resolve/create from `name` *before* consulting
  the fallback; pick one and be explicit.);
* the chosen or created allocation's course must equal the group's course — a field error
  on `allocation` ("this allocation belongs to a different course"), *not* a non-field
  error, because `group_form.html` renders errors per field explicitly and a non-field
  error would be invisible. This is the form-level counterpart of `Group.save()`'s
  `ValidationError`, and it is what stops that exception escaping `form.save()` as a 500;
* a `new_allocation` name is stripped and looked up `iexact` among that course's
  allocations, **archived rows included** (see above). A match on a non-archived row means
  `clean()` stashes that `Allocation` instance on the form (e.g. `self._resolved_allocation`)
  — it does not merely note that a match exists. This is what actually prevents the fork:
  `uniq_allocation_course_name` is case-sensitive, so a later `get_or_create(name="klasy")`
  beside an existing "Klasy" would create a second row without ever raising
  `IntegrityError`. A match on an archived row is a field error, as above.

`save()` uses the stashed instance when `clean()` found one. Only when it found none does
it create, and only there does the savepoint-and-retry idiom (as in
`services.add_students_to_group` and `services.enroll_self`) apply — its sole job is the
genuine concurrent-create race on an identical name:

`_resolved_allocation` is declared as a class attribute defaulting to `None`, so `save()`
cannot `AttributeError` when `clean()` never reached the stashing branch.

```python
def save(self, commit=True):
    course = self.cleaned_data["course"]
    name = (self.cleaned_data.get("new_allocation") or "").strip()
    # The picked-existing path must seed this too — otherwise the assignment
    # below overwrites construct_instance's value with None.
    allocation = self._resolved_allocation or self.cleaned_data.get("allocation")
    if allocation is None and name:
        try:
            with transaction.atomic():
                allocation = Allocation.objects.create(course=course, name=name)
        except IntegrityError:
            allocation = Allocation.objects.get(course=course, name=name)

    group = super().save(commit=False)
    group.allocation = allocation      # the resolved row, whichever path produced it
    group.save()
    self.save_m2m()
    return group
```

`GroupForm.save()` deliberately always commits (the two views call it plainly); `commit` is
accepted for signature compatibility and not honoured, unlike `CollectionForm.save`.

Two ways to get this wrong, both silent. Assigning `group.allocation` is easy to omit — the
resolve block would then compute an `Allocation` and do nothing with it, discarding every
`new_allocation` the admin types. And seeding `allocation` from `cleaned_data["allocation"]`
is equally load-bearing: `clean()` stashes `_resolved_allocation` **only** on the
`new_allocation` path, so without that fallback the picked-existing path leaves `allocation`
as `None` and the assignment *overwrites* the value `construct_instance` wrote — nulling the
group's allocation on every plain save. Each path is killed by a different mutant, and needs
its own test.

The "no silent detach" guarantee lives in the **queryset**, not here: the
`pk=self.instance.allocation_id` arm keeps the current allocation selectable, so the browser
always posts it back. A group whose `allocation` field is omitted from the POST entirely is
detached by `construct_instance` regardless — there is no `save()`-side preservation to test
for.

**Transaction boundary.** That inner `atomic()` is a savepoint around the allocation create
only. So that a failing group save cannot leave an orphan allocation behind, `group_create`
and `group_edit` wrap **their `form.save()` call** in `transaction.atomic()`.
`set_group_members` stays outside it, unchanged — it already manages its own atomic blocks
and per-student savepoints. (This is the boundary the corresponding test patches
`Group.save` to raise across.)

**Rendering the allocation select.** `ModelChoiceField` emits a flat `<option>` list, so
grouping by course is built explicitly, and it takes **two** cooperating pieces — a choices
tuple carries only a value and a label, so the iterator alone cannot produce the attribute
the filter needs:

* a `ModelChoiceIterator` subclass yielding
  `(course.title, [(value, self.field.label_from_instance(obj)), ...])` tuples, which
  Django's `Select` renders as `<optgroup>`s. Routing the label through
  `label_from_instance` is not incidental: that is the hook the "(archived)" suffix lives
  in, for **both** this field and `cohorts`. Yielding a bare `obj.name` would silently
  defeat the override — and defeat it asymmetrically, since `cohorts` keeps the stock
  iterator and would still show its suffix, so the implementer sees the mechanism working
  on one field while it is quietly absent on the other. The suffix is the whole point of
  keeping the archived row selectable: unmarked, it reads as an ordinary pickable
  allocation on a list that otherwise hides archived rows on purpose. It **must yield the empty choice
  `("", empty_label)` first, outside any optgroup** — the base
  `ModelChoiceIterator.__iter__` is what normally emits it, so a subclass that yields only
  optgroups silently drops "— none —" and leaves no way to detach a group from its
  allocation. The yielded value should be a `ModelChoiceIteratorValue` so the widget can
  recover the instance.

  **The iterator must be in place *before* the queryset is assigned.** `_set_queryset` ends
  with `self.widget.choices = self.choices`, and `self.choices` is `self.iterator(self)` —
  so the widget captures whichever iterator exists at assignment time. The natural `__init__`
  order (assign `queryset`, then set `field.iterator`) leaves the *widget* holding the base
  iterator: the rendered select is a flat option list with no `<optgroup>`s, while
  `form.fields["allocation"].choices` still looks correct because reading it re-invokes the
  new iterator. Declare the iterator as a class attribute on a `ModelChoiceField` subclass,
  or set `field.iterator = …` before `field.queryset = qs`.
* a `forms.Select` subclass overriding **`create_option`** to add
  `data-course="<course_pk>"` to each `<option>`'s attrs (reading the course id from the
  iterator value, or from a pk→course_id map the widget holds). Per-option attributes are
  only reachable here. Without this the options render without `data-course`, and
  `initAllocationFilter()` — filtering by course *and* resetting a stale selection — is
  silently inert.

  It must **skip the empty choice**: `Select.optgroups` calls `create_option` for that one
  too, passing a bare `""` rather than a `ModelChoiceIteratorValue`, so an unguarded
  `value.instance.course_id` raises `AttributeError` on every group-form render. Guard with
  `if not value:` (or `getattr(value, "instance", None) is None`) and emit no `data-course`
  for it — and the JS filter must never hide the empty option, since it is how a group is
  detached.

On the **create** form the course is chosen in the same submission, so the (already
user-scoped) allocations are rendered and filtered client-side to the selected course; the
server re-validates the course match regardless, so the filter is convenience, never the
gate. That filter is a small `initAllocationFilter()` function appended to
`grouping/static/grouping/js/roster_filter.js` (already loaded by `group_form.html`'s
`{% block extra_js %}`), keyed on `[data-allocation-select]` and the course select's value.
It is **invoked once from inside that file's IIFE, independently of `initRoster`** — the
file's only current entry point is `document.querySelectorAll("[data-roster]") → initRoster`,
and the allocation select sits outside every `[data-roster]` fieldset, so a function merely
appended to the file would never run. When the course select changes, the filter also
**resets the allocation select to "— none —" if the currently-selected option's
`data-course` no longer matches**, and hides whole `<optgroup>`s alongside their options —
otherwise a hidden-but-still-selected option posts a mismatched allocation and returns the
very field error the filter exists to prevent.
On the **edit** form `course` is already disabled, so the list is filtered server-side to
that one course and the script is inert.

### Templates and static files

New templates: `templates/grouping/allocation_list.html`, `allocation_form.html`,
`allocation_confirm_delete.html`, `allocation_assign.html`.

`templates/grouping/group_form.html` gains the allocation row plus, on a saved group with
an allocation, a link to that allocation's grid. `templates/grouping/group_list.html`
gains a muted allocation name per row, and `group_list`'s queryset gains
`select_related("course", "allocation")` so the extra column is not an N+1.

**Entry points.** Two, both gated on **`grouping.view_allocation`** — the same permission
`allocation_list` itself requires, so a visible link always leads somewhere the user can go.
(The seeded roles grant all four allocation permissions together, so this is equivalent
today; it is stated because gating a link on a *stronger* permission than its target is the
kind of silent mismatch the `cohort_list` / `view_cohort` split already had to explain.)

* a third tab in `templates/_groups_tabs.html` ("Allocations"), **nested inside** the
  strip's existing `{% if perms.grouping.view_group %}` wrapper — a Teacher holds
  `view_group` and must keep seeing the strip without the new tab.
  `tests/test_groups_tabs.py` already asserts strip composition and gains a case for this.
* an "Allocations" item in the Admin menu in `templates/base.html`, next to "Cohorts". That
  menu's outer `{% if %}` (at `templates/base.html:91`) currently tests four
  platform-admin-only permissions — `courses.change_subject`, `grouping.change_cohort`,
  `accounts.view_user`, `institution.change_institution` — none of which a Course Admin
  holds, so the menu renders for PA only. `or perms.grouping.view_allocation` must be
  added to that outer condition as well, or a Course Admin would hold the permission and
  still never see the menu. This edit has its own test.

New static files:

* `grouping/static/grouping/css/allocation_grid.css`, loaded via `{% block extra_css %}`
  (`templates/base.html:49`) — sticky header row, sticky name column, and the row-state
  treatments. Colours come from the existing surface/border tokens in
  `core/static/core/css/tokens.css`, with explicit dark-mode definitions; no raw hex.
  If the sticky first column is achieved by giving rows any explicit `display` (a grid or
  flex row layout being the usual way), that author rule outranks the UA's
  `[hidden] { display: none }` and filtered rows stay visible — so any such rule must be
  paired with an explicit `[hidden] { display: none !important }`. The filter e2e asserts
  `bounding_box()` is `None`, not merely that the attribute is present, so this cannot pass
  unnoticed.
* `grouping/static/grouping/js/allocation_grid.js`, loaded via `{% block extra_js %}` —
  live summary counts, row-state classes, and the row filters.

`grouping/static/grouping/js/roster_filter.js` is extended with the add-all control and the
allocation-select filter.

### The add-all checkbox

A checkbox rendered inside each roster fieldset's filter bar (`[data-roster-filter]`) and
found by its own hook `[data-roster-all]` rather than by position, labelled "Select all
shown", carrying **no `name` attribute** — like the existing filter
inputs, it must never post. Its wrapping `<label>` is rendered `hidden` and unhidden by the
script **unconditionally on init**, so with JS off it is invisible and the roster submits
exactly as it does today.

For that `hidden` to actually hide it, the wrapper must **not** carry an author `display`.
The filter bar's natural class, `.roster-filter__field`, is declared `display: flex` at
`core/static/core/css/app.css:210`, which outranks the UA's `[hidden] { display: none }` — so
with JS off the control would render visible and post nothing, silently breaking the
progressive-enhancement guarantee. Either give the wrapper its own class with no `display`,
or pair it with an explicit `[hidden] { display: none }` rule. A test asserts the no-JS state
by `bounding_box()`, not by the attribute's presence.

That "unconditionally" is worth stating, because the nearest-looking precedent does
something else: `[data-roster-count]` is unhidden by `applyFilter()`
(`shownEl.hidden = !filtering`), so it appears *only while a filter is active*. Copying that
treatment would make add-all invisible on a freshly loaded form — and every add-all test
applies a filter first, so nothing would catch it. Hence an explicit unfiltered-visibility
assertion in the test table.

* Checking it ticks every **visible** item; unchecking clears every **visible** item.
  Hidden items — those filtered out by the cohort select or the name search — are never
  read and never written. This is the whole point: "filter to Year 1, then add all" must
  not sweep in the rest of the school, and the *unchecking* direction matters more, because
  there a stray sweep silently removes students.
* Its state is recomputed by a new `syncAddAll()`, whose rules apply **in this order**:
  1. visible count is 0 → `disabled = true`, `checked = false`, `indeterminate = false`,
     return. (Stated as a precedence rule because "all visible items are ticked" is
     *vacuously true* of an empty set, so the tri-state rule alone would leave the box
     checked.)
  2. otherwise `disabled = false`, and: unchecked when no visible item is ticked, checked
     when all visible items are, `indeterminate` in between.

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
* every **student** (`student_users()` again — a staff user with a stray `GroupMembership`
  from a fixture, an import, or a post-hoc role change must not acquire a grid row) already
  in any of `allocation.groups.filter(course=allocation.course)`, *including archived ones*.
  The `course=` filter matches the one on `columns` in Rendering step 2, for the same
  reason: if a bulk-write path ever violates course scoping, an unfiltered arm would pull in
  a foreign-course group's students while the (course-filtered) membership query never
  fetches their memberships, so they would render as phantom "not placed" rows that no save
  can clear. The two derivations differ **only** on `archived`.

The second arm deliberately ignores `archived`. Restricting it to non-archived groups would
reintroduce exactly the invisibility it exists to prevent: a student outside the attached
cohorts, placed in a group that is later archived, would match neither arm and would vanish
from the screen while their membership survived — unseeable and unremovable from here. With
the arm widened, that student still gets a row; the archived group is not a column, so the
row reads as unassigned and the membership shows in the "also in" note.

The union **must be built by pk membership**, not `qs_a | qs_b`:

```python
def allocation_row_students(allocation):
    """The grid's row set. Called by BOTH the render path and the save path."""
    return User.objects.filter(
        Q(pk__in=by_cohort.values("pk")) | Q(pk__in=assigned.values("pk"))
    )
```

**This is a named helper for the same reason `columns` and the tokens are.** The row set is
the third axis on which render and save must agree, and a drift is silent by construction:
the save path's "student outside the recomputed row set" branch is the one place the design
deliberately says nothing to the user. If the save path rebuilt arm 2 with `archived=False`
— the natural slip, since every *other* allocation queryset here is `archived=False` — then
a student who is on the grid only through an archived allocation group would have their
posted assignment dropped with no message, no log, and nothing on screen. One helper, both
callers, arm 2 ignoring `archived` in both.

Note it deliberately carries **no** `select_related("cohort_membership__cohort")`: with the
cohort bucket resolved from the id map below, nothing in the render path ever dereferences
`user.cohort_membership`, so that hint would be dead weight rather than an N+1 fix.

`services.student_users()` ends in `.distinct()`, and OR-ing a distinct queryset with a
non-distinct one raises "Cannot combine a unique query with a non-unique query."
`scoping.collections_visible_to` carries an in-repo comment documenting exactly this trap
and this workaround; follow it.

Rows are grouped under a heading per attached cohort, ordered `-is_default, name`, with a
final "outside these cohorts" heading for the second arm's leftovers.

**A student may have no cohort at all, and reading it naively is a 500.**
`CohortMembership.user` is a `OneToOneField(related_name="cohort_membership")`
(`grouping/models.py:62-66`), so `user.cohort_membership` raises
`RelatedObjectDoesNotExist` in Python when the row is absent — it does not return `None`.
The obvious precedent is misleading: `group_form.html:40` dereferences it safely only
because Django's template engine silences `ObjectDoesNotExist`, and this bucketing happens
in Python. Such users are reachable — `student_users()` is defined by exclusion (every
non-staff user qualifies), the Default-cohort `post_save` receiver does not fire for
`bulk_create`, and it is documented as a no-op when no Default exists yet; "a fixture, an
import" is the second union arm's own stated justification.

So the cohort bucket is built from **one explicit id map** — not from `getattr`, and not
from the relation at all:

```python
cohort_of = dict(CohortMembership.objects
                 .filter(user_id__in=row_ids)
                 .values_list("user_id", "cohort_id"))
```

A student missing from it renders under "outside these cohorts" with `data-cohort=""`. The
attached `Cohort` objects are already in memory (they supply the headings and their slugs),
so `cohort_of` is the only lookup needed and the relation is never touched — which is why
the row queryset needs no `select_related` for it. A cohort with no
students renders its heading with an "(no students)" note rather than vanishing, so an
admin can see the cohort *is* attached; a heading whose rows are all hidden by a filter is
itself hidden by `allocation_grid.js`. Within a heading, students sort by
`polish_sort_key(user.sort_name)` then `username`, exactly as `group_detail` does.

Memberships needed for the row states and the "also in" notes are fetched in one query over
`GroupMembership.objects.filter(student_id__in=..., group__course=allocation.course)
.select_related("group")` and bucketed in Python — never per row.

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
`allocation_grid.js`. Its shape is deliberately **count-invariant** — rendered as
"Students: 84 · Assigned: 72 · Unassigned: 11 · Conflicts: 1", labels first, numbers last —
because Polish has three plural forms for cardinals (1 / 2–4 / 5+, with the teens
exception) and no amount of number substitution into a fixed noun fragment can be right for
all of them. `roster_filter.js`'s `data-saved-label="{% trans 'saved' %}"` precedent works
only because "saved" is count-invariant; this shape makes the same trick safe here.

Three further rules pin it down:

* It **always describes the whole allocation**, never the filtered subset: "who is still
  unplaced" is the number the admin came for, and a filter-sensitive count would hide
  exactly the students being looked for. Applying a filter must not change it.
* Live, it describes the **pending selection**, not the stored state: a checked radio counts
  as assigned, `— none —` as unassigned, and a row with nothing checked as a conflict. So
  picking a column on a conflict row moves it out of the conflict count immediately, before
  any save.
* Its **translated labels are rendered by the template as `data-*` attributes** on the
  summary element, and the script only substitutes numbers. A string composed in JavaScript
  cannot be wrapped in `{% trans %}` and would render English over the Polish page.

**Filters.** A name search and a cohort select that only *hide* rows (`hidden` attribute).
Each row carries `data-name` holding the lowercased display name used for its heading, and
the name filter matches **only that attribute** — never the row's `textContent`, which is
`roster_filter.js`'s fallback and here would also contain the "not placed" marker and the
"also in: 2B" note, so searching "2B" would match rows that merely mention 2B.
Every input stays in the DOM, mirroring the roster picker's rule, so a hidden row still
posts and is never silently rewritten — filtered-out rows must be hidden, never `disabled`,
since `disabled` inputs are dropped from the POST and the filter would then silently change
what the form submits. Each row carries `data-cohort="<cohort slug>"` and
the select's `<option value>` is that same slug — parity with `roster_filter.js`, which
already keys on `student.cohort_membership.cohort.slug`; a row in the "outside these
cohorts" section carries `data-cohort=""`. The select lists "All cohorts" (`value=""`), then
the allocation's **attached** cohorts in `-is_default, name` order (`value` = the cohort
slug), then an explicit "Outside these cohorts" option — without that last option the one
group an admin most often wants to inspect alone (the students who arrived from somewhere
else) could not be isolated.

That last option needs a **distinct non-empty sentinel**, `value="__none__"`, and its own
branch in the filter (`sentinel → row.dataset.cohort === ""`). Giving it `value=""` — the
literal reading of "matches `data-cohort=\"\"`" — would make it identical to "All cohorts"
under the `roster_filter.js`-style predicate `!cohort || row.dataset.cohort === cohort`, so
selecting it would show every row instead of isolating the outsiders.

Row-state classes follow the **same pending-selection rule as the summary**: when a radio
changes, the row's state class and its non-colour marker are recomputed from the checked
radio, so a conflict row that gets a column picked loses its red treatment and its warning
icon immediately, before any save.

**Empty states.** With no rows, the grid names the cause and the fix: "This allocation has
no cohorts attached" (linking to `allocation_edit`) when `cohorts` is empty, and "No
students in the attached cohorts yet" when cohorts are attached but yield nobody. With no
columns: "No groups belong to this allocation yet" (linking to `group_list`).

**Form size.** Each row posts two fields (the radio's single value plus the hidden token),
plus a small fixed overhead (CSRF token, the `columns` field, any query string — Django
counts GET, POST and FILES together). So a grid past roughly 500 students exceeds Django's
default `DATA_UPLOAD_MAX_NUMBER_FIELDS` of 1000 and 400s with `TooManyFieldsSent`, losing
every pending edit. No override exists in `config/settings/`; this change adds one to
`config/settings/base.py` — raised to 5000, with a comment naming this form as the reason —
which covers roughly 2400 students.

Without JavaScript the grid still works: native radios, server-rendered summary and row
states, and no filters.

## Data flow

### Rendering

1. Resolve the allocation through `allocations_manageable_by`.
2. `columns` = `allocation.groups.filter(course=allocation.course, archived=False)
   .order_by("name")`, resolved **once** and threaded through everything below. The
   redundant-looking `course=` filter is defence, not a fourth enforcement point: the
   course-scoping invariant is deliberately not enforced against bulk-write paths, and if it
   is ever violated the membership query below (which *is* course-filtered) would not fetch
   a foreign-course column's memberships — so every affected row would read as unassigned
   and every save would re-add. Deriving both sets the same way makes that incoherence
   impossible.
3. `rows` = the pk-membership union described above, each annotated with: the set of column
   group ids the student belongs to, the derived state, the "also in" group names, and a
   **state token**. The membership rows for all of this come from the single bucketed query
   described above.
4. The state token comes from `services.allocation_state_tokens(columns, student_ids,
   memberships=None)` — it takes the **already-resolved `columns` sequence**, not the
   allocation, so the column set is computed exactly once per request and lives in exactly
   one place (its sibling `allocation_columns_token(columns)` takes the same input): for
   each student, the ids of the column groups they belong to,
   **as ints, sorted numerically ascending, joined with `,`** — `""` for none, `"12"` for
   one, `"12,15"` for a conflict. Numeric (not lexical) ordering is chosen so the token is
   stable and human-readable in the DOM — `"9,10"`, never `"10,9"`; what actually keeps the
   two ends in step is that both go through this one helper.

   The optional `memberships` argument is `{student_id: set[int]}` — the student's
   `GroupMembership.group_id`s across **the whole course**, exactly as step 3 bucketed them
   — and the helper intersects it against `columns` itself. Passing it lets the render path
   avoid re-querying what step 3 just fetched; the save path omits it and lets the helper
   query. The shape matters because getting it wrong is a silent mis-token, not a crash:
   every row would read as unassigned and every save would be a guard mismatch. **A student
   id absent from the map means the empty set** (token `""`) — never a `KeyError`, never a
   fallback re-query. This is the grid's headline case, the unplaced student, who has no
   bucket at all: a plain-dict lookup would 500 the page and a re-query would silently
   reintroduce the N+1 the argument exists to avoid. The caller may pass a `defaultdict(set)`
   or the helper may use `.get(sid, set())`; either satisfies the rule.

   Both token strings obey one grammar: `^$|^\d+(,\d+)*$`, digits strictly ascending. That
   is what "non-conforming" means for the `columns` field below. For `-was` the malformed
   and merely-mismatched cases converge on the same outcome, so only the absent-versus-`""`
   distinction needs care there.
5. Each row renders a hidden `<input name="student-<pk>-was" value="<token>">` next to its
   radios. The form also renders one hidden `<input name="columns" value="...">` built by
   `services.allocation_columns_token(columns)` — the same canonical form (ints, numerically
   ascending, comma-joined) produced by one helper used at **both** render and save, so the
   two sides cannot disagree about sort discipline and abort every save spuriously.

### Saving

`allocation_assign` POST, wrapped in a single `transaction.atomic()`:

1. **Column-set check first.** Recompute the current columns and their token; if it differs
   from the posted `columns` field, abort the whole save, change nothing, and re-render. An
   **absent or non-conforming `columns` value aborts unconditionally** — it is never coerced
   to `""`, which would compare equal to the token of an allocation with no non-archived
   groups. Same sentinel discipline as `-was` below.
   Every row's token is computed *over the columns*, so a column archived between render and
   POST would otherwise shift every affected student's token at once and be reported as
   dozens of phantom "someone else changed this" rows. The re-render is built from **fresh
   server state** — fresh columns, fresh tokens, a fresh `columns` field — and the posted
   choices are discarded, because they were made against a column set that no longer exists
   and every `-was` in them is stale. The message says so plainly: "the allocation's groups
   changed while you were editing, so nothing was saved — please redo your changes."
2. Recompute the **server's own row set** — the request body is never trusted to define
   which students are editable. A posted `student-<pk>` for a student outside the recomputed
   row set is ignored, and deliberately *not* reported: that student is no longer in this
   screen's scope, so there is no row left to report against. (This is the one silent drop;
   the column axis aborts loudly and the row axis warns, both because there is still
   something on screen to attach the message to.)
3. For each row student, if `student-<pk>` is absent from the POST, the row is left
   untouched. This is exactly what an unresolved conflict row does (no radio checked, so
   the browser posts nothing for that name), so a conflict persists and stays flagged until
   an admin picks a column.
4. A posted value that is neither `""` nor the id of one of the current columns is ignored
   for that row — tolerant parsing, matching `_student_ids_from_post`. "Ignored" means
   **omitted from `assignments` entirely**, exactly as an absent key is; it must *not* be
   entered with a `None` target, which would silently unassign the student on forged or
   stale input — the same data loss the omission-versus-`None` rule exists to prevent.
5. Rows are then applied by `services.set_allocation_assignments`, which **owns the
   optimistic guard end to end** (the view only forwards the posted tokens). The three rules
   below are evaluated **in this order**, and the first that matches wins:
   * **No-op.** The row is a no-op iff `current_token == token_of(target)`, where
     `token_of(None) == ""` and `token_of(G) == str(G.pk)`. Nothing is written and nothing
     is reported — *even if the current token differs from `-was`, and even if `-was` was
     absent*. This ordering matters because every assigned and unassigned row posts a value,
     so a guard keyed on "token moved" alone would make admin A's save warn about every row
     admin B touched — dozens of misleading "not overwritten" names for rows A never edited.

     Comparing **whole tokens**, not membership, is equally load-bearing: a conflict row
     (`"12,15"`) posted with target 12 is **not** a no-op, because `"12,15" != "12"`. The
     sloppy reading — "the student is already in the target group, so there is nothing to
     do" — would leave group 15 in place and make conflicts permanently unresolvable through
     the very screen built to resolve them.
   * **Guard mismatch.** Otherwise, if the current token differs from the posted `-was`,
     someone moved that student since render: the row is **skipped** and collected into a
     report list. `was_token` is `None` when the `-was` field was absent or malformed, and
     `""` only for the legitimate "in no column group" token — the two must not collapse,
     since `""` is a valid state. `None` counts as a mismatch here: skipped and reported,
     never an unguarded write.
   * **Write.** Target group `G` → `add_students_to_group(G, [student])` **first**, then
     `remove_students_from_group(other_column_group, [student])` for every other column the
     student is in; target `— none —` → `remove_students_from_group` for every column the
     student is in. Both helpers already call `recompute_enrollment`, so removing a
     student's only group on this course drops their group-sourced `Enrollment` exactly as
     the per-group picker does today, and adding one creates it.

     **Add-before-remove is mandatory, not stylistic.** Removing first makes
     `recompute_enrollment` see `_is_reachable` as False for a student whose only membership
     on this course was the source column, so it *deletes* the group-sourced `Enrollment`;
     the following add then re-creates it and fires `notify_enrolled` again. Every ordinary
     move between two columns would emit a spurious "you were enrolled" notification and
     churn the `Enrollment` row. A test pins the order.
   * **Memberships outside the rectangle of (server row set × current columns) are never
     read for writing and never touched** — a membership in another of the course's groups
     survives a save untouched.
6. The view calls the service with **`added_by=request.user`**, which is forwarded to
   `add_students_to_group` so grid-created memberships record their actor exactly as
   `set_group_members` does from the per-group picker; without it they land with
   `added_by = NULL`.
7. Redirect back to the grid. If any rows were skipped, a `messages.warning` names them.
   The view resolves the returned ids to display names ordered by `polish_sort_key`, the
   same order the grid uses, and the message goes through `ngettext` on the row count:
   "1 row was changed by someone else and was not overwritten: Kowalski." /
   "2 rows were changed by someone else and were not overwritten: Kowalski, Nowak."

```python
def set_allocation_assignments(columns, assignments, *, added_by=None):
    """columns: the resolved column Group sequence, threaded in from the view.
    assignments: {student_id: (target_group_id_or_None, was_token_or_None)}.
    A row absent from the POST is OMITTED FROM THIS DICT ENTIRELY; within it,
    a target of None means "— none —". Applies the rectangle-scoped delta and
    returns the list of skipped student ids."""
```

The service takes the **resolved `columns`**, not the allocation — the view evaluates the
column set exactly once and threads that same sequence through the token check, step 4's
value validation, and this call. Handing it the `Allocation` instead would make it recompute
`allocation.groups.filter(archived=False)` independently, so a group archived between the
view's evaluation and the service's would have every affected row's `current_token` computed
over a column set the step-1 check never approved — reproducing exactly the phantom
"someone else changed this" storm that check exists to prevent.

**Omission versus `None` is the contract's sharpest edge.** `request.POST.get("student-7")`
returns `None` when the field is absent (an unresolved conflict row) and `""` when the
`— none —` radio is checked. Those must not be normalised together: build `assignments` over
the recomputed row set, **skip** any student whose key is absent, and map a posted `""` to a
target of `None`. Collapsing both to `None` mass-unassigns every conflict row on every save
— the precise data loss step 3 exists to prevent.

The service takes ids but **resolves them to instances once, up front** —
`User.objects.filter(pk__in=assignments)` into a dict, and the target group ids against the
recomputed column set — because `add_students_to_group` reaches `recompute_enrollment` →
`Enrollment.objects.get_or_create(student=...)` and `notify_enrolled(student, course)`,
both of which need a `User` instance and raise on a bare int.

Keeping the guard in the service (rather than half in the view) is what makes it
unit-testable without a request, and leaves exactly one place where the rule lives.

**One row can legitimately vanish after a save.** An out-of-cohort student — one who is on
the grid only through the second union arm — set to `— none —` matches neither arm on the
post-redirect render, so their row disappears. That is correct (they are no longer in this
screen's scope) but surprising enough to state, so it is not mistaken for a lost save.

**The guard is advisory, not a lock.** Under READ COMMITTED two concurrent saves can both
read the same tokens, both pass the guard, and both write; the guard narrows the race window
rather than closing it. Closing it would need `select_for_update()` over the affected
`GroupMembership` rows, which is deliberately not done here — the screen is admin-only and
low-contention, and the cost of a stray lost update is one re-edit, visible on the next
render.

## Error handling

| Situation | Behaviour |
|---|---|
| Group saved with an allocation on a different course | `ValidationError` from `Group.save()`; `GroupForm.clean()` turns it into a field error |
| Allocation's course changed while groups are attached | `ValidationError` from `Allocation.save()` |
| Group edited whose allocation is archived | the archived allocation stays selected and attached; no silent detach |
| Allocation edited whose cohort is archived | the archived cohort stays attached |
| Both `allocation` and `new_allocation` supplied | form error, "choose an existing allocation or type a new name, not both" |
| `new_allocation` duplicates an existing name on that course (any case) | `clean()` stashes and reuses that row; no second row, no `IntegrityError` |
| `AllocationForm` name duplicates an existing name on that course (any case) | field error on `name` from `clean()`; no row created |
| `AllocationForm` name duplicates an **archived** allocation's name on that course | field error naming the archived row and pointing at un-archiving; no 500 from the constraint |
| `new_allocation` matches an **archived** allocation on that course | field error on `new_allocation`; never a silent attach to a hidden allocation |
| `new_allocation` longer than 200 characters | field error from `max_length`; no row created |
| Two concurrent saves creating the same new allocation name | savepoint + `IntegrityError` catch re-fetches the winner's row; no 500 |
| Group save fails after a new allocation was created | the view's `transaction.atomic()` rolls both back; no orphan allocation |
| Allocation deleted while a group points at it | `SET_NULL`; group and roster unaffected |
| Allocation archived | disappears from pickers (except its own attached groups) and the default list; groups, memberships and grid access untouched |
| CA creates an allocation on a course they do not own | 200 re-render with an `invalid_choice` field error on `course`; no row created (the form queryset is the gate — no `PermissionDenied` is reachable) |
| CA opens an allocation on a course they do not own | 404 via `allocations_manageable_by` |
| Holder of `change_group` without `change_allocation` opens the grid | 404 from the scoped lookup |
| Teacher opens any allocation URL | 403 from `permission_required(..., raise_exception=True)` |
| Malformed / forged `student-<pk>` value | row ignored; never a 500 |
| Missing or malformed `student-<pk>-was`, where the post *would* change the row | `was_token = None`: row skipped and reported |
| Missing or malformed `student-<pk>-was`, where the post matches current state | no-op wins (it is checked first): not written, not reported |
| Missing or non-conforming `columns` field | abort, as for any mismatch; never coerced to `""` |
| Conflict row (`"12,15"`) posted with target 12 | not a no-op: 12 kept, 15 removed, conflict resolved |
| Student posted who is not in the server's row set | ignored, silently (no row left to report against) |
| Row's stored state changed since render, and the post would change it | row skipped, reported via `messages.warning` |
| Row's stored state changed since render, but the post matches it | no-op; not written, not reported |
| Column set changed since render | whole save aborted, nothing written, re-rendered from fresh state with a distinct message |
| Two saves racing the same row | advisory guard only; last writer may win (see "Saving") |
| Conflict row saved without a choice | untouched, still flagged |
| Grid larger than `DATA_UPLOAD_MAX_NUMBER_FIELDS` | avoided by raising the setting to 5000 in `config/settings/base.py`; beyond that, Django's `TooManyFieldsSent` 400 stands |
| Concurrent identical add | absorbed by `QuerySet.get_or_create`'s own internal `IntegrityError` retry inside `add_students_to_group`; the enclosing per-student savepoint's job is batch resilience, not swallowing — do not generalise it to other constraints |

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
| 6 | editing a group whose allocation is archived, POSTing the archived allocation's pk and a new name: the response is the **success redirect**, the rename landed, **and** `allocation_id` is unchanged. All three assertions are needed — under the mutant the POST is rejected as `invalid_choice`, so nothing saves and "unchanged" passes vacuously | filter the `allocation` queryset on `archived=False` alone |
| 7 | editing an allocation whose attached cohort is archived: `form.is_valid()` is **True** (or the view redirects) **and** the cohort survives in the M2M; equivalently, the archived cohort's pk is in `form.fields["cohorts"].queryset`. Same vacuity trap as row 6 | filter the `cohorts` queryset on `archived=False` alone |
| 8 | `GroupForm` reuses the existing allocation row for a case-different new name (asserting the pk, not just the count) | drop the stashed instance and let `save()` call `get_or_create(name=...)` |
| 8a | `AllocationForm` rejects a case-different duplicate name on the same course **on the create path** (where `instance.course_id` is `None`), and allows it on a different course | compare exactly instead of `iexact`; **and** move the check to `clean_name()`, where `course` is not yet cleaned — the create-path assertion is what makes the second mutant red |
| 8c | both entry points reject a name held by an **archived** allocation on that course, with no `IntegrityError` reaching the response | scope either dedup lookup to `archived=False` |
| 8b | **picked-existing path**: selecting an existing allocation writes it onto the group and does not null it | drop the `or self.cleaned_data.get("allocation")` fallback, so `save()` overwrites `construct_instance`'s value with `None`. (Dropping `allocation` from `Meta.fields` is *not* a usable mutant here — it `KeyError`s in `__init__` and reddens half the form suite) |
| 8b-ii | **typed-new path**: a `new_allocation` name writes the created/stashed row onto the group | drop the `group.allocation = allocation` assignment (kills only this path — on the picked path the fallback still carries the value) |
| 9 | `new_allocation` over 200 characters is a field error, not a 500 | omit `max_length` |
| 10 | with `Group.save` patched to raise inside the view's atomic block, a submitted new allocation name leaves no `Allocation` row | remove the view-level `transaction.atomic()` |
| 11 | `GroupForm`'s allocation choices exclude allocations on courses the user cannot manage. **Setup is load-bearing:** construct as `GroupForm(user=ca)` with **no `instance`** — that arm lives in the `elif user:` branch, so a test built on an existing group takes the `if self.instance.pk:` branch, which the mutant leaves intact | drop the `course__in=manageable_courses(user)` arm |
| 11d | `("", "— none —")` is among `form.fields["allocation"].choices`, and posting an empty `allocation` on an attached group sets `group.allocation` to `None` | have the custom iterator yield only optgroup tuples, dropping the empty choice |
| 11e | each rendered `<option>` carries `data-course` equal to its allocation's course pk, and options are nested in per-course `<optgroup>`s. **Assert against the rendered widget HTML, not `field.choices`** — a late-assigned iterator leaves `choices` correct while the widget renders flat | drop the `create_option` override (kills the attribute half); assign `field.iterator` *after* `field.queryset`, so the widget keeps the base iterator (kills the optgroup half) |
| 11h | rendering the group form with an allocation select does not raise: `create_option` skips the empty choice | drop the `if not value:` guard, so the bare `""` empty choice hits `value.instance.course_id` and `AttributeError`s |
| 11i | the attached **archived** allocation's rendered `<option>` label carries the "(archived)" suffix, and the archived cohort's checkbox label likewise | yield `obj.name` from the custom iterator instead of `self.field.label_from_instance(obj)` (kills the allocation half); drop the `label_from_instance` override (kills both) |
| 11f | typing a `new_allocation` on the **edit** form of a group that already has an allocation, **leaving the select at its echoed value**, succeeds and moves the group to a newly created allocation | test both non-empty values as a conflict regardless of the echo (kills the precedence rule); **and, separately,** omit `cleaned_data["allocation"] = None`, so the fallback resolves to the old allocation, the create branch never fires, and the group silently stays put behind a success redirect |
| 11g | the same, but with the select explicitly **cleared** to "— none —": also succeeds and moves the group | treat an empty `allocation` as "different from `instance.allocation_id`", making the clearest possible gesture a conflict error |
| 11a | `GroupForm()` with no `user` kwarg still constructs (the four existing call sites) and offers no allocation choices | make `user` required, or let a falsy user reach `manageable_courses` |
| 11b | a CA's `AllocationForm.fields["course"].queryset` excludes a course they do not own | drop the `manageable_courses(user)` restriction |
| 11c | posting a group whose allocation is on another course yields `form.is_valid() is False` with the error on `allocation`. **Setup is load-bearing:** the *create* path, as a Platform Admin (or a CA owning both courses), so the foreign allocation is genuinely inside the field queryset and only `clean()` can reject it — on the edit path, or for a single-course CA, `invalid_choice` rejects it anyway and the mutant survives | remove the course-equality check from `GroupForm.clean()` |
| 12 | `set_allocation_assignments` writes only inside (rows × columns): a membership in a non-column group of the same course survives, **and the intended in-rectangle write landed** (target column membership created, source column membership removed). **Setup is load-bearing:** the passed `was_token` must equal the student's current token, or the row is skipped, no removal of any kind runs, and the purely negative assertion holds under the mutant as well | widen the removal to `group__course=allocation.course` |
| 13 | `— none —` removes the membership and drops the group-sourced `Enrollment`. **Setup is load-bearing** (same trap as 16b): the starting membership must be created through `services.add_students_to_group`, or the `Enrollment` created explicitly with `source="group"` — `GroupMembershipFactory` creates no `Enrollment` at all, and `Enrollment.source` otherwise defaults to `"manual"`, which `recompute_enrollment` never deletes. Assert positively that the group-sourced `Enrollment` **exists before** the POST, or the "gone" assertion is true on every build | bypass `recompute_enrollment` (call `GroupMembership.delete()` directly) |
| 14 | a student absent from the POST is untouched (the conflict case). **Setup is load-bearing:** the POST must carry that row's `-was` equal to its true current token (`"12,15"`), or `was_token is None` skips the row and the mutant survives | treat a missing key as `— none —` |
| 15 | the guard skips a row whose stored state moved since render, applies the others, and reports the skipped one | ignore the `-was` field |
| 16 | a row whose stored state moved but whose posted value already matches it is neither written nor reported | report on token mismatch alone |
| 16a | a conflict row (`{12,15}`) posted with target 12 removes 15 and clears the conflict | treat `target_id in current_ids` as a no-op instead of comparing whole tokens |
| 16b | moving a student between two columns keeps their `Enrollment` pk and creates no second `ENROLLED` notification, **and the move actually landed** (member of the target column, no longer a member of the source). **Setup is doubly load-bearing:** (a) the passed `-was` must equal the student's true current token (`str(source.pk)`) — otherwise the guard skips the row, nothing is written, and both negative assertions hold on the mutant too; (b) the source membership must be created through `services.add_students_to_group` (or the `Enrollment` created explicitly with `source="group"`), because `Enrollment.source` defaults to `"manual"` and `EnrollmentFactory` does not set it — and `recompute_enrollment` only ever deletes a group-sourced row, so a `manual` fixture makes the swap invisible. Capture the pk before the save | swap the add and remove calls |
| 17 | a `student-<pk>` posted with a missing `-was` is skipped, not written. **Setup is load-bearing:** the student must currently be in *no* column group (current token `""`), and the post must target a real column — otherwise the mutant's `""` coincidentally mismatches the real token and skips too, leaving the test green | forward a missing `-was` as `""` instead of `None` |
| 17a | a row omitted from the POST entirely (conflict row) is not confused with `— none —`: its memberships survive. **Same load-bearing `-was`:** carry the row's true token (`"12,15"`) | normalise both `request.POST.get` outcomes (`None` and `""`) to a `None` target when building `assignments` |
| 17c | a row whose posted value is neither `""` nor a current column id (forged or stale) keeps its membership — it is omitted from `assignments`, not unassigned. **Setup is load-bearing:** student currently in column 12, POST `student-<pk>=9999` **with `-was="12"`** — without the matching `-was` the guard skips the row anyway and the mutant survives | map an out-of-range posted value to a `None` target |
| 17b | a membership created through the grid records `added_by` = the posting admin | drop `added_by=request.user` from the view's service call (and, separately, drop the forward to `add_students_to_group`) |
| 18 | a save whose posted `columns` differs from the current columns writes nothing, re-renders from fresh state, and reports the distinct message | drop the column-set check |
| 19 | a forged `student-<pk>` for a student outside the row set is ignored. **The forgery must carry a `student-<pk>-was` equal to that student's true current token** (typically `""`) — otherwise `was_token` is `None`, the guard skips the row even under the mutant, and nothing is written either way | build the row set from the POST keys instead of recomputing it |
| 20 | `allocation_assign` returns 404 for a CA on a course they do not own and 404 for a `change_group`-only holder | scope with `Allocation.objects.all()` |
| 20a | `allocation_assign` returns 403 — not a 302 to login — for a teacher | drop `raise_exception=True` |
| 21 | `allocation_create` refuses a course the CA does not own: 200, a field error on `course`, and **no `Allocation` row created** | drop the `manageable_courses(user)` restriction on `AllocationForm.course` — the row is then created and the test goes red (this asserts the POST outcome; 11b asserts the queryset contents) |
| 22 | `allocation_list` shows only allocations from `allocations_manageable_by`, and `?archived=1` flips the set | scope with `Allocation.objects.all()` |
| 23 | `allocation_delete` redirects and leaves memberships intact, through the view | make the view cascade-delete the groups |
| 24 | rows = cohort union ∪ already-assigned outsiders | drop the outsider union |
| 25 | a student outside the attached cohorts whose only membership is in an **archived** group of the allocation still gets a row | restrict the second union arm to `archived=False` |
| 25a | a placed student with **no `CohortMembership` row** renders under "outside these cohorts" with `data-cohort=""`, and the page returns 200. **Setup is load-bearing:** `signals.ensure_cohort_membership` fires `post_save` on every user create and inserts a Default-cohort row whenever a Default exists, so the fixture must *explicitly delete* the membership and assert `CohortMembership.objects.filter(user=s).exists() is False` before the GET. Without that, the student has a membership to a merely-unattached cohort — which also renders under "outside these cohorts" with `data-cohort=""` — so every assertion holds and the mutant's direct relation read never raises | read `user.cohort_membership.cohort` directly in Python instead of via the id map — `RelatedObjectDoesNotExist` 500s the page |
| 25b | rendering the grid issues a bounded number of queries (`assertNumQueries`), independent of the row count | drop the `memberships=` argument at the `allocation_state_tokens` call site, so the helper re-queries per student (and, separately, fetch each row's "also in" memberships individually instead of from the one bucketed query) |
| 25c | a student who is on the grid **only** through an archived allocation group can be assigned to a real column and the membership is written | scope the save path's second row-set arm to `archived=False`, so `allocation_row_students` disagrees between render and save and the post is silently dropped |
| 26 | the conflict row renders unchecked and flagged | classify a two-membership row as assigned |
| 27 | the "also in" note covers all three cases (other allocation, no allocation, archived column) | narrow it to `allocation__isnull=True` |
| 28 | on a plain GET the summary counts describe the whole allocation. **Fixture is load-bearing:** at least two attached cohorts *plus* one placed out-of-cohort student, asserting total = cohort A + cohort B + leftovers — with a single cohort, "the first heading" is every row and the mutant produces identical numbers | count only the rows under the first cohort heading |
| 29 | a Course Admin's `base.html` renders the Admin menu containing the Allocations link, asserted **inside the `.app-nav__admin` `[data-menu-panel]` markup** | leave `base.html`'s outer `{% if %}` condition unchanged |
| 30 | the tabs strip renders for a Teacher **without** the Allocations tab, asserted **inside the `nav.tnhub__tabs` markup** | hoist the tab outside the per-permission gate |
| 30b | the tabs strip renders **with** the Allocations tab for a CA, likewise scoped to `nav.tnhub__tabs` | omit the tab from `_groups_tabs.html` entirely |
| 30a | e2e: add-all is visible on a freshly loaded group form with **no filter applied** | unhide it from `applyFilter()` (the `[data-roster-count]` treatment) instead of unconditionally on init |
| 30c | e2e with JavaScript disabled: the add-all control's `bounding_box()` is `None` (not merely `hidden` present), and the roster still submits | put the control on `.roster-filter__field`, whose `display: flex` outranks the UA `[hidden]` rule |
| 31 | e2e: with a cohort filter active, add-all ticks only the filtered students | make add-all iterate all items instead of visible ones |
| 32 | e2e: with a cohort filter active, **unchecking** add-all clears only the filtered students | clear all items regardless of `hidden` |
| 33 | e2e: add-all is `indeterminate` when one visible student is unticked, and **unchecked and disabled** when nothing is visible | derive its state from the whole list (kills the first half); skip the zero-visible early return so the vacuous "all ticked" leaves it checked (kills the second) |
| 34 | e2e: after ticking add-all under a cohort filter, the "Added" counter shows the new live total | remove the explicit `updateSelected()` call from the add-all handler |
| 35 | e2e: applying the grid's cohort filter leaves the summary counts unchanged, and a filtered-out row's `bounding_box()` is `None` (not merely `hidden` present) | recompute the summary from non-hidden rows; separately, declare a `display` on rows without the `[hidden] { display: none !important }` pair |
| 35a | e2e: with a cohort filter active, saving leaves every hidden row's membership byte-identical, and the POST still carries their `student-<pk>` and `-was` fields | set `disabled` on filtered-out rows' inputs instead of only hiding the row |
| 35c | e2e: selecting "Outside these cohorts" hides every cohort-bucketed row and shows only the outside-section rows | give that option `value=""`, making it a duplicate of "All cohorts" that shows everything |
| 35d | e2e: the name search matches a student whose name contains the term, and does **not** match a row that merely carries that text in its "also in" note | match on the row's `textContent` instead of `data-name` |
| 35b | e2e (Polish locale): the live summary's labels stay Polish and grammatical after a radio change | compose the summary string from JavaScript literals instead of the `data-*` labels |
| 36 | e2e: picking a column on a conflict row moves it out of the conflict count **and clears the row's own red treatment and warning marker** before saving | update the summary only on load (kills the count half); leave the row's state class untouched on change (kills the marker half) |
| 37 | e2e: assign two students to different groups in the grid, save, and see both rosters change. **Fixture is load-bearing:** at least one student must already be in a *different* column group at render time, and the test must assert the old group **lost** them — starting from two unassigned students, the removal-skipping mutant produces an identical outcome and stays green | make `set_allocation_assignments` add to the target group but skip the removals, leaving a student in both rosters |
| 37a | e2e on the **create** group form: changing the course select hides the non-matching `<optgroup>`s and resets a now-stale allocation selection to "— none —" | omit the reset (a hidden-but-selected option then posts a mismatched allocation); separately, append `initAllocationFilter` to the file without invoking it from the IIFE, so it never runs |

Test files follow the existing grouping layout (`tests/test_grouping_*.py`):
`tests/test_grouping_allocation_models.py`, `_forms.py`, `_service.py`, `_views.py`, plus
cases added to `tests/test_groups_tabs.py`. The e2e tests carry the `e2e` marker and run
under `pytest -m e2e`.

Every new user-facing string is wrapped in `{% trans %}` / `gettext_lazy` — including the
grid summary's fragments, which reach `allocation_grid.js` as `data-*` attributes rather
than as JavaScript literals — and the Polish catalogue
(`locale/pl/LC_MESSAGES/django.po` plus the compiled `.mo`) is regenerated before the PR.
