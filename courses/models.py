from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from courses.constants import COURSE_LANGUAGES
from courses.fields import OrderField


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


class ContentNode(models.Model):
    """Uniform content-tree node: Part / Chapter / Section / Unit.

    Invariant: a child's kind is strictly deeper than its parent's
    (part<chapter<section<unit); units are leaves and the only element-bearing kind.
    Middle levels are author-time optional, so any deeper kind may be a child.
    """

    class Kind(models.TextChoices):
        PART = "part", "Part"
        CHAPTER = "chapter", "Chapter"
        SECTION = "section", "Section"
        UNIT = "unit", "Unit"

    class UnitType(models.TextChoices):
        LESSON = "lesson", "Lesson"
        QUIZ = "quiz", "Quiz"

    RANK = {"part": 0, "chapter": 1, "section": 2, "unit": 3}

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="nodes")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    order = OrderField(for_fields=["course", "parent"], blank=True)
    title = models.CharField(max_length=200)
    unit_type = models.CharField(
        max_length=10, choices=UnitType.choices, null=True, blank=True
    )
    obligatory = models.BooleanField(default=True)  # meaningful only for units
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.title}"

    def clean(self):
        if self.parent is not None:
            if self.parent.course_id != self.course_id:
                raise ValidationError("Parent must belong to the same course.")
            if self.RANK[self.parent.kind] >= self.RANK[self.kind]:
                raise ValidationError(
                    "A node's kind must be strictly deeper than its parent's."
                )
        if self.kind == self.Kind.UNIT:
            if not self.unit_type:
                raise ValidationError("Units require a unit_type.")
        elif self.unit_type:
            raise ValidationError("Only units may have a unit_type.")
        # Re-validate against existing children (admin edits can break the tree).
        if self.pk:
            children = list(self.children.all())
            if self.kind == self.Kind.UNIT and children:
                raise ValidationError("A unit cannot have children.")
            for child in children:
                if self.RANK[self.kind] >= self.RANK[child.kind]:
                    raise ValidationError(
                        "Change would make a child no longer deeper than this node."
                    )
