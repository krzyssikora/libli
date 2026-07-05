from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy


class WebhookEndpoint(models.Model):
    """Single-row (pk=1) config for the one outbound endpoint. Holds a secret and
    is read only by the flush command + the settings form — never on the render
    hot path (emit reads it read-only via filter(pk=1).first())."""

    enabled = models.BooleanField(default=False)
    url = models.URLField(blank=True)  # http/https; scheme checked in the form
    secret = models.CharField(max_length=255, blank=True)  # HMAC key, plaintext
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class WebhookDelivery(models.Model):
    """One outbox row = one pending/attempted POST of one finalized result."""

    class Event(models.TextChoices):
        RESULT_FINALIZED = "result_finalized", _("Result finalized")

    class Status(models.TextChoices):
        PENDING = "pending", pgettext_lazy("webhook delivery status", "Pending")
        DELIVERED = "delivered", pgettext_lazy("webhook delivery status", "Delivered")
        DEAD = "dead", pgettext_lazy("webhook delivery status", "Dead")
        SUPERSEDED = (
            "superseded",
            pgettext_lazy("webhook delivery status", "Superseded"),
        )

    event = models.CharField(
        max_length=32, choices=Event.choices, default=Event.RESULT_FINALIZED
    )
    dedupe_key = models.CharField(max_length=128)
    payload = models.JSONField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
            models.Index(fields=["dedupe_key", "status"]),
            models.Index(fields=["-created_at"]),
        ]
        ordering = ["-created_at", "-id"]
