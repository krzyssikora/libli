# Group Allocations and the Assignment Grid — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `Allocation` — a named label over a course's groups — plus a students × groups assignment grid that makes unplaced and double-placed students visible at a glance, and an "add all" checkbox for the existing roster picker.

**Architecture:** A new `grouping.Allocation` model with a nullable `Group.allocation` FK, course-scoped so "each student in at most one group here" is a real invariant. A new `allocation_assign` view renders one form of radio groups (students down the side, the allocation's non-archived groups across the top) and saves the whole grid through a single service that owns an optimistic per-row guard. Client-side JS only filters, counts, and syncs state; every behaviour degrades to working server-rendered HTML.

**Tech Stack:** Django 5.2 (server-rendered templates, no SPA), PostgreSQL, pytest + pytest-django + factory_boy, Playwright for e2e, plain ES5-style IIFE JavaScript, token-driven CSS.

**Spec:** `docs/superpowers/specs/2026-08-20-group-allocation-grid-design.md` — read it alongside this plan. Every "why" lives there; this plan is the "how". Where a step says *"see spec §X"*, read that section before writing the code.

## Global Constraints

- **Worktree:** all work happens in `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/group-allocation-grid`, branch `pipeline/group-allocation-grid` (based on `origin/master`). Never operate in the main checkout.
- **Naming:** the concept is **allocation**. `Collection` and "band" are already taken by unrelated features and must not be reused.
- **Start the test database before any pytest run:** `docker compose -f docker-compose.test.yml up -d` — otherwise the first run looks hung for minutes.
- **Test commands:** `uv run pytest <paths> -v` (ruff/pytest/python are not on PATH). E2E tests need `-m e2e` explicitly or they are silently deselected (exit 5).
- **Never run the whole suite as a task step** — run only the files the task touches. A whole-repo sweep is a branch-level gate, not a per-task one.
- **Falsify every test:** after a test passes, apply the mutant named in its step, re-run, and confirm **RED**, then revert the mutant **by hand** (never `git checkout` — that destroys the surrounding work). A test that has not been seen to fail is not trusted.
- **Migration number:** derived from the graph head at implementation time. `0004_group_external_id` is the head today.
- **i18n:** every user-facing string goes through `{% trans %}` / `gettext_lazy`. The Polish catalogue is regenerated once, in Task 10.
- **Permissions do not reach an existing database by themselves:** `seed_roles()` runs only from `python manage.py setup_roles`. The test suite calls it via `tests/factories.py`, so no test can catch a missing run. Task 10 records it in the PR body.
- **Line length / lint:** `uv run ruff check --no-cache .` and `uv run ruff format --check .` are separate gates; both must pass in Task 10.

---

### Task 1: The `Allocation` model, the `Group.allocation` FK, and their guards

**Files:**
- Modify: `grouping/models.py` (add `Allocation`; add `Group.allocation`; extend `Group.save`)
- Create: `grouping/migrations/0005_allocation.py` (generated)
- Modify: `tests/factories.py` (add `AllocationFactory`, re-export it)
- Test: `tests/test_grouping_allocation_models.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `grouping.models.Allocation(name, course, cohorts, archived, created)` with `__str__` returning `self.name`; `Group.allocation` (nullable FK, `related_name="groups"`, `on_delete=SET_NULL`); `tests.factories.AllocationFactory`.

- [ ] **Step 1: Write the failing model tests**

Create `tests/test_grouping_allocation_models.py`:

```python
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from grouping.models import Allocation
from grouping.models import Group
from grouping.models import GroupMembership
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory

pytestmark = pytest.mark.django_db


def test_allocation_str_is_its_name():
    a = AllocationFactory(name="matematyka 2026")
    assert str(a) == "matematyka 2026"


def test_group_rejects_allocation_from_another_course():
    """Spec: the course-scoping invariant, enforced in Group.save."""
    group = GroupFactory()
    foreign = AllocationFactory(course=CourseFactory())
    group.allocation = foreign
    with pytest.raises(ValidationError):
        group.save()


def test_group_accepts_allocation_on_its_own_course():
    group = GroupFactory()
    a = AllocationFactory(course=group.course)
    group.allocation = a
    group.save()
    group.refresh_from_db()
    assert group.allocation_id == a.pk


def test_allocation_course_frozen_once_groups_attached():
    a = AllocationFactory()
    GroupFactory(course=a.course, allocation=a)
    a.course = CourseFactory()
    with pytest.raises(ValidationError):
        a.save()


def test_allocation_course_editable_while_no_groups_attached():
    a = AllocationFactory()
    other = CourseFactory()
    a.course = other
    a.save()
    a.refresh_from_db()
    assert a.course_id == other.pk


def test_allocation_name_unique_per_course():
    a = AllocationFactory(name="Klasy")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Allocation.objects.create(course=a.course, name="Klasy")


def test_the_constraint_is_case_sensitive_so_the_form_must_dedup():
    """Pins WHY AllocationForm.clean() does an iexact lookup: the DB constraint
    does not catch "klasy" beside "Klasy"."""
    a = AllocationFactory(name="Klasy")
    other = Allocation.objects.create(course=a.course, name="klasy")
    assert other.pk != a.pk


def test_allocation_name_may_repeat_across_courses():
    a = AllocationFactory(name="Klasy")
    other = Allocation.objects.create(course=CourseFactory(), name="Klasy")
    assert other.pk != a.pk


def test_deleting_allocation_nulls_the_fk_and_keeps_memberships():
    a = AllocationFactory()
    group = GroupFactory(course=a.course, allocation=a)
    GroupMembershipFactory(group=group)
    a.delete()
    group.refresh_from_db()
    assert group.allocation_id is None
    assert Group.objects.filter(pk=group.pk).exists()
    assert GroupMembership.objects.filter(group=group).count() == 1


def test_archiving_allocation_leaves_groups_and_memberships_alone():
    a = AllocationFactory()
    group = GroupFactory(course=a.course, allocation=a)
    GroupMembershipFactory(group=group)
    a.archived = True
    a.save(update_fields=["archived"])
    group.refresh_from_db()
    assert group.allocation_id == a.pk
    assert group.archived is False
    assert GroupMembership.objects.filter(group=group).count() == 1
```

- [ ] **Step 2: Run the tests and watch them fail**

```
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_grouping_allocation_models.py -v
```

Expected: collection error — `cannot import name 'Allocation' from 'grouping.models'`.

- [ ] **Step 3: Add the model and the FK**

In `grouping/models.py`, add after `Group`/`GroupMembership` (before `Collection`):

```python
class Allocation(models.Model):
    """A named grouping of one course's groups that together are meant to
    partition one or more cohorts — e.g. "matematyka, starting 2026". See
    docs/superpowers/specs/2026-08-20-group-allocation-grid-design.md."""

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

    def save(self, *args, **kwargs):
        # Mirror-image of Group.save's guard: an allocation's course may not
        # change once groups are attached, or those groups would silently sit
        # in an allocation on a different course. The form's `disabled` widget
        # is not enough — it is not a model-layer guarantee.
        if self.pk is not None:
            old_course_id = (
                Allocation.objects.filter(pk=self.pk)
                .values_list("course_id", flat=True)
                .first()
            )
            if (
                old_course_id is not None
                and old_course_id != self.course_id
                and self.groups.exists()
            ):
                raise ValidationError(
                    _(
                        "An allocation's course cannot be changed"
                        " once groups are attached."
                    )
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
```

Note `Allocation` must be defined **before** `Group` references it by class, or use the string form `"Allocation"` in the FK. Simplest: declare the FK with the string reference so declaration order does not matter.

Add to `Group`:

```python
    allocation = models.ForeignKey(
        "Allocation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="groups",
    )
```

Extend `Group.save`, immediately before the existing `super().save(...)` call:

```python
        # The allocation must be on this group's own course (spec: course
        # scoping). Read the course id WITHOUT dereferencing the FK — touching
        # self.allocation would fetch the row on every Group.save(), including
        # services.set_group_archived's save(update_fields=["archived"]).
        if self.allocation_id is not None:
            alloc_course_id = (
                Allocation.objects.filter(pk=self.allocation_id)
                .values_list("course_id", flat=True)
                .first()
            )
            if alloc_course_id is not None and alloc_course_id != self.course_id:
                raise ValidationError(
                    _("The allocation must belong to the same course as the group.")
                )
```

- [ ] **Step 4: Add the factory**

In `tests/factories.py`, next to `GroupFactory`:

```python
class AllocationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Allocation

    name = factory.Sequence(lambda n: f"Allocation {n}")
    course = factory.SubFactory(CourseFactory)
```

and add `from grouping.models import Allocation` to the imports at the top.

- [ ] **Step 5: Generate the migration**

```
uv run python manage.py makemigrations grouping --name allocation
```

`--name` is not cosmetic: Django derives an auto-name by concatenating each operation's
`migration_name_fragment` (`Migration.suggest_name`), and this migration carries several
operations — the autodetector splits every relational field out of `CreateModel` —
so the auto-name would be something like `0005_allocation_allocation_course_and_more.py`,
not `0005_allocation.py`. Every later reference in this plan (Step 8's `git add`, mutants 4
and 5) uses the fixed name, so pin it here.

Expected: creates `grouping/migrations/0005_allocation.py`. It will carry roughly five
operations — `CreateModel(Allocation)`, `AddField(allocation.course)`,
`AddField(allocation.cohorts)`, `AddField(group.allocation)`, and
`AddConstraint(uniq_allocation_course_name)` — because the autodetector splits relational
fields out of `CreateModel`. That is correct; check only that there are no operations
touching *other* models. If the number is not `0005`, use whatever the graph head produced and substitute it everywhere below.

- [ ] **Step 6: Run the tests and watch them pass**

```
uv run pytest tests/test_grouping_allocation_models.py -v
```

Expected: 10 passed.

- [ ] **Step 7: Falsify — each mutant must go RED**

**Never run `makemigrations` while falsifying** — it would not rewrite `0005`, it would emit
`0006`, then `0007` on restore, leaving junk migrations on the branch and tripping the repo's
"migration restore must target graph head" hazard. Edit both the model and the migration file
by hand instead.

1. Delete the `alloc_course_id` guard block from `Group.save` → `test_group_rejects_allocation_from_another_course` must FAIL.
2. Delete the entire `if self.pk is not None:` guard block from `Allocation.save` → `test_allocation_course_frozen_once_groups_attached` must FAIL.
3. Drop **only** the `and self.groups.exists()` clause (making the guard stricter) → `test_allocation_course_editable_while_no_groups_attached` must FAIL. Note this reddens a *different* test than mutant 2 — the two clauses guard opposite directions.
4. Change `on_delete=models.SET_NULL` to `models.CASCADE` in **both** `grouping/models.py` and `grouping/migrations/0005_allocation.py` → `test_deleting_allocation_nulls_the_fk_and_keeps_memberships` must FAIL. Hand-revert both files and re-run to confirm green.
5. Remove `uniq_allocation_course_name` from **both** the model `Meta.constraints` and the migration's `AddConstraint` → `test_allocation_name_unique_per_course` must FAIL. Hand-revert both. (This is the only mutant that proves the constraint reached the migration, not just the model.)

- [ ] **Step 8: Commit**

```bash
git add grouping/models.py grouping/migrations/0005_allocation.py tests/factories.py tests/test_grouping_allocation_models.py
git commit -m "feat(grouping): add the Allocation model and Group.allocation"
```

---

### Task 2: Permissions and scoping

**Files:**
- Modify: `institution/roles.py:76-100` (`GROUPING_COURSE_ADMIN_PERMS`, `GROUPING_PLATFORM_ADMIN_PERMS`)
- Modify: `grouping/scoping.py` (add `allocations_manageable_by`)
- Test: `tests/test_grouping_allocation_scoping.py`

**Interfaces:**
- Consumes: `grouping.models.Allocation` (Task 1).
- Produces: `grouping.scoping.allocations_manageable_by(user) -> QuerySet[Allocation]`; the four `grouping.*_allocation` permissions on the Course Admin and Platform Admin roles.

- [ ] **Step 1: Write the failing scoping tests**

Create `tests/test_grouping_allocation_scoping.py`:

```python
import pytest

from grouping import scoping
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _role_user(role_name, username):
    from django.contrib.auth.models import Group as AuthGroup

    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    # Same shape as tests/factories.py::_make_role — a freshly created user has
    # never had has_perm() called on it, so these attributes do not exist yet and
    # a bare `del` would AttributeError before any assertion runs.
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_platform_admin_sees_every_allocation():
    pa = _role_user(PLATFORM_ADMIN, "pa_scope")
    a = AllocationFactory()
    assert list(scoping.allocations_manageable_by(pa)) == [a]


def test_course_admin_sees_only_allocations_on_owned_courses():
    ca = _role_user(COURSE_ADMIN, "ca_scope")
    mine = AllocationFactory(course=CourseFactory(owner=ca))
    AllocationFactory(course=CourseFactory())  # someone else's
    assert list(scoping.allocations_manageable_by(ca)) == [mine]


def test_course_admin_does_not_see_owner_less_courses():
    ca = _role_user(COURSE_ADMIN, "ca_ownerless")
    AllocationFactory(course=CourseFactory(owner=None))
    assert list(scoping.allocations_manageable_by(ca)) == []


def test_teacher_sees_none():
    teacher = _role_user(TEACHER, "t_scope")
    # The allocation must be on a course the TEACHER owns, or this test is blind
    # to the "Teacher accidentally granted change_allocation" mutant: that mutant
    # sends them down the CA branch (course__owner=user), which returns nothing
    # for a bare AllocationFactory() whose course has owner=None.
    AllocationFactory(course=CourseFactory(owner=teacher))
    assert list(scoping.allocations_manageable_by(teacher)) == []


def test_archived_allocations_are_included():
    """Parity with groups_manageable_by: list views filter on top."""
    pa = _role_user(PLATFORM_ADMIN, "pa_arch")
    a = AllocationFactory(archived=True)
    assert list(scoping.allocations_manageable_by(pa)) == [a]


def test_course_admin_role_holds_the_allocation_permissions():
    ca = _role_user(COURSE_ADMIN, "ca_perms")
    for codename in ("add", "change", "delete", "view"):
        assert ca.has_perm(f"grouping.{codename}_allocation")


def test_teacher_role_holds_no_allocation_permissions():
    teacher = _role_user(TEACHER, "t_perms")
    for codename in ("add", "change", "delete", "view"):
        assert not teacher.has_perm(f"grouping.{codename}_allocation")
```

- [ ] **Step 2: Run and watch it fail**

```
uv run pytest tests/test_grouping_allocation_scoping.py -v
```

Expected: `AttributeError: module 'grouping.scoping' has no attribute 'allocations_manageable_by'`.

- [ ] **Step 3: Add the permissions**

In `institution/roles.py`, add to **both** `GROUPING_COURSE_ADMIN_PERMS` and `GROUPING_PLATFORM_ADMIN_PERMS` (these are the two grouping lists — *not* `PLATFORM_ADMIN_PERMS`, which holds accounts/institution/courses permissions):

```python
    "grouping.add_allocation",
    "grouping.change_allocation",
    "grouping.delete_allocation",
    "grouping.view_allocation",
```

- [ ] **Step 4: Add the scoping helper**

In `grouping/scoping.py`, import `Allocation` and add after `groups_visible_to`:

```python
def allocations_manageable_by(user):
    """Allocations a user may create/edit/delete. Mirrors groups_manageable_by:
    PA -> all; CA -> allocations on courses they own; else none. Owner-less
    courses (Course.owner is nullable) are PA-manageable only, by design.

    Includes archived rows; list views apply the active/archived filter on top."""
    if _is_platform_admin(user):
        return Allocation.objects.all()
    if user.has_perm("grouping.change_allocation"):  # Course Admin
        return Allocation.objects.filter(course__owner=user)
    return Allocation.objects.none()
```

- [ ] **Step 5: Run and watch it pass**

```
uv run pytest tests/test_grouping_allocation_scoping.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Falsify**

1. Replace the CA branch's `Allocation.objects.filter(course__owner=user)` with `Allocation.objects.all()` → `test_course_admin_sees_only_allocations_on_owned_courses` and `test_course_admin_does_not_see_owner_less_courses` must FAIL.
2. Remove the four `grouping.*_allocation` entries from `GROUPING_COURSE_ADMIN_PERMS` → `test_course_admin_role_holds_the_allocation_permissions` **and** `test_course_admin_sees_only_allocations_on_owned_courses` must FAIL (the CA branch tests `change_allocation`, so losing the perm empties the queryset too).
3. Add the four entries to `GROUPING_TEACHER_PERMS` → `test_teacher_role_holds_no_allocation_permissions` and `test_teacher_sees_none` must FAIL.
4. Scope the helper's PA branch with `.filter(archived=False)` → `test_archived_allocations_are_included` must FAIL.

Restore each by hand. Step 3's permission-list edit is this task's main deliverable — without mutants 2 and 3 it would ship never having been seen to fail.

- [ ] **Step 7: Commit**

```bash
git add institution/roles.py grouping/scoping.py tests/test_grouping_allocation_scoping.py
git commit -m "feat(grouping): allocation permissions and manageable-by scoping"
```

---

### Task 3: `AllocationForm`

**Files:**
- Modify: `grouping/forms.py` (add `AllocationForm`)
- Test: `tests/test_grouping_allocation_forms.py`

**Interfaces:**
- Consumes: `Allocation` (Task 1), `courses.access.manageable_courses` (existing).
- Produces: `grouping.forms.AllocationForm(data=None, instance=None, *, user=None)` with fields `name`, `course`, `cohorts`.

Read spec §"Forms → `AllocationForm`" before writing this task. Three rules are load-bearing and each has its own mutant below: the course queryset restriction (which **is** the create-time permission gate — there is no reachable `PermissionDenied`), the archived-cohort `pk__in` arm, and the `iexact` dedup living in `clean()` with a defensive course resolve.

- [ ] **Step 1: Write the failing form tests**

Create `tests/test_grouping_allocation_forms.py`:

```python
import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping.forms import AllocationForm
from grouping.models import Allocation
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from tests.factories import AllocationFactory
from tests.factories import CohortFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _role_user(role_name, username):
    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    # Same shape as tests/factories.py::_make_role — a freshly created user has
    # never had has_perm() called on it, so these attributes do not exist yet and
    # a bare `del` would AttributeError before any assertion runs.
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_course_queryset_excludes_courses_the_ca_does_not_own():
    """This restriction IS the create-time gate; there is no PermissionDenied."""
    ca = _role_user(COURSE_ADMIN, "ca_form")
    mine = CourseFactory(owner=ca)
    theirs = CourseFactory()
    form = AllocationForm(user=ca)
    pks = set(form.fields["course"].queryset.values_list("pk", flat=True))
    assert mine.pk in pks
    assert theirs.pk not in pks


def test_platform_admin_sees_every_course():
    pa = _role_user(PLATFORM_ADMIN, "pa_form")
    other = CourseFactory()
    form = AllocationForm(user=pa)
    assert other.pk in set(form.fields["course"].queryset.values_list("pk", flat=True))


def test_posting_an_unowned_course_is_a_field_error_and_creates_nothing():
    ca = _role_user(COURSE_ADMIN, "ca_post")
    theirs = CourseFactory()
    form = AllocationForm(data={"name": "X", "course": theirs.pk}, user=ca)
    assert not form.is_valid()
    assert "course" in form.errors
    assert Allocation.objects.count() == 0


def test_rejects_case_different_duplicate_name_on_the_same_course_at_create():
    """Create path: instance.course_id is None, so the check must read
    cleaned_data['course'] — which is why it lives in clean(), not clean_name()."""
    pa = _role_user(PLATFORM_ADMIN, "pa_dupe")
    existing = AllocationFactory(name="Klasy")
    form = AllocationForm(
        data={"name": "klasy", "course": existing.course_id}, user=pa
    )
    assert not form.is_valid()
    assert "name" in form.errors


def test_allows_the_same_name_on_a_different_course():
    pa = _role_user(PLATFORM_ADMIN, "pa_dupe2")
    AllocationFactory(name="Klasy")
    form = AllocationForm(
        data={"name": "Klasy", "course": CourseFactory().pk}, user=pa
    )
    assert form.is_valid(), form.errors


def test_rejects_a_name_held_by_an_archived_allocation():
    """The unique constraint has no `archived` condition, so scoping the dedup
    lookup to archived=False would hit an unhandled IntegrityError in save()."""
    pa = _role_user(PLATFORM_ADMIN, "pa_arch_dupe")
    existing = AllocationFactory(name="Klasy", archived=True)
    form = AllocationForm(
        data={"name": "klasy", "course": existing.course_id}, user=pa
    )
    assert not form.is_valid()
    assert "name" in form.errors


def test_editing_keeps_its_own_name():
    pa = _role_user(PLATFORM_ADMIN, "pa_selfedit")
    a = AllocationFactory(name="Klasy")
    form = AllocationForm(
        data={"name": "Klasy", "course": a.course_id}, instance=a, user=pa
    )
    assert form.is_valid(), form.errors


def test_cohorts_queryset_keeps_an_already_attached_archived_cohort():
    pa = _role_user(PLATFORM_ADMIN, "pa_cohorts")
    a = AllocationFactory()
    archived = CohortFactory(archived=True)
    a.cohorts.add(archived)
    form = AllocationForm(instance=a, user=pa)
    assert archived.pk in set(
        form.fields["cohorts"].queryset.values_list("pk", flat=True)
    )


def test_editing_an_allocation_keeps_its_archived_cohort_in_the_m2m():
    """Vacuity trap: under the mutant the POST is REJECTED (invalid_choice), so
    nothing saves and 'the cohort survives' would pass anyway. Assert the save
    SUCCEEDED as well."""
    pa = _role_user(PLATFORM_ADMIN, "pa_cohort_save")
    a = AllocationFactory(name="A")
    archived = CohortFactory(archived=True)
    live = CohortFactory()
    a.cohorts.set([archived, live])
    form = AllocationForm(
        data={
            "name": "A renamed",
            "course": a.course_id,
            "cohorts": [archived.pk, live.pk],
        },
        instance=a,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    a.refresh_from_db()
    assert a.name == "A renamed"
    assert set(a.cohorts.values_list("pk", flat=True)) == {archived.pk, live.pk}


def test_attached_archived_cohort_renders_with_a_suffix():
    """Spec row 11i, cohort half. Assert on the RENDERED checkbox list."""
    pa = _role_user(PLATFORM_ADMIN, "pa_cohort_label")
    a = AllocationFactory()
    archived = CohortFactory(name="Rocznik 2024", archived=True)
    a.cohorts.add(archived)
    form = AllocationForm(instance=a, user=pa)
    html = str(form["cohorts"])
    assert "Rocznik 2024" in html
    assert "archived" in html.lower()


def test_course_disabled_once_groups_are_attached():
    pa = _role_user(PLATFORM_ADMIN, "pa_lock")
    a = AllocationFactory()
    GroupFactory(course=a.course, allocation=a)
    form = AllocationForm(instance=a, user=pa)
    assert form.fields["course"].disabled is True
```

- [ ] **Step 2: Run and watch it fail**

```
uv run pytest tests/test_grouping_allocation_forms.py -v
```

Expected: `ImportError: cannot import name 'AllocationForm'`.

- [ ] **Step 3: Implement the form**

In `grouping/forms.py` (add `from django.db.models import Q`, `from grouping.models import Allocation`, `from courses.access import manageable_courses`):

```python
class AllocationForm(forms.ModelForm):
    class Meta:
        model = Allocation
        fields = ["name", "course", "cohorts"]
        widgets = {"cohorts": forms.CheckboxSelectMultiple}
        labels = {
            "name": _("Name"),
            "course": _("Course"),
            "cohorts": _("Cohorts"),
        }
        help_texts = {
            "cohorts": _("Students in these cohorts appear as rows in the grid.")
        }

    # `archived` is intentionally not a form field: archiving goes through the
    # allocation_archive POST view, exactly as CohortForm keeps `archived` off
    # the form.

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)
        # The course queryset IS the create-time permission gate (see spec):
        # a CA posting an unowned course pk fails invalid_choice, so a
        # PermissionDenied check placed after is_valid() would be unreachable.
        self.fields["course"].queryset = (
            manageable_courses(user) if user is not None else Course.objects.none()
        )
        if self.instance.pk is not None and self.instance.groups.exists():
            self.fields["course"].disabled = True
        # Keep an already-attached archived cohort selectable. Without this arm
        # its checkbox is never RENDERED, so the browser cannot post it back and
        # save_m2m() silently drops it — emptying a whole section out of the grid.
        attached = Q(pk__in=[])
        if self.instance.pk is not None:
            attached = Q(pk__in=self.instance.cohorts.values("pk"))
        self.fields["cohorts"].queryset = Cohort.objects.filter(
            Q(archived=False) | attached
        ).order_by("-is_default", "name")
        # Spec: an attached archived cohort renders with an "(archived)" suffix.
        # Cohort.__str__ is the bare name and display_name adds "(default)", so
        # without this override the archived cohort reads as an ordinary choice —
        # losing the whole point of keeping it selectable.
        self.fields["cohorts"].label_from_instance = self._cohort_label

    @staticmethod
    def _cohort_label(obj):
        if obj.archived:
            return format_lazy("{} ({})", obj.name, _("archived"))
        return obj.display_name

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("name") or "").strip()
        # Resolve the course DEFENSIVELY: Django runs clean() even after a field
        # failed, and add_error deletes that key from cleaned_data — so in the
        # very scenario this form gates (a CA posting an unowned course) there is
        # no "course" key at all and cleaned_data["course"] would KeyError → 500.
        # Resolve to an ID, never a mixed type (cleaned_data holds a Course
        # instance; the fallback is an int) — every comparison below is id-to-id.
        posted_course = cleaned.get("course")
        course_id = posted_course.pk if posted_course else self.instance.course_id
        if not (name and course_id):
            return cleaned
        # Case-insensitive dedup, ARCHIVED ROWS INCLUDED: uniq_allocation_course_name
        # is case-sensitive and has no archived condition, so an archived "Klasy"
        # still owns that slot and would raise IntegrityError in save().
        clash = Allocation.objects.filter(course_id=course_id, name__iexact=name)
        if self.instance.pk is not None:
            clash = clash.exclude(pk=self.instance.pk)
        clash = clash.first()
        if clash is not None:
            if clash.archived:
                self.add_error(
                    "name",
                    _(
                        "An archived allocation with this name already exists on this"
                        " course — un-archive it to reuse the name."
                    ),
                )
            else:
                self.add_error(
                    "name",
                    _("An allocation with this name already exists on this course."),
                )
        return cleaned
```

Add these imports if not already present: `from django.db.models import Q`,
`from django.utils.text import format_lazy`, `from courses.access import manageable_courses`,
`from courses.models import Course`, `from grouping.models import Allocation`,
`from grouping.models import Cohort`. (Task 4 relies on all of these already being here —
do not add them a second time there, or `ruff` flags F811 four commits later.)

- [ ] **Step 4: Run and watch it pass**

```
uv run pytest tests/test_grouping_allocation_forms.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Falsify**

1. Drop the `manageable_courses(user)` restriction (use `Course.objects.all()`) → `test_course_queryset_excludes_courses_the_ca_does_not_own` and `test_posting_an_unowned_course_is_a_field_error_and_creates_nothing` must FAIL.
2. Compare `name=name` instead of `name__iexact=name` → `test_rejects_case_different_duplicate_name_on_the_same_course_at_create` must FAIL.
2b. Move the whole dedup block from `clean()` into a `clean_name()` → the same test must FAIL, because on the create path `cleaned_data["course"]` is not yet populated when `clean_name()` runs and `self.instance.course_id` is `None`. This is the mutant that demonstrates *why* the rule lives in `clean()`.
2c. Drop the `label_from_instance` override for `cohorts` → `test_attached_archived_cohort_renders_with_a_suffix` must FAIL.
3. Add `archived=False` to the `clash` filter → `test_rejects_a_name_held_by_an_archived_allocation` must FAIL.
4. Drop the `attached` arm from the `cohorts` queryset → `test_cohorts_queryset_keeps_an_already_attached_archived_cohort` **and** `test_editing_an_allocation_keeps_its_archived_cohort_in_the_m2m` must FAIL (the second one fails on `form.is_valid()`, which is exactly why that assertion is there).

Restore each by hand.

- [ ] **Step 6: Commit**

```bash
git add grouping/forms.py tests/test_grouping_allocation_forms.py
git commit -m "feat(grouping): AllocationForm with course gating and case-insensitive dedup"
```

---

### Task 4: The `GroupForm` allocation control

**Files:**
- Modify: `grouping/forms.py` (`GroupForm`: `Meta.fields`, `user` kwarg, the allocation field, the iterator, the widget, `clean`, `save`)
- Modify: `grouping/views.py:192,207,227,235` (pass `user=request.user`; wrap `form.save()` in `transaction.atomic()`)
- Test: `tests/test_grouping_allocation_group_form.py`

**Interfaces:**
- Consumes: `Allocation` (Task 1), `manageable_courses` (existing).
- Produces: `GroupForm(..., user=None)` writing `Group.allocation`; `grouping.forms.AllocationChoiceIterator`; `grouping.forms.AllocationSelect`.

Read spec §"Forms → `GroupForm`" and §"Rendering the allocation select" in full before starting. This is the subtlest task in the plan: five separate Django behaviours interact (`Meta.fields` vs `construct_instance`, iterator-before-queryset, `create_option` and the empty choice, `label_from_instance`, and `add_error` deleting `cleaned_data` keys).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_grouping_allocation_group_form.py`:

```python
import re

import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping.forms import GroupForm
from grouping.models import Allocation
from institution.roles import COURSE_ADMIN
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _role_user(role_name, username):
    seed_roles()
    user = UserFactory(username=username)
    user.groups.add(AuthGroup.objects.get(name=role_name))
    # Same shape as tests/factories.py::_make_role — a freshly created user has
    # never had has_perm() called on it, so these attributes do not exist yet and
    # a bare `del` would AttributeError before any assertion runs.
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_constructs_without_a_user_and_offers_no_allocations():
    """Four existing call sites construct GroupForm WITHOUT a `user` kwarg (two
    with no kwargs at all), one of them in another app
    (integrations/tests/test_form_fields.py:40)."""
    AllocationFactory()
    form = GroupForm()
    assert list(form.fields["allocation"].queryset) == []


def test_create_form_excludes_allocations_on_unmanageable_courses():
    """Setup is load-bearing: NO instance, or the edit branch is taken and the
    mutant survives."""
    ca = _role_user(COURSE_ADMIN, "ca_gf")
    mine = AllocationFactory(course=CourseFactory(owner=ca))
    theirs = AllocationFactory()
    form = GroupForm(user=ca)
    pks = set(form.fields["allocation"].queryset.values_list("pk", flat=True))
    assert mine.pk in pks
    assert theirs.pk not in pks


def test_edit_form_scopes_allocations_to_the_groups_own_course():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_edit")
    group = GroupFactory()
    same = AllocationFactory(course=group.course)
    other = AllocationFactory(course=CourseFactory())
    form = GroupForm(instance=group, user=pa)
    pks = set(form.fields["allocation"].queryset.values_list("pk", flat=True))
    assert same.pk in pks
    assert other.pk not in pks


def test_edit_form_keeps_its_own_archived_allocation_selectable():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_arch")
    a = AllocationFactory(archived=True)
    group = GroupFactory(course=a.course, allocation=a)
    form = GroupForm(instance=group, user=pa)
    assert a.pk in set(form.fields["allocation"].queryset.values_list("pk", flat=True))


def test_renaming_a_group_does_not_detach_its_archived_allocation():
    """Vacuity trap: under the mutant the POST is rejected as invalid_choice, so
    nothing saves and 'allocation_id unchanged' passes anyway. Assert the save
    SUCCEEDED and the rename LANDED."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_nodetach")
    a = AllocationFactory(archived=True)
    group = GroupFactory(course=a.course, allocation=a, name="7A")
    form = GroupForm(
        data={
            "name": "7A renamed",
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": a.pk,
            "new_allocation": "",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.name == "7A renamed"
    assert group.allocation_id == a.pk


def test_empty_choice_is_offered_and_detaches():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_none")
    a = AllocationFactory()
    group = GroupFactory(course=a.course, allocation=a)
    form = GroupForm(instance=group, user=pa)
    values = [value for value, label in form.fields["allocation"].choices]
    assert "" in [str(v) for v in values]
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation_id is None


def test_rendered_options_carry_data_course_and_optgroups():
    """Assert against the RENDERED widget, not field.choices: a late-assigned
    iterator leaves choices correct while the widget renders flat."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_render")
    a = AllocationFactory()
    form = GroupForm(user=pa)
    html = str(form["allocation"])
    assert "data-allocation-select" in html   # the hook the client filter keys on
    assert "<optgroup" in html
    assert f'data-course="{a.course_id}"' in html
    # The empty choice must carry no data-course (create_option skips it).
    # Parse the tag rather than matching a fixed attribute order — Django emits
    # `selected` before other attrs, so a prefix match would miss
    # `<option value="" selected data-course="3">`.
    empty = re.search(r'<option value=""[^>]*>', html)
    assert empty is not None
    assert "data-course" not in empty.group(0)


def test_archived_allocation_option_is_labelled():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_label")
    a = AllocationFactory(archived=True, name="Stare klasy")
    group = GroupFactory(course=a.course, allocation=a)
    form = GroupForm(instance=group, user=pa)
    html = str(form["allocation"])
    assert "Stare klasy" in html
    assert "archived" in html.lower()


def test_picking_an_existing_allocation_writes_it():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_pick")
    group = GroupFactory()
    a = AllocationFactory(course=group.course)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": a.pk,
            "new_allocation": "",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation_id == a.pk


def test_typing_a_new_allocation_creates_and_attaches_it():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_new")
    group = GroupFactory()
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "matematyka 2026",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation.name == "matematyka 2026"


def test_new_name_reuses_an_existing_row_case_insensitively():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_reuse")
    group = GroupFactory()
    existing = AllocationFactory(course=group.course, name="Klasy")
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "klasy",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation_id == existing.pk
    assert Allocation.objects.filter(course=group.course).count() == 1


def test_new_name_matching_an_archived_row_is_a_field_error():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_newarch")
    group = GroupFactory()
    AllocationFactory(course=group.course, name="Klasy", archived=True)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "klasy",
        },
        instance=group,
        user=pa,
    )
    assert not form.is_valid()
    assert "new_allocation" in form.errors


def test_new_allocation_longer_than_200_chars_is_a_field_error():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_long")
    group = GroupFactory()
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "x" * 201,
        },
        instance=group,
        user=pa,
    )
    assert not form.is_valid()
    assert "new_allocation" in form.errors


def test_typing_a_new_name_on_an_already_allocated_group_moves_it():
    """The select ECHOES the current allocation (it is a Meta field), so a naive
    'both are non-empty' conflict test would reject the natural way to move a
    group. And without cleaned_data['allocation'] = None the save() fallback
    resolves to the OLD allocation and the group silently stays put."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_move")
    old = AllocationFactory(name="stara")
    group = GroupFactory(course=old.course, allocation=old)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": old.pk,  # the browser always echoes this back
            "new_allocation": "nowa",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation.name == "nowa"


def test_clearing_the_select_and_typing_a_new_name_also_moves_it():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_move2")
    old = AllocationFactory(name="stara")
    group = GroupFactory(course=old.course, allocation=old)
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": "",
            "new_allocation": "nowa",
        },
        instance=group,
        user=pa,
    )
    assert form.is_valid(), form.errors
    form.save()
    group.refresh_from_db()
    assert group.allocation.name == "nowa"


def test_picking_a_different_existing_allocation_and_typing_is_a_conflict():
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_both")
    old = AllocationFactory(name="stara")
    group = GroupFactory(course=old.course, allocation=old)
    other = AllocationFactory(course=old.course, name="inna")
    form = GroupForm(
        data={
            "name": group.name,
            "course": group.course_id,
            "teachers": [],
            "external_id": "",
            "allocation": other.pk,
            "new_allocation": "nowa",
        },
        instance=group,
        user=pa,
    )
    assert not form.is_valid()
    assert "new_allocation" in form.errors


def test_allocation_on_another_course_is_a_field_error_on_the_create_path():
    """Setup is load-bearing: CREATE path as a PA, so the foreign allocation is
    genuinely inside the field queryset and only clean() can reject it."""
    pa = _role_user(PLATFORM_ADMIN, "pa_gf_cross")
    course = CourseFactory()
    foreign = AllocationFactory(course=CourseFactory())
    form = GroupForm(
        data={
            "name": "7A",
            "course": course.pk,
            "teachers": [],
            "external_id": "",
            "allocation": foreign.pk,
            "new_allocation": "",
        },
        user=pa,
    )
    assert not form.is_valid()
    assert "allocation" in form.errors
```

- [ ] **Step 2: Run and watch it fail**

```
uv run pytest tests/test_grouping_allocation_group_form.py -v
```

Expected: every test errors on the missing `allocation` field.

- [ ] **Step 3: Add the iterator and the widget**

In `grouping/forms.py`, above `GroupForm`:

```python
class AllocationChoiceIterator(forms.models.ModelChoiceIterator):
    """Groups allocation options into one <optgroup> per course.

    Two things here are load-bearing:
      * the empty choice is yielded FIRST and outside any optgroup — the base
        __iter__ is what normally emits it, so a subclass that yields only
        optgroups silently drops "— none —" and leaves no way to detach a group;
      * labels go through self.field.label_from_instance, which is where the
        "(archived)" suffix lives. Yielding obj.name would defeat that override
        for THIS field while `cohorts` (stock iterator) kept showing its suffix.
    """

    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        # Keyed on course_id, NOT title: Course.title is a plain CharField with
        # no unique constraint, and two same-titled courses merging into one
        # optgroup would give it options carrying different data-course values —
        # which the client filter hides wholesale, taking valid options with it.
        by_course = {}
        for obj in self.queryset:
            title, options = by_course.setdefault(obj.course_id, (obj.course.title, []))
            options.append((self.choice(obj)[0], self.field.label_from_instance(obj)))
        for title, options in by_course.values():
            yield (title, options)


class AllocationSelect(forms.Select):
    """Adds data-course to each real <option> so the create form's client-side
    filter can narrow allocations to the chosen course. Per-option attributes are
    only reachable from create_option — a choices tuple carries value and label
    only."""

    def create_option(self, name, value, label, selected, index, **kwargs):
        option = super().create_option(name, value, label, selected, index, **kwargs)
        # Select.optgroups calls this for the empty choice too, passing a bare
        # "" rather than a ModelChoiceIteratorValue — an unguarded
        # value.instance would AttributeError on every render.
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-course"] = str(instance.course_id)
        return option
```

- [ ] **Step 4: Wire the field into `GroupForm`**

Add `allocation` to `Meta.fields` (so the model field is form-managed and rendered — **not** because it writes the value; `save()` does that):

```python
        fields = ["name", "course", "teachers", "external_id", "allocation"]
```

and add labels for `allocation` / `new_allocation`. Then in `GroupForm`:

```python
    new_allocation = forms.CharField(
        max_length=200,  # matches Allocation.name; without it a long value 500s
        required=False,
        label=_("…or create a new allocation"),
    )

    _resolved_allocation = None  # class default: save() must not AttributeError

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None:
            self.fields["course"].disabled = True
        from grouping.services import teacher_users

        self.fields["teachers"].queryset = teacher_users()

        field = self.fields["allocation"]
        field.empty_label = _("— none —")
        field.label_from_instance = self._allocation_label
        # The iterator MUST be assigned before the queryset: _set_queryset ends
        # with `self.widget.choices = self.choices`, so the widget captures
        # whichever iterator exists at assignment time. Assigning it afterwards
        # leaves the WIDGET on the base iterator (flat options, no optgroups)
        # while field.choices still looks correct.
        field.iterator = AllocationChoiceIterator
        # The hook MUST be set here: `{{ form.allocation }}` renders the widget
        # as-is, Django templates cannot add attributes to a rendered widget, and
        # this repo has no widget_tweaks. Without it initAllocationFilter() finds
        # nothing and is silently inert.
        field.widget = AllocationSelect(attrs={"data-allocation-select": ""})
        if self.instance.pk:
            base = Q(course=self.instance.course)
        elif user is not None:
            base = Q(course__in=manageable_courses(user))
        else:
            base = Q(pk__in=[])
        field.queryset = (
            Allocation.objects.filter(
                (base & Q(archived=False)) | Q(pk=self.instance.allocation_id)
            )
            .select_related("course")
            .order_by("course__title", "name")
        )

    @staticmethod
    def _allocation_label(obj):
        if obj.archived:
            return format_lazy("{} ({})", obj.name, _("archived"))
        return obj.name
```

All the imports this needs (`Q`, `format_lazy`, `manageable_courses`, `Allocation`) were
added in Task 3 — do **not** add them again; duplicate import lines are an F811 that surfaces
only at Task 10's lint gate.

- [ ] **Step 5: Add `clean()` and `save()`**

```python
    def clean(self):
        cleaned = super().clean()
        # Defensive resolve — add_error deletes a failed field's key, and clean()
        # still runs. cleaned_data["course"] would KeyError.
        #
        # Resolve to an ID, never a mixed type: `cleaned.get("course")` is a
        # Course instance while `self.instance.course_id` is an int, so comparing
        # `picked.course_id != course.pk` would AttributeError on the fallback
        # branch — turning the specified 200 re-render into a 500. Every
        # comparison below is id-to-id.
        posted_course = cleaned.get("course")
        course_id = posted_course.pk if posted_course else self.instance.course_id
        picked = cleaned.get("allocation")
        new_name = (cleaned.get("new_allocation") or "").strip()

        if new_name:
            # The select ECHOES the current allocation back on every edit-form
            # POST, so only a genuinely DIFFERENT pick counts as a conflict.
            picked_id = picked.pk if picked is not None else None
            if picked_id is not None and picked_id != self.instance.allocation_id:
                self.add_error(
                    "new_allocation",
                    _("Choose an existing allocation or type a new name, not both."),
                )
                return cleaned
            # The new name wins: clear the echoed value so construct_instance and
            # save()'s fallback both see None and the create branch actually runs.
            cleaned["allocation"] = None
            picked = None
            if course_id:
                clash = Allocation.objects.filter(
                    course_id=course_id, name__iexact=new_name
                ).first()
                if clash is not None and clash.archived:
                    self.add_error(
                        "new_allocation",
                        _(
                            "An archived allocation with this name already exists on"
                            " this course — un-archive it to reuse the name."
                        ),
                    )
                    return cleaned
                self._resolved_allocation = clash

        if picked is not None and course_id and picked.course_id != course_id:
            # Field error, not a non-field one: group_form.html renders errors
            # per field, so a non-field error would be invisible.
            self.add_error(
                "allocation", _("This allocation belongs to a different course.")
            )
        return cleaned

    def save(self, commit=True):
        # commit is accepted for signature compatibility; GroupForm always
        # commits (both views call it plainly).
        course = self.cleaned_data.get("course") or self.instance.course
        name = (self.cleaned_data.get("new_allocation") or "").strip()
        # The picked path must seed this too — clean() stashes
        # _resolved_allocation only on the new_allocation path, so without the
        # fallback the assignment below would null a picked allocation.
        allocation = self._resolved_allocation or self.cleaned_data.get("allocation")
        if allocation is None and name:
            try:
                with transaction.atomic():  # savepoint: absorb a concurrent create
                    allocation = Allocation.objects.create(course=course, name=name)
            except IntegrityError:
                allocation = Allocation.objects.get(course=course, name=name)
        group = super().save(commit=False)
        group.allocation = allocation
        group.save()
        self.save_m2m()
        return group
```

Add `from django.db import IntegrityError` and `from django.db import transaction`.

- [ ] **Step 6: Run and watch it pass**

```
uv run pytest tests/test_grouping_allocation_group_form.py -v
```

Expected: 17 passed.

- [ ] **Step 7: Confirm the existing call sites and group views still pass**

```
uv run pytest tests/test_grouping_forms.py integrations/tests/test_form_fields.py tests/test_grouping_group_views.py -v
```

Expected: all pass, unchanged. If any fail, the `user=None` fallback (or the rewritten
`save()`) is wrong — fix it here, not by editing those tests. `test_grouping_group_views.py`
is in this command deliberately: Step 5 replaced `GroupForm.save()` wholesale and Step 8
rewires four view call sites, so waiting until Task 5 to run it would commit a group
create/edit regression one commit before detecting it.

- [ ] **Step 8: Wire the views**

In `grouping/views.py`, **add `from django.db import transaction` to the imports** (it is not
there today — the wrapper below would be a `NameError`), pass `user=request.user` at all four `GroupForm(...)` construction sites (lines ~192, 207, 227, 235), and wrap **only** the `form.save()` call in `group_create` and `group_edit`:

```python
            with transaction.atomic():
                group = form.save()
```

`services.set_group_members(...)` stays outside that block — it manages its own atomic blocks and per-student savepoints.

Then add the test that makes the wrapper real (spec row 10) to
`tests/test_grouping_allocation_group_form.py`:

```python
def test_a_failing_group_save_leaves_no_orphan_allocation(client, monkeypatch):
    """The atomic wrapper is the ONLY thing preventing an orphan Allocation when
    the group save fails after the allocation was created."""
    from django.urls import reverse

    from grouping.models import Group
    from tests.factories import make_pa

    pa = make_pa(client)
    course = CourseFactory(owner=pa)

    def boom(self, *args, **kwargs):
        raise RuntimeError("group save failed")

    monkeypatch.setattr(Group, "save", boom)
    with pytest.raises(RuntimeError):
        client.post(
            reverse("grouping:group_create"),
            {
                "name": "7A",
                "course": course.pk,
                "teachers": [],
                "external_id": "",
                "allocation": "",
                "new_allocation": "matematyka 2026",
            },
        )
    assert Allocation.objects.count() == 0
```

Re-run `uv run pytest tests/test_grouping_allocation_group_form.py -v` after Step 8, then
Step 7's command again, before committing.

- [ ] **Step 9: Falsify — every test, paired with its mutant**

| Test | Mutant that must redden it |
|---|---|
| `test_constructs_without_a_user_and_offers_no_allocations` | make `user` a required positional parameter (Step 7's files go red too) |
| `test_create_form_excludes_allocations_on_unmanageable_courses` | drop `Q(course__in=manageable_courses(user))`, use `Q()` |
| `test_edit_form_scopes_allocations_to_the_groups_own_course` | drop `Q(course=self.instance.course)` from the edit branch |
| `test_edit_form_keeps_its_own_archived_allocation_selectable` | drop `\| Q(pk=self.instance.allocation_id)` |
| `test_renaming_a_group_does_not_detach_its_archived_allocation` | the same `pk=` arm (this is the test that proves the save *succeeds*) |
| `test_empty_choice_is_offered_and_detaches` | have the iterator yield only optgroup tuples, dropping `("", empty_label)` |
| `test_rendered_options_carry_data_course_and_optgroups` | (a) drop the `create_option` override → the `data-course` assertion; (b) assign `field.iterator` **after** `field.queryset` → the `<optgroup` assertion; (c) construct `AllocationSelect()` with no `attrs` → the `data-allocation-select` assertion |
| `test_archived_allocation_option_is_labelled` | yield `obj.name` instead of `self.field.label_from_instance(obj)` |
| `test_picking_an_existing_allocation_writes_it` | drop `or self.cleaned_data.get("allocation")` from `save()` |
| `test_typing_a_new_allocation_creates_and_attaches_it` | drop the `group.allocation = allocation` assignment (kills only this path) |
| `test_new_name_reuses_an_existing_row_case_insensitively` | drop the stashed `_resolved_allocation` and let `save()` create unconditionally |
| `test_new_name_matching_an_archived_row_is_a_field_error` | drop the `clash.archived` branch |
| `test_new_allocation_longer_than_200_chars_is_a_field_error` | omit `max_length=200` |
| `test_typing_a_new_name_on_an_already_allocated_group_moves_it` | drop `cleaned["allocation"] = None` |
| `test_clearing_the_select_and_typing_a_new_name_also_moves_it` | treat an empty `allocation` as "different from `instance.allocation_id`" (making the clearest gesture a conflict) |
| `test_picking_a_different_existing_allocation_and_typing_is_a_conflict` | drop the conflict branch entirely |
| `test_allocation_on_another_course_is_a_field_error_on_the_create_path` | remove the course-equality check from `clean()` |
| `test_a_failing_group_save_leaves_no_orphan_allocation` | remove the view-level `with transaction.atomic():` from `group_create` |

Separately, removing the `instance is not None` guard in `create_option` must make every render test **ERROR** with `AttributeError` — that is spec row 11h, and an error is an acceptable red.

Restore each by hand.

- [ ] **Step 10: Commit**

```bash
git add grouping/forms.py grouping/views.py tests/test_grouping_allocation_group_form.py
git commit -m "feat(grouping): allocation control on the group form"
```

---

### Task 5: Allocation CRUD views, templates, and navigation

**Files:**
- Modify: `grouping/urls.py`, `grouping/views.py`
- Create: `templates/grouping/allocation_list.html`, `allocation_form.html`, `allocation_confirm_delete.html`
- Modify: `templates/_groups_tabs.html`, `templates/base.html:91-103`, `templates/grouping/group_list.html`, `templates/grouping/group_form.html`
- Test: `tests/test_grouping_allocation_views.py`, and new cases in `tests/test_groups_tabs.py`

**Interfaces:**
- Consumes: `AllocationForm` (Task 3), `allocations_manageable_by` (Task 2).
- Produces: URL names `grouping:allocation_list|allocation_create|allocation_edit|allocation_archive|allocation_delete`.

- [ ] **Step 1: Write the failing view tests**

Create `tests/test_grouping_allocation_views.py` with, at minimum:

```python
import pytest
from django.urls import reverse

from grouping.models import Allocation
from grouping.models import GroupMembership
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db


def _card_list(body):
    """Scope assertions to the list itself — the page also carries the nav, the
    tabs strip and the archived toggle, and a bare substring against the whole
    body is the shadowing shape this repo has been bitten by before."""
    return body.split('class="card-list"')[1].split("</ul>")[0]


def test_list_is_scoped_and_honours_the_archived_toggle(client):
    ca = make_ca(client)
    mine = AllocationFactory(course=CourseFactory(owner=ca), name="Mine")
    AllocationFactory(course=CourseFactory(owner=ca), name="Old", archived=True)
    AllocationFactory(name="Theirs")
    rows = _card_list(client.get(reverse("grouping:allocation_list")).content.decode())
    assert "Mine" in rows
    assert "Old" not in rows
    assert "Theirs" not in rows
    assert reverse("grouping:allocation_edit", args=[mine.pk]) in rows
    rows = _card_list(
        client.get(reverse("grouping:allocation_list") + "?archived=1").content.decode()
    )
    assert "Old" in rows
    assert "Mine" not in rows


def test_teacher_gets_403(client):
    make_teacher(client)
    a = AllocationFactory()
    assert client.get(reverse("grouping:allocation_list")).status_code == 403
    assert client.get(reverse("grouping:allocation_edit", args=[a.pk])).status_code == 403


def test_ca_cannot_create_on_an_unowned_course(client):
    make_ca(client)
    theirs = CourseFactory()
    resp = client.post(
        reverse("grouping:allocation_create"), {"name": "X", "course": theirs.pk}
    )
    assert resp.status_code == 200          # re-render, not a redirect
    assert "course" in resp.context["form"].errors
    assert Allocation.objects.count() == 0


def test_archive_toggles_both_ways(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    client.post(reverse("grouping:allocation_archive", args=[a.pk]))
    a.refresh_from_db()
    assert a.archived is True
    client.post(reverse("grouping:allocation_archive", args=[a.pk]))
    a.refresh_from_db()
    assert a.archived is False


def test_delete_view_nulls_the_fk_and_keeps_memberships(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    group = GroupFactory(course=a.course, allocation=a)
    GroupMembershipFactory(group=group)
    resp = client.post(reverse("grouping:allocation_delete", args=[a.pk]))
    assert resp.status_code == 302
    group.refresh_from_db()
    assert group.allocation_id is None
    assert GroupMembership.objects.filter(group=group).count() == 1


def test_ca_sees_the_admin_menu_allocations_link(client):
    """Scoped to the admin menu panel — /manage/allocations/ also appears in the
    tabs strip, and a bare substring assertion would be satisfied by either."""
    make_ca(client)
    body = client.get(reverse("grouping:group_list")).content.decode()
    panel = body.split('data-menu-panel')[1].split("</div>")[0]
    assert reverse("grouping:allocation_list") in panel
```

Add to `tests/test_groups_tabs.py` — that file imports only `make_login` and `make_pa` today,
so **add `from tests.factories import make_ca` and `from tests.factories import make_teacher`**
to its import block (force-single-line, alphabetical within the group: `make_ca`,
`make_login`, `make_pa`, `make_teacher`):

```python
def test_tabs_show_allocations_for_a_course_admin(client):
    make_ca(client)
    body = client.get(reverse("grouping:group_list")).content.decode()
    strip = body.split('class="tnhub__tabs"')[1].split("</nav>")[0]
    assert reverse("grouping:allocation_list") in strip


def test_tabs_hide_allocations_from_a_teacher(client):
    make_teacher(client)
    body = client.get(reverse("grouping:my_groups")).content.decode()
    assert 'class="tnhub__tabs"' in body          # the strip still renders
    strip = body.split('class="tnhub__tabs"')[1].split("</nav>")[0]
    assert reverse("grouping:allocation_list") not in strip
```

- [ ] **Step 2: Run and watch them fail**

```
uv run pytest tests/test_grouping_allocation_views.py tests/test_groups_tabs.py -v
```

Expected: `NoReverseMatch: 'allocation_list' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the URLs**

In `grouping/urls.py`, after the group routes:

```python
    path("manage/allocations/", views.allocation_list, name="allocation_list"),
    path("manage/allocations/new/", views.allocation_create, name="allocation_create"),
    path(
        "manage/allocations/<int:pk>/edit/",
        views.allocation_edit,
        name="allocation_edit",
    ),
    path(
        "manage/allocations/<int:pk>/archive/",
        views.allocation_archive,
        name="allocation_archive",
    ),
    path(
        "manage/allocations/<int:pk>/delete/",
        views.allocation_delete,
        name="allocation_delete",
    ),
```

- [ ] **Step 4: Add the views**

In `grouping/views.py`, following the shape of `group_list` / `group_edit` / `group_archive` / `group_delete`. Every view carries `@login_required` then
`@permission_required("grouping.<perm>_allocation", raise_exception=True)` — without `raise_exception=True` the teacher case is a 302 to login, not the 403 the tests assert.

```python
@login_required
@permission_required("grouping.view_allocation", raise_exception=True)
def allocation_list(request):
    show_archived = request.GET.get("archived") == "1"
    allocations = (
        scoping.allocations_manageable_by(request.user)
        .filter(archived=show_archived)
        .select_related("course")
        .prefetch_related("cohorts")
        .annotate(group_count=Count("groups", filter=Q(groups__archived=False)))
        .order_by("course__title", "name")
    )
    return render(
        request,
        "grouping/allocation_list.html",
        {
            "allocations": allocations,
            "show_archived": show_archived,
            "hub_tab": "allocations",
        },
    )


@login_required
@permission_required("grouping.add_allocation", raise_exception=True)
def allocation_create(request):
    # NOTE: no PermissionDenied check here — AllocationForm restricts `course` to
    # manageable_courses(user), so an unowned pk fails invalid_choice and any
    # check placed after is_valid() would be unreachable dead code.
    if request.method == "POST":
        form = AllocationForm(request.POST, user=request.user)
        if form.is_valid():
            allocation = form.save()
            return redirect("grouping:allocation_edit", pk=allocation.pk)
    else:
        form = AllocationForm(user=request.user)
    return render(
        request, "grouping/allocation_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("grouping.change_allocation", raise_exception=True)
def allocation_edit(request, pk):
    allocation = get_object_or_404(
        scoping.allocations_manageable_by(request.user), pk=pk
    )
    if request.method == "POST":
        form = AllocationForm(request.POST, instance=allocation, user=request.user)
        if form.is_valid():
            form.save()
            return redirect("grouping:allocation_list")
    else:
        form = AllocationForm(instance=allocation, user=request.user)
    return render(
        request,
        "grouping/allocation_form.html",
        {"form": form, "creating": False, "allocation": allocation},
    )


@login_required
@permission_required("grouping.change_allocation", raise_exception=True)
@require_POST
def allocation_archive(request, pk):
    """Toggles, exactly as group_archive does. Archiving leaves groups and
    memberships untouched — deliberately unlike archive_cohort."""
    allocation = get_object_or_404(
        scoping.allocations_manageable_by(request.user), pk=pk
    )
    allocation.archived = not allocation.archived
    allocation.save(update_fields=["archived"])
    return redirect("grouping:allocation_list")


@login_required
@permission_required("grouping.delete_allocation", raise_exception=True)
def allocation_delete(request, pk):
    allocation = get_object_or_404(
        scoping.allocations_manageable_by(request.user), pk=pk
    )
    if request.method == "POST":
        allocation.delete()  # SET_NULL on Group.allocation; memberships untouched
        return redirect("grouping:allocation_list")
    return render(
        request,
        "grouping/allocation_confirm_delete.html",
        {"allocation": allocation, "group_count": allocation.groups.count()},
    )
```

Add `from django.db.models import Count`, `from django.db.models import Q`, and `from grouping.forms import AllocationForm`.

- [ ] **Step 5: Add the templates**

`templates/grouping/allocation_list.html` — model it on `group_list.html`: include `_groups_tabs.html`, an `<h1>`, a "New allocation" button, the archived toggle, and a `card-list` whose rows show the name (linking to `grouping:allocation_assign` — added in Task 7; until then link to `allocation_edit` and change it in Task 7), the course, the cohort names, `{{ a.group_count }}`, and Edit / Archive / Delete actions.

`allocation_form.html` — model it on `cohort_form.html`: render `form.name`, `form.course`, and the `form.cohorts` checkbox list, plus Save and Cancel.

`allocation_confirm_delete.html` — model it on `group_confirm_delete.html`, stating that groups keep their memberships and only lose the label.

- [ ] **Step 6: Add the navigation entry points**

In `templates/_groups_tabs.html`, **inside** the existing `{% if perms.grouping.view_group %}` wrapper (a Teacher holds `view_group` and must keep seeing the strip without the new tab):

```html
  {% if perms.grouping.view_allocation %}
  <a class="tnhub__tab{% if hub_tab == 'allocations' %} is-on{% endif %}"
     href="{% url 'grouping:allocation_list' %}">{% trans "Allocations" %}</a>
  {% endif %}
```

In `templates/base.html`, add `or perms.grouping.view_allocation` to the admin menu's **outer** `{% if %}` at line 91 (a Course Admin holds none of its four current permissions, so without this they would hold the permission and never see the menu), and add the item next to "Cohorts":

```html
              {% if perms.grouping.view_allocation %}
              <a class="menu__item" href="{% url 'grouping:allocation_list' %}">{% trans "Allocations" %}</a>
              {% endif %}
```

- [ ] **Step 7: Surface the allocation on the group screens**

In `grouping/views.py::group_list`, add `.select_related("course", "allocation")` to the queryset. In `templates/grouping/group_list.html`, add a muted allocation name to each row. In `templates/grouping/group_form.html`, add the allocation row (select + `new_allocation` input) after the `external_id` row, rendering `{{ form.allocation }}`, `{{ form.allocation.errors }}`, `{{ form.new_allocation }}`, `{{ form.new_allocation.errors }}`. The select **already carries** `data-allocation-select` from the widget's `attrs` (Task 4) — render it as-is; a Django template cannot add attributes to a rendered widget, and this repo has no `widget_tweaks`.

The course field stays `{{ form.course }}`, which renders `<select name="course" id="id_course">` with no data hook. Task 9's filter therefore reads it as `form.querySelector('[name="course"]')` — and if that element is absent or `disabled` (which it is on the edit form, where the course is frozen), the filter returns immediately and the select stays server-filtered. Do not add a hook to the course field.

- [ ] **Step 8: Run and watch them pass**

```
uv run pytest tests/test_grouping_allocation_views.py tests/test_groups_tabs.py tests/test_grouping_group_views.py -v
```

Expected: all pass.

- [ ] **Step 9: Falsify**

1. Scope `allocation_list` with `Allocation.objects.all()` → `test_list_is_scoped_and_honours_the_archived_toggle` must FAIL.
1b. Drop the `manageable_courses(user)` restriction on `AllocationForm.course` → `test_ca_cannot_create_on_an_unowned_course` must FAIL (the row is created). This asserts the POST *outcome*; Task 3's mutant 1 asserts the queryset contents — they are different tests of the same gate.
1c. Make `allocation_delete` cascade-delete the allocation's groups → `test_delete_view_nulls_the_fk_and_keeps_memberships` must FAIL.
2. Drop `raise_exception=True` from `allocation_list` → `test_teacher_gets_403` must FAIL (302, not 403).
3. Make `allocation_archive` set `archived = True` unconditionally → `test_archive_toggles_both_ways` must FAIL.
4. Leave `base.html`'s outer `{% if %}` unchanged → `test_ca_sees_the_admin_menu_allocations_link` must FAIL.
5. Hoist the tab outside its `{% if perms.grouping.view_allocation %}` → `test_tabs_hide_allocations_from_a_teacher` must FAIL.
6. Delete the new `<a class="tnhub__tab">` block from `_groups_tabs.html` entirely → `test_tabs_show_allocations_for_a_course_admin` must FAIL. (Mutant 5 makes the tab *more* visible, so it leaves the positive half green — spec row 30b needs its own mutant.)

Restore each by hand.

- [ ] **Step 10: Commit**

```bash
git add grouping/urls.py grouping/views.py templates/ tests/test_grouping_allocation_views.py tests/test_groups_tabs.py
git commit -m "feat(grouping): allocation CRUD screens and navigation"
```

---

### Task 6: Grid services — tokens, the row set, and `set_allocation_assignments`

**Files:**
- Modify: `grouping/services.py`
- Test: `tests/test_grouping_allocation_service.py`

**Interfaces:**
- Consumes: `Allocation` (Task 1); existing `add_students_to_group`, `remove_students_from_group`, `student_users`.
- Produces:
  - `allocation_columns(allocation) -> QuerySet[Group]`
  - `allocation_columns_token(columns) -> str`
  - `allocation_state_tokens(columns, student_ids, memberships=None) -> dict[int, str]`
  - `allocation_row_students(allocation) -> QuerySet[User]`
  - `set_allocation_assignments(columns, assignments, *, added_by=None) -> list[int]` (returns skipped student ids)

Read spec §"Data flow → Saving" before starting. The three-rule ordering (no-op → guard mismatch → write) and the omission-versus-`None` encoding are the whole point of this task.

- [ ] **Step 1: Write the failing service tests**

Create `tests/test_grouping_allocation_service.py`:

```python
import pytest

from courses.models import Enrollment
from grouping import services
from grouping.models import GroupMembership
from notifications.models import Notification
from tests.factories import AllocationFactory
from tests.factories import CohortFactory
from tests.factories import CohortMembershipFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _alloc_with_columns(n=2):
    a = AllocationFactory()
    cols = [
        GroupFactory(course=a.course, allocation=a, name=f"col{i}") for i in range(n)
    ]
    return a, cols


def test_columns_token_sorts_numerically_not_lexically():
    """Asserting against a re-computation of the implementation would be blind to
    the lexical-sort mutant, and two consecutive pks never straddle a decade —
    so pin it with a stub whose pks do."""

    class _Stub:
        def __init__(self, pk):
            self.pk = pk

    assert services.allocation_columns_token([_Stub(10), _Stub(9)]) == "9,10"


def test_state_token_shapes():
    a, cols = _alloc_with_columns(2)
    s_none = UserFactory()
    s_one = UserFactory()
    s_conflict = UserFactory()
    services.add_students_to_group(cols[0], [s_one])
    services.add_students_to_group(cols[0], [s_conflict])
    services.add_students_to_group(cols[1], [s_conflict])
    tokens = services.allocation_state_tokens(
        cols, [s_none.pk, s_one.pk, s_conflict.pk]
    )
    assert tokens[s_none.pk] == ""
    assert tokens[s_one.pk] == str(cols[0].pk)
    assert tokens[s_conflict.pk] == ",".join(
        str(pk) for pk in sorted([cols[0].pk, cols[1].pk])
    )


def test_row_students_union_includes_out_of_cohort_and_archived_column_members():
    a, cols = _alloc_with_columns(1)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    in_cohort = UserFactory()
    CohortMembershipFactory(user=in_cohort, cohort=cohort)
    outsider = UserFactory()
    services.add_students_to_group(cols[0], [outsider])
    archived_col = GroupFactory(course=a.course, allocation=a, archived=True)
    archived_only = UserFactory()
    services.add_students_to_group(archived_col, [archived_only])
    ids = set(services.allocation_row_students(a).values_list("pk", flat=True))
    assert {in_cohort.pk, outsider.pk, archived_only.pk} <= ids


def test_row_students_excludes_staff():
    a, cols = _alloc_with_columns(1)
    staff = UserFactory(is_staff=True)
    GroupMembership.objects.create(group=cols[0], student=staff)
    ids = set(services.allocation_row_students(a).values_list("pk", flat=True))
    assert staff.pk not in ids


def test_writes_only_inside_the_rectangle_and_the_write_lands():
    """Load-bearing: was_token must match, or the row is skipped and the purely
    negative assertion holds under the mutant too."""
    a, cols = _alloc_with_columns(2)
    outside = GroupFactory(course=a.course)          # same course, NOT a column
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(outside, [student])
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[1].pk, str(cols[0].pk))}
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=outside, student=student).exists()
    assert GroupMembership.objects.filter(group=cols[1], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_none_target_removes_membership_and_drops_group_sourced_enrollment():
    """Load-bearing: the membership must come from add_students_to_group, or no
    group-sourced Enrollment exists and the assertion is vacuous."""
    a, cols = _alloc_with_columns(1)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    assert Enrollment.objects.filter(
        student=student, course=a.course, source="group"
    ).exists()
    services.set_allocation_assignments(cols, {student.pk: (None, str(cols[0].pk))})
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert not Enrollment.objects.filter(
        student=student, course=a.course, source="group"
    ).exists()


def test_a_row_absent_from_assignments_is_untouched():
    """The conflict case: no radio checked, so the browser posts nothing."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(cols[1], [student])
    services.set_allocation_assignments(cols, {})
    assert GroupMembership.objects.filter(student=student).count() == 2


def test_conflict_row_resolves_when_a_column_is_picked():
    """Whole-token comparison: 'already in the target group' must NOT read as a
    no-op, or conflicts are unresolvable through the screen built to resolve them."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(cols[1], [student])
    token = ",".join(str(pk) for pk in sorted([cols[0].pk, cols[1].pk]))
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[0].pk, token)}
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[1], student=student).exists()


def test_guard_skips_a_moved_row_and_reports_it():
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[1].pk, "")}      # stale: claims "no membership"
    )
    assert skipped == [student.pk]
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[1], student=student).exists()


def test_a_no_op_row_is_neither_written_nor_reported_even_when_the_token_moved():
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[0].pk, "")}      # stale -was, but posted == current
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_a_none_was_token_is_a_mismatch_not_an_unguarded_write():
    """Load-bearing: the student must currently be in NO column (token ""), or
    the mutant's "" coincidentally mismatches and skips too."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (cols[0].pk, None)}
    )
    assert skipped == [student.pk]
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_moving_between_columns_keeps_the_enrollment_and_fires_no_new_notification():
    """Add-before-remove. Load-bearing: the membership must be group-sourced, or
    recompute_enrollment never deletes and the swap is invisible."""
    a, cols = _alloc_with_columns(2)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    enrollment = Enrollment.objects.get(
        student=student, course=a.course, source="group"
    )
    before = Notification.objects.filter(recipient=student).count()
    services.set_allocation_assignments(
        cols, {student.pk: (cols[1].pk, str(cols[0].pk))}
    )
    assert GroupMembership.objects.filter(group=cols[1], student=student).exists()
    assert not GroupMembership.objects.filter(group=cols[0], student=student).exists()
    assert Enrollment.objects.get(
        student=student, course=a.course
    ).pk == enrollment.pk
    assert Notification.objects.filter(recipient=student).count() == before


def test_an_out_of_range_target_keeps_the_membership():
    """Spec row 17c. Load-bearing: the -was must MATCH the current token, or the
    guard skips the row and the mutant survives."""
    a, cols = _alloc_with_columns(1)
    student = UserFactory()
    services.add_students_to_group(cols[0], [student])
    skipped = services.set_allocation_assignments(
        cols, {student.pk: (9999, str(cols[0].pk))}
    )
    assert skipped == []
    assert GroupMembership.objects.filter(group=cols[0], student=student).exists()


def test_added_by_is_recorded():
    a, cols = _alloc_with_columns(1)
    actor = UserFactory(is_staff=True)
    student = UserFactory()
    services.set_allocation_assignments(
        cols, {student.pk: (cols[0].pk, "")}, added_by=actor
    )
    membership = GroupMembership.objects.get(group=cols[0], student=student)
    assert membership.added_by_id == actor.pk
```

Check `notifications.models.Notification`'s recipient field name before writing that import; adjust the two notification assertions to the real field if it differs.

- [ ] **Step 2: Run and watch it fail**

```
uv run pytest tests/test_grouping_allocation_service.py -v
```

Expected: `AttributeError: module 'grouping.services' has no attribute 'allocation_columns_token'`.

- [ ] **Step 3: Implement the helpers**

Append to `grouping/services.py`:

```python
def allocation_columns(allocation):
    """The grid's columns: the allocation's non-archived groups, resolved ONCE
    per request and threaded through the token check, the value validation, and
    set_allocation_assignments.

    The redundant-looking `course=` filter is defence, not a fourth enforcement
    point: course scoping is deliberately not enforced against bulk-write paths,
    and the membership query below IS course-filtered — so a foreign-course
    column would render every affected row as unassigned and re-add on save."""
    return allocation.groups.filter(
        course=allocation.course, archived=False
    ).order_by("name")


def _token(group_ids):
    return ",".join(str(pk) for pk in sorted(int(pk) for pk in group_ids))


def allocation_columns_token(columns):
    return _token(c.pk for c in columns)


def allocation_state_tokens(columns, student_ids, memberships=None):
    """{student_id: token} over `columns`. `memberships` is {student_id: set[int]}
    of the student's group ids across the whole course, as the render path already
    bucketed them; a student ABSENT from it means the empty set (never a KeyError,
    never a re-query). Omitting it costs exactly ONE bulk query, never one per
    student."""
    column_ids = {c.pk for c in columns}
    if memberships is None:
        memberships = {}
        rows = GroupMembership.objects.filter(
            student_id__in=student_ids, group__in=columns
        ).values_list("student_id", "group_id")
        for student_id, group_id in rows:
            memberships.setdefault(student_id, set()).add(group_id)
    return {
        sid: _token(memberships.get(sid, set()) & column_ids) for sid in student_ids
    }


def allocation_row_students(allocation):
    """The grid's row set — called by BOTH the render path and the save path, so
    the two cannot drift. Arm 2 deliberately ignores `archived`: restricting it
    would make a student who is on the grid only through an archived column
    invisible while their membership survives."""
    by_cohort = student_users().filter(
        cohort_membership__cohort__in=allocation.cohorts.all()
    )
    assigned = student_users().filter(
        group_memberships__group__in=allocation.groups.filter(
            course=allocation.course
        )
    )
    # pk-membership OR, never `qs_a | qs_b`: student_users() ends in .distinct()
    # and OR-ing a distinct queryset with a non-distinct one raises "Cannot
    # combine a unique query with a non-unique query" (see
    # scoping.collections_visible_to's comment).
    return User.objects.filter(
        Q(pk__in=by_cohort.values("pk")) | Q(pk__in=assigned.values("pk"))
    )


@transaction.atomic
def set_allocation_assignments(columns, assignments, *, added_by=None):
    """assignments: {student_id: (target_group_id_or_None, was_token_or_None)},
    where the target is an **int pk** or None — NEVER the raw posted string. The
    caller coerces; `column_by_id`'s keys are ints, so a str "12" would miss the
    dict and the row would be silently omitted.

    A row absent from the POST is OMITTED FROM THIS DICT ENTIRELY; within it, a
    target of None means "— none —". Returns the skipped student ids.

    Three rules, first match wins:
      1. no-op   — current_token == token_of(target); never written, never
                   reported, EVEN IF the current token differs from `-was`.
      2. mismatch — current_token != was_token (was_token None counts) → skip
                   and report.
      3. write   — add to the target FIRST, then remove from the other columns.
    """
    column_by_id = {c.pk: c for c in columns}
    student_ids = list(assignments)
    students = {u.pk: u for u in User.objects.filter(pk__in=student_ids)}
    current = allocation_state_tokens(columns, student_ids)
    skipped = []
    for student_id, (target_id, was_token) in assignments.items():
        student = students.get(student_id)
        if student is None:
            continue
        target = column_by_id.get(target_id) if target_id is not None else None
        if target_id is not None and target is None:
            continue  # out-of-range: omitted, NOT unassigned
        now = current.get(student_id, "")
        # Rule 1 — whole-token comparison. "already in the target group" must not
        # read as a no-op, or a conflict row ("12,15" posted with 12) never resolves.
        wanted = str(target.pk) if target is not None else ""
        if now == wanted:
            continue
        # Rule 2
        if was_token is None or now != was_token:
            skipped.append(student_id)
            continue
        # Rule 3 — ADD BEFORE REMOVE. Removing first makes recompute_enrollment
        # see the student as unreachable and DELETE their group-sourced
        # Enrollment; the following add re-creates it and re-fires
        # notify_enrolled, so every ordinary move would emit a spurious
        # "you were enrolled" notification.
        if target is not None:
            add_students_to_group(target, [student], added_by=added_by)
        for column in columns:
            if target is not None and column.pk == target.pk:
                continue
            if str(column.pk) in now.split(","):
                remove_students_from_group(column, [student])
    return skipped
```

No new imports are needed: `Q` is already imported at `grouping/services.py:8`, and these
helpers reach the model only through `allocation.groups` / `allocation.cohorts`, so do **not**
import `Allocation` — an unused import is an F401 to unpick at Task 10's lint gate.

- [ ] **Step 4: Run and watch it pass**

```
uv run pytest tests/test_grouping_allocation_service.py -v
```

Expected: 14 passed.

- [ ] **Step 5: Falsify**

1. Widen the **membership source**, not the iteration — replace the whole `for column in columns:` removal block with:
   ```python
   for m in GroupMembership.objects.filter(
       student=student, group__course=columns[0].course
   ).exclude(group=target):
       remove_students_from_group(m.group, [student])
   ```
   → `test_writes_only_inside_the_rectangle_and_the_write_lands` must FAIL. (Merely iterating more groups is **inert**: each removal is guarded by `if str(column.pk) in now.split(",")`, and `now` is computed over `columns` only, so an extra column is never removed. The rectangle guarantee lives in the token, so the mutant has to attack the token.)
2. Replace `add_students_to_group` / `remove_students_from_group` with direct `GroupMembership` writes → `test_none_target_removes_membership_and_drops_group_sourced_enrollment` must FAIL.
3. **No service-level mutant exists for `test_a_row_absent_from_assignments_is_untouched`, and that is a deliberate, stated exception** rather than an omission. Two plausible mutants are both *inert*: rebuilding from `current` iterates nothing (it is keyed off the `{}` the test passes), and rebuilding from column memberships supplies no `was_token`, so rule 2 skips the row and nothing is written either way. Making it bite would require the mutant to *also* synthesise `was_token` from a recomputed `current` — a three-part change that no plausible implementer slip resembles. Treat this test as a consistency check; its live falsification is Task 7's `test_an_absent_row_key_is_not_read_as_none`, at the layer where the omission-versus-`""` decision is actually made.
4. Change rule 1 to `if target is not None and str(target.pk) in now.split(","):` → `test_conflict_row_resolves_when_a_column_is_picked` must FAIL.
5. Delete **rule 2 entirely** (fall straight from the no-op check into the write) → `test_guard_skips_a_moved_row_and_reports_it` **and** `test_a_none_was_token_is_a_mismatch_not_an_unguarded_write` must FAIL. This is spec row 15's "ignore the `-was` field", and it is the only mutant that falsifies the guard itself. (Dropping just the `was_token is None` clause is **inert** — `now` is always a `str`, so `now != None` is unconditionally true and the clause is pure documentation. Row 17's live mutant is at the view level, in Task 7.)
6. Move rule 2 above rule 1 → `test_a_no_op_row_is_neither_written_nor_reported_even_when_the_token_moved` must FAIL.
7. Swap the add and the remove in rule 3 → `test_moving_between_columns_keeps_the_enrollment_and_fires_no_new_notification` must FAIL.

8. Sort the token lexically (`sorted(str(pk) for pk in group_ids)`) → `test_columns_token_sorts_numerically_not_lexically` must FAIL.
9. Restrict `allocation_row_students`' arm 2 to `archived=False` → `test_row_students_union_includes_out_of_cohort_and_archived_column_members` must FAIL.
10. Replace the out-of-range `continue` with `target = None` → `test_an_out_of_range_target_keeps_the_membership` must FAIL.
11. Drop `added_by=added_by` from the `add_students_to_group` call inside the service → `test_added_by_is_recorded` must FAIL. (Spec row 17b names *two* mutants; Task 7 carries the view-side one. Dropping only the service forward leaves `added_by = NULL` on every grid-created membership while the view still passes the argument.)
12. Replace `student_users()` with `User.objects` in `allocation_row_students`' arm 2 → `test_row_students_excludes_staff` must FAIL.
13. Drop the `& column_ids` intersection in `allocation_state_tokens` → a new
    `test_state_token_intersects_a_passed_membership_map` must FAIL. That test must call the
    helper **with an explicit map**, because the `memberships is None` branch already filters
    on `group__in=columns`, so the intersection is only live for a caller-supplied
    (course-wide) map — a DB-fixture change cannot reach it:
    ```python
    def test_state_token_intersects_a_passed_membership_map():
        a, cols = _alloc_with_columns(1)
        outside = GroupFactory(course=a.course)      # same course, not a column
        s = UserFactory()
        tokens = services.allocation_state_tokens(
            cols, [s.pk], memberships={s.pk: {cols[0].pk, outside.pk}}
        )
        assert tokens[s.pk] == str(cols[0].pk)
    ```

Restore each by hand.

- [ ] **Step 6: Commit**

```bash
git add grouping/services.py tests/test_grouping_allocation_service.py
git commit -m "feat(grouping): allocation grid services with an optimistic row guard"
```

---

### Task 7: The grid view and template

**Files:**
- Modify: `grouping/urls.py`, `grouping/views.py`, `config/settings/base.py`
- Create: `templates/grouping/allocation_assign.html`
- Modify: `templates/grouping/allocation_list.html` (point the name at the grid), `templates/grouping/group_form.html` (link to the grid on a saved, allocated group)
- Test: `tests/test_grouping_allocation_grid.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: URL name `grouping:allocation_assign`; template context keys `columns`, `sections`, `summary`, `columns_token`.

Read spec §"The assignment grid" and §"Data flow" in full before starting.

- [ ] **Step 1: Write the failing grid tests**

Create `tests/test_grouping_allocation_grid.py` covering: the 404/403 matrix; the row union including a cohort-less student; the three row states and the "also in" note; the whole-allocation summary with two cohorts plus an outsider; the forged-student rejection; the column-set abort (including one POST with **no `columns` key at all**, against an allocation whose current token is `""` — the only fixture where coercing an absent field to `""` is visible); an attached cohort with zero students still rendering its heading with the "(no students)" note; and a bounded query count. Follow the assertion discipline the spec's test table specifies.

The file opens with:

```python
import pytest
from django.urls import reverse

from grouping import services
from grouping.models import CohortMembership
from grouping.models import GroupMembership
from tests.factories import AllocationFactory
from tests.factories import CohortFactory
from tests.factories import CohortMembershipFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_ca
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_teacher

pytestmark = pytest.mark.django_db
```

Four of its cases must be written exactly as below — they are the ones whose setup is
load-bearing, and three of them cover contract edges that live in the **view**, not the
service, so no Task 6 test can reach them:

```python
def test_a_posted_assignment_lands_through_the_view(client):
    """The only end-to-end proof that a save writes anything. Without it the
    int()-coercion bug drops every row behind a success redirect."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{student.pk}": str(col.pk),
            f"student-{student.pk}-was": "",
        },
    )
    assert resp.status_code == 302
    assert GroupMembership.objects.filter(group=col, student=student).exists()


def test_an_absent_row_key_is_not_read_as_none(client):
    """Spec row 17a — the contract's sharpest edge, and it lives in the VIEW's
    dict-building, not in the service (which cannot distinguish a key that was
    never built). A conflict row posts no radio at all."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    cols = [GroupFactory(course=a.course, allocation=a, name=f"c{i}") for i in range(2)]
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    services.add_students_to_group(cols[0], [student])
    services.add_students_to_group(cols[1], [student])
    token = ",".join(str(pk) for pk in sorted(c.pk for c in cols))
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token(cols),
            f"student-{student.pk}-was": token,   # the hidden field posts; the radio does not
        },
    )
    assert resp.status_code == 302
    assert GroupMembership.objects.filter(student=student).count() == 2


def test_a_missing_was_field_is_skipped_not_written(client):
    """Spec row 17's LIVE mutant is here, not in the service: the service can only
    see the None it was handed, so the `.get(key, "")` slip has to be caught at
    the layer that reads the POST. Load-bearing: the student must be in NO column
    (true token ""), or the mutant's "" coincidentally mismatches and skips too."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{student.pk}": str(col.pk),   # no -was field at all
        },
    )
    assert resp.status_code == 302
    assert not GroupMembership.objects.filter(group=col, student=student).exists()


def test_added_by_is_recorded_through_the_view(client):
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{student.pk}": str(col.pk),
            f"student-{student.pk}-was": "",
        },
    )
    membership = GroupMembership.objects.get(group=col, student=student)
    assert membership.added_by_id == pa.pk


def test_a_student_on_the_grid_only_via_an_archived_column_can_be_assigned(client):
    """Spec row 25c. The failure is completely silent — the row-set branch that
    would drop them is the one place the design deliberately says nothing."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    live = GroupFactory(course=a.course, allocation=a, name="live")
    archived = GroupFactory(course=a.course, allocation=a, name="old", archived=True)
    student = UserFactory()                       # in NO attached cohort
    services.add_students_to_group(archived, [student])
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([live]),
            f"student-{student.pk}": str(live.pk),
            f"student-{student.pk}-was": "",
        },
    )
    assert resp.status_code == 302
    assert GroupMembership.objects.filter(group=live, student=student).exists()
```

The 404/403 matrix needs one fixture neither factory can supply. After Task 2, `make_ca`
grants **all four** allocation permissions alongside `change_group`, and `make_teacher`
grants none — so spec row 20's "holder of `change_group` without `change_allocation`" (which
must 404 from the scoped lookup, not 403 from the decorator) has to be built by hand, using
the recipe `tests/test_groups_tabs.py::test_my_groups_no_strip_for_view_collection_only_user`
already demonstrates:

```python
def test_change_group_without_change_allocation_gets_404(client):
    from django.contrib.auth.models import Permission

    user = make_login(client, "grid_partial")
    user.user_permissions.add(
        Permission.objects.get(codename="change_group", content_type__app_label="grouping")
    )
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    a = AllocationFactory()
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    assert resp.status_code == 404      # NOT 403 — the decorator passes, scoping does not
```

and these two, whose fixtures are load-bearing in the other direction:

```python
def test_cohort_less_student_renders_without_500(client):
    """Load-bearing: signals.ensure_cohort_membership auto-creates a membership
    on user create whenever a Default cohort exists, so the fixture must DELETE
    it — otherwise the student has one, renders under "outside these cohorts"
    with data-cohort="" anyway, and the mutant's direct relation read never raises."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    student = UserFactory()
    services.add_students_to_group(col, [student])
    CohortMembership.objects.filter(user=student).delete()
    assert not CohortMembership.objects.filter(user=student).exists()
    resp = client.get(reverse("grouping:allocation_assign", args=[a.pk]))
    assert resp.status_code == 200
    assert 'data-cohort=""' in resp.content.decode()


def test_column_set_change_aborts_the_whole_save(client):
    """Fixture is load-bearing: the student must be IN the row set (via an
    attached cohort), or they fall outside it and the write would not land even
    without the column-set check — leaving only status_code carrying the test."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    cohort = CohortFactory()
    a.cohorts.add(cohort)
    student = UserFactory()
    CohortMembershipFactory(user=student, cohort=cohort)
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": "999999",              # not the current column set
            f"student-{student.pk}": str(col.pk),
            f"student-{student.pk}-was": "",
        },
    )
    assert resp.status_code == 200            # re-render, not a redirect
    assert not GroupMembership.objects.filter(group=col, student=student).exists()
    assert "changed while you were editing" in resp.content.decode()


def test_a_forged_student_outside_the_row_set_is_ignored(client):
    """The forgery MUST carry a matching -was (""), or the guard skips the row
    even under the mutant and nothing is written either way."""
    pa = make_pa(client)
    a = AllocationFactory(course=CourseFactory(owner=pa))
    col = GroupFactory(course=a.course, allocation=a)
    outsider = UserFactory()                  # in no cohort of this allocation
    CohortMembership.objects.filter(user=outsider).delete()
    resp = client.post(
        reverse("grouping:allocation_assign", args=[a.pk]),
        {
            "columns": services.allocation_columns_token([col]),
            f"student-{outsider.pk}": str(col.pk),
            f"student-{outsider.pk}-was": "",
        },
    )
    assert resp.status_code == 302
    assert not GroupMembership.objects.filter(group=col, student=outsider).exists()
```

- [ ] **Step 2: Run and watch it fail**

```
uv run pytest tests/test_grouping_allocation_grid.py -v
```

Expected: `NoReverseMatch: 'allocation_assign'`.

- [ ] **Step 3: Raise the form-field ceiling**

In `config/settings/base.py`:

```python
# The allocation grid posts two fields per student row (the radio's single value
# plus its hidden state token) plus a small fixed overhead, so Django's default
# of 1000 would 400 with TooManyFieldsSent past roughly 500 students — losing
# every pending edit on the one screen built for a whole year group.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000
```

- [ ] **Step 4: Add the URL and the view**

```python
    path(
        "manage/allocations/<int:pk>/assign/",
        views.allocation_assign,
        name="allocation_assign",
    ),
```

Add these imports to `grouping/views.py` — none is present today: **`import re`** (stdlib, so it goes in its own group above the `django.*` block per the repo's isort profile — the module-level `COLUMNS_TOKEN_RE` below would otherwise `NameError` at import and take down *every* grouping view, not just the grid), `from django.contrib import messages`, `from django.utils.translation import ngettext` (not the `_lazy` variant; the message is formatted immediately), `from grouping.models import CohortMembership`, `from grouping.models import GroupMembership`. (`transaction` was added in Task 4.)

The view is gated on `grouping.change_group` (it writes `GroupMembership`, not `Allocation`) and scoped through `allocations_manageable_by`. Build the context in one place so GET and the POST re-render share it:

```python
def _allocation_grid_context(allocation):
    columns = list(services.allocation_columns(allocation))
    students = list(
        services.allocation_row_students(allocation).order_by("username")
    )
    student_ids = [s.pk for s in students]
    # ONE bucketed membership query for row states AND the "also in" notes.
    memberships = {}
    also_in = {}
    column_ids = {c.pk for c in columns}
    rows = GroupMembership.objects.filter(
        student_id__in=student_ids, group__course=allocation.course
    ).select_related("group")
    for row in rows:
        memberships.setdefault(row.student_id, set()).add(row.group_id)
        if row.group_id not in column_ids:
            also_in.setdefault(row.student_id, []).append(row.group.name)
    tokens = services.allocation_state_tokens(columns, student_ids, memberships)
    # The cohort bucket comes from an explicit id map: user.cohort_membership
    # raises RelatedObjectDoesNotExist in Python when absent (templates silence
    # it, which is why group_form.html's dereference looks safe).
    cohort_of = dict(
        CohortMembership.objects.filter(user_id__in=student_ids).values_list(
            "user_id", "cohort_id"
        )
    )
    # id -> slug for the ATTACHED cohorts only. A student whose cohort id is
    # absent from cohort_of (no membership at all) OR present but not attached to
    # this allocation both go to "outside these cohorts" with data_cohort="" —
    # the second case is easy to miss and would otherwise produce a stray section
    # or a KeyError.
    attached = {c.pk: c for c in allocation.cohorts.all().order_by("-is_default", "name")}
    ...
    return {...}
```

Group students into sections (one per attached cohort in `-is_default, name` order, then "outside these cohorts"), sorting each section by `polish_sort_key(s.sort_name)` then `username`; derive each row's `state` (`assigned` / `unassigned` / `conflict`) from `len(memberships.get(sid, set()) & column_ids)`; and compute the summary counts over **all** rows, never a filtered subset.

**Return exactly this shape** — Task 8's JS and the template both code against it, so it is a
fixed contract, not an illustration:

```python
    return {
        "allocation": allocation,
        "columns": columns,                  # list[Group], the resolved sequence
        "columns_token": services.allocation_columns_token(columns),
        "sections": sections,                # list of {"label", "cohort_slug", "rows"}
        "summary": {                         # whole-allocation counts, never filtered
            "total": ..., "assigned": ..., "unassigned": ..., "conflict": ...,
        },
        "hub_tab": "allocations",
    }
```

and each entry in a section's `rows` is:

```python
    {
        "student": student,
        "state": "assigned" | "unassigned" | "conflict",
        "selected_id": <column pk or None>,   # None for unassigned AND for conflict
        "check_none": <bool>,                 # True ONLY when state == "unassigned"
        "token": tokens[student.pk],          # the hidden -was value
        "also_in": also_in.get(student.pk, []),
        "data_name": student.sort_name.lower(),
        "data_cohort": <cohort slug or "">,   # "" for the outside section
    }
```

The summary element carries its translated labels as
`data-label-total`, `data-label-assigned`, `data-label-unassigned`, `data-label-conflict`;
the script substitutes numbers only. Rows carry `data-grid-row`, the summary carries
`data-grid-summary`, and the two filter inputs carry `data-grid-search` and
`data-grid-cohort`. The cohort select's options are: "All cohorts" with `value=""`, then one
per attached cohort with `value="<slug>"`, then "Outside these cohorts" with
**`value="__none__"`** — that sentinel is load-bearing markup (spec row 35c's mutant is
"give that option `value=""`", which would make it a duplicate of "All cohorts").

The POST path is **wrapped in a single `transaction.atomic()`** (spec §Saving's opening line —
`set_allocation_assignments` has its own decorator, but the column-set check and the row-set
recompute must be inside the same transaction, since that window is exactly what the
column-set check exists to close). Resolve `columns = services.allocation_columns(allocation)`
and `row_students = services.allocation_row_students(allocation)` **once** at the top and
thread the same objects through the token comparison, the `assignments` build, and the
service call. Inside the transaction, in order: the column-set check, the server-side row set,
the `assignments` build, then the service call with
`added_by=request.user`, then `messages.warning` through `ngettext` for any skipped rows,
naming them in `polish_sort_key` order.

The column-set check is not just a comparison — the **absent** and **malformed** cases must
abort too, and coercing either to `""` would compare *equal* to the token of an allocation
with no non-archived groups:

```python
    COLUMNS_TOKEN_RE = re.compile(r"^$|^\d+(,\d+)*$")   # module level

    raw_columns = request.POST.get("columns")           # None when absent
    if raw_columns is None or not COLUMNS_TOKEN_RE.match(raw_columns):
        return _abort_stale(request, allocation)        # same path as a mismatch
    if raw_columns != services.allocation_columns_token(columns):
        return _abort_stale(request, allocation)
```

where `_abort_stale` re-renders from **fresh** server state (fresh columns, fresh tokens, a
fresh `columns` field), discards the posted choices, and shows "the allocation's groups
changed while you were editing, so nothing was saved — please redo your changes."

Building `assignments` is where the two sharpest edges of the contract live — write it
exactly like this:

```python
    assignments = {}
    for student in row_students:                      # the SERVER's row set
        key = f"student-{student.pk}"
        if key not in request.POST:
            continue                                  # absent → omit entirely
        raw = request.POST.get(key)
        was = request.POST.get(f"{key}-was")           # missing → None → mismatch
        if raw == "":
            target_id = None                           # the "— none —" radio
        else:
            try:
                target_id = int(raw)                   # ints, never the raw string:
            except (TypeError, ValueError):            # column_by_id is keyed on pks
                continue                               # non-integer → omit, not unassign
        assignments[student.pk] = (target_id, was)
```

`request.POST.get` returns `None` for an absent field and `""` for the none-radio; collapsing
those two into one `None` target mass-unassigns every conflict row on every save. And
`int()` is not optional — a posted `"12"` would miss `column_by_id`'s int keys, so **every**
assignment would be dropped behind a success redirect.

- [ ] **Step 5: Write the template**

**Which radio is checked is load-bearing, and `selected_id` alone does not say.** Both
`unassigned` and `conflict` carry `selected_id = None`, but the spec requires `— none —`
**checked** on unassigned rows and **no radio checked at all** on conflict rows. Hence the
separate `check_none` flag: the template writes `checked` on the `— none —` radio only when
`row.check_none` is true. Keying the template off `selected_id` being falsy would check it on
conflict rows too — and a checked `— none —` posts `student-<pk>=""`, which the view maps to a
`None` target and the service turns into *removal of both memberships*. That is the exact
mass-unassign of every conflict row that the omission-versus-`""` contract exists to prevent,
and no forged-POST test would catch it, because the bug is in what the browser sends.
Assert it: a rendered conflict row's radio group contains no `checked` attribute.

**Empty sections are rendered, not filtered out.** A section whose `rows` is empty still
appears, with a translated "(no students)" note beside its heading — the spec requires it so
an admin can see the cohort *is* attached rather than wondering whether they attached it.
Keep such sections in the `sections` list; do not drop them when building the context. This
is separate from the three grid-level empty states below.

`templates/grouping/allocation_assign.html`: the tabs strip with `hub_tab="allocations"`, back/edit links, the summary line with its labels in `data-*` attributes (count-invariant shape: "Students: 84 · Assigned: 72 · Unassigned: 11 · Conflicts: 1"), the filter bar, then a `<table>` with a sticky header row and sticky name column. Each row carries `data-name`, `data-cohort`, and a state class; each radio carries an `aria-label` of "<student> → <group>"; each row renders its hidden `student-<pk>-was`; and the form renders one hidden `columns` field. Empty states for no-cohorts / no-students / no-columns.

- [ ] **Step 6: Wire the grid's two entry points**

Both are listed in this task's Files and neither happens by itself:

1. `templates/grouping/allocation_list.html` — re-point the name cell from
   `allocation_edit` (where Task 5 parked it) to
   `{% url 'grouping:allocation_assign' a.pk %}`. Without this the grid has no
   entry point from the list at all. Add an assertion to
   `test_list_is_scoped_and_honours_the_archived_toggle` that the list body
   contains `reverse("grouping:allocation_assign", args=[mine.pk])`.
2. `templates/grouping/group_form.html` — on a saved group that has an
   allocation, render a link to that allocation's grid
   (`{% if not creating and group.allocation_id %}`), per spec §Templates.

- [ ] **Step 7: Run, falsify, commit**

```
uv run pytest tests/test_grouping_allocation_grid.py tests/test_grouping_allocation_views.py -v
```

Mutants (each must go RED): scope with `Allocation.objects.all()`; drop `raise_exception=True`; drop the outsider union arm; build the row set from the POST keys; drop the column-set check; **treat an absent `columns` field as `""`** (→ the no-`columns` test against a groups-less allocation must FAIL); classify a two-membership row as assigned; narrow "also in" to `allocation__isnull=True`; count the summary from the first section only; read `user.cohort_membership.cohort` directly; **drop the `memberships=` argument at the `allocation_state_tokens` call site**, and separately **fetch each row's "also in" memberships individually** (→ the `assertNumQueries` test must FAIL under each — without these two the implementer simply writes down whatever number the green run reports); **drop the `int()` coercion when building `assignments`** (→ `test_a_posted_assignment_lands_through_the_view` must FAIL); **collapse `request.POST.get`'s `None` and `""` to a `None` target** (→ `test_an_absent_row_key_is_not_read_as_none` must FAIL); **read the token as `request.POST.get(f"{key}-was", "")`** (→ `test_a_missing_was_field_is_skipped_not_written` must FAIL); **drop `added_by=request.user`** (→ `test_added_by_is_recorded_through_the_view` must FAIL); **filter empty sections out of `sections`** (→ the "(no students)" heading test must FAIL); **key the `— none —` radio's `checked` off `not row.selected_id` instead of `row.check_none`** (→ the conflict-row rendering assertion must FAIL).

```bash
git add grouping/urls.py grouping/views.py config/settings/base.py templates/grouping/ tests/test_grouping_allocation_grid.py tests/test_grouping_allocation_views.py
git commit -m "feat(grouping): the allocation assignment grid"
```

---

### Task 8: Grid CSS and JavaScript

**Files:**
- Create: `grouping/static/grouping/css/allocation_grid.css`, `grouping/static/grouping/js/allocation_grid.js`
- Modify: `templates/grouping/allocation_assign.html` (load both)
- Test: `tests/test_e2e_allocation_grid.py`

**Interfaces:**
- Consumes: the markup contract from Task 7 (`data-name`, `data-cohort`, `[data-grid-row]`, `[data-grid-summary]`, `[data-grid-search]`, `[data-grid-cohort]`).
- Produces: no Python interface.

- [ ] **Step 1: Write the failing e2e tests** (`pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]`)

Cover: the cohort filter leaves the summary unchanged and a filtered-out row's `bounding_box()` is `None`; saving under a filter leaves hidden rows byte-identical and still posts their fields; the "Outside these cohorts" sentinel isolates only outsider rows; the name search matches `data-name` and not an "also in" note; picking a column on a conflict row clears both the conflict count and the row's own red treatment; **the live summary's labels stay Polish and grammatical after a radio change** (spec row 35b). **The mechanism matters:** the active language is *session*-based here — `core.signals.seed_language_on_login` writes `user.language` into `session[LANGUAGE_SESSION_KEY]` on every login and `core.middleware.SessionLocaleMiddleware` prefers that key over the cookie and `Accept-Language`. So a Playwright context created with `locale="pl-PL"` renders the login page in Polish and then flips to English the moment the test logs in. Set **`user.language = "pl"` and save it before driving the login form** (the same shape the dark-mode e2e uses for `user.theme`); `"pl"` is already in `get_site_config()["enabled_languages"]`, so no institution change is needed. Assert on **literal Polish text**, never on a comparison with the page's own `data-*` values — that comparison is locale-independent and passes under the mutant; and a full assign-two-students-and-save round trip where **one student starts in a different column** and the old group must lose them.

- [ ] **Step 2: Run and watch them fail** — `uv run pytest tests/test_e2e_allocation_grid.py -m e2e -v`

- [ ] **Step 3: Write the CSS** — sticky header row and sticky name column from `core/static/core/css/tokens.css` tokens with explicit dark-mode definitions and no raw hex. If rows carry any author `display`, pair it with `[hidden] { display: none !important }`.

- [ ] **Step 4: Write the JS** — live summary from the **pending selection** (checked radio → assigned, `— none —` → unassigned, nothing checked → conflict), substituting numbers into the template's `data-*` labels only; row-state classes and markers recomputed on the same rule; filters that only set `hidden` (never `disabled`) and hide a section heading when all its rows are hidden.

- [ ] **Step 5: Run, falsify, commit** — mutants per the spec's rows 35, 35a, 35b, 35c, 35d, 36, 37. In particular row 35b's: **compose the summary string from JavaScript literals instead of the `data-*` labels** — the only spec requirement whose violation (English leaking over the Polish page) no other listed test can see.

```bash
git add grouping/static/grouping/ templates/grouping/allocation_assign.html tests/test_e2e_allocation_grid.py
git commit -m "feat(grouping): allocation grid styling and live client behaviour"
```

---

### Task 9: The roster add-all checkbox and the allocation-select filter

**Files:**
- Modify: `grouping/static/grouping/js/roster_filter.js`, `templates/grouping/group_form.html`, `core/static/core/css/app.css` (or a scoped rule in the template's block)
- Test: `tests/test_e2e_roster_add_all.py`

**Interfaces:**
- Consumes: the existing `[data-roster]` / `[data-roster-filter]` / `[data-roster-list]` contract.
- Produces: `[data-roster-all]`; `initAllocationFilter()`.

Read spec §"The add-all checkbox" and the last paragraph of §"Rendering the allocation select".

- [ ] **Step 1: Write the failing e2e tests** covering: visible on a freshly loaded form with no filter (the `[data-roster-count]` precedent is unhidden only *while filtering* — copying it would hide add-all until a filter is applied); with JS disabled its `bounding_box()` is `None`; ticking under a cohort filter ticks only the filtered students; **unticking** clears only the filtered students; the tri-state including unchecked-and-disabled at zero visible; the click-from-indeterminate direction (tick all, untick one, click again → the rest end up ticked, never cleared); the "Added" counter updating after a sweep; the allocation select filtering on course change and resetting a stale selection; and the init pass hiding every optgroup on a freshly loaded create form.

**The last two need spec row 37a's fixture and assertion technique, which do not appear in the sections named above — read that row.** Fixture: act as a **PA with two courses**, each carrying one non-archived allocation; select course A, pick one of A's allocations, then switch the course select to B. A single-course fixture leaves no non-matching optgroup to hide and no way to make a selection stale, so *both* mutants survive. Assertion: **never `bounding_box()`** — the options and optgroups of a collapsed `size=1` select are not laid out in the page (their popup is browser UI), so it returns `None` for hidden and visible alike. Evaluate instead:

```js
[...select.querySelectorAll('optgroup')].filter(g => !g.hidden).map(g => g.label)
```

and assert it equals exactly course B's label. (`bounding_box()` stays correct for the `<label>` and `<tr>` assertions in rows 30c and 35.)

- [ ] **Step 2: Run and watch them fail** — `uv run pytest tests/test_e2e_roster_add_all.py -m e2e -v`

- [ ] **Step 3: Implement the add-all control**

Template: a `<label hidden data-roster-all-wrap>` inside each `[data-roster-filter]`, holding
an unnamed `<input type="checkbox" data-roster-all>` and the translated text
**"Select all shown"** (the e2e locates the control by that label). Give the wrapper a class with **no**
author `display` (or pair it with `[hidden] { display: none }`) — `.roster-filter__field` is
`display: flex` at `app.css:210`, which outranks the UA `[hidden]` rule and would leave the
control visible with JS off.

`roster_filter.js`: `syncAddAll()` in strict precedence order — visible count 0 →
`disabled = true, checked = false, indeterminate = false`, return; otherwise
`disabled = false`, then unchecked / checked / (`indeterminate = true` **and**
`checked = false`). Unhide the wrapper unconditionally on init. Call `updateSelected()`
explicitly after mutating checkboxes (a scripted `.checked` fires no `change`), and call
`syncAddAll()` from both `applyFilter()` and the list's `change` handler.

- [ ] **Step 4: Implement the allocation filter**

`initAllocationFilter()`, invoked once from inside the IIFE (not from `initRoster` — the
select sits outside every `[data-roster]`), reading `[data-allocation-select]` and
`form.querySelector('[name="course"]')`. Return immediately if either is missing or the
course select is `disabled` (the edit form). Then, on init **and** on every `change`:

* **the primary rule** — hide each `<optgroup>` and its `<option>`s whose `data-course` does
  not equal the course select's current value, and show the matching ones;
* with **no** course selected, hide every `<optgroup>`;
* never hide the empty `— none —` option (it is how a group is detached);
* reset the select to `""` when the currently-selected option's `data-course` no longer
  matches.

- [ ] **Step 5: Re-run the existing roster e2e before committing**

```
uv run pytest tests/test_e2e_grouping.py -m e2e -v
```

Must pass unchanged. `tests/test_e2e_grouping.py` already covers this exact file —
`test_roster_search_filters_and_added_count_is_live`,
`test_added_count_shows_saved_baseline_on_unsaved_changes`,
`test_teacher_picker_search_filters_rows`, `test_create_group_and_add_student_via_ui` — and
this task restructures the IIFE. Any throw inside it (an `initAllocationFilter()` reaching a
null course select on the edit form, say) kills `initRoster` for the whole page and reddens
all four. Without this step the regression first surfaces at Task 10's whole-suite gate,
several commits later, where an e2e failure is expensive to attribute. Same rule as Task 4
Step 7: **if it fails, fix the JS, not the test.**

- [ ] **Step 6: Run, falsify, commit** — the nine mutants, each named with the test it must redden:

| Spec row | Mutant | Test that must go RED |
|---|---|---|
| 30a | unhide the control from `applyFilter()` instead of on init | visible on a freshly loaded form |
| 30c | put the control on `.roster-filter__field` (author `display` beats `[hidden]`) | JS-off `bounding_box()` is `None` |
| 31 | iterate all items instead of visible ones | filtered add-all ticks only the filtered |
| 32 | clear all items regardless of `hidden` | filtered untick clears only the filtered |
| 33 | derive state from the whole list / skip the zero-visible early return | indeterminate, and unchecked+disabled at zero visible |
| 33a | leave `checked` untouched in the indeterminate branch | click-from-indeterminate adds, never clears |
| 34 | remove the explicit `updateSelected()` call | the "Added" counter after a sweep |
| 36a | bind to `change` only, omitting the init pass | freshly loaded create form hides every optgroup |
| 37a | omit the stale-selection reset | changing course resets the select to `""` |

```bash
git add grouping/static/grouping/js/roster_filter.js templates/grouping/group_form.html core/static/core/css/app.css tests/test_e2e_roster_add_all.py
git commit -m "feat(grouping): add-all roster control and course-scoped allocation picker"
```

---

### Task 10: Translations, lint, and the branch gate

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.mo`

- [ ] **Step 1: Regenerate the Polish catalogue**

```
uv run python manage.py makemessages -l pl
```

Review the diff: `makemessages` pre-fills fuzzy translations, and a fuzzy entry is a *wrong* translation that ships silently. Clear every `#, fuzzy` marker on the new entries and translate them properly, then:

```
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 2: Lint**

```
uv run ruff check --no-cache .
uv run ruff format --check .
```

Both must pass. `--no-cache` matters: a stale cache hides the warning.

- [ ] **Step 3: Run the branch gate**

```
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/ integrations/
uv run pytest tests/ -m e2e -n 2
```

**Do not add `-q`.** `pyproject.toml` already sets `addopts = "-q -m 'not e2e'"`; a second
`-q` stacks to quiet level −2, which suppresses the final `N passed / N failed` summary
altogether — so the grep below would have nothing to find and a long run would read as a
hang.

`integrations/` is in the gate deliberately: `integrations/tests/test_form_fields.py:40`
constructs `GroupForm()` and calls `form.save()`, both of which Task 4 rewrites, and the
`tests/`-only invocation would never run it.

**Grep the summary line** — a backgrounded pytest has reported exit 0 with failures in this
repo, so the exit code alone is not evidence:

```
grep -E "^=+ .*(passed|failed|error)|^FAILED|^ERROR"
```

Both runs must show zero failures.

- [ ] **Step 4: Commit**

```bash
git add locale/
git commit -m "chore(i18n): Polish catalogue for the allocation grid"
```

- [ ] **Step 5: Write the deployment notes into the PR body**

Two changes in this branch are invisible to every test and must be stated where a human will
read them before deploying:

1. **`python manage.py setup_roles` must be run after `migrate`.** The four new
   `grouping.*_allocation` permissions are assigned by `institution.roles.seed_roles()`,
   which runs only from that management command — editing the constants grants nothing on an
   already-migrated database. `tests/factories.py` calls `seed_roles()`, so the whole test
   suite passes either way; this is the one requirement in the change with no code and no
   test behind it.
2. **`DATA_UPLOAD_MAX_NUMBER_FIELDS` was raised to 5000** in `config/settings/base.py`, for
   the grid's two-fields-per-row POST.

Both belong in the PR description, not only in a commit message.

---

## Self-Review

**Spec coverage.** Model + guards → T1. Permissions + scoping → T2. `AllocationForm` → T3. `GroupForm` + views wiring → T4. CRUD + navigation + `group_list`/`group_form` surfacing → T5. Token/row-set/save services → T6. Grid view, template, settings ceiling → T7. Grid CSS/JS + grid e2e → T8. Add-all + allocation-select filter + their e2e → T9. i18n, lint, gate → T10. Every numbered row in the spec's test table maps to a task; the ones written out verbatim are those whose setup is load-bearing.

**Placeholders.** Tasks 7-9 give structure and the load-bearing assertions rather than every line of template, CSS, and Playwright code — those files are long and mechanical, and the spec pins their contracts precisely. Each still names its exact files, its markup contract, its context keys, and its mutants by name.

**Layer discipline.** Three contract edges live in the view, not the service, and therefore
cannot be falsified by any Task 6 test: the `int()` coercion of the posted target, the
absent-versus-`""` distinction when building `assignments`, and `added_by=request.user`.
Their tests are in Task 7 (`test_a_posted_assignment_lands_through_the_view`,
`test_an_absent_row_key_is_not_read_as_none`, `test_added_by_is_recorded_through_the_view`).

**Type consistency.** `allocation_columns`, `allocation_columns_token`, `allocation_state_tokens`, `allocation_row_students`, and `set_allocation_assignments` keep the same names and signatures across T6, T7, and the tests. `set_allocation_assignments` takes the resolved `columns` sequence (never the allocation) everywhere it appears.
