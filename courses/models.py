from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from courses.constants import COURSE_LANGUAGES
from courses.fields import OrderField
from courses.marking import MarkResult
from courses.sanitize import sanitize_html
from courses.validators import validate_embed_url
from courses.validators import validate_image_size
from courses.validators import validate_video_size


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
    html_css = models.TextField(blank=True)
    html_js = models.TextField(blank=True)

    def __str__(self):
        return self.title


class ContentNode(models.Model):
    """Uniform content-tree node: Part / Chapter / Section / Unit.

    Invariant: a child's kind is strictly deeper than its parent's
    (part<chapter<section<unit); units are leaves and the only element-bearing kind.
    Middle levels are author-time optional, so any deeper kind may be a child.
    """

    class Kind(models.TextChoices):
        PART = "part", _("Part")
        CHAPTER = "chapter", _("Chapter")
        SECTION = "section", _("Section")
        UNIT = "unit", _("Unit")

    class UnitType(models.TextChoices):
        LESSON = "lesson", _("Lesson")
        QUIZ = "quiz", _("Quiz")

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
    html_seed_js = models.TextField(blank=True)  # per-unit seed; dormant on non-units

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


ELEMENT_MODELS = [
    "textelement",
    "imageelement",
    "videoelement",
    "iframeelement",
    "mathelement",
    "htmlelement",
    "choicequestionelement",
]


class Element(models.Model):
    """GFK join-row: an ordered slot in a unit pointing at one concrete element."""

    unit = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="elements",
        limit_choices_to={"kind": "unit"},
    )
    title = models.CharField(max_length=200, blank=True)  # optional author label
    order = OrderField(for_fields=["unit"], blank=True)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        limit_choices_to={"app_label": "courses", "model__in": ELEMENT_MODELS},
    )
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"Element #{self.pk} of {self.unit_id}"


class ElementBase(models.Model):
    """Abstract base: each concrete element renders its own template by convention."""

    class Meta:
        abstract = True

    def render(self):
        name = self._meta.model_name
        return render_to_string(f"courses/elements/{name}.html", {"el": self})


class TextElement(ElementBase):
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)


class MediaAsset(models.Model):
    """Per-course reusable uploaded file (image or video), referenced by elements."""

    class Kind(models.TextChoices):
        IMAGE = "image", _("Image")
        VIDEO = "video", _("Video")

    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="media_assets"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    file = models.FileField(upload_to="courses/media/")
    original_filename = models.CharField(max_length=255)
    name = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    created = models.DateTimeField(auto_now_add=True)

    # Per-kind validators (extension allowlist + size cap), applied in clean()/forms.
    IMAGE_VALIDATORS = [
        FileExtensionValidator(["png", "jpg", "jpeg", "gif", "webp"]),
        validate_image_size,
    ]
    VIDEO_VALIDATORS = [
        FileExtensionValidator(["mp4", "webm", "ogg", "mov"]),
        validate_video_size,
    ]

    @property
    def display_name(self):
        return self.name or self.original_filename

    def __str__(self):
        return f"{self.get_kind_display()}: {self.display_name}"

    def clean(self):
        # Model clean() is the single validation authority for the file (extension +
        # size, by kind). Skip when no file is set (a required-file error is raised by
        # the field/form, not here) so clean() is well-defined on an empty file.
        if not self.file:
            return
        validators = (
            self.IMAGE_VALIDATORS
            if self.kind == self.Kind.IMAGE
            else self.VIDEO_VALIDATORS
        )
        for v in validators:
            v(self.file)


class ImageElement(ElementBase):
    media = models.ForeignKey(
        "MediaAsset", on_delete=models.PROTECT, limit_choices_to={"kind": "image"}
    )
    alt = models.CharField(max_length=255, blank=True)  # empty = decorative (valid)
    figcaption = models.CharField(max_length=255, blank=True)
    elements = GenericRelation(Element)


class VideoElement(ElementBase):
    url = models.URLField(blank=True)  # whitelisted embed URL
    media = models.ForeignKey(
        "MediaAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        limit_choices_to={"kind": "video"},
    )
    elements = GenericRelation(Element)

    def clean(self):
        has_url = bool(self.url)
        has_media = self.media_id is not None
        if has_url == has_media:
            raise ValidationError("Provide exactly one of url or media.")
        if has_url:
            validate_embed_url(self.url)


class IframeElement(ElementBase):
    url = models.URLField(validators=[validate_embed_url])
    title = models.CharField(max_length=255, blank=True)
    elements = GenericRelation(Element)

    def clean(self):
        validate_embed_url(self.url)


class MathElement(ElementBase):
    latex = models.TextField()  # rendered client-side via KaTeX (Task 11)
    elements = GenericRelation(Element)


class HtmlElement(ElementBase):
    html = models.TextField(blank=True)  # raw author HTML/CSS/JS — NOT sanitized
    elements = GenericRelation(Element)

    def render(self, unit, course):
        from django.conf import settings

        from courses import htmlsandbox

        doc = htmlsandbox.build_srcdoc(
            self.html,
            course.html_css,
            course.html_js,
            unit.html_seed_js,
            origin=settings.HTMLEL_SANDBOX_ORIGIN,
        )
        return render_to_string("courses/elements/htmlelement.html", {"doc": doc})


class QuestionElement(ElementBase):
    """Abstract base for all question element types (Phase 2).

    Owns the shared rich-text fields and declares the marking contract. Concrete
    subclasses implement mark(); the server is the sole marking authority.
    """

    stem = models.TextField(blank=True)  # the prompt; rich text, sanitised on save
    explanation = models.TextField(blank=True)  # shown in feedback; sanitised on save

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.stem = sanitize_html(self.stem)
        self.explanation = sanitize_html(self.explanation)
        super().save(*args, **kwargs)

    def mark(self, answer):
        raise NotImplementedError


class ChoiceQuestionElement(QuestionElement):
    """Single- (multiple=False) or multiple-choice (multiple=True) MCQ."""

    multiple = models.BooleanField(default=False)
    elements = GenericRelation(Element)

    def correct_ids(self):
        return frozenset(
            self.choices.filter(is_correct=True).values_list("pk", flat=True)
        )

    def mark(self, answer):
        # `answer` is an already-validated set of this question's choice ids
        # (foreign/forged ids are dropped in check_answer before mark() is called).
        # Single and multi are one uniform rule: exact set equality.
        correct_set = self.correct_ids()
        is_correct = set(answer) == set(correct_set)
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal=correct_set,
        )

    def render(
        self,
        *,
        element=None,
        feedback_for_pk=None,
        selected_ids=frozenset(),
        mark_result=None,
    ):
        # `element` is the Element join-row (carries the unit + pk for the form action
        # and the per-element feedback gate). Mirrors HtmlElement.render's extra args.
        choices = list(self.choices.all())
        unit = element.unit if element is not None else None
        return render_to_string(
            "courses/elements/choicequestion.html",
            {
                "el": self,
                "element": element,
                "choices": choices,
                "slug": unit.course.slug if unit is not None else "",
                "node_pk": unit.pk if unit is not None else "",
                "feedback_for_pk": feedback_for_pk,
                "selected_ids": set(selected_ids or ()),
                "mark_result": mark_result,
            },
        )


class Choice(models.Model):
    question = models.ForeignKey(
        ChoiceQuestionElement, on_delete=models.CASCADE, related_name="choices"
    )
    text = models.CharField(
        max_length=500
    )  # plain text + KaTeX delimiters; never sanitised
    is_correct = models.BooleanField(default=False)
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.text


class Enrollment(models.Model):
    SOURCE_CHOICES = [("manual", "Manual"), ("group", "Group"), ("self", "Self")]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default="manual")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course"], name="uniq_enrollment_student_course"
            )
        ]

    def __str__(self):
        return f"{self.student_id} in {self.course_id}"


class UnitProgress(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="unit_progress"
    )
    unit = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="progress",
        limit_choices_to={"kind": "unit"},
    )
    # Element.pk values (the seen-set)
    seen_element_ids = models.JSONField(default=list)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "unit"], name="uniq_progress_student_unit"
            )
        ]

    def save(self, *args, **kwargs):
        # Invariant: completed => completed_at set, for EVERY write path (incl. admin).
        if self.completed and self.completed_at is None:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)
