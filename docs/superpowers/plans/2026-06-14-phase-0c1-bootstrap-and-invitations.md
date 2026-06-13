# Phase 0c‑1 — Platform Bootstrap + Invitations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the two remaining **local** account-origin paths to libli: a one-command `init_platform` bootstrap that mints/reconciles the first Platform Admin, and a bespoke single-use **invite-token** flow (model + admin + auto-email + accept view) powering `signup_policy == "invite"`.

**Architecture:** Build on Plan 0a (custom `accounts.User`, `Institution` singleton, seeded role Groups, `institution.roles` constants, `setup_roles`) and Plan 0b (django-allauth local auth, mandatory email verification, `make_verified_user` test helper). A shared production helper `accounts.emails.ensure_verified_primary_email` pre-verifies emails for both the bootstrap admin and invited users. The invite accept view reuses allauth's own username/password validation (via the account adapter) so invited accounts are identical to open-signup accounts, and consumes the token inside a `transaction.atomic()` + `select_for_update()` block. SSO/JIT (0c‑2) and emailless login (Phase 1) are out of scope.

**Tech Stack:** Python 3.13, Django 5.2, django-allauth 65.18 (`allauth.account`, `django.contrib.sites`), PostgreSQL (psycopg 3), pytest + pytest-django + factory_boy, ruff. Dev email via console backend; tests via locmem backend.

This plan implements [the Phase 0c‑1 spec](../specs/2026-06-13-phase-0c1-bootstrap-and-invitations-design.md), which refines [Phase 0 foundations](../specs/2026-06-13-phase-0-foundations-design.md) §8 (init_platform) and §4 (invite signup path).

---

## Execution environment

The developer machine is **Windows (win32)** with PowerShell as the primary shell, but every
`bash` block in this plan is written for **POSIX sh** and must be run through the **Bash tool /
Git Bash**. Always invoke Python through **`uv run python ...`** (system `python` is 3.11; uv
manages 3.13). PostgreSQL is provisioned from Plan 0a: role `libli` / password `libli` /
database `libli` on `localhost:5432` (the role has `CREATEDB`, so pytest-django builds
`test_libli` itself). Run `uv run ruff format .` before **every** commit so CI's
`ruff format --check` stays green.

**Ruff line length (E501):** `ruff format` does **not** re-wrap comments/docstrings, but
`ruff check` enforces 88 columns on all files. Keep comment/docstring lines ≤88 cols.

**Test password:** reuse Plan 0b's `tests.factories.TEST_PASSWORD` (`"Sup3r!pass9"`), which
clears all four `AUTH_PASSWORD_VALIDATORS`. For `init_platform` the same value is used for
`INIT_ADMIN_PASSWORD`. The `tests/**` ruff per-file-ignore already covers `S105`/`S106`/`S107`.

**`transaction.on_commit` in tests:** the invite-creation email is sent via
`transaction.on_commit`, whose callbacks do **not** run inside pytest-django's default
transaction-wrapped tests. Tests that assert the email use pytest-django's
**`django_capture_on_commit_callbacks(execute=True)`** fixture (shown in Task 6).

## Scope boundary

**In scope (0c‑1):** `accounts.emails.ensure_verified_primary_email`; `init_platform`
(env-first / prompt-fallback creds, idempotent non-destructive reconcile, superuser PA in the
Platform Admin group with a pre-verified email); the `Invitation` model (single-use, expiring,
`secrets.token_urlsafe(32)`); `InvitationAdmin` + a `post_save` auto-email via
`transaction.on_commit`; a dedicated `/invite/accept/<token>/` view that validates the token in
an atomic block, creates the account with allauth-consistent username/password rules, pre-verifies
the invited email, assigns the Student group, consumes the token, and logs the user in.

**Out of scope — deferred:** SSO/social + JIT adapter + "pre-invited email" consumption of
`Invitation` (0c‑2); emailless front-door login (Phase 1); branded/styled accept + invalid
pages, resend-invite UI, role-bearing invitations (0d / Phase 5).

## File Structure

```
accounts/
├── emails.py                              # NEW: ensure_verified_primary_email (shared)
├── models.py                              # + Invitation (INVITE_TTL, token, save(), is_valid, status, __str__)
├── forms.py                               # NEW: AcceptInviteForm (allauth-consistent username/password)
├── invitations.py                         # NEW: INVITE_SUBJECT, build_accept_url, send_invitation_email
├── views.py                               # + accept_invite view
├── urls.py                                # NEW: app_name="accounts"; /invite/accept/<token>/
├── signals.py                             # + post_save Invitation -> on_commit send email
├── admin.py                               # + InvitationAdmin (accept URL read-only)
├── management/commands/init_platform.py   # NEW: bootstrap PA + roles + institution
├── migrations/                            # NEW: Invitation model migration
config/
└── urls.py                                # + include("accounts.urls")
templates/accounts/
├── invite_email.txt                       # NEW: plaintext invite email (accept link)
├── accept_invite.html                     # NEW: minimal accept form (extends base.html)
└── invite_invalid.html                    # NEW: invalid/expired/used/already-registered
tests/
├── factories.py                           # MODIFIED: make_verified_user delegates to accounts.emails
├── test_accounts_emails.py                # NEW: ensure_verified_primary_email
├── test_init_platform.py                  # NEW
└── test_invitations.py                    # NEW
```

---

### Task 1: Shared verified-email helper + factory refactor

**Files:**
- Create: `accounts/emails.py`
- Modify: `tests/factories.py`
- Test: `tests/test_accounts_emails.py`

- [ ] **Step 1: Write the failing tests** — `tests/test_accounts_emails.py`:
```python
import pytest

from accounts.emails import ensure_verified_primary_email
from accounts.models import User
from tests.factories import TEST_PASSWORD


def test_creates_verified_primary_email_row():
    from allauth.account.models import EmailAddress

    user = User.objects.create_user(
        username="amy", email="amy@school.edu", password=TEST_PASSWORD
    )
    addr = ensure_verified_primary_email(user, "amy@school.edu")
    assert addr.verified and addr.primary
    assert EmailAddress.objects.filter(user=user, email="amy@school.edu").count() == 1


def test_forces_verified_primary_on_existing_unverified_row():
    from allauth.account.models import EmailAddress

    user = User.objects.create_user(
        username="bee", email="bee@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(
        user=user, email="bee@school.edu", verified=False, primary=False
    )
    addr = ensure_verified_primary_email(user, "bee@school.edu")
    assert addr.verified and addr.primary


def test_raises_when_email_bound_to_a_different_user():
    other = User.objects.create_user(
        username="cas", email="shared@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(other, "shared@school.edu")
    intruder = User.objects.create_user(
        username="dan", email="dan@school.edu", password=TEST_PASSWORD
    )
    with pytest.raises(ValueError):
        ensure_verified_primary_email(intruder, "shared@school.edu")


def test_does_not_raise_for_unverified_row_on_a_different_user():
    from allauth.account.models import EmailAddress

    other = User.objects.create_user(
        username="eve", email="eve@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(
        user=other, email="shared2@school.edu", verified=False, primary=False
    )
    user = User.objects.create_user(
        username="fox", email="fox@school.edu", password=TEST_PASSWORD
    )
    # An *unverified* row on another user must NOT block (only verified rows do).
    addr = ensure_verified_primary_email(user, "shared2@school.edu")
    assert addr.verified and addr.primary
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_accounts_emails.py -v`
Expected: FAIL — `accounts.emails` does not exist (ImportError / ModuleNotFoundError).

- [ ] **Step 3: Implement the helper** — `accounts/emails.py`:
```python
"""Account email helpers shared by production code (init_platform, the invite
accept view) and the test factory. Kept out of test modules so production code
never imports test helpers."""

from allauth.account.models import EmailAddress


def ensure_verified_primary_email(user, email):
    """Ensure `user` owns a verified, primary allauth EmailAddress for `email`.

    Get-or-creates keyed on (user, email); forces verified=True + primary=True.
    Raises ValueError only if a *verified* row for the same address is already
    bound to a different user (so a caller can never silently re-point another
    account's confirmed email; an unverified row on another user does not block).
    Precondition: callers pass a user without a conflicting existing primary
    address (true for the 0c-1 callers — a fresh invited user and the bootstrap
    admin); this helper does not demote another primary."""
    clash = (
        EmailAddress.objects.filter(email__iexact=email, verified=True)
        .exclude(user=user)
        .first()
    )
    if clash is not None:
        raise ValueError(
            f"Email {email!r} is already bound to a different user (id={clash.user_id})."
        )
    address, _ = EmailAddress.objects.get_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    if not (address.verified and address.primary):
        address.verified = True
        address.primary = True
        address.save()
    return address
```

- [ ] **Step 4: Refactor the test factory to delegate** — in `tests/factories.py`, replace the body of `make_verified_user` that builds the `EmailAddress` so it calls the shared helper. The function becomes:
```python
def make_verified_user(
    username="member", email="member@school.edu", password=TEST_PASSWORD
):
    """Create a user with a *verified, primary* allauth EmailAddress so that, under
    mandatory email verification, they can log in via username OR email. Delegates the
    EmailAddress reconciliation to the shared production helper."""
    from accounts.emails import ensure_verified_primary_email

    user = User.objects.create_user(username=username, email=email, password=password)
    ensure_verified_primary_email(user, email)
    return user
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_accounts_emails.py tests/test_auth_login.py -v`
Expected: PASS — the new helper tests pass AND Plan 0b's login tests still pass (proving the
factory refactor preserved behavior).

- [ ] **Step 6: Run the full suite, format, lint, commit**

```bash
uv run python -m pytest -q
uv run ruff format .
uv run ruff check .
git add accounts/emails.py tests/factories.py tests/test_accounts_emails.py
git commit -m "feat: shared ensure_verified_primary_email helper; factory delegates to it"
```
Expected: full suite green — all previously-passing 0a + 0b tests plus the new
`test_accounts_emails.py` tests.

---

### Task 2: `init_platform` bootstrap command

**Files:**
- Create: `accounts/management/commands/init_platform.py`
- Test: `tests/test_init_platform.py`

> Depends on Task 1's helper, Plan 0a's `setup_roles` command + `institution.roles.PLATFORM_ADMIN`,
> and `Institution.load()`.

- [ ] **Step 1: Write the failing tests** — `tests/test_init_platform.py`:
```python
import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User
from institution.models import Institution
from institution.roles import PLATFORM_ADMIN
from tests.factories import TEST_PASSWORD


def _set_admin_env(monkeypatch, username="boss", email="boss@school.edu"):
    monkeypatch.setenv("INIT_ADMIN_USERNAME", username)
    monkeypatch.setenv("INIT_ADMIN_EMAIL", email)
    monkeypatch.setenv("INIT_ADMIN_PASSWORD", TEST_PASSWORD)


def test_creates_superuser_pa_with_verified_email(monkeypatch):
    from allauth.account.models import EmailAddress

    _set_admin_env(monkeypatch)
    call_command("init_platform")

    user = User.objects.get(username="boss")
    assert user.is_staff and user.is_superuser
    assert user.groups.filter(name=PLATFORM_ADMIN).exists()
    assert EmailAddress.objects.filter(
        user=user, email="boss@school.edu", verified=True, primary=True
    ).exists()
    # Roles + the singleton exist.
    assert Group.objects.filter(name=PLATFORM_ADMIN).exists()
    assert Institution.objects.count() == 1


def test_admin_can_log_in_via_allauth_front_door(client, monkeypatch):
    _set_admin_env(monkeypatch)
    call_command("init_platform")
    response = client.post(
        "/accounts/login/", {"login": "boss", "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
    assert client.session.get("_auth_user_id")


def test_second_run_is_idempotent_and_non_destructive(monkeypatch):
    _set_admin_env(monkeypatch)
    call_command("init_platform")
    # Simulate the admin rotating their password after first bootstrap.
    user = User.objects.get(username="boss")
    user.set_password("R0tated!pass12")
    user.save()
    call_command("init_platform")  # must not raise
    assert User.objects.filter(username="boss").count() == 1
    user.refresh_from_db()
    # Reconcile is non-destructive: the rotated password and email survive.
    assert user.check_password("R0tated!pass12")
    assert user.email == "boss@school.edu"
    # ...while flags + group remain asserted.
    assert user.is_staff and user.is_superuser
    assert user.groups.filter(name=PLATFORM_ADMIN).exists()


def test_reconciles_existing_non_superuser(monkeypatch):
    existing = User.objects.create_user(
        username="boss", email="boss@school.edu", password=TEST_PASSWORD
    )
    assert not existing.is_superuser
    _set_admin_env(monkeypatch)
    call_command("init_platform")
    existing.refresh_from_db()
    assert existing.is_staff and existing.is_superuser
    assert existing.groups.filter(name=PLATFORM_ADMIN).exists()


def test_missing_credentials_noninteractive_raises(monkeypatch):
    monkeypatch.delenv("INIT_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("INIT_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("INIT_ADMIN_PASSWORD", raising=False)
    # pytest's stdin is not a TTY, so missing env must fail fast.
    with pytest.raises(CommandError):
        call_command("init_platform")
    assert not User.objects.filter(is_superuser=True).exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_init_platform.py -v`
Expected: FAIL — `Unknown command: 'init_platform'` (the command does not exist yet).

- [ ] **Step 3: Implement the command** — `accounts/management/commands/init_platform.py`:
```python
"""Bootstrap libli on a fresh database: ensure roles + the Institution singleton
exist, then mint (or idempotently reconcile) the first Platform Admin. Credentials
come from env first (INIT_ADMIN_USERNAME/EMAIL/PASSWORD); missing values are prompted
for only when attached to a TTY, otherwise the command fails fast."""

import getpass
import os
import sys

from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from accounts.emails import ensure_verified_primary_email
from accounts.models import User
from institution.models import Institution
from institution.roles import PLATFORM_ADMIN


def _read_credential(env_name, prompt, secret=False):
    value = os.environ.get(env_name)
    if value:
        return value
    if not sys.stdin.isatty():
        return None
    if secret:
        return getpass.getpass(f"{prompt}: ")
    return input(f"{prompt}: ").strip()


class Command(BaseCommand):
    help = (
        "Ensure roles + the Institution singleton and mint/reconcile the first "
        "Platform Admin (idempotent)."
    )

    def handle(self, *args, **options):
        username = _read_credential("INIT_ADMIN_USERNAME", "Admin username")
        email = _read_credential("INIT_ADMIN_EMAIL", "Admin email")
        password = _read_credential("INIT_ADMIN_PASSWORD", "Admin password", secret=True)
        missing = [
            name
            for name, value in (
                ("INIT_ADMIN_USERNAME", username),
                ("INIT_ADMIN_EMAIL", email),
                ("INIT_ADMIN_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise CommandError(
                "Missing required credential(s): "
                + ", ".join(missing)
                + " (set the env vars or run interactively)."
            )

        # 1. Roles (delegates to the institution-app command; never re-seeds here).
        call_command("setup_roles")
        # 2. Institution singleton (default signup_policy is "invite").
        Institution.load()

        # Validate the password against a constructed (unsaved) user so
        # UserAttributeSimilarityValidator can compare it to the username/email.
        try:
            validate_password(password, User(username=username, email=email))
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc

        pa_group = Group.objects.get(name=PLATFORM_ADMIN)
        existing = User.objects.filter(username=username).first()
        if existing is None:
            user = User.objects.create_superuser(
                username=username, email=email, password=password
            )
            user.groups.add(pa_group)
            self.stdout.write(self.style.SUCCESS(f"Created Platform Admin '{username}'."))
        else:
            # Non-destructive reconcile: never overwrite an existing password/email.
            user = existing
            changes = []
            if not (user.is_staff and user.is_superuser):
                user.is_staff = True
                user.is_superuser = True
                user.save(update_fields=["is_staff", "is_superuser"])
                changes.append("superuser flags")
            if not user.groups.filter(pk=pa_group.pk).exists():
                user.groups.add(pa_group)
                changes.append("Platform Admin group")
            summary = ", ".join(changes) if changes else "nothing to change"
            self.stdout.write(
                self.style.SUCCESS(f"Reconciled existing user '{username}' ({summary}).")
            )

        # 4. Pre-verify the admin's email for the allauth front door.
        if user.email:
            try:
                ensure_verified_primary_email(user, user.email)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Platform bootstrap complete."))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_init_platform.py -v`
Expected: PASS (all five tests).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add accounts/management/commands/init_platform.py tests/test_init_platform.py
git commit -m "feat: init_platform bootstraps roles, institution, and the first Platform Admin"
```

---

### Task 3: `Invitation` model + migration

**Files:**
- Modify: `accounts/models.py`
- Create: `accounts/migrations/000X_invitation.py` (generated)
- Test: `tests/test_invitations.py` (model tests only in this task)

- [ ] **Step 1: Write the failing model tests** — `tests/test_invitations.py`:
```python
import datetime

from django.utils import timezone

from accounts.models import INVITE_TTL, Invitation


def test_token_is_autogenerated_and_unique():
    a = Invitation.objects.create(email="a@school.edu")
    b = Invitation.objects.create(email="b@school.edu")
    assert a.token and b.token and a.token != b.token


def test_expires_at_defaults_to_now_plus_ttl():
    before = timezone.now()
    inv = Invitation.objects.create(email="a@school.edu")
    assert inv.expires_at >= before + INVITE_TTL - datetime.timedelta(seconds=5)
    assert inv.expires_at <= timezone.now() + INVITE_TTL + datetime.timedelta(seconds=5)


def test_is_valid_true_when_fresh():
    inv = Invitation.objects.create(email="a@school.edu")
    assert inv.is_valid()


def test_is_valid_false_when_expired():
    inv = Invitation.objects.create(
        email="a@school.edu", expires_at=timezone.now() - datetime.timedelta(days=1)
    )
    assert not inv.is_valid()


def test_is_valid_false_when_accepted():
    inv = Invitation.objects.create(email="a@school.edu", accepted_at=timezone.now())
    assert not inv.is_valid()


def test_status_string_precedence():
    accepted = Invitation.objects.create(
        email="a@school.edu", accepted_at=timezone.now()
    )
    expired = Invitation.objects.create(
        email="b@school.edu", expires_at=timezone.now() - datetime.timedelta(days=1)
    )
    pending = Invitation.objects.create(email="c@school.edu")
    assert accepted.status == "accepted"
    assert expired.status == "expired"
    assert pending.status == "pending"
    assert str(pending) == "c@school.edu (pending)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_invitations.py -v`
Expected: FAIL — `cannot import name 'Invitation' from 'accounts.models'`.

- [ ] **Step 3: Add the model** — append to `accounts/models.py` (keep the existing `User` model and imports; add these imports at the top if missing: `import datetime`, `import secrets`, `from django.conf import settings`, `from django.utils import timezone`):
```python
INVITE_TTL = datetime.timedelta(days=14)


def _generate_invite_token():
    # 32 bytes -> a 43-char URL-safe token. Collisions are negligible; an
    # IntegrityError on the unique constraint would simply propagate (no retry).
    return secrets.token_urlsafe(32)


class Invitation(models.Model):
    """A single-use, expiring invite to self-register under signup_policy == 'invite'.
    Email-bound; accepting it pre-verifies that email and lands the user as a Student."""

    email = models.EmailField()
    token = models.CharField(
        max_length=64, unique=True, default=_generate_invite_token, editable=False
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invitations_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Compute from now() (NOT created_at, which auto_now_add only fills during
        # the INSERT, so it is None here on first save).
        if not self.expires_at:
            self.expires_at = timezone.now() + INVITE_TTL
        super().save(*args, **kwargs)

    def is_valid(self):
        return self.accepted_at is None and self.expires_at > timezone.now()

    @property
    def status(self):
        if self.accepted_at is not None:
            return "accepted"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"

    def __str__(self):
        return f"{self.email} ({self.status})"
```
> Confirm `accounts/models.py` already imports `from django.db import models` (Plan 0a). Add
> the four new imports listed above only if they aren't already present. `unique=True` on
> `token` already creates the index the spec's "indexed" calls for — do **not** add a redundant
> `db_index=True`.

- [ ] **Step 4: Generate and apply the migration**

```bash
uv run python manage.py makemigrations accounts
uv run python manage.py migrate
```
Expected: a new migration `accounts/migrations/000X_invitation.py` is created and applied.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_invitations.py -v`
Expected: PASS (all six model tests).

- [ ] **Step 6: Confirm migrations in sync, format, lint, commit**

```bash
uv run python manage.py makemigrations --check --dry-run   # expect: No changes detected
uv run ruff format .
uv run ruff check .
git add accounts/models.py accounts/migrations tests/test_invitations.py
git commit -m "feat: Invitation model (single-use, expiring, token-keyed)"
```

---

### Task 4: Accept-invite form, view, URLs, and templates

**Files:**
- Create: `accounts/forms.py`, `accounts/urls.py`, `templates/accounts/accept_invite.html`, `templates/accounts/invite_invalid.html`
- Modify: `accounts/views.py`, `config/urls.py`
- Test: add to `tests/test_invitations.py`

> The accept form reuses allauth's account-adapter `clean_username` (USERNAME_VALIDATORS +
> case-aware uniqueness) and `clean_password` (`AUTH_PASSWORD_VALIDATORS`) so an invited account
> is identical to an open-signup account. Verified against allauth 65.18:
> `get_adapter().clean_username(username)` raises on a taken username;
> `clean_password(password)` runs the validators.

- [ ] **Step 1: Write the failing view tests** — append to `tests/test_invitations.py`:
```python
import pytest

from accounts.models import User
from tests.factories import TEST_PASSWORD


def _make_invite(email="invitee@school.edu", **kwargs):
    return Invitation.objects.create(email=email, **kwargs)


def test_accept_get_renders_form_with_email(client):
    inv = _make_invite()
    response = client.get(f"/invite/accept/{inv.token}/")
    assert response.status_code == 200
    assert b"invitee@school.edu" in response.content


def test_accept_valid_creates_student_logged_in(client):
    inv = _make_invite()
    response = client.post(
        f"/invite/accept/{inv.token}/",
        {"username": "invitee", "password": TEST_PASSWORD},
    )
    assert response.status_code == 302
    assert response["Location"].endswith("/home/")  # LOGIN_REDIRECT_URL resolves to /home/
    user = User.objects.get(username="invitee")
    assert user.groups.filter(name="Student").exists()
    from allauth.account.models import EmailAddress

    assert EmailAddress.objects.filter(
        user=user, email="invitee@school.edu", verified=True, primary=True
    ).exists()
    inv.refresh_from_db()
    assert inv.accepted_at is not None  # token consumed
    assert client.session.get("_auth_user_id")  # logged in


def test_accept_unknown_token_shows_invalid(client):
    response = client.get("/invite/accept/not-a-real-token/")
    assert response.status_code == 200
    assert not User.objects.filter(username="invitee").exists()


def test_accept_expired_token_shows_invalid_no_account(client):
    from django.utils import timezone
    import datetime

    inv = _make_invite(expires_at=timezone.now() - datetime.timedelta(days=1))
    response = client.post(
        f"/invite/accept/{inv.token}/",
        {"username": "invitee", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200  # invalid page, not a redirect
    assert not User.objects.filter(username="invitee").exists()


def test_accept_used_token_cannot_be_reused(client):
    inv = _make_invite()
    client.post(
        f"/invite/accept/{inv.token}/",
        {"username": "invitee", "password": TEST_PASSWORD},
    )
    client.logout()
    response = client.post(
        f"/invite/accept/{inv.token}/",
        {"username": "invitee2", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200  # invalid page
    assert not User.objects.filter(username="invitee2").exists()


def test_accept_email_already_registered_shows_invalid(client):
    from tests.factories import make_verified_user

    make_verified_user(username="existing", email="invitee@school.edu")
    inv = _make_invite(email="invitee@school.edu")
    response = client.get(f"/invite/accept/{inv.token}/")
    assert response.status_code == 200
    assert b"log in" in response.content.lower()
    assert User.objects.count() == 1  # only the pre-seeded "existing" user; none created


def test_accept_when_authenticated_redirects_without_consuming(client):
    from tests.factories import make_verified_user

    member = make_verified_user(username="member", email="member@school.edu")
    client.force_login(member)
    inv = _make_invite()
    response = client.get(f"/invite/accept/{inv.token}/")
    assert response.status_code == 302
    assert response["Location"].endswith("/home/")
    inv.refresh_from_db()
    assert inv.accepted_at is None  # an already-logged-in user consumes nothing


def test_accept_taken_username_rerenders_form_token_unconsumed(client):
    from tests.factories import make_verified_user

    make_verified_user(username="taken", email="someone@school.edu")
    inv = _make_invite()
    response = client.post(
        f"/invite/accept/{inv.token}/",
        {"username": "taken", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200  # form re-rendered with errors
    inv.refresh_from_db()
    assert inv.accepted_at is None  # token not consumed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_invitations.py -k accept -v`
Expected: FAIL — `/invite/accept/<token>/` is not routed yet (404).

- [ ] **Step 3: Create the form** — `accounts/forms.py`:
```python
from allauth.account.adapter import get_adapter
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError


class AcceptInviteForm(forms.Form):
    """Username + password for accepting an invite. Delegates validation to allauth's
    account adapter so invited accounts match open-signup accounts (same username
    case/uniqueness rules and the same password validators — including
    UserAttributeSimilarity against the username + invited email)."""

    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, invited_email=None, **kwargs):
        # The invited email is authoritative (from the Invitation, not the form);
        # it feeds password attribute-similarity validation, mirroring allauth signup.
        self.invited_email = invited_email
        super().__init__(*args, **kwargs)

    def clean_username(self):
        try:
            return get_adapter().clean_username(self.cleaned_data["username"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password:
            # Build a dummy unsaved user (username + invited email) so allauth's
            # clean_password runs UserAttributeSimilarityValidator exactly as the
            # open-signup form does (allauth.account.forms builds the same dummy_user).
            dummy = get_user_model()(
                username=cleaned.get("username") or "", email=self.invited_email or ""
            )
            try:
                get_adapter().clean_password(password, user=dummy)
            except ValidationError as exc:
                self.add_error("password", forms.ValidationError(exc.messages))
        return cleaned
```

- [ ] **Step 4: Add the view** — append to `accounts/views.py` (keep any existing content; add the imports it needs at the top of the file):
```python
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from allauth.account.models import EmailAddress
from allauth.account.utils import perform_login

from accounts.emails import ensure_verified_primary_email
from accounts.forms import AcceptInviteForm
from accounts.models import Invitation, User
from institution.roles import STUDENT


def _email_is_registered(email):
    return (
        EmailAddress.objects.filter(email__iexact=email).exists()
        or User.objects.filter(email__iexact=email).exists()
    )


class _InvitationNoLongerValid(Exception):
    """Raised inside the atomic block when a re-check fails between GET and POST."""


@require_http_methods(["GET", "POST"])
def accept_invite(request, token):
    # An already-authenticated user has no business accepting an invite; send them
    # to their landing page and consume nothing. (Out of the normal invite flow.)
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    invitation = Invitation.objects.filter(token=token).first()
    if invitation is None or not invitation.is_valid():
        return render(request, "accounts/invite_invalid.html", {"reason": "invalid"})
    if _email_is_registered(invitation.email):
        return render(request, "accounts/invite_invalid.html", {"reason": "registered"})

    if request.method == "POST":
        form = AcceptInviteForm(request.POST, invited_email=invitation.email)
        if form.is_valid():
            try:
                user = _consume_and_create(invitation, form)
            except _InvitationNoLongerValid:
                return render(
                    request, "accounts/invite_invalid.html", {"reason": "invalid"}
                )
            except IntegrityError:
                # A concurrent accept may have registered the email or taken the
                # username between our re-check and INSERT. Distinguish the two:
                # an email clash routes to the "already registered" page; otherwise
                # the username is the culprit.
                if _email_is_registered(invitation.email):
                    return render(
                        request, "accounts/invite_invalid.html", {"reason": "registered"}
                    )
                form.add_error("username", "That username is already taken.")
            else:
                # email is sourced server-side from invitation.email, never the POST.
                return perform_login(request, user, email=invitation.email)
    else:
        form = AcceptInviteForm(invited_email=invitation.email)

    return render(
        request,
        "accounts/accept_invite.html",
        {"form": form, "email": invitation.email},
    )


def _consume_and_create(invitation, form):
    """Create the account and consume the token atomically. The invited email is
    authoritative (taken from the locked invitation, never the form)."""
    with transaction.atomic():
        locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
        if not locked.is_valid() or _email_is_registered(locked.email):
            raise _InvitationNoLongerValid
        user = User.objects.create_user(
            username=form.cleaned_data["username"],
            email=locked.email,
            password=form.cleaned_data["password"],
        )
        ensure_verified_primary_email(user, locked.email)
        group, _ = Group.objects.get_or_create(name=STUDENT)
        user.groups.add(group)
        locked.accepted_at = timezone.now()
        locked.save(update_fields=["accepted_at"])
    return user
```
> `perform_login` already returns the redirect response, so the success path returns it directly
> (no separate `redirect(...)` call needed).

- [ ] **Step 5: Create the URLs** — `accounts/urls.py`:
```python
from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("invite/accept/<str:token>/", views.accept_invite, name="accept_invite"),
]
```
And mount it in `config/urls.py` (keep the existing patterns; the invite route lives at site
root, not under allauth's `/accounts/` prefix):
```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz, name="healthz"),
    path("home/", home, name="home"),
    path("", include("accounts.urls")),
    path("accounts/", include("allauth.account.urls")),
]
```
> Add `from django.urls import include` if it is not already imported in `config/urls.py`
> (Plan 0b added it for the allauth include).

- [ ] **Step 6: Create the templates** — `templates/accounts/accept_invite.html`:
```django
{% extends "base.html" %}
{% block head_title %}Accept invitation{% endblock %}
{% block content %}
<h1>Accept your invitation</h1>
<p>Creating an account for <strong>{{ email }}</strong>.</p>
<form method="post">
  {% csrf_token %}
  {{ form.as_p }}
  <button type="submit">Create account</button>
</form>
{% endblock %}
```
`templates/accounts/invite_invalid.html`:
```django
{% extends "base.html" %}
{% block head_title %}Invitation{% endblock %}
{% block content %}
{% if reason == "registered" %}
<p>This email already has an account. Please <a href="/accounts/login/">log in</a>.</p>
{% else %}
<p>This invitation is invalid or has expired.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_invitations.py -v`
Expected: PASS (model tests + all seven accept-flow tests).

- [ ] **Step 8: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add accounts/forms.py accounts/views.py accounts/urls.py config/urls.py templates/accounts tests/test_invitations.py
git commit -m "feat: accept-invite flow (atomic, allauth-consistent, Student-on-accept)"
```

---

### Task 5: Invite email rendering + send helper

**Files:**
- Create: `accounts/invitations.py`, `templates/accounts/invite_email.txt`
- Test: add to `tests/test_invitations.py`

> Depends on Task 4's `accounts:accept_invite` route for `reverse(...)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_invitations.py`:
```python
from django.core import mail

from accounts.invitations import INVITE_SUBJECT, build_accept_url, send_invitation_email


def test_build_accept_url_contains_path_and_token():
    inv = _make_invite()
    url = build_accept_url(inv)
    assert f"/invite/accept/{inv.token}/" in url


def test_send_invitation_email_sends_one_plaintext_message():
    inv = _make_invite(email="newperson@school.edu")
    mail.outbox.clear()
    send_invitation_email(inv)
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.subject == INVITE_SUBJECT
    assert "newperson@school.edu" in message.to
    # Body carries the accept link (path + token); host is example.com in tests.
    assert f"/invite/accept/{inv.token}/" in message.body
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run python -m pytest tests/test_invitations.py -k "accept_url or send_invitation" -v`
Expected: FAIL — `accounts.invitations` does not exist.

- [ ] **Step 3: Implement the helpers** — `accounts/invitations.py`:
```python
"""Invite token URL building and email sending. Host is always taken from the
django.contrib.sites Site (never a request Host header) so the emailed security
link cannot be host-spoofed; the scheme reuses allauth's ACCOUNT_DEFAULT_HTTP_PROTOCOL."""

from allauth.account import app_settings as account_settings
from django.contrib.sites.models import Site
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse

INVITE_SUBJECT = "You're invited to libli"


def build_accept_url(invitation):
    path = reverse("accounts:accept_invite", args=[invitation.token])
    domain = Site.objects.get_current().domain
    scheme = account_settings.DEFAULT_HTTP_PROTOCOL
    return f"{scheme}://{domain}{path}"


def send_invitation_email(invitation):
    body = render_to_string(
        "accounts/invite_email.txt",
        {"invitation": invitation, "accept_url": build_accept_url(invitation)},
    )
    # from_email=None -> DEFAULT_FROM_EMAIL; plaintext only in 0c-1.
    send_mail(INVITE_SUBJECT, body, None, [invitation.email])
```
`templates/accounts/invite_email.txt`:
```django
You have been invited to join libli.

To create your account, open this link:

{{ accept_url }}

This invitation expires on {{ invitation.expires_at }}.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_invitations.py -v`
Expected: PASS (all invitation tests).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format .
uv run ruff check .
git add accounts/invitations.py templates/accounts/invite_email.txt tests/test_invitations.py
git commit -m "feat: invite email rendering + send helper (Site-based URL, plaintext)"
```

---

### Task 6: Admin registration + auto-email on creation

**Files:**
- Modify: `accounts/admin.py`, `accounts/signals.py`
- Test: add to `tests/test_invitations.py`

> The `post_save` receiver lives in `accounts/signals.py` beside Plan 0b's `user_signed_up`
> receiver, which `accounts/apps.py:ready()` already imports — so no `apps.py` change is needed.

- [ ] **Step 1: Write the failing test** — append to `tests/test_invitations.py`:
```python
def test_creating_invitation_sends_email_on_commit(
    django_capture_on_commit_callbacks,
):
    from django.core import mail

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        inv = Invitation.objects.create(email="hook@school.edu")
    assert len(mail.outbox) == 1
    assert "hook@school.edu" in mail.outbox[0].to
    assert f"/invite/accept/{inv.token}/" in mail.outbox[0].body
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/test_invitations.py::test_creating_invitation_sends_email_on_commit -v`
Expected: FAIL — no email is sent (the receiver does not exist yet); `len(mail.outbox) == 0`.

- [ ] **Step 3: Add the receiver** — append to `accounts/signals.py` (keep Plan 0b's
`user_signed_up` receiver and its imports; add these):
```python
from django.db import transaction
from django.db.models.signals import post_save

from accounts.invitations import send_invitation_email
from accounts.models import Invitation


@receiver(post_save, sender=Invitation)
def send_invitation_on_create(sender, instance, created, **kwargs):
    """Email the invite link once, after the row actually commits (so a rolled-back
    admin save sends nothing, and there is no ordering race in tests)."""
    if created:
        transaction.on_commit(lambda: send_invitation_email(instance))
```
> `receiver` is already imported in `accounts/signals.py` from Plan 0b
> (`from django.dispatch import receiver`); reuse it.

- [ ] **Step 4: Register the admin** — `accounts/admin.py` already exists (Plan 0a registered
the `User` model) and already imports `from django.contrib import admin`, so **append** only the
two imports and the `InvitationAdmin` class below (do not re-add the `admin` import):
```python
from accounts.invitations import build_accept_url
from accounts.models import Invitation


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "invited_by", "created_at", "expires_at", "accepted_at")
    readonly_fields = ("token", "created_at", "accepted_at", "accept_url")
    fields = (
        "email",
        "invited_by",
        "expires_at",
        "token",
        "accept_url",
        "created_at",
        "accepted_at",
    )

    @admin.display(description="Accept URL")
    def accept_url(self, obj):
        if not obj.pk:
            return "(available after saving)"
        return build_accept_url(obj)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run python -m pytest tests/test_invitations.py -v`
Expected: PASS (including the on-commit email test).

- [ ] **Step 6: Full Plan-0c‑1 verification**

```bash
uv run ruff format .
uv run ruff check . && uv run ruff format --check .
uv run python -m pytest
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
```
Expected: lint + format pass; **all tests green** (all previously-passing Plan 0a + 0b tests
plus the new bootstrap/invitation tests); `No changes detected`; `System check identified no
issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add accounts/admin.py accounts/signals.py tests/test_invitations.py
git commit -m "feat: InvitationAdmin + auto-email invite on creation (on_commit)"
```

---

## Definition of Done (Plan 0c‑1)

- `uv run python manage.py init_platform` on a fresh DB (env creds) creates a superuser Platform
  Admin in the Platform Admin group with a verified+primary email; the PA can log in via both
  Django admin and the allauth front door. Re-running reconciles idempotently and exits 0.
- Non-interactive `init_platform` with incomplete credentials fails clearly (non-zero, no
  partial admin).
- Creating an `Invitation` (admin/ORM) emails the invitee an accept link; opening a **valid**
  link lets them set username + password and lands them logged-in as a **Student** with a
  pre-verified email; the token is single-use and expires after 14 days.
- Invalid/expired/used tokens and already-registered emails get a generic invalid-invite page;
  no account is created and no failed attempt consumes a token.
- `uv run python -m pytest` is green (all existing 0a + 0b tests plus the new tests);
  `ruff check .` and `ruff format --check .` pass; `makemigrations --check --dry-run` is clean.

**Out of scope (later plans):** SSO/social + `SocialApp` + JIT adapter + "pre-invited email"
consumption of `Invitation` (0c‑2); emailless front-door login (Phase 1); bespoke styling,
resend-invite UI, role-bearing invitations (0d / Phase 5).

---

## Self-Review

- **Spec coverage:** `ensure_verified_primary_email` shared helper + (user,email) key + raise on
  different-user (Task 1) ✓; `init_platform` env-first/prompt-fallback, create_superuser hashing,
  idempotent non-destructive reconcile, setup_roles + Institution.load(), password validation with
  constructed user, pre-verify email (Task 2) ✓; `Invitation` model — token_urlsafe(32),
  expires_at from now() in save(), is_valid(), status precedence, __str__, INVITE_TTL in models.py
  (Task 3) ✓; accept view — atomic + select_for_update re-check (consumed/expired/registered),
  server-side invitation.email, allauth username/password reuse, IntegrityError backstop,
  Student get_or_create, perform_login after the block, require_http_methods GET/POST, app_name +
  root mount, invalid/registered pages (Task 4) ✓; invitations.py — INVITE_SUBJECT, Site-based
  host (never request), ACCOUNT_DEFAULT_HTTP_PROTOCOL scheme, plaintext send, tests assert
  path+token not host (Task 5) ✓; InvitationAdmin read-only accept URL + post_save on_commit
  auto-email (Task 6) ✓. signup_policy default "invite" is a documented post-bootstrap state
  (no code path in 0c‑1 changes it). Sibling-invitation harmlessness is covered by the
  already-registered branch (Task 4 test).
- **Placeholder scan:** none — every code step shows full code; every command shows its expected
  output. No "TBD"/"handle errors"/"similar to Task N".
- **Type/name consistency:** `ensure_verified_primary_email(user, email)` (Tasks 1, 2, 4);
  `Invitation` / `INVITE_TTL` (Tasks 3–6); `is_valid()` / `status` / `token` / `accepted_at`
  (Tasks 3–6); `accounts:accept_invite` route name (Tasks 4, 5); `build_accept_url` /
  `send_invitation_email` / `INVITE_SUBJECT` (Tasks 5, 6); `AcceptInviteForm` (Task 4);
  `institution.roles.PLATFORM_ADMIN` / `STUDENT` constants; `TEST_PASSWORD` from Plan 0b — all
  aligned across tasks.
- **Emailless login NOT built** (deferred to Phase 1); **no SSO/JIT** (deferred to 0c‑2) — both
  correctly absent.
