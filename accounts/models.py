import datetime
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from institution.roles import ROLE_CHOICES
from institution.roles import STUDENT


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
    external_id = models.CharField(max_length=64, blank=True, default="")
    language = models.CharField(max_length=5, choices=LANG_CHOICES, default="en")
    theme = models.CharField(max_length=5, choices=THEME_CHOICES, default="auto")

    def save(self, *args, **kwargs):
        # Normalize blank email to NULL so the unique constraint ignores it.
        if not self.email:
            self.email = None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name or self.username

    @property
    def sort_name(self):
        """Roster sort key: "Last First" when both structured names exist
        (populated for SSO users via allauth's default given_name/family_name
        mapping), else display_name-or-username. Callers case-fold it. NOTE:
        Python's default string order mis-sorts Polish diacritics (ł/ń/ś/ż land
        after z) — the app does no locale-aware collation anywhere yet."""
        first = (self.first_name or "").strip()
        last = (self.last_name or "").strip()
        if first and last:
            return f"{last} {first}"
        return self.display_name or self.username

    @property
    def list_display_name(self):
        """Human label for rosters/lists: "First Last" when both structured
        names exist, else display_name-or-username (the app-wide convention). A
        display_name carrying extra info (e.g. a nickname) not already shown is
        appended in parens so it isn't lost."""
        first = (self.first_name or "").strip()
        last = (self.last_name or "").strip()
        if first and last:
            label = f"{first} {last}"
        else:
            label = self.display_name or self.username
        display = (self.display_name or "").strip()
        if display and display not in {label, first, last, self.username}:
            label = f"{label} ({display})"
        return label


INVITE_TTL = datetime.timedelta(days=14)


def _generate_invite_token():
    # 32 bytes -> a 43-char URL-safe token. Collisions are negligible; an
    # IntegrityError on the unique constraint would simply propagate (no retry).
    return secrets.token_urlsafe(32)


class Invitation(models.Model):
    """A single-use, expiring invite to self-register under signup_policy == 'invite'.

    Email-bound; accepting it pre-verifies that email and lands the user in the
    invite's `role` (default Student).
    """

    email = models.EmailField()
    role = models.CharField(
        max_length=32,
        choices=ROLE_CHOICES,
        default=STUDENT,
        help_text="Role the invitee lands in on accept.",
    )
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

    @classmethod
    def find_pending(cls, email):
        """The single still-valid invite for `email` to consume on SSO accept:
        case-insensitive, unaccepted, unexpired, most-recently-created first.
        Older pending duplicates are left alone (they expire naturally)."""
        return (
            cls.objects.filter(
                email__iexact=email,
                accepted_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )

    @property
    def status(self):
        if self.accepted_at is not None:
            return "accepted"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"

    def __str__(self):
        return f"{self.email} ({self.status})"
