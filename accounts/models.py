from django.contrib.auth.models import AbstractUser
from django.db import models


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
