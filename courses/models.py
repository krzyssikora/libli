from django.conf import settings
from django.db import models

from courses.constants import COURSE_LANGUAGES


class Subject(models.Model):
    """Admin-only metadata in 1a (no learner-facing surface).

    Gives Course.subject a target."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)

    def __str__(self):
        return self.title


class Course(models.Model):
    VISIBILITY_CHOICES = [("assigned", "Assigned"), ("open", "Open")]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    subject = models.ForeignKey(
        Subject,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="courses",
    )
    language = models.CharField(max_length=5, choices=COURSE_LANGUAGES, default="en")
    overview = models.TextField(blank=True)
    # hook: Course-Admin scoping (inert in 1a — admin-authored).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_courses",
    )
    # hook: 'open'/self-enroll behaviour is Phase 3 (inert in 1a).
    visibility = models.CharField(
        max_length=10, choices=VISIBILITY_CHOICES, default="assigned"
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title
