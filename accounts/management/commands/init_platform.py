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
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.db import transaction

from accounts.emails import ensure_verified_primary_email
from accounts.models import User
from institution.models import Institution
from institution.roles import PLATFORM_ADMIN


def _read_credential(env_name, prompt, secret=False):
    value = os.environ.get(env_name)
    # Strip non-secret credentials (matching the TTY input path); leave secrets
    # untouched since a password may legitimately start or end with whitespace.
    if value and not secret:
        value = value.strip()
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
        password = _read_credential(
            "INIT_ADMIN_PASSWORD", "Admin password", secret=True
        )
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

        # 3. Create or idempotently reconcile the Platform Admin user.
        pa_group = Group.objects.get(name=PLATFORM_ADMIN)
        existing = User.objects.filter(username=username).first()
        if existing is None:
            try:
                with transaction.atomic():
                    user = User.objects.create_superuser(
                        username=username, email=email, password=password
                    )
            except IntegrityError as exc:
                # User.email is unique; a new admin username with an email already
                # used by another account collides here. Surface it cleanly.
                raise CommandError(
                    f"Could not create admin '{username}': {exc}. Is INIT_ADMIN_EMAIL "
                    "already used by another account?"
                ) from exc
            user.groups.add(pa_group)
            self.stdout.write(
                self.style.SUCCESS(f"Created Platform Admin '{username}'.")
            )
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
                self.style.SUCCESS(
                    f"Reconciled existing user '{username}' ({summary})."
                )
            )

        # 4. Pre-verify the admin's email for the allauth front door.
        if user.email:
            try:
                ensure_verified_primary_email(user, user.email)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Platform bootstrap complete."))
