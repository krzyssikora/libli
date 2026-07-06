from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from courses.constants import COURSE_LANGUAGES
from courses.fields import OrderField
from courses.marking import MarkResult
from courses.marking import normalize_text
from courses.marking import parse_number
from courses.sanitize import sanitize_html
from courses.validators import validate_embed_url


class SubjectQuerySet(models.QuerySet):
    def localized_order(self):
        """Order by the active-language title: Polish under PL (falling back to the
        English title for subjects with no Polish name), English otherwise. DB-level
        over the real columns — `title` is a property and cannot be a sort key."""
        if (get_language() or "").startswith("pl"):
            return self.annotate(
                _loc_title=models.Case(
                    models.When(title_pl="", then=models.F("title_en")),
                    default=models.F("title_pl"),
                )
            ).order_by("_loc_title")
        return self.order_by("title_en")


class Subject(models.Model):
    """Course taxonomy: gives Course.subjects its targets.

    Bilingual (EN/PL): `title_en` is required, `title_pl` optional. Read titles
    via the `title` property (resolves the active language, EN fallback) — never
    the raw fields. Curated by the Platform Admin via the bespoke
    /manage/subjects/ UI (Phase 5a); also learner-facing on the self-enrol
    catalog (cards + subject filter, Phase 3b)."""

    title_en = models.CharField(max_length=200)
    title_pl = models.CharField(max_length=200, blank=True)
    slug = models.SlugField(max_length=200, unique=True)

    objects = SubjectQuerySet.as_manager()

    class Meta:
        # Default sort uses a real column (the localized `title` is a property,
        # unusable as DB ordering). List views that need locale-aware order opt
        # into SubjectQuerySet.localized_order() (PL-title order under PL); this
        # Meta default is the fallback for plain querysets.
        ordering = ["title_en"]

    @property
    def title(self):
        if (get_language() or "").startswith("pl") and self.title_pl:
            return self.title_pl
        return self.title_en

    @property
    def title_alt(self):
        """Secondary 'other-language' title for the management list.

        The list leads with the active-language `title`; this is the reference
        in the other language — the English title under PL, the Polish title
        under EN. Empty when there is nothing extra to show (PL blank, or PL
        active but falling back to EN); the list renders a "—" there, which
        doubles as the "no Polish name yet" signal."""
        if (get_language() or "").startswith("pl"):
            return self.title_en if self.title_pl else ""
        return self.title_pl

    def __str__(self):
        return self.title


def _delete_element_content_objects(elements):
    """Delete the concrete content_object of each Element in `elements`.

    Concrete element models reach the content tree only through the Element GFK
    join, which DB cascade cannot traverse — so deleting a Course or a node
    subtree would orphan every concrete element row (and, for Image/Video/Drag
    elements, hit ProtectedError on their PROTECT FK to a cascade-deleted
    MediaAsset). Deleting each content_object cascades its own Element join via
    the model's GenericRelation. Callers must invoke this BEFORE super().delete()
    — a ProtectedError is raised at cascade-collect time, before pre_delete.
    """
    for element in elements.prefetch_related("content_object"):
        obj = element.content_object
        if obj is not None:
            obj.delete()


class Course(models.Model):
    VISIBILITY_CHOICES = [("assigned", "Assigned"), ("open", "Open")]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    subjects = models.ManyToManyField(Subject, blank=True, related_name="courses")
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
    # Phase 3b: which cohorts may self-enroll when visibility="open".
    # Empty set = open to all students (see grouping.services.catalog_courses_for).
    # String ref avoids importing grouping (grouping.models already string-refs Course).
    self_enroll_cohorts = models.ManyToManyField(
        "grouping.Cohort", blank=True, related_name="self_enroll_courses"
    )
    external_id = models.CharField(max_length=64, blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    html_css = models.TextField(blank=True)
    html_js = models.TextField(blank=True)
    # Per-course structure (depth) policy. True = that optional level is offered
    # in the builder; `unit` is always present (mandatory leaf). Defaults = Full
    # reproduce today's part>chapter>section>unit depth (backward-safe). Edited
    # only via CourseForm's preset picker, never as raw checkboxes.
    uses_parts = models.BooleanField(default=True)
    uses_chapters = models.BooleanField(default=True)
    uses_sections = models.BooleanField(default=True)
    # Phase 3c-ii: per-course analytics color bands (5-band threshold table).
    # Empty list = use courses.color_bands.default_color_bands(); validated &
    # read through courses.color_bands.course_color_bands(). Stored mins are
    # JSON ints (a plain JSONField can't serialize Decimal).
    color_bands = models.JSONField(blank=True, default=list)

    def __str__(self):
        return self.title

    @property
    def allowed_kinds(self):
        """Content kinds this course offers, RANK-ordered, always ending in
        'unit'. Drives the builder + chips and the add-time policy guard."""
        from courses.ordering import kinds_for_flags

        return kinds_for_flags(self.uses_parts, self.uses_chapters, self.uses_sections)

    def delete(self, *args, **kwargs):
        # Remove concrete element rows first (see _delete_element_content_objects):
        # the plain cascade would orphan them and hit ProtectedError on media.
        _delete_element_content_objects(Element.objects.filter(unit__course=self))
        return super().delete(*args, **kwargs)


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

    def _subtree_node_ids(self):
        """This node's pk plus every descendant's, via breadth-first parent walk."""
        ids = [self.pk]
        frontier = [self.pk]
        while frontier:
            children = list(
                ContentNode.objects.filter(parent_id__in=frontier).values_list(
                    "pk", flat=True
                )
            )
            ids.extend(children)
            frontier = children
        return ids

    def delete(self, *args, **kwargs):
        # Remove concrete element rows across the whole subtree first (see
        # _delete_element_content_objects): deleting this node cascades its
        # descendant nodes + their Element joins, but never the concrete element
        # rows, which would otherwise orphan.
        _delete_element_content_objects(
            Element.objects.filter(unit_id__in=self._subtree_node_ids())
        )
        return super().delete(*args, **kwargs)

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
    "shorttextquestionelement",
    "extendedresponsequestionelement",
    "shortnumericquestionelement",
    "fillblankquestionelement",
    "dragfillblankquestionelement",
    "matchpairquestionelement",
    "dragtoimagequestionelement",
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

    @property
    def display_name(self):
        return self.name or self.original_filename

    def __str__(self):
        return f"{self.get_kind_display()}: {self.display_name}"

    def clean(self):
        # Single validation authority for the file (extension + size, by kind),
        # reading the admin-configured effective limits. Skip when no file is set.
        if not self.file:
            return
        from courses.validators import validate_image_file
        from courses.validators import validate_video_file

        if self.kind == self.Kind.IMAGE:
            validate_image_file(self.file)
        else:
            validate_video_file(self.file)


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
    # Pasted <iframe> intrinsic size; drives the render aspect ratio (16:9 fallback
    # when null). Null = unknown (plain-URL paste). Not form fields — captured in
    # IframeElementForm.clean_url.
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    elements = GenericRelation(Element)

    def clean(self):
        validate_embed_url(self.url)

    @property
    def embed_src(self):
        """Render-ready iframe src: the stored URL, plus GeoGebra display sizing
        (``/width/W/height/H``) when dimensions are known, so the applet fills the
        frame at its captured aspect ratio. Non-GeoGebra URLs pass through."""
        from courses.geogebra import geogebra_sized_src

        return geogebra_sized_src(self.url, self.width, self.height)


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

    class MarkingMode(models.TextChoices):
        AUTO = "A", _("Auto-marked")
        NOT_MARKED = "N", _("Not marked")
        REVIEW = "R", _("Requires review")

    stem = models.TextField(blank=True)  # the prompt; rich text, sanitised on save
    explanation = models.TextField(blank=True)  # shown in feedback; sanitised on save
    marking_mode = models.CharField(
        max_length=1, choices=MarkingMode.choices, default=MarkingMode.AUTO
    )
    # null = unlimited attempts; consumed only in quiz units (dormant in lessons).
    max_attempts = models.PositiveSmallIntegerField(null=True, blank=True, default=1)
    max_marks = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.stem = sanitize_html(self.stem)
        self.explanation = sanitize_html(self.explanation)
        super().save(*args, **kwargs)

    REVEAL_TEMPLATE = None  # each concrete type sets its per-type reveal include

    def render(
        self,
        *,
        element=None,
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
        mode="lesson",
        action_url=None,
        feedback_partial="courses/elements/_question_feedback.html",
        quiz_submitted=False,
        locked=False,
        attempts_left=None,
        feedback_html="",
    ):
        name = self._meta.model_name
        unit = element.unit if element is not None else None
        # Lesson default: post to check_answer. Quiz: caller supplies action_url.
        if action_url is None and unit is not None:
            action_url = reverse(
                "courses:check_answer",
                kwargs={
                    "slug": unit.course.slug,
                    "node_pk": unit.pk,
                    "element_pk": element.pk,
                },
            )
        return render_to_string(
            f"courses/elements/{name}.html",
            {
                "el": self,
                "element": element,
                "slug": unit.course.slug if unit is not None else "",
                "node_pk": unit.pk if unit is not None else "",
                "feedback_for_pk": feedback_for_pk,
                "selected_ids": set(selected_ids or ()),
                "submitted_values": submitted_values,
                "mark_result": mark_result,
                "reveal_template": self.REVEAL_TEMPLATE,
                "mode": mode,
                "action_url": action_url,
                "feedback_partial": feedback_partial,
                "quiz_submitted": quiz_submitted,
                "locked": locked,
                "attempts_left": attempts_left,
                "feedback_html": feedback_html,
            },
        )

    def feedback_context(self, mark_result):
        # The dict the JS-fragment check_answer feeds to _question_feedback.html.
        # Shared by all question types; ChoiceQuestionElement overrides to add choices.
        return {
            "el": self,
            "mark_result": mark_result,
            "reveal_template": self.REVEAL_TEMPLATE,
        }

    def mark(self, answer):
        raise NotImplementedError


class ChoiceQuestionElement(QuestionElement):
    """Single- (multiple=False) or multiple-choice (multiple=True) MCQ."""

    multiple = models.BooleanField(default=False)
    elements = GenericRelation(Element)

    REVEAL_TEMPLATE = "courses/elements/_reveal_choice.html"

    def correct_ids(self):
        return frozenset(
            self.choices.filter(is_correct=True).values_list("pk", flat=True)
        )

    def build_answer(self, post):
        # getlist + int-coerce + validate against own choices (logic moved out of
        # the view); foreign/forged ids are dropped, never error-leaking.
        valid = {c.pk for c in self.choices.all()}
        submitted = set()
        for raw in post.getlist("choice"):
            try:
                submitted.add(int(raw))
            except (TypeError, ValueError):
                continue
        return submitted & valid

    def feedback_context(self, mark_result):
        ctx = super().feedback_context(mark_result)
        ctx["choices"] = list(self.choices.all())
        return ctx

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
        submitted_values=None,
        mark_result=None,
        mode="lesson",
        action_url=None,
        feedback_partial="courses/elements/_question_feedback.html",
        quiz_submitted=False,
        locked=False,
        attempts_left=None,
        feedback_html="",
    ):
        # `element` is the Element join-row (carries the unit + pk for the form
        # action and the per-element feedback gate). `submitted_values` is accepted
        # for signature uniformity but unused (choices repopulate from selected_ids).
        choices = list(self.choices.all())
        unit = element.unit if element is not None else None
        if action_url is None and unit is not None:
            action_url = reverse(
                "courses:check_answer",
                kwargs={
                    "slug": unit.course.slug,
                    "node_pk": unit.pk,
                    "element_pk": element.pk,
                },
            )
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
                "reveal_template": self.REVEAL_TEMPLATE,
                "mode": mode,
                "action_url": action_url,
                "feedback_partial": feedback_partial,
                "quiz_submitted": quiz_submitted,
                "locked": locked,
                "attempts_left": attempts_left,
                "feedback_html": feedback_html,
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


def _accepted_lines(blob):
    """Split a newline-delimited accepted-answers blob into non-blank lines."""
    return [ln for ln in (blob or "").splitlines() if ln.strip()]


class ShortTextQuestionElement(QuestionElement):
    """Free-text answer marked by normalized comparison against >=1 accepted lines."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_shorttext.html"

    accepted = models.TextField(blank=True)  # newline-delimited accepted answers
    case_sensitive = models.BooleanField(default=False)
    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.get("answer", "")

    def mark(self, answer):
        lines = _accepted_lines(self.accepted)
        wanted = {normalize_text(a, case_sensitive=self.case_sensitive) for a in lines}
        got = normalize_text(answer, case_sensitive=self.case_sensitive)
        is_correct = got != "" and got in wanted
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal=lines[0] if lines else "",
        )


EXTENDED_RESPONSE_MAX_CHARS = 10_000


class ExtendedResponseQuestionElement(QuestionElement):
    """Long free text: [A] auto-marked by required/forbidden keywords, or
    [R] human-reviewed (Phase 3 queue) / [N] recorded. Single-row, no sub-tables."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_extendedresponse.html"
    required_keywords = models.TextField(blank=True)
    forbidden_keywords = models.TextField(blank=True)
    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.get("answer", "")[:EXTENDED_RESPONSE_MAX_CHARS]

    def mark(self, answer):
        from courses.keywords import mark_keywords

        frac, reveal, correct = mark_keywords(
            answer,
            _accepted_lines(self.required_keywords),
            _accepted_lines(self.forbidden_keywords),
        )
        return MarkResult(correct=correct, fraction=frac, reveal=reveal)

    def feedback_context(self, mark_result):
        # The live reveal always follows a real submit -> answered=True.
        # The results page passes answered=row.answered explicitly instead.
        ctx = super().feedback_context(mark_result)
        ctx["answered"] = True
        return ctx


class ShortNumericQuestionElement(QuestionElement):
    """Numeric answer marked correct iff within an absolute tolerance of value."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_shortnumeric.html"

    value = models.DecimalField(max_digits=20, decimal_places=8)
    tolerance = models.DecimalField(
        max_digits=20, decimal_places=8, default=0, validators=[MinValueValidator(0)]
    )
    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.get("answer", "")

    def mark(self, answer):
        n = parse_number(answer)
        is_correct = n is not None and abs(n - self.value) <= self.tolerance
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal={"value": self.value, "tolerance": self.tolerance},
        )


class FillBlankQuestionElement(QuestionElement):
    """Stem with ordered blank tokens; each gap text-matched against its own answers."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_fillblank.html"

    elements = GenericRelation(Element)

    def build_answer(self, post):
        return post.getlist("blank")

    def mark(self, answer):
        blanks = list(self.blanks.all())
        n = len(blanks)
        vals = list(answer or [])
        vals = (vals + [""] * n)[:n]  # pad short / truncate long → exactly n
        reveal = []
        n_correct = 0
        for i, blank in enumerate(blanks):
            lines = _accepted_lines(blank.accepted)
            wanted = {
                normalize_text(a, case_sensitive=blank.case_sensitive) for a in lines
            }
            got = normalize_text(vals[i], case_sensitive=blank.case_sensitive)
            ok = got != "" and got in wanted
            if ok:
                n_correct += 1
            reveal.append(
                {"index": i, "correct": ok, "accepted": lines[0] if lines else ""}
            )
        fraction = (n_correct / n) if n else 0.0
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=fraction,
            reveal=tuple(reveal),
        )


class Blank(models.Model):
    question = models.ForeignKey(
        FillBlankQuestionElement, on_delete=models.CASCADE, related_name="blanks"
    )
    accepted = models.TextField(blank=True)  # newline-delimited; parsed from {{a|b}}
    case_sensitive = models.BooleanField(default=False)  # reserved: always False in 2b
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.accepted


class DragFillBlankQuestionElement(QuestionElement):
    """Drag tokens into ordered gaps. Marking is per-gap, like fill-blank, but the
    student picks a discrete chip instead of typing. `stem` stores the token-stem
    from fillblank.parse(); each gap's correct token is a DragBlank row."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_dragfill.html"

    distractors = models.TextField(blank=True)  # newline-delimited extra (wrong) tokens
    elements = GenericRelation(Element)

    def expected_tokens(self):
        # Order is load-bearing: expected_tokens()[n] must align with stem gap n
        # (the nth <select name="slot">). DragBlank.order is assigned in builder
        # creation order, which mirrors the stem's marker order — keep that coupling
        # (re-parse the stem when rebuilding rows; never reorder rows independently).
        return [b.correct_token for b in self.dragblanks.all()]

    def build_answer(self, post):
        return post.getlist("slot")

    def mark(self, answer):
        from courses import dnd

        expected = self.expected_tokens()
        pool = dnd.build_pool(self)
        n_correct, reveal = dnd.mark_slots(expected, pool, answer)
        n = len(expected)
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=reveal,
        )


class DragBlank(models.Model):
    question = models.ForeignKey(
        DragFillBlankQuestionElement,
        on_delete=models.CASCADE,
        related_name="dragblanks",
    )
    correct_token = models.CharField(
        max_length=500
    )  # plain text + KaTeX; never sanitised
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.correct_token


class MatchPairQuestionElement(QuestionElement):
    """Match each left label to its right token by drag/select. Marking is per-left,
    against the pair's `right`. `left` labels are targets and never enter the pool."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_matchpair.html"

    distractors = models.TextField(blank=True)  # newline-delimited extra right-items
    elements = GenericRelation(Element)

    def expected_tokens(self):
        # Order is load-bearing: expected_tokens()[n] must align with row n's
        # <select name="slot"> (rendered in self.pairs order). reveal also indexes
        # pairs[n].left by the same position — keep pairs order stable.
        return [p.right for p in self.pairs.all()]

    def build_answer(self, post):
        return post.getlist("slot")

    def mark(self, answer):
        from courses import dnd

        pairs = list(self.pairs.all())
        expected = [p.right for p in pairs]
        pool = dnd.build_pool(self)
        n_correct, reveal = dnd.mark_slots(expected, pool, answer)
        reveal = tuple({**r, "left": pairs[r["index"]].left} for r in reveal)
        n = len(expected)
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=reveal,
        )


class MatchPair(models.Model):
    question = models.ForeignKey(
        MatchPairQuestionElement, on_delete=models.CASCADE, related_name="pairs"
    )
    left = models.CharField(max_length=500)  # target label; plain text + KaTeX
    right = models.CharField(
        max_length=500
    )  # correct token for this left; plain text + KaTeX
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"{self.left} → {self.right}"


ZONE_COORD_EPSILON = 1e-6


class DragToImageQuestionElement(QuestionElement):
    """Drag labels onto author-defined rectangle zones over an image. Marking is
    per-zone via the shared DnD substrate; each zone's correct token is a DragZone
    row. `stem` (inherited) is the optional prompt above the image."""

    REVEAL_TEMPLATE = "courses/elements/_reveal_dragimage.html"

    media = models.ForeignKey(
        "MediaAsset", on_delete=models.PROTECT, limit_choices_to={"kind": "image"}
    )
    alt = models.CharField(max_length=255, blank=True)  # see a11y note in spec §7.2
    distractors = models.TextField(blank=True)  # newline-delimited wrong labels
    elements = GenericRelation(Element)

    def expected_tokens(self):
        # Order is load-bearing: expected_tokens()[n] aligns with zone n (the nth
        # <select name="slot"> and the nth badge). Keep zones order stable.
        return [z.correct_label for z in self.zones.all()]

    def build_answer(self, post):
        return post.getlist("slot")

    def mark(self, answer):
        from courses import dnd

        expected = self.expected_tokens()
        pool = dnd.build_pool(self)
        n_correct, reveal = dnd.mark_slots(expected, pool, answer)
        n = len(expected)
        return MarkResult(
            correct=(n_correct == n and n > 0),
            fraction=(n_correct / n) if n else 0.0,
            reveal=reveal,
        )


class DragZone(models.Model):
    question = models.ForeignKey(
        DragToImageQuestionElement, on_delete=models.CASCADE, related_name="zones"
    )
    correct_label = models.CharField(
        max_length=500
    )  # plain text + KaTeX; never sanitised
    x = models.FloatField()  # left,   fraction 0..1 of image width
    y = models.FloatField()  # top,    fraction 0..1 of image height
    w = models.FloatField()  # width,  fraction 0..1
    h = models.FloatField()  # height, fraction 0..1
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.correct_label

    def clean(self):
        e = ZONE_COORD_EPSILON
        if not (0 <= self.x <= 1 and 0 <= self.y <= 1):
            raise ValidationError(_("Zone position must be within the image."))
        if not (0 < self.w <= 1 and 0 < self.h <= 1):
            raise ValidationError(_("Zone must have a positive size."))
        # round() to 12 d.p. strips float-arithmetic noise (~2e-16) from the
        # sum before comparing, so a zone exactly at the 1.0 boundary (stored
        # as 0.5+ε) does not spuriously trip the overflow check.
        if round(self.x + self.w, 12) > 1 + e or round(self.y + self.h, 12) > 1 + e:
            raise ValidationError(_("Zone must not extend past the image."))


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


class QuizSubmission(models.Model):
    """Per (student, quiz unit). The spine: status + submitted_at are the Phase 3
    deadline-snapshot hook; score/max_score are cached at Finish."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", _("In progress")
        SUBMITTED = "submitted", _("Submitted")

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_submissions",
    )
    unit = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        limit_choices_to={"kind": "unit"},
        related_name="quiz_submissions",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.IN_PROGRESS
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    # Reserved, inert hook for Phase-3 teacher "force-submit" (set by Phase 3 only;
    # 2e never writes it). related_name="+" avoids a reverse-accessor clash with the
    # other AUTH_USER_MODEL FKs (student, QuestionResponse.reviewed_by).
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "unit"], name="uniq_quizsubmission_student_unit"
            )
        ]

    def save(self, *args, **kwargs):
        # Invariant: submitted => submitted_at set, on every write path.
        if self.status == self.Status.SUBMITTED and self.submitted_at is None:
            self.submitted_at = timezone.now()
        super().save(*args, **kwargs)


class QuestionResponse(models.Model):
    """Per (submission, question Element): current student state for one question."""

    submission = models.ForeignKey(
        QuizSubmission, on_delete=models.CASCADE, related_name="responses"
    )
    element = models.ForeignKey(
        Element, on_delete=models.CASCADE, related_name="responses"
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    latest_answer = models.JSONField(null=True, blank=True)
    fraction = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    earned_marks = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    locked = models.BooleanField(default=False)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    review_feedback = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "element"],
                name="uniq_response_submission_element",
            )
        ]


class Attempt(models.Model):
    """One row per submission of a question. fraction/correct null for [N]/[R]."""

    response = models.ForeignKey(
        QuestionResponse, on_delete=models.CASCADE, related_name="attempts"
    )
    n = models.PositiveSmallIntegerField()
    answer = models.JSONField()
    fraction = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    correct = models.BooleanField(null=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["n"]
        constraints = [
            models.UniqueConstraint(
                fields=["response", "n"], name="uniq_attempt_response_n"
            )
        ]
