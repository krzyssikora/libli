from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    class Kind(models.TextChoices):
        QUIZ_NEEDS_REVIEW = "quiz_needs_review", _("Quiz needs review")
        QUIZ_GRADED = "quiz_graded", _("Quiz graded")
        ENROLLED = "enrolled", _("Enrolled in course")

    class TargetType(models.TextChoices):
        SUBMISSION = "submission", _("Quiz submission")
        COURSE = "course", _("Course")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    target_id = models.BigIntegerField()
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(
                fields=["recipient"],
                name="notif_unread_idx",
                condition=Q(read_at__isnull=True),
            ),
        ]

    def __str__(self):
        return f"{self.kind} → {self.recipient_id}"


class NotificationEmailPreference(models.Model):
    """Per-user, per-kind opt-out for notification EMAILS (never gates the in-app
    row). Absence of a row = all-on (see notifications.emails.email_enabled). The
    boolean field names deliberately equal the Notification.Kind values so a kind
    resolves via getattr(pref, kind) with no mapping table."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_email_pref",
    )
    quiz_needs_review = models.BooleanField(default=True)
    quiz_graded = models.BooleanField(default=True)
    enrolled = models.BooleanField(default=True)

    def __str__(self):
        return f"email prefs for {self.user_id}"


class PushSubscription(models.Model):
    """One subscribed browser (PWA C2 spec §2). Delivers only while the login session
    named by session_key is live, authenticated as `user` and remembered (D7, D8)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField(max_length=1024, unique=True)
    p256dh = models.CharField(max_length=128)
    auth = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set on every subscribe upsert; orders the 5-device cap (created_at would keep
    # a re-subscribed endpoint looking old).
    subscribed_at = models.DateTimeField()
    last_success_at = models.DateTimeField(null=True, blank=True)
    session_key = models.CharField(max_length=40, db_index=True)

    def __str__(self):
        return f"push subscription {self.pk} for {self.user_id}"


class NotificationPushPreference(models.Model):
    """Per-user, per-kind opt-out for PUSH (mirrors NotificationEmailPreference).
    Absence of a row = all-on. Field names equal the Notification.Kind values."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_push_pref",
    )
    quiz_needs_review = models.BooleanField(default=True)
    quiz_graded = models.BooleanField(default=True)
    enrolled = models.BooleanField(default=True)

    def __str__(self):
        return f"push prefs for {self.user_id}"
