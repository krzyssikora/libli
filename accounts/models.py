import datetime
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """libli user. Username is the required identifier; email is optional
    (required only on the open self-signup form). See Phase 0 spec §1."""

    LANG_CHOICES = [("en", "English"), ("pl", "Polski")]
    THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("auto", "Auto")]

    # Email is optional but unique when present. Empty input is normalized to
    # NULL in save() so Postgres's unique index ignores it (many emailless users
    # are allowed). INVARIANT: all user creation goes through create_user()/save();
    # do not bulk_create users, which would bypass this normalization.
    email = models.EmailField("email address", blank=True, null=True, unique=True)
    # Optional human-friendly name; falls back to username in __str__.
    display_name = models.CharField(max_length=150, blank=True)
    language = models.CharField(max_length=5, choices=LANG_CHOICES, default="en")
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="auto")

    def save(self, *args, **kwargs):
        # Normalize blank email to NULL so the unique constraint ignores it.
        if not self.email:
            self.email = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.username


INVITE_TTL = datetime.timedelta(days=14)


def _generate_invite_token():
    # 32 bytes -> a 43-char URL-safe token. Collisions are negligible; an
    # IntegrityError on the unique constraint would simply propagate (no retry).
    return secrets.token_urlsafe(32)


class Invitation(models.Model):
    """A single-use, expiring invite to self-register under signup_policy == 'invite'.

    Email-bound; accepting it pre-verifies that email and lands the user as a Student.
    """

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
        if self.expires_at is None:
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
