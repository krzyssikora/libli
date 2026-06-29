import zlib

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

TAG_NAME_MAX_LEN = 50
TAG_PALETTE = ["teal", "amber", "indigo", "rose", "green", "violet", "slate", "cyan"]
TAG_PALETTE_SIZE = len(TAG_PALETTE)


def default_color_for(name):
    """Process-stable palette default (crc32, NOT salted built-in hash())."""
    return TAG_PALETTE[zlib.crc32(name.encode("utf-8")) % TAG_PALETTE_SIZE]


class Tag(models.Model):
    """A private, reusable, named, colour-coded label one user applies to units."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags"
    )
    name = models.CharField(max_length=TAG_NAME_MAX_LEN)
    color = models.CharField(
        max_length=20, choices=[(k, k) for k in TAG_PALETTE], default=TAG_PALETTE[0]
    )
    units = models.ManyToManyField(
        "courses.ContentNode", through="UnitTag", related_name="tags"
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [Lower("name"), "pk"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "author", name="uniq_tag_author_lower_name"
            )
        ]

    def __str__(self):
        return self.name


class UnitTag(models.Model):
    """Join-row: this tag is on this unit (lesson or quiz)."""

    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name="unit_tags")
    unit = models.ForeignKey(
        "courses.ContentNode",
        on_delete=models.CASCADE,
        related_name="unit_tags",
        limit_choices_to={"kind": "unit"},
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created", "pk"]
        constraints = [
            models.UniqueConstraint("tag", "unit", name="uniq_unittag_tag_unit")
        ]
        indexes = [
            models.Index(fields=["unit"]),
            models.Index(fields=["tag"]),
        ]

    def __str__(self):
        return f"UnitTag(tag={self.tag_id}, unit={self.unit_id})"
