from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from demo.constants import LABEL_MAX
from demo.constants import SLUG_MAX


class DemoKit(models.Model):
    """One school representative's demo access.

    `users` is the authority for purging, so nothing depends on a username
    convention at delete time. The row is RETAINED after purge (closed_at set,
    FKs nulled) as a record of who was given a demo and when; it holds no
    credentials.
    """

    class ClosedReason(models.TextChoices):
        EXPIRED = "expired", _("Expired")
        REVOKED = "revoked", _("Revoked")

    label = models.CharField(max_length=LABEL_MAX)
    # NOT unique: a closed kit's row is retained, so a unique slug would
    # permanently block a second demo for the same school. Uniqueness lives on
    # the usernames instead (services._free_base).
    # max_length is SLUG_MAX, not a loose 200: the constant's whole job is to
    # leave room for "-NNN-nauczyciel" inside username's 150, and a column twice
    # the size lets a direct write break that invariant silently.
    slug = models.SlugField(max_length=SLUG_MAX)
    # SET_NULL, not PROTECT. The row is retained for ever (see the class
    # docstring), so PROTECT would mean every closed kit permanently blocks its
    # course from deletion: after a few dozen demos, dropping or replacing
    # mat-pp raises ProtectedError, and neither `revoke` nor `purge` can clear
    # it because neither nulls this FK. `course_slug` below keeps the historical
    # record readable after the course is gone.
    course = models.ForeignKey(
        "courses.Course", on_delete=models.SET_NULL, null=True, blank=True
    )
    # Denormalised at creation so `demo_access list` and the retained row still
    # say WHICH course the demo was for once the FK is nulled.
    course_slug = models.SlugField(max_length=SLUG_MAX, blank=True)
    group = models.ForeignKey(
        "grouping.Group", on_delete=models.SET_NULL, null=True, blank=True
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="demo_kits"
    )
    seed = models.PositiveIntegerField()
    pupil_count = models.PositiveSmallIntegerField()
    frontier_part = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.CharField(
        max_length=16, choices=ClosedReason.choices, blank=True
    )

    class Meta:
        # "Newest first" pinned so the command and PR 3's list cannot drift, and
        # so it never resolves to pk order by accident.
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.label} (#{self.pk})"

    @property
    def status_key(self):
        """Machine-readable status. The TRANSLATED label lives in a display map
        used only by PR 3's tab: a lazily translated property would make
        `demo_access list` follow the process locale."""
        if self.closed_at is not None:
            return f"closed_{self.closed_reason or 'expired'}"
        if self.expires_at <= timezone.now():
            return "pending_purge"
        return "active"
