# Phase 5b — User & Role Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a Platform Admin a bespoke `/manage/people/` surface (Users + Invitations tabs) to invite users with a role, search/list everyone, change a user's role, and deactivate/reactivate accounts — no Django admin.

**Architecture:** A new role service (`accounts/services.py`) is the single point that enforces "exactly one role" + staff-sync + the last-PA lockout guard, reused by both the accept-flow and the management UI. The `Invitation` model gains a `role` field so invites carry their target role. Management views live in a new `accounts/views_manage.py`, gated on the existing `accounts.*_user` permissions (already granted to Platform Admin). Two server-rendered tabs (two URLs sharing a shell), no JS required.

**Tech Stack:** Django 5.2, PostgreSQL, allauth, pytest + factory_boy, Playwright (e2e), ruff, uv.

## Global Constraints

- **Tooling:** bash `ruff`/`pytest`/`python` are NOT on PATH. Use `uv run ruff check .`, `uv run ruff format .`, `uv run pytest`, `uv run python manage.py ...`. CI runs `ruff format --check`, so run `uv run ruff format .` before every commit.
- **Role source of truth:** the 4 role names + helpers live ONLY in `institution/roles.py`. Never redeclare role strings elsewhere. Stored role value == exact Group name (`"Student"`, `"Teacher"`, `"Course Admin"`, `"Platform Admin"`).
- **i18n:** every new user-facing string is wrapped in `{% trans %}`/`{% blocktrans %}` (templates) or `gettext`/`gettext_lazy` (Python). Module-level translatable dicts MUST use `gettext_lazy` (eager `gettext` at import freezes the label to the import-time language — the PR #46 burn). After UI tasks, run makemessages/compilemessages (Task 12).
- **Django multi-line comments:** `{# #}` must be single-line; use `{% comment %}…{% endcomment %}` for multi-line, or it renders as visible text.
- **Styling:** every view ships styled (Task 11) per the design language; light + dark; mobile; verify with throwaway Playwright screenshots, deleted after review. Templates use only utility classes that are either **global** in `core/.../app.css` (`.btn`, `.btn--ghost`, `.btn--primary`, `.btn--small`, `.badge`, `.manage`, `.manage__head`, `.manage__title`, `.manage__filters`, `.manage__field`, `.manage__empty`, `.card-list`, `.row-actions`, `.alert`) or **defined by this slice** in `people.css` (`.manage__tabs`/`.manage__tab`, `.people-table`, `.invite-form`, `.pagination`, `.user-activation`, **`.form__actions`**, **`.btn--danger`** — the last two are NOT global). Don't assume `.btn--danger`/`.form__actions` exist globally; Task 11 defines them.
- **Permissions:** `accounts.add_user/change_user/view_user/delete_user` are ALREADY in `PLATFORM_ADMIN_PERMS` (`institution/roles.py`) and applied by `setup_roles`. No new grant work; views just consume them.
- **Tests:** `@pytest.mark.django_db` on DB tests; e2e marked `@pytest.mark.e2e` and `@pytest.mark.django_db(transaction=True)`, driving REAL UI gestures (no `page.evaluate` shortcuts).
- **Auth Groups hold ONLY the 4 roles** (cohorts/grouping use separate models), so `user.groups.set([role_group])` is a safe full-replace.

---

### Task 1: Role helpers in `institution/roles.py`

**Files:**
- Modify: `institution/roles.py`
- Test: `tests/test_role_helpers.py` (create)

**Interfaces:**
- Produces: `ROLE_LABELS: dict[str, lazy-str]`, `ROLE_CHOICES: list[tuple[str, lazy-str]]`, `role_is_staff(role: str) -> bool` — all importable from `institution.roles`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_role_helpers.py`:

```python
from institution.roles import (
    COURSE_ADMIN,
    PLATFORM_ADMIN,
    ROLE_CHOICES,
    ROLE_LABELS,
    ROLE_NAMES,
    STUDENT,
    TEACHER,
    role_is_staff,
)


def test_role_is_staff_only_student_is_non_staff():
    assert role_is_staff(STUDENT) is False
    assert role_is_staff(TEACHER) is True
    assert role_is_staff(COURSE_ADMIN) is True
    assert role_is_staff(PLATFORM_ADMIN) is True


def test_role_choices_values_are_exact_group_names():
    values = [value for value, _label in ROLE_CHOICES]
    assert values == ROLE_NAMES  # exact Group-name strings, in order


def test_role_labels_cover_all_four_roles():
    assert set(ROLE_LABELS) == set(ROLE_NAMES)


def test_role_choices_labels_come_from_role_labels():
    for value, label in ROLE_CHOICES:
        assert label == ROLE_LABELS[value]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_role_helpers.py -v`
Expected: FAIL with `ImportError` (ROLE_LABELS / ROLE_CHOICES / role_is_staff not defined).

- [ ] **Step 3: Write minimal implementation**

In `institution/roles.py`, add the import at the top (after the existing imports):

```python
from django.utils.translation import gettext_lazy as _
```

Then add, immediately after the `ROLE_NAMES = [...]` line:

```python
# Translatable display labels for the 4 roles. gettext_lazy (NOT gettext): this
# dict is built at module import, and eager gettext would freeze the labels to the
# import-time language. This is the single display source — the role column,
# filters, and selects all render through it; the Group name stays the storage key.
ROLE_LABELS = {
    STUDENT: _("Student"),
    TEACHER: _("Teacher"),
    COURSE_ADMIN: _("Course Admin"),
    PLATFORM_ADMIN: _("Platform Admin"),
}

# (group_name, label) pairs for model `choices` and form selects. Labels are the
# SAME ROLE_LABELS — never a parallel set.
ROLE_CHOICES = [(name, ROLE_LABELS[name]) for name in ROLE_NAMES]


def role_is_staff(role):
    """True for every role except Student. Used by set_user_role to derive is_staff."""
    return role != STUDENT
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_role_helpers.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format institution/roles.py tests/test_role_helpers.py
uv run ruff check institution/roles.py tests/test_role_helpers.py
git add institution/roles.py tests/test_role_helpers.py
git commit -m "feat(5b): ROLE_CHOICES/ROLE_LABELS (gettext_lazy) + role_is_staff helper"
```

---

### Task 2: `Invitation.role` field + migration

**Files:**
- Modify: `accounts/models.py:46-101` (the `Invitation` model)
- Create: `accounts/migrations/00NN_invitation_role.py` (generated)
- Test: `tests/test_invitation_role_field.py` (create)

**Interfaces:**
- Consumes: `institution.roles.ROLE_CHOICES`, `STUDENT` (Task 1).
- Produces: `Invitation.role` (CharField, default `"Student"`, choices = ROLE_CHOICES).

- [ ] **Step 1: Write the failing test**

Create `tests/test_invitation_role_field.py`:

```python
import pytest

from accounts.models import Invitation
from institution.roles import STUDENT, TEACHER


@pytest.mark.django_db
def test_invitation_role_defaults_to_student():
    inv = Invitation.objects.create(email="a@school.edu")
    assert inv.role == STUDENT


@pytest.mark.django_db
def test_invitation_role_can_be_set():
    inv = Invitation.objects.create(email="t@school.edu", role=TEACHER)
    inv.refresh_from_db()
    assert inv.role == TEACHER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_invitation_role_field.py -v`
Expected: FAIL (`TypeError`/`FieldError`: `role` is not a field).

- [ ] **Step 3: Add the field**

In `accounts/models.py`, add the import near the top:

```python
from institution.roles import ROLE_CHOICES
from institution.roles import STUDENT
```

In the `Invitation` model, add the field right after the `email` field (line 52):

```python
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default=STUDENT,
        help_text="Role the invitee lands in on accept.",
    )
```

Also update the now-stale class docstring (currently "...lands the user as a
Student.") to reflect the carried role:

```python
class Invitation(models.Model):
    """A single-use, expiring invite to self-register under signup_policy == 'invite'.

    Email-bound; accepting it pre-verifies that email and lands the user in the
    invite's `role` (default Student).
    """
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations accounts`
Expected: creates `accounts/migrations/00NN_invitation_role.py` with an `AddField` for `role` (default `"Student"`). The `AddField` default backfills all existing pending `Invitation` rows to Student — consistent with today's accept flow (which already hardcodes Student), so a conscious no-surprise consequence.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_invitation_role_field.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format accounts/models.py tests/test_invitation_role_field.py
uv run ruff check accounts/models.py
git add accounts/models.py accounts/migrations/ tests/test_invitation_role_field.py
git commit -m "feat(5b): Invitation.role field + migration (default Student)"
```

---

### Task 3: `set_user_role` service

**Files:**
- Create: `accounts/services.py`
- Test: `tests/test_set_user_role.py` (create)

**Interfaces:**
- Consumes: `institution.roles.role_is_staff`, role-name constants (Task 1).
- Produces: `accounts.services.set_user_role(user, role: str) -> None` — raises `ValueError` on a falsy role; makes `user` hold exactly the named role Group; sets `is_staff = role_is_staff(role) or user.is_superuser`; runs in `transaction.atomic()`; sets `is_staff` BEFORE `groups.set`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_set_user_role.py`:

```python
import pytest

from accounts.models import User
from accounts.services import set_user_role
from grouping.models import Cohort, CohortMembership
from institution.roles import PLATFORM_ADMIN, STUDENT, TEACHER, seed_roles


@pytest.fixture
def roles(db):
    seed_roles()


@pytest.mark.django_db
def test_set_role_makes_user_hold_exactly_one_group(roles):
    user = User.objects.create_user(username="u1")
    set_user_role(user, TEACHER)
    assert list(user.groups.values_list("name", flat=True)) == [TEACHER]
    set_user_role(user, PLATFORM_ADMIN)
    assert list(user.groups.values_list("name", flat=True)) == [PLATFORM_ADMIN]


@pytest.mark.django_db
def test_set_role_sets_is_staff_from_role(roles):
    user = User.objects.create_user(username="u2")
    set_user_role(user, TEACHER)
    user.refresh_from_db()
    assert user.is_staff is True
    set_user_role(user, STUDENT)
    user.refresh_from_db()
    assert user.is_staff is False


@pytest.mark.django_db
def test_superuser_keeps_is_staff_even_as_student(roles):
    su = User.objects.create_superuser(username="root", password="x")
    set_user_role(su, STUDENT)
    su.refresh_from_db()
    assert su.is_staff is True  # admin recovery path preserved
    assert su.is_superuser is True  # never modified


@pytest.mark.django_db
def test_demotion_to_student_rejoins_default_cohort(roles):
    # Guards the is_staff-before-groups.set ordering: the Phase-3a cohort signal
    # reads is_staff during groups.set. A Teacher (staff, no cohort) demoted to
    # Student (non-staff) must be (re)joined to the Default cohort. Use the REAL
    # default cohort (migration grouping/0002 creates one) — keying on the literal
    # name "Default" could collide with the partial-unique is_default index.
    if not Cohort.objects.filter(is_default=True).exists():
        Cohort.objects.create(name="Default", is_default=True)
    user = User.objects.create_user(username="u3")
    set_user_role(user, TEACHER)
    assert not CohortMembership.objects.filter(user=user).exists()
    set_user_role(user, STUDENT)
    assert CohortMembership.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_blank_role_is_rejected(roles):
    user = User.objects.create_user(username="u4")
    with pytest.raises(ValueError):
        set_user_role(user, "")
```

> NOTE for the implementer: confirm the Default-cohort bootstrap matches Phase-3a. If `seed_roles`/migrations already create the default cohort, drop the `Cohort.objects.get_or_create` line; if the signal needs an existing default cohort, keep it. Inspect `grouping/models.py` + `grouping/signals.py` before finalizing this test.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_set_user_role.py -v`
Expected: FAIL (`ModuleNotFoundError: accounts.services`).

- [ ] **Step 3: Write the service**

Create `accounts/services.py`:

```python
"""Platform-admin people services: the single role-swap point + lockout guards."""

from django.contrib.auth.models import Group
from django.db import transaction

from institution.roles import role_is_staff


def set_user_role(user, role):
    """Make `user` hold exactly the one role Group named `role`, syncing is_staff.

    Order matters and is pinned: is_staff is set + saved BEFORE groups.set, because
    the Phase-3a cohort m2m_changed receiver reads `user.is_staff` during
    `groups.set` to decide Default-cohort membership. If groups changed first, a
    Teacher->Student demote would still look like staff at signal time and not be
    rejoined to the Default cohort. Superusers always keep is_staff=True (Django
    admin login requires it — the recovery path); is_superuser is never modified.
    Runs atomic so the staff write, group swap, and cohort sync commit together.
    """
    if not role:
        raise ValueError("set_user_role requires a non-empty role name")
    # get_or_create (NOT get): preserves the prior _consume_and_create behavior so
    # accept/SSO flows that have not called seed_roles still work; setup_roles
    # assigns the perms in prod. (Using .get would raise Group.DoesNotExist and
    # turn existing non-seeded accept/SSO tests red.)
    group, _ = Group.objects.get_or_create(name=role)
    with transaction.atomic():
        user.is_staff = role_is_staff(role) or user.is_superuser
        user.save(update_fields=["is_staff"])
        # Full replace is safe: auth Groups hold only the 4 roles in this app.
        user.groups.set([group])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_set_user_role.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format accounts/services.py tests/test_set_user_role.py
uv run ruff check accounts/services.py tests/test_set_user_role.py
git add accounts/services.py tests/test_set_user_role.py
git commit -m "feat(5b): set_user_role service (atomic, is_staff-before-groups, superuser-safe)"
```

---

### Task 4: Last-active-Platform-Admin lockout helper

**Files:**
- Modify: `accounts/services.py`
- Test: `tests/test_lockout_guard.py` (create)

**Interfaces:**
- Produces: `accounts.services.is_last_active_platform_admin(user, *, lock=False) -> bool` — true iff the set of active Platform-Admin-group members is exactly `{user}`. `lock=True` issues `select_for_update` (call inside a transaction for the authoritative check).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lockout_guard.py`:

```python
import pytest

from accounts.models import User
from accounts.services import is_last_active_platform_admin, set_user_role
from institution.roles import PLATFORM_ADMIN, seed_roles


@pytest.fixture
def roles(db):
    seed_roles()


@pytest.mark.django_db
def test_sole_active_pa_is_last(roles):
    pa = User.objects.create_user(username="pa")
    set_user_role(pa, PLATFORM_ADMIN)
    assert is_last_active_platform_admin(pa) is True


@pytest.mark.django_db
def test_two_pas_neither_is_last(roles):
    pa1 = User.objects.create_user(username="pa1")
    pa2 = User.objects.create_user(username="pa2")
    set_user_role(pa1, PLATFORM_ADMIN)
    set_user_role(pa2, PLATFORM_ADMIN)
    assert is_last_active_platform_admin(pa1) is False


@pytest.mark.django_db
def test_inactive_pa_does_not_count(roles):
    active = User.objects.create_user(username="pa_a")
    inactive = User.objects.create_user(username="pa_i", is_active=False)
    set_user_role(active, PLATFORM_ADMIN)
    set_user_role(inactive, PLATFORM_ADMIN)
    assert is_last_active_platform_admin(active) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_lockout_guard.py -v`
Expected: FAIL (`ImportError`: is_last_active_platform_admin).

- [ ] **Step 3: Add the helper**

In `accounts/services.py`, add the imports:

```python
from accounts.models import User
from institution.roles import PLATFORM_ADMIN
```

and append:

```python
def is_last_active_platform_admin(user, *, lock=False):
    """True iff `user` is the ONLY active member of the Platform Admin group.

    Counts by group membership; superusers outside the PA group are a separate
    recovery path and are not counted. Pass lock=True inside a transaction to take
    a row lock (authoritative check that closes the deactivate/demote TOCTOU window).
    """
    qs = User.objects.filter(is_active=True, groups__name=PLATFORM_ADMIN)
    if lock:
        qs = qs.select_for_update()
    ids = list(qs.values_list("id", flat=True))
    return ids == [user.id]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_lockout_guard.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format accounts/services.py tests/test_lockout_guard.py
uv run ruff check accounts/services.py
git add accounts/services.py tests/test_lockout_guard.py
git commit -m "feat(5b): is_last_active_platform_admin lockout helper"
```

---

### Task 5: Accept-flow assigns the invited role (local + SSO)

**Files:**
- Modify: `accounts/views.py:76-93` (`_consume_and_create`)
- Modify: `accounts/adapters.py:85-95` (`_consume_invitation`)
- Test: `tests/test_accept_role.py` (create)

**Interfaces:**
- Consumes: `accounts.services.set_user_role` (Task 3), `Invitation.role` (Task 2).
- Behavior: local accept assigns `locked.role`; SSO-JIT assigns the consumed invite's role, or Student when no pending invite under open policy.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accept_role.py`:

```python
import pytest

from accounts.forms import AcceptInviteForm
from accounts.models import Invitation, User
from accounts.views import _consume_and_create
from institution.roles import TEACHER, seed_roles


@pytest.mark.django_db
def test_local_accept_assigns_invited_role():
    seed_roles()
    inv = Invitation.objects.create(email="newteacher@school.edu", role=TEACHER)
    form = AcceptInviteForm(
        {"username": "newteacher", "password": TEST_PASSWORD},
        invited_email=inv.email,
    )
    assert form.is_valid(), form.errors
    user = _consume_and_create(inv, form)
    assert list(user.groups.values_list("name", flat=True)) == [TEACHER]
    assert user.is_staff is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_accept_role.py -v`
Expected: FAIL — user lands as Student (current hardcode), so `["Teacher"]` assertion fails.

- [ ] **Step 3: Update the local accept flow**

In `accounts/views.py`, replace the hardcoded Student block in `_consume_and_create` (currently lines 88-90):

```python
        ensure_verified_primary_email(user, locked.email)
        group, _ = Group.objects.get_or_create(name=STUDENT)
        user.groups.add(group)
```

with:

```python
        ensure_verified_primary_email(user, locked.email)
        set_user_role(user, locked.role)
```

Update imports at the top of `accounts/views.py`: remove the now-unused `from django.contrib.auth.models import Group` and `from institution.roles import STUDENT` IF they are no longer referenced elsewhere in the file (grep first); add:

```python
from accounts.services import set_user_role
```

> The `set_user_role` call already runs its own `transaction.atomic()`; it nests safely inside the existing `_consume_and_create` atomic block (savepoint).

- [ ] **Step 4: Update the SSO-JIT path**

In `accounts/adapters.py`, in `_consume_invitation`, after marking the invite accepted, assign the role; and add a Student default for the invitation-less open-signup case. Replace the method body (lines 85-95) with:

```python
    def _consume_invitation(self, sociallogin, user):
        from accounts.services import set_user_role
        from institution.roles import STUDENT

        invitation = getattr(sociallogin, "_libli_invitation", None)
        if invitation is None and user.email:
            invitation = Invitation.find_pending(user.email)
        if invitation is None:
            # Open-policy SSO signup with no pending invite -> default to Student.
            # (Closed policy never reaches here: creation is gated earlier.)
            set_user_role(user, STUDENT)
            return
        with transaction.atomic():
            locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
            if locked.is_valid():
                locked.accepted_at = timezone.now()
                locked.save(update_fields=["accepted_at"])
                set_user_role(user, locked.role)
```

> Local imports inside the method avoid any import-time cycle between `adapters` and `services`/`models`.

- [ ] **Step 5: Guard the `assign_default_student_group` signal against double-assignment**

`accounts/signals.py` has an existing `@receiver(user_signed_up)
assign_default_student_group` that unconditionally does `user.groups.add(Student)`.
For an SSO signup, allauth sends `user_signed_up` **after** `save_user` (which now
runs `set_user_role`), so a Teacher/CA/PA invitee would end up in **two** role
groups (their role + Student). Guard the signal to skip when the user already holds
a role group. In `accounts/signals.py`, replace the function body:

```python
@receiver(user_signed_up)
def assign_default_student_group(sender, request, user, **kwargs):
    """New self-signups default to Student — UNLESS a role was already assigned
    (e.g. an SSO invite consumed via set_user_role in the adapter's save_user, which
    runs before this signal). Skipping then preserves the exactly-one-role invariant.
    Open local self-signup (no set_user_role) still lands Student here."""
    from institution.roles import ROLE_NAMES

    if user.groups.filter(name__in=ROLE_NAMES).exists():
        return
    group, _ = Group.objects.get_or_create(name=STUDENT)
    user.groups.add(group)
```

Add a test to `tests/test_accept_role.py` (add `from accounts.services import
set_user_role` to its imports):

```python
@pytest.mark.django_db
def test_signal_skips_when_role_already_assigned():
    # Simulates the SSO order: set_user_role ran in save_user, THEN user_signed_up
    # fires. The signal must NOT add Student on top of the already-assigned role.
    from accounts.signals import assign_default_student_group

    seed_roles()
    user = User.objects.create_user(username="ssoteacher")
    set_user_role(user, TEACHER)
    assign_default_student_group(sender=None, request=None, user=user)
    assert list(user.groups.values_list("name", flat=True)) == [TEACHER]
```

- [ ] **Step 6: Run tests + the existing invitation/SSO suites**

Run: `uv run pytest tests/test_accept_role.py tests/test_invitations.py tests/test_sso_provisioning.py -v`
Expected: PASS. The local accept and SSO paths assign the invited role; the guarded
signal no longer double-adds Student; existing non-seeded invitation/SSO tests stay
green because `set_user_role` uses `get_or_create` (Task 3).

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format accounts/views.py accounts/adapters.py accounts/signals.py tests/test_accept_role.py
uv run ruff check accounts/views.py accounts/adapters.py accounts/signals.py
git add accounts/views.py accounts/adapters.py accounts/signals.py tests/test_accept_role.py
git commit -m "feat(5b): accept flow assigns invited role (local + SSO-JIT); guard default-student signal"
```

---

### Task 6: Invitation services (create-or-refresh, revoke, resend)

**Files:**
- Modify: `accounts/services.py`
- Test: `tests/test_invitation_services.py` (create)

**Interfaces:**
- Consumes: `accounts.provisioning.resolve_user_for_email`, `accounts.invitations.send_invitation_email`, `accounts.models.Invitation` + `INVITE_TTL`.
- Produces:
  - `accounts.services.InvitationError(Exception)`
  - `create_or_refresh_invitation(*, email, role, invited_by) -> tuple[Invitation, bool]` — raises `InvitationError` if the email already has an account (active OR inactive — checked FIRST, before the pending-refresh path); otherwise refreshes an existing pending invite (updating role/invited_by/expires_at) or creates a new one; sends the email; returns `(invitation, created)`.
  - `revoke_invitation(invitation) -> None` — deletes the row.
  - `resend_invitation(invitation) -> None` — refreshes `expires_at` explicitly and resends.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_invitation_services.py`:

```python
import pytest

from accounts.models import Invitation, User
from accounts.services import (
    InvitationError,
    create_or_refresh_invitation,
    resend_invitation,
    revoke_invitation,
)
from institution.roles import COURSE_ADMIN, STUDENT, TEACHER


@pytest.mark.django_db
def test_create_new_invite_sets_role_and_inviter(
    django_capture_on_commit_callbacks, mailoutbox
):
    pa = User.objects.create_user(username="pa")
    # The new-row email is sent by the post_save signal via transaction.on_commit,
    # so capture+execute on_commit callbacks to observe exactly ONE email (not two).
    with django_capture_on_commit_callbacks(execute=True):
        inv, created = create_or_refresh_invitation(
            email="new@school.edu", role=TEACHER, invited_by=pa
        )
    assert created is True
    assert inv.role == TEACHER
    assert inv.invited_by == pa
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_existing_active_account_is_rejected(mailoutbox):
    User.objects.create_user(username="taken", email="taken@school.edu")
    with pytest.raises(InvitationError):
        create_or_refresh_invitation(
            email="taken@school.edu", role=STUDENT, invited_by=None
        )
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_existing_inactive_account_is_rejected(mailoutbox):
    User.objects.create_user(
        username="gone", email="gone@school.edu", is_active=False
    )
    with pytest.raises(InvitationError):
        create_or_refresh_invitation(
            email="gone@school.edu", role=STUDENT, invited_by=None
        )


@pytest.mark.django_db
def test_existing_account_check_precedes_pending_refresh(mailoutbox):
    # An email with BOTH a pending invite AND a registered account is rejected,
    # not refreshed.
    User.objects.create_user(username="dup", email="dup@school.edu")
    Invitation.objects.create(email="dup@school.edu", role=STUDENT)
    with pytest.raises(InvitationError):
        create_or_refresh_invitation(
            email="dup@school.edu", role=TEACHER, invited_by=None
        )


@pytest.mark.django_db
def test_pending_invite_is_refreshed_with_new_role(mailoutbox):
    pa = User.objects.create_user(username="pa2")
    first = Invitation.objects.create(email="p@school.edu", role=STUDENT)
    inv, created = create_or_refresh_invitation(
        email="p@school.edu", role=COURSE_ADMIN, invited_by=pa
    )
    assert created is False
    assert inv.pk == first.pk
    assert inv.role == COURSE_ADMIN
    assert inv.invited_by == pa
    assert len(mailoutbox) == 1  # refresh sends explicitly (not a create)


@pytest.mark.django_db
def test_revoke_deletes_the_row():
    inv = Invitation.objects.create(email="r@school.edu")
    revoke_invitation(inv)
    assert not Invitation.objects.filter(pk=inv.pk).exists()


@pytest.mark.django_db
def test_resend_refreshes_expiry_and_sends(mailoutbox):
    from django.utils import timezone

    inv = Invitation.objects.create(email="s@school.edu")
    near = timezone.now()
    inv.expires_at = near  # deliberately lower it to ~now
    inv.save(update_fields=["expires_at"])
    resend_invitation(inv)
    inv.refresh_from_db()
    assert inv.expires_at > near  # refreshed forward from the lowered value
    assert len(mailoutbox) == 1
```

> `mailoutbox` is pytest-django's built-in fixture capturing `django.core.mail` sends.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_invitation_services.py -v`
Expected: FAIL (`ImportError`: create_or_refresh_invitation etc.).

- [ ] **Step 3: Add the services**

In `accounts/services.py`, add imports:

```python
from django.utils import timezone

from accounts.invitations import send_invitation_email
from accounts.models import INVITE_TTL
from accounts.models import Invitation
from accounts.provisioning import resolve_user_for_email
```

and append:

```python
class InvitationError(Exception):
    """An invite cannot be sent (e.g. the email already has an account)."""


def create_or_refresh_invitation(*, email, role, invited_by):
    """Send (or refresh + resend) an invite for `email` carrying `role`.

    The existing-account rejection (active OR inactive) is evaluated FIRST, before
    the pending-refresh path, so a registered email is never refreshed into a dead
    invite. resolve_user_for_email is case-insensitive.
    """
    existing = resolve_user_for_email(email)
    if existing is not None:
        if existing.is_active:
            raise InvitationError("An active account already uses this email.")
        raise InvitationError(
            "This email belongs to a deactivated user — reactivate them instead."
        )
    pending = Invitation.find_pending(email)
    if pending is not None:
        pending.role = role
        pending.invited_by = invited_by
        pending.expires_at = timezone.now() + INVITE_TTL
        pending.save(update_fields=["role", "invited_by", "expires_at"])
        # Refresh is NOT a create, so the post_save `send_invitation_on_create`
        # signal does not fire — send explicitly here.
        send_invitation_email(pending)
        return pending, False
    invitation = Invitation.objects.create(email=email, role=role, invited_by=invited_by)
    # Create: the EXISTING post_save `send_invitation_on_create` signal
    # (accounts/signals.py) emails the link via transaction.on_commit. Do NOT call
    # send_invitation_email here, or a new invite is emailed twice (the Django-admin
    # invite path also relies on that signal).
    return invitation, True


def revoke_invitation(invitation):
    """Revoke a pending invite by deleting the row (it carries no user data)."""
    invitation.delete()


def resend_invitation(invitation):
    """Re-send a pending invite, refreshing expiry explicitly (save() won't)."""
    invitation.expires_at = timezone.now() + INVITE_TTL
    invitation.save(update_fields=["expires_at"])
    send_invitation_email(invitation)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_invitation_services.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format accounts/services.py tests/test_invitation_services.py
uv run ruff check accounts/services.py
git add accounts/services.py tests/test_invitation_services.py
git commit -m "feat(5b): invitation services (create-or-refresh, revoke, resend)"
```

---

### Task 7: Users tab — list view, people shell, tabs, nav link

**Files:**
- Create: `accounts/views_manage.py`
- Modify: `accounts/urls.py`
- Create: `templates/accounts/manage/people.html`
- Create: `templates/accounts/manage/_tabs.html`
- Modify: `templates/base.html` (nav link)
- Test: `tests/test_people_users_tab.py` (create)

**Interfaces:**
- Consumes: `accounts.view_user` perm; `institution.roles.ROLE_LABELS/ROLE_NAMES`.
- Produces: URL name `accounts:people` (Users tab, `/manage/people/`); template `accounts/manage/people.html`; reusable `accounts/manage/_tabs.html`. Context keys: `page_obj`, `rows` (list of `{"user", "role_labels"}`), `q`, `role`, `active`, `role_choices`, `tab="users"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_people_users_tab.py`:

```python
import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.models import User
from accounts.services import set_user_role
from institution.roles import PLATFORM_ADMIN, STUDENT, TEACHER, seed_roles
from tests.factories import TEST_PASSWORD, make_verified_user


def make_pa(client, username="pa"):
    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_pa_can_list_users(client):
    make_pa(client, "pa_list")
    target = User.objects.create_user(username="alice", display_name="Alice Liddell")
    set_user_role(target, STUDENT)
    resp = client.get(reverse("accounts:people"))
    assert resp.status_code == 200
    assert "Alice Liddell" in resp.content.decode()


@pytest.mark.django_db
def test_non_pa_is_forbidden(client):
    make_verified_user(username="stu", email="stu@school.edu", password=TEST_PASSWORD)
    client.login(username="stu", password=TEST_PASSWORD)
    resp = client.get(reverse("accounts:people"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_search_filters_by_name(client):
    make_pa(client, "pa_search")
    User.objects.create_user(username="findme", display_name="Findme Smith")
    User.objects.create_user(username="hidden", display_name="Other Person")
    resp = client.get(reverse("accounts:people"), {"q": "Findme"})
    body = resp.content.decode()
    assert "Findme Smith" in body
    assert "Other Person" not in body


@pytest.mark.django_db
def test_role_filter_no_role_bucket(client):
    make_pa(client, "pa_norole")
    roleless = User.objects.create_user(username="roleless", display_name="No Role Ned")
    teacher = User.objects.create_user(username="teach", display_name="Teach Tess")
    set_user_role(teacher, TEACHER)
    resp = client.get(reverse("accounts:people"), {"role": "__none__"})
    body = resp.content.decode()
    assert "No Role Ned" in body
    assert "Teach Tess" not in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_people_users_tab.py -v`
Expected: FAIL (`NoReverseMatch: accounts:people`).

- [ ] **Step 3: Write the view**

Create `accounts/views_manage.py`:

```python
"""Platform-admin People surface: Users + Invitations tabs."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from accounts.models import User
from institution.roles import ROLE_LABELS
from institution.roles import ROLE_NAMES

PAGE_SIZE = 25
NO_ROLE = "__none__"


def _role_labels_for(user):
    """The translatable labels for the role Groups a user holds (0, 1, or more)."""
    return [ROLE_LABELS[g.name] for g in user.groups.all() if g.name in ROLE_NAMES]


@login_required
@permission_required("accounts.view_user", raise_exception=True)
def people(request):
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    active = request.GET.get("active", "all")

    users = User.objects.prefetch_related("groups").order_by(
        "display_name", "email", "username"
    )
    if q:
        users = users.filter(
            Q(display_name__icontains=q)
            | Q(email__icontains=q)
            | Q(username__icontains=q)
        )
    if active == "active":
        users = users.filter(is_active=True)
    elif active == "inactive":
        users = users.filter(is_active=False)
    if role == NO_ROLE:
        users = users.exclude(groups__name__in=ROLE_NAMES)
    elif role in ROLE_NAMES:
        users = users.filter(groups__name=role)
    users = users.distinct()

    page_obj = Paginator(users, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [{"user": u, "role_labels": _role_labels_for(u)} for u in page_obj]

    return render(
        request,
        "accounts/manage/people.html",
        {
            "tab": "users",
            "page_obj": page_obj,
            "rows": rows,
            "q": q,
            "role": role,
            "active": active,
            "role_choices": [(name, ROLE_LABELS[name]) for name in ROLE_NAMES],
            "no_role_value": NO_ROLE,
        },
    )
```

- [ ] **Step 4: Wire the URL**

In `accounts/urls.py`, add the import and route:

```python
from accounts import views_manage
```

```python
    path("manage/people/", views_manage.people, name="people"),
```

- [ ] **Step 5: Create the tabs partial**

Create `templates/accounts/manage/_tabs.html`:

```django
{% load i18n %}
<nav class="manage__tabs" aria-label="{% trans 'People sections' %}">
  <a class="manage__tab{% if tab == 'users' %} is-on{% endif %}"
     href="{% url 'accounts:people' %}">{% trans "Users" %}</a>
  <a class="manage__tab{% if tab == 'invitations' %} is-on{% endif %}"
     href="{% url 'accounts:people_invitations' %}">{% trans "Invitations" %}</a>
</nav>
```

> `accounts:people_invitations` is created in Task 8. This partial is shared; the link resolves once that route exists. Do Task 7 and Task 8 in order.

- [ ] **Step 6: Create the people (Users tab) template**

Create `templates/accounts/manage/people.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "People" %} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% load static %}{% static 'accounts/css/people.css' %}">{% endblock %}
{% block content %}
<section class="manage">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "People" %}</h1>
  </header>

  {% include "accounts/manage/_tabs.html" %}

  <form class="manage__filters" method="get">
    <label class="manage__field"><span>{% trans "Search" %}</span>
      <input type="search" name="q" value="{{ q }}"
             placeholder="{% trans 'Name, email or username' %}">
    </label>
    <label class="manage__field"><span>{% trans "Role" %}</span>
      <select name="role">
        <option value="">{% trans "All roles" %}</option>
        <option value="{{ no_role_value }}" {% if role == no_role_value %}selected{% endif %}>{% trans "No role" %}</option>
        {% for value, label in role_choices %}
          <option value="{{ value }}" {% if role == value %}selected{% endif %}>{{ label }}</option>
        {% endfor %}
      </select>
    </label>
    <label class="manage__field"><span>{% trans "Status" %}</span>
      <select name="active">
        <option value="all" {% if active == "all" %}selected{% endif %}>{% trans "All" %}</option>
        <option value="active" {% if active == "active" %}selected{% endif %}>{% trans "Active" %}</option>
        <option value="inactive" {% if active == "inactive" %}selected{% endif %}>{% trans "Inactive" %}</option>
      </select>
    </label>
    <button class="btn btn--ghost" type="submit">{% trans "Filter" %}</button>
  </form>

  {% if rows %}
    <table class="people-table">
      <thead>
        <tr>
          <th>{% trans "Name" %}</th><th>{% trans "Role" %}</th>
          <th>{% trans "Status" %}</th><th>{% trans "Last login" %}</th><th></th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr>
            <td>{{ row.user }}</td>
            <td>{% if row.role_labels %}{{ row.role_labels|join:", " }}{% else %}<span class="badge">{% trans "— / None" %}</span>{% endif %}</td>
            <td>{% if row.user.is_active %}{% trans "Active" %}{% else %}<span class="badge">{% trans "Inactive" %}</span>{% endif %}</td>
            <td>{% if row.user.last_login %}{{ row.user.last_login|date:"Y-m-d" }}{% else %}{% trans "Never" %}{% endif %}</td>
            <td class="row-actions">
              <a class="btn btn--ghost btn--small" href="{% url 'accounts:user_edit' row.user.pk %}">{% trans "Edit" %}</a>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>

    {% if page_obj.has_other_pages %}
      <nav class="pagination" aria-label="{% trans 'Pagination' %}">
        {% if page_obj.has_previous %}<a class="btn btn--ghost btn--small" href="?{% if q %}q={{ q }}&{% endif %}{% if role %}role={{ role }}&{% endif %}{% if active %}active={{ active }}&{% endif %}page={{ page_obj.previous_page_number }}">{% trans "Previous" %}</a>{% endif %}
        <span class="pagination__status">{% blocktrans with n=page_obj.number total=page_obj.paginator.num_pages %}Page {{ n }} of {{ total }}{% endblocktrans %}</span>
        {% if page_obj.has_next %}<a class="btn btn--ghost btn--small" href="?{% if q %}q={{ q }}&{% endif %}{% if role %}role={{ role }}&{% endif %}{% if active %}active={{ active }}&{% endif %}page={{ page_obj.next_page_number }}">{% trans "Next" %}</a>{% endif %}
      </nav>
    {% endif %}
  {% else %}
    <div class="manage__empty"><p>{% trans "No users match." %}</p></div>
  {% endif %}
</section>
{% endblock %}
```

> The `people.html` and `_tabs.html` templates reference `accounts:user_edit`,
> `accounts:people_invitations`, `accounts:user_deactivate`, and
> `accounts:user_reactivate`, which are fully built in Tasks 8–10. To keep this
> task's tests green standalone, add **all four** People routes now (below),
> pointing at thin stub views; Tasks 8–10 replace only the view BODIES (same names).

In `accounts/urls.py` add (alongside `people`) ALL the People routes now, so every
`{% url %}` in the templates resolves from the start. Tasks 8–10 replace the stub
view BODIES (same names), not the routes:

```python
    path("manage/people/invitations/", views_manage.people_invitations, name="people_invitations"),
    path("manage/people/users/<int:pk>/edit/", views_manage.user_edit, name="user_edit"),
    path("manage/people/users/<int:pk>/deactivate/", views_manage.user_deactivate, name="user_deactivate"),
    path("manage/people/users/<int:pk>/reactivate/", views_manage.user_reactivate, name="user_reactivate"),
```

and add minimal stubs in `accounts/views_manage.py` (replaced fully in Tasks 8/9/10):

```python
from django.http import HttpResponse


@login_required
@permission_required("accounts.view_user", raise_exception=True)
def people_invitations(request):  # fleshed out in Task 8
    return render(request, "accounts/manage/people.html", {"tab": "invitations", "rows": []})


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_edit(request, pk):  # fleshed out in Task 9
    return HttpResponse("")


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_deactivate(request, pk):  # fleshed out in Task 10
    return HttpResponse("")


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_reactivate(request, pk):  # fleshed out in Task 10
    return HttpResponse("")
```

- [ ] **Step 7: Add the nav link**

In `templates/base.html`, in the `app-nav` block (after the Cohorts/Groups links), add:

```django
  {% if perms.accounts.view_user %}
  <a class="app-nav__link" href="{% url 'accounts:people' %}">{% trans "People" %}</a>
  {% endif %}
```

- [ ] **Step 8: Create a placeholder CSS file** (styled fully in Task 11)

Create `accounts/static/accounts/css/people.css` with a single comment line so the `{% static %}` link resolves:

```css
/* Phase 5b People surface — styles added in the styling task. */
```

> Confirm `accounts/` is an app with a `static/` dir convention (mirror `courses/static/courses/css/`). If the project serves app static differently, place the file to match the existing convention found in Task pattern digest.

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/test_people_users_tab.py -v`
Expected: PASS (4 tests).

- [ ] **Step 10: Format, lint, commit**

```bash
uv run ruff format accounts/views_manage.py accounts/urls.py tests/test_people_users_tab.py
uv run ruff check accounts/views_manage.py accounts/urls.py
git add accounts/views_manage.py accounts/urls.py templates/accounts/manage/ templates/base.html accounts/static/accounts/css/people.css tests/test_people_users_tab.py
git commit -m "feat(5b): People Users tab (list, search, role/status filters, pagination) + nav"
```

---

### Task 8: Invitations tab — list + send/revoke/resend

**Files:**
- Modify: `accounts/views_manage.py`
- Modify: `accounts/forms.py`
- Modify: `accounts/urls.py`
- Create: `templates/accounts/manage/invitations.html`
- Test: `tests/test_people_invitations_tab.py` (create)

**Interfaces:**
- Consumes: `accounts.services.create_or_refresh_invitation/revoke_invitation/resend_invitation/InvitationError` (Task 6); `ROLE_CHOICES`.
- Produces: `SendInvitationForm` (email + role, no blank role, default Student); URL names `accounts:people_invitations`, `accounts:invitation_send`, `accounts:invitation_revoke`, `accounts:invitation_resend`. Template `accounts/manage/invitations.html`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_people_invitations_tab.py`:

```python
import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.models import Invitation, User
from institution.roles import PLATFORM_ADMIN, TEACHER, seed_roles
from tests.factories import TEST_PASSWORD, make_verified_user


def make_pa(client, username="pa"):
    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_send_creates_invitation_with_role(
    client, django_capture_on_commit_callbacks, mailoutbox
):
    pa = make_pa(client, "pa_send")
    # The new-invite email is sent by the post_save signal via transaction.on_commit,
    # so capture+execute on_commit callbacks to observe the email under the test.
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("accounts:invitation_send"),
            {"email": "invitee@school.edu", "role": TEACHER},
        )
    assert resp.status_code == 302
    inv = Invitation.objects.get(email="invitee@school.edu")
    assert inv.role == TEACHER
    assert inv.invited_by == pa
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_send_to_existing_account_shows_error(client, mailoutbox):
    make_pa(client, "pa_dup")
    User.objects.create_user(username="taken", email="taken@school.edu")
    resp = client.post(
        reverse("accounts:invitation_send"),
        {"email": "taken@school.edu", "role": "Student"},
    )
    assert resp.status_code == 200  # re-renders with form error
    assert not Invitation.objects.filter(email="taken@school.edu").exists()
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_revoke_deletes_pending(client):
    make_pa(client, "pa_rev")
    inv = Invitation.objects.create(email="rev@school.edu")
    resp = client.post(reverse("accounts:invitation_revoke", args=[inv.pk]))
    assert resp.status_code == 302
    assert not Invitation.objects.filter(pk=inv.pk).exists()


@pytest.mark.django_db
def test_list_shows_pending_invite_with_role(client):
    make_pa(client, "pa_listinv")
    Invitation.objects.create(email="pend@school.edu", role=TEACHER)
    resp = client.get(reverse("accounts:people_invitations"))
    assert resp.status_code == 200
    assert "pend@school.edu" in resp.content.decode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_people_invitations_tab.py -v`
Expected: FAIL (`NoReverseMatch: accounts:invitation_send`).

- [ ] **Step 3: Add the form**

In `accounts/forms.py`, add imports and the form:

```python
from institution.roles import ROLE_CHOICES, STUDENT
```

```python
class SendInvitationForm(forms.Form):
    """Email + role for a new invite. The role select offers the 4 roles (default
    Student) with NO blank option — every invite carries a role."""

    email = forms.EmailField()
    role = forms.ChoiceField(choices=ROLE_CHOICES, initial=STUDENT)
```

- [ ] **Step 4: Add the views**

In `accounts/views_manage.py`, add imports:

```python
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from accounts.forms import SendInvitationForm
from accounts.models import Invitation
from accounts.services import (
    InvitationError,
    create_or_refresh_invitation,
    resend_invitation,
    revoke_invitation,
)
```

Replace the `people_invitations` stub with:

```python
# Localized labels for Invitation.status (the model property returns raw strings).
# gettext_lazy so this module-level dict is not frozen to the import-time language.
STATUS_LABELS = {
    "pending": gettext_lazy("Pending"),
    "accepted": gettext_lazy("Accepted"),
    "expired": gettext_lazy("Expired"),
}


def _render_invitations(request, form):
    qs = Invitation.objects.order_by("-created_at")
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [{"inv": inv, "status_label": STATUS_LABELS[inv.status]} for inv in page_obj]
    return render(
        request,
        "accounts/manage/invitations.html",
        {"tab": "invitations", "rows": rows, "page_obj": page_obj, "form": form},
    )


@login_required
@permission_required("accounts.view_user", raise_exception=True)
def people_invitations(request):
    return _render_invitations(request, SendInvitationForm())


@require_POST
@login_required
@permission_required("accounts.add_user", raise_exception=True)
def invitation_send(request):
    form = SendInvitationForm(request.POST)
    if form.is_valid():
        try:
            create_or_refresh_invitation(
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                invited_by=request.user,
            )
            messages.success(request, _("Invitation sent."))
            return redirect("accounts:people_invitations")
        except InvitationError as exc:
            form.add_error("email", str(exc))
    return _render_invitations(request, form)


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def invitation_revoke(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.status == "pending":
        revoke_invitation(invitation)
        messages.success(request, _("Invitation revoked."))
    return redirect("accounts:people_invitations")


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def invitation_resend(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.status == "pending":
        resend_invitation(invitation)
        messages.success(request, _("Invitation re-sent."))
    return redirect("accounts:people_invitations")
```

- [ ] **Step 5: Wire the URLs**

In `accounts/urls.py`, add:

```python
    path("manage/people/invitations/send/", views_manage.invitation_send, name="invitation_send"),
    path("manage/people/invitations/<int:pk>/revoke/", views_manage.invitation_revoke, name="invitation_revoke"),
    path("manage/people/invitations/<int:pk>/resend/", views_manage.invitation_resend, name="invitation_resend"),
```

- [ ] **Step 6: Create the invitations template**

Create `templates/accounts/manage/invitations.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Invitations" %} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% load static %}{% static 'accounts/css/people.css' %}">{% endblock %}
{% block content %}
<section class="manage">
  <header class="manage__head">
    <h1 class="manage__title">{% trans "People" %}</h1>
  </header>

  {% include "accounts/manage/_tabs.html" %}

  <form class="invite-form" method="post" action="{% url 'accounts:invitation_send' %}">
    {% csrf_token %}
    {{ form.non_field_errors }}
    <label class="manage__field"><span>{% trans "Email" %}</span>{{ form.email }}{{ form.email.errors }}</label>
    <label class="manage__field"><span>{% trans "Role" %}</span>{{ form.role }}</label>
    <button class="btn btn--primary" type="submit">{% trans "Send invitation" %}</button>
  </form>

  {% if rows %}
    <table class="people-table">
      <thead>
        <tr>
          <th>{% trans "Email" %}</th><th>{% trans "Role" %}</th><th>{% trans "Status" %}</th>
          <th>{% trans "Expires" %}</th><th>{% trans "Sent" %}</th><th></th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr>
            <td>{{ row.inv.email }}</td>
            <td>{{ row.inv.get_role_display }}</td>
            <td>{{ row.status_label }}</td>
            <td>{{ row.inv.expires_at|date:"Y-m-d" }}</td>
            <td>{{ row.inv.created_at|date:"Y-m-d" }}</td>
            <td class="row-actions">
              {% if row.inv.status == "pending" %}
                <form method="post" action="{% url 'accounts:invitation_resend' row.inv.pk %}">{% csrf_token %}<button class="btn btn--ghost btn--small" type="submit">{% trans "Resend" %}</button></form>
                <form method="post" action="{% url 'accounts:invitation_revoke' row.inv.pk %}">{% csrf_token %}<button class="btn btn--ghost btn--small" type="submit">{% trans "Revoke" %}</button></form>
              {% endif %}
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>

    {% if page_obj.has_other_pages %}
      <nav class="pagination" aria-label="{% trans 'Pagination' %}">
        {% if page_obj.has_previous %}<a class="btn btn--ghost btn--small" href="?page={{ page_obj.previous_page_number }}">{% trans "Previous" %}</a>{% endif %}
        <span class="pagination__status">{% blocktrans with n=page_obj.number total=page_obj.paginator.num_pages %}Page {{ n }} of {{ total }}{% endblocktrans %}</span>
        {% if page_obj.has_next %}<a class="btn btn--ghost btn--small" href="?page={{ page_obj.next_page_number }}">{% trans "Next" %}</a>{% endif %}
      </nav>
    {% endif %}
  {% else %}
    <div class="manage__empty"><p>{% trans "No invitations yet." %}</p></div>
  {% endif %}
</section>
{% endblock %}
```

> `row.inv.get_role_display` uses Django's auto choices-display, which renders the
> `ROLE_LABELS` label (lazy-translated). `row.status_label` comes from the
> `STATUS_LABELS` (`gettext_lazy`) mapping built in `_render_invitations`, so the
> status is already localized here; Task 12 only supplies the PL `msgstr`s.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_people_invitations_tab.py -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format accounts/views_manage.py accounts/forms.py accounts/urls.py tests/test_people_invitations_tab.py
uv run ruff check accounts/views_manage.py accounts/forms.py accounts/urls.py
git add accounts/views_manage.py accounts/forms.py accounts/urls.py templates/accounts/manage/invitations.html tests/test_people_invitations_tab.py
git commit -m "feat(5b): Invitations tab (send with role, revoke, resend)"
```

---

### Task 9: Edit user — form + view (role/name/email, atomic, demote guard, self-block)

**Files:**
- Modify: `accounts/views_manage.py` (replace the `user_edit` stub)
- Modify: `accounts/forms.py`
- Create: `templates/accounts/manage/user_form.html`
- Test: `tests/test_user_edit.py` (create)

**Interfaces:**
- Consumes: `set_user_role`, `is_last_active_platform_admin` (Tasks 3-4); `reconcile_primary_email`, `verified_email_belongs_to_other`; `ROLE_CHOICES`.
- Produces: `UserEditForm`; the `accounts:user_edit` view (already URL-wired in Task 7).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_user_edit.py`:

```python
import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.models import User
from accounts.services import set_user_role
from institution.roles import PLATFORM_ADMIN, STUDENT, TEACHER, seed_roles
from tests.factories import TEST_PASSWORD, make_verified_user


def make_pa(client, username="pa"):
    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_edit_changes_role(client):
    make_pa(client, "pa_edit")
    target = User.objects.create_user(username="stu", display_name="Stu")
    set_user_role(target, STUDENT)
    resp = client.post(
        reverse("accounts:user_edit", args=[target.pk]),
        {"display_name": "Stu", "email": "", "role": TEACHER},
    )
    assert resp.status_code == 302
    target.refresh_from_db()
    assert list(target.groups.values_list("name", flat=True)) == [TEACHER]
    assert target.is_staff is True


@pytest.mark.django_db
def test_edit_role_less_user_keeps_blank_when_not_chosen(client):
    make_pa(client, "pa_blank")
    roleless = User.objects.create_user(username="root2", display_name="Root")
    resp = client.post(
        reverse("accounts:user_edit", args=[roleless.pk]),
        {"display_name": "Root", "email": "", "role": ""},  # blank "No role"
    )
    assert resp.status_code == 302
    roleless.refresh_from_db()
    assert roleless.groups.count() == 0  # no silent Student assignment


@pytest.mark.django_db
def test_cannot_demote_sole_platform_admin(client):
    seed_roles()
    # Editor is a superuser NOT in the PA group: holds all perms (so the view's
    # permission gate passes), isn't the target, and isn't counted as an active PA.
    editor = User.objects.create_superuser(username="root_ed", password="x")
    client.force_login(editor)
    pa = User.objects.create_user(username="sole_pa")
    set_user_role(pa, PLATFORM_ADMIN)  # the ONLY active Platform Admin
    resp = client.post(
        reverse("accounts:user_edit", args=[pa.pk]),
        {"display_name": "", "email": pa.email or "", "role": STUDENT},
    )
    assert resp.status_code == 200  # re-rendered with a non-field error
    pa.refresh_from_db()
    assert PLATFORM_ADMIN in list(pa.groups.values_list("name", flat=True))


@pytest.mark.django_db
def test_email_uniqueness_case_insensitive(client):
    make_pa(client, "pa_email")
    User.objects.create_user(username="owner", email="owner@school.edu")
    target = User.objects.create_user(username="other", display_name="Other")
    resp = client.post(
        reverse("accounts:user_edit", args=[target.pk]),
        {"display_name": "Other", "email": "Owner@School.edu", "role": ""},
    )
    assert resp.status_code == 200  # re-render with field error
    target.refresh_from_db()
    assert target.email is None or target.email.lower() != "owner@school.edu"


@pytest.mark.django_db
def test_self_role_change_blocked(client):
    pa = make_pa(client, "pa_self")
    resp = client.post(
        reverse("accounts:user_edit", args=[pa.pk]),
        {"display_name": "", "email": pa.email, "role": STUDENT},
    )
    pa.refresh_from_db()
    # role unchanged — still Platform Admin (disabled field discards posted value)
    assert PLATFORM_ADMIN in list(pa.groups.values_list("name", flat=True))
```

> The `test_self_role_change_blocked` test relies on the disabled role field
> discarding the posted value (`forms.Field(disabled=True)`), so the sole PA editing
> themselves never changes role even with a forged POST.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_user_edit.py -v`
Expected: FAIL (the `user_edit` stub returns empty 200; assertions fail).

- [ ] **Step 3: Add the form**

In `accounts/forms.py`, add imports and the form:

```python
from django.db import transaction

from accounts.emails import reconcile_primary_email
from accounts.provisioning import verified_email_belongs_to_other
from accounts.services import (
    is_last_active_platform_admin,
    set_user_role,
)
from institution.roles import PLATFORM_ADMIN
```

```python
class UserEditForm(forms.Form):
    """PA edit of role / display_name / email. is_active is NOT here (button-only).

    Role select has an explicit blank "— No role —" with no implicit default, so a
    role-less/multi-role user is never silently assigned Student. When `editing_self`,
    the role field is disabled server-side (Django disabled=True discards any posted
    value, defeating a forged POST). Email is optional and validated only when
    non-blank (case-insensitive uniqueness + verified-elsewhere guard).
    """

    display_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(required=False)

    def __init__(self, *args, instance, editing_self, **kwargs):
        self.instance = instance
        self.editing_self = editing_self
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [("", _("— No role —"))] + list(ROLE_CHOICES)
        if editing_self:
            self.fields["role"].disabled = True  # discards posted data

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            return ""
        clash = (
            User.objects.filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if clash:
            raise forms.ValidationError(_("Another user already uses this email."))
        if verified_email_belongs_to_other(email, self.instance):
            raise forms.ValidationError(
                _("A verified account elsewhere already owns this email.")
            )
        return email

    def save(self):
        """Apply role + name + email atomically. Demote of the last active PA is
        re-checked under select_for_update inside this transaction; failure raises
        forms.ValidationError (caught by the view -> re-render)."""
        user = self.instance
        new_role = self.cleaned_data.get("role")
        new_email = self.cleaned_data.get("email") or None
        email_changed = (new_email or "") != (user.email or "")
        with transaction.atomic():
            if new_role and not self.editing_self:
                demoting = (
                    PLATFORM_ADMIN in user.groups.values_list("name", flat=True)
                    and new_role != PLATFORM_ADMIN
                )
                if demoting and is_last_active_platform_admin(user, lock=True):
                    raise forms.ValidationError(
                        _("Cannot demote the last active Platform Admin.")
                    )
                set_user_role(user, new_role)
            user.display_name = self.cleaned_data.get("display_name", "")
            user.email = new_email
            user.save(update_fields=["display_name", "email"])
            if email_changed and new_email:
                reconcile_primary_email(user)
        return user
```

> `User` and `ROLE_CHOICES` are imported at the top of `forms.py` already (Task 8 added `ROLE_CHOICES`; add `from accounts.models import User` and `from django.utils.translation import gettext_lazy as _` if not present). Use `gettext_lazy as _` for form-level strings.

- [ ] **Step 4: Replace the `user_edit` view**

In `accounts/views_manage.py`, replace the `user_edit` stub with:

```python
from accounts.forms import UserEditForm


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    editing_self = target.pk == request.user.pk
    if request.method == "POST":
        form = UserEditForm(
            request.POST, instance=target, editing_self=editing_self
        )
        if form.is_valid():
            try:
                form.save()
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, _("User updated."))
                return redirect("accounts:people")
    else:
        initial = {
            "display_name": target.display_name,
            "email": target.email or "",
            "role": _current_role(target),
        }
        form = UserEditForm(initial=initial, instance=target, editing_self=editing_self)
    return render(
        request,
        "accounts/manage/user_form.html",
        {"form": form, "target": target, "editing_self": editing_self},
    )
```

Add the `_current_role` helper and `ValidationError` import in `accounts/views_manage.py`:

```python
from django.core.exceptions import ValidationError


def _current_role(user):
    """The single role name if the user holds exactly one, else "" (role-less/multi)."""
    names = [g.name for g in user.groups.all() if g.name in ROLE_NAMES]
    return names[0] if len(names) == 1 else ""
```

- [ ] **Step 5: Create the edit template**

Create `templates/accounts/manage/user_form.html`:

```django
{% extends "base.html" %}
{% load i18n %}
{% block head_title %}{% trans "Edit user" %} · libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% load static %}{% static 'accounts/css/people.css' %}">{% endblock %}
{% block content %}
<section class="manage">
  <header class="manage__head"><h1 class="manage__title">{% trans "Edit user" %}: {{ target }}</h1></header>
  <form method="post">
    {% csrf_token %}
    {{ form.non_field_errors }}
    <label class="manage__field"><span>{% trans "Display name" %}</span>{{ form.display_name }}{{ form.display_name.errors }}</label>
    <label class="manage__field"><span>{% trans "Email" %}</span>{{ form.email }}{{ form.email.errors }}</label>
    <label class="manage__field"><span>{% trans "Role" %}</span>{{ form.role }}{{ form.role.errors }}
      {% if editing_self %}<small>{% trans "You cannot change your own role." %}</small>{% endif %}
    </label>
    <div class="form__actions">
      <button class="btn btn--primary" type="submit">{% trans "Save" %}</button>
      <a class="btn btn--ghost" href="{% url 'accounts:people' %}">{% trans "Cancel" %}</a>
    </div>
  </form>

  {% comment %} Activation is a guarded button action, not a form field. {% endcomment %}
  <div class="user-activation">
    {% if target.is_active %}
      <form method="post" action="{% url 'accounts:user_deactivate' target.pk %}">{% csrf_token %}<button class="btn btn--danger" type="submit">{% trans "Deactivate" %}</button></form>
    {% else %}
      <form method="post" action="{% url 'accounts:user_reactivate' target.pk %}">{% csrf_token %}<button class="btn" type="submit">{% trans "Reactivate" %}</button></form>
    {% endif %}
  </div>
</section>
{% endblock %}
```

> `accounts:user_deactivate` / `accounts:user_reactivate` are created in Task 10. Build 9→10 in order.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_user_edit.py -v`
Expected: PASS (refine the last-PA test per the note; all green).

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format accounts/views_manage.py accounts/forms.py tests/test_user_edit.py
uv run ruff check accounts/views_manage.py accounts/forms.py
git add accounts/views_manage.py accounts/forms.py templates/accounts/manage/user_form.html tests/test_user_edit.py
git commit -m "feat(5b): edit user (role/name/email, atomic, demote guard, self-block, email reconcile)"
```

---

### Task 10: Deactivate / reactivate views

**Files:**
- Modify: `accounts/views_manage.py`
- Modify: `accounts/urls.py`
- Test: `tests/test_user_activation.py` (create)

**Interfaces:**
- Consumes: `is_last_active_platform_admin` (Task 4).
- Produces: URL names `accounts:user_deactivate`, `accounts:user_reactivate`. Deactivate is guarded (self + last-PA, in-transaction `select_for_update`); reactivate is unguarded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_user_activation.py`:

```python
import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.models import User
from accounts.services import set_user_role
from institution.roles import PLATFORM_ADMIN, STUDENT, seed_roles
from tests.factories import TEST_PASSWORD, make_verified_user


def make_pa(client, username="pa"):
    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_deactivate_a_student(client):
    make_pa(client, "pa_de")
    stu = User.objects.create_user(username="stu")
    set_user_role(stu, STUDENT)
    resp = client.post(reverse("accounts:user_deactivate", args=[stu.pk]))
    assert resp.status_code == 302
    stu.refresh_from_db()
    assert stu.is_active is False


@pytest.mark.django_db
def test_cannot_deactivate_self(client):
    pa = make_pa(client, "pa_self_de")
    resp = client.post(reverse("accounts:user_deactivate", args=[pa.pk]))
    pa.refresh_from_db()
    assert pa.is_active is True  # blocked


@pytest.mark.django_db
def test_cannot_deactivate_sole_platform_admin(client):
    seed_roles()
    # Editor is a superuser NOT in the PA group (has all perms; not the target; not
    # counted as a PA). The target is the only active Platform Admin.
    editor = User.objects.create_superuser(username="root_ed2", password="x")
    client.force_login(editor)
    pa = User.objects.create_user(username="sole_pa2")
    set_user_role(pa, PLATFORM_ADMIN)
    resp = client.post(reverse("accounts:user_deactivate", args=[pa.pk]))
    pa.refresh_from_db()
    assert pa.is_active is True  # blocked: last active Platform Admin


@pytest.mark.django_db
def test_reactivate(client):
    make_pa(client, "pa_re")
    gone = User.objects.create_user(username="gone", is_active=False)
    resp = client.post(reverse("accounts:user_reactivate", args=[gone.pk]))
    assert resp.status_code == 302
    gone.refresh_from_db()
    assert gone.is_active is True
```

> The sole-PA block uses a superuser-non-PA editor (the editor must not be the
> target — self-deactivation is separately blocked — and must not be counted as an
> active PA). The service-layer guard is unit-tested in Task 4.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_user_activation.py -v`
Expected: FAIL — the Task 7 stub `user_deactivate`/`user_reactivate` views return an
empty 200, so the `is_active` assertions fail.

- [ ] **Step 3: Replace the stub views with the real ones**

In `accounts/views_manage.py`, **replace** the `user_deactivate` / `user_reactivate`
stub bodies (from Task 7) with the real guarded views below; remove the now-unused
`from django.http import HttpResponse` import if nothing else uses it:

```python
from django.db import transaction

from accounts.services import is_last_active_platform_admin


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_deactivate(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, _("You cannot deactivate your own account."))
        return redirect("accounts:user_edit", pk=pk)
    with transaction.atomic():
        if is_last_active_platform_admin(target, lock=True):
            messages.error(
                request, _("Cannot deactivate the last active Platform Admin.")
            )
            return redirect("accounts:user_edit", pk=pk)
        target.is_active = False
        target.save(update_fields=["is_active"])
    messages.success(request, _("User deactivated."))
    return redirect("accounts:people")


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_reactivate(request, pk):
    target = get_object_or_404(User, pk=pk)
    target.is_active = True
    target.save(update_fields=["is_active"])
    messages.success(request, _("User reactivated."))
    return redirect("accounts:people")
```

- [ ] **Step 4: URLs already wired**

The `accounts:user_deactivate` / `accounts:user_reactivate` routes already exist
(added with the other People routes in Task 7), so no URL change is needed here.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_user_activation.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full accounts suite to check nothing regressed**

Run: `uv run pytest tests/ -k "people or invitation or user_edit or activation or set_user_role or lockout or accept_role or role_helpers" -v`
Expected: all green.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format accounts/views_manage.py accounts/urls.py tests/test_user_activation.py
uv run ruff check accounts/views_manage.py accounts/urls.py
git add accounts/views_manage.py accounts/urls.py tests/test_user_activation.py
git commit -m "feat(5b): deactivate (guarded) + reactivate user views"
```

---

### Task 11: Styling pass (people.css, light + dark, mobile)

**Files:**
- Modify: `accounts/static/accounts/css/people.css`
- Test: throwaway Playwright screenshot harness (delete after review)

**Interfaces:** none (visual only).

- [ ] **Step 1: Write the styles**

Replace `accounts/static/accounts/css/people.css` with real styles using design tokens (`var(--space-*)`, `var(--border-subtle)`, `var(--primary)`, `var(--text-secondary)`, `var(--text-primary)` — mirror `courses/static/courses/css/editor.css`). Cover: `.manage__tabs` / `.manage__tab` / `.manage__tab.is-on` (tab bar, replicate `.picker__tabs`), `.people-table` (full-width, row hairlines, `tabular-nums` for dates, responsive horizontal scroll on narrow screens), `.invite-form` (inline fields wrap on mobile), `.pagination` / `.pagination__status`, `.user-activation` spacing, and — because they
are **NOT** global in `core/.../app.css` — `.form__actions` (the edit-form button row)
and `.btn--danger` (the Deactivate button) must be defined here too. Example:

```css
.manage__tabs { display: flex; gap: var(--space-2); margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-subtle); }
.manage__tab { padding: var(--space-2) var(--space-3); color: var(--text-secondary);
  border-bottom: 2px solid transparent; text-decoration: none; }
.manage__tab.is-on { color: var(--text-primary); border-bottom-color: var(--primary);
  font-weight: 600; }
.people-table { width: 100%; border-collapse: collapse; }
.people-table th, .people-table td { text-align: left; padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border-subtle); }
.people-table td:last-child { text-align: right; }
.invite-form { display: flex; flex-wrap: wrap; gap: var(--space-3); align-items: flex-end;
  margin-bottom: var(--space-5); }
.pagination { display: flex; gap: var(--space-3); align-items: center; margin-top: var(--space-4); }
.form__actions { display: flex; gap: var(--space-3); margin-top: var(--space-4); }
.user-activation { margin-top: var(--space-5); }
.btn--danger { background: var(--danger, #b3261e); color: #fff; border-color: transparent; }
.btn--danger:hover { filter: brightness(0.95); }
@media (max-width: 640px) {
  .people-table { display: block; overflow-x: auto; }
}
```

> `.form__actions` and `.btn--danger` are NOT defined in the global `app.css` (they
> live only in per-page sheets like `editor.css`/`tags.css`), so this slice must
> ship its own rules — confirm the `--danger` token exists in `app.css`; if not, use
> a literal hex as shown.

- [ ] **Step 2: Screenshot-verify light + dark (throwaway harness)**

Write a throwaway Playwright script in the scratchpad that logs in a PA, visits `/manage/people/`, `/manage/people/invitations/`, and a `user_edit` page, in BOTH light and dark themes, saving PNGs. Review them, self-critique contrast/spacing/mobile (resize to 375px). Then DELETE the harness. (See the "verify UI with screenshots" practice.)

- [ ] **Step 3: Commit**

```bash
uv run ruff format .
git add accounts/static/accounts/css/people.css
git commit -m "style(5b): People surface styling (tabs, table, invite form; light/dark/mobile)"
```

---

### Task 12: i18n (EN/PL) for all new strings

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (regenerated)

**Interfaces:** none.

- [ ] **Step 1: (no code change) confirm all strings are marked for translation**

The role labels (`ROLE_LABELS`, Task 1) and invitation status labels (`STATUS_LABELS`
in `_render_invitations`, Task 8) already use `gettext_lazy`, and all templates use
`{% trans %}`/`{% blocktrans %}`. There is no Python to add here — this task only
extracts and translates. Quickly grep the new templates/modules to confirm no
user-facing string was left unmarked, and fix any that were.

- [ ] **Step 2: Extract messages**

Run: `uv run python manage.py makemessages -l pl -l en`
Expected: new msgids for all the `{% trans %}` / `gettext` strings added in Tasks 7–11.

- [ ] **Step 3: Translate the PL strings**

Edit `locale/pl/LC_MESSAGES/django.po`: fill `msgstr` for every new People/Invitations string (e.g. "People"→"Osoby", "Invitations"→"Zaproszenia", "Send invitation"→"Wyślij zaproszenie", "No role"→"Brak roli", "Deactivate"→"Dezaktywuj", "Reactivate"→"Aktywuj ponownie", "Never"→"Nigdy", role labels Student→"Uczeń" etc. — match existing translations of these terms where already present). **Clear any `#, fuzzy` flags** makemessages added, and grep the new msgids to verify none got a wrong auto-guess.

- [ ] **Step 4: Compile**

Run: `uv run python manage.py compilemessages`
Expected: `django.mo` rebuilt, no errors.

- [ ] **Step 5: Verify a PL render**

Run a quick check (throwaway): set `language="pl"` on a PA and GET `/manage/people/`; assert "Osoby"/"Zaproszenia" appear. Delete the throwaway check.

- [ ] **Step 6: Commit**

```bash
uv run ruff format accounts/views_manage.py
uv run ruff check accounts/views_manage.py
git add locale/ templates/accounts/manage/  # locale/* always; templates only if Step 1 fixed an unmarked string
git commit -m "i18n(5b): EN/PL for People surface + localized invitation status"
```

---

### Task 13: End-to-end test (real gestures)

**Files:**
- Create: `tests/test_e2e_people.py`

**Interfaces:** none.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_people.py` (mirror `tests/test_e2e_subjects.py` harness):

```python
"""Playwright e2e for Phase 5b: PA invites a Teacher, accepts, changes role,
deactivates. Marked `e2e` (run with -m e2e)."""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from accounts.models import Invitation, User
from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from accounts.emails import ensure_verified_primary_email
    from institution.roles import PLATFORM_ADMIN, seed_roles

    seed_roles()
    user = User.objects.create_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(user, f"{username}@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_selector("form[action*='login']", state="detached")


def _logout(page, live_server):
    """Log out via the real allauth logout confirm page (real UI gesture)."""
    page.goto(f"{live_server.url}/accounts/logout/")
    page.get_by_role("button", name="Sign Out").click()
    page.wait_for_url("**/login/**", timeout=5000)


@pytest.mark.django_db(transaction=True)
def test_pa_invites_teacher_then_changes_role_and_deactivates(page, live_server):
    _make_pa_user("e2e_people_pa")
    _login(page, live_server, "e2e_people_pa")

    # Go to People -> Invitations, send a Teacher invite via the real form.
    page.get_by_role("link", name="People").click()
    page.wait_for_url("**/manage/people/")
    page.get_by_role("link", name="Invitations").click()
    page.wait_for_url("**/manage/people/invitations/")
    page.fill("input[name='email']", "newteacher@school.edu")
    page.select_option("select[name='role']", value="Teacher")
    page.get_by_role("button", name="Send invitation").click()
    page.wait_for_load_state("networkidle")
    assert "newteacher@school.edu" in page.content()

    # Log the PA out first: accept_invite redirects an AUTHENTICATED user away and
    # consumes nothing, so the accept form would never render otherwise.
    _logout(page, live_server)

    # Accept the invite as the invitee via the real accept page.
    inv = Invitation.objects.get(email="newteacher@school.edu")
    page.goto(f"{live_server.url}/invite/accept/{inv.token}/")
    page.fill("input[name='username']", "newteacher")
    page.fill("input[name='password']", TEST_PASSWORD)
    page.get_by_role("button", name="Create account").click()  # accept_invite submit label
    page.wait_for_load_state("networkidle")

    newteacher = User.objects.get(username="newteacher")
    assert list(newteacher.groups.values_list("name", flat=True)) == ["Teacher"]

    # The invitee is now logged in; log them out before re-logging in as the PA.
    _logout(page, live_server)

    # Back as PA: change the user's role to Student via the edit form.
    _login(page, live_server, "e2e_people_pa")
    page.goto(f"{live_server.url}/manage/people/users/{newteacher.pk}/edit/")
    page.select_option("select[name='role']", value="Student")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url("**/manage/people/")
    newteacher.refresh_from_db()
    assert list(newteacher.groups.values_list("name", flat=True)) == ["Student"]

    # Deactivate the user via the edit page button.
    page.goto(f"{live_server.url}/manage/people/users/{newteacher.pk}/edit/")
    page.get_by_role("button", name="Deactivate").click()
    page.wait_for_load_state("networkidle")
    newteacher.refresh_from_db()
    assert newteacher.is_active is False
```

> The accept-form submit button is rendered as `{% trans "Create account" %}` in
> `templates/accounts/accept_invite.html`, so the selector uses "Create account".
> Because it goes through `{% trans %}`, run this e2e under the EN locale (default)
> or match the localized label if you switch locales.

- [ ] **Step 2: Run the e2e test**

Run: `uv run pytest tests/test_e2e_people.py -m e2e -v`
Expected: PASS (drives the real invite → accept → role-change → deactivate path).

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_people.py
git commit -m "test(5b): e2e invite->accept->change-role->deactivate (real gestures)"
```

---

### Definition of Done

- [ ] Full suite green: `uv run pytest` (and `uv run pytest -m e2e` for e2e).
- [ ] `uv run ruff check .` clean and `uv run ruff format --check .` clean.
- [ ] `uv run python manage.py makemigrations --check` reports no missing migrations.
- [ ] `uv run python manage.py migrate` then `setup_roles` run clean ("Roles ensured.").
- [ ] `compilemessages` clean; PL strings render; no stray `#, fuzzy`.
- [ ] People surface verified styled in light + dark + mobile (screenshots reviewed, harness deleted).
- [ ] Manual smoke: PA invites a Teacher, accepts, edits role, deactivates; non-PA gets 403 on `/manage/people/`.
```
