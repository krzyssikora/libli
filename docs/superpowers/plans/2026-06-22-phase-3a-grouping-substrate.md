# Phase 3a — Grouping Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cohort / group / collection grouping substrate so students can be organized, group membership drives course `Enrollment` (while progress is always preserved), and managers get the CRUD + roster screens to run it.

**Architecture:** A new `grouping` Django app holds five models (`Cohort`, `CohortMembership`, `Group`, `GroupMembership`, `Collection`). All enrollment side-effects flow through one service module (`grouping/services.py`) with `recompute_enrollment(student, course)` as the single sync point — never via membership signals (so batch ops dedupe). Object-level access is pure functions in `grouping/scoping.py`, layered on top of Django model permissions seeded by an extended `seed_roles()`. Views are function-based, mirroring `courses/views_manage.py`.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL, pytest + pytest-django + factory_boy, Playwright (e2e), ruff. Server-rendered templates extending `templates/base.html`; token-driven CSS (no Bootstrap/React).

## Global Constraints

- **Test runner:** `uv run pytest` (settings `config.settings.test`). e2e is excluded by default; run e2e with `uv run pytest -m e2e`.
- **Lint/format gate (CI):** every task ends by running `uv run ruff format .` **and** `uv run ruff check .` — CI runs `ruff format --check`, so formatting (not just linting) must pass.
- **Tests live in `tests/`** (centralized, not per-app); factories in `tests/factories.py` (the single import surface for tests).
- **i18n:** all user-facing strings use `gettext_lazy as _` in Python and `{% trans %}` / `{% blocktrans %}` in templates. UI languages are EN/PL.
- **RBAC:** never branch on a role *name* in app logic. Gate views with Django model permissions (`@permission_required(..., raise_exception=True)`), then narrow rows with `grouping/scoping.py`. The convention for "is Platform Admin" is `user.has_perm("courses.change_course")` (a PA-only perm), exactly as `courses/views_manage.py:course_list` does.
- **Permissions are seeded by `setup_roles`, never by a migration `RunPython`.** Auto-generated `Permission` rows don't exist until `post_migrate` fires after the run; `seed_roles()` in a migration would raise `Permission.DoesNotExist`. Deploy/DoD order: `migrate` → `setup_roles`.
- **Responsive + light/dark** apply to every new view (inherited from `base.html` + token CSS).
- **`Enrollment` is unchanged schema-wise** — `courses.Enrollment` already has `source ∈ {manual, group, self}` and `UniqueConstraint(student, course)`. 3a only adds write paths.

---

### Task 1: Scaffold the `grouping` app + models + initial migration

**Files:**
- Create: `grouping/__init__.py`
- Create: `grouping/apps.py`
- Create: `grouping/models.py`
- Create: `grouping/admin.py` (empty registrations placeholder; keep minimal)
- Create: `grouping/migrations/__init__.py`
- Create: `grouping/migrations/0001_initial.py` (generated)
- Modify: `config/settings/base.py` (add `"grouping"` to `INSTALLED_APPS`)
- Modify: `tests/factories.py` (add grouping factories)
- Test: `tests/test_grouping_models.py`

**Interfaces:**
- Produces: models `grouping.models.Cohort`, `CohortMembership`, `Group`, `GroupMembership`, `Collection`.
  - `Cohort(name, slug, is_default, archived, created)`; `Cohort.save()` auto-generates `slug` (slugify + numeric suffix; reserves `default` for the system cohort). Partial unique constraint `uniq_single_default_cohort` ⇒ at most one `is_default=True`.
  - `Group(name, course→courses.Course CASCADE, teachers M2M→User, archived, created)`; `Group.save()` raises `ValidationError` if `course` changes on an existing row (immutable after create).
  - `Collection(name, course→courses.Course CASCADE, owner→User CASCADE, groups M2M→Group, archived, created)`; `Collection.save()` raises `ValidationError` if `course` changes while `groups.exists()`.
  - `CohortMembership(user OneToOne→User, cohort FK, assigned_at, assigned_by→User SET_NULL)`.
  - `GroupMembership(group FK, student FK→User, added_at, added_by→User SET_NULL)`; `UniqueConstraint(group, student)`.
- Produces (factories): `CohortFactory`, `GroupFactory`, `CollectionFactory`, `CohortMembershipFactory`, `GroupMembershipFactory` in `tests/factories.py`.

- [ ] **Step 1: Create the app package files**

`grouping/__init__.py`: empty file.

`grouping/apps.py`:
```python
from django.apps import AppConfig


class GroupingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "grouping"

    def ready(self):
        # Registers the post_save→default-cohort receiver (added in Task 2).
        from grouping import signals  # noqa: F401
```

`grouping/admin.py`:
```python
# Admin registrations are intentionally minimal for 3a; management happens
# through the dedicated /manage/ surfaces, not Django admin.
```

`grouping/migrations/__init__.py`: empty file.

- [ ] **Step 2: Write `grouping/models.py`**

```python
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

# 'default' is permanently reserved for the system Default cohort's slug.
RESERVED_DEFAULT_SLUG = "default"


class Cohort(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    is_default = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="uniq_single_default_cohort",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_slug()
        super().save(*args, **kwargs)

    def _generate_slug(self):
        base = slugify(self.name) or "cohort"
        candidate = base
        n = 1
        # A non-default cohort may never claim the reserved 'default' slug.
        reserved = candidate == RESERVED_DEFAULT_SLUG and not self.is_default
        while (
            reserved
            or Cohort.objects.filter(slug=candidate).exclude(pk=self.pk).exists()
        ):
            n += 1
            candidate = f"{base}-{n}"
            reserved = False
        return candidate

    def __str__(self):
        return self.name


class CohortMembership(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cohort_membership",
    )
    cohort = models.ForeignKey(
        Cohort, on_delete=models.CASCADE, related_name="memberships"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self):
        return f"{self.user_id} in cohort {self.cohort_id}"


class Group(models.Model):
    name = models.CharField(max_length=200)
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="groups"
    )
    teachers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="taught_groups"
    )
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # A group's course is immutable after creation (see spec §2).
        if self.pk is not None:
            old_course_id = (
                Group.objects.filter(pk=self.pk)
                .values_list("course_id", flat=True)
                .first()
            )
            if old_course_id is not None and old_course_id != self.course_id:
                raise ValidationError(
                    _("A group's course cannot be changed after creation.")
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class GroupMembership(models.Model):
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="memberships"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="group_memberships",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group", "student"], name="uniq_groupmembership_group_student"
            )
        ]

    def __str__(self):
        return f"{self.student_id} in group {self.group_id}"


class Collection(models.Model):
    name = models.CharField(max_length=200)
    course = models.ForeignKey(
        "courses.Course", on_delete=models.CASCADE, related_name="collections"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_collections",
    )
    groups = models.ManyToManyField(Group, related_name="collections")
    archived = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # course is immutable once ANY group is attached (parity with the M2M
        # guard) — the guard triggers on "any groups attached", independent of
        # whether the new course would match those groups.
        if self.pk is not None:
            old_course_id = (
                Collection.objects.filter(pk=self.pk)
                .values_list("course_id", flat=True)
                .first()
            )
            if (
                old_course_id is not None
                and old_course_id != self.course_id
                and self.groups.exists()
            ):
                raise ValidationError(
                    _("A collection's course cannot be changed once groups are attached.")
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
```

- [ ] **Step 3: Register the app**

In `config/settings/base.py`, add `"grouping"` to `INSTALLED_APPS` immediately after `"courses"`:
```python
    "accounts",
    "institution",
    "courses",
    "grouping",
```

- [ ] **Step 4: Create a temporary no-op signals module so `ready()` imports cleanly**

`grouping/signals.py` (real receiver lands in Task 2; this keeps Task 1 importable):
```python
# Signal receivers for the grouping app. The default-cohort membership
# receiver is added in Task 2.
```

- [ ] **Step 5: Generate the initial migration**

Run: `uv run python manage.py makemigrations grouping`
Expected: creates `grouping/migrations/0001_initial.py` with the five models, the `uniq_single_default_cohort` partial constraint, the `uniq_groupmembership_group_student` constraint, and the two auto M2M through-tables (`Group.teachers`, `Collection.groups`).

- [ ] **Step 6: Add factories to `tests/factories.py`**

Append (and add the imports near the top with the other model imports). Optionally extend the existing re-export note comment block (`tests/factories.py` lines ~29–33) to mention the new `grouping` factories, keeping that doc accurate — purely cosmetic, not load-bearing.
```python
from grouping.models import Cohort
from grouping.models import CohortMembership
from grouping.models import Collection
from grouping.models import Group
from grouping.models import GroupMembership


class CohortFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cohort

    name = factory.Sequence(lambda n: f"Cohort {n}")


class CohortMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CohortMembership
        # Once Task 2's post_save signal lands, every UserFactory() user already
        # gets a Default-cohort membership. django_get_or_create makes this factory
        # update that existing OneToOne row instead of colliding on a duplicate.
        django_get_or_create = ("user",)

    user = factory.SubFactory(UserFactory)
    cohort = factory.SubFactory(CohortFactory)


class GroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Group

    name = factory.Sequence(lambda n: f"Group {n}")
    course = factory.SubFactory(CourseFactory)


class GroupMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GroupMembership

    group = factory.SubFactory(GroupFactory)
    student = factory.SubFactory(UserFactory)


class CollectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Collection

    name = factory.Sequence(lambda n: f"Collection {n}")
    course = factory.SubFactory(CourseFactory)
    owner = factory.SubFactory(UserFactory)
```

- [ ] **Step 7: Write the failing model tests**

`tests/test_grouping_models.py`:
```python
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from grouping.models import Cohort
from tests.factories import CohortFactory
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_slug_autogenerated_from_name():
    c = CohortFactory(name="Year 7")
    assert c.slug == "year-7"


def test_slug_suffixes_on_collision():
    CohortFactory(name="Year 7")
    c2 = CohortFactory(name="Year 7")
    assert c2.slug == "year-7-2"


def test_non_default_cohort_named_default_is_suffixed():
    c = CohortFactory(name="Default")  # not is_default
    assert c.slug == "default-2"


def test_at_most_one_default_cohort_enforced_by_constraint():
    CohortFactory(name="A", is_default=True)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CohortFactory(name="B", is_default=True)


def test_groupmembership_unique_group_student():
    gm = GroupMembershipFactory()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            GroupMembershipFactory(group=gm.group, student=gm.student)


def test_cohortmembership_is_one_to_one():
    from grouping.models import CohortMembership

    # Boundary-safe across Task 2: update_or_create guarantees exactly one row
    # whether or not the Default-cohort signal already created one. A second raw
    # create for the same user must then violate the OneToOne.
    user = UserFactory()
    CohortMembership.objects.update_or_create(
        user=user, defaults={"cohort": CohortFactory()}
    )
    assert CohortMembership.objects.filter(user=user).count() == 1
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CohortMembership.objects.create(user=user, cohort=CohortFactory())


def test_group_course_is_immutable_after_create():
    g = GroupFactory()
    other = CourseFactory()
    g.course = other
    with pytest.raises(ValidationError):
        g.save()


def test_collection_course_immutable_only_when_groups_attached():
    coll = CollectionFactory()
    other = CourseFactory()
    # No groups attached yet -> retarget is allowed.
    coll.course = other
    coll.save()  # no error
    # Attach a group on the new course, then retargeting is blocked.
    g = GroupFactory(course=other)
    coll.groups.add(g)
    coll.course = CourseFactory()
    with pytest.raises(ValidationError):
        coll.save()
```

- [ ] **Step 8: Run the tests to verify they fail, then pass**

Run: `uv run pytest tests/test_grouping_models.py -v`
Expected first run: FAIL (migration not yet applied / models import). After Steps 1–6 are in place it should PASS. If `makemigrations` was skipped, the test DB build will error — re-run Step 5.

- [ ] **Step 9: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/ config/settings/base.py tests/factories.py tests/test_grouping_models.py
git commit -m "feat(3a): grouping app + cohort/group/collection models + constraints"
```

---

### Task 2: Default-cohort membership signal + backfill migration

**Files:**
- Modify: `grouping/signals.py`
- Create: `grouping/migrations/0002_default_cohort_backfill.py`
- Test: `tests/test_grouping_cohort_membership.py`

**Interfaces:**
- Consumes: `grouping.models.Cohort`, `CohortMembership` (Task 1).
- Produces: a `post_save` receiver `ensure_cohort_membership` that puts every newly-created user into the current Default cohort (idempotent via `get_or_create`); a data migration creating the Default cohort (`is_default=True`, slug `default`) and back-filling memberships for all existing users with `assigned_by=None`.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_cohort_membership.py`:
```python
import pytest

from grouping.models import Cohort
from grouping.models import CohortMembership
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_default_cohort_exists_from_migration():
    assert Cohort.objects.filter(is_default=True, slug="default").count() == 1


def test_new_user_auto_joins_default_cohort():
    user = UserFactory()
    membership = CohortMembership.objects.get(user=user)
    assert membership.cohort.is_default is True
    assert membership.assigned_by is None


def test_membership_creation_is_idempotent():
    user = UserFactory()
    # Saving the user again must not create a second membership (OneToOne).
    user.save()
    assert CohortMembership.objects.filter(user=user).count() == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_cohort_membership.py -v`
Expected: FAIL — no Default cohort / no auto-membership yet.

- [ ] **Step 3: Implement the signal receiver**

`grouping/signals.py` (replace the placeholder):
```python
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User


@receiver(post_save, sender=User)
def ensure_cohort_membership(sender, instance, created, **kwargs):
    """Every newly-created user joins the current Default cohort.

    Deliberately NOT the allauth `user_signed_up` signal (which fires only for
    self-signups) — cohort membership must cover admin/fixture/SSO-JIT creation
    too. Idempotent via get_or_create; a no-op if no Default exists yet (e.g.
    mid-backfill, which seeds memberships directly against historical models)."""
    if not created:
        return
    from grouping.models import Cohort, CohortMembership

    default = Cohort.objects.filter(is_default=True).first()
    if default is None:
        return
    CohortMembership.objects.get_or_create(
        user=instance, defaults={"cohort": default}
    )
```

- [ ] **Step 4: Write the backfill data migration**

`grouping/migrations/0002_default_cohort_backfill.py`:
```python
from django.conf import settings
from django.db import migrations


def forwards(apps, schema_editor):
    Cohort = apps.get_model("grouping", "Cohort")
    CohortMembership = apps.get_model("grouping", "CohortMembership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    default, _ = Cohort.objects.get_or_create(
        slug="default",
        defaults={"name": "Default", "is_default": True},
    )
    if not default.is_default:
        default.is_default = True
        default.save(update_fields=["is_default"])

    for user in User.objects.all():
        CohortMembership.objects.get_or_create(
            user=user, defaults={"cohort": default}
        )


def backwards(apps, schema_editor):
    Cohort = apps.get_model("grouping", "Cohort")
    Cohort.objects.filter(slug="default", is_default=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("grouping", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_cohort_membership.py -v`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/signals.py grouping/migrations/0002_default_cohort_backfill.py tests/test_grouping_cohort_membership.py
git commit -m "feat(3a): default-cohort auto-membership signal + backfill migration"
```

---

### Task 3: Cohort service (default promotion, reassignment, archive/delete guards)

**Files:**
- Create: `grouping/services.py` (cohort half; enrollment half added in Task 4)
- Test: `tests/test_grouping_cohort_service.py`

**Interfaces:**
- Consumes: `Cohort`, `CohortMembership` (Task 1).
- Produces:
  - `get_default_cohort() -> Cohort | None`
  - `promote_default(cohort)` — demotes the current default first, then promotes `cohort` (one transaction; never two `is_default=True` rows at any statement boundary).
  - `assign_student_to_cohort(user, cohort, *, assigned_by=None)` — in-place `update_or_create`.
  - `archive_cohort(cohort)` / `delete_cohort(cohort)` — reassign members to Default first (in-place `UPDATE`), then archive/delete; raise `ValidationError` if `cohort.is_default`.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_cohort_service.py`:
```python
import pytest
from django.core.exceptions import ValidationError

from grouping import services
from grouping.models import Cohort
from grouping.models import CohortMembership
from tests.factories import CohortFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_promote_default_demotes_old_default():
    old = Cohort.objects.get(is_default=True)
    new = CohortFactory(name="Year 8")
    services.promote_default(new)
    old.refresh_from_db()
    new.refresh_from_db()
    assert new.is_default is True
    assert old.is_default is False
    assert Cohort.objects.filter(is_default=True).count() == 1


def test_delete_cohort_reassigns_members_to_default():
    default = services.get_default_cohort()
    other = CohortFactory(name="Spanish")
    user = UserFactory()
    services.assign_student_to_cohort(user, other)
    services.delete_cohort(other)
    assert not Cohort.objects.filter(pk=other.pk).exists()
    assert CohortMembership.objects.get(user=user).cohort == default


def test_archive_cohort_reassigns_and_hides():
    default = services.get_default_cohort()
    other = CohortFactory(name="French")
    user = UserFactory()
    services.assign_student_to_cohort(user, other)
    services.archive_cohort(other)
    other.refresh_from_db()
    assert other.archived is True
    assert CohortMembership.objects.get(user=user).cohort == default


def test_cannot_delete_default_cohort():
    default = services.get_default_cohort()
    with pytest.raises(ValidationError):
        services.delete_cohort(default)


def test_cannot_archive_default_cohort():
    default = services.get_default_cohort()
    with pytest.raises(ValidationError):
        services.archive_cohort(default)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_cohort_service.py -v`
Expected: FAIL — `grouping.services` does not exist.

- [ ] **Step 3: Implement the cohort service**

`grouping/services.py`:
```python
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from grouping.models import Cohort
from grouping.models import CohortMembership


def get_default_cohort():
    return Cohort.objects.filter(is_default=True).first()


@transaction.atomic
def promote_default(cohort):
    """Make `cohort` the sole default. Demote the current default FIRST, then
    promote, so the partial unique index never sees two True rows."""
    Cohort.objects.filter(is_default=True).exclude(pk=cohort.pk).update(
        is_default=False
    )
    if not cohort.is_default:
        cohort.is_default = True
        cohort.save(update_fields=["is_default"])


def assign_student_to_cohort(user, cohort, *, assigned_by=None):
    """In-place reassignment: update the OneToOne row, never delete+recreate."""
    CohortMembership.objects.update_or_create(
        user=user, defaults={"cohort": cohort, "assigned_by": assigned_by}
    )


def _guard_not_default(cohort):
    if cohort.is_default:
        raise ValidationError(
            _("The default cohort cannot be removed; designate another default first.")
        )


def _reassign_members_to_default(cohort):
    default = get_default_cohort()
    CohortMembership.objects.filter(cohort=cohort).update(cohort=default)


@transaction.atomic
def archive_cohort(cohort):
    _guard_not_default(cohort)
    _reassign_members_to_default(cohort)
    cohort.archived = True
    cohort.save(update_fields=["archived"])


@transaction.atomic
def delete_cohort(cohort):
    _guard_not_default(cohort)
    _reassign_members_to_default(cohort)
    cohort.delete()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_cohort_service.py -v`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/services.py tests/test_grouping_cohort_service.py
git commit -m "feat(3a): cohort service (default promotion, reassignment, archive/delete guards)"
```

---

### Task 4: `recompute_enrollment` + group-membership/archive services (the enrollment heart)

**Files:**
- Modify: `grouping/services.py` (append enrollment + group-membership functions)
- Test: `tests/test_grouping_recompute.py`

**Interfaces:**
- Consumes: `courses.models.Enrollment`, `Group`, `GroupMembership`, `accounts.models.User`.
- Produces:
  - `recompute_enrollment(student, course)` — idempotent sync of `Enrollment` to group reachability (nested `atomic()` savepoint + `get_or_create`).
  - `add_students_to_group(group, students, *, added_by=None)`
  - `remove_students_from_group(group, students)`
  - `set_group_members(group, student_ids, *, added_by=None)` — diff current vs target, add/remove.
  - `set_group_archived(group, archived)` — flips archive flag and recomputes per member.
  - `delete_group(group)` — deletes group and recomputes per ex-member.

- [ ] **Step 1: Write the failing tests (the recompute truth table)**

`tests/test_grouping_recompute.py`:
```python
import pytest

from courses.models import Enrollment
from courses.models import UnitProgress
from grouping import services
from grouping.models import GroupMembership
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enrollment(student, course):
    return Enrollment.objects.filter(student=student, course=course).first()


def test_add_creates_group_enrollment():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    e = _enrollment(student, course)
    assert e is not None and e.source == "group"


def test_remove_last_drops_enrollment():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    services.remove_students_from_group(group, [student])
    assert _enrollment(student, course) is None


def test_remove_with_second_group_keeps_enrollment():
    course = CourseFactory()
    g1 = GroupFactory(course=course)
    g2 = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(g1, [student])
    services.add_students_to_group(g2, [student])
    services.remove_students_from_group(g1, [student])
    assert _enrollment(student, course) is not None


def test_archive_drops_unarchive_restores():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    services.set_group_archived(group, True)
    assert _enrollment(student, course) is None
    services.set_group_archived(group, False)
    assert _enrollment(student, course) is not None


def test_archive_with_second_active_group_keeps_enrollment():
    # Student in group A (archived) and group B (active) of the SAME course
    # keeps the group-sourced enrollment after A is archived (parity with the
    # remove-with-second-group case).
    course = CourseFactory()
    g_a = GroupFactory(course=course)
    g_b = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(g_a, [student])
    services.add_students_to_group(g_b, [student])
    services.set_group_archived(g_a, True)
    assert _enrollment(student, course) is not None


def test_self_and_manual_enrollment_immune_to_group_changes():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course, source="manual")
    services.add_students_to_group(group, [student])
    # source not downgraded/overwritten
    assert _enrollment(student, course).source == "manual"
    services.remove_students_from_group(group, [student])
    # manual enrollment survives losing group membership
    assert _enrollment(student, course) is not None


def test_progress_preserved_across_drop_and_readd():
    course = CourseFactory()
    group = GroupFactory(course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    student = UserFactory()
    services.add_students_to_group(group, [student])
    UnitProgress.objects.create(student=student, unit=unit, completed=True)
    services.remove_students_from_group(group, [student])
    services.add_students_to_group(group, [student])
    assert UnitProgress.objects.get(student=student, unit=unit).completed is True


def test_delete_group_drops_enrollment_and_recomputes():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    services.delete_group(group)
    assert _enrollment(student, course) is None
    assert not GroupMembership.objects.filter(student=student).exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_recompute.py -v`
Expected: FAIL — the new service functions do not exist.

- [ ] **Step 3: Append the enrollment + group-membership functions to `grouping/services.py`**

```python
from django.db import IntegrityError

from accounts.models import User
from courses.models import Enrollment
from grouping.models import GroupMembership


def _is_reachable(student, course):
    return GroupMembership.objects.filter(
        student=student, group__course=course, group__archived=False
    ).exists()


def recompute_enrollment(student, course):
    """Sync Enrollment for (student, course) to group reachability. Idempotent;
    safe under concurrency. Self/manual sources are never downgraded; a
    group-reachable student is never stranded."""
    reachable = _is_reachable(student, course)
    enrollment = Enrollment.objects.filter(student=student, course=course).first()
    if reachable and enrollment is None:
        try:
            with transaction.atomic():  # savepoint: a racing create won't poison the batch
                Enrollment.objects.get_or_create(
                    student=student, course=course, defaults={"source": "group"}
                )
        except IntegrityError:
            pass  # concurrent create won; leave its row untouched
    elif (
        not reachable
        and enrollment is not None
        and enrollment.source == "group"
    ):
        enrollment.delete()
    # else: self/manual immune, or reachable+group steady state -> no-op


@transaction.atomic
def add_students_to_group(group, students, *, added_by=None):
    for student in students:
        # Per-student savepoint: a unique-violation on one row (concurrent add)
        # rolls back only that student, never the whole batch.
        with transaction.atomic():
            GroupMembership.objects.get_or_create(
                group=group, student=student, defaults={"added_by": added_by}
            )
            recompute_enrollment(student, group.course)


@transaction.atomic
def remove_students_from_group(group, students):
    students = list(students)
    GroupMembership.objects.filter(group=group, student__in=students).delete()
    for student in students:
        with transaction.atomic():  # per-student savepoint (batch resilience)
            recompute_enrollment(student, group.course)


@transaction.atomic
def set_group_members(group, student_ids, *, added_by=None):
    """Diff the target student set against current members; add/remove the delta."""
    target = set(student_ids)
    current = set(group.memberships.values_list("student_id", flat=True))
    to_add = User.objects.filter(pk__in=(target - current))
    to_remove = User.objects.filter(pk__in=(current - target))
    add_students_to_group(group, to_add, added_by=added_by)
    remove_students_from_group(group, to_remove)


@transaction.atomic
def set_group_archived(group, archived):
    group.archived = archived
    group.save(update_fields=["archived"])
    student_ids = list(group.memberships.values_list("student_id", flat=True))
    for student in User.objects.filter(pk__in=student_ids):
        recompute_enrollment(student, group.course)


@transaction.atomic
def delete_group(group):
    course = group.course
    student_ids = list(group.memberships.values_list("student_id", flat=True))
    group.delete()
    for student in User.objects.filter(pk__in=student_ids):
        recompute_enrollment(student, course)
```

Fan-out is O(members) recompute calls, each doing 1–2 queries — acceptable at 3a roster scale (tens–low-hundreds per group); not a hot path. No batching/`bulk_*` optimization is needed here.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_recompute.py -v`
Expected: PASS (all 9).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/services.py tests/test_grouping_recompute.py
git commit -m "feat(3a): recompute_enrollment + group membership/archive services"
```

---

### Task 5: Collection M2M course-match validation (`m2m_changed` defense + helper)

**Files:**
- Modify: `grouping/signals.py` (add `m2m_changed` receiver)
- Modify: `grouping/services.py` (add `set_collection_groups`)
- Test: `tests/test_grouping_collection_validation.py`

**Interfaces:**
- Consumes: `Collection`, `Group` (Task 1).
- Produces:
  - `m2m_changed` receiver on `Collection.groups` that raises `ValidationError` (aborting the surrounding transaction) when a group whose `course != collection.course` is added.
  - `set_collection_groups(collection, group_ids)` — replaces the group set inside an `atomic()` block.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_collection_validation.py`:
```python
import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from grouping import services
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory

pytestmark = pytest.mark.django_db


def test_adding_same_course_group_is_allowed():
    course = CourseFactory()
    coll = CollectionFactory(course=course)
    g = GroupFactory(course=course)
    services.set_collection_groups(coll, [g.pk])
    assert list(coll.groups.values_list("pk", flat=True)) == [g.pk]


def test_adding_mismatched_course_group_is_rejected():
    coll = CollectionFactory(course=CourseFactory())
    foreign = GroupFactory(course=CourseFactory())
    with pytest.raises(ValidationError):
        with transaction.atomic():
            services.set_collection_groups(coll, [foreign.pk])
    coll.refresh_from_db()
    assert coll.groups.count() == 0


def test_empty_collection_is_allowed():
    coll = CollectionFactory()
    services.set_collection_groups(coll, [])
    assert coll.groups.count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_collection_validation.py -v`
Expected: FAIL — `set_collection_groups` and the receiver don't exist.

- [ ] **Step 3: Add the `m2m_changed` receiver to `grouping/signals.py`**

```python
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed
from django.utils.translation import gettext_lazy as _

from grouping.models import Collection


@receiver(m2m_changed, sender=Collection.groups.through)
def validate_collection_group_course(sender, instance, action, pk_set, **kwargs):
    """Defense-in-depth (non-form code paths): every group must share the
    collection's course. Raises to abort the surrounding transaction."""
    if action != "pre_add" or not pk_set:
        return
    from grouping.models import Group

    mismatched = (
        Group.objects.filter(pk__in=pk_set)
        .exclude(course_id=instance.course_id)
        .exists()
    )
    if mismatched:
        raise ValidationError(
            _("All groups in a collection must belong to the collection's course.")
        )
```

(Keep the existing imports/receivers in `signals.py`; add `from django.dispatch import receiver` only if not already imported.)

- [ ] **Step 4: Add `set_collection_groups` to `grouping/services.py`**

```python
@transaction.atomic
def set_collection_groups(collection, group_ids):
    """Replace the collection's group set. The m2m_changed receiver enforces the
    single-course rule; wrapping in atomic() lets its ValidationError roll back."""
    collection.groups.set(group_ids)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_collection_validation.py -v`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/signals.py grouping/services.py tests/test_grouping_collection_validation.py
git commit -m "feat(3a): collection group-course validation (m2m_changed + set_collection_groups)"
```

---

### Task 6: Object-level scoping functions

**Files:**
- Create: `grouping/scoping.py`
- Test: `tests/test_grouping_scoping.py`

**Interfaces:**
- Consumes: `Group`, `Collection` (Task 1); the role-perm convention (`courses.change_course` ⇒ PA).
- Produces:
  - `groups_manageable_by(user) -> QuerySet[Group]`
  - `groups_visible_to(user) -> QuerySet[Group]`
  - `collections_manageable_by(user) -> QuerySet[Collection]`
  - `can_add_collection_group(user, group) -> bool`
  - All return archived rows too (list views apply the active/archived filter).

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_scoping.py`:
```python
import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping import scoping
from institution.roles import seed_roles
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _with_role(user, role_name):
    seed_roles()
    user.groups.add(AuthGroup.objects.get(name=role_name))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


def test_pa_sees_all_groups():
    GroupFactory()
    GroupFactory()
    pa = _with_role(UserFactory(), "Platform Admin")
    assert scoping.groups_manageable_by(pa).count() == 2


def test_ca_sees_only_owned_course_groups():
    ca = _with_role(UserFactory(), "Course Admin")
    mine = GroupFactory(course=CourseFactory(owner=ca))
    GroupFactory(course=CourseFactory(owner=UserFactory()))  # someone else's
    result = list(scoping.groups_manageable_by(ca))
    assert result == [mine]


def test_visible_includes_taught_groups():
    teacher = _with_role(UserFactory(), "Teacher")
    g = GroupFactory()
    g.teachers.add(teacher)
    assert g in scoping.groups_visible_to(teacher)
    assert g not in scoping.groups_manageable_by(teacher)


def test_can_add_collection_group_rules():
    pa = _with_role(UserFactory(), "Platform Admin")
    ca = UserFactory()
    teacher = UserFactory()
    owned_course = CourseFactory(owner=ca)
    g = GroupFactory(course=owned_course)
    g.teachers.add(teacher)
    assert scoping.can_add_collection_group(pa, g) is True
    assert scoping.can_add_collection_group(ca, g) is True
    assert scoping.can_add_collection_group(teacher, g) is True
    assert scoping.can_add_collection_group(UserFactory(), g) is False


def test_collections_manageable_owner_and_course():
    ca = _with_role(UserFactory(), "Course Admin")
    own = CollectionFactory(owner=ca, course=CourseFactory(owner=UserFactory()))
    on_my_course = CollectionFactory(
        owner=UserFactory(), course=CourseFactory(owner=ca)
    )
    CollectionFactory(owner=UserFactory(), course=CourseFactory(owner=UserFactory()))
    result = set(scoping.collections_manageable_by(ca))
    assert result == {own, on_my_course}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_scoping.py -v`
Expected: FAIL — `grouping.scoping` does not exist.

- [ ] **Step 3: Implement `grouping/scoping.py`**

```python
from django.db.models import Q

from grouping.models import Collection
from grouping.models import Group


def _is_platform_admin(user):
    # Convention (mirrors courses/views_manage.py): the PA group alone holds
    # courses.change_course. Never branch on the role *name*.
    return user.has_perm("courses.change_course")


def _owner_or_course_q(user):
    return Q(owner=user) | Q(course__owner=user)


def groups_manageable_by(user):
    """Groups a user may create/edit/delete. Includes archived rows; list views
    apply the active/archived filter on top.

    NOTE on owner-less courses: `courses.Course.owner` is nullable
    (`on_delete=SET_NULL`). A course with `owner=None` matches no CA via
    `course__owner=user` and is therefore PA-manageable only, by design — a CA
    only manages groups on courses they explicitly own."""
    if _is_platform_admin(user):
        return Group.objects.all()
    if user.has_perm("grouping.change_group"):  # Course Admin
        return Group.objects.filter(course__owner=user)
    return Group.objects.none()


def groups_visible_to(user):
    """Manageable groups plus groups the user teaches (read access)."""
    manageable = groups_manageable_by(user)
    taught = Group.objects.filter(teachers=user)
    return (manageable | taught).distinct()


def collections_manageable_by(user):
    if _is_platform_admin(user):
        return Collection.objects.all()
    if user.has_perm("grouping.change_collection"):  # Teacher or Course Admin
        # Teacher: collections they own. Course Admin: + collections on courses
        # they own (owner-less courses are PA-only, as in groups_manageable_by).
        return Collection.objects.filter(_owner_or_course_q(user)).distinct()
    return Collection.objects.none()


def can_add_collection_group(user, group):
    if _is_platform_admin(user):
        return True
    if group.course.owner_id == user.id:  # Course Admin owns the course
        return True
    return group.teachers.filter(pk=user.pk).exists()  # Teacher teaches it
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_scoping.py -v`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/scoping.py tests/test_grouping_scoping.py
git commit -m "feat(3a): object-level scoping functions for groups/collections"
```

---

### Task 7: Permission seeding — extend `seed_roles()` with `grouping.*` perms

**Files:**
- Modify: `institution/roles.py`
- Test: `tests/test_grouping_roles.py`

**Interfaces:**
- Consumes: `grouping.*` model permissions (exist after the Task 1 migration is applied; in the test DB they exist because pytest-django runs migrations + `post_migrate`).
- Produces: `TEACHER`, `COURSE_ADMIN` role groups gain their `grouping.*` perms; `PLATFORM_ADMIN` gains all `grouping.*` perms. `seed_roles()` stays idempotent.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_roles.py`:
```python
import pytest
from django.contrib.auth.models import Group

from institution.roles import seed_roles

pytestmark = pytest.mark.django_db


def _codenames(role_name):
    seed_roles()
    g = Group.objects.get(name=role_name)
    return set(g.permissions.values_list("codename", flat=True))


def test_teacher_gets_group_view_and_collection_crud():
    cn = _codenames("Teacher")
    assert "view_group" in cn
    assert {"add_collection", "change_collection", "delete_collection", "view_collection"} <= cn
    assert "add_group" not in cn  # teachers don't author groups


def test_course_admin_gets_group_crud_and_cohort_view():
    cn = _codenames("Course Admin")
    assert {"add_group", "change_group", "delete_group", "view_group"} <= cn
    assert "view_cohort" in cn
    assert "add_cohort" not in cn  # cohorts are PA-managed


def test_platform_admin_gets_all_grouping_perms():
    cn = _codenames("Platform Admin")
    assert {"add_cohort", "change_cohort", "delete_cohort", "view_cohort"} <= cn
    assert {"add_group", "change_group", "delete_group", "view_group"} <= cn
    assert {"add_collection", "change_collection", "delete_collection", "view_collection"} <= cn


def test_seed_roles_idempotent_for_grouping():
    seed_roles()
    seed_roles()
    teacher = Group.objects.get(name="Teacher")
    assert teacher.permissions.filter(codename="view_group").count() == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_roles.py -v`
Expected: FAIL — Teacher/Course Admin groups have no grouping perms yet.

- [ ] **Step 3: Extend `institution/roles.py`**

Add the role-name imports and new perm lists near the top (after the existing `*_PERMS` definitions):
```python
GROUPING_TEACHER_PERMS = [
    "grouping.view_group",
    "grouping.add_collection",
    "grouping.change_collection",
    "grouping.delete_collection",
    "grouping.view_collection",
]

GROUPING_COURSE_ADMIN_PERMS = [
    "grouping.add_group",
    "grouping.change_group",
    "grouping.delete_group",
    "grouping.view_group",
    "grouping.view_cohort",
    "grouping.add_collection",
    "grouping.change_collection",
    "grouping.delete_collection",
    "grouping.view_collection",
]

GROUPING_PLATFORM_ADMIN_PERMS = [
    "grouping.add_cohort",
    "grouping.change_cohort",
    "grouping.delete_cohort",
    "grouping.view_cohort",
    "grouping.add_group",
    "grouping.change_group",
    "grouping.delete_group",
    "grouping.view_group",
    "grouping.add_collection",
    "grouping.change_collection",
    "grouping.delete_collection",
    "grouping.view_collection",
]
```

Then rewrite `seed_roles()` to set all three role groups (the existing version only sets Platform Admin):
```python
def seed_roles():
    """Create the four role Groups (idempotent) and assign their permissions.
    Permissions must already exist, so run this AFTER `migrate` (the setup_roles
    command and the DoD do exactly that)."""
    groups = {name: Group.objects.get_or_create(name=name)[0] for name in ROLE_NAMES}
    groups[PLATFORM_ADMIN].permissions.set(
        [_permission(label) for label in PLATFORM_ADMIN_PERMS + GROUPING_PLATFORM_ADMIN_PERMS]
    )
    groups[TEACHER].permissions.set(
        [_permission(label) for label in GROUPING_TEACHER_PERMS]
    )
    groups[COURSE_ADMIN].permissions.set(
        [_permission(label) for label in GROUPING_COURSE_ADMIN_PERMS]
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_roles.py tests/test_roles.py -v`
Expected: PASS (including the existing `test_roles.py`, unchanged behavior for Platform Admin's Phase-0 perms).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add institution/roles.py tests/test_grouping_roles.py
git commit -m "feat(3a): seed grouping.* permissions to Teacher/CourseAdmin/PlatformAdmin via seed_roles"
```

---

### Task 8: Forms — `CohortForm`, `GroupForm`, `CollectionForm`

**Files:**
- Create: `grouping/forms.py`
- Test: `tests/test_grouping_forms.py`

**Interfaces:**
- Consumes: models (Task 1), scoping (Task 6).
- Produces:
  - `CohortForm(ModelForm)` — fields `name`, `archived`; `is_default` is NOT a form field (the service is the sole write path).
  - `GroupForm(ModelForm)` — fields `name`, `course`, `teachers`; `course` is disabled when editing an existing instance (immutable). The **roster is NOT a form field**: it is handled by the view reading `request.POST.getlist("students")` and the template's hand-rolled `<select name="students" multiple>` (cohort filtering is a GET param on the picker, not a form field). See `_student_ids_from_post` in Task 10, which tolerates non-integer/foreign ids.
  - `CollectionForm(ModelForm)` — fields `name`, `course`, `groups`; validates every selected group shares `course`; `course` widget disabled when the instance already has groups.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_forms.py`:
```python
import pytest

from grouping.forms import CollectionForm
from grouping.forms import GroupForm
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_group_form_course_locked_on_edit():
    g = GroupFactory()
    form = GroupForm(instance=g)
    assert form.fields["course"].disabled is True


def test_group_form_course_editable_on_create():
    form = GroupForm()
    assert form.fields["course"].disabled is False


def test_collection_form_rejects_mismatched_group():
    course = CourseFactory()
    foreign = GroupFactory(course=CourseFactory())
    form = CollectionForm(
        data={"name": "Mix", "course": course.pk, "groups": [foreign.pk]},
        owner=UserFactory(),
    )
    assert not form.is_valid()
    assert "groups" in form.errors


def test_collection_form_accepts_same_course_group():
    course = CourseFactory()
    g = GroupFactory(course=course)
    form = CollectionForm(
        data={"name": "OK", "course": course.pk, "groups": [g.pk]},
        owner=UserFactory(),
    )
    assert form.is_valid(), form.errors
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_forms.py -v`
Expected: FAIL — `grouping.forms` does not exist.

- [ ] **Step 3: Implement `grouping/forms.py`**

```python
from django import forms
from django.utils.translation import gettext_lazy as _

from grouping.models import Cohort
from grouping.models import Collection
from grouping.models import Group


class CohortForm(forms.ModelForm):
    class Meta:
        model = Cohort
        fields = ["name"]

    # `is_default` and `archived` are intentionally NOT form fields: promotion
    # goes through grouping.services.promote_default, and archiving through
    # grouping.services.archive_cohort (which reassigns members to Default and
    # refuses to archive the Default cohort). Letting a plain form write either
    # would bypass those guards. They are the sole write paths.


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "course", "teachers"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is not None:
            # Course is immutable after creation; lock the widget.
            self.fields["course"].disabled = True


class CollectionForm(forms.ModelForm):
    class Meta:
        model = Collection
        fields = ["name", "course", "groups"]

    def __init__(self, *args, owner=None, **kwargs):
        self._owner = owner
        super().__init__(*args, **kwargs)
        # Course is immutable once groups are attached.
        if self.instance.pk is not None and self.instance.groups.exists():
            self.fields["course"].disabled = True

    def clean(self):
        cleaned = super().clean()
        course = cleaned.get("course")
        groups = cleaned.get("groups")
        if course and groups:
            mismatched = [g for g in groups if g.course_id != course.pk]
            if mismatched:
                self.add_error(
                    "groups",
                    _("Every group must belong to the collection's course."),
                )
        return cleaned

    def save(self, commit=True):
        collection = super().save(commit=False)
        if self._owner is not None and collection.owner_id is None:
            collection.owner = self._owner
        if commit:
            collection.save()
            self.save_m2m()
        return collection
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_forms.py -v`
Expected: PASS.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/forms.py tests/test_grouping_forms.py
git commit -m "feat(3a): cohort/group/collection forms with immutability + course-match validation"
```

---

### Task 9: Cohort management views (view 6.4) + URLs + templates + nav

**Files:**
- Create: `grouping/views.py` (cohort views; group/collection views appended in Tasks 10–12)
- Create: `grouping/urls.py`
- Modify: `config/urls.py` (include `grouping.urls`)
- Create: `templates/grouping/cohort_list.html`
- Create: `templates/grouping/cohort_form.html`
- Create: `templates/grouping/cohort_confirm_delete.html`
- Modify: `templates/base.html` (PA nav link to cohorts)
- Test: `tests/test_grouping_cohort_views.py`

**Interfaces:**
- Consumes: `CohortForm` (Task 8), cohort service (Task 3), `make_pa` test helper.
- Produces: URL names under `app_name = "grouping"`: `cohort_list`, `cohort_create`, `cohort_edit`, `cohort_promote`, `cohort_archive`, `cohort_assign_students`, `cohort_delete`. Routed by `slug`. (`cohort_archive` routes archiving through `services.archive_cohort`; `cohort_assign_students` is view 6.4's "assign & reassign students" surface, calling `services.assign_student_to_cohort`.)

> **Hard dependency for Tasks 9–12 (all view tasks):** every `@permission_required("grouping.*")` view is unreachable (403) until **Task 7** extends `seed_roles()` to attach the `grouping.*` perms. The `make_pa` / role-add test helpers call `seed_roles()`, so these tests only pass once Task 7 has landed. Execute Tasks 9–12 strictly after Task 7.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_cohort_views.py`:
```python
import pytest
from django.urls import reverse

from django.contrib.auth.models import Group as AuthGroup

from grouping.models import Cohort
from grouping.models import CohortMembership
from grouping.services import get_default_cohort
from institution.roles import seed_roles
from tests.factories import CohortFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_cohort_list_requires_permission(client):
    make_login(client, "plainstudent")
    resp = client.get(reverse("grouping:cohort_list"))
    assert resp.status_code == 403


def test_course_admin_cannot_reach_cohort_list(client):
    # CA holds only `view_cohort` (for the picker filter), not `change_cohort`,
    # so the PA-only management list must 403 for a Course Admin (spec §4).
    seed_roles()
    user = make_login(client, "courseadmin")
    user.groups.add(AuthGroup.objects.get(name="Course Admin"))
    resp = client.get(reverse("grouping:cohort_list"))
    assert resp.status_code == 403


def test_pa_can_create_cohort(client):
    make_pa(client)
    resp = client.post(reverse("grouping:cohort_create"), {"name": "Year 9"})
    assert resp.status_code == 302
    assert Cohort.objects.filter(name="Year 9").exists()


def test_pa_can_promote_default(client):
    make_pa(client)
    other = CohortFactory(name="Year 10")
    resp = client.post(reverse("grouping:cohort_promote", args=[other.slug]))
    assert resp.status_code == 302
    other.refresh_from_db()
    assert other.is_default is True


def test_pa_cannot_delete_default(client):
    make_pa(client)
    default = get_default_cohort()
    resp = client.post(reverse("grouping:cohort_delete", args=[default.slug]))
    # Service raises ValidationError -> view re-renders the confirm page with the
    # error surfaced (200), and the row survives. Assert all three so a regression
    # that swallowed the error or redirected can't pass.
    assert resp.status_code == 200
    assert resp.context["error"]
    assert Cohort.objects.filter(pk=default.pk).exists()


def test_archive_via_ui_reassigns_members_and_guards_default(client):
    # Archiving routes through services.archive_cohort, so members move to Default
    # and the Default cohort itself can never be archived (spec §2/§3).
    make_pa(client)
    default = get_default_cohort()
    other = CohortFactory(name="Spanish")
    student = UserFactory()
    from grouping import services

    services.assign_student_to_cohort(student, other)
    resp = client.post(reverse("grouping:cohort_archive", args=[other.slug]))
    assert resp.status_code == 302
    other.refresh_from_db()
    assert other.archived is True
    assert CohortMembership.objects.get(user=student).cohort == default
    # Archiving the Default is a no-op (guarded).
    client.post(reverse("grouping:cohort_archive", args=[default.slug]))
    default.refresh_from_db()
    assert default.archived is False


def test_pa_can_assign_student_to_cohort(client):
    make_pa(client)
    target = CohortFactory(name="Year 11")
    student = UserFactory()  # starts in Default via the signal
    resp = client.post(
        reverse("grouping:cohort_assign_students", args=[target.slug]),
        {"students": [student.pk]},
    )
    assert resp.status_code == 302
    assert CohortMembership.objects.get(user=student).cohort == target
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_cohort_views.py -v`
Expected: FAIL — URLs/views not defined.

- [ ] **Step 3: Implement the cohort views in `grouping/views.py`**

```python
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.models import User
from grouping import services
from grouping.forms import CohortForm
from grouping.models import Cohort


# Cohort management is PA-only. The list is gated on `change_cohort` (a PA-only
# perm), NOT `view_cohort` — per spec §4, the CA `view_cohort` grant exists ONLY
# to read cohort names in the group student-picker, not to reach this screen.
@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
def cohort_list(request):
    cohorts = Cohort.objects.order_by("-is_default", "name")
    return render(request, "grouping/cohort_list.html", {"cohorts": cohorts})


@login_required
@permission_required("grouping.add_cohort", raise_exception=True)
def cohort_create(request):
    if request.method == "POST":
        form = CohortForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("grouping:cohort_list")
    else:
        form = CohortForm()
    return render(
        request, "grouping/cohort_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
def cohort_edit(request, slug):
    cohort = get_object_or_404(Cohort, slug=slug)
    if request.method == "POST":
        form = CohortForm(request.POST, instance=cohort)
        if form.is_valid():
            # NOTE: slugs are frozen after creation for ALL cohorts (Cohort.save
            # only generates a slug when blank) — a rename does NOT re-slug, so
            # cohort URLs are stable. This is intentional, not an oversight.
            form.save()
            return redirect("grouping:cohort_list")
    else:
        form = CohortForm(instance=cohort)
    members = User.objects.filter(cohort_membership__cohort=cohort).order_by("username")
    return render(
        request,
        "grouping/cohort_form.html",
        {
            "form": form,
            "creating": False,
            "cohort": cohort,
            "members": members,
            "all_students": User.objects.order_by("username"),
        },
    )


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
@require_POST
def cohort_promote(request, slug):
    cohort = get_object_or_404(Cohort, slug=slug)
    services.promote_default(cohort)
    return redirect("grouping:cohort_list")


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
@require_POST
def cohort_archive(request, slug):
    """Toggle a cohort's archived state through the SERVICE (not the form), so
    archiving reassigns members to Default and refuses to archive the Default
    cohort (spec §3 lifecycle). The archive button is rendered for non-default
    cohorts only; the ValidationError catch is a defense-in-depth backstop."""
    cohort = get_object_or_404(Cohort, slug=slug)
    if cohort.archived:
        cohort.archived = False  # un-archive: just make it active again (it is empty)
        cohort.save(update_fields=["archived"])
    else:
        try:
            services.archive_cohort(cohort)  # reassigns members to Default + guards default
        except ValidationError:
            pass  # cannot archive the Default cohort; no-op
    return redirect("grouping:cohort_list")


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
@require_POST
def cohort_assign_students(request, slug):
    """View 6.4 'assign & reassign students': move each selected student INTO
    this cohort (exactly-one cohort => assignment is a reassignment from wherever
    they are). Non-integer / unknown ids are skipped."""
    cohort = get_object_or_404(Cohort, slug=slug)
    for raw in request.POST.getlist("students"):
        try:
            student = User.objects.get(pk=int(raw))
        except (TypeError, ValueError, User.DoesNotExist):
            continue
        services.assign_student_to_cohort(student, cohort, assigned_by=request.user)
    return redirect("grouping:cohort_edit", slug=cohort.slug)


@login_required
@permission_required("grouping.delete_cohort", raise_exception=True)
def cohort_delete(request, slug):
    cohort = get_object_or_404(Cohort, slug=slug)
    error = None
    if request.method == "POST":
        try:
            services.delete_cohort(cohort)
            return redirect("grouping:cohort_list")
        except ValidationError as exc:
            error = exc.messages[0]
    member_count = cohort.memberships.count()
    return render(
        request,
        "grouping/cohort_confirm_delete.html",
        {"cohort": cohort, "member_count": member_count, "error": error},
    )
```

- [ ] **Step 4: Create `grouping/urls.py`**

```python
from django.urls import path

from grouping import views

app_name = "grouping"

urlpatterns = [
    path("manage/cohorts/", views.cohort_list, name="cohort_list"),
    path("manage/cohorts/new/", views.cohort_create, name="cohort_create"),
    path("manage/cohorts/<slug:slug>/edit/", views.cohort_edit, name="cohort_edit"),
    path(
        "manage/cohorts/<slug:slug>/promote/",
        views.cohort_promote,
        name="cohort_promote",
    ),
    path(
        "manage/cohorts/<slug:slug>/archive/",
        views.cohort_archive,
        name="cohort_archive",
    ),
    path(
        "manage/cohorts/<slug:slug>/assign/",
        views.cohort_assign_students,
        name="cohort_assign_students",
    ),
    path(
        "manage/cohorts/<slug:slug>/delete/",
        views.cohort_delete,
        name="cohort_delete",
    ),
]
```

- [ ] **Step 5: Include the urls in `config/urls.py`**

Add after the `courses.urls` include:
```python
    path("", include("grouping.urls")),
```

- [ ] **Step 6: Create the templates**

`templates/grouping/cohort_list.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% trans "Cohorts" %}</h1>
<a class="btn" href="{% url 'grouping:cohort_create' %}">{% trans "New cohort" %}</a>
<ul class="card-list">
  {% for cohort in cohorts %}
  <li>
    <span>{{ cohort.name }}</span>
    {% if cohort.is_default %}<span class="badge">{% trans "Default" %}</span>{% endif %}
    {% if cohort.archived %}<span class="badge">{% trans "Archived" %}</span>{% endif %}
    <a href="{% url 'grouping:cohort_edit' cohort.slug %}">{% trans "Edit" %}</a>
    {% if not cohort.is_default %}
    <form method="post" action="{% url 'grouping:cohort_promote' cohort.slug %}" style="display:inline">
      {% csrf_token %}
      <button type="submit">{% trans "Make default" %}</button>
    </form>
    <form method="post" action="{% url 'grouping:cohort_archive' cohort.slug %}" style="display:inline">
      {% csrf_token %}
      <button type="submit">{% if cohort.archived %}{% trans "Un-archive" %}{% else %}{% trans "Archive" %}{% endif %}</button>
    </form>
    <a href="{% url 'grouping:cohort_delete' cohort.slug %}">{% trans "Delete" %}</a>
    {% endif %}
  </li>
  {% endfor %}
</ul>
{% endblock %}
```

`templates/grouping/cohort_form.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% if creating %}{% trans "New cohort" %}{% else %}{% trans "Edit cohort" %}{% endif %}</h1>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">{% trans "Save" %}</button>
  <a href="{% url 'grouping:cohort_list' %}">{% trans "Cancel" %}</a>
</form>

{% if not creating %}
<h2>{% trans "Members" %}</h2>
<ul>
  {% for m in members %}<li>{{ m }}</li>{% empty %}<li>{% trans "No members." %}</li>{% endfor %}
</ul>
<form method="post" action="{% url 'grouping:cohort_assign_students' cohort.slug %}">
  {% csrf_token %}
  <label>{% trans "Assign students to this cohort (moves them from their current cohort)" %}</label>
  <select name="students" multiple size="10">
    {% for s in all_students %}<option value="{{ s.pk }}">{{ s }}</option>{% endfor %}
  </select>
  <button type="submit">{% trans "Assign" %}</button>
</form>
{% endif %}
{% endblock %}
```

`templates/grouping/cohort_confirm_delete.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% blocktrans with name=cohort.name %}Delete cohort “{{ name }}”?{% endblocktrans %}</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<p>{% blocktrans count counter=member_count %}{{ counter }} student will be moved to the Default cohort.{% plural %}{{ counter }} students will be moved to the Default cohort.{% endblocktrans %}</p>
<form method="post">
  {% csrf_token %}
  <button type="submit">{% trans "Delete" %}</button>
  <a href="{% url 'grouping:cohort_list' %}">{% trans "Cancel" %}</a>
</form>
{% endblock %}
```

- [ ] **Step 7: Add the PA nav link in `templates/base.html`**

After the existing `{% if perms.courses.change_course %}` Manage link block (around line 60–62), add. Gate on `change_cohort` (PA-only), NOT `view_cohort` (which CAs also hold for the picker) — matching the `cohort_list` view gate:
```html
          {% if perms.grouping.change_cohort %}
          <a class="app-nav__link" href="{% url 'grouping:cohort_list' %}">{% trans "Cohorts" %}</a>
          {% endif %}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_cohort_views.py -v`
Expected: PASS.

- [ ] **Step 9: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/views.py grouping/urls.py config/urls.py templates/grouping/ templates/base.html tests/test_grouping_cohort_views.py
git commit -m "feat(3a): cohort management views (6.4) + urls + templates + nav"
```

---

### Task 10: Group list (5.15) + group create/edit (5.16) views/templates/urls

**Files:**
- Modify: `grouping/views.py` (append group views)
- Modify: `grouping/urls.py` (append group routes)
- Create: `templates/grouping/group_list.html`
- Create: `templates/grouping/group_form.html`
- Modify: `templates/base.html` (CA/PA nav link to groups)
- Test: `tests/test_grouping_group_views.py`

**Interfaces:**
- Consumes: `GroupForm` (Task 8), scoping (Task 6), group services (Task 4).
- Produces: URL names `group_list`, `group_create`, `group_edit`, `group_archive`, `group_delete`. Routed by `<int:pk>`. The create/edit view persists `name`/`teachers` via the form, the roster via `services.set_group_members`, and on create assigns the chosen course.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_group_views.py`:
```python
import pytest
from django.urls import reverse

from courses.models import Enrollment
from grouping.models import Group
from grouping.models import GroupMembership
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_group_list_scoped_to_owned_courses(client):
    pa = make_pa(client)  # PA sees all
    GroupFactory()
    resp = client.get(reverse("grouping:group_list"))
    assert resp.status_code == 200


def test_create_group_enrolls_selected_students(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    student = UserFactory()
    resp = client.post(
        reverse("grouping:group_create"),
        {"name": "7A", "course": course.pk, "teachers": [], "students": [student.pk]},
    )
    assert resp.status_code == 302
    group = Group.objects.get(name="7A")
    assert GroupMembership.objects.filter(group=group, student=student).exists()
    assert Enrollment.objects.filter(student=student, course=course, source="group").exists()


def test_remove_student_via_edit_drops_enrollment(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    group = GroupFactory(course=course)
    student = UserFactory()
    from grouping import services

    services.add_students_to_group(group, [student])
    # Edit with an empty roster -> student removed.
    resp = client.post(
        reverse("grouping:group_edit", args=[group.pk]),
        {"name": group.name, "course": course.pk, "teachers": [], "students": []},
    )
    assert resp.status_code == 302
    assert not Enrollment.objects.filter(student=student, course=course).exists()


def test_archive_group_drops_access(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    group = GroupFactory(course=course)
    student = UserFactory()
    from grouping import services

    services.add_students_to_group(group, [student])
    resp = client.post(reverse("grouping:group_archive", args=[group.pk]))
    assert resp.status_code == 302
    group.refresh_from_db()
    assert group.archived is True
    assert not Enrollment.objects.filter(student=student, course=course).exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_group_views.py -v`
Expected: FAIL — group URLs/views not defined.

- [ ] **Step 3: Append group views to `grouping/views.py`**

```python
from django.core.exceptions import PermissionDenied

from accounts.models import User
from grouping import scoping
from grouping.forms import GroupForm
from grouping.models import Cohort
from grouping.models import Group


def _student_ids_from_post(request):
    """Parse the roster <select name='students'> POST list. Silently drops
    non-integer values so a malformed/forged field can't 500 the view; foreign
    pks are harmless — set_group_members filters to real User rows."""
    ids = []
    for raw in request.POST.getlist("students"):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def _student_choices(request):
    """Users for the roster picker, optionally filtered by the ?cohort=<slug> GET
    param (the spec's cohort-filtered picker; CA holds grouping.view_cohort for this)."""
    cohort_slug = request.GET.get("cohort")
    qs = User.objects.order_by("username")
    if cohort_slug:
        qs = qs.filter(cohort_membership__cohort__slug=cohort_slug)
    return qs


def _cohort_choices():
    return Cohort.objects.filter(archived=False).order_by("-is_default", "name")


@login_required
@permission_required("grouping.view_group", raise_exception=True)
def group_list(request):
    show_archived = request.GET.get("archived") == "1"
    groups = scoping.groups_manageable_by(request.user).filter(archived=show_archived)
    return render(
        request,
        "grouping/group_list.html",
        {"groups": groups.order_by("course__title", "name"), "show_archived": show_archived},
    )


@login_required
@permission_required("grouping.add_group", raise_exception=True)
def group_create(request):
    if request.method == "POST":
        form = GroupForm(request.POST)
        if form.is_valid():
            course = form.cleaned_data["course"]
            # A CA may only create groups on courses they own; PA may use any.
            if not (
                request.user.has_perm("courses.change_course")
                or course.owner_id == request.user.id
            ):
                raise PermissionDenied
            group = form.save()
            services.set_group_members(
                group, _student_ids_from_post(request), added_by=request.user
            )
            return redirect("grouping:group_edit", pk=group.pk)
    else:
        form = GroupForm()
    return render(
        request,
        "grouping/group_form.html",
        {
            "form": form,
            "creating": True,
            "all_students": _student_choices(request),
            "cohorts": _cohort_choices(),
            "current_ids": set(),
        },
    )


@login_required
@permission_required("grouping.change_group", raise_exception=True)
def group_edit(request, pk):
    group = get_object_or_404(scoping.groups_manageable_by(request.user), pk=pk)
    if request.method == "POST":
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            group = form.save()
            services.set_group_members(
                group, _student_ids_from_post(request), added_by=request.user
            )
            return redirect("grouping:group_edit", pk=group.pk)
    else:
        form = GroupForm(instance=group)
    current_ids = set(group.memberships.values_list("student_id", flat=True))
    return render(
        request,
        "grouping/group_form.html",
        {
            "form": form,
            "creating": False,
            "group": group,
            "current_ids": current_ids,
            "all_students": _student_choices(request),
            "cohorts": _cohort_choices(),
        },
    )


@login_required
@permission_required("grouping.change_group", raise_exception=True)
@require_POST
def group_archive(request, pk):
    group = get_object_or_404(scoping.groups_manageable_by(request.user), pk=pk)
    services.set_group_archived(group, not group.archived)
    return redirect("grouping:group_list")


@login_required
@permission_required("grouping.delete_group", raise_exception=True)
def group_delete(request, pk):
    group = get_object_or_404(scoping.groups_manageable_by(request.user), pk=pk)
    if request.method == "POST":
        services.delete_group(group)
        return redirect("grouping:group_list")
    return render(
        request,
        "grouping/group_confirm_delete.html",
        {"group": group, "member_count": group.memberships.count()},
    )
```

- [ ] **Step 4: Append group routes to `grouping/urls.py`**

```python
    path("manage/groups/", views.group_list, name="group_list"),
    path("manage/groups/new/", views.group_create, name="group_create"),
    path("manage/groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("manage/groups/<int:pk>/archive/", views.group_archive, name="group_archive"),
    path("manage/groups/<int:pk>/delete/", views.group_delete, name="group_delete"),
```

- [ ] **Step 5: Create the templates**

`templates/grouping/group_list.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% trans "Groups" %}</h1>
<a class="btn" href="{% url 'grouping:group_create' %}">{% trans "New group" %}</a>
<a href="?archived={% if show_archived %}0{% else %}1{% endif %}">
  {% if show_archived %}{% trans "Show active" %}{% else %}{% trans "Show archived" %}{% endif %}
</a>
<ul class="card-list">
  {% for group in groups %}
  <li>
    <a href="{% url 'grouping:group_edit' group.pk %}">{{ group.name }}</a>
    <span class="muted">{{ group.course.title }}</span>
    <form method="post" action="{% url 'grouping:group_archive' group.pk %}" style="display:inline">
      {% csrf_token %}
      <button type="submit">{% if group.archived %}{% trans "Un-archive" %}{% else %}{% trans "Archive" %}{% endif %}</button>
    </form>
    <a href="{% url 'grouping:group_delete' group.pk %}">{% trans "Delete" %}</a>
  </li>
  {% empty %}
  <li>{% trans "No groups yet." %}</li>
  {% endfor %}
</ul>
{% endblock %}
```

`templates/grouping/group_form.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% if creating %}{% trans "New group" %}{% else %}{% trans "Edit group" %}{% endif %}</h1>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <fieldset>
    <legend>{% trans "Students" %}</legend>
    {# Roster picker: a multi-select of users. Server reads request.POST.getlist('students'). #}
    <select name="students" multiple size="10">
      {% for student in all_students %}
      <option value="{{ student.pk }}" {% if student.pk in current_ids %}selected{% endif %}>{{ student }}</option>
      {% endfor %}
    </select>
  </fieldset>
  <button type="submit">{% trans "Save" %}</button>
  <a href="{% url 'grouping:group_list' %}">{% trans "Cancel" %}</a>
</form>
{% endblock %}
```

The `all_students` / `current_ids` context this template consumes is already provided by `group_create` and `group_edit` in Step 3 (via the `_student_choices` / `_cohort_choices` helpers defined there). No further context wiring is needed.

- [ ] **Step 6: Add the CA/PA nav link in `templates/base.html`**

Next to the Cohorts link added in Task 9:
```html
          {% if perms.grouping.view_group %}
          <a class="app-nav__link" href="{% url 'grouping:group_list' %}">{% trans "Groups" %}</a>
          {% endif %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_group_views.py -v`
Expected: PASS.

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/views.py grouping/urls.py templates/grouping/ templates/base.html tests/test_grouping_group_views.py
git commit -m "feat(3a): group list (5.15) + group create/edit/archive/delete (5.16)"
```

---

### Task 11: Group detail (4.2) + "My groups & collections" (4.1)

**Files:**
- Modify: `grouping/views.py` (append `group_detail`, `my_groups`)
- Modify: `grouping/urls.py` (append routes)
- Create: `templates/grouping/group_detail.html`
- Create: `templates/grouping/my_groups.html`
- Modify: `templates/base.html` (T/CA/PA nav link to "My groups")
- Test: `tests/test_grouping_detail_views.py`

**Interfaces:**
- Consumes: scoping (Task 6).
- Produces: URL names `group_detail` (`<int:pk>`), `my_groups`. `group_detail` shows the student roster (from `GroupMembership`), the teacher list (from `teachers` M2M + the course owner labeled "(owner)"), and the student-member count. **Roster + counts only — no progress/results.**

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_detail_views.py`:
```python
import pytest
from django.urls import reverse

from grouping import services
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_group_detail_shows_roster_and_owner(client):
    pa = make_pa(client)
    owner = UserFactory(username="courseowner")
    course = CourseFactory(owner=owner)
    group = GroupFactory(course=course)
    student = UserFactory(username="rosterkid")
    services.add_students_to_group(group, [student])
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "rosterkid" in body
    assert "courseowner" in body  # owner surfaced in the teacher list
    assert resp.context["student_count"] == 1


def test_my_groups_lists_visible_groups(client):
    pa = make_pa(client)
    GroupFactory()
    resp = client.get(reverse("grouping:my_groups"))
    assert resp.status_code == 200


def test_group_detail_403_without_view_group_perm(client):
    # A user with no grouping perms is stopped at the permission gate (403),
    # before scoping runs.
    from tests.factories import make_login

    make_login(client, "noperms")
    group = GroupFactory()
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 403


def test_group_detail_404_for_teacher_out_of_scope(client):
    # A Teacher HAS grouping.view_group (passes the gate) but neither manages nor
    # teaches THIS group -> groups_visible_to excludes it -> get_object_or_404 = 404.
    # This is the real security-boundary assertion (distinct from the 403 above).
    from django.contrib.auth.models import Group as AuthGroup

    from institution.roles import seed_roles
    from tests.factories import make_login

    seed_roles()
    teacher = make_login(client, "scopedoutteacher")
    teacher.groups.add(AuthGroup.objects.get(name="Teacher"))
    group = GroupFactory()  # teacher does not teach it
    resp = client.get(reverse("grouping:group_detail", args=[group.pk]))
    assert resp.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_detail_views.py -v`
Expected: FAIL — routes/views not defined.

- [ ] **Step 3: Append the views to `grouping/views.py`**

```python
@login_required
@permission_required("grouping.view_group", raise_exception=True)
def group_detail(request, pk):
    group = get_object_or_404(scoping.groups_visible_to(request.user), pk=pk)
    students = group.memberships.select_related("student").order_by("student__username")
    teachers = list(group.teachers.order_by("username"))
    owner = group.course.owner  # surfaced separately, labeled "(owner)", non-removable
    return render(
        request,
        "grouping/group_detail.html",
        {
            "group": group,
            "students": students,
            "teachers": teachers,
            "owner": owner,
            "student_count": len(students),
        },
    )


@login_required  # intentionally login-only (no perm gate): scoping yields an empty
# list for a user who manages/teaches nothing, so a plain student simply sees an
# empty "My groups & collections" page. The nav link is perm-gated so they never
# see the entry point. This is a deliberate exception to the gate-then-scope rule.
def my_groups(request):
    groups = scoping.groups_visible_to(request.user).filter(archived=False)
    collections = scoping.collections_manageable_by(request.user).filter(archived=False)
    return render(
        request,
        "grouping/my_groups.html",
        {
            "groups": groups.order_by("course__title", "name"),
            "collections": collections.order_by("name"),
        },
    )
```

- [ ] **Step 4: Append routes to `grouping/urls.py`**

```python
    path("groups/mine/", views.my_groups, name="my_groups"),
    path("groups/<int:pk>/", views.group_detail, name="group_detail"),
```

- [ ] **Step 5: Create the templates**

`templates/grouping/group_detail.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{{ group.name }}{% if group.archived %} <span class="badge">{% trans "Archived" %}</span>{% endif %}</h1>
<p class="muted">{{ group.course.title }}</p>

<h2>{% blocktrans count counter=student_count %}{{ counter }} student{% plural %}{{ counter }} students{% endblocktrans %}</h2>
<ul>
  {% for m in students %}<li>{{ m.student }}</li>{% empty %}<li>{% trans "No students." %}</li>{% endfor %}
</ul>

<h2>{% trans "Teachers" %}</h2>
<ul>
  {% if owner %}<li>{{ owner }} <span class="badge">{% trans "owner" %}</span></li>{% endif %}
  {% for t in teachers %}<li>{{ t }}</li>{% endfor %}
</ul>
{% endblock %}
```

`templates/grouping/my_groups.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% trans "My groups & collections" %}</h1>
<h2>{% trans "Groups" %}</h2>
<ul class="card-list">
  {% for group in groups %}
  <li><a href="{% url 'grouping:group_detail' group.pk %}">{{ group.name }}</a> <span class="muted">{{ group.course.title }}</span></li>
  {% empty %}<li>{% trans "No groups." %}</li>
  {% endfor %}
</ul>
<h2>{% trans "Collections" %}</h2>
<ul class="card-list">
  {% for c in collections %}
  <li><a href="{% url 'grouping:collection_detail' c.pk %}">{{ c.name }}</a> <span class="muted">{{ c.course.title }}</span></li>
  {% empty %}<li>{% trans "No collections." %}</li>
  {% endfor %}
</ul>
{% endblock %}
```

(`collection_detail` is defined in Task 12; the `{% url %}` resolves once that route exists. Implement Task 12 before running e2e, but this template is committed here.)

- [ ] **Step 6: Add the nav link in `templates/base.html`**

```html
          {% if perms.grouping.view_collection or perms.grouping.view_group %}
          <a class="app-nav__link" href="{% url 'grouping:my_groups' %}">{% trans "My groups" %}</a>
          {% endif %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_detail_views.py -v`
Expected: `test_group_detail_*` and `test_my_groups_*` PASS. (If `my_groups.html` fails to reverse `collection_detail`, temporarily complete Task 12 first; the two tasks are adjacent and the commit order is Task 11 → Task 12.)

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/views.py grouping/urls.py templates/grouping/ templates/base.html tests/test_grouping_detail_views.py
git commit -m "feat(3a): group detail (4.2) + my groups & collections (4.1)"
```

---

### Task 12: Collection create/edit (4.4) + collection detail (4.3)

**Files:**
- Modify: `grouping/views.py` (append collection views)
- Modify: `grouping/urls.py` (append routes)
- Create: `templates/grouping/collection_form.html`
- Create: `templates/grouping/collection_detail.html`
- Test: `tests/test_grouping_collection_views.py`

**Interfaces:**
- Consumes: `CollectionForm` (Task 8), scoping incl. `can_add_collection_group` (Task 6), `set_collection_groups` (Task 5).
- Produces: URL names `collection_create`, `collection_edit`, `collection_detail` (`<int:pk>`), `collection_delete`. Create gated by `add_collection` perm + `can_add_collection_group` per selected group; `owner` = the creating user. Edit/delete gated by `collections_manageable_by`. Detail shows the **union roster across non-archived member groups + counts only**.

- [ ] **Step 1: Write the failing tests**

`tests/test_grouping_collection_views.py`:
```python
import pytest
from django.urls import reverse

from grouping import services
from grouping.models import Collection
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_create_collection_sets_owner(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    g = GroupFactory(course=course)
    resp = client.post(
        reverse("grouping:collection_create"),
        {"name": "Both 7s", "course": course.pk, "groups": [g.pk]},
    )
    assert resp.status_code == 302
    coll = Collection.objects.get(name="Both 7s")
    assert coll.owner == pa


def test_collection_detail_union_excludes_archived_group(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    g1 = GroupFactory(course=course)
    g2 = GroupFactory(course=course)
    s1 = UserFactory(username="s1")
    s2 = UserFactory(username="s2")
    services.add_students_to_group(g1, [s1])
    services.add_students_to_group(g2, [s2])
    coll = Collection.objects.create(name="Union", course=course, owner=pa)
    services.set_collection_groups(coll, [g1.pk, g2.pk])
    services.set_group_archived(g2, True)  # g2 archived -> s2 excluded
    resp = client.get(reverse("grouping:collection_detail", args=[coll.pk]))
    body = resp.content.decode()
    assert "s1" in body
    assert "s2" not in body
    assert resp.context["student_count"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_grouping_collection_views.py -v`
Expected: FAIL — collection routes/views not defined.

- [ ] **Step 3: Append collection views to `grouping/views.py`**

```python
from grouping.forms import CollectionForm
from grouping.models import Collection


@login_required
@permission_required("grouping.add_collection", raise_exception=True)
def collection_create(request):
    if request.method == "POST":
        form = CollectionForm(request.POST, owner=request.user)
        if form.is_valid():
            # Bootstrap gate: the creator must be allowed to add each selected group.
            for group in form.cleaned_data["groups"]:
                if not scoping.can_add_collection_group(request.user, group):
                    raise PermissionDenied
            collection = form.save()
            return redirect("grouping:collection_detail", pk=collection.pk)
    else:
        form = CollectionForm(owner=request.user)
    return render(
        request, "grouping/collection_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("grouping.change_collection", raise_exception=True)
def collection_edit(request, pk):
    collection = get_object_or_404(
        scoping.collections_manageable_by(request.user), pk=pk
    )
    if request.method == "POST":
        form = CollectionForm(request.POST, instance=collection, owner=request.user)
        if form.is_valid():
            for group in form.cleaned_data["groups"]:
                if not scoping.can_add_collection_group(request.user, group):
                    raise PermissionDenied
            collection = form.save()
            return redirect("grouping:collection_detail", pk=collection.pk)
    else:
        form = CollectionForm(instance=collection, owner=request.user)
    return render(
        request,
        "grouping/collection_form.html",
        {"form": form, "creating": False, "collection": collection},
    )


@login_required
@permission_required("grouping.view_collection", raise_exception=True)
def collection_detail(request, pk):
    collection = get_object_or_404(
        scoping.collections_manageable_by(request.user), pk=pk
    )
    # Union roster across NON-archived member groups only.
    from accounts.models import User

    students = (
        User.objects.filter(
            group_memberships__group__in=collection.groups.filter(archived=False)
        )
        .distinct()
        .order_by("username")
    )
    return render(
        request,
        "grouping/collection_detail.html",
        {
            "collection": collection,
            "students": students,
            "student_count": students.count(),
        },
    )


@login_required
@permission_required("grouping.delete_collection", raise_exception=True)
@require_POST
def collection_delete(request, pk):
    collection = get_object_or_404(
        scoping.collections_manageable_by(request.user), pk=pk
    )
    collection.delete()
    return redirect("grouping:my_groups")
```

- [ ] **Step 4: Append routes to `grouping/urls.py`**

```python
    path("collections/new/", views.collection_create, name="collection_create"),
    path("collections/<int:pk>/", views.collection_detail, name="collection_detail"),
    path("collections/<int:pk>/edit/", views.collection_edit, name="collection_edit"),
    path(
        "collections/<int:pk>/delete/",
        views.collection_delete,
        name="collection_delete",
    ),
```

- [ ] **Step 5: Create the templates**

`templates/grouping/collection_form.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{% if creating %}{% trans "New collection" %}{% else %}{% trans "Edit collection" %}{% endif %}</h1>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">{% trans "Save" %}</button>
  <a href="{% url 'grouping:my_groups' %}">{% trans "Cancel" %}</a>
</form>
{% endblock %}
```

`templates/grouping/collection_detail.html`:
```html
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<h1>{{ collection.name }}</h1>
<p class="muted">{{ collection.course.title }}</p>
<a href="{% url 'grouping:collection_edit' collection.pk %}">{% trans "Edit" %}</a>
<form method="post" action="{% url 'grouping:collection_delete' collection.pk %}" style="display:inline">
  {% csrf_token %}
  <button type="submit">{% trans "Delete" %}</button>
</form>

<h2>{% blocktrans count counter=student_count %}{{ counter }} student{% plural %}{{ counter }} students{% endblocktrans %}</h2>
<ul>
  {% for student in students %}<li>{{ student }}</li>{% empty %}<li>{% trans "No students." %}</li>{% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_grouping_collection_views.py tests/test_grouping_detail_views.py -v`
Expected: PASS (this also unblocks the `collection_detail` reverse used by `my_groups.html` in Task 11).

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add grouping/views.py grouping/urls.py templates/grouping/ tests/test_grouping_collection_views.py
git commit -m "feat(3a): collection create/edit (4.4) + collection detail (4.3, archived-aware union)"
```

---

### Task 13: e2e — real management gestures + full suite green

**Files:**
- Create: `tests/test_e2e_grouping.py`
- Test: itself

**Interfaces:**
- Consumes: all views/URLs (Tasks 9–12), `make_verified_user`, `seed_roles`, role groups.
- Produces: a Playwright e2e that drives the real click path for a multi-student group add and a cohort delete-with-reassignment. No `page.evaluate` shortcuts (per the "e2e must drive real UI" rule).

- [ ] **Step 1: Write the e2e test**

`tests/test_e2e_grouping.py`:
```python
"""Playwright e2e for the grouping management surfaces (Phase 3a).

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user():
    from accounts.emails import ensure_verified_primary_email
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN, seed_roles

    seed_roles()
    user = User.objects.create_user(
        username="e2e_pa", email="e2epa@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(user, "e2epa@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    # Selectors mirror the PROVEN helper in tests/test_e2e_courses.py (and the
    # other e2e suites): allauth's login field is `login` (username OR email),
    # and the form action contains "login". Username login works because the
    # project's existing e2e suites log in by username via this exact pattern.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_create_group_and_add_student_via_ui(page, live_server):
    from courses.models import Enrollment
    from grouping.models import Group
    from tests.factories import CourseFactory, UserFactory

    pa = _make_pa_user()
    course = CourseFactory(owner=pa, slug="e2e-grp-course")
    student = UserFactory(username="e2e_student")

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/groups/new/")
    page.locator("input[name='name']").fill("7A")
    page.select_option("select[name='course']", str(course.pk))
    page.select_option("select[name='students']", str(student.pk))
    page.locator("button[type='submit']").click()

    # Real outcome: membership + group-sourced enrollment created.
    group = Group.objects.get(name="7A")
    assert group.memberships.filter(student=student).exists()
    assert Enrollment.objects.filter(
        student=student, course=course, source="group"
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_delete_cohort_reassigns_to_default_via_ui(page, live_server):
    from grouping import services
    from grouping.models import Cohort, CohortMembership
    from tests.factories import CohortFactory, UserFactory

    _make_pa_user()
    default = services.get_default_cohort()
    other = CohortFactory(name="E2E Spanish")
    student = UserFactory(username="e2e_reassign")
    services.assign_student_to_cohort(student, other)

    _login(page, live_server, "e2e_pa")
    page.goto(f"{live_server.url}/manage/cohorts/{other.slug}/delete/")
    page.locator("button[type='submit']").click()

    assert not Cohort.objects.filter(pk=other.pk).exists()
    assert CohortMembership.objects.get(user=student).cohort == default
```

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_grouping.py -m e2e -v`
Expected: PASS (Playwright drives the real forms; both DB assertions hold).

- [ ] **Step 3: Run the full non-e2e suite to confirm no regressions**

Run: `uv run pytest`
Expected: PASS (all pre-existing tests + the new `tests/test_grouping_*.py`).

- [ ] **Step 4: Verify the deploy/role step works end-to-end**

Run: `uv run python manage.py migrate` then `uv run python manage.py setup_roles`
Expected: `setup_roles` prints "Roles ensured." with no `Permission.DoesNotExist` — confirming the `migrate → setup_roles` sequence attaches the new `grouping.*` perms.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add tests/test_e2e_grouping.py
git commit -m "test(3a): e2e for group add + cohort delete-reassign; full suite green"
```

---

## Self-Review

**Spec coverage check (spec §-by-§ → task):**
- §2 models (Cohort/CohortMembership/Group/GroupMembership/Collection, constraints, slug rules, immutability guards) → **Task 1**.
- §2 default-membership signal + §7 backfill migration → **Task 2**.
- §2 exactly-one-default (promote/demote ordering, guards) + reassignment → **Task 3**.
- §3 recompute truth table, batch fan-out, archive/un-archive/delete, progress-preserved, source precedence → **Task 4** (truth table) + invariants exercised in Task 4 tests.
- §2 collection M2M course-match (`m2m_changed` + form) → **Task 5** (receiver) + **Task 8** (form).
- §4 scoping functions + archived-rows-returned + bootstrap predicate → **Task 6**.
- §4/§7 permission seeding via extended `seed_roles()` + `setup_roles` (NOT RunPython) → **Task 7**; verified in **Task 13 Step 4**.
- §2 forms + immutability widget locking → **Task 8**.
- §5 surfaces: 6.4 → Task 9; 5.15/5.16 → Task 10; 4.2/4.1 → Task 11; 4.4/4.3 → Task 12.
- §6 testing (truth table, cohort invariants, collection validation, scoping per role, batch/cohort, e2e real gestures) → distributed across Tasks 3–12 + **Task 13**.
- §3 cohort-ops-are-an-enrollment-no-op → asserted in **Task 3** (no recompute import in cohort service) and **Task 4** (recompute only on group ops).

**Placeholder scan:** No `TBD`/`TODO`/"add error handling"/"similar to Task N" remain; every code step shows complete code.

**Type/name consistency:** service names used by views match their definitions — `recompute_enrollment`, `add_students_to_group`, `remove_students_from_group`, `set_group_members`, `set_group_archived`, `delete_group` (Task 4); `promote_default`, `assign_student_to_cohort`, `archive_cohort`, `delete_cohort`, `get_default_cohort` (Task 3); `set_collection_groups` (Task 5). Scoping names match across Tasks 6/10/11/12: `groups_manageable_by`, `groups_visible_to`, `collections_manageable_by`, `can_add_collection_group`. URL names referenced in templates (`grouping:cohort_*`, `grouping:group_*`, `grouping:collection_*`, `grouping:my_groups`) all have matching `path(... name=...)` entries.

**Known cross-task ordering note:** `templates/grouping/my_groups.html` (Task 11) reverses `grouping:collection_detail`, which is defined in Task 12. Build order is sequential (11 → 12); Task 11 Step 7 flags this. Under subagent-driven execution, run Task 11 and Task 12 before treating the my_groups page as fully green.
