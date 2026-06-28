from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models

NOTE_MAX_LEN = 5000
NOTE_PALETTE_SIZE = 8


class Note(models.Model):
    """A private, plain-text note one user attaches to a content block in a lesson.

    `unit` is the stable page anchor (survives block deletion); `element` is the
    within-page anchor (NULL ⇒ unanchored/orphaned).
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    unit = models.ForeignKey(
        "courses.ContentNode",
        on_delete=models.CASCADE,
        related_name="notes",
        limit_choices_to={"kind": "unit"},
    )
    element = models.ForeignKey(
        "courses.Element",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notes",
    )
    body = models.TextField(validators=[MaxLengthValidator(NOTE_MAX_LEN)])
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created", "pk"]
        indexes = [
            models.Index(fields=["author", "unit"]),
            models.Index(fields=["author", "element"]),
        ]

    def __str__(self):
        return f"Note #{self.pk} by {self.author_id} on unit {self.unit_id}"
