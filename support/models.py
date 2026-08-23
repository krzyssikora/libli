"""SupportSettings (who may report, where reports go) and IssueReport (one report)."""

import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from courses.validators import SAFE_IMAGE_EXTENSIONS
from support.constants import PAGE_TITLE_MAX_LENGTH
from support.constants import REPORTER_LABEL_MAX_LENGTH
from support.constants import REPORTER_ROLES_MAX_LENGTH
from support.storage import ScreenshotStorage
from support.validators import validate_screenshot_file

DEFAULT_SCREENSHOT_EXT = "png"


def truncate_roles(value):
    """Truncate a comma-joined role snapshot ON A COMMA BOUNDARY.

    A blind slice could store "Course Adm", which role_labels()'s
    raw-name fallback would then faithfully render as a role the user never
    held. The four current roles cannot overflow 200 chars; the cap exists for
    future or renamed Groups, which is exactly the case where a mid-token cut
    would lie.
    """
    if len(value) <= REPORTER_ROLES_MAX_LENGTH:
        return value
    names = value.split(",")
    kept = []
    for name in names:
        candidate = ",".join(kept + [name])
        if len(candidate) > REPORTER_ROLES_MAX_LENGTH:
            break
        kept.append(name)
    return ",".join(kept)


def screenshot_upload_to(instance, filename):
    """screenshots/<YYYY>/<MM>/<uuid4>.<ext> — never any part of the client name.

    upload_to runs from FileField.pre_save on EVERY save, whereas
    validate_screenshot_file only fires under full_clean()/a ModelForm. So the
    extension is clamped here too: the stored name must be safe even on a path
    that skipped validation (a fixture, a management command). A dot-less name
    would otherwise make a naive rsplit return the whole basename.
    """
    ext = PurePosixPath(filename).suffix.lstrip(".").lower()
    if ext not in SAFE_IMAGE_EXTENSIONS:
        ext = DEFAULT_SCREENSHOT_EXT
    now = timezone.now()
    return f"screenshots/{now:%Y}/{now:%m}/{uuid.uuid4().hex}.{ext}"


class SupportSettings(models.Model):
    """Single-row (pk=1) config. Modelled on integrations.WebhookEndpoint.

    READS on a render path MUST use objects.filter(pk=1).first(), never load():
    load()'s get_or_create would write a row during a plain GET. load() is used
    by both POST paths and, deliberately, by the Allowed reporters GET too.
    """

    class Audience(models.TextChoices):
        ADMINS = "admins", _("Platform Admins only")
        COURSE_ADMINS = "course_admins", _("Course Admins and Platform Admins")
        TEACHERS = "teachers", _("Teachers, Course Admins and Platform Admins")
        ALL = "all", _("Everyone, including students")

    audience = models.CharField(
        max_length=16, choices=Audience.choices, default=Audience.ADMINS
    )
    extra_reporters = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="+"
    )
    extra_emails = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class IssueReport(models.Model):
    """One submitted report. reporter_label/reporter_roles are denormalised on
    purpose: this repo hard-deletes and keeps no orphan audit rows, so a report
    whose provenance vanishes with the account tells the PA nothing."""

    class Status(models.TextChoices):
        OPEN = "open", pgettext_lazy("issue report status", "Open")
        RESOLVED = "resolved", pgettext_lazy("issue report status", "Resolved")

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="issue_reports",
    )
    reporter_label = models.CharField(max_length=REPORTER_LABEL_MAX_LENGTH, blank=True)
    reporter_roles = models.CharField(max_length=REPORTER_ROLES_MAX_LENGTH, blank=True)
    description = models.TextField()
    page_url = models.TextField(blank=True)
    page_title = models.CharField(max_length=PAGE_TITLE_MAX_LENGTH, blank=True)
    screenshot = models.ImageField(
        blank=True,
        storage=ScreenshotStorage,
        upload_to=screenshot_upload_to,
        validators=[validate_screenshot_file],
    )
    telemetry = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            # Serves the throttle's per-user count, which would otherwise scan.
            models.Index(fields=["reporter", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        # Truncate here, not only at the call site: a composed
        # "Display Name (username) <email>" can reach ~560 chars (display_name 150 +
        # username 150 + email 254) and Postgres raises DataError on overflow,
        # which would 500 the submission and lose the report.
        self.reporter_label = self.reporter_label[:REPORTER_LABEL_MAX_LENGTH]
        self.reporter_roles = truncate_roles(self.reporter_roles)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Issue report #{self.pk}"
